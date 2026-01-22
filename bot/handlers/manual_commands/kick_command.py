# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /akick
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит обработчик команды /akick:
# - Кик пользователя (ответом на сообщение или по @username/id)
# - Пользователь может вернуться после кика
#
# Создано: 2026-01-22
# ═══════════════════════════════════════════════════════════════════════════

import logging
import html
import asyncio
from datetime import datetime, timezone

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, User, LinkPreviewOptions
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы
from bot.services.manual_commands import (
    get_manual_command_settings,
    apply_kick,
    format_user_link,
)
# Импортируем парсер команд
from bot.services.manual_commands.parser import ParsedCommand

# Импортируем сервис журнала
from bot.services.group_journal_service import get_group_journal_channel
# Импортируем модель группы
from bot.database.models import Group

# Создаём роутер для команды кика
kick_router = Router(name="kick_command")

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ОТЛОЖЕННОЕ УДАЛЕНИЕ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
async def delayed_delete(message: Message, delay_seconds: int):
    """
    Удаляет сообщение после задержки.

    Args:
        message: Сообщение для удаления
        delay_seconds: Задержка в секундах
    """
    try:
        await asyncio.sleep(delay_seconds)
        await message.delete()
        logger.debug(f"[MANUAL_CMD] Delayed delete: msg_id={message.message_id} after {delay_seconds}s")
    except TelegramAPIError as e:
        logger.debug(f"[MANUAL_CMD] Failed to delete after delay: {e}")
    except asyncio.CancelledError:
        pass  # Задача отменена — игнорируем


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
        # Получаем информацию о члене группы
        member = await bot.get_chat_member(chat_id, user_id)
        # Проверяем статус — creator или administrator
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
# ХЕЛПЕР: ПАРСИНГ КОМАНДЫ /akick
# ═══════════════════════════════════════════════════════════════════════════
def parse_kick_command(text: str, has_reply: bool = False) -> ParsedCommand:
    """
    Парсит текст команды /akick и извлекает target и reason.

    Форматы команды:
    1. /akick                → reply
    2. /akick причина        → reply с причиной
    3. /akick @username      → кик @username
    4. /akick @username спам → кик @username с причиной
    5. /akick 123456789      → кик по user_id
    6. /akick 123456789 спам → кик по user_id с причиной

    Args:
        text: Полный текст сообщения с командой
        has_reply: True если сообщение является ответом на другое

    Returns:
        ParsedCommand: Результат парсинга
    """
    import re

    # Создаём результат с дефолтными значениями
    result = ParsedCommand()

    # Убираем команду из начала текста
    # Поддерживаем /akick и /akick@botname
    text = re.sub(r'^/akick(@\w+)?\s*', '', text, flags=re.IGNORECASE).strip()

    # Если текст пустой — используем reply
    if not text:
        if has_reply:
            result.target_type = 'reply'
        return result

    # Разбиваем текст на части
    parts = text.split()

    # Индекс текущей позиции парсинга
    idx = 0

    # ─── Пытаемся найти target (@username или user_id) ───
    first_part = parts[0]

    # Проверяем на @username
    if first_part.startswith('@'):
        result.target = first_part  # Сохраняем с @
        result.target_type = 'username'
        idx = 1
    # Проверяем на user_id (число больше 10000 — чтобы не путать)
    elif first_part.isdigit() and int(first_part) > 10000:
        result.target = first_part
        result.target_type = 'user_id'
        idx = 1
    # Если нет target — используем reply
    elif has_reply:
        result.target_type = 'reply'
    else:
        result.target_type = 'reply'

    # ─── Остаток — это причина ───
    if idx < len(parts):
        result.reason = ' '.join(parts[idx:])

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ПОСТРОЕНИЕ СООБЩЕНИЯ ДЛЯ ЖУРНАЛА
# ═══════════════════════════════════════════════════════════════════════════
def build_journal_message(
    group_title: str,
    target_user: User | None,
    target_id: int,
    admin_user: User | None,
    reason: str | None,
    chat_id: int | None = None,
    group_username: str | None = None,
) -> str:
    """
    Строит HTML сообщение для журнала.

    Args:
        group_title: Название группы
        target_user: Объект User (цель кика)
        target_id: ID цели
        admin_user: Объект User (админ)
        reason: Причина
        chat_id: ID группы (для ссылки)
        group_username: Username группы (для ссылки)

    Returns:
        str: HTML текст сообщения
    """
    # Заголовок с хештегами
    header = "👢 <b>#РУЧНОЙ_КИК</b>"

    # Название группы (с ссылкой если возможно)
    escaped_title = html.escape(group_title)
    if group_username:
        # Публичная группа — ссылка через username
        group_link = f'<a href="https://t.me/{group_username}">{escaped_title}</a>'
    elif chat_id:
        # Приватная группа — ссылка через chat_id
        real_id = str(chat_id).replace("-100", "")
        group_link = f'<a href="tg://openmessage?chat_id={real_id}">{escaped_title}</a>'
    else:
        group_link = escaped_title
    group_line = f"\n\n📍 <b>Группа:</b> {group_link}"

    # Информация о нарушителе
    if target_user:
        # Ссылка на пользователя
        user_link = format_user_link(target_user)
        username = f"@{target_user.username}" if target_user.username else "—"
        target_line = (
            f"\n\n👤 <b>Пользователь:</b> {user_link}"
            f"\n    {username} | ID: <code>{target_id}</code>"
        )
    else:
        target_line = f"\n\n👤 <b>Пользователь:</b> ID: <code>{target_id}</code>"

    # Информация об админе
    if admin_user:
        admin_link = format_user_link(admin_user)
        admin_username = f"@{admin_user.username}" if admin_user.username else "—"
        admin_line = f"\n\n👮 <b>Админ:</b> {admin_link} ({admin_username})"
    else:
        # Анонимный админ (пишет от имени группы)
        admin_line = "\n\n👮 <b>Админ:</b> Анонимный администратор"

    # Причина
    if reason:
        reason_line = f"\n📝 <b>Причина:</b> {html.escape(reason)}"
    else:
        reason_line = ""

    # Дата
    now = datetime.now(timezone.utc)
    date_line = f"\n🕐 <b>Дата:</b> {now.strftime('%d.%m.%Y %H:%M')} UTC"

    # Примечание
    note_line = "\n\n<i>Пользователь может вернуться по ссылке</i>"

    # Собираем всё вместе
    message = (
        f"{header}"
        f"{group_line}"
        f"{target_line}"
        f"{admin_line}"
        f"{reason_line}"
        f"{date_line}"
        f"{note_line}"
    )

    return message


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ПОСТРОЕНИЕ КЛАВИАТУРЫ ДЛЯ ЖУРНАЛА
# ═══════════════════════════════════════════════════════════════════════════
def build_journal_keyboard(
    target_id: int,
    chat_id: int,
) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру с кнопками для журнала.

    Args:
        target_id: ID пользователя
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    buttons = []

    # Кнопка бана
    buttons.append(
        InlineKeyboardButton(
            text="🚫 Бан",
            callback_data=f"mc:ban:{target_id}:{chat_id}"
        )
    )

    # Кнопка OK (закрыть)
    buttons.append(
        InlineKeyboardButton(
            text="✅ OK",
            callback_data=f"mc:ok:{target_id}:{chat_id}"
        )
    )

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /akick
# ═══════════════════════════════════════════════════════════════════════════
@kick_router.message(Command("akick"))
async def handle_akick_command(
    message: Message,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработчик команды /akick.

    Форматы:
    - /akick                 → кик reply
    - /akick причина         → кик reply с причиной
    - /akick @user спам      → кик @user с причиной
    - /akick 123456 скам     → кик user_id с причиной
    """
    # ─── Шаг 1: Проверяем что команда из группы ───
    if message.chat.type not in ('group', 'supergroup'):
        await message.reply("❌ Эта команда работает только в группах")
        return

    # ─── Шаг 2: Проверяем что отправитель — админ ───
    # Поддерживаем анонимных админов (sender_chat == chat)
    if is_anonymous_admin(message):
        # Анонимный админ — разрешаем
        admin_id = message.chat.id  # Используем ID группы как "admin_id"
        admin_user = None
    else:
        admin_id = message.from_user.id
        admin_user = message.from_user
        if not await is_user_admin(bot, message.chat.id, admin_id):
            await message.reply("❌ Эта команда только для администраторов")
            return

    # ─── Шаг 3: Парсим команду ───
    has_reply = message.reply_to_message is not None
    parsed = parse_kick_command(message.text, has_reply=has_reply)

    # ─── Шаг 4: Определяем цель кика ───
    target_id = 0
    target_user = None

    if parsed.target_type == 'reply':
        # Кик по reply на сообщение
        if not message.reply_to_message:
            await message.reply(
                "❌ Ответьте на сообщение пользователя которого хотите кикнуть\n"
                "Или укажите @username или ID: <code>/akick @user причина</code>",
                parse_mode="HTML"
            )
            return
        target_id = message.reply_to_message.from_user.id
        target_user = message.reply_to_message.from_user

    elif parsed.target_type == 'username':
        # Кик по @username — пока не поддерживается
        await message.reply(
            "❌ Кик по @username пока не поддерживается.\n"
            "Ответьте на сообщение пользователя или используйте его ID:\n"
            "<code>/akick 123456789 причина</code>",
            parse_mode="HTML"
        )
        return

    elif parsed.target_type == 'user_id':
        # Кик по user_id
        target_id = int(parsed.target)
        # Пробуем получить информацию о пользователе
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
            target_user = member.user
        except TelegramAPIError:
            # Пользователь не в группе
            await message.reply("❌ Пользователь не найден в группе")
            return

    # Проверяем что target_id валидный
    if target_id == 0:
        await message.reply("❌ Не удалось определить пользователя для кика")
        return

    # ─── Шаг 5: Получаем настройки модуля ───
    settings = await get_manual_command_settings(session, message.chat.id)

    # ─── Шаг 6: Применяем кик ───
    kick_result = await apply_kick(
        bot=bot,
        session=session,
        chat_id=message.chat.id,
        user_id=target_id,
        admin_id=admin_id,
        reason=parsed.reason,
    )

    # ─── Шаг 7: Проверяем результат ───
    if not kick_result.success:
        await message.reply(f"❌ {kick_result.error}")
        return

    # ─── Шаг 8: Удаляем сообщение нарушителя (если включено) ───
    if settings.kick_delete_message and message.reply_to_message:
        delete_delay = getattr(settings, 'kick_delete_delay', 0) or 0
        if delete_delay > 0:
            # Отложенное удаление
            asyncio.create_task(delayed_delete(message.reply_to_message, delete_delay))
        else:
            # Мгновенное удаление
            try:
                await message.reply_to_message.delete()
            except TelegramAPIError as e:
                logger.warning(f"[MANUAL_CMD] Failed to delete message: {e}")

    # ─── Шаг 9: Отправляем уведомление в группу (если включено) ───
    notify_message = None
    if settings.kick_notify_group:
        # Формируем ссылку на пользователя
        if target_user:
            user_link = format_user_link(target_user)
        else:
            user_link = f"<code>{target_id}</code>"

        # Формируем ссылку на админа
        if admin_user:
            admin_link = format_user_link(admin_user)
        else:
            admin_link = "Анонимный администратор"

        # Проверяем есть ли кастомный текст
        custom_text = getattr(settings, 'kick_notify_text', None)
        if custom_text:
            # Используем кастомный текст с подстановкой переменных
            notify_text = custom_text
            notify_text = notify_text.replace('%user%', user_link)
            notify_text = notify_text.replace('%reason%', html.escape(parsed.reason or '—'))
            notify_text = notify_text.replace('%admin%', admin_link)
        else:
            # Стандартный текст
            notify_text = f"👢 {user_link} кикнут из группы."

            # Добавляем причину если есть
            if parsed.reason:
                notify_text += f"\n📝 Причина: {html.escape(parsed.reason)}"

        notify_message = await message.answer(notify_text, parse_mode="HTML")

        # Отложенное удаление уведомления (если настроено)
        notify_delete_delay = getattr(settings, 'kick_notify_delete_delay', 0) or 0
        if notify_delete_delay > 0 and notify_message:
            asyncio.create_task(delayed_delete(notify_message, notify_delete_delay))

    # ─── Шаг 10: Отправляем в журнал ───
    # Получаем канал журнала для этой группы
    journal = await get_group_journal_channel(session, message.chat.id)

    if journal and journal.journal_channel_id:
        try:
            # Получаем название группы
            group_query = await session.execute(
                select(Group).where(Group.chat_id == message.chat.id)
            )
            group = group_query.scalar_one_or_none()
            group_title = group.title if group else message.chat.title or str(message.chat.id)

            # Строим сообщение журнала
            journal_text = build_journal_message(
                group_title=group_title,
                target_user=target_user,
                target_id=target_id,
                admin_user=admin_user,
                reason=parsed.reason,
                chat_id=message.chat.id,
                group_username=message.chat.username,
            )

            # Строим клавиатуру
            keyboard = build_journal_keyboard(
                target_id=target_id,
                chat_id=message.chat.id,
            )

            # Отправляем в журнал (без превью ссылок)
            await bot.send_message(
                chat_id=journal.journal_channel_id,
                text=journal_text,
                parse_mode="HTML",
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )

        except TelegramAPIError as e:
            logger.error(f"[MANUAL_CMD] Failed to send to journal: {e}")

    # ─── Шаг 11: Удаляем команду ───
    try:
        await message.delete()
        logger.debug(f"[MANUAL_CMD] Command message deleted: msg_id={message.message_id}")
    except TelegramAPIError as e:
        logger.debug(f"[MANUAL_CMD] Failed to delete command: {e}")

    # Логируем успешное выполнение
    logger.info(
        f"[MANUAL_CMD] /akick completed: target={target_id}, "
        f"admin={admin_id}, chat={message.chat.id}"
    )
