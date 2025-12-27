# ============================================================
# BASE SIGNALS - НАСТРОЙКА БАЗОВЫХ СИГНАЛОВ ДЕТЕКТОРА
# ============================================================
# Этот модуль содержит хендлеры для управления базовыми сигналами:
# - base_signals_menu: меню сигналов
# - toggle_base_signal: включение/отключение сигнала
# - start_edit_signal_weight: редактирование веса
# - process_signal_weight: обработка ввода веса
# - reset_all_base_signals: сброс к дефолтам
#
# Базовые сигналы определены в scam_detector.py:
# money_amount, income_period, easy_money, call_to_action, crypto,
# recruitment, remote_work, exclamations, urgency, scheme,
# training, investments, gambling, age_restriction, unique_offer
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
from sqlalchemy import select, delete

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и константы
from bot.handlers.content_filter.common import EditBaseSignalWeightStates, BASE_SIGNAL_NAMES
# Импортируем модель BaseSignalOverride
from bot.database.models_content_filter import BaseSignalOverride

# Создаём роутер для базовых сигналов
base_signals_router = Router(name='scam_base_signals')


# ============================================================
# HELPER: Получение переопределений из таблицы
# ============================================================

async def get_signal_overrides(chat_id: int, session: AsyncSession) -> dict:
    """
    Получает переопределения сигналов из таблицы BaseSignalOverride.

    Возвращает словарь вида:
    {
        "signal_name": {"enabled": True/False, "weight": 100 или None}
    }
    """
    result = await session.execute(
        select(BaseSignalOverride).where(BaseSignalOverride.chat_id == chat_id)
    )
    overrides_list = result.scalars().all()

    overrides = {}
    for override in overrides_list:
        overrides[override.signal_name] = {
            "enabled": override.enabled,
            "weight": override.weight_override
        }
    return overrides


async def get_or_create_signal_override(
    chat_id: int,
    signal_name: str,
    session: AsyncSession
) -> BaseSignalOverride:
    """
    Получает или создаёт запись переопределения сигнала.
    """
    result = await session.execute(
        select(BaseSignalOverride).where(
            BaseSignalOverride.chat_id == chat_id,
            BaseSignalOverride.signal_name == signal_name
        )
    )
    override = result.scalar_one_or_none()

    if not override:
        override = BaseSignalOverride(
            chat_id=chat_id,
            signal_name=signal_name,
            enabled=True,
            weight_override=None
        )
        session.add(override)

    return override


# ============================================================
# HELPER: Рендер меню базовых сигналов
# ============================================================

async def _render_base_signals_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    chat_id: int
) -> None:
    """
    Рендерит меню настройки базовых сигналов.

    Вынесено в отдельную функцию для переиспользования из toggle/reset.

    Args:
        callback: CallbackQuery
        session: Сессия БД
        chat_id: ID чата
    """
    # Получаем переопределения из таблицы
    overrides = await get_signal_overrides(chat_id, session)

    # Формируем текст
    text = (
        f"⚙️ <b>Базовые сигналы антискама</b>\n\n"
        f"Настройте веса и состояние каждого сигнала.\n"
        f"✅ = включён, ❌ = выключен\n\n"
    )

    # Показываем сигналы
    for signal_key, signal_name in BASE_SIGNAL_NAMES.items():
        override = overrides.get(signal_key, {})
        enabled = override.get('enabled', True)
        weight = override.get('weight', None)

        status = "✅" if enabled else "❌"
        weight_text = f" ({weight})" if weight is not None else ""
        text += f"{status} {signal_name}{weight_text}\n"

    # Клавиатура - по 2 сигнала в ряд
    keyboard_rows = []
    signals = list(BASE_SIGNAL_NAMES.keys())

    for i in range(0, len(signals), 2):
        row = []
        for j in range(2):
            if i + j < len(signals):
                signal = signals[i + j]
                override = overrides.get(signal, {})
                enabled = override.get('enabled', True)
                emoji = "✅" if enabled else "❌"
                # Укорачиваем название
                short_name = signal[:8]
                row.append(InlineKeyboardButton(
                    text=f"{emoji} {short_name}",
                    callback_data=f"cf:bsigt:{signal}:{chat_id}"
                ))
        keyboard_rows.append(row)

    # Добавляем кнопки управления
    keyboard_rows.append([
        InlineKeyboardButton(
            text="⚖️ Изменить веса",
            callback_data=f"cf:bsigwm:{chat_id}"
        ),
        InlineKeyboardButton(
            text="🔄 Сбросить всё",
            callback_data=f"cf:bsigr:{chat_id}"
        )
    ])
    keyboard_rows.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:scs:{chat_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# МЕНЮ БАЗОВЫХ СИГНАЛОВ
# ============================================================

@base_signals_router.callback_query(F.data.regexp(r"^cf:bsig:-?\d+$"))
async def base_signals_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настройки базовых сигналов.

    Callback: cf:bsig:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await _render_base_signals_menu(callback, session, chat_id)
    await callback.answer()


# ============================================================
# ПЕРЕКЛЮЧЕНИЕ СИГНАЛА
# ============================================================

@base_signals_router.callback_query(F.data.regexp(r"^cf:bsigt:\w+:-?\d+$"))
async def toggle_base_signal(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает включение/отключение базового сигнала.

    Callback: cf:bsigt:{signal_key}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    signal_key = parts[2]
    chat_id = int(parts[3])

    # Получаем или создаём запись в таблице
    override = await get_or_create_signal_override(chat_id, signal_key, session)

    # Переключаем состояние
    override.enabled = not override.enabled
    await session.commit()

    signal_name = BASE_SIGNAL_NAMES.get(signal_key, signal_key)
    status = "включён" if override.enabled else "выключен"
    await callback.answer(f"{signal_name} {status}")

    # Обновляем меню используя helper
    await _render_base_signals_menu(callback, session, chat_id)


# ============================================================
# МЕНЮ РЕДАКТИРОВАНИЯ ВЕСОВ
# ============================================================

@base_signals_router.callback_query(F.data.regexp(r"^cf:bsigwm:-?\d+$"))
async def weights_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню редактирования весов сигналов.

    Callback: cf:bsigwm:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем переопределения из таблицы
    overrides = await get_signal_overrides(chat_id, session)

    # Формируем текст
    text = (
        f"⚖️ <b>Редактирование весов сигналов</b>\n\n"
        f"Нажмите на сигнал чтобы изменить его вес.\n"
        f"Стандартный вес = 100 баллов.\n\n"
    )

    for signal_key, signal_name in BASE_SIGNAL_NAMES.items():
        override = overrides.get(signal_key, {})
        weight = override.get('weight', None)
        weight_text = str(weight) if weight is not None else "100 (стд)"
        text += f"• {signal_name}: <b>{weight_text}</b>\n"

    # Клавиатура - кнопки для редактирования веса каждого сигнала
    keyboard_rows = []
    signals = list(BASE_SIGNAL_NAMES.items())

    for i in range(0, len(signals), 2):
        row = []
        for j in range(2):
            if i + j < len(signals):
                signal_key, signal_name = signals[i + j]
                override = overrides.get(signal_key, {})
                weight = override.get('weight', None)
                weight_text = str(weight) if weight else "100"
                # Укорачиваем название
                short_name = signal_key[:6]
                row.append(InlineKeyboardButton(
                    text=f"{short_name}:{weight_text}",
                    callback_data=f"cf:bsigw:{signal_key}:{chat_id}"
                ))
        keyboard_rows.append(row)

    # Кнопка назад
    keyboard_rows.append([
        InlineKeyboardButton(
            text="◀️ Назад к сигналам",
            callback_data=f"cf:bsig:{chat_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# РЕДАКТИРОВАНИЕ ВЕСА СИГНАЛА
# ============================================================

@base_signals_router.callback_query(F.data.regexp(r"^cf:bsigw:\w+:-?\d+$"))
async def start_edit_signal_weight(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает редактирование веса сигнала.

    Callback: cf:bsigw:{signal_key}:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    signal_key = parts[2]
    chat_id = int(parts[3])

    signal_name = BASE_SIGNAL_NAMES.get(signal_key, signal_key)

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        signal_key=signal_key
    )
    await state.set_state(EditBaseSignalWeightStates.waiting_weight)

    text = (
        f"⚖️ <b>Изменение веса: {signal_name}</b>\n\n"
        f"Введите новый вес (положительное число).\n"
        f"Стандартный вес: 100"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:bsig:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@base_signals_router.message(EditBaseSignalWeightStates.waiting_weight)
async def process_signal_weight(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод веса сигнала.

    Args:
        message: Сообщение с весом
        state: FSMContext
        session: Сессия БД
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим вес
    try:
        weight = int(message.text.strip())
        if weight <= 0:
            raise ValueError("Вес должен быть положительным")
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    signal_key = data.get('signal_key')

    # Получаем или создаём запись в таблице
    override = await get_or_create_signal_override(chat_id, signal_key, session)

    # Обновляем вес
    override.weight_override = weight
    await session.commit()

    await state.clear()

    signal_name = BASE_SIGNAL_NAMES.get(signal_key, signal_key)
    await message.answer(f"✅ Вес {signal_name} установлен: {weight}")

    # Показываем меню (создаём фейковый callback)
    # Просто отправляем сообщение с меню
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К сигналам", callback_data=f"cf:bsig:{chat_id}")]
    ])
    await message.answer("Нажмите для возврата:", reply_markup=keyboard)


# ============================================================
# СБРОС ВСЕХ СИГНАЛОВ
# ============================================================

@base_signals_router.callback_query(F.data.regexp(r"^cf:bsigr:-?\d+$"))
async def reset_all_base_signals(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Сбрасывает все переопределения сигналов к дефолтам.

    Callback: cf:bsigr:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Удаляем все переопределения для группы из таблицы
    await session.execute(
        delete(BaseSignalOverride).where(BaseSignalOverride.chat_id == chat_id)
    )
    await session.commit()

    logger.info(f"[ContentFilter] Сброшены базовые сигналы для чата {chat_id}")

    await callback.answer("✅ Все сигналы сброшены к дефолтам")

    # Обновляем меню используя helper
    await _render_base_signals_menu(callback, session, chat_id)
