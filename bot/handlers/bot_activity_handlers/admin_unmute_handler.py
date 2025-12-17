# bot/handlers/bot_activity_handlers/admin_unmute_handler.py
"""
Обработчик размута пользователя админом через Telegram UI.

Цель: Когда админ снимает мут через интерфейс Telegram (не через бота),
деактивировать запись в БД чтобы мут не восстановился при повторном входе.
"""
import logging
from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.filters.chat_member_updated import RESTRICTED, IS_MEMBER, IS_ADMIN
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.restriction_service import deactivate_restriction

logger = logging.getLogger(__name__)

admin_unmute_router = Router()

# Фильтр: только когда пользователь был RESTRICTED и стал MEMBER или ADMIN
# Это позволяет другим handler'ам (например join_handler) обрабатывать остальные события
_UNRESTRICTED_FILTER = ChatMemberUpdatedFilter(member_status_changed=RESTRICTED >> (IS_MEMBER | IS_ADMIN))


@admin_unmute_router.chat_member(_UNRESTRICTED_FILTER)
async def handle_user_unrestricted_by_admin(
    event: ChatMemberUpdated,
    session: AsyncSession,
    bot: Bot,
):
    """
    Обрабатывает изменение статуса пользователя в группе.

    Цель: Определить когда АДМИН снимает мут через Telegram UI,
    чтобы деактивировать запись в БД (is_active = false).

    Это предотвращает повторное восстановление мута при выходе/входе пользователя.

    Условия срабатывания:
    1. Старый статус = restricted (был замучен)
    2. Новый статус = member (снят мут) или administrator
    3. Действие выполнил НЕ бот (from_user != bot)
    """
    # Пропускаем если это не группа/супергруппа
    if event.chat.type not in ("group", "supergroup"):
        return

    new_member = event.new_chat_member
    actor = event.from_user  # Кто выполнил действие

    # Фильтр _UNRESTRICTED_FILTER уже гарантирует:
    # - old_status был RESTRICTED
    # - new_status НЕ RESTRICTED

    # Проверяем что действие выполнил НЕ бот
    bot_info = await bot.get_me()
    if actor.id == bot_info.id:
        # Бот сам снял мут (например через /unmute) - пропускаем
        # Команда /unmute сама вызовет deactivate_restriction
        return

    # Это админ снял мут через Telegram UI
    chat_id = event.chat.id
    user_id = new_member.user.id

    logger.info(
        f"🔓 [ADMIN_UNMUTE] Admin {actor.id} ({actor.full_name}) "
        f"removed restriction from user {user_id} in chat {chat_id}"
    )

    # Деактивируем запись об ограничении в БД
    deactivated = await deactivate_restriction(session, chat_id, user_id)

    if deactivated:
        logger.info(
            f"✅ [ADMIN_UNMUTE] Restriction deactivated in DB: "
            f"chat={chat_id} user={user_id}"
        )
    else:
        logger.debug(
            f"ℹ️ [ADMIN_UNMUTE] No active restriction found in DB: "
            f"chat={chat_id} user={user_id}"
        )
