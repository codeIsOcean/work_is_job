# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /amute И /aunmute
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит обработчики команд:
# - /amute — замутить пользователя (ответом на сообщение или по @username/id)
# - /aunmute — размутить пользователя
#
# Особенности:
# - При /amute forever — добавляет в БД спаммеров и мутит кросс-группово
# - Ссылочные имена в уведомлениях
# - Журналирование с кнопками действий
#
# Создано: 2026-01-21
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
    parse_mute_command,
    format_duration,
    get_manual_command_settings,
    apply_mute,
    apply_unmute,
    format_user_link,
    MuteResult,
)
# Импортируем сервис журнала
from bot.services.group_journal_service import get_group_journal_channel
# Импортируем модель группы
from bot.database.models import Group

# Создаём роутер для команд мута
mute_router = Router(name="mute_command")

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
# ХЕЛПЕР: ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ ПО @username ИЛИ ID
# ═══════════════════════════════════════════════════════════════════════════
async def resolve_user(bot: Bot, chat_id: int, target: str) -> tuple[int, User | None]:
    """
    Получает user_id и объект User по @username или числовому id.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы (для поиска участника)
        target: @username или числовой id

    Returns:
        tuple[int, User | None]: (user_id, User объект или None)
    """
    # Если это @username
    if target.startswith('@'):
        # Telegram не позволяет получить пользователя по username напрямую
        # Нужно искать через get_chat_member (работает только если юзер в группе)
        # Пока возвращаем None для User объекта
        # TODO: Можно использовать Pyrogram для получения user по username
        return (0, None)

    # Если это числовой id
    if target.isdigit():
        user_id = int(target)
        try:
            # Пытаемся получить информацию о участнике группы
            member = await bot.get_chat_member(chat_id, user_id)
            return (user_id, member.user)
        except TelegramAPIError:
            # Пользователь не найден в группе, но id валидный
            return (user_id, None)

    return (0, None)


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ПОСТРОЕНИЕ СООБЩЕНИЯ ДЛЯ ЖУРНАЛА
# ═══════════════════════════════════════════════════════════════════════════
def build_journal_message(
    group_title: str,
    target_user: User | None,
    target_id: int,
    admin_user: User | None,
    duration_minutes: int | None,
    reason: str | None,
    is_forever: bool,
    added_to_spammers: bool,
    muted_groups_count: int,
    chat_id: int | None = None,
    group_username: str | None = None,
) -> str:
    """
    Строит HTML сообщение для журнала.

    Args:
        group_title: Название группы
        target_user: Объект User (цель мута)
        target_id: ID цели
        admin_user: Объект User (админ)
        duration_minutes: Длительность в минутах
        reason: Причина
        is_forever: Навсегда ли
        added_to_spammers: Добавлен ли в БД спаммеров
        muted_groups_count: Количество групп где замучен
        chat_id: ID группы (для ссылки)
        group_username: Username группы (для ссылки)

    Returns:
        str: HTML текст сообщения
    """
    # Заголовок с хештегами
    if is_forever:
        header = "🔇 <b>#РУЧНОЙ_МУТ #НАВСЕГДА</b>"
    else:
        header = "🔇 <b>#РУЧНОЙ_МУТ</b>"

    # Название группы (с ссылкой если возможно)
    escaped_title = html.escape(group_title)
    if group_username:
        # Публичная группа — ссылка через username
        group_link = f'<a href="https://t.me/{group_username}">{escaped_title}</a>'
    elif chat_id:
        # Приватная группа — ссылка через chat_id (работает в Telegram)
        # Для supergroup -100XXXXXXXXXX → XXXXXXXXXX
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
            f"\n\n👤 <b>Нарушитель:</b> {user_link}"
            f"\n    {username} | ID: <code>{target_id}</code>"
        )
    else:
        target_line = f"\n\n👤 <b>Нарушитель:</b> ID: <code>{target_id}</code>"

    # Информация об админе
    if admin_user:
        admin_link = format_user_link(admin_user)
        admin_username = f"@{admin_user.username}" if admin_user.username else "—"
        admin_line = f"\n\n👮 <b>Админ:</b> {admin_link} ({admin_username})"
    else:
        # Анонимный админ (пишет от имени группы)
        admin_line = "\n\n👮 <b>Админ:</b> Анонимный администратор"

    # Время мута
    if is_forever:
        time_line = "\n⏱️ <b>Время:</b> Навсегда"
    else:
        time_text = format_duration(duration_minutes)
        time_line = f"\n⏱️ <b>Время:</b> {time_text}"

    # Причина
    if reason:
        reason_line = f"\n📝 <b>Причина:</b> {html.escape(reason)}"
    else:
        reason_line = ""

    # Дата
    now = datetime.now(timezone.utc)
    date_line = f"\n🕐 <b>Дата:</b> {now.strftime('%d.%m.%Y %H:%M')} UTC"

    # Дополнительная информация для мута навсегда
    extra_lines = ""
    if added_to_spammers:
        extra_lines += "\n\n🗃️ <b>Добавлен в БД спаммеров</b>"
    if muted_groups_count > 1:
        extra_lines += f"\n🌍 <b>Замучен в {muted_groups_count} группах</b>"

    # Собираем всё вместе
    message = (
        f"{header}"
        f"{group_line}"
        f"{target_line}"
        f"{admin_line}"
        f"{time_line}"
        f"{reason_line}"
        f"{date_line}"
        f"{extra_lines}"
    )

    return message


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ПОСТРОЕНИЕ КЛАВИАТУРЫ ДЛЯ ЖУРНАЛА
# ═══════════════════════════════════════════════════════════════════════════
def build_journal_keyboard(
    target_id: int,
    chat_id: int,
    is_forever: bool,
) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру с кнопками для журнала.

    Args:
        target_id: ID пользователя
        chat_id: ID группы
        is_forever: Навсегда ли мут

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    buttons = []

    # Кнопка размута
    if is_forever:
        # Для вечного мута — кнопка "Размут везде"
        buttons.append(
            InlineKeyboardButton(
                text="🔊 Размут везде",
                callback_data=f"mc:unmute_all:{target_id}:{chat_id}"
            )
        )
    else:
        # Для обычного мута — просто "Размут"
        buttons.append(
            InlineKeyboardButton(
                text="🔊 Размут",
                callback_data=f"mc:unmute:{target_id}:{chat_id}"
            )
        )

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
# ХЕНДЛЕР КОМАНДЫ /amute
# ═══════════════════════════════════════════════════════════════════════════
@mute_router.message(Command("amute"))
async def handle_amute_command(
    message: Message,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработчик команды /amute.

    Форматы:
    - /amute                 → мут reply на время по умолчанию
    - /amute 1h              → мут reply на 1 час
    - /amute forever         → мут reply навсегда + кросс-групповой
    - /amute @user 1h спам   → мут @user на 1 час с причиной
    - /amute 123456 forever  → мут user_id навсегда
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
    else:
        admin_id = message.from_user.id
        if not await is_user_admin(bot, message.chat.id, admin_id):
            await message.reply("❌ Эта команда только для администраторов")
            return

    # ─── Шаг 3: Парсим команду ───
    has_reply = message.reply_to_message is not None
    parsed = parse_mute_command(message.text, has_reply=has_reply)

    # ─── Шаг 4: Определяем цель мута ───
    target_id = 0
    target_user = None

    if parsed.target_type == 'reply':
        # Мут по reply на сообщение
        if not message.reply_to_message:
            await message.reply(
                "❌ Ответьте на сообщение пользователя которого хотите замутить\n"
                "Или укажите @username или ID: <code>/amute @user 1h</code>",
                parse_mode="HTML"
            )
            return
        target_id = message.reply_to_message.from_user.id
        target_user = message.reply_to_message.from_user

    elif parsed.target_type == 'username':
        # Мут по @username
        # К сожалению Telegram Bot API не позволяет найти пользователя по username
        # Можно только если он уже в группе через get_chat_member
        await message.reply(
            "❌ Мут по @username пока не поддерживается.\n"
            "Ответьте на сообщение пользователя или используйте его ID:\n"
            "<code>/amute 123456789 1h причина</code>",
            parse_mode="HTML"
        )
        return

    elif parsed.target_type == 'user_id':
        # Мут по user_id
        target_id = int(parsed.target)
        # Пробуем получить информацию о пользователе
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
            target_user = member.user
        except TelegramAPIError:
            # Пользователь не в группе — продолжаем без User объекта
            target_user = None

    # Проверяем что target_id валидный
    if target_id == 0:
        await message.reply("❌ Не удалось определить пользователя для мута")
        return

    # ─── Шаг 5: Получаем настройки модуля ───
    settings = await get_manual_command_settings(session, message.chat.id)

    # ─── Шаг 6: Определяем длительность мута ───
    if parsed.is_forever:
        # Мут навсегда
        duration_minutes = None
        is_forever = True
    elif parsed.duration_minutes is not None:
        # Указано конкретное время
        duration_minutes = parsed.duration_minutes
        is_forever = False
    else:
        # Время не указано — используем из настроек
        duration_minutes = settings.mute_default_duration
        is_forever = (duration_minutes == 0)

    # ─── Шаг 7: Применяем мут ───
    mute_result = await apply_mute(
        bot=bot,
        session=session,
        chat_id=message.chat.id,
        user_id=target_id,
        admin_id=admin_id,
        duration_minutes=duration_minutes,
        reason=parsed.reason,
        is_forever=is_forever,
    )

    # ─── Шаг 8: Проверяем результат ───
    if not mute_result.success:
        await message.reply(f"❌ {mute_result.error}")
        return

    # ─── Шаг 9: Удаляем сообщение нарушителя (если включено) ───
    if settings.mute_delete_message and message.reply_to_message:
        delete_delay = getattr(settings, 'mute_delete_delay', 0) or 0
        if delete_delay > 0:
            # Отложенное удаление
            asyncio.create_task(delayed_delete(message.reply_to_message, delete_delay))
        else:
            # Мгновенное удаление
            try:
                await message.reply_to_message.delete()
            except TelegramAPIError as e:
                logger.warning(f"[MANUAL_CMD] Failed to delete message: {e}")

    # ─── Шаг 10: Отправляем уведомление в группу (если включено) ───
    notify_message = None
    if settings.mute_notify_group:
        # Формируем ссылку на пользователя
        if target_user:
            user_link = format_user_link(target_user)
        else:
            user_link = f"<code>{target_id}</code>"

        # Формируем текст времени
        if is_forever:
            time_text = "навсегда"
        else:
            time_text = format_duration(duration_minutes)

        # Формируем ссылку на админа
        if message.from_user:
            admin_link = format_user_link(message.from_user)
        else:
            admin_link = "Анонимный администратор"

        # Проверяем есть ли кастомный текст
        custom_text = getattr(settings, 'mute_notify_text', None)
        if custom_text:
            # Используем кастомный текст с подстановкой переменных
            notify_text = custom_text
            notify_text = notify_text.replace('%user%', user_link)
            notify_text = notify_text.replace('%time%', time_text)
            notify_text = notify_text.replace('%reason%', html.escape(parsed.reason or '—'))
            notify_text = notify_text.replace('%admin%', admin_link)
        else:
            # Стандартный текст
            if is_forever:
                notify_text = f"🔇 {user_link} получил мут навсегда."
            else:
                notify_text = f"🔇 {user_link} получил мут на {time_text}."

            # Добавляем причину если есть
            if parsed.reason:
                notify_text += f"\n📝 Причина: {html.escape(parsed.reason)}"

            # Добавляем информацию о кросс-групповом муте
            if mute_result.added_to_spammers:
                notify_text += "\n🗃️ Добавлен в БД спаммеров"
            if len(mute_result.muted_groups) > 1:
                notify_text += f"\n🌍 Замучен в {len(mute_result.muted_groups)} группах"

        notify_message = await message.answer(notify_text, parse_mode="HTML")

        # Отложенное удаление уведомления (если настроено)
        notify_delete_delay = getattr(settings, 'mute_notify_delete_delay', 0) or 0
        if notify_delete_delay > 0 and notify_message:
            asyncio.create_task(delayed_delete(notify_message, notify_delete_delay))

    # ─── Шаг 11: Отправляем в журнал ───
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
                admin_user=message.from_user,
                duration_minutes=duration_minutes,
                reason=parsed.reason,
                is_forever=is_forever,
                added_to_spammers=mute_result.added_to_spammers,
                muted_groups_count=len(mute_result.muted_groups),
                chat_id=message.chat.id,
                group_username=message.chat.username,
            )

            # Строим клавиатуру
            keyboard = build_journal_keyboard(
                target_id=target_id,
                chat_id=message.chat.id,
                is_forever=is_forever,
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

    # ─── Шаг 12: Удаляем команду (опционально) ───
    try:
        await message.delete()
        logger.debug(f"[MANUAL_CMD] Command message deleted: msg_id={message.message_id}")
    except TelegramAPIError as e:
        logger.debug(f"[MANUAL_CMD] Failed to delete command: {e}")

    # Логируем успешное выполнение
    logger.info(
        f"[MANUAL_CMD] /amute completed: target={target_id}, "
        f"duration={'forever' if is_forever else f'{duration_minutes}min'}, "
        f"admin={admin_id}, chat={message.chat.id}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КОМАНДЫ /aunmute
# ═══════════════════════════════════════════════════════════════════════════
@mute_router.message(Command("aunmute"))
async def handle_aunmute_command(
    message: Message,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработчик команды /aunmute — размут пользователя.

    Форматы:
    - /aunmute          → размут reply
    - /aunmute 123456   → размут по user_id
    """
    # ─── Проверяем что команда из группы ───
    if message.chat.type not in ('group', 'supergroup'):
        await message.reply("❌ Эта команда работает только в группах")
        return

    # ─── Проверяем что отправитель — админ ───
    # Поддерживаем анонимных админов (sender_chat == chat)
    if is_anonymous_admin(message):
        admin_id = message.chat.id
    else:
        admin_id = message.from_user.id
        if not await is_user_admin(bot, message.chat.id, admin_id):
            await message.reply("❌ Эта команда только для администраторов")
            return

    # ─── Определяем цель ───
    target_id = 0

    # Пробуем reply
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        # Пробуем user_id из текста
        text_parts = message.text.split()
        if len(text_parts) > 1 and text_parts[1].isdigit():
            target_id = int(text_parts[1])

    if target_id == 0:
        await message.reply(
            "❌ Ответьте на сообщение пользователя или укажите ID:\n"
            "<code>/aunmute 123456789</code>",
            parse_mode="HTML"
        )
        return

    # ─── Применяем размут ───
    result = await apply_unmute(
        bot=bot,
        session=session,
        chat_id=message.chat.id,
        user_id=target_id,
        unmute_everywhere=False,
        admin_id=admin_id,
    )

    if result.success:
        await message.reply(f"✅ Пользователь <code>{target_id}</code> размучен", parse_mode="HTML")
    else:
        await message.reply(f"❌ {result.error}")

    # Удаляем команду
    try:
        await message.delete()
    except TelegramAPIError:
        pass
