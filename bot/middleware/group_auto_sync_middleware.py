"""
Middleware для автоматической синхронизации групп.

При получении любого сообщения/события из группы:
1. Проверяет, есть ли группа в БД
2. Если нет - автоматически создаёт и синхронизирует админов
3. Использует кэш чтобы не синхронизировать слишком часто
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.types import Update, Message, CallbackQuery, ChatMemberUpdated
from aiogram.enums import ChatType

from bot.database.session import get_session
from bot.services.group_auto_sync import ensure_group_exists

logger = logging.getLogger(__name__)


class GroupAutoSyncMiddleware(BaseMiddleware):
    """
    Middleware для автоматической синхронизации групп с БД.

    Срабатывает на:
    - Сообщения из групп
    - CallbackQuery из групп
    - ChatMemberUpdated события
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        # Получаем chat из разных типов событий
        chat = None
        bot: Bot = data.get("bot")

        if event.message and event.message.chat:
            chat = event.message.chat
        elif event.callback_query and event.callback_query.message:
            chat = event.callback_query.message.chat
        elif event.chat_member:
            chat = event.chat_member.chat
        elif event.my_chat_member:
            chat = event.my_chat_member.chat

        # Синхронизируем только группы
        if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and bot:
            try:
                async with get_session() as session:
                    await ensure_group_exists(session, chat, bot)
            except Exception as e:
                # Не блокируем обработку при ошибке синхронизации
                logger.warning(f"⚠️ [AUTO_SYNC] Ошибка синхронизации группы {chat.id}: {e}")

        return await handler(event, data)
