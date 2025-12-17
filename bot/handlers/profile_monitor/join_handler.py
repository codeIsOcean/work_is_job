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
