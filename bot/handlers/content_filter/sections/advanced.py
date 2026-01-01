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
# Импортируем FSM states и парсеры
from bot.handlers.content_filter.common import (
    SectionMuteTextStates,
    SectionBanTextStates,
    SectionForwardChannelStates,
    SectionNotificationDelayStates,
    parse_delay_seconds
)
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
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню настройки задержки автоудаления уведомления.

    Callback: cf:secnd:{section_id}
    """
    # Очищаем FSM если пришли из ручного ввода
    await state.clear()

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
# РУЧНОЙ ВВОД ЗАДЕРЖКИ УДАЛЕНИЯ УВЕДОМЛЕНИЯ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secndc:\d+$"))
async def start_custom_notification_delay_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ручного ввода задержки удаления уведомления.

    Callback: cf:secndc:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(SectionNotificationDelayStates.waiting_for_delay)

    current_delay = section.notification_delete_delay or 0

    text = (
        f"⏱️ <b>Задержка удаления уведомления</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n"
        f"Текущее значение: <b>{current_delay} сек</b>\n\n"
        f"Введите время:\n\n"
        f"<i>Форматы:\n"
        f"• 30 или 30s — секунды\n"
        f"• 5min — минуты\n"
        f"• 1h — часы\n"
        f"• 1d — дни\n"
        f"• 1m — месяцы\n"
        f"• 1y — годы\n"
        f"• 0 — не удалять</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"cf:secnd:{section_id}"
            )
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(SectionNotificationDelayStates.waiting_for_delay)
async def process_custom_notification_delay(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод задержки удаления уведомления.
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем данные FSM
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    if not section_id:
        await state.clear()
        return

    # Парсим значение с помощью универсального парсера
    delay = parse_delay_seconds(message.text)

    if delay is None:
        # Сообщаем об ошибке
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text=(
                    f"❌ <b>Ошибка</b>\n\n"
                    f"Неверный формат времени.\n\n"
                    f"<i>Примеры: 30s, 5min, 1h, 1d, 1m, 1y</i>"
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад",
                            callback_data=f"cf:secnd:{section_id}"
                        )
                    ]
                ]),
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    # Обновляем значение
    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        notification_delete_delay=delay
    )

    await state.clear()

    if success:
        if delay == 0:
            delay_text = "Не удалять"
        elif delay < 60:
            delay_text = f"{delay} сек"
        elif delay < 3600:
            delay_text = f"{delay // 60} мин"
        elif delay < 86400:
            delay_text = f"{delay // 3600} ч"
        elif delay < 2592000:
            delay_text = f"{delay // 86400} д"
        elif delay < 31536000:
            delay_text = f"{delay // 2592000} мес"
        else:
            delay_text = f"{delay // 31536000} г"
        text = f"✅ Задержка удаления: <b>{delay_text}</b> ({delay} сек)"
    else:
        text = f"❌ Ошибка: {error or 'неизвестная ошибка'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"cf:secnd:{section_id}"
            )
        ]
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


# ============================================================
# КАНАЛ ПЕРЕСЫЛКИ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secch:\d+$"))
async def start_section_forward_channel_input(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для ввода канала пересылки.

    Callback: cf:secch:{section_id}

    Канал общий для всех действий (delete/mute/ban).
    Пересылка включается отдельно для каждого действия.
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    await state.update_data(
        section_id=section_id,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(SectionForwardChannelStates.waiting_for_channel)

    current = section.forward_channel_id or "не задан"

    text = (
        f"📢 <b>Канал для пересылки</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n"
        f"Текущий канал: <code>{current}</code>\n\n"
        f"Введите ID канала куда будут пересылаться сообщения.\n\n"
        f"<i>Убедитесь что бот добавлен в канал как админ!</i>\n"
        f"<i>Пересылка включается отдельно для каждого действия (📤).</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:secac:{section_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(SectionForwardChannelStates.waiting_for_channel)
async def process_section_forward_channel(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод канала пересылки.
    """
    data = await state.get_data()
    section_id = data.get('section_id')
    instruction_message_id = data.get('instruction_message_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Парсим ID канала
    try:
        channel_id = int(message.text.strip())
    except ValueError:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"cf:secac:{section_id}"
            )]
        ])
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ Введите числовой ID канала.\n\nПример: -1001234567890",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        return

    # Обновляем раздел
    section_service = get_section_service()
    await section_service.update_section(section_id, session, forward_channel_id=channel_id)

    # Очищаем FSM
    await state.clear()

    confirm_text = f"✅ Канал пересылки: <code>{channel_id}</code>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ К действиям",
            callback_data=f"cf:secac:{section_id}"
        )]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# CAS (COMBOT ANTI-SPAM) TOGGLE
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:seccas:\d+$"))
async def toggle_section_cas(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает CAS (Combot Anti-Spam) для раздела.

    CAS — бесплатная глобальная база забаненных спамеров Telegram.
    При включении: если пользователь найден в CAS при срабатывании раздела,
    к нему применяется действие раздела (mute/ban).

    Callback: cf:seccas:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Переключаем флаг
    new_value = not section.cas_enabled

    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        cas_enabled=new_value
    )

    if success:
        status = "включена ✅" if new_value else "выключена ❌"
        await callback.answer(f"Проверка CAS {status}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)
        return

    # Обновляем меню — получаем обновлённый раздел
    section = await section_service.get_section_by_id(section_id, session)

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


# ============================================================
# БД СПАММЕРОВ TOGGLE
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:secspdb:\d+$"))
async def toggle_section_spammer_db(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает добавление в глобальную БД спаммеров для раздела.

    При включении: нарушитель добавляется в глобальную БД спаммеров бота.
    Это позволяет мутить/банить спаммера во всех группах где бот админ.

    Callback: cf:secspdb:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Переключаем флаг
    new_value = not section.add_to_spammer_db

    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        add_to_spammer_db=new_value
    )

    if success:
        status = "включено ✅" if new_value else "выключено ❌"
        await callback.answer(f"Добавление в БД спаммеров {status}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)
        return

    # Обновляем меню — получаем обновлённый раздел
    section = await section_service.get_section_by_id(section_id, session)

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
