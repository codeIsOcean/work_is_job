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

    # Создаём кликабельную ссылку на пользователя
    user_link = _get_user_link(user_id, check_result.original_name)

    # Формируем сообщение
    # Используем HTML разметку с чётким визуальным разделением
    message_text = (
        f"<b>⛔ ANTI-RAID: Запрещённое имя</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"👤 <b>Пользователь:</b> {user_link}\n"
        f"    <i>ID:</i> <code>{user_id}</code>\n"
        f"\n"
        f"🔍 <b>Причина бана:</b>\n"
        f"    <i>Паттерн:</i> <code>{pattern_text}</code>\n"
        f"    <i>После нормализации:</i> <code>{check_result.normalized_name}</code>\n"
        f"\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    # Если действие не удалось — добавляем ошибку
    if not action_result.success:
        message_text += f"\n❌ <b>Ошибка:</b> {action_result.error_message}"

    # Добавляем разделитель и хештеги для поиска
    message_text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"#name_pattern #antiraid #user{user_id}"
    )

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

    # Создаём кликабельную ссылку на пользователя
    user_link = _get_user_link(user_id, user_name)

    # Формируем сообщение с чётким визуальным разделением
    message_text = (
        f"<b>⚠️ ANTI-RAID: Частые входы/выходы</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"👤 <b>Пользователь:</b> {user_link}\n"
        f"    <i>ID:</i> <code>{user_id}</code>\n"
        f"\n"
        f"🔍 <b>Причина:</b>\n"
        f"    <i>Злоупотребление:</i> {event_count} входов/выходов\n"
        f"    <i>За период:</i> {window_seconds} секунд\n"
        f"\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    if not action_result.success:
        message_text += f"\n❌ <b>Ошибка:</b> {action_result.error_message}"

    message_text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"#join_exit #antiraid #user{user_id}"
    )

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


def _format_raid_journal_text(
    join_count: int,
    window_seconds: int,
    banned_count: int,
    protection_seconds: int,
    action_taken: str,
    slowmode_seconds: int = 0,
    is_active: bool = True
) -> str:
    """
    Формирует текст сообщения о рейде.

    Используется для создания и обновления агрегированного уведомления.

    Args:
        join_count: Количество вступлений при детекции
        window_seconds: Временное окно
        banned_count: Сколько забанено ВСЕГО
        protection_seconds: Длительность protection mode
        action_taken: Применённое действие
        slowmode_seconds: Значение slowmode
        is_active: Protection mode ещё активен?

    Returns:
        Отформатированный HTML текст
    """
    # Статус
    if is_active:
        status = "🔴 АКТИВЕН"
    else:
        status = "🟢 ЗАВЕРШЁН"

    # Определяем текст действия
    if action_taken == 'ban':
        action_text = "Бан рейдеров"
    elif action_taken == 'slowmode':
        action_text = f"Slowmode {slowmode_seconds} сек"
    elif action_taken == 'lock':
        action_text = "Группа закрыта"
    else:
        action_text = "Уведомление"

    # Формируем сообщение
    message_text = (
        f"<b>🚨 #ANTIRAID | Рейд детектирован!</b>\n"
        f"\n"
        f"📊 <b>Статус:</b> {status}\n"
        f"🔢 <b>Вступлений при детекции:</b> {join_count} за {window_seconds} сек\n"
        f"🚫 <b>Забанено:</b> {banned_count}\n"
        f"🛡️ <b>Режим защиты:</b> {protection_seconds} сек\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
        f"\n"
        f"#raid #antiraid #mass_join"
    )

    return message_text


def _create_raid_journal_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для сообщения о рейде.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Снять защиту",
                callback_data=f"ar:unprotect:{chat_id}:0"
            ),
            InlineKeyboardButton(
                text="OK",
                callback_data=f"ar:ok:{chat_id}:0"
            ),
        ]
    ])
    return keyboard


async def send_raid_detected_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    join_count: int,
    window_seconds: int,
    banned_count: int,
    protection_seconds: int,
    action_taken: str = 'ban',
    slowmode_seconds: int = 0
) -> Optional[int]:
    """
    Отправляет агрегированное сообщение в журнал о детекции рейда.

    Это ПЕРВОЕ уведомление при обнаружении рейда.
    Потом оно обновляется через update_raid_journal.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        join_count: Количество вступлений при детекции
        window_seconds: Временное окно
        banned_count: Сколько забанено (на момент детекции)
        protection_seconds: Длительность protection mode
        action_taken: Применённое действие (ban/slowmode/lock/notify)
        slowmode_seconds: Значение slowmode (если применимо)

    Returns:
        ID отправленного сообщения или None
    """
    # Получаем канал журнала
    journal = await get_group_journal_channel(session, chat_id)
    if journal is None:
        return None

    journal_channel_id = journal.journal_channel_id

    # Формируем текст
    message_text = _format_raid_journal_text(
        join_count=join_count,
        window_seconds=window_seconds,
        banned_count=banned_count,
        protection_seconds=protection_seconds,
        action_taken=action_taken,
        slowmode_seconds=slowmode_seconds,
        is_active=True
    )

    # Создаём клавиатуру
    keyboard = _create_raid_journal_keyboard(chat_id)

    try:
        message = await bot.send_message(
            chat_id=journal_channel_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        logger.info(
            f"[ANTIRAID] Raid journal отправлен: chat_id={chat_id}, "
            f"message_id={message.message_id}, banned={banned_count}"
        )

        return message.message_id

    except TelegramAPIError as e:
        logger.error(f"[ANTIRAID] Ошибка отправки raid journal: {e}")
        return None


async def update_raid_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    journal_message_id: int,
    join_count: int,
    window_seconds: int,
    banned_count: int,
    protection_seconds: int,
    action_taken: str = 'ban',
    slowmode_seconds: int = 0,
    is_active: bool = True
) -> bool:
    """
    Обновляет существующее сообщение о рейде в журнале.

    Вызывается при каждом бане в protection mode чтобы
    обновить счётчик забаненных.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        journal_message_id: ID сообщения для обновления
        join_count: Количество вступлений при детекции
        window_seconds: Временное окно
        banned_count: Текущее количество забаненных
        protection_seconds: Длительность protection mode
        action_taken: Применённое действие
        slowmode_seconds: Значение slowmode
        is_active: Protection mode ещё активен?

    Returns:
        True если успешно обновлено
    """
    # Получаем канал журнала
    journal = await get_group_journal_channel(session, chat_id)
    if journal is None:
        return False

    journal_channel_id = journal.journal_channel_id

    # Формируем текст
    message_text = _format_raid_journal_text(
        join_count=join_count,
        window_seconds=window_seconds,
        banned_count=banned_count,
        protection_seconds=protection_seconds,
        action_taken=action_taken,
        slowmode_seconds=slowmode_seconds,
        is_active=is_active
    )

    # Создаём клавиатуру
    keyboard = _create_raid_journal_keyboard(chat_id)

    try:
        await bot.edit_message_text(
            chat_id=journal_channel_id,
            message_id=journal_message_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        logger.debug(
            f"[ANTIRAID] Raid journal обновлён: chat_id={chat_id}, "
            f"banned={banned_count}, is_active={is_active}"
        )

        return True

    except TelegramAPIError as e:
        # "message is not modified" — игнорируем
        if "message is not modified" in str(e):
            return True
        logger.error(f"[ANTIRAID] Ошибка обновления raid journal: {e}")
        return False


async def send_mass_invite_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    inviter_id: int,
    inviter_name: str,
    invite_count: int,
    window_seconds: int,
    action_result: ActionResult
) -> Optional[int]:
    """
    Отправляет сообщение в журнал о массовых инвайтах.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        inviter_id: ID инвайтера
        inviter_name: Имя инвайтера
        invite_count: Количество инвайтов
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

    # Создаём кликабельную ссылку на инвайтера
    inviter_link = _get_user_link(inviter_id, inviter_name)

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
    elif action_result.action_type == 'warn':
        action_text = "Предупреждение"
    else:
        action_text = action_result.action_type

    # Формируем сообщение с кликабельным именем
    message_text = (
        f"<b>📨 ANTI-RAID: Массовые инвайты</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"👤 <b>Инвайтер:</b> {inviter_link}\n"
        f"    <i>ID:</i> <code>{inviter_id}</code>\n"
        f"\n"
        f"🔍 <b>Причина:</b>\n"
        f"    <i>Инвайтов:</i> {invite_count} за {window_seconds} сек\n"
        f"\n"
        f"⚡ <b>Действие:</b> {action_text}\n"
    )

    if not action_result.success:
        message_text += f"\n❌ <b>Ошибка:</b> {action_result.error_message}"

    message_text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"#mass_invite #antiraid #user{inviter_id}"
    )

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Разбанить" if action_result.action_type == 'ban' else "Размутить",
                callback_data=f"ar:unban:{chat_id}:{inviter_id}"
            ),
            InlineKeyboardButton(
                text="Бан навсегда",
                callback_data=f"ar:permban:{chat_id}:{inviter_id}"
            ),
            InlineKeyboardButton(
                text="OK",
                callback_data=f"ar:ok:{chat_id}:{inviter_id}"
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
        logger.error(f"[ANTIRAID] Ошибка отправки в журнал (mass_invite): {e}")
        return None


async def send_mass_reaction_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    user_name: str,
    abuse_type: str,
    reaction_count: int,
    window_seconds: int,
    action_result: ActionResult,
    message_id: Optional[int] = None
) -> Optional[int]:
    """
    Отправляет сообщение в журнал о массовых реакциях.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя
        user_name: Имя пользователя
        abuse_type: Тип злоупотребления ('user' или 'message')
        reaction_count: Количество реакций
        window_seconds: Временное окно в секундах
        action_result: Результат применения действия
        message_id: ID сообщения (для message abuse)

    Returns:
        ID отправленного сообщения или None
    """
    # Получаем канал журнала
    journal = await get_group_journal_channel(session, chat_id)
    if journal is None:
        return None

    journal_channel_id = journal.journal_channel_id

    # Создаём кликабельную ссылку на пользователя
    user_link = _get_user_link(user_id, user_name)

    # Определяем текст действия
    if action_result.action_type == 'mute':
        action_text = f"Мут на {action_result.duration_hours}ч" if action_result.duration_hours > 0 else "Мут"
    elif action_result.action_type == 'kick':
        action_text = "Кик"
    elif action_result.action_type == 'ban':
        action_text = f"Бан на {action_result.duration_hours}ч"
    elif action_result.action_type == 'warn':
        action_text = "Предупреждение"
    else:
        action_text = action_result.action_type

    # Определяем тип abuse
    if abuse_type == 'user':
        abuse_text = "Спам реакциями (per-user)"
    else:
        abuse_text = "Атака на сообщение (per-message)"

    # Формируем сообщение
    message_text = (
        f"<b>😡 #ANTIRAID | Массовые реакции</b>\n"
        f"\n"
        f"👤 <b>Пользователь:</b> {user_link}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📌 <b>Тип:</b> {abuse_text}\n"
        f"🔢 <b>Реакций:</b> {reaction_count} за {window_seconds} сек\n"
    )

    if message_id:
        message_text += f"💬 <b>Сообщение:</b> <code>{message_id}</code>\n"

    message_text += f"\n⚡ <b>Действие:</b> {action_text}\n"

    if not action_result.success:
        message_text += f"\n⚠️ <b>Ошибка:</b> {action_result.error_message}"

    message_text += f"\n\n#mass_reaction #antiraid #id{user_id}"

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Размутить" if action_result.action_type == 'mute' else "Разбанить",
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
        logger.error(f"[ANTIRAID] Ошибка отправки в журнал (mass_reaction): {e}")
        return None
