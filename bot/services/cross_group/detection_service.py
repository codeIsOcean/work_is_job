# bot/services/cross_group/detection_service.py
"""
Сервис детекции кросс-групповых скамеров.

Отслеживает активность пользователей в нескольких группах:
1. Входы в группы
2. Смену профиля (имя/фото)
3. Сообщения в группах

Детекция срабатывает когда ВСЕ критерии выполнены:
- Вход в 2+ группы в заданном интервале
- Смена профиля в заданном окне
- Сообщения в 2+ группах в заданном интервале
"""

# Импортируем логгер для записи событий
import logging
# Импортируем datetime для работы со временем
from datetime import datetime, timedelta
# Импортируем типы для аннотаций
from typing import Optional, Dict, Any, Tuple
# Импортируем json для работы с JSONB
import json

# Импортируем AsyncSession для асинхронной работы с БД
from sqlalchemy.ext.asyncio import AsyncSession
# Импортируем select для построения запросов
from sqlalchemy import select, delete

# Импортируем модели кросс-групповой детекции
from bot.database.models_cross_group import (
    CrossGroupScammerSettings,
    CrossGroupUserActivity,
    CrossGroupDetectionLog,
    CrossGroupActionType,
    ProfileChangeType,
)

# Импортируем сервис настроек
from bot.services.cross_group.settings_service import (
    get_cross_group_settings,
    is_group_excluded,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


async def get_user_activity(
    session: AsyncSession,
    user_id: int
) -> Optional[CrossGroupUserActivity]:
    """
    Получает запись активности пользователя.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram

    Returns:
        CrossGroupUserActivity или None если записи нет
    """
    # Строим запрос для получения активности пользователя
    query = select(CrossGroupUserActivity).where(
        CrossGroupUserActivity.user_id == user_id
    )

    # Выполняем запрос
    result = await session.execute(query)

    # Возвращаем запись или None
    return result.scalar_one_or_none()


async def get_or_create_user_activity(
    session: AsyncSession,
    user_id: int
) -> CrossGroupUserActivity:
    """
    Получает или создаёт запись активности пользователя.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram

    Returns:
        CrossGroupUserActivity: Запись активности (существующая или новая)
    """
    # Пытаемся получить существующую запись
    activity = await get_user_activity(session, user_id)

    # Если записи нет — создаём новую
    if activity is None:
        # Логируем создание новой записи
        logger.debug(f"Создаём запись активности для пользователя {user_id}")

        # Создаём новый объект
        activity = CrossGroupUserActivity(user_id=user_id)

        # Добавляем в сессию
        session.add(activity)
        # Сохраняем в БД
        await session.commit()
        # Обновляем объект из БД
        await session.refresh(activity)

    return activity


async def track_user_join(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    group_title: str
) -> bool:
    """
    Отслеживает вход пользователя в группу.

    Записывает информацию о входе в groups_joined.
    Проверяет не находится ли группа в списке исключений.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram
        chat_id: ID группы
        group_title: Название группы

    Returns:
        bool: True если вход записан, False если группа в исключениях
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Проверяем включён ли модуль
    if not settings.enabled:
        return False

    # Проверяем не в исключениях ли группа
    if await is_group_excluded(session, chat_id):
        logger.debug(f"Группа {chat_id} в исключениях, пропускаем")
        return False

    # Получаем или создаём запись активности пользователя
    activity = await get_or_create_user_activity(session, user_id)

    # Получаем текущий список групп (копируем для изменения)
    groups_joined = dict(activity.groups_joined or {})

    # Добавляем информацию о входе
    # Используем str(chat_id) так как JSON ключи должны быть строками
    groups_joined[str(chat_id)] = {
        "joined_at": datetime.utcnow().isoformat(),
        "group_title": group_title,
    }

    # Обновляем запись (JSONB требует явного присваивания)
    activity.groups_joined = groups_joined

    # Сохраняем в БД
    await session.commit()

    # Логируем вход
    logger.info(
        f"Записан вход пользователя {user_id} в группу {chat_id} ({group_title})"
    )

    return True


async def track_profile_change(
    session: AsyncSession,
    user_id: int,
    change_type: ProfileChangeType,
    original_name: Optional[str] = None,
    original_photo_id: Optional[str] = None
) -> bool:
    """
    Отслеживает смену профиля пользователя.

    Записывает информацию об изменении в profile_changed_at.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram
        change_type: Тип изменения (NAME, PHOTO, BOTH)
        original_name: Оригинальное имя до изменения
        original_photo_id: ID оригинального фото до изменения

    Returns:
        bool: True если изменение записано
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Проверяем включён ли модуль
    if not settings.enabled:
        return False

    # Получаем или создаём запись активности пользователя
    activity = await get_or_create_user_activity(session, user_id)

    # Обновляем информацию о смене профиля
    activity.profile_changed_at = datetime.utcnow()
    activity.profile_change_type = change_type

    # Сохраняем оригинальные данные если переданы
    if original_name is not None:
        activity.original_name = original_name
    if original_photo_id is not None:
        activity.original_photo_id = original_photo_id

    # Сохраняем в БД
    await session.commit()

    # Логируем изменение профиля
    logger.info(
        f"Записана смена профиля пользователя {user_id}: {change_type.value}"
    )

    return True


async def track_user_message(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    message_id: int
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Отслеживает сообщение пользователя в группе.

    Записывает информацию о сообщении и проверяет детекцию.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram
        chat_id: ID группы
        message_id: ID сообщения (для последующего удаления)

    Returns:
        Tuple[bool, Optional[dict]]:
            - bool: True если сообщение записано
            - dict: Данные детекции если сработала, None если нет
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Проверяем включён ли модуль
    if not settings.enabled:
        return False, None

    # Проверяем не в исключениях ли группа
    if await is_group_excluded(session, chat_id):
        return False, None

    # Получаем или создаём запись активности пользователя
    activity = await get_or_create_user_activity(session, user_id)

    # Получаем текущий список сообщений (копируем для изменения)
    messages = dict(activity.messages_in_groups or {})

    # Получаем текущие данные для группы
    chat_key = str(chat_id)
    current = messages.get(chat_key, {"message_count": 0, "message_ids": []})

    # Получаем текущий список message_id (ограничиваем до 100 последних)
    message_ids = current.get("message_ids", [])
    message_ids.append(message_id)
    # Храним только последние 100 сообщений чтобы не раздувать БД
    if len(message_ids) > 100:
        message_ids = message_ids[-100:]

    # Обновляем информацию о сообщении
    messages[chat_key] = {
        "last_message_at": datetime.utcnow().isoformat(),
        "first_message_at": current.get("first_message_at", datetime.utcnow().isoformat()),
        "message_count": current.get("message_count", 0) + 1,
        "message_ids": message_ids,
    }

    # Обновляем запись (JSONB требует явного присваивания)
    activity.messages_in_groups = messages

    # Сохраняем в БД
    await session.commit()

    # Логируем сообщение
    logger.debug(
        f"Записано сообщение пользователя {user_id} в группе {chat_id}, msg_id={message_id}"
    )

    # Проверяем детекцию
    detection_result = await check_cross_group_detection(session, user_id)

    return True, detection_result


async def check_cross_group_detection(
    session: AsyncSession,
    user_id: int
) -> Optional[Dict[str, Any]]:
    """
    Проверяет критерии кросс-групповой детекции.

    Детекция срабатывает когда ВСЕ критерии выполнены:
    1. Вход в min_groups+ групп за join_interval_seconds
    2. Смена профиля за profile_change_window_seconds
    3. Сообщения в min_groups+ группах за message_interval_seconds

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя Telegram

    Returns:
        dict: Данные детекции если сработала:
            {
                "user_id": int,
                "groups_involved": dict,
                "profile_changes": dict или None,
                "reason": str
            }
        None: Если детекция не сработала
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Проверяем включён ли модуль
    if not settings.enabled:
        return None

    # Получаем запись активности пользователя
    activity = await get_user_activity(session, user_id)

    # Если записи нет — детекция не срабатывает
    if activity is None:
        return None

    # Если пользователь уже помечен и действие применено — пропускаем
    if activity.is_flagged and activity.action_taken:
        return None

    # Текущее время для расчётов
    now = datetime.utcnow()

    # ═══════════════════════════════════════════════════════════
    # КРИТЕРИЙ 1: Входы в группы
    # ═══════════════════════════════════════════════════════════
    # Порог времени для входов
    join_threshold = now - timedelta(seconds=settings.join_interval_seconds)

    # Фильтруем группы по времени входа
    groups_joined = activity.groups_joined or {}
    recent_joins = {}

    for chat_id, data in groups_joined.items():
        # Парсим время входа
        joined_at_str = data.get("joined_at")
        if joined_at_str:
            try:
                joined_at = datetime.fromisoformat(joined_at_str)
                # Проверяем попадает ли в интервал
                if joined_at >= join_threshold:
                    recent_joins[chat_id] = data
            except (ValueError, TypeError):
                # Пропускаем некорректные данные
                continue

    # Проверяем достаточно ли групп
    if len(recent_joins) < settings.min_groups:
        logger.debug(
            f"Пользователь {user_id}: недостаточно входов "
            f"({len(recent_joins)} < {settings.min_groups})"
        )
        return None

    # ═══════════════════════════════════════════════════════════
    # КРИТЕРИЙ 2: Смена профиля
    # ═══════════════════════════════════════════════════════════
    # Порог времени для смены профиля
    profile_threshold = now - timedelta(
        seconds=settings.profile_change_window_seconds
    )

    # Проверяем была ли смена профиля в заданном окне
    profile_changed = False
    profile_changes = None

    if activity.profile_changed_at:
        if activity.profile_changed_at >= profile_threshold:
            profile_changed = True
            # Собираем данные об изменении профиля
            profile_changes = {
                "change_type": activity.profile_change_type.value if activity.profile_change_type else None,
                "original_name": activity.original_name,
                "original_photo_id": activity.original_photo_id,
                "changed_at": activity.profile_changed_at.isoformat(),
            }

    # Если профиль не менялся — детекция не срабатывает
    if not profile_changed:
        logger.debug(
            f"Пользователь {user_id}: профиль не менялся в заданном окне"
        )
        return None

    # ═══════════════════════════════════════════════════════════
    # КРИТЕРИЙ 3: Сообщения в группах
    # ═══════════════════════════════════════════════════════════
    # Порог времени для сообщений
    message_threshold = now - timedelta(
        seconds=settings.message_interval_seconds
    )

    # Фильтруем группы по времени сообщений
    messages = activity.messages_in_groups or {}
    recent_messages = {}

    for chat_id, data in messages.items():
        # Парсим время сообщения
        message_at_str = data.get("last_message_at")
        if message_at_str:
            try:
                message_at = datetime.fromisoformat(message_at_str)
                # Проверяем попадает ли в интервал
                if message_at >= message_threshold:
                    recent_messages[chat_id] = data
            except (ValueError, TypeError):
                # Пропускаем некорректные данные
                continue

    # Проверяем достаточно ли групп с сообщениями
    if len(recent_messages) < settings.min_groups:
        logger.debug(
            f"Пользователь {user_id}: недостаточно групп с сообщениями "
            f"({len(recent_messages)} < {settings.min_groups})"
        )
        return None

    # ═══════════════════════════════════════════════════════════
    # ВСЕ КРИТЕРИИ ВЫПОЛНЕНЫ — ДЕТЕКЦИЯ СРАБОТАЛА!
    # ═══════════════════════════════════════════════════════════
    logger.warning(
        f"КРОСС-ГРУППОВАЯ ДЕТЕКЦИЯ: пользователь {user_id} "
        f"затронул {len(recent_joins)} групп"
    )

    # Помечаем пользователя как подозрительного
    activity.is_flagged = True
    activity.flagged_at = now

    # Сохраняем изменения
    await session.commit()

    # Формируем данные детекции
    # Объединяем информацию о входах и сообщениях
    groups_involved = {}
    for chat_id in set(recent_joins.keys()) | set(recent_messages.keys()):
        join_data = recent_joins.get(chat_id, {})
        msg_data = recent_messages.get(chat_id, {})

        groups_involved[chat_id] = {
            "group_title": join_data.get("group_title", "Неизвестно"),
            "joined_at": join_data.get("joined_at"),
            "first_message_at": msg_data.get("first_message_at"),
            "last_message_at": msg_data.get("last_message_at"),
            "message_count": msg_data.get("message_count", 0),
            "message_ids": msg_data.get("message_ids", []),
        }

    return {
        "user_id": user_id,
        "groups_involved": groups_involved,
        "profile_changes": profile_changes,
        "reason": (
            f"Вход в {len(recent_joins)} групп, "
            f"смена профиля, "
            f"сообщения в {len(recent_messages)} группах"
        ),
    }


async def clear_old_activity(
    session: AsyncSession,
    max_age_days: int = 7
) -> int:
    """
    Очищает старые записи активности.

    Удаляет записи пользователей которые не были активны
    дольше max_age_days дней.

    Args:
        session: Асинхронная сессия SQLAlchemy
        max_age_days: Максимальный возраст записи в днях

    Returns:
        int: Количество удалённых записей
    """
    # Порог времени для удаления
    threshold = datetime.utcnow() - timedelta(days=max_age_days)

    # Строим запрос на удаление старых записей
    # Удаляем только записи где не было действий
    query = delete(CrossGroupUserActivity).where(
        CrossGroupUserActivity.updated_at < threshold,
        CrossGroupUserActivity.action_taken == False
    )

    # Выполняем удаление
    result = await session.execute(query)

    # Сохраняем изменения
    await session.commit()

    # Получаем количество удалённых строк
    deleted_count = result.rowcount

    # Логируем результат
    if deleted_count > 0:
        logger.info(
            f"Очищено {deleted_count} старых записей активности "
            f"(старше {max_age_days} дней)"
        )

    return deleted_count


async def mark_action_taken(
    session: AsyncSession,
    user_id: int,
    actioned_groups: list
) -> bool:
    """
    Помечает что действие по детекции было применено.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя
        actioned_groups: Список chat_id где применено действие

    Returns:
        bool: True если запись обновлена
    """
    # Получаем запись активности пользователя
    activity = await get_user_activity(session, user_id)

    # Если записи нет — ничего не делаем
    if activity is None:
        return False

    # Обновляем статус
    activity.action_taken = True
    activity.actioned_groups = actioned_groups

    # Сохраняем в БД
    await session.commit()

    # Логируем
    logger.info(
        f"Помечено действие для пользователя {user_id} "
        f"в {len(actioned_groups)} группах"
    )

    return True
