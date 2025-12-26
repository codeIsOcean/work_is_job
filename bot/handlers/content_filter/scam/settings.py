# ============================================================
# SETTINGS - НАСТРОЙКИ АНТИСКАМА
# ============================================================
# Этот модуль содержит хендлеры для настроек антискама:
# - scam_settings_menu: меню настроек
# - scam_action_menu: выбор действия
# - set_scam_action: установка действия
# - start_scam_mute_duration_input: запрос времени мута
# - process_scam_mute_duration: обработка времени
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
    create_scam_settings_menu,
    create_scam_action_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и helpers
from bot.handlers.content_filter.common import DurationInputStates, parse_duration

# Создаём роутер для настроек
settings_router = Router(name='scam_settings')


# ============================================================
# МЕНЮ НАСТРОЕК АНТИСКАМА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scs:-?\d+$"))
async def scam_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек антискама.

    Callback: cf:scs:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст
    text = (
        f"🎯 <b>Настройки антискама</b>\n\n"
        f"Эвристический анализ сообщений:\n"
        f"• Деньги, криптовалюта\n"
        f"• Призывы к действию\n"
        f"• Гарантии заработка\n\n"
        f"Чувствительность определяет порог срабатывания."
    )

    # Клавиатура
    keyboard = create_scam_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ВЫБОР ДЕЙСТВИЯ ДЛЯ АНТИСКАМА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scact:-?\d+$"))
async def scam_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия для антискама.

    Callback: cf:scact:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст
    text = (
        f"⚡ <b>Действие при срабатывании антискама</b>\n\n"
        f"Выберите что делать при обнаружении скама."
    )

    # Клавиатура
    # Используем default_mute_duration - это правильное имя поля в модели
    keyboard = create_scam_action_menu(
        chat_id,
        current_action=settings.default_action or 'delete',
        current_duration=settings.default_mute_duration
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.callback_query(F.data.regexp(r"^cf:scact:(delete|mute|ban):-?\d+$"))
async def set_scam_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие для антискама.

    Callbacks:
    - cf:scact:delete:{chat_id}
    - cf:scact:mute:{chat_id}
    - cf:scact:ban:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    action = parts[2]  # delete, mute, ban
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Устанавливаем действие
    settings.default_action = action

    # Если выбрали delete или ban - сбрасываем длительность мута
    # Используем default_mute_duration - правильное имя поля
    if action != 'mute':
        settings.default_mute_duration = None

    await session.commit()

    # Формируем текст подтверждения
    action_texts = {
        'delete': '🗑️ Только удалить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }
    await callback.answer(f"✅ Установлено: {action_texts.get(action, action)}")

    # Обновляем меню
    text = (
        f"⚡ <b>Действие при срабатывании антискама</b>\n\n"
        f"Выберите что делать при обнаружении скама."
    )

    # Используем default_mute_duration - правильное имя поля
    keyboard = create_scam_action_menu(
        chat_id,
        current_action=action,
        current_duration=settings.default_mute_duration
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@settings_router.callback_query(F.data.regexp(r"^cf:scact:time:-?\d+$"))
async def start_scam_mute_duration_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода времени мута антискама.

    Callback: cf:scact:time:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext для хранения состояния
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Сохраняем chat_id в FSM
    await state.update_data(chat_id=chat_id)
    await state.set_state(DurationInputStates.waiting_for_scam_duration)

    # Создаём клавиатуру отмены
    cancel_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Отмена",
                    callback_data=f"cf:scact:{chat_id}"
                )
            ]
        ]
    )

    # Формируем текст с инструкцией
    text = (
        f"⏱️ <b>Введите длительность мута для антискама</b>\n\n"
        f"Форматы:\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n"
        f"• <code>1d</code> — 1 день\n"
        f"• <code>1m</code> — 1 месяц\n\n"
        f"Отправьте значение или нажмите Отмена."
    )

    try:
        await callback.message.edit_text(text, reply_markup=cancel_keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.message(DurationInputStates.waiting_for_scam_duration)
async def process_scam_mute_duration(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод времени мута для антискама.

    Args:
        message: Сообщение с длительностью
        session: Сессия БД
        state: FSMContext с данными
    """
    # Получаем chat_id из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await state.clear()
        return

    # Парсим длительность
    duration = parse_duration(message.text.strip())

    if duration is None:
        # Неверный формат - удаляем сообщение пользователя и показываем ошибку
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Показываем ошибку в исходном сообщении (если есть)
        instruction_message_id = await state.get_data()
        instruction_msg_id = instruction_message_id.get('instruction_message_id')
        error_text = (
            "❌ Неверный формат. Используйте: 30s, 5min, 1h, 1d, 1m\n\n"
            "Попробуйте ещё раз:"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scs:{chat_id}")]
        ])
        if instruction_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_msg_id,
                    text=error_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        # Fallback если нет сохранённого ID
        await message.answer(error_text, reply_markup=keyboard, parse_mode="HTML")
        return

    # Очищаем FSM
    await state.clear()

    # Получаем настройки и устанавливаем значения
    # Используем default_mute_duration - правильное имя поля в модели
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.default_action = 'mute'
    settings.default_mute_duration = duration
    await session.commit()

    # Форматируем текст длительности для отображения
    if duration < 60:
        duration_text = f"{duration} мин"
    elif duration < 1440:
        duration_text = f"{duration // 60} ч"
    else:
        duration_text = f"{duration // 1440} д"

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем ответ
    text = (
        f"⚡ <b>Действие при срабатывании антискама</b>\n\n"
        f"✅ Установлено: мут {duration_text}\n\n"
        f"Выберите что делать при обнаружении скама."
    )

    keyboard = create_scam_action_menu(
        chat_id,
        current_action='mute',
        current_duration=duration
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
