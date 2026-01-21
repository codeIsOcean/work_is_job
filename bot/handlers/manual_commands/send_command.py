# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /asend
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит обработчик команды /asend для отправки сообщений
# от имени бота в группу.
#
# Использование:
# - /asend <текст> — отправить сообщение от имени бота
# - /asend <текст> (ответом на сообщение) — ответить на сообщение от имени бота
#
# Особенности:
# - Только для админов группы
# - Поддержка HTML-форматирования
# - Настраиваемое удаление команды после отправки
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

import logging

from aiogram import Router, Bot, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис для получения настроек
from bot.services.manual_commands import get_manual_command_settings

# Создаём роутер для команды send
send_router = Router(name="send_command")

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ПРОВЕРКА ПРАВ АДМИНА
# ═══════════════════════════════════════════════════════════════════════════
async def is_user_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет является ли пользователь админом группы.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        bool: True если админ или владелец
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ('creator', 'administrator')
    except TelegramAPIError:
        return False


def is_anonymous_admin(message: Message) -> bool:
    """
    Проверяет является ли отправитель анонимным админом группы.

    Анонимный админ — когда админ пишет от имени группы.
    В этом случае sender_chat == chat.

    Args:
        message: Сообщение

    Returns:
        bool: True если анонимный админ
    """
    return (
        message.sender_chat is not None
        and message.sender_chat.id == message.chat.id
    )


# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /asend
# ═══════════════════════════════════════════════════════════════════════════
@send_router.message(
    Command("asend"),
    F.chat.type.in_({"group", "supergroup"})
)
async def cmd_asend(message: Message, bot: Bot, session: AsyncSession):
    """
    Обрабатывает команду /asend.

    Отправляет сообщение от имени бота в группу.
    Поддерживает ответ на сообщение.

    Использование:
    - /asend <текст> — отправить сообщение
    - /asend <текст> (ответом) — ответить на сообщение
    """
    chat_id = message.chat.id

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА ПРАВ: только админы
    # ─────────────────────────────────────────────────────────
    is_admin = False

    # Проверяем анонимного админа
    if is_anonymous_admin(message):
        is_admin = True
        logger.debug(f"[ASEND] Anonymous admin in chat_id={chat_id}")
    # Проверяем обычного пользователя
    elif message.from_user:
        is_admin = await is_user_admin(bot, chat_id, message.from_user.id)

    if not is_admin:
        logger.debug(f"[ASEND] Non-admin tried to use /asend in chat_id={chat_id}")
        # Молча игнорируем — не админ
        return

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧЕНИЕ НАСТРОЕК
    # ─────────────────────────────────────────────────────────
    settings = await get_manual_command_settings(session, chat_id)

    # ─────────────────────────────────────────────────────────
    # ПАРСИНГ ТЕКСТА СООБЩЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Получаем текст после команды /asend
    # message.text = "/asend текст сообщения"
    # Нужно извлечь "текст сообщения"

    text = message.text or ""

    # Убираем команду из начала
    if text.startswith("/asend@"):
        # /asend@botname текст
        parts = text.split(" ", 1)
        text_to_send = parts[1] if len(parts) > 1 else ""
    elif text.startswith("/asend"):
        # /asend текст
        text_to_send = text[6:].strip()
    else:
        text_to_send = ""

    # Проверяем что есть что отправлять
    if not text_to_send:
        # Пустое сообщение — удаляем команду и выходим
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        return

    # ─────────────────────────────────────────────────────────
    # ОПРЕДЕЛЯЕМ REPLY_TO (если ответ на сообщение)
    # ─────────────────────────────────────────────────────────
    reply_to_message_id = None

    if message.reply_to_message:
        reply_to_message_id = message.reply_to_message.message_id

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА СООБЩЕНИЯ ОТ ИМЕНИ БОТА
    # ─────────────────────────────────────────────────────────
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text_to_send,
            reply_to_message_id=reply_to_message_id,
            parse_mode="HTML"
        )
        logger.info(
            f"[ASEND] Message sent in chat_id={chat_id}, "
            f"reply_to={reply_to_message_id}, len={len(text_to_send)}"
        )
    except TelegramAPIError as e:
        logger.error(f"[ASEND] Failed to send message: {e}")
        # Не удалось отправить — оставляем команду для диагностики
        return

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ КОМАНДЫ /asend (если включено в настройках)
    # ─────────────────────────────────────────────────────────
    if settings.send_delete_command:
        try:
            await message.delete()
        except TelegramAPIError as e:
            logger.debug(f"[ASEND] Failed to delete command: {e}")
