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
    create_scam_action_menu,
    create_scam_advanced_menu,
    create_scam_notification_delay_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и helpers
from bot.handlers.content_filter.common import (
    DurationInputStates,
    ScamTextStates,
    ScamDelayStates,
    parse_duration
)

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
    # Используем scam_action и scam_mute_duration для антискама
    keyboard = create_scam_action_menu(
        chat_id,
        current_action=settings.scam_action or 'delete',
        current_duration=settings.scam_mute_duration
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

    # Устанавливаем действие для антискама (scam_action, НЕ default_action!)
    settings.scam_action = action

    # Если выбрали delete или ban - сбрасываем длительность мута
    # Используем scam_mute_duration для антискама
    if action != 'mute':
        settings.scam_mute_duration = None

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

    # Используем scam_mute_duration для антискама
    keyboard = create_scam_action_menu(
        chat_id,
        current_action=action,
        current_duration=settings.scam_mute_duration
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
    # Используем scam_action и scam_mute_duration для антискама
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.scam_action = 'mute'
    settings.scam_mute_duration = duration
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


# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ АНТИСКАМА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scadv:-?\d+$"))
async def scam_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню дополнительных настроек антискама.

    Callback: cf:scadv:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем превью текстов
    mute_text_preview = (
        settings.scam_mute_text[:30] + "..."
        if settings.scam_mute_text and len(settings.scam_mute_text) > 30
        else settings.scam_mute_text or "По умолчанию"
    )
    ban_text_preview = (
        settings.scam_ban_text[:30] + "..."
        if settings.scam_ban_text and len(settings.scam_ban_text) > 30
        else settings.scam_ban_text or "По умолчанию"
    )
    notify_delay = settings.scam_notification_delete_delay or 0
    notify_delay_text = f"{notify_delay} сек" if notify_delay else "Не удалять"

    text = (
        f"⚙️ <b>Дополнительные настройки антискама</b>\n\n"
        f"<b>Текст при муте:</b> {mute_text_preview}\n"
        f"<b>Текст при бане:</b> {ban_text_preview}\n"
        f"<b>Автоудаление уведомления:</b> {notify_delay_text}"
    )

    keyboard = create_scam_advanced_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ТЕКСТ ПРИ МУТЕ (АНТИСКАМ)
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scmt:-?\d+$"))
async def start_scam_mute_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода текста уведомления при муте.

    Callback: cf:scmt:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = settings.scam_mute_text or "Не задан"

    await state.update_data(
        chat_id=chat_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(ScamTextStates.waiting_for_mute_text)

    text = (
        f"📝 <b>Текст при муте (антискам)</b>\n\n"
        f"Текущий текст:\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или <code>-</code> для сброса.\n"
        f"Доступные переменные: %user%, %time%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.message(ScamTextStates.waiting_for_mute_text)
async def process_scam_mute_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод текста при муте."""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    await state.clear()

    text_input = message.text.strip()
    if text_input == "-":
        text_input = None

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.scam_mute_text = text_input
    await session.commit()

    result_text = "✅ Текст при муте сохранён" if text_input else "✅ Текст при муте сброшен"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=result_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ТЕКСТ ПРИ БАНЕ (АНТИСКАМ)
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scbt:-?\d+$"))
async def start_scam_ban_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает FSM для ввода текста уведомления при бане.

    Callback: cf:scbt:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = settings.scam_ban_text or "Не задан"

    await state.update_data(
        chat_id=chat_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(ScamTextStates.waiting_for_ban_text)

    text = (
        f"📝 <b>Текст при бане (антискам)</b>\n\n"
        f"Текущий текст:\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или <code>-</code> для сброса.\n"
        f"Доступные переменные: %user%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.message(ScamTextStates.waiting_for_ban_text)
async def process_scam_ban_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод текста при бане."""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    await state.clear()

    text_input = message.text.strip()
    if text_input == "-":
        text_input = None

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.scam_ban_text = text_input
    await session.commit()

    result_text = "✅ Текст при бане сохранён" if text_input else "✅ Текст при бане сброшен"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=result_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ЗАДЕРЖКА АВТОУДАЛЕНИЯ УВЕДОМЛЕНИЯ (АНТИСКАМ)
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scnd:-?\d+$"))
async def scam_notification_delay_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настройки задержки автоудаления уведомления.

    Callback: cf:scnd:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_delay = settings.scam_notification_delete_delay or 0

    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Через сколько секунд удалять уведомление о нарушении.\n\n"
        f"Текущее значение: <b>{current_delay} сек</b>"
    )

    keyboard = create_scam_notification_delay_menu(chat_id, current_delay)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.callback_query(F.data.regexp(r"^cf:scnd:\d+:-?\d+$"))
async def set_scam_notification_delay(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает задержку автоудаления уведомления.

    Callback: cf:scnd:{delay}:{chat_id}
    """
    parts = callback.data.split(":")
    delay = int(parts[2])
    chat_id = int(parts[3])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.scam_notification_delete_delay = delay if delay > 0 else None
    await session.commit()

    delay_text = f"{delay} сек" if delay else "Не удалять"
    await callback.answer(f"Автоудаление: {delay_text}")

    # Обновляем меню
    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Через сколько секунд удалять уведомление о нарушении.\n\n"
        f"Текущее значение: <b>{delay} сек</b>"
    )

    keyboard = create_scam_notification_delay_menu(chat_id, delay)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# РУЧНОЙ ВВОД ЗАДЕРЖКИ АВТОУДАЛЕНИЯ (Правило 22 — без хардкода)
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:scndc:-?\d+$"))
async def start_custom_notification_delay(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс ручного ввода задержки автоудаления.

    Callback: cf:scndc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем в FSM
    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamDelayStates.waiting_for_notification_delay)

    text = (
        f"✏️ <b>Ручной ввод задержки</b>\n\n"
        f"Введите количество секунд для автоудаления уведомления.\n\n"
        f"Примеры: <code>0</code> (не удалять), <code>30</code>, <code>120</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scnd:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.message(ScamDelayStates.waiting_for_notification_delay)
async def process_custom_notification_delay(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод кастомной задержки автоудаления.

    Args:
        message: Сообщение с задержкой
        state: FSMContext
        session: Сессия БД
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим задержку
    try:
        delay = int(message.text.strip())
        if delay < 0:
            raise ValueError("Задержка должна быть >= 0")
        if delay > 3600:
            delay = 3600  # Максимум 1 час
    except ValueError:
        await message.answer("❌ Введите положительное число (0-3600 секунд).")
        return

    # Получаем chat_id из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id.")
        await state.clear()
        return

    # Обновляем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    settings.scam_notification_delete_delay = delay if delay > 0 else None
    await session.commit()

    await state.clear()

    # Формируем ответ
    delay_text = f"{delay} сек" if delay else "Не удалять"

    text = (
        f"✅ Задержка установлена: <b>{delay_text}</b>\n\n"
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Через сколько секунд удалять уведомление о нарушении.\n\n"
        f"Текущее значение: <b>{delay} сек</b>"
    )

    keyboard = create_scam_notification_delay_menu(chat_id, delay)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
