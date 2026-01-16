# bot/handlers/profile_monitor/join_handler.py
"""
Handler для создания snapshot профиля при входе пользователя в группу.

Использует событие chat_member_updated с JOIN_TRANSITION для отслеживания
ВСЕХ случаев входа:
- Одобрение join request (закрытая группа)
- Самостоятельный вход (открытая группа)
- Приглашение другим участником

ВАЖНО: Этот handler работает НЕЗАВИСИМО от капчи!
Он просто создаёт snapshot профиля для последующего сравнения.
"""

import logging

from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.profile_monitor import (
    get_profile_monitor_settings,
    create_snapshot_on_join,
)
# Импортируем функции кросс-групповой детекции
from bot.services.cross_group.detection_service import (
    track_user_join,
    check_cross_group_detection,
)
# Импортируем функцию применения действия при детекции
from bot.services.cross_group.action_service import apply_cross_group_action


# Логгер модуля
logger = logging.getLogger(__name__)

# Роутер для событий входа
router = Router(name="profile_monitor_join")


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def handle_user_joined(
    event: ChatMemberUpdated,
    session: AsyncSession,
) -> None:
    """
    Создаёт snapshot профиля при входе пользователя в группу.

    Это событие срабатывает когда статус пользователя меняется на "member":
    - После одобрения join request
    - При самостоятельном входе в открытую группу
    - При приглашении другим участником

    Args:
        event: Событие изменения статуса участника
        session: AsyncSession (инжектится middleware)
    """
    # Пропускаем ботов
    if event.new_chat_member.user.is_bot:
        return

    # Извлекаем данные
    chat_id = event.chat.id
    user = event.new_chat_member.user
    user_id = user.id

    # ─────────────────────────────────────────────────────────────────────
    # КРОСС-ГРУППОВАЯ ДЕТЕКЦИЯ: трекинг входа пользователя
    # Работает независимо от Profile Monitor
    # ─────────────────────────────────────────────────────────────────────
    try:
        # Записываем факт входа пользователя в группу
        await track_user_join(
            session=session,
            user_id=user_id,
            chat_id=chat_id,
        )
        # Логируем трекинг
        logger.debug(
            f"[CROSS_GROUP] Tracked join: user={user_id} chat={chat_id}"
        )
        # Проверяем детекцию (срабатывает если выполнены все условия)
        detection_result = await check_cross_group_detection(
            session=session,
            user_id=user_id,
        )
        # Если детекция сработала — применяем действие
        if detection_result:
            # Логируем детекцию скамера
            logger.warning(
                f"[CROSS_GROUP] DETECTED SCAMMER on JOIN: "
                f"user={user_id} groups={detection_result.get('groups', [])}"
            )
            # Применяем действие во всех затронутых группах
            await apply_cross_group_action(
                session=session,
                bot=event.bot,
                user_id=user_id,
                detection_data=detection_result,
            )
    except Exception as e:
        # Ошибки кросс-групповой детекции не должны ломать основной флоу
        logger.error(f"[CROSS_GROUP] Error in join tracking: {e}")

    # Проверяем включён ли модуль Profile Monitor для этой группы
    settings = await get_profile_monitor_settings(session, chat_id)
    if not settings or not settings.enabled:
        logger.debug(
            f"[PROFILE_MONITOR] Skip join snapshot: chat={chat_id} "
            f"user={user_id} (module disabled)"
        )
        return

    # Создаём snapshot профиля
    logger.info(
        f"[PROFILE_MONITOR] Creating snapshot on JOIN: "
        f"chat={chat_id} user={user_id} name='{user.first_name}'"
    )

    snapshot = await create_snapshot_on_join(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        is_premium=user.is_premium or False,
    )

    if snapshot:
        logger.info(
            f"[PROFILE_MONITOR] Snapshot created on JOIN: "
            f"chat={chat_id} user={user_id} has_photo={snapshot.has_photo}"
        )
    else:
        logger.warning(
            f"[PROFILE_MONITOR] Failed to create snapshot on JOIN: "
            f"chat={chat_id} user={user_id}"
        )
