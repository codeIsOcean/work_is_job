# ============================================================
# ADVANCED - РАСШИРЕННЫЕ НАСТРОЙКИ РАЗДЕЛА
# ============================================================
# Этот модуль содержит хендлеры для расширенных настроек раздела:
# - section_advanced_menu: меню дополнительных настроек
# - section_notification_delay_menu: задержка уведомлений
# - section_mute_text: текст уведомления при муте
# - section_ban_text: текст уведомления при бане
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем FSM
from aiogram.fsm.context import FSMContext
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_section_advanced_menu,
    create_section_notification_delay_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем FSM states
from bot.handlers.content_filter.common import SectionMuteTextStates, SectionBanTextStates
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для расширенных настроек
advanced_router = Router(name='sections_advanced')


# ============================================================
# МЕНЮ ДОПОЛНИТЕЛЬНЫХ НАСТРОЕК
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secadv:\d+$"))
async def section_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню дополнительных настроек раздела.

    Callback: cf:secadv:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Формируем текст
    mute_text_preview = section.mute_text[:30] + "..." if section.mute_text and len(section.mute_text) > 30 else section.mute_text or "По умолчанию"
    ban_text_preview = section.ban_text[:30] + "..." if section.ban_text and len(section.ban_text) > 30 else section.ban_text or "По умолчанию"
    notify_delay = section.notification_delete_delay or 0
    notify_delay_text = f"{notify_delay} сек" if notify_delay else "Не удалять"

    text = (
        f"⚙️ <b>Дополнительные настройки</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"<b>Текст при муте:</b> {mute_text_preview}\n"
        f"<b>Текст при бане:</b> {ban_text_preview}\n"
        f"<b>Автоудаление уведомления:</b> {notify_delay_text}"
    )

    keyboard = create_section_advanced_menu(section_id, section)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ЗАДЕРЖКА АВТОУДАЛЕНИЯ УВЕДОМЛЕНИЯ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secnd:\d+$"))
async def section_notification_delay_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настройки задержки автоудаления уведомления.

    Callback: cf:secnd:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    current_delay = section.notification_delete_delay or 0

    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Через сколько секунд удалять уведомление о нарушении.\n\n"
        f"Текущее значение: <b>{current_delay} сек</b>"
    )

    keyboard = create_section_notification_delay_menu(section_id, current_delay)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.callback_query(F.data.regexp(r"^cf:secnd:\d+:\d+$"))
async def set_section_notification_delay(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает задержку автоудаления уведомления.

    Callback: cf:secnd:{delay}:{section_id}
    """
    parts = callback.data.split(":")
    delay = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        notification_delete_delay=delay
    )

    if success:
        delay_text = f"{delay} сек" if delay else "Не удалять"
        await callback.answer(f"Автоудаление: {delay_text}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Обновляем меню
    section = await section_service.get_section_by_id(section_id, session)
    keyboard = create_section_notification_delay_menu(section_id, delay)

    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Через сколько секунд удалять уведомление о нарушении.\n\n"
        f"Текущее значение: <b>{delay} сек</b>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# ТЕКСТ ПРИ МУТЕ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secmt:\d+$"))
async def start_section_mute_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода текста уведомления при муте.

    Callback: cf:secmt:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    current_text = section.mute_text or "Не задан"

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(SectionMuteTextStates.waiting_for_text)

    text = (
        f"📝 <b>Текст при муте</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Текущий текст:\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или <code>-</code> для сброса.\n"
        f"Доступные переменные: %user%, %time%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secadv:{section_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(SectionMuteTextStates.waiting_for_text)
async def process_section_mute_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод текста при муте."""
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    await state.clear()

    # Получаем текст
    text_input = message.text.strip()
    if text_input == "-":
        text_input = None

    # Обновляем раздел
    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        mute_text=text_input
    )

    if success:
        text = "✅ Текст при муте сохранён" if text_input else "✅ Текст при муте сброшен"
    else:
        text = f"❌ {error or 'Ошибка'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secadv:{section_id}")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ТЕКСТ ПРИ БАНЕ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secbt:\d+$"))
async def start_section_ban_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода текста уведомления при бане.

    Callback: cf:secbt:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    current_text = section.ban_text or "Не задан"

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(SectionBanTextStates.waiting_for_text)

    text = (
        f"📝 <b>Текст при бане</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Текущий текст:\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или <code>-</code> для сброса.\n"
        f"Доступные переменные: %user%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secadv:{section_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(SectionBanTextStates.waiting_for_text)
async def process_section_ban_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод текста при бане."""
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    await state.clear()

    # Получаем текст
    text_input = message.text.strip()
    if text_input == "-":
        text_input = None

    # Обновляем раздел
    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        ban_text=text_input
    )

    if success:
        text = "✅ Текст при бане сохранён" if text_input else "✅ Текст при бане сброшен"
    else:
        text = f"❌ {error or 'Ошибка'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secadv:{section_id}")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
