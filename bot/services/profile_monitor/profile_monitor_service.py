# bot/services/profile_monitor/profile_monitor_service.py
"""
Сервис для мониторинга изменений профиля пользователей.

Основные функции:
1. Сохранение снимка профиля при входе в группу
2. Отслеживание изменений имени, username, фото
3. Автомут по критериям:
   - Нет фото + аккаунт младше N дней
   - Нет фото + смена имени + быстрые сообщения
4. Удаление сообщений спаммеров
5. Логирование в журнал группы
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from aiogram import Bot
from aiogram.types import Message, ChatPermissions
from sqlalchemy import select, and_, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models_profile_monitor import (
    ProfileMonitorSettings,
    ProfileSnapshot,
    ProfileChangeLog,
)
from bot.services.pyrogram_client import pyrogram_service
from bot.services.restriction_service import save_restriction
from bot.services.group_journal_service import send_journal_event
from bot.services.redis_conn import redis

# Логгер для модуля
logger = logging.getLogger(__name__)

# Redis ключ для хранения message_id пользователей
# Формат: user_messages:{chat_id}:{user_id} -> список message_id
USER_MESSAGES_KEY_PREFIX = "user_messages"
USER_MESSAGES_TTL = 3600  # 1 час хранения сообщений


# ============================================================
# ФУНКЦИЯ: ТРЕКИНГ СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
async def track_user_message(chat_id: int, user_id: int, message_id: int) -> None:
    """
    Сохраняет message_id пользователя в Redis для последующего удаления.

    Args:
        chat_id: ID группы
        user_id: ID пользователя
        message_id: ID сообщения
    """
    key = f"{USER_MESSAGES_KEY_PREFIX}:{chat_id}:{user_id}"
    try:
        # Добавляем message_id в список (RPUSH добавляет в конец)
        await redis.rpush(key, str(message_id))
        # Обновляем TTL
        await redis.expire(key, USER_MESSAGES_TTL)
        # Ограничиваем размер списка (храним последние 100 сообщений)
        await redis.ltrim(key, -100, -1)
    except Exception as e:
        logger.debug(f"[PROFILE_MONITOR] Failed to track message: {e}")


async def get_tracked_messages(chat_id: int, user_id: int) -> List[int]:
    """
    Получает список message_id пользователя из Redis.

    Args:
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        Список message_id
    """
    key = f"{USER_MESSAGES_KEY_PREFIX}:{chat_id}:{user_id}"
    try:
        messages = await redis.lrange(key, 0, -1)
        return [int(m) for m in messages]
    except Exception as e:
        logger.debug(f"[PROFILE_MONITOR] Failed to get tracked messages: {e}")
        return []


async def clear_tracked_messages(chat_id: int, user_id: int) -> None:
    """
    Очищает сохранённые message_id пользователя.

    Args:
        chat_id: ID группы
        user_id: ID пользователя
    """
    key = f"{USER_MESSAGES_KEY_PREFIX}:{chat_id}:{user_id}"
    try:
        await redis.delete(key)
    except Exception as e:
        logger.debug(f"[PROFILE_MONITOR] Failed to clear tracked messages: {e}")


# ============================================================
# ФУНКЦИЯ: ПОЛУЧЕНИЕ НАСТРОЕК МОНИТОРИНГА
# ============================================================
def _utcnow_naive() -> datetime:
    """Возвращает текущее UTC время без timezone (naive)."""
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_profile_monitor_settings(
    session: AsyncSession,
    chat_id: int,
) -> Optional[ProfileMonitorSettings]:
    """
    Получает настройки мониторинга профиля для группы.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID группы

    Returns:
        ProfileMonitorSettings или None если не настроено
    """
    # Выполняем SELECT запрос к таблице настроек
    stmt = select(ProfileMonitorSettings).where(
        ProfileMonitorSettings.chat_id == chat_id
    )
    # Получаем результат запроса
    result = await session.execute(stmt)
    # Возвращаем одну запись или None
    return result.scalar_one_or_none()


async def create_or_update_settings(
    session: AsyncSession,
    chat_id: int,
    **kwargs,
) -> ProfileMonitorSettings:
    """
    Создаёт или обновляет настройки мониторинга для группы.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID группы
        **kwargs: Поля для обновления

    Returns:
        ProfileMonitorSettings: Созданная или обновлённая запись
    """
    # Ищем существующие настройки
    settings = await get_profile_monitor_settings(session, chat_id)

    if settings:
        # Обновляем существующие настройки
        for key, value in kwargs.items():
            # Проверяем что атрибут существует
            if hasattr(settings, key):
                setattr(settings, key, value)
        # Обновляем время изменения
        settings.updated_at = _utcnow_naive()
    else:
        # Создаём новые настройки
        settings = ProfileMonitorSettings(
            chat_id=chat_id,
            **kwargs,
        )
        session.add(settings)

    # Сохраняем изменения в БД
    await session.commit()
    # Обновляем объект из БД
    await session.refresh(settings)
    # Логируем действие
    logger.info(f"[PROFILE_MONITOR] Settings updated for chat={chat_id}")
    return settings


# ============================================================
# ФУНКЦИЯ: СОЗДАНИЕ СНИМКА ПРОФИЛЯ
# ============================================================
async def create_profile_snapshot(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    has_photo: bool = False,
    photo_id: Optional[str] = None,
    account_age_days: Optional[int] = None,
    is_premium: bool = False,
    photo_age_days: Optional[int] = None,
) -> ProfileSnapshot:
    """
    Создаёт снимок профиля пользователя при входе в группу.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID группы
        user_id: ID пользователя
        first_name: Имя пользователя
        last_name: Фамилия пользователя
        username: Username (@)
        has_photo: Есть ли фото профиля
        photo_id: ID фото профиля
        account_age_days: Возраст аккаунта в днях
        is_premium: Premium аккаунт
        photo_age_days: Возраст самого свежего фото в днях (для критериев 4,5)

    Returns:
        ProfileSnapshot: Созданный снимок
    """
    # Формируем полное имя из first_name и last_name
    full_name = " ".join(filter(None, [first_name, last_name]))

    # Проверяем существующий снимок
    existing = await get_profile_snapshot(session, chat_id, user_id)

    if existing:
        # Обновляем существующий снимок
        existing.first_name = first_name
        existing.last_name = last_name
        existing.full_name = full_name
        existing.username = username
        existing.has_photo = has_photo
        existing.photo_id = photo_id
        existing.account_age_days = account_age_days
        existing.is_premium = is_premium
        # Возраст самого свежего фото в днях (для критериев 4,5)
        existing.photo_age_days = photo_age_days
        # ВАЖНО: Обновляем joined_at при повторном входе (rejoin)
        # Это нужно для правильного расчёта minutes_since_join
        existing.joined_at = _utcnow_naive()
        existing.updated_at = _utcnow_naive()
        await session.commit()
        logger.info(
            f"[PROFILE_MONITOR] Snapshot updated: chat={chat_id} user={user_id} "
            f"name='{full_name}' has_photo={has_photo} photo_age_days={photo_age_days}"
        )
        return existing

    # Создаём новый снимок
    snapshot = ProfileSnapshot(
        chat_id=chat_id,
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        username=username,
        has_photo=has_photo,
        photo_id=photo_id,
        account_age_days=account_age_days,
        is_premium=is_premium,
        # Возраст самого свежего фото в днях (для критериев 4,5)
        photo_age_days=photo_age_days,
        joined_at=_utcnow_naive(),
        updated_at=_utcnow_naive(),
    )
    session.add(snapshot)
    await session.commit()

    logger.info(
        f"[PROFILE_MONITOR] Snapshot created: chat={chat_id} user={user_id} "
        f"name='{full_name}' has_photo={has_photo} age_days={account_age_days} "
        f"photo_age_days={photo_age_days}"
    )
    return snapshot


# ============================================================
# ФУНКЦИЯ: СОЗДАНИЕ СНАПШОТА ПРИ ВХОДЕ В ГРУППУ
# ============================================================
# Вызывается из chat_member handler когда пользователь вступает
# Получает данные профиля через Pyrogram и создаёт/обновляет снапшот
async def create_snapshot_on_join(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    is_premium: bool = False,
) -> Optional[ProfileSnapshot]:
    """
    Создаёт или обновляет снапшот профиля при входе пользователя в группу.

    Вызывается из chat_member_updated handler когда:
    - Пользователь вступает через join request (одобрение капчи)
    - Пользователь приглашён админом/участником
    - Пользователь входит в открытую группу

    ВАЖНО: При повторном входе (rejoin) старый снапшот ПЕРЕЗАПИСЫВАЕТСЯ
    новыми данными профиля. Это нужно для правильного отслеживания изменений.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID группы
        user_id: ID пользователя
        first_name: Имя пользователя (из Telegram события)
        last_name: Фамилия пользователя (из Telegram события)
        username: Username пользователя (из Telegram события)
        is_premium: Premium статус (из Telegram события)

    Returns:
        ProfileSnapshot: Созданный или обновлённый снапшот, None при ошибке
    """
    try:
        # Проверяем включен ли модуль Profile Monitor для этой группы
        settings = await get_profile_monitor_settings(session, chat_id)
        # Если настроек нет или модуль выключен — не создаём снапшот
        if not settings or not settings.enabled:
            logger.debug(
                f"[PROFILE_MONITOR] Skip snapshot on join: chat={chat_id} "
                f"user={user_id} (module disabled)"
            )
            return None

        # Получаем данные профиля через Pyrogram (фото, возраст аккаунта)
        # Эта функция безопасна — возвращает пустые данные если Pyrogram недоступен
        profile_data = await get_user_profile_data(user_id)
        # Извлекаем данные о фото профиля
        has_photo = profile_data.get("has_photo", False)
        # Извлекаем возраст аккаунта в днях
        account_age_days = profile_data.get("account_age_days")
        # Извлекаем возраст самого свежего фото в днях (для критериев 4,5)
        photo_age_days = profile_data.get("photo_age_days")

        # Создаём или обновляем снапшот
        # Функция create_profile_snapshot сама проверяет существующий снапшот
        # и обновляет его если есть — это обеспечивает перезапись при rejoin
        snapshot = await create_profile_snapshot(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            has_photo=has_photo,
            account_age_days=account_age_days,
            is_premium=is_premium,
            # Передаём возраст фото для критериев 4,5
            photo_age_days=photo_age_days,
        )

        # Логируем успешное создание снапшота при входе
        logger.info(
            f"[PROFILE_MONITOR] Snapshot on join: chat={chat_id} user={user_id} "
            f"name='{first_name} {last_name}' has_photo={has_photo} "
            f"age_days={account_age_days} photo_age_days={photo_age_days}"
        )

        return snapshot

    except Exception as e:
        # Ошибка не должна ломать процесс вступления в группу
        # Логируем и продолжаем — снапшот создастся при первом сообщении (fallback)
        logger.error(
            f"[PROFILE_MONITOR] Error creating snapshot on join: "
            f"chat={chat_id} user={user_id} error={e}"
        )
        return None


async def get_profile_snapshot(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> Optional[ProfileSnapshot]:
    """
    Получает снимок профиля пользователя.

    Args:
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        ProfileSnapshot или None если не найден
    """
    # SELECT запрос с условиями chat_id и user_id
    stmt = select(ProfileSnapshot).where(
        and_(
            ProfileSnapshot.chat_id == chat_id,
            ProfileSnapshot.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_profile_snapshot(
    session: AsyncSession,
    snapshot: ProfileSnapshot,
    **kwargs,
) -> ProfileSnapshot:
    """
    Обновляет снимок профиля.

    Args:
        session: AsyncSession
        snapshot: Существующий снимок
        **kwargs: Поля для обновления

    Returns:
        ProfileSnapshot: Обновлённый снимок
    """
    # Обновляем указанные поля
    for key, value in kwargs.items():
        if hasattr(snapshot, key):
            setattr(snapshot, key, value)

    # Обновляем время изменения
    snapshot.updated_at = _utcnow_naive()
    await session.commit()
    return snapshot


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА ИЗМЕНЕНИЙ ПРОФИЛЯ
# ============================================================
async def check_profile_changes(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    current_first_name: Optional[str],
    current_last_name: Optional[str],
    current_username: Optional[str],
    current_has_photo: bool,
    current_photo_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Проверяет изменения профиля по сравнению со снимком.

    Args:
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        current_first_name: Текущее имя
        current_last_name: Текущая фамилия
        current_username: Текущий username
        current_has_photo: Есть ли фото сейчас
        current_photo_id: ID текущего фото

    Returns:
        Список изменений: [{"type": "name", "old": "...", "new": "..."}]
    """
    # Получаем сохранённый снимок
    snapshot = await get_profile_snapshot(session, chat_id, user_id)

    # Если снимка нет - нет и изменений
    if not snapshot:
        return []

    changes = []
    current_full_name = " ".join(filter(None, [current_first_name, current_last_name]))

    # Проверяем изменение имени
    if snapshot.full_name != current_full_name:
        changes.append({
            "type": "name",
            "old": snapshot.full_name or "(пусто)",
            "new": current_full_name or "(пусто)",
        })

    # Проверяем изменение username
    if snapshot.username != current_username:
        changes.append({
            "type": "username",
            "old": f"@{snapshot.username}" if snapshot.username else "(нет)",
            "new": f"@{current_username}" if current_username else "(нет)",
        })

    # Проверяем изменение фото
    if snapshot.has_photo != current_has_photo:
        if current_has_photo and not snapshot.has_photo:
            changes.append({
                "type": "photo_added",
                "old": "нет фото",
                "new": "добавлено фото",
            })
        elif not current_has_photo and snapshot.has_photo:
            changes.append({
                "type": "photo_removed",
                "old": "было фото",
                "new": "удалено фото",
            })
    elif current_has_photo and snapshot.photo_id != current_photo_id:
        # Фото было и осталось, но изменилось
        changes.append({
            "type": "photo_changed",
            "old": "старое фото",
            "new": "новое фото",
        })

    return changes


# ============================================================
# ФУНКЦИЯ: ЛОГИРОВАНИЕ ИЗМЕНЕНИЯ ПРОФИЛЯ
# ============================================================
async def log_profile_change(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    change_type: str,
    old_value: Optional[str],
    new_value: Optional[str],
    minutes_since_join: Optional[int] = None,
    message_id: Optional[int] = None,
    action_taken: Optional[str] = None,
) -> ProfileChangeLog:
    """
    Записывает изменение профиля в журнал.

    Args:
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        change_type: Тип изменения (name, username, photo_*)
        old_value: Старое значение
        new_value: Новое значение
        minutes_since_join: Минут с момента входа
        message_id: ID сообщения при котором обнаружено
        action_taken: Применённое действие

    Returns:
        ProfileChangeLog: Созданная запись
    """
    log_entry = ProfileChangeLog(
        chat_id=chat_id,
        user_id=user_id,
        change_type=change_type,
        old_value=old_value,
        new_value=new_value,
        minutes_since_join=minutes_since_join,
        detected_at_message_id=message_id,
        action_taken=action_taken,
        created_at=_utcnow_naive(),
    )
    session.add(log_entry)
    await session.commit()

    logger.info(
        f"[PROFILE_MONITOR] Change logged: chat={chat_id} user={user_id} "
        f"type={change_type} old='{old_value}' new='{new_value}' "
        f"action={action_taken}"
    )
    return log_entry


async def get_user_change_history(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    limit: int = 10,
) -> List[ProfileChangeLog]:
    """
    Получает историю изменений профиля пользователя.

    Args:
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        limit: Максимальное количество записей

    Returns:
        Список записей об изменениях (от новых к старым)
    """
    stmt = (
        select(ProfileChangeLog)
        .where(
            and_(
                ProfileChangeLog.chat_id == chat_id,
                ProfileChangeLog.user_id == user_id,
            )
        )
        .order_by(ProfileChangeLog.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА КРИТЕРИЕВ АВТОМУТА
# ============================================================
async def check_auto_mute_criteria(
    session: AsyncSession,
    settings: ProfileMonitorSettings,
    snapshot: ProfileSnapshot,
    has_recent_name_change: bool = False,
    has_recent_photo_change: bool = False,
    minutes_since_change: float = 0,
    current_photo_age_days: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Проверяет критерии автоматического мута.

    КРИТЕРИЙ 1: Смена имени + смена фото + сообщение в течение 30 мин → МУТ
    КРИТЕРИЙ 2: Смена имени + сообщение в течение 30 мин → МУТ
    КРИТЕРИЙ 3: Добавление фото + сообщение в течение 30 мин → МУТ
    КРИТЕРИЙ 4: Свежее фото (<N дней) + смена имени + сообщение ≤30 мин → МУТ
    КРИТЕРИЙ 5: Свежее фото (<N дней) + сообщение ≤30 мин → МУТ

    ПРИОРИТЕТ ПРОВЕРКИ:
    - Есть фото → проверяем свежесть фото (критерии 4, 5)
    - Нет фото → проверяем возраст аккаунта (критерии 1, 2, 3)

    Args:
        session: AsyncSession
        settings: Настройки мониторинга
        snapshot: Снимок профиля пользователя
        has_recent_name_change: Была ли смена имени недавно
        has_recent_photo_change: Была ли смена фото недавно
        minutes_since_change: Минут с момента последнего изменения профиля
        current_photo_age_days: Возраст текущего самого свежего фото в днях

    Returns:
        Tuple[bool, str]: (нужен_мут, причина)
    """
    # Получаем порог времени из настроек (по умолчанию 20 минут)
    window_minutes = settings.first_message_window_minutes

    # Получаем порог свежести фото из настроек (по умолчанию 1 день)
    photo_freshness_threshold = settings.photo_freshness_threshold_days

    # Логируем входные данные для отладки
    logger.info(
        f"[PROFILE_MONITOR] Auto-mute check: user={snapshot.user_id} "
        f"name_change={has_recent_name_change} photo_change={has_recent_photo_change} "
        f"minutes_since={minutes_since_change:.1f} window={window_minutes} "
        f"current_photo_age={current_photo_age_days} photo_freshness_threshold={photo_freshness_threshold}"
    )

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 1: Смена имени + смена фото + сообщение в течение N минут
    # ─────────────────────────────────────────────────────────
    # Проверяем включён ли критерий в настройках
    if settings.auto_mute_no_photo_young:
        # Проверяем: была смена имени И смена фото
        if has_recent_name_change and has_recent_photo_change:
            # Проверяем: сообщение в течение заданного окна времени
            if minutes_since_change <= window_minutes:
                # Формируем причину для лога и уведомления
                reason = (
                    f"Автомут: смена имени + смена фото + "
                    f"сообщение через {int(minutes_since_change)} мин "
                    f"(порог: {window_minutes} мин)"
                )
                # Логируем срабатывание критерия
                logger.warning(
                    f"[PROFILE_MONITOR] Auto-mute criteria #1 TRIGGERED: "
                    f"user={snapshot.user_id} chat={snapshot.chat_id} "
                    f"minutes={int(minutes_since_change)} threshold={window_minutes}"
                )
                # Возвращаем True и причину
                return True, reason

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 2: Смена имени + сообщение в течение N минут
    # ─────────────────────────────────────────────────────────
    # Проверяем включён ли критерий в настройках
    if settings.auto_mute_name_change_fast_msg:
        # Проверяем: была смена имени
        if has_recent_name_change:
            # Проверяем: сообщение в течение заданного окна времени
            if minutes_since_change <= window_minutes:
                # Формируем причину для лога и уведомления
                reason = (
                    f"Автомут: смена имени + "
                    f"сообщение через {int(minutes_since_change)} мин "
                    f"(порог: {window_minutes} мин)"
                )
                # Логируем срабатывание критерия
                logger.warning(
                    f"[PROFILE_MONITOR] Auto-mute criteria #2 TRIGGERED: "
                    f"user={snapshot.user_id} chat={snapshot.chat_id} "
                    f"minutes={int(minutes_since_change)} threshold={window_minutes}"
                )
                # Возвращаем True и причину
                return True, reason

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 3: Добавление фото + сообщение в течение N минут
    # ─────────────────────────────────────────────────────────
    # Проверяем включён ли критерий в настройках (используем тот же флаг)
    if settings.auto_mute_no_photo_young:
        # Проверяем: было добавление фото (без смены имени)
        if has_recent_photo_change and not has_recent_name_change:
            # Проверяем: сообщение в течение заданного окна времени
            if minutes_since_change <= window_minutes:
                # Формируем причину для лога и уведомления
                reason = (
                    f"Автомут: добавление фото + "
                    f"сообщение через {int(minutes_since_change)} мин "
                    f"(порог: {window_minutes} мин)"
                )
                # Логируем срабатывание критерия
                logger.warning(
                    f"[PROFILE_MONITOR] Auto-mute criteria #3 TRIGGERED: "
                    f"user={snapshot.user_id} chat={snapshot.chat_id} "
                    f"minutes={int(minutes_since_change)} threshold={window_minutes}"
                )
                # Возвращаем True и причину
                return True, reason

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 4: Свежее фото + смена имени + сообщение в течение N минут
    # ─────────────────────────────────────────────────────────
    # Этот критерий срабатывает когда:
    # - У пользователя есть фото (current_photo_age_days не None)
    # - Фото "свежее" (моложе photo_freshness_threshold дней)
    # - Была смена имени недавно
    # - Сообщение в течение заданного окна времени
    # Проверяем включён ли критерий в настройках (используем тот же флаг)
    if settings.auto_mute_no_photo_young:
        # Проверяем: есть фото И оно "свежее"
        if current_photo_age_days is not None:
            # Проверяем: фото моложе порога свежести
            if current_photo_age_days < photo_freshness_threshold:
                # Проверяем: была смена имени недавно
                if has_recent_name_change:
                    # Проверяем: сообщение в течение заданного окна времени
                    if minutes_since_change <= window_minutes:
                        # Формируем причину для лога и уведомления
                        reason = (
                            f"Автомут: свежее фото ({current_photo_age_days} дн) + "
                            f"смена имени + сообщение через {int(minutes_since_change)} мин "
                            f"(порог фото: {photo_freshness_threshold} дн, окно: {window_minutes} мин)"
                        )
                        # Логируем срабатывание критерия
                        logger.warning(
                            f"[PROFILE_MONITOR] Auto-mute criteria #4 TRIGGERED: "
                            f"user={snapshot.user_id} chat={snapshot.chat_id} "
                            f"photo_age={current_photo_age_days} threshold={photo_freshness_threshold} "
                            f"minutes={int(minutes_since_change)}"
                        )
                        # Возвращаем True и причину
                        return True, reason

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 5: Свежее фото + сообщение в течение N минут
    # ─────────────────────────────────────────────────────────
    # Этот критерий срабатывает когда:
    # - У пользователя есть фото (current_photo_age_days не None)
    # - Фото "свежее" (моложе photo_freshness_threshold дней)
    # - Фото было заменено на более свежее (сравниваем с snapshot.photo_age_days)
    # - Сообщение в течение заданного окна времени
    # Проверяем включён ли критерий в настройках (используем тот же флаг)
    if settings.auto_mute_no_photo_young:
        # Проверяем: есть фото И оно "свежее"
        if current_photo_age_days is not None:
            # Проверяем: фото моложе порога свежести
            if current_photo_age_days < photo_freshness_threshold:
                # Проверяем: фото стало "свежее" чем было при входе
                # Это означает что пользователь сменил фото на более новое
                snapshot_photo_age = snapshot.photo_age_days
                # Если при входе фото было старше или его не было
                if snapshot_photo_age is None or current_photo_age_days < snapshot_photo_age:
                    # Проверяем: сообщение в течение заданного окна времени
                    if minutes_since_change <= window_minutes:
                        # Формируем причину для лога и уведомления
                        reason = (
                            f"Автомут: свежее фото ({current_photo_age_days} дн) + "
                            f"сообщение через {int(minutes_since_change)} мин "
                            f"(было: {snapshot_photo_age} дн, порог: {photo_freshness_threshold} дн)"
                        )
                        # Логируем срабатывание критерия
                        logger.warning(
                            f"[PROFILE_MONITOR] Auto-mute criteria #5 TRIGGERED: "
                            f"user={snapshot.user_id} chat={snapshot.chat_id} "
                            f"photo_age={current_photo_age_days} was={snapshot_photo_age} "
                            f"threshold={photo_freshness_threshold} minutes={int(minutes_since_change)}"
                        )
                        # Возвращаем True и причину
                        return True, reason

    # Ни один критерий не сработал
    logger.debug(
        f"[PROFILE_MONITOR] Auto-mute criteria NOT triggered: "
        f"user={snapshot.user_id} chat={snapshot.chat_id}"
    )
    return False, ""


# ============================================================
# ФУНКЦИЯ: ПРИМЕНЕНИЕ АВТОМУТА
# ============================================================
async def apply_auto_mute(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    reason: str,
) -> bool:
    """
    Применяет бессрочный мут к пользователю.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        reason: Причина мута

    Returns:
        True если мут успешно применён
    """
    try:
        # Применяем мут через Telegram API
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=None,  # Бессрочно
        )

        # Сохраняем ограничение в БД для восстановления после перезахода
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="mute",
            reason="profile_monitor",
            restricted_by=bot.id,
            until_date=None,
        )

        logger.info(
            f"[PROFILE_MONITOR] Auto-mute applied: chat={chat_id} user={user_id} "
            f"reason={reason}"
        )
        return True

    except Exception as e:
        logger.error(
            f"[PROFILE_MONITOR] Failed to apply auto-mute: "
            f"chat={chat_id} user={user_id} error={e}"
        )
        return False


# ============================================================
# ФУНКЦИЯ: УДАЛЕНИЕ СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЯ
# ============================================================
async def delete_user_messages(
    bot: Bot,
    chat_id: int,
    user_id: int,
    limit: int = 100,
) -> int:
    """
    Удаляет все сообщения пользователя в группе (до лимита).

    Использует сохранённые message_id из Redis (через track_user_message).
    Bot API не позволяет получить историю сообщений, поэтому мы трекаем
    сообщения при их поступлении в координаторе.

    Args:
        bot: Bot instance
        chat_id: ID группы
        user_id: ID пользователя
        limit: Максимальное количество сообщений для удаления

    Returns:
        Количество удалённых сообщений
    """
    deleted_count = 0

    try:
        # Получаем сохранённые message_id из Redis
        message_ids = await get_tracked_messages(chat_id, user_id)

        if not message_ids:
            logger.info(
                f"[PROFILE_MONITOR] No tracked messages to delete: "
                f"chat={chat_id} user={user_id}"
            )
            return 0

        # Ограничиваем количество
        message_ids = message_ids[-limit:]

        for message_id in message_ids:
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id,
                )
                deleted_count += 1
            except Exception as e:
                # Пропускаем ошибки удаления отдельных сообщений
                # (сообщение могло быть уже удалено)
                logger.debug(
                    f"[PROFILE_MONITOR] Failed to delete message {message_id}: {e}"
                )

        # Очищаем трекер после удаления
        await clear_tracked_messages(chat_id, user_id)

        logger.info(
            f"[PROFILE_MONITOR] Deleted {deleted_count}/{len(message_ids)} messages: "
            f"chat={chat_id} user={user_id}"
        )

    except Exception as e:
        logger.error(
            f"[PROFILE_MONITOR] Failed to delete messages: "
            f"chat={chat_id} user={user_id} error={e}"
        )

    return deleted_count


# ============================================================
# ФУНКЦИЯ: ПОЛУЧЕНИЕ ДАННЫХ ПРОФИЛЯ ЧЕРЕЗ PYROGRAM
# ============================================================
async def get_user_profile_data(
    user_id: int,
) -> Dict[str, Any]:
    """
    Получает данные профиля пользователя через Pyrogram.

    Args:
        user_id: ID пользователя

    Returns:
        Словарь с данными профиля:
        {
            "has_photo": bool,
            "photo_id": str | None,
            "account_age_days": int | None,
        }
    """
    result = {
        "has_photo": False,
        "photo_id": None,
        "account_age_days": None,
        # Возраст самого свежего фото в днях (для критериев 4,5)
        "photo_age_days": None,
    }

    # Проверяем доступность Pyrogram
    if not pyrogram_service.is_available():
        logger.warning("[PROFILE_MONITOR] Pyrogram not available for profile check")
        return result

    try:
        # Получаем информацию о фото (включая возраст самого свежего)
        photos_info = await pyrogram_service.check_all_photos_young(
            user_id=user_id,
            max_age_days=15,
        )
        # Есть ли фото вообще
        result["has_photo"] = photos_info.get("photos_count", 0) > 0
        # Возраст самого свежего фото в днях (для критериев 4,5)
        # Используем youngest_photo_days из pyrogram_service
        # Если фото нет - photo_age_days будет None
        result["photo_age_days"] = photos_info.get("youngest_photo_days")

        # Получаем возраст аккаунта
        age_info = await pyrogram_service.get_account_age(user_id)
        if age_info and age_info.get("account_age_days") is not None:
            result["account_age_days"] = age_info["account_age_days"]

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Error getting profile data: {e}")

    return result


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА СМЕНЫ ИМЕНИ В ОКНЕ ВРЕМЕНИ
# ============================================================
async def has_recent_name_change(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    window_hours: int = 24,
) -> bool:
    """
    Проверяет была ли смена имени в указанном временном окне.

    Args:
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        window_hours: Окно времени в часах

    Returns:
        True если была смена имени в указанном окне
    """
    # Вычисляем границу времени
    cutoff = _utcnow_naive() - timedelta(hours=window_hours)

    # Ищем записи об изменении имени за указанный период
    stmt = (
        select(ProfileChangeLog)
        .where(
            and_(
                ProfileChangeLog.chat_id == chat_id,
                ProfileChangeLog.user_id == user_id,
                ProfileChangeLog.change_type == "name",
                ProfileChangeLog.created_at >= cutoff,
            )
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА СМЕНЫ ФОТО В ОКНЕ ВРЕМЕНИ
# ============================================================
async def has_recent_photo_change(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    window_hours: int = 24,
) -> bool:
    """
    Проверяет была ли смена фото в указанном временном окне.

    Ищет записи об изменении фото (добавление, удаление, замена)
    в таблице profile_change_logs за указанный период.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID группы
        user_id: ID пользователя
        window_hours: Окно времени в часах (по умолчанию 24)

    Returns:
        True если была смена фото в указанном окне, False иначе
    """
    # Вычисляем границу времени (текущее время минус окно)
    cutoff = _utcnow_naive() - timedelta(hours=window_hours)

    # Типы изменений фото: добавление, удаление, замена
    photo_change_types = ["photo_added", "photo_removed", "photo_changed"]

    # Ищем записи об изменении фото за указанный период
    stmt = (
        select(ProfileChangeLog)
        .where(
            and_(
                # Фильтруем по группе
                ProfileChangeLog.chat_id == chat_id,
                # Фильтруем по пользователю
                ProfileChangeLog.user_id == user_id,
                # Фильтруем по типам изменения фото
                ProfileChangeLog.change_type.in_(photo_change_types),
                # Фильтруем по времени (только недавние)
                ProfileChangeLog.created_at >= cutoff,
            )
        )
        # Достаточно найти хотя бы одну запись
        .limit(1)
    )
    # Выполняем запрос
    result = await session.execute(stmt)
    # Возвращаем True если найдена хотя бы одна запись
    return result.scalar_one_or_none() is not None
