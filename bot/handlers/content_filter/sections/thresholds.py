# ============================================================
# THRESHOLDS - ПОРОГИ БАЛЛОВ РАЗДЕЛА
# ============================================================
# Этот модуль содержит хендлеры для управления порогами раздела:
# - section_threshold_menu: меню выбора порога
# - set_section_threshold: установка порога
# - section_thresholds_menu: меню дифференцированных порогов
# - add_section_threshold: добавление порога
# - delete_section_threshold: удаление порога
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
from bot.keyboards.content_filter_keyboards import create_section_threshold_menu

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем FSM states
from bot.handlers.content_filter.common import AddSectionThresholdStates, parse_duration
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для порогов
thresholds_router = Router(name='sections_thresholds')


# ============================================================
# МЕНЮ ВЫБОРА ПОРОГА
# ============================================================

@thresholds_router.callback_query(F.data.regexp(r"^cf:secth:\d+$"))
async def section_threshold_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора порога срабатывания.

    Callback: cf:secth:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    current_threshold = section.threshold or 100

    text = (
        f"🎯 <b>Порог срабатывания</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Если сумма весов сработавших паттернов превысит порог — "
        f"сработает действие.\n\n"
        f"Текущий порог: <b>{current_threshold}</b> баллов"
    )

    keyboard = create_section_threshold_menu(section_id, current_threshold)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@thresholds_router.callback_query(F.data.regexp(r"^cf:secth:\d+:\d+$"))
async def set_section_threshold(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает порог срабатывания для раздела.

    Callback: cf:secth:{threshold}:{section_id}
    """
    parts = callback.data.split(":")
    threshold = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    success, error = await section_service.update_section(
        section_id=section_id,
        session=session,
        threshold=threshold
    )

    if success:
        await callback.answer(f"Порог: {threshold} баллов")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Обновляем меню
    section = await section_service.get_section_by_id(section_id, session)
    keyboard = create_section_threshold_menu(section_id, threshold)

    text = (
        f"🎯 <b>Порог срабатывания</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Если сумма весов сработавших паттернов превысит порог — "
        f"сработает действие.\n\n"
        f"Текущий порог: <b>{threshold}</b> баллов"
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# ДИФФЕРЕНЦИРОВАННЫЕ ПОРОГИ
# ============================================================

@thresholds_router.callback_query(F.data.regexp(r"^cf:secthr:\d+$"))
async def section_thresholds_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню дифференцированных порогов раздела.

    Callback: cf:secthr:{section_id}

    Позволяет задавать разные действия для разных диапазонов скора.
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Получаем пороги раздела
    thresholds = await section_service.get_section_thresholds(section_id, session)

    text = (
        f"📊 <b>Пороги баллов раздела</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
    )

    if thresholds:
        text += "Разные действия для разных диапазонов скора:\n\n"
        for t in thresholds:
            max_str = str(t.max_score) if t.max_score else "∞"
            range_str = f"{t.min_score}–{max_str}"
            action_map = {
                'delete': '🗑️ Удалить',
                'mute': '🔇 Мут',
                'ban': '🚫 Бан'
            }
            action_str = action_map.get(t.action, t.action)
            if t.action == 'mute' and t.mute_duration:
                hours = t.mute_duration // 60
                mins = t.mute_duration % 60
                if hours > 0:
                    action_str += f" {hours}ч"
                if mins > 0:
                    action_str += f" {mins}м"
            status = "✅" if t.enabled else "⏸️"
            text += f"{status} {range_str} баллов → {action_str}\n"
    else:
        text += (
            "<i>Нет дифференцированных порогов.</i>\n\n"
            "Добавьте пороги для градации действий по скору."
        )

    text += f"\n\n💡 Базовый порог раздела: {section.threshold} баллов"

    # Формируем клавиатуру
    buttons = []

    # Кнопки для существующих порогов
    for t in thresholds:
        max_str = str(t.max_score) if t.max_score else "∞"
        toggle_emoji = "⏸️" if t.enabled else "✅"
        buttons.append([
            InlineKeyboardButton(
                text=f"{toggle_emoji} {t.min_score}–{max_str}",
                callback_data=f"cf:secthrt:{t.id}:{section_id}"
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=f"cf:secthrd:{t.id}:{section_id}"
            )
        ])

    # Кнопка добавления
    buttons.append([
        InlineKeyboardButton(
            text="➕ Добавить порог",
            callback_data=f"cf:secthra:{section_id}"
        )
    ])

    # Назад
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:secs:{section_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@thresholds_router.callback_query(F.data.regexp(r"^cf:secthrt:\d+:\d+$"))
async def toggle_section_threshold(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает активность порога раздела.

    Callback: cf:secthrt:{threshold_id}:{section_id}
    """
    parts = callback.data.split(":")
    threshold_id = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    success = await section_service.toggle_section_threshold(threshold_id, session)

    if success:
        await callback.answer("Порог переключён")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)

    # Обновляем меню
    callback.data = f"cf:secthr:{section_id}"
    await section_thresholds_menu(callback, session)


@thresholds_router.callback_query(F.data.regexp(r"^cf:secthrd:\d+:\d+$"))
async def delete_section_threshold(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет порог раздела.

    Callback: cf:secthrd:{threshold_id}:{section_id}
    """
    parts = callback.data.split(":")
    threshold_id = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    success = await section_service.delete_section_threshold(threshold_id, session)

    if success:
        await callback.answer("Порог удалён")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

    # Обновляем меню
    callback.data = f"cf:secthr:{section_id}"
    await section_thresholds_menu(callback, session)


# ============================================================
# ДОБАВЛЕНИЕ ПОРОГА (FSM)
# ============================================================

@thresholds_router.callback_query(F.data.regexp(r"^cf:secthra:\d+$"))
async def start_add_section_threshold(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для добавления порога.

    Callback: cf:secthra:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(AddSectionThresholdStates.waiting_min_score)

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Шаг 1/3: Введите <b>минимальный</b> скор для этого порога.\n\n"
        f"Пример: <code>100</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@thresholds_router.message(AddSectionThresholdStates.waiting_min_score)
async def process_section_threshold_min_score(
    message: Message,
    state: FSMContext
) -> None:
    """Обрабатывает ввод минимального скора."""
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    try:
        min_score = int(message.text.strip())
        if min_score < 0:
            raise ValueError()
    except (ValueError, TypeError):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
        ])
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text="❌ Введите положительное число.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    await state.update_data(min_score=min_score)
    await state.set_state(AddSectionThresholdStates.waiting_max_score)

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Минимальный скор: {min_score}\n\n"
        f"Шаг 2/3: Введите <b>максимальный</b> скор (или 0 для ∞)."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
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


@thresholds_router.message(AddSectionThresholdStates.waiting_max_score)
async def process_section_threshold_max_score(
    message: Message,
    state: FSMContext
) -> None:
    """Обрабатывает ввод максимального скора."""
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')
    min_score = data.get('min_score')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    try:
        max_score = int(message.text.strip())
        if max_score < 0:
            raise ValueError()
    except (ValueError, TypeError):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
        ])
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text="❌ Введите положительное число или 0 для бесконечности.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    # 0 = бесконечность
    if max_score == 0:
        max_score = None

    await state.update_data(max_score=max_score)
    await state.set_state(AddSectionThresholdStates.waiting_action)

    max_text = str(max_score) if max_score else "∞"

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Диапазон: {min_score} - {max_text}\n\n"
        f"Шаг 3/3: Выберите действие."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"cf:secthraa:delete:{section_id}"),
            InlineKeyboardButton(text="🔇 Мут", callback_data=f"cf:secthraa:mute:{section_id}")
        ],
        [
            InlineKeyboardButton(text="🚫 Бан", callback_data=f"cf:secthraa:ban:{section_id}")
        ],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
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


@thresholds_router.callback_query(F.data.regexp(r"^cf:secthraa:(delete|mute|ban):\d+$"))
async def process_section_threshold_action(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает выбор действия для порога.

    Callback: cf:secthraa:{action}:{section_id}
    """
    parts = callback.data.split(":")
    action = parts[2]
    section_id = int(parts[3])

    data = await state.get_data()
    min_score = data.get('min_score')
    max_score = data.get('max_score')

    if action == 'mute':
        # Нужно запросить длительность мута
        await state.update_data(action=action)
        await state.set_state(AddSectionThresholdStates.waiting_mute_duration)

        text = (
            f"📊 <b>Добавление порога</b>\n\n"
            f"Диапазон: {min_score} - {max_score or '∞'}\n"
            f"Действие: мут\n\n"
            f"Введите длительность мута (например: 30, 1h, 1d):"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
        ])

        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except TelegramAPIError:
            pass

        await callback.answer()
        return

    # Создаём порог без длительности мута
    await state.clear()

    section_service = get_section_service()
    success, error = await section_service.add_section_threshold(
        section_id=section_id,
        min_score=min_score,
        max_score=max_score,
        action=action,
        mute_duration=None,
        session=session
    )

    if success:
        await callback.answer("✅ Порог добавлен")
    else:
        await callback.answer(f"❌ {error or 'Ошибка'}", show_alert=True)

    # Показываем меню порогов
    callback.data = f"cf:secthr:{section_id}"
    await section_thresholds_menu(callback, session)


@thresholds_router.message(AddSectionThresholdStates.waiting_mute_duration)
async def process_section_threshold_mute_duration(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод длительности мута для порога."""
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')
    min_score = data.get('min_score')
    max_score = data.get('max_score')
    action = data.get('action')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим длительность
    duration = parse_duration(message.text.strip())

    if duration is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secthr:{section_id}")]
        ])
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text="❌ Неверный формат. Попробуйте: 30, 1h, 1d",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    await state.clear()

    # Создаём порог
    section_service = get_section_service()
    success, error = await section_service.add_section_threshold(
        section_id=section_id,
        min_score=min_score,
        max_score=max_score,
        action=action,
        mute_duration=duration,
        session=session
    )

    if success:
        text = "✅ Порог добавлен"
    else:
        text = f"❌ {error or 'Ошибка'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К порогам", callback_data=f"cf:secthr:{section_id}")]
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
