# ============================================================
# THRESHOLDS - ПОРОГИ БАЛЛОВ АНТИСКАМА
# ============================================================
# Этот модуль содержит хендлеры для управления порогами:
# - scam_thresholds_menu: меню порогов
# - toggle_threshold: включение/отключение порога
# - delete_threshold: удаление порога
# - start_add_threshold: добавление порога
# - process_min_score, process_max_score: ввод диапазона
# - process_threshold_action: выбор действия
#
# Пороги позволяют задавать разные действия для разных
# диапазонов скора. Например:
# - 100-299 → delete
# - 300-399 → mute 1ч
# - 400+ → ban
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

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и утилиты парсинга
from bot.handlers.content_filter.common import AddThresholdStates, parse_duration
# Импортируем сервис порогов
from bot.services.content_filter.scam_pattern_service import get_threshold_service

# Создаём роутер для порогов
thresholds_router = Router(name='scam_thresholds')


# ============================================================
# МЕНЮ ПОРОГОВ БАЛЛОВ
# ============================================================

@thresholds_router.callback_query(F.data.regexp(r"^cf:scthr:-?\d+$"))
async def scam_thresholds_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню порогов баллов антискама.

    Callback: cf:scthr:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис порогов
    threshold_service = get_threshold_service()

    # Получаем пороги
    thresholds = await threshold_service.get_thresholds(chat_id, session)

    # Формируем текст
    text = (
        f"📊 <b>Пороги баллов антискама</b>\n\n"
        f"Задайте разные действия для разных диапазонов скора.\n\n"
    )

    if thresholds:
        text += "<b>Текущие пороги:</b>\n"
        for t in thresholds:
            status = "✅" if t.enabled else "❌"
            max_text = str(t.max_score) if t.max_score else "∞"
            action_text = t.action
            if t.action == 'mute' and t.mute_duration:
                action_text = f"mute {t.mute_duration}м"
            text += f"{status} {t.min_score}-{max_text}: {action_text}\n"
    else:
        text += "<i>Пороги не настроены. Используется действие по умолчанию.</i>"

    # Клавиатура
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➕ Добавить порог",
            callback_data=f"cf:scthra:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:scs:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ ПОРОГА (FSM)
# ============================================================

@thresholds_router.callback_query(F.data.regexp(r"^cf:scthra:-?\d+$"))
async def start_add_threshold(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления порога.

    Callback: cf:scthra:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем в FSM
    await state.update_data(chat_id=chat_id)
    await state.set_state(AddThresholdStates.waiting_min_score)

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Шаг 1/3: Введите <b>минимальный</b> скор для этого порога.\n\n"
        f"Пример: <code>100</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:scthr:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@thresholds_router.message(AddThresholdStates.waiting_min_score)
async def process_min_score(
    message: Message,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод минимального скора.

    Args:
        message: Сообщение со скором
        state: FSMContext
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим скор
    try:
        min_score = int(message.text.strip())
        if min_score < 0:
            raise ValueError("Скор должен быть положительным")
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    # Сохраняем в FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    await state.update_data(min_score=min_score)
    await state.set_state(AddThresholdStates.waiting_max_score)

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Минимальный скор: {min_score}\n\n"
        f"Шаг 2/3: Введите <b>максимальный</b> скор (или 0 для ∞)."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:scthr:{chat_id}"
        )]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@thresholds_router.message(AddThresholdStates.waiting_max_score)
async def process_max_score(
    message: Message,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод максимального скора.

    Args:
        message: Сообщение со скором
        state: FSMContext
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим скор
    try:
        max_score = int(message.text.strip())
        if max_score < 0:
            raise ValueError("Скор должен быть положительным")
    except ValueError:
        await message.answer("❌ Введите положительное число или 0 для бесконечности.")
        return

    # Сохраняем в FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    min_score = data.get('min_score')
    await state.update_data(max_score=max_score if max_score > 0 else None)
    await state.set_state(AddThresholdStates.waiting_action)

    max_text = str(max_score) if max_score > 0 else "∞"

    text = (
        f"📊 <b>Добавление порога</b>\n\n"
        f"Диапазон: {min_score} - {max_text}\n\n"
        f"Шаг 3/3: Выберите действие."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"cf:scthrac:delete:{chat_id}"),
            InlineKeyboardButton(text="🔇 Мут", callback_data=f"cf:scthrac:mute:{chat_id}")
        ],
        [
            InlineKeyboardButton(text="🚫 Бан", callback_data=f"cf:scthrac:ban:{chat_id}")
        ],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:scthr:{chat_id}"
        )]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@thresholds_router.callback_query(F.data.regexp(r"^cf:scthrac:(delete|mute|ban):-?\d+$"))
async def process_threshold_action(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает выбор действия для порога.

    Callback: cf:scthrac:{action}:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    action = parts[2]
    chat_id = int(parts[3])

    # Получаем данные из FSM
    data = await state.get_data()
    min_score = data.get('min_score')
    max_score = data.get('max_score')

    if action == 'mute':
        # Нужно запросить длительность
        await state.update_data(action=action)
        await state.set_state(AddThresholdStates.waiting_mute_duration)

        text = (
            f"📊 <b>Добавление порога</b>\n\n"
            f"Диапазон: {min_score} - {max_score or '∞'}\n"
            f"Действие: мут\n\n"
            f"Введите длительность мута (в минутах или формате 1h, 1d):"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scthr:{chat_id}")]
        ])

        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except TelegramAPIError:
            pass

        await callback.answer()
        return

    # Создаём порог без длительности
    threshold_service = get_threshold_service()

    await threshold_service.add_threshold(
        chat_id=chat_id,
        min_score=min_score,
        max_score=max_score,
        action=action,
        mute_duration=None,
        session=session
    )

    await state.clear()

    # Показываем меню порогов
    await scam_thresholds_menu(callback, session)

    await callback.answer("✅ Порог добавлен")


@thresholds_router.message(AddThresholdStates.waiting_mute_duration)
async def process_mute_duration(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод длительности мута для порога.

    Args:
        message: Сообщение с длительностью
        state: FSMContext
        session: Сессия БД
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим длительность (поддерживает форматы: 30, 1h, 1d и т.д.)
    duration = parse_duration(message.text.strip())

    if duration is None or duration <= 0:
        await message.answer("❌ Неверный формат. Введите число минут или формат вида 1h, 1d.")
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    min_score = data.get('min_score')
    max_score = data.get('max_score')
    action = data.get('action')

    # Создаём порог с длительностью мута
    threshold_service = get_threshold_service()

    await threshold_service.add_threshold(
        chat_id=chat_id,
        min_score=min_score,
        max_score=max_score,
        action=action,
        mute_duration=duration,
        session=session
    )

    await state.clear()

    # Показываем меню порогов — создаём фейковый callback
    # для вызова scam_thresholds_menu
    from aiogram.types import CallbackQuery as CQ
    message.data = f"cf:scthr:{chat_id}"

    # Формируем текст и клавиатуру напрямую
    thresholds = await threshold_service.get_thresholds(chat_id, session)

    text = (
        f"✅ Порог добавлен!\n\n"
        f"📊 <b>Пороги баллов антискама</b>\n\n"
    )

    if thresholds:
        text += "<b>Текущие пороги:</b>\n"
        for t in thresholds:
            status = "✅" if t.enabled else "❌"
            max_text = str(t.max_score) if t.max_score else "∞"
            action_text = t.action
            if t.action == 'mute' and t.mute_duration:
                action_text = f"mute {t.mute_duration}м"
            text += f"{status} {t.min_score}-{max_text}: {action_text}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➕ Добавить порог",
            callback_data=f"cf:scthra:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:scs:{chat_id}"
        )]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@thresholds_router.callback_query(F.data.regexp(r"^cf:scthrx:-?\d+$"))
async def cancel_add_threshold(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Отменяет добавление порога.

    Callback: cf:scthrx:{chat_id}
    """
    await state.clear()
    await scam_thresholds_menu(callback, session)
