# bot/handlers/profile_monitor/monitor_handler.py
"""
Обработчик мониторинга профилей в группах.

Вызывается из group_message_coordinator при каждом сообщении.
Проверяет изменения профиля и применяет автомут при необходимости.

НЕ ЯВЛЯЕТСЯ САМОСТОЯТЕЛЬНЫМ ХЕНДЛЕРОМ - вызывается только из координатора!
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot
from aiogram.types import Message, User
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models_profile_monitor import (
    ProfileMonitorSettings,
    ProfileSnapshot,
)
from bot.services.profile_monitor.profile_monitor_service import (
    get_profile_monitor_settings,
    get_profile_snapshot,
    create_profile_snapshot,
    update_profile_snapshot,
    check_profile_changes,
    log_profile_change,
    check_auto_mute_criteria,
    apply_auto_mute,
    delete_user_messages,
    get_user_profile_data,
    has_recent_name_change,
    has_recent_photo_change,
    get_user_change_history,
)
from bot.services.group_journal_service import send_journal_event
from bot.keyboards.profile_monitor_kb import (
    get_journal_action_kb,
    get_auto_mute_kb,
)

# Логгер модуля
logger = logging.getLogger(__name__)

# ПРИМЕЧАНИЕ: Этот файл НЕ содержит роутер с @router.message() хендлерами!
# Функция process_message_profile_check() вызывается напрямую из
# group_message_coordinator.py для избежания конфликта хендлеров в aiogram 3.x


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА ПРОФИЛЯ ПРИ СООБЩЕНИИ (ГЛАВНАЯ)
# ============================================================
async def process_message_profile_check(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> Optional[Dict[str, Any]]:
    """
    Проверяет профиль пользователя при отправке сообщения.

    Эта функция вызывается из group_message_coordinator для каждого сообщения.

    Логика:
    1. Получить настройки модуля для группы
    2. Если модуль выключен - выход
    3. Получить или создать снимок профиля
    4. Проверить изменения профиля
    5. Проверить критерии автомута
    6. Применить действия если нужно

    Args:
        message: Сообщение из группы
        session: AsyncSession для БД
        bot: Bot instance

    Returns:
        Dict с результатом или None если модуль выключен
        {
            "action_taken": "auto_mute" | "logged" | None,
            "reason": str | None,
            "changes": list | None,
        }
    """
    # Проверяем что сообщение из группы
    if not message.chat or message.chat.type not in ("group", "supergroup"):
        return None

    # Проверяем что есть отправитель
    if not message.from_user:
        return None

    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id

    # ─────────────────────────────────────────────────────────
    # ШАГ 1: Получаем настройки модуля
    # ─────────────────────────────────────────────────────────
    settings = await get_profile_monitor_settings(session, chat_id)

    # Если настроек нет или модуль выключен - выход
    if not settings or not settings.enabled:
        return None

    logger.debug(f"[PROFILE_MONITOR] Checking user={user_id} in chat={chat_id}")

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: Получаем снимок профиля
    # ─────────────────────────────────────────────────────────
    snapshot = await get_profile_snapshot(session, chat_id, user_id)

    # Если снимка нет - создаём новый (пользователь пишет первый раз)
    if not snapshot:
        return await _handle_first_message(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            user=user,
        )

    # ─────────────────────────────────────────────────────────
    # ШАГ 3: Обновляем время первого сообщения (если не установлено)
    # ─────────────────────────────────────────────────────────
    if snapshot.first_message_at is None:
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        snapshot = await update_profile_snapshot(
            session=session,
            snapshot=snapshot,
            first_message_at=now,
        )
        logger.info(
            f"[PROFILE_MONITOR] First message recorded: user={user_id} chat={chat_id}"
        )

    # ─────────────────────────────────────────────────────────
    # ШАГ 4: Получаем текущие данные профиля
    # ─────────────────────────────────────────────────────────
    # Проверяем фото через Pyrogram (если доступен)
    profile_data = await get_user_profile_data(user_id)
    current_has_photo = profile_data.get("has_photo", False)

    # Используем данные из сообщения для имени/username
    current_first_name = user.first_name
    current_last_name = user.last_name
    current_username = user.username

    # ─────────────────────────────────────────────────────────
    # ШАГ 5: Проверяем изменения профиля
    # ─────────────────────────────────────────────────────────
    changes = await check_profile_changes(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        current_first_name=current_first_name,
        current_last_name=current_last_name,
        current_username=current_username,
        current_has_photo=current_has_photo,
    )

    # ─────────────────────────────────────────────────────────
    # ШАГ 6: Обрабатываем изменения
    # ─────────────────────────────────────────────────────────
    if changes:
        return await _handle_profile_changes(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            snapshot=snapshot,
            changes=changes,
            current_has_photo=current_has_photo,
        )

    return {"action_taken": None, "reason": None, "changes": None}


# ============================================================
# ФУНКЦИЯ: ОБРАБОТКА ПЕРВОГО СООБЩЕНИЯ (FALLBACK)
# ============================================================
async def _handle_first_message(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    user: User,
) -> Dict[str, Any]:
    """
    FALLBACK: Обрабатывает первое сообщение пользователя в группе.

    ВАЖНО: Эта функция вызывается только если снапшот НЕ существует.
    С версии 2024-12: снапшот создаётся при JOIN (в visual_captcha_handler),
    поэтому эта функция - FALLBACK для:
    1. Пользователей, вступивших ДО включения модуля
    2. Пользователей, вступивших через способы без chat_member_updated
    3. Ошибок при создании снапшота при JOIN

    ВНИМАНИЕ: joined_at будет установлен как время первого сообщения,
    а не реальное время входа. Это некорректно для расчёта minutes_since_join,
    но приемлемо для fallback-случаев.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        user: Пользователь

    Returns:
        Dict с результатом обработки
    """
    chat_id = message.chat.id
    user_id = user.id

    logger.info(
        f"[PROFILE_MONITOR] FALLBACK: Creating snapshot on first message "
        f"(no snapshot from JOIN): user={user_id} chat={chat_id}"
    )

    # Получаем данные профиля через Pyrogram
    profile_data = await get_user_profile_data(user_id)
    has_photo = profile_data.get("has_photo", False)
    account_age_days = profile_data.get("account_age_days")

    # Создаём снимок профиля
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    snapshot = await create_profile_snapshot(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        has_photo=has_photo,
        account_age_days=account_age_days,
        is_premium=user.is_premium or False,
    )

    # Устанавливаем время первого сообщения
    snapshot = await update_profile_snapshot(
        session=session,
        snapshot=snapshot,
        first_message_at=now,
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА КРИТЕРИЯ 1: Нет фото + молодой аккаунт
    # ─────────────────────────────────────────────────────────
    should_mute, reason = await check_auto_mute_criteria(
        session=session,
        settings=settings,
        snapshot=snapshot,
        has_recent_name_change=False,  # Первое сообщение - смены имени ещё не было
    )

    if should_mute:
        return await _apply_auto_mute_action(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            snapshot=snapshot,
            reason=reason,
        )

    return {"action_taken": None, "reason": None, "changes": None}


# ============================================================
# ФУНКЦИЯ: ОБРАБОТКА ИЗМЕНЕНИЙ ПРОФИЛЯ
# ============================================================
async def _handle_profile_changes(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    snapshot: ProfileSnapshot,
    changes: list,
    current_has_photo: bool,
) -> Dict[str, Any]:
    """
    Обрабатывает обнаруженные изменения профиля.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        snapshot: Снимок профиля
        changes: Список изменений
        current_has_photo: Есть ли фото сейчас

    Returns:
        Dict с результатом обработки
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user

    logger.info(
        f"[PROFILE_MONITOR] Profile changes detected: user={user_id} "
        f"chat={chat_id} changes={changes}"
    )

    # Проверяем есть ли смена имени среди изменений
    name_changed = any(c["type"] == "name" for c in changes)

    # Вычисляем время с момента входа
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    time_diff = now - snapshot.joined_at
    minutes_since_join = int(time_diff.total_seconds() / 60)

    # Логируем каждое изменение
    log_entries = []
    for change in changes:
        # Проверяем настройки логирования
        if change["type"] == "name" and not settings.log_name_changes:
            continue
        if change["type"] == "username" and not settings.log_username_changes:
            continue
        if change["type"].startswith("photo") and not settings.log_photo_changes:
            continue

        entry = await log_profile_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            change_type=change["type"],
            old_value=change["old"],
            new_value=change["new"],
            minutes_since_join=minutes_since_join,
            message_id=message.message_id,
        )
        log_entries.append(entry)

    # Обновляем снимок профиля
    current_full_name = " ".join(filter(None, [user.first_name, user.last_name]))
    await update_profile_snapshot(
        session=session,
        snapshot=snapshot,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=current_full_name,
        username=user.username,
        has_photo=current_has_photo,
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА КРИТЕРИЕВ АВТОМУТА
    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 1: Смена имени + смена фото + сообщение в течение 20 мин
    # КРИТЕРИЙ 2: Смена имени + сообщение в течение 20 мин

    # Проверяем есть ли смена фото среди изменений
    photo_changed = any(c["type"].startswith("photo") for c in changes)

    # Если была смена имени ИЛИ смена фото - проверяем критерии автомута
    if name_changed or photo_changed:
        # Проверяем была ли смена имени в окне времени (24 часа)
        recent_name_change = await has_recent_name_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            window_hours=settings.name_change_window_hours,
        )

        # Проверяем была ли смена фото в окне времени (24 часа)
        recent_photo_change = await has_recent_photo_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            window_hours=settings.name_change_window_hours,
        )

        # Логируем для отладки
        logger.info(
            f"[PROFILE_MONITOR] Auto-mute pre-check: chat={chat_id} user={user_id} "
            f"name_changed={name_changed} photo_changed={photo_changed} "
            f"recent_name={recent_name_change} recent_photo={recent_photo_change} "
            f"minutes_since_join={minutes_since_join}"
        )

        # Вызываем проверку критериев автомута
        should_mute, reason = await check_auto_mute_criteria(
            session=session,
            settings=settings,
            snapshot=snapshot,
            has_recent_name_change=recent_name_change,
            has_recent_photo_change=recent_photo_change,
            minutes_since_change=float(minutes_since_join),
        )

        # Если критерий сработал - применяем автомут
        if should_mute:
            return await _apply_auto_mute_action(
                message=message,
                session=session,
                bot=bot,
                settings=settings,
                snapshot=snapshot,
                reason=reason,
            )

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА В ЖУРНАЛ (если настроено)
    # ─────────────────────────────────────────────────────────
    # Логируем входные данные для отладки
    logger.info(
        f"[PROFILE_MONITOR] Journal check: chat={chat_id} user={user_id} "
        f"send_to_journal={settings.send_to_journal} "
        f"log_entries={len(log_entries)} min_changes={settings.min_changes_for_journal}"
    )

    # Проверяем условие отправки в журнал
    if settings.send_to_journal and log_entries:
        # Проверяем достаточно ли изменений для отправки
        if len(log_entries) >= settings.min_changes_for_journal:
            # Логируем что отправляем в журнал
            logger.info(f"[PROFILE_MONITOR] Sending to journal: chat={chat_id} user={user_id}")
            # Отправляем уведомление в журнал группы
            await _send_changes_to_journal(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user=user,
                changes=changes,
                log_entry=log_entries[0],
                minutes_since_join=minutes_since_join,
            )
        else:
            # Логируем причину пропуска - недостаточно изменений
            logger.info(
                f"[PROFILE_MONITOR] Skip journal: not enough changes "
                f"({len(log_entries)} < {settings.min_changes_for_journal})"
            )
    else:
        # Логируем причину пропуска - отключено или нет записей
        if not settings.send_to_journal:
            logger.info(f"[PROFILE_MONITOR] Skip journal: send_to_journal=False")
        elif not log_entries:
            logger.info(f"[PROFILE_MONITOR] Skip journal: no log entries")

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА В ГРУППУ (если настроено)
    # ─────────────────────────────────────────────────────────
    # Проверяем настройку отправки в группу
    if settings.send_to_group and name_changed:
        # Логируем что отправляем в группу
        logger.info(f"[PROFILE_MONITOR] Sending to group: chat={chat_id} user={user_id}")

        # Получаем историю изменений имен для отображения
        history = await get_user_change_history(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            limit=10,
        )

        # Отправляем простое уведомление в группу
        await _send_changes_to_group(
            bot=bot,
            chat_id=chat_id,
            user=user,
            changes=changes,
            history=history,
        )
    elif not settings.send_to_group:
        # Логируем причину пропуска
        logger.debug(f"[PROFILE_MONITOR] Skip group: send_to_group=False")

    # Возвращаем результат обработки
    return {
        "action_taken": "logged",
        "reason": None,
        "changes": changes,
    }


# ============================================================
# ФУНКЦИЯ: ПРИМЕНЕНИЕ АВТОМУТА
# ============================================================
async def _apply_auto_mute_action(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    snapshot: ProfileSnapshot,
    reason: str,
) -> Dict[str, Any]:
    """
    Применяет автоматический мут и сопутствующие действия.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        snapshot: Снимок профиля
        reason: Причина мута

    Returns:
        Dict с результатом
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user

    logger.warning(
        f"[PROFILE_MONITOR] Applying auto-mute: user={user_id} "
        f"chat={chat_id} reason={reason}"
    )

    # Применяем мут
    mute_success = await apply_auto_mute(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        reason=reason,
    )

    # Удаляем сообщения если настроено
    deleted_count = 0
    if mute_success and settings.auto_mute_delete_messages:
        deleted_count = await delete_user_messages(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

    # Логируем действие
    log_entry = await log_profile_change(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        change_type="auto_mute",
        old_value=None,
        new_value=reason,
        action_taken="auto_mute",
    )

    # Отправляем уведомление в журнал
    if settings.send_to_journal:
        await _send_auto_mute_to_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user=user,
            reason=reason,
            deleted_count=deleted_count,
            log_entry=log_entry,
        )

    return {
        "action_taken": "auto_mute",
        "reason": reason,
        "changes": None,
    }


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА ИЗМЕНЕНИЙ В ЖУРНАЛ
# ============================================================
async def _send_changes_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    changes: list,
    log_entry,
    minutes_since_join: int,
) -> None:
    """
    Отправляет уведомление об изменениях профиля в журнал группы.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user: Пользователь
        changes: Список изменений
        log_entry: Запись в журнале
        minutes_since_join: Минут с момента входа
    """
    # Формируем имя пользователя для отображения
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    username_str = f" (@{user.username})" if user.username else ""

    # Формируем текст изменений
    changes_text = []
    for change in changes:
        if change["type"] == "name":
            changes_text.append(f"Имя: {change['old']} → {change['new']}")
        elif change["type"] == "username":
            changes_text.append(f"Username: {change['old']} → {change['new']}")
        elif change["type"] == "photo_added":
            changes_text.append("Добавлено фото профиля")
        elif change["type"] == "photo_removed":
            changes_text.append("Удалено фото профиля")
        elif change["type"] == "photo_changed":
            changes_text.append("Изменено фото профиля")

    changes_list = "\n".join(f"  • {c}" for c in changes_text)

    # Формируем сообщение
    text = (
        f"🔄 <b>Изменение профиля</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"⏱ Через {minutes_since_join} мин после входа\n\n"
        f"<b>Изменения:</b>\n"
        f"{changes_list}"
    )

    # Отправляем в журнал с кнопками
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_journal_action_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=log_entry.id if log_entry else 0,
        ),
    )


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА АВТОМУТА В ЖУРНАЛ
# ============================================================
async def _send_auto_mute_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    reason: str,
    deleted_count: int,
    log_entry,
) -> None:
    """
    Отправляет уведомление об автомуте в журнал группы.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user: Пользователь
        reason: Причина мута
        deleted_count: Количество удалённых сообщений
        log_entry: Запись в журнале
    """
    # Формируем имя пользователя для отображения
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    username_str = f" (@{user.username})" if user.username else ""

    # Формируем сообщение
    text = (
        f"🔇 <b>Автоматический мут</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"<b>Причина:</b>\n"
        f"{reason}\n\n"
        f"<b>Действия:</b>\n"
        f"  • Мут навсегда\n"
    )

    if deleted_count > 0:
        text += f"  • Удалено {deleted_count} сообщений"

    # Отправляем в журнал с кнопками
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_auto_mute_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=log_entry.id if log_entry else 0,
        ),
    )


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА ИЗМЕНЕНИЙ В ГРУППУ (для всех участников)
# ============================================================
async def _send_changes_to_group(
    bot: Bot,
    chat_id: int,
    user: User,
    changes: list,
    history: list,
) -> None:
    """
    Отправляет простое уведомление об изменениях профиля прямо в группу.

    Это сообщение видят все участники группы (не только админы).
    Формат простой и информативный:
    - Кто сменил имя
    - Было / Стало
    - История всех имен с датами

    Args:
        bot: Bot instance для отправки сообщений
        chat_id: ID группы куда отправлять
        user: Пользователь который изменил профиль
        changes: Список обнаруженных изменений
        history: История изменений профиля из БД
    """
    # Формируем имя пользователя для отображения (кликабельная ссылка)
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    # Добавляем @username если есть
    username_str = f" (@{user.username})" if user.username else ""

    # Ищем изменение имени среди изменений
    name_change = None
    for change in changes:
        if change["type"] == "name":
            name_change = change
            break

    # Если нет изменения имени - ничего не отправляем в группу
    if not name_change:
        return

    # Формируем основной текст сообщения
    text = (
        f"📝 <b>Пользователь сменил имя</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"<b>Было:</b> {name_change['old']}\n"
        f"<b>Стало:</b> {name_change['new']}\n"
    )

    # Добавляем историю имен если есть записи
    if history:
        text += "\n<b>История имен:</b>\n"
        # Перебираем историю изменений (от новых к старым)
        for entry in history[:5]:  # Показываем последние 5 записей
            # Форматируем дату
            entry_date = entry.created_at.strftime("%d.%m.%Y %H:%M")
            # Добавляем строку с именем и датой
            if entry.change_type == "name":
                text += f"  • {entry.new_value} — {entry_date}\n"

    # Отправляем сообщение в группу
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )
        # Логируем успешную отправку
        logger.info(f"[PROFILE_MONITOR] Sent to group: chat={chat_id} user={user.id}")
    except Exception as e:
        # Логируем ошибку но не падаем
        logger.error(f"[PROFILE_MONITOR] Failed to send to group: {e}")
