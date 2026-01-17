# bot/services/antiraid/journal_service.py
"""
Сервис отправки уведомлений в журнал группы для модуля Anti-Raid.

Отправляет детальные сообщения о:
- Бане по паттернам имени
- Частых входах/выходах
- Детекции рейда
- Массовых инвайтах
- Массовых реакциях

ВАЖНО: Использует существующий group_journal_service для получения канала журнала.
Каждая группа может иметь свой канал журнала (/linkjournal).
"""

# Импортируем логгер для записи событий
import logging
# Импортируем типы для аннотаций
from typing import Optional

# Импортируем Bot и типы из aiogram
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис журнала
from bot.services.group_journal_service import get_group_journal_channel

# Импортируем модели
from bot.database.models_antiraid import AntiRaidNamePattern

# Импортируем результаты проверок
from bot.services.antiraid.name_pattern_checker import NameCheckResult
from bot.services.antiraid.action_service import ActionResult


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


def _get_user_link(user_id: int, name: str) -> str:
    """
    Создаёт HTML ссылку на пользователя.

    Args:
        user_id: ID пользователя
        name: Имя для отображения

    Returns:
        HTML ссылка вида <a href="tg://user?id=123">Имя</a>
    """
    # Экранируем HTML символы в имени
    safe_name = (
        name
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def _create_name_pattern_journal_keyboard(
    chat_id: int,
    user_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для сообщения в журнале о бане по имени.

    Кнопки:
    - Разбанить
    - ОК (закрыть)

    Args:
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        InlineKeyboardMarkup с кнопками
    """
    # Создаём кнопки
    # Callback data формат: ar:action:chat_id:user_id
    # ar = antiraid (короткий префикс для 64 байт лимита)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            # Кнопка разбана
            InlineKeyboardButton(
                text="Разбанить",
                callback_data=f"ar:unban:{chat_id}:{user_id}"
            ),
            # Кнопка OK (просто закрывает/удаляет сообщение)
            InlineKeyboardButton(
                text="OK",
                callback_data=f"ar:ok:{chat_id}:{user_id}"
            ),
        ]
    ])

    return keyboard


async def send_name_pattern_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    check_result: NameCheckResult,
    action_result: ActionResult
) -> Optional[int]:
    """
    Отправляет сообщение в журнал о бане по паттерну имени.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя
        check_result: Результат проверки имени
        action_result: Результат применения действия

    Returns:
        ID отправленного сообщения или None если не удалось
    """
    # ─────────────────────────────────────────────────────────
    # Получаем канал журнала для группы
    # ─────────────────────────────────────────────────────────
    journal = await get_group_journal_channel(session, chat_id)

    # Если журнал не привязан — логируем и выходим
    if journal is None:
        logger.debug(
            f"[ANTIRAID] Журнал не привязан для chat_id={chat_id}, "
            f"пропускаем отправку уведомления"
        )
        return None

    journal_channel_id = journal.journal_channel_id

    # ─────────────────────────────────────────────────────────
    # Формируем текст сообщения
    # ─────────────────────────────────────────────────────────
    # Экранируем имена для HTML
    original_name_safe = (
        check_result.original_name
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )

    # Определяем текст действия
    if action_result.action_type == 'ban':
        if action_result.duration_hours == 0:
            action_text = "Бан навсегда"
        else:
            action_text = f"Бан на {action_result.duration_hours}ч"
    elif action_result.action_type == 'kick':
        action_text = "Кик"
    else:
        action_text = action_result.action_type

    # Получаем паттерн который сработал
    pattern_text = ""
    if check_result.pattern:
        pattern_text = check_result.pattern.pattern

    # Формируем сообщение
    # Используем HTML разметку
    message_text = (
        f"<b>⛔ #ANTIRAID | Бан по имени</b>\n"
        f"\n"
        f"👤 <b>Имя:</b> {original_name_safe}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📝 <b>Паттерн:</b> <code>{pattern_text}</code>\n"
        f"🔄 <b>Нормализация:</b> <code>{check_result.normalized_name}</code>\n"
        f"\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    # Если действие не удалось — добавляем ошибку
    if not action_result.success:
        message_text += f"\n⚠️ <b>Ошибка:</b> {action_result.error_message}"

    # Добавляем хештеги для поиска
    message_text += f"\n\n#name_pattern #antiraid #id{user_id}"

    # ─────────────────────────────────────────────────────────
    # Создаём клавиатуру
    # ─────────────────────────────────────────────────────────
    keyboard = _create_name_pattern_journal_keyboard(chat_id, user_id)

    # ─────────────────────────────────────────────────────────
    # Отправляем сообщение в журнал
    # ─────────────────────────────────────────────────────────
    try:
        message = await bot.send_message(
            chat_id=journal_channel_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        logger.info(
            f"[ANTIRAID] Отправлено в журнал: chat_id={chat_id}, "
            f"journal_id={journal_channel_id}, message_id={message.message_id}"
        )

        return message.message_id

    except TelegramAPIError as e:
        # Ошибка отправки в журнал — логируем но НЕ прерываем основной флоу
        logger.error(
            f"[ANTIRAID] Ошибка отправки в журнал: chat_id={chat_id}, "
            f"journal_id={journal_channel_id}, error={e}"
        )
        return None


async def send_join_exit_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    user_name: str,
    event_count: int,
    window_seconds: int,
    action_result: ActionResult
) -> Optional[int]:
    """
    Отправляет сообщение в журнал о частых входах/выходах.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя
        user_name: Имя пользователя
        event_count: Количество событий
        window_seconds: Временное окно в секундах
        action_result: Результат применения действия

    Returns:
        ID отправленного сообщения или None
    """
    # Получаем канал журнала
    journal = await get_group_journal_channel(session, chat_id)
    if journal is None:
        return None

    journal_channel_id = journal.journal_channel_id

    # Экранируем имя
    user_name_safe = (
        user_name
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )

    # Определяем текст действия
    if action_result.action_type == 'ban':
        if action_result.duration_hours == 0:
            action_text = "Бан навсегда"
        else:
            action_text = f"Бан на {action_result.duration_hours}ч"
    elif action_result.action_type == 'kick':
        action_text = "Кик"
    elif action_result.action_type == 'mute':
        action_text = f"Мут на {action_result.duration_hours}ч"
    else:
        action_text = action_result.action_type

    # Формируем сообщение
    message_text = (
        f"<b>⚠️ #ANTIRAID | Частые входы/выходы</b>\n"
        f"\n"
        f"👤 <b>Пользователь:</b> {user_name_safe}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🔢 <b>События:</b> {event_count} за {window_seconds} сек\n"
        f"\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    if not action_result.success:
        message_text += f"\n⚠️ <b>Ошибка:</b> {action_result.error_message}"

    message_text += f"\n\n#join_exit #antiraid #id{user_id}"

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Разбанить" if action_result.action_type == 'ban' else "Размутить",
                callback_data=f"ar:unban:{chat_id}:{user_id}"
            ),
            InlineKeyboardButton(
                text="Бан навсегда",
                callback_data=f"ar:permban:{chat_id}:{user_id}"
            ),
            InlineKeyboardButton(
                text="OK",
                callback_data=f"ar:ok:{chat_id}:{user_id}"
            ),
        ]
    ])

    try:
        message = await bot.send_message(
            chat_id=journal_channel_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return message.message_id
    except TelegramAPIError as e:
        logger.error(f"[ANTIRAID] Ошибка отправки в журнал: {e}")
        return None


async def send_raid_detected_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    join_count: int,
    window_seconds: int,
    action_taken: str,
    slowmode_seconds: int = 0,
    auto_unlock_minutes: int = 0
) -> Optional[int]:
    """
    Отправляет сообщение в журнал о детекции рейда.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        join_count: Количество вступлений
        window_seconds: Временное окно
        action_taken: Применённое действие (slowmode/lock/notify)
        slowmode_seconds: Значение slowmode (если применимо)
        auto_unlock_minutes: Время до авто-снятия

    Returns:
        ID отправленного сообщения или None
    """
    # Получаем канал журнала
    journal = await get_group_journal_channel(session, chat_id)
    if journal is None:
        return None

    journal_channel_id = journal.journal_channel_id

    # Определяем текст действия
    if action_taken == 'slowmode':
        action_text = f"Slowmode {slowmode_seconds} сек"
    elif action_taken == 'lock':
        action_text = "Группа закрыта"
    else:
        action_text = "Уведомление"

    # Формируем сообщение
    message_text = (
        f"<b>🚨 #ANTIRAID | Рейд детектирован!</b>\n"
        f"\n"
        f"🔢 <b>Вступлений:</b> {join_count} за {window_seconds} сек\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    if auto_unlock_minutes > 0:
        message_text += f"⏱ <b>Авто-снятие через:</b> {auto_unlock_minutes} мин\n"

    message_text += f"\n#raid #antiraid #mass_join"

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Снять slowmode",
                callback_data=f"ar:unslowmode:{chat_id}:0"
            ),
            InlineKeyboardButton(
                text="Закрыть группу",
                callback_data=f"ar:lock:{chat_id}:0"
            ),
            InlineKeyboardButton(
                text="OK",
                callback_data=f"ar:ok:{chat_id}:0"
            ),
        ]
    ])

    try:
        message = await bot.send_message(
            chat_id=journal_channel_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return message.message_id
    except TelegramAPIError as e:
        logger.error(f"[ANTIRAID] Ошибка отправки в журнал: {e}")
        return None
