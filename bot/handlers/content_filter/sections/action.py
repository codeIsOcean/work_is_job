# ============================================================
# ACTION - ДЕЙСТВИЯ РАЗДЕЛА
# ============================================================
# Этот модуль содержит хендлеры для выбора действий раздела:
# - section_action_menu: меню выбора действия
# - set_section_action: установка действия
# - toggle_section_forward: переключение пересылки
# - section_mute_duration_menu: выбор длительности мута
# - set_section_mute_duration: установка длительности
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
    create_section_action_menu,
    create_section_mute_duration_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем FSM states и helpers
from bot.handlers.content_filter.common import SectionMuteDurationStates, SectionForwardChannelStates, parse_duration
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для действий
action_router = Router(name='sections_action')


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ
# ============================================================

@action_router.callback_query(F.data.regexp(r"^cf:secac:\d+$"))
async def section_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия для раздела.

    Callback: cf:secac:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    text = (
        f"⚡ <b>Действие при срабатывании</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Выберите действие и настройте пересылку.\n"
        f"📤 = пересылать в канал при этом действии"
    )

    keyboard = create_section_action_menu(section_id, section)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.callback_query(F.data.regexp(r"^cf:secac:(delete|mute|ban):\d+$"))
async def set_section_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие для раздела.

    Callback: cf:secac:{action}:{section_id}
    """
    parts = callback.data.split(":")
    action = parts[2]
    section_id = int(parts[3])

    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        action=action
    )

    if success:
        action_names = {
            'delete': 'Удалить',
            'mute': 'Мут',
            'ban': 'Бан'
        }
        await callback.answer(f"Действие: {action_names.get(action, action)}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Обновляем меню
    section = await section_service.get_section_by_id(section_id, session)
    keyboard = create_section_action_menu(section_id, section)

    text = (
        f"⚡ <b>Действие при срабатывании</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Выберите действие и настройте пересылку.\n"
        f"📤 = пересылать в канал при этом действии"
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@action_router.callback_query(F.data.regexp(r"^cf:secfd:(delete|mute|ban):\d+$"))
async def toggle_section_forward(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает пересылку для конкретного действия раздела.

    Callback: cf:secfd:{action}:{section_id}
    """
    parts = callback.data.split(":")
    action = parts[2]
    section_id = int(parts[3])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Получаем текущее значение и переключаем
    field_name = f"forward_on_{action}"
    current_value = getattr(section, field_name, False)
    new_value = not current_value

    # Обновляем
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        **{field_name: new_value}
    )

    if success:
        status = "включена" if new_value else "выключена"
        await callback.answer(f"Пересылка при {action} {status}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Обновляем меню
    section = await section_service.get_section_by_id(section_id, session)
    keyboard = create_section_action_menu(section_id, section)

    text = (
        f"⚡ <b>Действие при срабатывании</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Выберите действие и настройте пересылку.\n"
        f"📤 = пересылать в канал при этом действии"
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# ДЛИТЕЛЬНОСТЬ МУТА
# ============================================================

@action_router.callback_query(F.data.regexp(r"^cf:secmd:\d+$"))
async def section_mute_duration_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора длительности мута.

    Callback: cf:secmd:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    current_duration = section.mute_duration or 60

    text = (
        f"⏱️ <b>Длительность мута</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Выберите длительность мута или введите своё значение."
    )

    keyboard = create_section_mute_duration_menu(section_id, current_duration)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.callback_query(F.data.regexp(r"^cf:secmd:\d+:\d+$"))
async def set_section_mute_duration(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает длительность мута для раздела.

    Callback: cf:secmd:{duration}:{section_id}
    """
    parts = callback.data.split(":")
    duration = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        mute_duration=duration
    )

    if success:
        # Форматируем длительность
        if duration < 60:
            dur_text = f"{duration} мин"
        elif duration < 1440:
            dur_text = f"{duration // 60} ч"
        else:
            dur_text = f"{duration // 1440} д"
        await callback.answer(f"Длительность: {dur_text}")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Обновляем меню
    section = await section_service.get_section_by_id(section_id, session)
    keyboard = create_section_mute_duration_menu(section_id, duration)

    text = (
        f"⏱️ <b>Длительность мута</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Выберите длительность мута или введите своё значение."
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@action_router.callback_query(F.data.regexp(r"^cf:secmdc:\d+$"))
async def start_custom_mute_duration(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода кастомной длительности мута.

    Callback: cf:secmdc:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(SectionMuteDurationStates.waiting_for_duration)

    text = (
        f"⏱️ <b>Ручной ввод длительности</b>\n\n"
        f"Введите длительность мута.\n\n"
        f"Форматы:\n"
        f"• <code>30</code> — 30 минут\n"
        f"• <code>1h</code> — 1 час\n"
        f"• <code>1d</code> — 1 день\n"
        f"• <code>1m</code> — 1 месяц"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:secmd:{section_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.message(SectionMuteDurationStates.waiting_for_duration)
async def process_custom_mute_duration(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод кастомной длительности мута."""
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

    # Парсим длительность
    duration = parse_duration(message.text.strip())

    if duration is None:
        # Неверный формат - показываем ошибку
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secmd:{section_id}")]
        ])
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text="❌ Неверный формат. Попробуйте: 30, 1h, 1d, 1m",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    await state.clear()

    # Обновляем раздел
    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        mute_duration=duration
    )

    # Форматируем длительность
    if duration < 60:
        dur_text = f"{duration} мин"
    elif duration < 1440:
        dur_text = f"{duration // 60} ч"
    else:
        dur_text = f"{duration // 1440} д"

    if success:
        text = f"✅ Длительность мута: {dur_text}"
    else:
        text = f"❌ Ошибка: {error or 'Не удалось обновить'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secmd:{section_id}")]
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

@action_router.callback_query(F.data.regexp(r"^cf:secfc:\d+$"))
async def start_forward_channel_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода канала пересылки.

    Callback: cf:secfc:{section_id}
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
    await state.set_state(SectionForwardChannelStates.waiting_for_channel)

    current_channel = section.forward_channel_id or "Не задан"

    text = (
        f"📤 <b>Канал для пересылки</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Текущий канал: <code>{current_channel}</code>\n\n"
        f"Введите ID канала (например: -100123456789)\n"
        f"или <code>-</code> чтобы сбросить."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:secac:{section_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.message(SectionForwardChannelStates.waiting_for_channel)
async def process_forward_channel_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод канала пересылки."""
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

    # Парсим канал
    channel_text = message.text.strip()

    if channel_text == "-":
        channel_id = None
    else:
        try:
            channel_id = int(channel_text)
        except ValueError:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secac:{section_id}")]
            ])
            try:
                await message.bot.edit_message_text(
                    chat_id=bot_chat_id,
                    message_id=bot_message_id,
                    text="❌ Введите числовой ID канала или '-' для сброса.",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except TelegramAPIError:
                pass
            return

    await state.clear()

    # Обновляем раздел
    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        forward_channel_id=channel_id
    )

    if success:
        if channel_id:
            text = f"✅ Канал пересылки: <code>{channel_id}</code>"
        else:
            text = "✅ Канал пересылки сброшен"
    else:
        text = f"❌ Ошибка: {error or 'Не удалось обновить'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secac:{section_id}")]
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