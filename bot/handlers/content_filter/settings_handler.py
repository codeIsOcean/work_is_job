# ============================================================
# SETTINGS HANDLER - UI НАСТРОЕК CONTENT FILTER
# ============================================================
# Этот хендлер обрабатывает callback query для настройки модуля:
# - Главное меню модуля
# - Включение/выключение подмодулей
# - Управление словами
# - Выбор чувствительности и действий
#
# Callback формат: cf:{action}:{params}:{chat_id}
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы callback и клавиатуры
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем FSM для добавления слов
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError
# Импортируем логгер
import logging

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

# Импортируем модели
from bot.database.models_content_filter import FilterWord, ScamPattern
# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_content_filter_main_menu,
    create_content_filter_settings_menu,
    create_words_menu,
    create_sensitivity_menu,
    create_action_menu,
    create_clear_words_confirm_menu,
    create_words_list_menu,
    create_flood_settings_menu,
    # Клавиатуры для паттернов скама
    create_scam_patterns_menu,
    create_pattern_type_menu,
    create_pattern_weight_menu,
    create_patterns_list_menu,
    create_pattern_delete_confirm_menu,
    create_clear_patterns_confirm_menu,
    create_import_preview_menu,
    create_cancel_pattern_input_menu,
    # Клавиатура выбора веса при импорте
    create_import_weight_menu,
    # Клавиатуры для раздельных действий
    create_word_filter_action_menu,
    create_flood_action_menu,
    # НОВЫЕ: Клавиатуры для категорий слов
    create_word_filter_settings_menu,
    create_category_action_menu,
    create_scam_settings_menu,
    create_category_words_list_menu,
    # Клавиатура выбора действия антискама
    create_scam_action_menu
)
# Импортируем FilterManager и сервис паттернов
from bot.services.content_filter import FilterManager, get_pattern_service

# Импортируем Redis клиент для FloodDetector
from bot.services.redis_conn import redis

# Создаём логгер
logger = logging.getLogger(__name__)

# Создаём роутер для настроек
settings_handler_router = Router(name='content_filter_settings')

# Глобальный FilterManager с Redis для FloodDetector
_filter_manager = FilterManager(redis=redis)

# Количество слов на странице в списке
WORDS_PER_PAGE = 10


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ ДОБАВЛЕНИЯ СЛОВ
# ============================================================

class AddWordStates(StatesGroup):
    """Состояния FSM для добавления запрещённого слова."""
    # Ожидание ввода слова от пользователя
    waiting_for_word = State()


class AddPatternStates(StatesGroup):
    """Состояния FSM для добавления паттерна скама."""
    # Ожидание ввода паттерна от пользователя
    waiting_for_pattern = State()
    # Ожидание текста для импорта
    waiting_for_import_text = State()


class DurationInputStates(StatesGroup):
    """Состояния FSM для ручного ввода времени.

    Форматы: s (секунды), min (минуты), h (часы), d (дни), m (месяцы)
    Примеры: 30s, 5min, 1h, 1d, 1m
    """
    # Ожидание ввода длительности для категории слов
    waiting_for_duration = State()
    # Ожидание ввода длительности для антискама
    waiting_for_scam_duration = State()


class CategoryTextStates(StatesGroup):
    """Состояния FSM для ввода кастомного текста уведомлений.

    Поддерживает плейсхолдер %user% для упоминания пользователя.
    """
    # Ожидание ввода текста уведомления при муте
    waiting_for_mute_text = State()
    # Ожидание ввода текста уведомления при бане
    waiting_for_ban_text = State()


class CategoryDelayStates(StatesGroup):
    """Состояния FSM для ввода задержек.

    Форматы: s (секунды), min (минуты), h (часы)
    Примеры: 30s, 5min, 1h
    """
    # Ожидание ввода задержки удаления сообщения нарушителя
    waiting_for_delete_delay = State()
    # Ожидание ввода задержки автоудаления уведомления бота
    waiting_for_notification_delay = State()


# Количество паттернов на странице
PATTERNS_PER_PAGE = 5


def parse_duration(duration_str: str) -> int:
    """Парсит строку длительности и возвращает минуты.

    Форматы:
    - 30s = 30 секунд = 0 минут (минимум 1)
    - 5min = 5 минут
    - 1h = 1 час = 60 минут
    - 1d = 1 день = 1440 минут
    - 1m = 1 месяц = 43200 минут (30 дней)

    Args:
        duration_str: Строка вида "30s", "5min", "1h", "1d", "1m" или просто число (минуты)

    Returns:
        int: Длительность в минутах, или None если формат неверный
    """
    import re

    # Проверка на пустой ввод
    if not duration_str or not duration_str.strip():
        return None

    # Приводим к нижнему регистру и убираем пробелы
    s = duration_str.lower().strip()

    # Проверка на отрицательные числа
    if s.startswith('-'):
        return None

    # Сначала пробуем с единицами измерения
    match = re.match(r'^(\d+)\s*(s|sec|min|h|hour|d|day|m|month)$', s)
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        # Конвертируем в минуты
        if unit in ('s', 'sec'):
            # Секунды -> минуты (минимум 1 минута)
            return max(1, value // 60)
        elif unit == 'min':
            return value
        elif unit in ('h', 'hour'):
            return value * 60
        elif unit in ('d', 'day'):
            return value * 1440
        elif unit in ('m', 'month'):
            return value * 43200

    # Пробуем как просто число (минуты по умолчанию)
    if re.match(r'^\d+$', s):
        return int(s)

    # Неверный формат
    return None


def parse_delay_seconds(delay_str: str) -> int:
    """Парсит строку задержки и возвращает секунды.

    Форматы:
    - 30s или 30 = 30 секунд
    - 5min = 5 минут = 300 секунд
    - 1h = 1 час = 3600 секунд

    Args:
        delay_str: Строка вида "30s", "5min", "1h" или просто число (секунды)

    Returns:
        int: Задержка в секундах, или None если формат неверный
    """
    import re

    # Проверка на пустой ввод
    if not delay_str or not delay_str.strip():
        return None

    # Приводим к нижнему регистру и убираем пробелы
    s = delay_str.lower().strip()

    # Проверка на отрицательные числа
    if s.startswith('-'):
        return None

    # Пробуем с единицами измерения
    match = re.match(r'^(\d+)\s*(s|sec|min|h|hour)$', s)
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        # Конвертируем в секунды
        if unit in ('s', 'sec'):
            return value
        elif unit == 'min':
            return value * 60
        elif unit in ('h', 'hour'):
            return value * 3600

    # Пробуем как просто число (секунды по умолчанию)
    if re.match(r'^\d+$', s):
        return int(s)

    # Неверный формат
    return None


# ============================================================
# ГЛАВНОЕ МЕНЮ МОДУЛЯ
# ============================================================

@settings_handler_router.callback_query(F.data.startswith("cf:m:"))
async def content_filter_main_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает главное меню модуля content_filter.

    Callback: cf:m:{chat_id}

    Args:
        callback: CallbackQuery от пользователя
        session: Сессия БД
    """
    # Парсим chat_id из callback_data
    # Формат: cf:m:{chat_id}
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки группы
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    status_emoji = "✅" if settings.enabled else "❌"
    text = (
        f"🔍 <b>Фильтр контента</b>\n\n"
        f"Статус: {status_emoji} {'Включён' if settings.enabled else 'Выключен'}\n\n"
        f"Модуль фильтрует сообщения на наличие:\n"
        f"• Запрещённых слов\n"
        f"• Скам-сообщений\n"
        f"• Повторяющегося контента (флуд)\n"
    )

    # Создаём клавиатуру
    keyboard = create_content_filter_main_menu(chat_id, settings)

    # Редактируем сообщение
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        # Сообщение не изменилось - игнорируем
        pass

    # Отвечаем на callback
    await callback.answer()


# ============================================================
# ВКЛЮЧЕНИЕ/ВЫКЛЮЧЕНИЕ МОДУЛЯ
# ============================================================

@settings_handler_router.callback_query(F.data.startswith("cf:t:on:") | F.data.startswith("cf:t:off:"))
async def toggle_module(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Включает или выключает весь модуль content_filter.

    Callback: cf:t:on:{chat_id} или cf:t:off:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    action = parts[2]  # on или off
    chat_id = int(parts[3])

    # Определяем новое состояние
    enabled = (action == "on")

    # Обновляем настройки
    await _filter_manager.toggle_module(chat_id, enabled, session)

    # Показываем обновлённое главное меню
    settings = await _filter_manager.get_or_create_settings(chat_id, session)
    status_emoji = "✅" if settings.enabled else "❌"

    text = (
        f"🔍 <b>Фильтр контента</b>\n\n"
        f"Статус: {status_emoji} {'Включён' if settings.enabled else 'Выключен'}\n\n"
        f"Модуль фильтрует сообщения на наличие:\n"
        f"• Запрещённых слов\n"
        f"• Скам-сообщений\n"
        f"• Повторяющегося контента (флуд)\n"
    )

    keyboard = create_content_filter_main_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    # Уведомление
    await callback.answer(f"Модуль {'включён' if enabled else 'выключен'}")


# ============================================================
# МЕНЮ НАСТРОЕК ПОДМОДУЛЕЙ
# ============================================================

@settings_handler_router.callback_query(F.data.startswith("cf:s:"))
async def settings_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек подмодулей.

    Callback: cf:s:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст
    text = (
        f"⚙️ <b>Настройки фильтра</b>\n\n"
        f"Включите/выключите отдельные модули фильтрации.\n"
        f"Настройте чувствительность и действия."
    )

    # Клавиатура
    keyboard = create_content_filter_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ПЕРЕКЛЮЧЕНИЕ ПОДМОДУЛЕЙ
# ============================================================

@settings_handler_router.callback_query(F.data.startswith("cf:t:wf:") | F.data.startswith("cf:t:sc:") |
                                         F.data.startswith("cf:t:fl:") | F.data.startswith("cf:t:log:") |
                                         F.data.startswith("cf:t:sw:") | F.data.startswith("cf:t:hw:") |
                                         F.data.startswith("cf:t:ow:"))
async def toggle_submodule(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает отдельные подмодули и категории слов.

    Callbacks:
    - cf:t:wf:{chat_id} - word filter
    - cf:t:sc:{chat_id} - scam detection
    - cf:t:fl:{chat_id} - flood detection
    - cf:t:log:{chat_id} - logging
    - cf:t:sw:{chat_id} - simple words (категория)
    - cf:t:hw:{chat_id} - harmful words (категория)
    - cf:t:ow:{chat_id} - obfuscated words (категория)

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    submodule = parts[2]  # wf, sc, fl, log, sw, hw, ow
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Определяем поле для обновления и инвертируем
    # Маппинг: код подмодуля -> поле в БД
    field_map = {
        'wf': 'word_filter_enabled',
        'sc': 'scam_detection_enabled',
        'fl': 'flood_detection_enabled',
        'log': 'log_violations',
        # Новые категории слов
        'sw': 'simple_words_enabled',
        'hw': 'harmful_words_enabled',
        'ow': 'obfuscated_words_enabled'
    }

    # Категории которые возвращают в меню настроек слов
    word_categories = {'sw', 'hw', 'ow'}

    field_name = field_map.get(submodule)
    if field_name:
        # Получаем текущее значение и инвертируем
        current_value = getattr(settings, field_name, True)
        new_value = not current_value

        # Обновляем
        await _filter_manager.update_settings(chat_id, session, **{field_name: new_value})

    # Показываем обновлённое меню
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Определяем какое меню показать
    if submodule in word_categories:
        # Возвращаемся в меню настроек фильтра слов
        text = (
            f"🔤 <b>Настройки фильтра слов</b>\n\n"
            f"Три категории с разными действиями:\n"
            f"• 📝 Простые — реклама, спам\n"
            f"• 💊 Вредные — наркотики, запрещённое\n"
            f"• 🔀 Обфускация — l33tspeak обходы"
        )
        keyboard = create_word_filter_settings_menu(chat_id, settings)
    else:
        # Возвращаемся в главное меню
        status_emoji = "✅" if settings.enabled else "❌"
        text = (
            f"🔍 <b>Фильтр контента</b>\n\n"
            f"Статус: {status_emoji} {'Включён' if settings.enabled else 'Выключен'}\n\n"
            f"Модуль фильтрует сообщения на наличие:\n"
            f"• Запрещённых слов\n"
            f"• Скам-сообщений\n"
            f"• Повторяющегося контента (флуд)\n"
        )
        keyboard = create_content_filter_main_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Настройка изменена")


# ============================================================
# МЕНЮ НАСТРОЕК ФИЛЬТРА СЛОВ (3 КАТЕГОРИИ)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wfs:-?\d+$"))
async def word_filter_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек фильтра слов с 3 категориями.

    Callback: cf:wfs:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст
    text = (
        f"🔤 <b>Настройки фильтра слов</b>\n\n"
        f"Три категории с разными действиями:\n"
        f"• 📝 Простые — реклама, спам\n"
        f"• 💊 Вредные — наркотики, запрещённое\n"
        f"• 🔀 Обфускация — l33tspeak обходы\n\n"
        f"📋 — список слов категории\n"
        f"🗑️/🔇/🚫 — действие при срабатывании"
    )

    # Клавиатура
    keyboard = create_word_filter_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# МЕНЮ НАСТРОЕК АНТИСКАМА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scs:-?\d+$"))
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
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

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

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scact:-?\d+$"))
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
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

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


@settings_handler_router.callback_query(F.data.regexp(r"^cf:scact:(delete|mute|ban):-?\d+$"))
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
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

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


@settings_handler_router.callback_query(F.data.regexp(r"^cf:scact:time:-?\d+$"))
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


@settings_handler_router.message(DurationInputStates.waiting_for_scam_duration)
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
    settings = await _filter_manager.get_or_create_settings(chat_id, session)
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


# ============================================================
# ВЫБОР ДЕЙСТВИЯ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)a:-?\d+$"))
async def category_action_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора действия для категории слов.

    Callbacks:
    - cf:swa:{chat_id} - действие для простых слов
    - cf:hwa:{chat_id} - действие для вредных слов
    - cf:owa:{chat_id} - действие для обфускации

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние если оно было активно (при отмене ввода времени)
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    # Извлекаем категорию: swa -> sw, hwa -> hw, owa -> ow
    category_full = parts[1]  # swa, hwa, owa
    category = category_full[:-1]  # sw, hw, ow
    chat_id = int(parts[2])

    # Маппинг категории на поле действия
    action_field_map = {
        'sw': 'simple_words_action',
        'hw': 'harmful_words_action',
        'ow': 'obfuscated_words_action'
    }
    duration_field_map = {
        'sw': 'simple_words_mute_duration',
        'hw': 'harmful_words_mute_duration',
        'ow': 'obfuscated_words_mute_duration'
    }
    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Получаем текущие значения
    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)

    # Формируем текст
    text = (
        f"⚡ <b>Действие: {category_names[category]}</b>\n\n"
        f"Выберите действие при срабатывании:\n"
        f"• 🗑️ Удалить — только удалить сообщение\n"
        f"• 🔇 Мут — удалить + мут на время\n"
        f"• 🚫 Бан — удалить + бан\n\n"
        f"⏱️ — задать время вручную\n"
        f"Форматы: 30s, 5min, 1h, 1d, 1m"
    )

    # Клавиатура
    keyboard = create_category_action_menu(chat_id, category, current_action, current_duration)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УСТАНОВКА ДЕЙСТВИЯ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)a:(delete|mute|ban):-?\d+$"))
async def set_category_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие для категории слов.

    Callback: cf:{category}a:{action}:{chat_id}
    Пример: cf:swa:mute:-1001234567890

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    # cf:swa:mute:-1001234567890 -> ['cf', 'swa', 'mute', '-1001234567890']
    category_full = parts[1]  # swa, hwa, owa
    category = category_full[:-1]  # sw, hw, ow
    action = parts[2]  # delete, mute, ban
    chat_id = int(parts[3])

    # ─────────────────────────────────────────────────────────
    # Маппинг категории на поля в БД
    # action_field - поле для хранения типа действия (delete/mute/ban)
    # duration_field - поле для хранения длительности мута в минутах
    # ─────────────────────────────────────────────────────────
    action_field_map = {
        'sw': 'simple_words_action',
        'hw': 'harmful_words_action',
        'ow': 'obfuscated_words_action'
    }
    duration_field_map = {
        'sw': 'simple_words_mute_duration',
        'hw': 'harmful_words_mute_duration',
        'ow': 'obfuscated_words_mute_duration'
    }

    # ─────────────────────────────────────────────────────────
    # Получаем текущие настройки чтобы проверить duration
    # ─────────────────────────────────────────────────────────
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # ─────────────────────────────────────────────────────────
    # Подготавливаем данные для обновления
    # ─────────────────────────────────────────────────────────
    field_name = action_field_map[category]
    duration_field = duration_field_map[category]
    update_data = {field_name: action}

    # ─────────────────────────────────────────────────────────
    # ВАЖНО: Если выбран мут и duration ещё не установлен -
    # устанавливаем дефолтное значение из default_mute_duration
    # Это исправляет баг когда мут делался на 720ч вместо заданного времени
    # ─────────────────────────────────────────────────────────
    if action == 'mute':
        # Получаем текущую длительность для этой категории
        current_duration = getattr(settings, duration_field, None)
        # Если длительность не установлена - ставим дефолтную
        if current_duration is None:
            # Используем default_mute_duration как начальное значение
            update_data[duration_field] = settings.default_mute_duration or 1440

    # ─────────────────────────────────────────────────────────
    # Обновляем настройки в БД
    # ─────────────────────────────────────────────────────────
    await _filter_manager.update_settings(chat_id, session, **update_data)

    # Получаем обновлённые настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Возвращаемся в меню настроек фильтра слов
    text = (
        f"🔤 <b>Настройки фильтра слов</b>\n\n"
        f"Три категории с разными действиями:\n"
        f"• 📝 Простые — реклама, спам\n"
        f"• 💊 Вредные — наркотики, запрещённое\n"
        f"• 🔀 Обфускация — l33tspeak обходы"
    )
    keyboard = create_word_filter_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Действие установлено")


# ============================================================
# РУЧНОЙ ВВОД ВРЕМЕНИ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)(t|bt):-?\d+$"))
async def request_duration_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод времени для мута/бана категории.

    Callbacks:
    - cf:swt:{chat_id} - время мута для простых
    - cf:hwt:{chat_id} - время мута для вредных
    - cf:owt:{chat_id} - время мута для обфускации
    - cf:swbt:{chat_id} - время бана для простых
    - и т.д.

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM состояние
    """
    # Парсим данные
    parts = callback.data.split(":")
    # cf:swt:-1001234567890 -> ['cf', 'swt', '-1001234567890']
    category_type = parts[1]  # swt, hwt, owt, swbt, hwbt, owbt
    chat_id = int(parts[2])

    # Определяем категорию и тип (мут или бан)
    if category_type.endswith('bt'):
        # Бан: swbt -> sw, hwbt -> hw, owbt -> ow
        category = category_type[:-2]
        action_type = 'ban'
    else:
        # Мут: swt -> sw, hwt -> hw, owt -> ow
        category = category_type[:-1]
        action_type = 'mute'

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Сохраняем в FSM (включая message_id для последующего редактирования)
    await state.set_state(DurationInputStates.waiting_for_duration)
    await state.update_data(
        chat_id=chat_id,
        category=category,
        action_type=action_type,
        instruction_message_id=callback.message.message_id
    )

    # Просим ввести время
    text = (
        f"⏱️ <b>Введите длительность {action_type} для {category_names[category]}</b>\n\n"
        f"Форматы:\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n"
        f"• <code>1d</code> — 1 день\n"
        f"• <code>1m</code> — 1 месяц\n\n"
        f"Отправьте значение или нажмите Отмена."
    )

    # Кнопка отмены для возврата к настройкам категории
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:{category}a:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(DurationInputStates.waiting_for_duration)
async def process_duration_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает введённое время для мута/бана.

    Args:
        message: Сообщение с временем
        session: Сессия БД
        state: FSM состояние
    """
    # Проверка на отмену
    if message.text and message.text.lower() in ('/cancel', 'отмена'):
        await state.clear()
        await message.answer("Отменено.")
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    action_type = data.get('action_type')
    instruction_message_id = data.get('instruction_message_id')

    # ─────────────────────────────────────────────────────────
    # Удаляем сообщение пользователя чтобы не засорять диалог
    # ─────────────────────────────────────────────────────────
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим введённое время
    try:
        duration_minutes = parse_duration(message.text)
    except ValueError as e:
        await message.answer(
            f"❌ {str(e)}\n\n"
            f"Попробуйте ещё раз или /cancel для отмены."
        )
        return

    # Маппинг на поля БД
    duration_field_map = {
        'sw': 'simple_words_mute_duration',
        'hw': 'harmful_words_mute_duration',
        'ow': 'obfuscated_words_mute_duration'
    }
    action_field_map = {
        'sw': 'simple_words_action',
        'hw': 'harmful_words_action',
        'ow': 'obfuscated_words_action'
    }

    # Обновляем настройки: устанавливаем и действие, и длительность
    await _filter_manager.update_settings(
        chat_id, session,
        **{
            action_field_map[category]: action_type,
            duration_field_map[category]: duration_minutes
        }
    )

    # Очищаем FSM
    await state.clear()

    # Формируем текст подтверждения
    if duration_minutes < 60:
        duration_text = f"{duration_minutes} мин"
    elif duration_minutes < 1440:
        duration_text = f"{duration_minutes // 60} ч"
    else:
        duration_text = f"{duration_minutes // 1440} д"

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # ─────────────────────────────────────────────────────────
    # Редактируем исходное сообщение с подтверждением
    # и кнопкой возврата к меню действий
    # ─────────────────────────────────────────────────────────
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category}a:{chat_id}"
        )]
    ])

    confirm_text = (
        f"✅ Установлено: {action_type} {duration_text} для «{category_names[category]}»"
    )

    try:
        # Редактируем исходное сообщение-инструкцию
        await message.bot.edit_message_text(
            text=confirm_text,
            chat_id=message.chat.id,
            message_id=instruction_message_id,
            reply_markup=keyboard
        )
    except TelegramAPIError:
        # Fallback — отправляем новое сообщение
        await message.answer(confirm_text, reply_markup=keyboard)


# ============================================================
# МЕНЮ ЧУВСТВИТЕЛЬНОСТИ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:sens:-?\d+$"))
async def sensitivity_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора чувствительности.

    Callback: cf:sens:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"🎚️ <b>Чувствительность антискама</b>\n\n"
        f"Чем выше чувствительность, тем больше сообщений "
        f"будет считаться скамом.\n\n"
        f"🔴 Высокая — ловит больше, но возможны ошибки\n"
        f"🟡 Средняя — рекомендуется\n"
        f"🟢 Низкая — только явный скам"
    )

    keyboard = create_sensitivity_menu(chat_id, settings.scam_sensitivity)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sens:\d+:-?\d+$"))
async def set_sensitivity(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает чувствительность.

    Callback: cf:sens:{value}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    value = int(parts[2])
    chat_id = int(parts[3])

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, scam_sensitivity=value)

    # Показываем обновлённое меню
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"🎚️ <b>Чувствительность антискама</b>\n\n"
        f"Чем выше чувствительность, тем больше сообщений "
        f"будет считаться скамом.\n\n"
        f"🔴 Высокая — ловит больше, но возможны ошибки\n"
        f"🟡 Средняя — рекомендуется\n"
        f"🟢 Низкая — только явный скам"
    )

    keyboard = create_sensitivity_menu(chat_id, settings.scam_sensitivity)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer(f"Чувствительность установлена: {value}")


# ============================================================
# МЕНЮ ДЕЙСТВИЯ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:act:-?\d+$"))
async def action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия.

    Callback: cf:act:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие при нарушении</b>\n\n"
        f"Выберите что делать при обнаружении запрещённого контента."
    )

    keyboard = create_action_menu(chat_id, settings.default_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:act:\w+:-?\d+$"))
async def set_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие по умолчанию.

    Callback: cf:act:{action}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    action = parts[2]  # delete, warn, mute, ban
    chat_id = int(parts[3])

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, default_action=action)

    # Показываем обновлённое меню
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие при нарушении</b>\n\n"
        f"Выберите что делать при обнаружении запрещённого контента."
    )

    keyboard = create_action_menu(chat_id, settings.default_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    action_names = {
        'delete': 'Удаление',
        'warn': 'Предупреждение',
        'mute': 'Мут',
        'kick': 'Кик',
        'ban': 'Бан'
    }
    await callback.answer(f"Действие: {action_names.get(action, action)}")


# ============================================================
# МЕНЮ ДЕЙСТВИЯ ДЛЯ ФИЛЬТРА СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wact:-?\d+$"))
async def word_filter_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия для фильтра слов.

    Callback: cf:wact:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие для запрещённых слов</b>\n\n"
        f"Выберите действие при обнаружении запрещённого слова.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    keyboard = create_word_filter_action_menu(chat_id, settings.word_filter_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:wact:\w+:-?\d+$"))
async def set_word_filter_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие для фильтра слов.

    Callback: cf:wact:{action}:{chat_id}
    """
    parts = callback.data.split(":")
    action = parts[2]  # delete, warn, mute, ban, default
    chat_id = int(parts[3])

    # Если action = default, устанавливаем NULL
    new_action = None if action == 'default' else action

    await _filter_manager.update_settings(chat_id, session, word_filter_action=new_action)

    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие для запрещённых слов</b>\n\n"
        f"Выберите действие при обнаружении запрещённого слова.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    keyboard = create_word_filter_action_menu(chat_id, settings.word_filter_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    action_names = {
        'default': 'Общее',
        'delete': 'Удаление',
        'warn': 'Предупреждение',
        'mute': 'Мут',
        'ban': 'Бан'
    }
    await callback.answer(f"Действие для слов: {action_names.get(action, action)}")


# ============================================================
# МЕНЮ ДЕЙСТВИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:fact:-?\d+$"))
async def flood_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия для антифлуда.

    Callback: cf:fact:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие для антифлуда</b>\n\n"
        f"Выберите действие при обнаружении флуда.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    keyboard = create_flood_action_menu(chat_id, settings.flood_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:fact:\w+:-?\d+$"))
async def set_flood_action(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает действие для антифлуда.

    Callback: cf:fact:{action}:{chat_id}
    """
    parts = callback.data.split(":")
    action = parts[2]  # delete, warn, mute, ban, default
    chat_id = int(parts[3])

    # Если action = default, устанавливаем NULL
    new_action = None if action == 'default' else action

    await _filter_manager.update_settings(chat_id, session, flood_action=new_action)

    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие для антифлуда</b>\n\n"
        f"Выберите действие при обнаружении флуда.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    keyboard = create_flood_action_menu(chat_id, settings.flood_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    action_names = {
        'default': 'Общее',
        'delete': 'Удаление',
        'warn': 'Предупреждение',
        'mute': 'Мут',
        'ban': 'Бан'
    }
    await callback.answer(f"Действие для флуда: {action_names.get(action, action)}")


# ============================================================
# ПЕРЕКЛЮЧАТЕЛЬ НОРМАЛИЗАТОРА ДЛЯ СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wnorm:-?\d+$"))
async def toggle_word_normalizer(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает нормализатор для фильтра слов.

    Callback: cf:wnorm:{chat_id}

    Нормализатор преобразует l33tspeak в обычный текст:
    - "3" -> "е"
    - "0" -> "о"
    - и т.д.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем значение
    new_value = not settings.word_filter_normalize

    await _filter_manager.update_settings(chat_id, session, word_filter_normalize=new_value)

    # Возвращаемся в меню настроек
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚙️ <b>Настройки фильтра контента</b>\n\n"
        f"Здесь вы можете:\n"
        f"• Включать/выключать подмодули\n"
        f"• Настраивать чувствительность\n"
        f"• Выбирать действия\n"
        f"• 📝 = нормализатор (обход l33tspeak)\n"
        f"• ⚡ = действие для модуля"
    )

    keyboard = create_content_filter_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    status_text = "включён" if new_value else "выключен"
    await callback.answer(f"Нормализатор {status_text}")


# ============================================================
# МЕНЮ УПРАВЛЕНИЯ СЛОВАМИ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:w:-?\d+$"))
async def words_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню управления словами.

    Callback: cf:w:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние если оно было активно (при отмене)
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем количество слов
    words_count = await _filter_manager.word_filter.get_words_count(chat_id, session)

    text = (
        f"🔤 <b>Запрещённые слова</b>\n\n"
        f"Всего слов: {words_count}\n\n"
        f"Добавьте слова которые будут удаляться из сообщений."
    )

    keyboard = create_words_menu(chat_id, words_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ СЛОВА (FSM)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wa:-?\d+$"))
async def start_add_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления слова (FSM).

    Callback: cf:wa:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext для сохранения состояния
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id в состояние
    await state.update_data(chat_id=chat_id)

    # Переводим в состояние ожидания слова
    await state.set_state(AddWordStates.waiting_for_word)

    text = (
        f"📝 <b>Добавление слова</b>\n\n"
        f"Отправьте слово или фразу которую нужно заблокировать.\n\n"
        f"Можно отправить несколько слов, каждое с новой строки."
    )

    # Кнопка отмены для возврата к меню слов
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:w:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(AddWordStates.waiting_for_word)
async def process_add_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод слова от пользователя.

    Args:
        message: Сообщение с текстом слова
        state: FSMContext
        session: Сессия БД
    """
    # Получаем chat_id из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id. Попробуйте снова.")
        await state.clear()
        return

    # Получаем текст и разбиваем на строки (несколько слов)
    text = message.text.strip()
    words = [w.strip() for w in text.split('\n') if w.strip()]

    if not words:
        await message.answer("❌ Не указано ни одного слова. Попробуйте снова.")
        return

    # Добавляем каждое слово
    added = 0
    skipped = 0

    for word in words:
        try:
            await _filter_manager.word_filter.add_word(
                chat_id=chat_id,
                word=word,
                created_by=message.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            # Скорее всего дубликат
            logger.warning(f"Не удалось добавить слово '{word}': {e}")
            skipped += 1

    # Очищаем состояние
    await state.clear()

    # Формируем ответ
    if added > 0 and skipped == 0:
        response = f"✅ Добавлено слов: {added}"
    elif added > 0 and skipped > 0:
        response = f"✅ Добавлено: {added}, пропущено (дубликаты): {skipped}"
    else:
        response = f"⚠️ Все слова уже были добавлены ранее"

    # Показываем меню слов
    words_count = await _filter_manager.word_filter.get_words_count(chat_id, session)
    keyboard = create_words_menu(chat_id, words_count)

    await message.answer(
        f"{response}\n\n"
        f"🔤 <b>Запрещённые слова</b>\n"
        f"Всего слов: {words_count}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# СПИСОК СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wl:-?\d+:\d+$"))
async def show_words_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список слов с пагинацией.

    Callback: cf:wl:{chat_id}:{page}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])

    # Получаем все слова
    words = await _filter_manager.word_filter.get_words_list(chat_id, session)

    # Вычисляем пагинацию
    total_pages = max(1, (len(words) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
    page = min(page, total_pages - 1)  # Не выходим за границы

    # Получаем слова для текущей страницы
    start_idx = page * WORDS_PER_PAGE
    end_idx = start_idx + WORDS_PER_PAGE
    page_words = words[start_idx:end_idx]

    # Формируем текст
    if not page_words:
        text = "🔤 <b>Запрещённые слова</b>\n\nСписок пуст."
    else:
        text = f"🔤 <b>Запрещённые слова</b> (стр. {page + 1}/{total_pages})\n\n"
        for i, fw in enumerate(page_words, start=start_idx + 1):
            # Показываем слово и категорию если есть
            category_text = f" [{fw.category}]" if fw.category else ""
            text += f"{i}. <code>{fw.word}</code>{category_text}\n"

    # Клавиатура
    keyboard = create_words_list_menu(chat_id, page, total_pages, len(page_words) > 0)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ВСЕХ СЛОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:wc:-?\d+$"))
async def confirm_clear_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления всех слов.

    Callback: cf:wc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"⚠️ <b>Удаление всех слов</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ запрещённые слова?\n\n"
        f"Это действие нельзя отменить."
    )

    keyboard = create_clear_words_confirm_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:wcc:-?\d+$"))
async def clear_all_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все слова из группы.

    Callback: cf:wcc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Удаляем все слова
    query = delete(FilterWord).where(FilterWord.chat_id == chat_id)
    await session.execute(query)
    await session.commit()

    logger.info(f"[ContentFilter] Удалены все слова из чата {chat_id}")

    # Показываем меню слов
    keyboard = create_words_menu(chat_id, 0)

    await callback.message.edit_text(
        "✅ Все слова удалены.\n\n"
        "🔤 <b>Запрещённые слова</b>\n"
        "Всего слов: 0",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Все слова удалены")


# ============================================================
# СТАТИСТИКА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:stats:-?\d+$"))
async def show_stats(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает статистику нарушений.

    Callback: cf:stats:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем статистику за 7 дней
    stats = await _filter_manager.get_violation_stats(chat_id, session, days=7)

    # Формируем текст
    text = (
        f"📊 <b>Статистика за 7 дней</b>\n\n"
        f"Всего срабатываний: {stats['total']}\n\n"
    )

    if stats['by_detector']:
        text += "<b>По типу:</b>\n"
        detector_names = {
            'word_filter': '🔤 Слова',
            'scam_detector': '💰 Скам',
            'flood_detector': '📢 Флуд',
            'referral_detector': '👤 Referral'
        }
        for detector, count in stats['by_detector'].items():
            name = detector_names.get(detector, detector)
            text += f"  {name}: {count}\n"
        text += "\n"

    if stats['by_action']:
        text += "<b>По действию:</b>\n"
        action_names = {
            'delete': '🗑️ Удаление',
            'warn': '⚠️ Предупреждение',
            'mute': '🔇 Мут',
            'kick': '👢 Кик',
            'ban': '🚫 Бан'
        }
        for action, count in stats['by_action'].items():
            name = action_names.get(action, action)
            text += f"  {name}: {count}\n"

    # Кнопка назад
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:m:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# НАСТРОЙКИ ФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:fls:-?\d+$"))
async def flood_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню настроек антифлуда.

    Callback: cf:fls:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние при возврате из ручного ввода
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем статус расширенного антифлуда
    any_status = "✅ Вкл" if settings.flood_detect_any_messages else "❌ Выкл"
    media_status = "✅ Вкл" if settings.flood_detect_media else "❌ Выкл"

    text = (
        f"📢 <b>Настройки антифлуда</b>\n\n"
        f"Флуд — это когда пользователь отправляет одинаковые "
        f"сообщения несколько раз подряд.\n\n"
        f"<b>Макс. повторов:</b> {settings.flood_max_repeats}\n"
        f"<b>Временное окно:</b> {settings.flood_time_window} сек.\n\n"
        f"<b>Расширенный антифлуд:</b>\n"
        f"• Любые сообщения подряд: {any_status}\n"
        f"• Медиа-флуд: {media_status}\n\n"
        f"Если пользователь отправит больше {settings.flood_max_repeats} "
        f"одинаковых сообщений за {settings.flood_time_window} секунд — "
        f"сработает фильтр."
    )

    keyboard = create_flood_settings_menu(
        chat_id,
        settings.flood_max_repeats,
        settings.flood_time_window,
        settings.flood_action,
        settings.flood_mute_duration,
        settings.flood_detect_any_messages,
        settings.flood_any_max_messages,
        settings.flood_any_time_window,
        settings.flood_detect_media
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:flr:\d+:-?\d+$"))
async def set_flood_max_repeats(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает максимальное количество повторов для флуда.

    Callback: cf:flr:{value}:{chat_id}

    После установки возвращает в меню "Дополнительно" (cf:fladv)

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    value = int(parts[2])
    chat_id = int(parts[3])

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_max_repeats=value)

    # Показываем уведомление
    await callback.answer(f"✅ Макс. повторов: {value}")

    # Создаём фейковый callback для вызова flood_advanced_menu
    # Меняем data на cf:fladv:{chat_id}
    callback.data = f"cf:fladv:{chat_id}"

    # Вызываем меню "Дополнительно"
    await flood_advanced_menu(callback, session)


@settings_handler_router.callback_query(F.data.regexp(r"^cf:flw:\d+:-?\d+$"))
async def set_flood_time_window(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает временное окно для подсчёта повторов.

    Callback: cf:flw:{value}:{chat_id}

    После установки возвращает в меню "Дополнительно" (cf:fladv)

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    value = int(parts[2])
    chat_id = int(parts[3])

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_time_window=value)

    # Показываем уведомление
    await callback.answer(f"✅ Временное окно: {value} сек.")

    # Создаём фейковый callback для вызова flood_advanced_menu
    callback.data = f"cf:fladv:{chat_id}"

    # Вызываем меню "Дополнительно"
    await flood_advanced_menu(callback, session)


# ============================================================
# РУЧНОЙ ВВОД ПАРАМЕТРОВ АНТИФЛУДА (FSM)
# ============================================================

class FloodCustomInputStates(StatesGroup):
    """FSM состояния для ручного ввода параметров антифлуда."""
    waiting_for_max_repeats = State()
    waiting_for_time_window = State()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:flrc:-?\d+$"))
async def start_custom_max_repeats(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает ручной ввод максимального количества повторов.

    Callback: cf:flrc:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(chat_id=chat_id)
    await state.set_state(FloodCustomInputStates.waiting_for_max_repeats)

    text = (
        "📢 <b>Ручной ввод: Макс. повторов</b>\n\n"
        "Введите положительное число.\n"
        "После стольких одинаковых сообщений сработает антифлуд.\n\n"
        "<i>Рекомендуется: 2-5</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:fladv:{chat_id}"  # Возврат в меню "Дополнительно"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(FloodCustomInputStates.waiting_for_max_repeats)
async def process_custom_max_repeats(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ручной ввод max_repeats. Возвращает в меню 'Дополнительно'."""
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Валидация ввода (без верхнего лимита — админ решает сам)
    try:
        value = int(message.text.strip())
        if value < 1:
            # Удаляем сообщение пользователя чтобы не засорять чат
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            await message.answer("❌ Введите положительное число.")
            return
    except ValueError:
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        await message.answer("❌ Введите целое число.")
        return

    # Сохраняем значение
    await _filter_manager.update_settings(chat_id, session, flood_max_repeats=value)
    await state.clear()

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Возвращаем в меню "Дополнительно" с кнопкой перехода
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    await message.answer(
        f"✅ Установлено: {value} повторов",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@settings_handler_router.callback_query(F.data.regexp(r"^cf:flwc:-?\d+$"))
async def start_custom_time_window(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает ручной ввод временного окна.

    Callback: cf:flwc:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(chat_id=chat_id)
    await state.set_state(FloodCustomInputStates.waiting_for_time_window)

    text = (
        "⏱️ <b>Ручной ввод: Временное окно</b>\n\n"
        "Введите положительное число в секундах.\n"
        "За это время считаются повторы.\n\n"
        "<i>Рекомендуется: 30-120 секунд</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:fladv:{chat_id}"  # Возврат в меню "Дополнительно"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(FloodCustomInputStates.waiting_for_time_window)
async def process_custom_time_window(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ручной ввод time_window. Возвращает в меню 'Дополнительно'."""
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Валидация ввода (без верхнего лимита — админ решает сам)
    try:
        value = int(message.text.strip())
        if value < 1:
            # Удаляем сообщение пользователя чтобы не засорять чат
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            await message.answer("❌ Введите положительное число.")
            return
    except ValueError:
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        await message.answer("❌ Введите целое число.")
        return

    # Сохраняем значение
    await _filter_manager.update_settings(chat_id, session, flood_time_window=value)
    await state.clear()

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Возвращаем в меню "Дополнительно" с кнопкой перехода
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    await message.answer(
        f"✅ Установлено: {value} сек.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# ОБРАБОТКА NOOP (пустые callback)
# ============================================================

@settings_handler_router.callback_query(F.data == "cf:noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает пустые callback (например, разделители).

    Args:
        callback: CallbackQuery
    """
    await callback.answer()


# ============================================================
# МЕНЮ ПАТТЕРНОВ СКАМА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:sp:-?\d+$"))
async def scam_patterns_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню управления паттернами скама.

    Callback: cf:sp:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние если оно было активно (при отмене)
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем количество паттернов
    pattern_service = get_pattern_service()
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)

    text = (
        f"🎯 <b>Паттерны антискама</b>\n\n"
        f"Всего паттернов: {patterns_count}\n\n"
        f"Добавьте фразы которые будут увеличивать скор скама.\n"
        f"Если сумма весов сработавших паттернов превысит порог "
        f"чувствительности — сообщение будет удалено."
    )

    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ ПАТТЕРНА (FSM)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spa:-?\d+$"))
async def start_add_pattern(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления паттерна.

    Callback: cf:spa:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Переводим в состояние ожидания паттерна
    await state.set_state(AddPatternStates.waiting_for_pattern)

    text = (
        f"📝 <b>Добавление паттерна</b>\n\n"
        f"Отправьте фразу или слово которое должно увеличивать скор скама.\n\n"
        f"<b>Тип:</b> Подстрока\n"
        f"<b>Вес:</b> 25 баллов\n\n"
        f"<i>Можно отправить несколько фраз, каждую с новой строки.</i>"
    )

    keyboard = create_cancel_pattern_input_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    # Сохраняем chat_id и значения по умолчанию + message_id для редактирования
    await state.update_data(
        chat_id=chat_id,
        pattern_type='phrase',
        weight=25,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )

    await callback.answer()


@settings_handler_router.message(AddPatternStates.waiting_for_pattern)
async def process_add_pattern(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод паттерна от пользователя.

    Сообщение пользователя удаляется для чистоты чата.
    FSM НЕ очищается - можно продолжить добавлять паттерны.

    Args:
        message: Сообщение с паттерном
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')
    pattern_type = data.get('pattern_type', 'phrase')
    weight = data.get('weight', 25)
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id. Попробуйте снова.")
        await state.clear()
        return

    # Разбиваем на строки
    text = message.text.strip()
    patterns = [p.strip() for p in text.split('\n') if p.strip()]

    if not patterns:
        # Удаляем сообщение пользователя
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Редактируем сохранённое сообщение вместо создания нового
        error_text = "❌ Не указано ни одного паттерна. Попробуйте снова."
        keyboard = create_cancel_pattern_input_menu(chat_id)
        try:
            await message.bot.edit_message_text(
                text=error_text,
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                reply_markup=keyboard
            )
        except TelegramAPIError:
            await message.answer(error_text, reply_markup=keyboard)
        return

    # Добавляем каждый паттерн
    pattern_service = get_pattern_service()
    added = 0
    skipped = 0

    for pattern_text in patterns:
        try:
            await pattern_service.add_pattern(
                chat_id=chat_id,
                pattern=pattern_text,
                pattern_type=pattern_type,
                weight=weight,
                created_by=message.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            logger.warning(f"Не удалось добавить паттерн '{pattern_text}': {e}")
            skipped += 1

    # НЕ очищаем FSM - позволяем продолжить добавление
    # FSM очистится при нажатии "Готово" или "Отмена"

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем ответ
    if added > 0 and skipped == 0:
        response = f"✅ Добавлено паттернов: {added}"
    elif added > 0 and skipped > 0:
        response = f"✅ Добавлено: {added}, пропущено (дубликаты): {skipped}"
    else:
        response = f"⚠️ Все паттерны уже были добавлены ранее"

    # Получаем обновлённое количество паттернов
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)

    # Формируем текст с возможностью продолжить добавление
    text = (
        f"{response}\n\n"
        f"📝 <b>Добавление паттерна</b>\n"
        f"Всего паттернов: {patterns_count}\n\n"
        f"Отправьте ещё паттерны или нажмите «Готово».\n"
        f"<i>Можно отправить несколько фраз, каждую с новой строки.</i>"
    )

    # Кнопки: Готово и Отмена
    # cf:sp:{chat_id} - возвращает в меню паттернов и очищает FSM
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"cf:sp:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:sp:{chat_id}"
        )]
    ])

    # Редактируем сохранённое сообщение вместо создания нового
    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ИМПОРТ ИЗ ТЕКСТА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spi:-?\d+$"))
async def start_import_patterns(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс импорта паттернов из текста.

    Callback: cf:spi:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Переводим в состояние ожидания текста
    await state.set_state(AddPatternStates.waiting_for_import_text)

    text = (
        f"📥 <b>Импорт паттернов из текста</b>\n\n"
        f"Вставьте сюда скам-сообщение целиком.\n"
        f"Я проанализирую его и извлеку ключевые фразы.\n\n"
        f"<i>Эти фразы станут паттернами для обнаружения похожих сообщений.</i>"
    )

    keyboard = create_cancel_pattern_input_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    # Сохраняем chat_id и message_id для последующего редактирования
    await state.update_data(
        chat_id=chat_id,
        import_weight=25,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )

    await callback.answer()


@settings_handler_router.message(AddPatternStates.waiting_for_import_text)
async def process_import_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Анализирует текст и извлекает паттерны.

    Сообщение пользователя удаляется для чистоты чата.

    Args:
        message: Сообщение со скам-текстом
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')
    weight = data.get('import_weight', 25)
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id. Попробуйте снова.")
        await state.clear()
        return

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Анализируем текст
    pattern_service = get_pattern_service()
    phrases = pattern_service.extract_patterns_from_text(message.text)

    if not phrases:
        # Редактируем сохранённое сообщение вместо создания нового
        error_text = (
            "⚠️ Не удалось извлечь паттерны из текста.\n"
            "Попробуйте вставить другой текст."
        )
        keyboard = create_cancel_pattern_input_menu(chat_id)
        try:
            await message.bot.edit_message_text(
                text=error_text,
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                reply_markup=keyboard
            )
        except TelegramAPIError:
            await message.answer(error_text, reply_markup=keyboard)
        return

    # Сохраняем извлечённые фразы в состояние
    await state.update_data(extracted_phrases=phrases)

    # Показываем превью
    text = f"🔍 <b>Найденные паттерны</b>\n\n"
    for i, (phrase, phrase_weight) in enumerate(phrases[:10], 1):
        text += f"{i}. <code>{phrase}</code> (+{phrase_weight})\n"

    if len(phrases) > 10:
        text += f"\n<i>...и ещё {len(phrases) - 10} паттернов</i>\n"

    text += f"\n<b>Всего найдено:</b> {len(phrases)} паттернов"

    keyboard = create_import_preview_menu(chat_id, len(phrases))

    # Редактируем сохранённое сообщение вместо создания нового
    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@settings_handler_router.callback_query(F.data.regexp(r"^cf:spic:-?\d+$"))
async def confirm_import_patterns(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Подтверждает импорт паттернов.

    Callback: cf:spic:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')
    phrases = data.get('extracted_phrases', [])
    weight = data.get('import_weight', 25)

    if not phrases:
        await callback.answer("❌ Нет паттернов для импорта")
        await state.clear()
        return

    # Добавляем паттерны
    pattern_service = get_pattern_service()
    added = 0
    skipped = 0

    for phrase, phrase_weight in phrases:
        try:
            await pattern_service.add_pattern(
                chat_id=chat_id,
                pattern=phrase,
                pattern_type='phrase',
                weight=phrase_weight if weight == 25 else weight,
                created_by=callback.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            logger.warning(f"Не удалось добавить паттерн '{phrase}': {e}")
            skipped += 1

    # Очищаем состояние
    await state.clear()

    # Показываем результат
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)

    text = (
        f"✅ <b>Импорт завершён</b>\n\n"
        f"Добавлено: {added}\n"
        f"Пропущено (дубликаты): {skipped}\n\n"
        f"🎯 <b>Паттерны антискама</b>\n"
        f"Всего паттернов: {patterns_count}"
    )

    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer(f"Импортировано: {added}")


# ============================================================
# ВЫБОР ВЕСА ДЛЯ ИМПОРТА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spiw:-?\d+$"))
async def show_import_weight_menu(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора веса для импортируемых паттернов.

    Callback: cf:spiw:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext для получения текущего веса
    """
    # Парсим chat_id из callback
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем текущий вес из состояния
    data = await state.get_data()
    current_weight = data.get('import_weight', 25)

    # Формируем текст с описанием весов
    text = (
        f"⚖️ <b>Выбор веса для импорта</b>\n\n"
        f"Вес определяет насколько сильно паттерн влияет на скор скама.\n\n"
        f"🟢 Слабый (15) — небольшой сигнал\n"
        f"🟡 Средний (25) — стандартный\n"
        f"🔴 Сильный (40) — явный признак скама\n\n"
        f"<b>Текущий вес:</b> {current_weight}"
    )

    # Создаём клавиатуру с галочкой на текущем весе
    keyboard = create_import_weight_menu(chat_id, current_weight)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:spw:\d+:-?\d+$"))
async def set_import_weight(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Устанавливает вес для импортируемых паттернов и возвращает к превью.

    Callback: cf:spw:{weight}:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext для сохранения веса
    """
    # Парсим данные из callback
    parts = callback.data.split(":")
    weight = int(parts[2])
    chat_id = int(parts[3])

    # Сохраняем вес в состояние
    await state.update_data(import_weight=weight)

    # Получаем извлечённые фразы из состояния
    data = await state.get_data()
    phrases = data.get('extracted_phrases', [])

    # Формируем превью
    text = f"🔍 <b>Найденные паттерны</b>\n\n"

    # Показываем паттерны с выбранным весом
    for i, (phrase, phrase_weight) in enumerate(phrases[:10], 1):
        text += f"{i}. <code>{phrase}</code> (+{weight})\n"

    if len(phrases) > 10:
        text += f"\n<i>...и ещё {len(phrases) - 10} паттернов</i>\n"

    text += f"\n<b>Всего найдено:</b> {len(phrases)} паттернов"
    text += f"\n<b>Вес:</b> {weight} баллов"

    # Показываем превью
    keyboard = create_import_preview_menu(chat_id, len(phrases))

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer(f"Вес установлен: {weight}")


# ============================================================
# СПИСОК ПАТТЕРНОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spl:-?\d+:\d+$"))
async def show_patterns_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список паттернов с пагинацией.

    Callback: cf:spl:{chat_id}:{page}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])

    # Получаем паттерны
    pattern_service = get_pattern_service()
    patterns = await pattern_service.get_patterns(chat_id, session)

    # Вычисляем пагинацию
    total_pages = max(1, (len(patterns) + PATTERNS_PER_PAGE - 1) // PATTERNS_PER_PAGE)
    page = min(page, total_pages - 1)

    # Получаем паттерны для текущей страницы
    start_idx = page * PATTERNS_PER_PAGE
    end_idx = start_idx + PATTERNS_PER_PAGE
    page_patterns = patterns[start_idx:end_idx]

    # Формируем текст
    if not page_patterns:
        text = "🎯 <b>Паттерны антискама</b>\n\nСписок пуст."
        pattern_ids = []
    else:
        text = f"🎯 <b>Паттерны</b> (стр. {page + 1}/{total_pages})\n\n"
        pattern_ids = []
        for p in page_patterns:
            # Показываем паттерн и его характеристики
            type_emoji = {'phrase': '📝', 'word': '🔤', 'regex': '⚙️'}.get(p.pattern_type, '📝')
            status = "✅" if p.is_active else "❌"

            # Обрезаем длинные паттерны
            pattern_text = p.pattern[:40]
            if len(p.pattern) > 40:
                pattern_text += '...'

            text += (
                f"{type_emoji} <b>#{p.id}</b> {status}\n"
                f"<code>{pattern_text}</code>\n"
                f"Вес: {p.weight} | Срабатываний: {p.triggers_count}\n\n"
            )
            pattern_ids.append(p.id)

    # Клавиатура
    keyboard = create_patterns_list_menu(chat_id, page, total_pages, pattern_ids)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ПАТТЕРНА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spd:\d+:-?\d+$"))
async def confirm_delete_pattern(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления паттерна.

    Callback: cf:spd:{pattern_id}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    chat_id = int(parts[3])

    # Получаем паттерн
    query = select(ScamPattern).where(ScamPattern.id == pattern_id)
    result = await session.execute(query)
    pattern = result.scalar_one_or_none()

    if not pattern:
        await callback.answer("❌ Паттерн не найден")
        return

    text = (
        f"⚠️ <b>Удаление паттерна #{pattern_id}</b>\n\n"
        f"<code>{pattern.pattern}</code>\n\n"
        f"Вы уверены что хотите удалить этот паттерн?"
    )

    keyboard = create_pattern_delete_confirm_menu(chat_id, pattern_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:spdc:\d+:-?\d+$"))
async def delete_pattern_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет паттерн после подтверждения.

    Callback: cf:spdc:{pattern_id}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    chat_id = int(parts[3])

    # Удаляем паттерн
    pattern_service = get_pattern_service()
    deleted = await pattern_service.delete_pattern(pattern_id, session)

    if not deleted:
        await callback.answer("❌ Паттерн не найден")
        return

    # Показываем обновлённый список
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)

    text = (
        f"✅ Паттерн #{pattern_id} удалён.\n\n"
        f"🎯 <b>Паттерны антискама</b>\n"
        f"Всего паттернов: {patterns_count}"
    )

    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Паттерн удалён")


# ============================================================
# УДАЛЕНИЕ ВСЕХ ПАТТЕРНОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spc:-?\d+$"))
async def confirm_clear_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления всех паттернов.

    Callback: cf:spc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"⚠️ <b>Удаление всех паттернов</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ паттерны скама?\n\n"
        f"Это действие нельзя отменить."
    )

    keyboard = create_clear_patterns_confirm_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:spcc:-?\d+$"))
async def clear_all_patterns_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все паттерны после подтверждения.

    Callback: cf:spcc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Удаляем все паттерны
    pattern_service = get_pattern_service()
    deleted = await pattern_service.delete_all_patterns(chat_id, session)

    logger.info(f"[ContentFilter] Удалены все паттерны из чата {chat_id}: {deleted}")

    # Показываем меню
    keyboard = create_scam_patterns_menu(chat_id, 0)

    await callback.message.edit_text(
        f"✅ Удалено паттернов: {deleted}\n\n"
        f"🎯 <b>Паттерны антискама</b>\n"
        f"Всего паттернов: 0",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Все паттерны удалены")


# ============================================================
# ЭКСПОРТ ПАТТЕРНОВ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:spe:-?\d+$"))
async def export_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Экспортирует паттерны в текстовый формат.

    Callback: cf:spe:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Экспортируем паттерны
    pattern_service = get_pattern_service()
    export_text = await pattern_service.export_patterns(chat_id, session)

    if not export_text:
        await callback.answer("❌ Нет паттернов для экспорта")
        return

    # Отправляем как отдельное сообщение
    await callback.message.answer(
        f"📤 <b>Экспорт паттернов</b>\n\n"
        f"<pre>{export_text}</pre>\n\n"
        f"<i>Скопируйте и сохраните этот текст для импорта в другую группу.</i>",
        parse_mode="HTML"
    )

    await callback.answer("Паттерны экспортированы")


# ============================================================
# СПИСКИ СЛОВ ПО КАТЕГОРИЯМ
# ============================================================

# Словарь категорий для читаемых названий
CATEGORY_NAMES = {
    'sw': ('simple', '📝 Простые слова', 'простое слово'),
    'hw': ('harmful', '💊 Вредные слова', 'вредное слово'),
    'ow': ('obfuscated', '🔀 Обфускация', 'обфусцированное слово')
}

# Количество слов на странице в категориях
CATEGORY_WORDS_PER_PAGE = 10


@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)l:-?\d+:\d+$"))
async def show_category_words_list(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает список слов категории с пагинацией.

    Callback: cf:{category}l:{chat_id}:{page}
    Примеры: cf:swl:-123:0, cf:hwl:-123:1, cf:owl:-123:0

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние если оно было активно (при отмене)
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])
    page = int(parts[3])

    # Получаем название категории
    category_db, category_title, _ = CATEGORY_NAMES.get(category_code, ('simple', '📝 Слова', 'слово'))

    # Получаем слова категории
    words = await _filter_manager.word_filter.get_words_by_category(chat_id, session, category_db)

    # Вычисляем пагинацию
    total_pages = max(1, (len(words) + CATEGORY_WORDS_PER_PAGE - 1) // CATEGORY_WORDS_PER_PAGE)
    page = min(page, total_pages - 1)

    # Получаем слова для текущей страницы
    start_idx = page * CATEGORY_WORDS_PER_PAGE
    end_idx = start_idx + CATEGORY_WORDS_PER_PAGE
    page_words = words[start_idx:end_idx]

    # Формируем текст сообщения
    if not page_words:
        # Список пуст - показываем сообщение
        text = f"{category_title}\n\nСписок пуст. Добавьте слова через кнопку ниже."
    else:
        # Формируем заголовок
        text = f"{category_title} (стр. {page + 1}/{total_pages})\n\n"
        text += f"Всего слов: {len(words)}\n\n"
        text += "📋 <b>Запрещённые слова:</b>\n"
        # Формируем текстовый список слов (не кнопки!)
        for i, w in enumerate(page_words, start=start_idx + 1):
            # Каждое слово на новой строке с номером
            text += f"{i}. {w.word}\n"

    # Клавиатура (только кнопки управления, без слов)
    keyboard = create_category_words_list_menu(
        chat_id, category_code, page, total_pages
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


async def _refresh_category_words_list(
    callback: CallbackQuery,
    session: AsyncSession,
    category_code: str,
    chat_id: int,
    page: int = 0
) -> None:
    """
    Обновляет меню списка слов категории без модификации callback.data.

    Используется после удаления слова чтобы избежать ошибки frozen Pydantic model.

    Args:
        callback: CallbackQuery для обновления сообщения
        session: Сессия БД
        category_code: Код категории (sw, hw, ow)
        chat_id: ID группы
        page: Номер страницы (по умолчанию 0)
    """
    # Получаем название категории
    category_db, category_title, _ = CATEGORY_NAMES.get(category_code, ('simple', '📝 Слова', 'слово'))

    # Получаем слова категории
    words = await _filter_manager.word_filter.get_words_by_category(chat_id, session, category_db)

    # Вычисляем пагинацию
    total_pages = max(1, (len(words) + CATEGORY_WORDS_PER_PAGE - 1) // CATEGORY_WORDS_PER_PAGE)
    page = min(page, total_pages - 1)

    # Получаем слова для текущей страницы
    start_idx = page * CATEGORY_WORDS_PER_PAGE
    end_idx = start_idx + CATEGORY_WORDS_PER_PAGE
    page_words = words[start_idx:end_idx]

    # Формируем текст сообщения
    if not page_words:
        # Список пуст - показываем сообщение
        text = f"{category_title}\n\nСписок пуст. Добавьте слова через кнопку ниже."
    else:
        # Формируем заголовок
        text = f"{category_title} (стр. {page + 1}/{total_pages})\n\n"
        text += f"Всего слов: {len(words)}\n\n"
        text += "📋 <b>Запрещённые слова:</b>\n"
        # Формируем текстовый список слов (не кнопки!)
        for i, w in enumerate(page_words, start=start_idx + 1):
            # Каждое слово на новой строке с номером
            text += f"{i}. {w.word}\n"

    # Клавиатура (только кнопки управления, без слов)
    keyboard = create_category_words_list_menu(
        chat_id, category_code, page, total_pages
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)d:\d+:-?\d+$"))
async def delete_category_word(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Удаляет слово из категории.

    Callback: cf:{category}d:{word_id}:{chat_id}
    Примеры: cf:swd:123:-456, cf:hwd:124:-456

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    word_id = int(parts[2])
    chat_id = int(parts[3])

    # Удаляем слово
    query = delete(FilterWord).where(FilterWord.id == word_id)
    result = await session.execute(query)
    await session.commit()

    if result.rowcount > 0:
        logger.info(f"[ContentFilter] Удалено слово #{word_id} из чата {chat_id}")
        await callback.answer("✅ Слово удалено")
    else:
        await callback.answer("❌ Слово не найдено")

    # Возвращаемся к списку (страница 0)
    # НЕ модифицируем callback.data напрямую (Pydantic frozen model!)
    # Вместо этого обновляем меню напрямую
    await _refresh_category_words_list(callback, session, category_code, chat_id)


# ============================================================
# ДОБАВЛЕНИЕ СЛОВ В КАТЕГОРИЮ (FSM)
# ============================================================

class AddCategoryWordStates(StatesGroup):
    """FSM состояния для добавления слова в категорию."""
    waiting_for_word = State()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)w:-?\d+$"))
async def start_add_category_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора типа совпадения для добавления слова.

    Callback: cf:{category}w:{chat_id}
    Примеры: cf:sww:-123, cf:hww:-123, cf:oww:-123

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Получаем название категории
    category_db, category_title, category_name = CATEGORY_NAMES.get(
        category_code, ('simple', '📝 Простые слова', 'простое слово')
    )

    text = (
        f"➕ <b>Добавление слова</b>\n\n"
        f"Категория: {category_title}\n\n"
        f"Выберите тип совпадения:\n\n"
        f"📝 <b>Точное слово</b> — слово должно быть отдельным\n"
        f"<i>Пример: «спам» найдёт «спам», но не «спамер»</i>\n\n"
        f"📄 <b>Содержит</b> — слово может быть частью текста\n"
        f"<i>Пример: «спам» найдёт и «спам», и «спамер»</i>"
    )

    # Кнопки выбора типа
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📝 Точное слово",
                callback_data=f"cf:{category_code}wt:{chat_id}"
            ),
            InlineKeyboardButton(
                text="📄 Содержит",
                callback_data=f"cf:{category_code}wp:{chat_id}"
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}l:{chat_id}:0"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)w(t|p):-?\d+$"))
async def select_word_match_type(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Обрабатывает выбор типа совпадения и запрашивает ввод слова.

    Callback: cf:{category}wt:{chat_id} (word) или cf:{category}wp:{chat_id} (phrase)

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_and_type = parts[1]  # swt, hwt, owt, swp, hwp, owp
    category_code = category_and_type[:2]  # sw, hw, ow
    match_type = 'word' if category_and_type[2] == 't' else 'phrase'
    chat_id = int(parts[2])

    # Получаем название категории
    category_db, category_title, category_name = CATEGORY_NAMES.get(
        category_code, ('simple', '📝 Простые слова', 'простое слово')
    )

    # Сохраняем данные в состояние
    await state.update_data(
        chat_id=chat_id,
        category_code=category_code,
        category_db=category_db,
        match_type=match_type,
        instruction_message_id=callback.message.message_id
    )

    # Переводим в состояние ожидания слова
    await state.set_state(AddCategoryWordStates.waiting_for_word)

    match_type_text = "📝 Точное слово" if match_type == 'word' else "📄 Содержит"
    text = (
        f"➕ <b>Добавление слова</b>\n\n"
        f"Категория: {category_title}\n"
        f"Тип: {match_type_text}\n\n"
        f"Отправьте слово или фразу для добавления в фильтр.\n\n"
        f"<i>Можно отправить несколько слов, каждое с новой строки.</i>"
    )

    # Кнопка отмены
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}w:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(AddCategoryWordStates.waiting_for_word)
async def process_add_category_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает добавление слова в категорию.

    Args:
        message: Сообщение с текстом слова
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category_code = data.get('category_code')
    category_db = data.get('category_db')
    match_type = data.get('match_type', 'word')  # По умолчанию 'word'
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category_code:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны. Попробуйте снова.")
        return

    # Получаем название категории
    _, category_title, _ = CATEGORY_NAMES.get(category_code, ('simple', '📝 Простые слова', 'слово'))

    # Парсим слова (каждое с новой строки)
    words_text = message.text.strip()
    words_list = [w.strip() for w in words_text.split('\n') if w.strip()]

    if not words_list:
        await message.answer("❌ Не указаны слова для добавления.")
        return

    # Добавляем слова
    added = 0
    duplicates = 0

    # Список слов-дубликатов с указанием категории
    duplicate_details = []

    for word in words_list:
        # ─────────────────────────────────────────────────────────
        # Проверяем на дубликат по (chat_id, word)
        # БД constraint uq_filter_chat_word проверяет именно эту пару,
        # поэтому проверка category НЕ нужна (и вызывала IntegrityError)
        # ─────────────────────────────────────────────────────────
        existing_result = await session.execute(
            select(FilterWord).where(
                FilterWord.chat_id == chat_id,
                FilterWord.word == word
            )
        )
        existing_word = existing_result.scalar_one_or_none()
        if existing_word:
            # ─────────────────────────────────────────────────────────
            # Если слово имеет category=NULL (застряло в БД без категории),
            # автоматически удаляем его и позволяем добавить с правильной категорией.
            # Такие слова не отображаются ни в одной категории, но блокируют добавление.
            # ─────────────────────────────────────────────────────────
            if existing_word.category is None:
                # Удаляем "сиротское" слово
                await session.delete(existing_word)
                await session.flush()
                logger.info(f"[ContentFilter] Удалено слово '{word}' с category=NULL из чата {chat_id}")
                # Продолжаем добавление — не считаем это дубликатом
            else:
                # Слово уже существует в конкретной категории — запоминаем где
                cat_names = {
                    'simple': '📝 Простые',
                    'harmful': '💊 Вредные',
                    'obfuscated': '🔀 Обфускация'
                }
                existing_cat = cat_names.get(existing_word.category, existing_word.category)
                duplicate_details.append(f"«{word}» → {existing_cat}")
                duplicates += 1
                continue

        # Добавляем слово с выбранным match_type
        new_word = FilterWord(
            chat_id=chat_id,
            word=word,
            normalized=word.lower(),
            match_type=match_type,
            category=category_db,
            created_by=message.from_user.id
        )
        session.add(new_word)
        added += 1

    await session.commit()

    # НЕ очищаем FSM - позволяем продолжить добавление
    # FSM очистится при нажатии "Готово" или "Назад"

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # ─────────────────────────────────────────────────────────
    # Формируем ответ с детализацией дубликатов
    # Показываем в какой категории уже существует каждое слово
    # ─────────────────────────────────────────────────────────
    result_text = f"✅ Добавлено слов: {added}"
    if duplicates > 0:
        result_text += f"\n⚠️ Дубликатов: {duplicates}"
        # Показываем первые 5 дубликатов с их категориями
        if duplicate_details:
            shown_details = duplicate_details[:5]
            result_text += "\n" + "\n".join(shown_details)
            if len(duplicate_details) > 5:
                result_text += f"\n...и ещё {len(duplicate_details) - 5}"

    match_type_text = "📝 Точное слово" if match_type == 'word' else "📄 Содержит"
    logger.info(f"[ContentFilter] В чат {chat_id} добавлено {added} слов категории {category_db}, match_type={match_type}")

    # Получаем обновлённый список слов для отображения общего количества
    words = await _filter_manager.word_filter.get_words_by_category(chat_id, session, category_db)

    # Формируем текст с возможностью продолжить добавление
    text = (
        f"{result_text}\n\n"
        f"📝 {category_title}\n"
        f"Тип: {match_type_text}\n"
        f"Всего слов: {len(words)}\n\n"
        f"Отправьте ещё слова или нажмите «Готово».\n"
        f"<i>Можно отправить несколько слов, каждое с новой строки.</i>"
    )

    # Кнопки: Готово и Назад
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"cf:{category_code}l:{chat_id}:0"
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}w:{chat_id}"
        )]
    ])

    # Редактируем исходное сообщение вместо отправки нового
    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    # Fallback: отправляем новое сообщение
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# УДАЛЕНИЕ СЛОВ ПО FSM ВВОДУ
# ============================================================

class DeleteCategoryWordStates(StatesGroup):
    """FSM состояния для удаления слов по вводу."""
    waiting_for_word = State()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)dw:-?\d+$"))
async def start_delete_category_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для удаления слова по вводу.

    Callback: cf:{category}dw:{chat_id}
    Пользователь вводит слово и оно удаляется из БД.

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Логируем вызов хендлера для отладки
    logger.info(f"[ContentFilter] start_delete_category_word вызван: {callback.data}")

    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Получаем название категории
    category_db, category_title, _ = CATEGORY_NAMES.get(
        category_code, ('simple', '📝 Простые слова', 'простое слово')
    )

    # Сохраняем данные в состояние
    await state.update_data(
        chat_id=chat_id,
        category_code=category_code,
        category_db=category_db
    )

    # Переводим в состояние ожидания слова
    await state.set_state(DeleteCategoryWordStates.waiting_for_word)

    text = (
        f"🗑️ <b>Удаление слова</b>\n\n"
        f"Категория: {category_title}\n\n"
        f"Отправьте слово или фразу для удаления.\n\n"
        f"<i>Можно отправить несколько слов, каждое с новой строки.</i>"
    )

    # Кнопка возврата (◀️ Назад для консистентности с остальным UI)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}l:{chat_id}:0"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(DeleteCategoryWordStates.waiting_for_word)
async def process_delete_category_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает удаление слова из категории по введённому тексту.

    Args:
        message: Сообщение с текстом слова
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category_code = data.get('category_code')
    category_db = data.get('category_db')

    if not chat_id or not category_code:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны. Попробуйте снова.")
        return

    # Получаем название категории
    _, category_title, _ = CATEGORY_NAMES.get(category_code, ('simple', '📝 Простые слова', 'слово'))

    # ─────────────────────────────────────────────────────────
    # Проверяем что message.text не None (пользователь мог отправить стикер)
    # ─────────────────────────────────────────────────────────
    if not message.text:
        await message.answer("❌ Пожалуйста, отправьте текст для удаления.")
        return

    # Парсим слова (каждое с новой строки)
    words_text = message.text.strip()
    words_list = [w.strip() for w in words_text.split('\n') if w.strip()]

    if not words_list:
        await message.answer("❌ Не указаны слова для удаления.")
        return

    # Удаляем слова
    deleted = 0
    not_found = 0

    for word in words_list:
        # ─────────────────────────────────────────────────────────
        # При добавлении используется normalized=word.lower(), поэтому
        # при удалении тоже ищем по word.lower() для консистентности.
        # НЕ используем TextNormalizer здесь, т.к. добавление его не использует.
        # ─────────────────────────────────────────────────────────
        normalized = word.lower()

        # Ищем и удаляем слово по (chat_id, category, normalized)
        result = await session.execute(
            delete(FilterWord).where(
                FilterWord.chat_id == chat_id,
                FilterWord.category == category_db,
                FilterWord.normalized == normalized
            )
        )

        if result.rowcount > 0:
            deleted += 1
        else:
            not_found += 1

    await session.commit()

    # НЕ очищаем FSM - позволяем продолжить удаление
    # FSM очистится при нажатии "Готово" или "Отмена"

    # Удаляем сообщение пользователя для чистоты чата
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем ответ
    result_text = f"✅ Удалено слов: {deleted}"
    if not_found > 0:
        result_text += f"\n⚠️ Не найдено: {not_found}"

    logger.info(f"[ContentFilter] Из чата {chat_id} удалено {deleted} слов категории {category_db}")

    # Получаем обновлённый список слов
    words = await _filter_manager.word_filter.get_words_by_category(chat_id, session, category_db)

    # Формируем текст с возможностью продолжить удаление
    text = (
        f"{result_text}\n\n"
        f"🗑️ {category_title}\n"
        f"Всего слов: {len(words)}\n\n"
        f"Отправьте ещё слова для удаления или нажмите «Готово».\n"
        f"<i>Можно отправить несколько слов, каждое с новой строки.</i>"
    )

    # Кнопки: Готово и Назад (консистентность UI)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"cf:{category_code}l:{chat_id}:0"
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}l:{chat_id}:0"
        )]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# УДАЛЕНИЕ ВСЕХ СЛОВ КАТЕГОРИИ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)da:-?\d+$"))
async def delete_all_category_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все слова из категории.

    Callback: cf:{category}da:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Получаем название категории
    category_db, category_title, _ = CATEGORY_NAMES.get(
        category_code, ('simple', '📝 Простые слова', 'слово')
    )

    # Удаляем все слова категории
    result = await session.execute(
        delete(FilterWord).where(
            FilterWord.chat_id == chat_id,
            FilterWord.category == category_db
        )
    )
    await session.commit()

    deleted_count = result.rowcount
    logger.info(f"[ContentFilter] Из чата {chat_id} удалено {deleted_count} слов категории {category_db}")

    await callback.answer(f"✅ Удалено {deleted_count} слов")

    # Показываем пустой список
    text = f"{category_title}\n\nСписок пуст. Добавьте слова через кнопку ниже."

    # Клавиатура (только кнопки управления, без слов)
    keyboard = create_category_words_list_menu(
        chat_id, category_code, 0, 1
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ КАТЕГОРИЙ (ТЕКСТ, ЗАДЕРЖКИ)
# ============================================================
# Эти настройки позволяют админам кастомизировать:
# - Текст уведомления при муте/бане (с %user% плейсхолдером)
# - Задержку удаления сообщения нарушителя
# - Автоудаление уведомления бота через заданное время
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)adv:-?\d+$"))
async def category_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню дополнительных настроек категории.

    Callback: cf:{category}adv:{chat_id}
    Примеры: cf:swadv:-123, cf:hwadv:-123, cf:owadv:-123

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние при возврате из ввода
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Маппинг категории на названия
    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Маппинг на поля БД
    text_fields = {
        'sw': ('simple_words_mute_text', 'simple_words_ban_text'),
        'hw': ('harmful_words_mute_text', 'harmful_words_ban_text'),
        'ow': ('obfuscated_words_mute_text', 'obfuscated_words_ban_text')
    }
    delay_fields = {
        'sw': ('simple_words_delete_delay', 'simple_words_notification_delete_delay'),
        'hw': ('harmful_words_delete_delay', 'harmful_words_notification_delete_delay'),
        'ow': ('obfuscated_words_delete_delay', 'obfuscated_words_notification_delete_delay')
    }

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Получаем текущие значения
    mute_text_field, ban_text_field = text_fields[category_code]
    delete_delay_field, notif_delay_field = delay_fields[category_code]

    mute_text = getattr(settings, mute_text_field, None)
    ban_text = getattr(settings, ban_text_field, None)
    delete_delay = getattr(settings, delete_delay_field, None)
    notif_delay = getattr(settings, notif_delay_field, None)

    # Форматируем значения для отображения
    mute_text_display = f"«{mute_text[:30]}...»" if mute_text and len(mute_text) > 30 else (f"«{mute_text}»" if mute_text else "по умолчанию")
    ban_text_display = f"«{ban_text[:30]}...»" if ban_text and len(ban_text) > 30 else (f"«{ban_text}»" if ban_text else "по умолчанию")
    delete_delay_display = f"{delete_delay} сек" if delete_delay else "сразу"
    notif_delay_display = f"{notif_delay} сек" if notif_delay else "не удалять"

    # Формируем текст меню
    text = (
        f"⚙️ <b>Доп. настройки: {category_names[category_code]}</b>\n\n"
        f"<b>Текст уведомлений:</b>\n"
        f"• При муте: {mute_text_display}\n"
        f"• При бане: {ban_text_display}\n\n"
        f"<b>Задержки:</b>\n"
        f"• Удаление сообщения: {delete_delay_display}\n"
        f"• Автоудаление уведомления: {notif_delay_display}\n\n"
        f"<i>Используйте %user% для упоминания пользователя в тексте.</i>"
    )

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # ─────────────────────────────────────────────────────────
        # Текст уведомления при муте
        # ─────────────────────────────────────────────────────────
        [InlineKeyboardButton(
            text=f"📝 Текст при муте: {mute_text_display[:15]}",
            callback_data=f"cf:{category_code}mt:{chat_id}"
        )],
        # ─────────────────────────────────────────────────────────
        # Текст уведомления при бане
        # ─────────────────────────────────────────────────────────
        [InlineKeyboardButton(
            text=f"📝 Текст при бане: {ban_text_display[:15]}",
            callback_data=f"cf:{category_code}bt:{chat_id}"
        )],
        # ─────────────────────────────────────────────────────────
        # Задержка удаления сообщения нарушителя
        # ─────────────────────────────────────────────────────────
        [InlineKeyboardButton(
            text=f"⏱️ Удаление сообщения: {delete_delay_display}",
            callback_data=f"cf:{category_code}dd:{chat_id}"
        )],
        # ─────────────────────────────────────────────────────────
        # Автоудаление уведомления бота
        # ─────────────────────────────────────────────────────────
        [InlineKeyboardButton(
            text=f"🗑️ Автоудаление уведомления: {notif_delay_display}",
            callback_data=f"cf:{category_code}nd:{chat_id}"
        )],
        # ─────────────────────────────────────────────────────────
        # Назад к меню действий категории
        # ─────────────────────────────────────────────────────────
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}a:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# FSM: ВВОД ТЕКСТА УВЕДОМЛЕНИЯ ПРИ МУТЕ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)mt:-?\d+$"))
async def request_mute_text_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста уведомления при муте.

    Callback: cf:{category}mt:{chat_id}
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Сохраняем в FSM (включая message_id для последующего редактирования)
    await state.set_state(CategoryTextStates.waiting_for_mute_text)
    await state.update_data(
        chat_id=chat_id,
        category=category_code,
        instruction_message_id=callback.message.message_id  # Сохраняем ID сообщения
    )

    text = (
        f"📝 <b>Текст уведомления при муте</b>\n"
        f"Категория: {category_names[category_code]}\n\n"
        f"Введите текст уведомления.\n"
        f"Используйте <code>%user%</code> для упоминания пользователя.\n\n"
        f"Пример: <code>%user% получил мут за спам</code>\n\n"
        f"Отправьте <code>-</code> чтобы сбросить на стандартный текст."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}adv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(CategoryTextStates.waiting_for_mute_text)
async def process_mute_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод текста уведомления при муте.
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Маппинг на поле БД
    field_map = {
        'sw': 'simple_words_mute_text',
        'hw': 'harmful_words_mute_text',
        'ow': 'obfuscated_words_mute_text'
    }
    field_name = field_map[category]

    # Получаем текст (или NULL если сброс)
    text_value = message.text.strip()
    if text_value == '-':
        text_value = None

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, **{field_name: text_value})

    # Очищаем FSM
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Подтверждение
    if text_value:
        confirm_text = f"✅ Текст при муте установлен:\n«{text_value}»"
    else:
        confirm_text = "✅ Текст при муте сброшен на стандартный"

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:{category}adv:{chat_id}"
        )]
    ])

    result_text = f"{confirm_text}\n\nКатегория: {category_names[category]}"

    # Редактируем исходное сообщение вместо отправки нового
    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=result_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    # Fallback: отправляем новое сообщение
    await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# FSM: ВВОД ТЕКСТА УВЕДОМЛЕНИЯ ПРИ БАНЕ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)bt:-?\d+$"))
async def request_ban_text_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста уведомления при бане.

    Callback: cf:{category}bt:{chat_id}
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Сохраняем в FSM (включая message_id для последующего редактирования)
    await state.set_state(CategoryTextStates.waiting_for_ban_text)
    await state.update_data(
        chat_id=chat_id,
        category=category_code,
        instruction_message_id=callback.message.message_id
    )

    text = (
        f"📝 <b>Текст уведомления при бане</b>\n"
        f"Категория: {category_names[category_code]}\n\n"
        f"Введите текст уведомления.\n"
        f"Используйте <code>%user%</code> для упоминания пользователя.\n\n"
        f"Пример: <code>%user% забанен за запрещённый контент</code>\n\n"
        f"Отправьте <code>-</code> чтобы сбросить на стандартный текст."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}adv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(CategoryTextStates.waiting_for_ban_text)
async def process_ban_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод текста уведомления при бане.
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Маппинг на поле БД
    field_map = {
        'sw': 'simple_words_ban_text',
        'hw': 'harmful_words_ban_text',
        'ow': 'obfuscated_words_ban_text'
    }
    field_name = field_map[category]

    # Получаем текст (или NULL если сброс)
    text_value = message.text.strip()
    if text_value == '-':
        text_value = None

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, **{field_name: text_value})

    # Очищаем FSM
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Подтверждение
    if text_value:
        confirm_text = f"✅ Текст при бане установлен:\n«{text_value}»"
    else:
        confirm_text = "✅ Текст при бане сброшен на стандартный"

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:{category}adv:{chat_id}"
        )]
    ])

    result_text = f"{confirm_text}\n\nКатегория: {category_names[category]}"

    # Редактируем исходное сообщение вместо отправки нового
    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=result_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    # Fallback: отправляем новое сообщение
    await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# FSM: ВВОД ЗАДЕРЖКИ УДАЛЕНИЯ СООБЩЕНИЯ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)dd:-?\d+$"))
async def request_delete_delay_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод задержки удаления сообщения нарушителя.

    Callback: cf:{category}dd:{chat_id}
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Сохраняем в FSM (включая message_id для последующего редактирования)
    await state.set_state(CategoryDelayStates.waiting_for_delete_delay)
    await state.update_data(
        chat_id=chat_id,
        category=category_code,
        instruction_message_id=callback.message.message_id
    )

    text = (
        f"⏱️ <b>Задержка удаления сообщения</b>\n"
        f"Категория: {category_names[category_code]}\n\n"
        f"Введите время через которое удалить сообщение нарушителя.\n\n"
        f"Форматы:\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n\n"
        f"Отправьте <code>0</code> или <code>-</code> для мгновенного удаления."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}adv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(CategoryDelayStates.waiting_for_delete_delay)
async def process_delete_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод задержки удаления сообщения.
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Маппинг на поле БД
    field_map = {
        'sw': 'simple_words_delete_delay',
        'hw': 'harmful_words_delete_delay',
        'ow': 'obfuscated_words_delete_delay'
    }
    field_name = field_map[category]

    # Парсим значение
    text_input = message.text.strip()
    if text_input in ('-', '0'):
        delay_seconds = None
    else:
        delay_seconds = parse_delay_seconds(text_input)
        if delay_seconds is None:
            # Неверный формат - удаляем сообщение пользователя
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            # Показываем ошибку в редактируемом сообщении
            error_text = (
                "❌ Неверный формат. Используйте: 30s, 5min, 1h\n"
                "Или отправьте 0 для мгновенного удаления.\n\n"
                "Попробуйте ещё раз:"
            )
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:{category}adv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text=error_text,
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            await message.answer(error_text, reply_markup=error_keyboard, parse_mode="HTML")
            return

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, **{field_name: delay_seconds})

    # Очищаем FSM
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Подтверждение
    if delay_seconds:
        confirm_text = f"✅ Задержка удаления: {delay_seconds} сек"
    else:
        confirm_text = "✅ Сообщение будет удаляться сразу"

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:{category}adv:{chat_id}"
        )]
    ])

    result_text = f"{confirm_text}\n\nКатегория: {category_names[category]}"

    # Редактируем исходное сообщение вместо отправки нового
    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=result_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    # Fallback: отправляем новое сообщение
    await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# FSM: ВВОД ЗАДЕРЖКИ АВТОУДАЛЕНИЯ УВЕДОМЛЕНИЯ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)nd:-?\d+$"))
async def request_notification_delay_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод задержки автоудаления уведомления бота.

    Callback: cf:{category}nd:{chat_id}
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_code = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Сохраняем в FSM (включая message_id для последующего редактирования)
    await state.set_state(CategoryDelayStates.waiting_for_notification_delay)
    await state.update_data(
        chat_id=chat_id,
        category=category_code,
        instruction_message_id=callback.message.message_id
    )

    text = (
        f"🗑️ <b>Автоудаление уведомления бота</b>\n"
        f"Категория: {category_names[category_code]}\n\n"
        f"Введите время через которое удалить уведомление бота.\n\n"
        f"Форматы:\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n\n"
        f"Отправьте <code>-</code> чтобы не удалять уведомления."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category_code}adv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.message(CategoryDelayStates.waiting_for_notification_delay)
async def process_notification_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод задержки автоудаления уведомления бота.
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Маппинг на поле БД
    field_map = {
        'sw': 'simple_words_notification_delete_delay',
        'hw': 'harmful_words_notification_delete_delay',
        'ow': 'obfuscated_words_notification_delete_delay'
    }
    field_name = field_map[category]

    # Парсим значение
    text_input = message.text.strip()
    if text_input == '-':
        delay_seconds = None
    else:
        delay_seconds = parse_delay_seconds(text_input)
        if delay_seconds is None:
            # Неверный формат - удаляем сообщение пользователя
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            # Показываем ошибку в редактируемом сообщении
            error_text = (
                "❌ Неверный формат. Используйте: 30s, 5min, 1h\n"
                "Или отправьте - чтобы не удалять уведомления.\n\n"
                "Попробуйте ещё раз:"
            )
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:{category}adv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text=error_text,
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            await message.answer(error_text, reply_markup=error_keyboard, parse_mode="HTML")
            return

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, **{field_name: delay_seconds})

    # Очищаем FSM
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Подтверждение
    if delay_seconds:
        confirm_text = f"✅ Автоудаление уведомления через: {delay_seconds} сек"
    else:
        confirm_text = "✅ Уведомления не будут удаляться автоматически"

    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:{category}adv:{chat_id}"
        )]
    ])

    result_text = f"{confirm_text}\n\nКатегория: {category_names[category]}"

    # Редактируем исходное сообщение вместо отправки нового
    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=result_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    # Fallback: отправляем новое сообщение
    await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# КАТЕГОРИИ СИГНАЛОВ АНТИСКАМА
# ============================================================
# Категории позволяют админам создавать свои наборы ключевых слов
# для обнаружения скама (например: "Наркотики", "Контакты").
# Каждая категория имеет название, ключевые слова и вес.
# ============================================================


class SignalCategoryStates(StatesGroup):
    """FSM состояния для добавления/редактирования категории."""
    waiting_for_name = State()
    waiting_for_keywords = State()
    waiting_for_weight = State()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sccat:-?\d+$"))
async def signal_categories_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает список категорий сигналов антискама.

    Callback: cf:sccat:{chat_id}
    """
    await state.clear()

    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Загружаем категории из БД
    from bot.database.models_content_filter import ScamSignalCategory
    from sqlalchemy import select

    query = select(ScamSignalCategory).where(
        ScamSignalCategory.chat_id == chat_id
    ).order_by(ScamSignalCategory.category_name)

    result = await session.execute(query)
    categories = result.scalars().all()

    # Формируем текст
    if categories:
        text = f"📂 <b>Категории сигналов</b>\n\n"
        for i, cat in enumerate(categories, 1):
            status = "✅" if cat.enabled else "❌"
            kw_count = len([k for k in cat.keywords.split(',') if k.strip()]) if cat.keywords else 0
            text += f"{i}. {status} <b>{cat.category_name}</b>\n"
            text += f"   Слов: {kw_count}, Вес: +{cat.weight}\n\n"
    else:
        text = (
            f"📂 <b>Категории сигналов</b>\n\n"
            f"Категорий пока нет.\n"
            f"Создайте первую категорию для детекции скама.\n\n"
            f"<i>Например: \"Наркотики\" с ключевыми словами\n"
            f"drugs, cocaine, weed...</i>"
        )

    # Создаём клавиатуру
    keyboard_buttons = []

    # Список существующих категорий
    for cat in categories:
        status = "✅" if cat.enabled else "❌"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{status} {cat.category_name}",
                callback_data=f"cf:sccatedit:{chat_id}:{cat.id}"
            )
        ])

    # Кнопка добавления
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="➕ Добавить категорию",
            callback_data=f"cf:sccatadd:{chat_id}"
        )
    ])

    # Кнопка назад
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:scs:{chat_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sccatadd:-?\d+$"))
async def add_signal_category_start(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления новой категории.

    Callback: cf:sccatadd:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(chat_id=chat_id)
    await state.set_state(SignalCategoryStates.waiting_for_name)

    text = (
        f"📂 <b>Новая категория</b>\n\n"
        f"Введите название категории.\n"
        f"Например: <code>Наркотики</code> или <code>Контакты</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:sccat:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await state.update_data(
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )

    await callback.answer()


@settings_handler_router.message(SignalCategoryStates.waiting_for_name)
async def add_signal_category_name(
    message: Message,
    state: FSMContext
) -> None:
    """Обрабатывает ввод названия категории."""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сохраняем название
    category_name = message.text.strip()[:100]
    await state.update_data(category_name=category_name)
    await state.set_state(SignalCategoryStates.waiting_for_keywords)

    text = (
        f"📂 <b>Новая категория: {category_name}</b>\n\n"
        f"Введите ключевые слова через запятую.\n"
        f"Например: <code>drugs, cocaine, weed, meth</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:sccat:{chat_id}"
        )]
    ])

    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@settings_handler_router.message(SignalCategoryStates.waiting_for_keywords)
async def add_signal_category_keywords(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ввод ключевых слов и создаёт категорию."""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category_name = data.get('category_name')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Очищаем FSM
    await state.clear()

    # Нормализуем ключевые слова
    keywords = message.text.strip()

    # Создаём категорию в БД
    from bot.database.models_content_filter import ScamSignalCategory

    new_category = ScamSignalCategory(
        chat_id=chat_id,
        category_name=category_name,
        keywords=keywords,
        weight=25,  # Вес по умолчанию
        enabled=True,
        created_by=message.from_user.id
    )

    session.add(new_category)
    await session.commit()

    # Показываем успех и возвращаемся к списку
    text = (
        f"✅ Категория <b>{category_name}</b> создана!\n\n"
        f"Ключевые слова: {keywords[:50]}{'...' if len(keywords) > 50 else ''}\n"
        f"Вес: +25 баллов\n\n"
        f"<i>Вы можете изменить настройки категории в меню.</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📂 К списку категорий",
            callback_data=f"cf:sccat:{chat_id}"
        )]
    ])

    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sccatedit:-?\d+:\d+$"))
async def edit_signal_category(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню редактирования категории.

    Callback: cf:sccatedit:{chat_id}:{category_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    category_id = int(parts[3])

    # Загружаем категорию
    from bot.database.models_content_filter import ScamSignalCategory
    from sqlalchemy import select

    query = select(ScamSignalCategory).where(ScamSignalCategory.id == category_id)
    result = await session.execute(query)
    category = result.scalar_one_or_none()

    if not category:
        await callback.answer("❌ Категория не найдена", show_alert=True)
        return

    # Формируем текст
    status = "Включена ✅" if category.enabled else "Выключена ❌"
    kw_preview = category.keywords[:100] if category.keywords else "—"
    if len(category.keywords or '') > 100:
        kw_preview += "..."

    text = (
        f"📂 <b>Категория: {category.category_name}</b>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Вес:</b> +{category.weight} баллов\n"
        f"<b>Ключевые слова:</b>\n<code>{kw_preview}</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'❌ Выключить' if category.enabled else '✅ Включить'}",
            callback_data=f"cf:sccattgl:{chat_id}:{category_id}"
        )],
        [InlineKeyboardButton(
            text="🗑️ Удалить",
            callback_data=f"cf:sccatdel:{chat_id}:{category_id}"
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:sccat:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sccattgl:-?\d+:\d+$"))
async def toggle_signal_category(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает активность категории.

    Callback: cf:sccattgl:{chat_id}:{category_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    category_id = int(parts[3])

    from bot.database.models_content_filter import ScamSignalCategory
    from sqlalchemy import select, update

    # Получаем текущее состояние
    query = select(ScamSignalCategory).where(ScamSignalCategory.id == category_id)
    result = await session.execute(query)
    category = result.scalar_one_or_none()

    if not category:
        await callback.answer("❌ Категория не найдена", show_alert=True)
        return

    # Переключаем
    new_status = not category.enabled
    update_query = update(ScamSignalCategory).where(
        ScamSignalCategory.id == category_id
    ).values(enabled=new_status)

    await session.execute(update_query)
    await session.commit()

    status_text = "включена" if new_status else "выключена"
    await callback.answer(f"Категория {status_text}")

    # Перерисовываем меню
    # Создаём новый callback data для edit
    callback.data = f"cf:sccatedit:{chat_id}:{category_id}"
    await edit_signal_category(callback, session)


@settings_handler_router.callback_query(F.data.regexp(r"^cf:sccatdel:-?\d+:\d+$"))
async def delete_signal_category(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет категорию.

    Callback: cf:sccatdel:{chat_id}:{category_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    category_id = int(parts[3])

    from bot.database.models_content_filter import ScamSignalCategory
    from sqlalchemy import delete

    # Удаляем
    query = delete(ScamSignalCategory).where(ScamSignalCategory.id == category_id)
    await session.execute(query)
    await session.commit()

    await callback.answer("✅ Категория удалена")

    # Возвращаемся к списку
    callback.data = f"cf:sccat:{chat_id}"
    await signal_categories_menu(callback, session, None)


# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ АНТИСКАМА (ТЕКСТ, ЗАДЕРЖКИ)
# ============================================================
# Эти настройки позволяют админам кастомизировать:
# - Текст уведомления при муте/бане (с %user% плейсхолдером)
# - Задержку удаления сообщения нарушителя
# - Автоудаление уведомления бота через заданное время
# ============================================================


class ScamTextStates(StatesGroup):
    """FSM состояния для ввода кастомного текста уведомлений антискама."""
    waiting_for_mute_text = State()
    waiting_for_ban_text = State()


class ScamDelayStates(StatesGroup):
    """FSM состояния для ввода задержек антискама."""
    waiting_for_delete_delay = State()
    waiting_for_notification_delay = State()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:scadv:-?\d+$"))
async def scam_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню дополнительных настроек антискама.

    Callback: cf:scadv:{chat_id}
    """
    # Очищаем FSM состояние при возврате из ввода
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Получаем текущие значения
    mute_text = settings.scam_mute_text
    ban_text = settings.scam_ban_text
    delete_delay = settings.scam_delete_delay
    notif_delay = settings.scam_notification_delete_delay

    # Форматируем значения для отображения
    mute_text_display = f"«{mute_text[:30]}...»" if mute_text and len(mute_text) > 30 else (f"«{mute_text}»" if mute_text else "по умолчанию")
    ban_text_display = f"«{ban_text[:30]}...»" if ban_text and len(ban_text) > 30 else (f"«{ban_text}»" if ban_text else "по умолчанию")
    delete_delay_display = f"{delete_delay} сек" if delete_delay else "сразу"
    notif_delay_display = f"{notif_delay} сек" if notif_delay else "не удалять"

    # Формируем текст меню
    text = (
        f"⚙️ <b>Доп. настройки: Антискам</b>\n\n"
        f"<b>Текст уведомлений:</b>\n"
        f"• При муте: {mute_text_display}\n"
        f"• При бане: {ban_text_display}\n\n"
        f"<b>Задержки:</b>\n"
        f"• Удаление сообщения: {delete_delay_display}\n"
        f"• Автоудаление уведомления: {notif_delay_display}\n\n"
        f"<i>Используйте %user% для упоминания пользователя в тексте.</i>"
    )

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📝 Текст при муте: {mute_text_display[:15]}",
            callback_data=f"cf:scmt:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"📝 Текст при бане: {ban_text_display[:15]}",
            callback_data=f"cf:scbt:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"⏱️ Удаление сообщения: {delete_delay_display}",
            callback_data=f"cf:scdd:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"🗑️ Автоудаление уведомления: {notif_delay_display}",
            callback_data=f"cf:scnd:{chat_id}"
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
# FSM: ВВОД ТЕКСТА УВЕДОМЛЕНИЯ ПРИ МУТЕ (АНТИСКАМ)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scmt:-?\d+$"))
async def request_scam_mute_text_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста уведомления при муте для антискама.

    Callback: cf:scmt:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"📝 <b>Текст уведомления при муте</b>\n\n"
        f"Введите текст, который будет показан при муте за скам.\n"
        f"Используйте <code>%user%</code> для упоминания нарушителя.\n\n"
        f"<b>Пример:</b>\n"
        f"<code>%user% замьючен за скам</code>\n\n"
        f"Отправьте <code>-</code> чтобы сбросить на стандартный текст."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await state.set_state(ScamTextStates.waiting_for_mute_text)
    await state.update_data(chat_id=chat_id, instruction_message_id=callback.message.message_id)
    await callback.answer()


@settings_handler_router.message(ScamTextStates.waiting_for_mute_text)
async def process_scam_mute_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста уведомления при муте для антискама."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    text_input = message.text.strip()
    if text_input == "-":
        new_text = None
    else:
        if len(text_input) > 500:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text="❌ Текст слишком длинный (макс. 500 символов).\n\nПопробуйте ещё раз:",
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            return
        new_text = text_input

    await _filter_manager.update_settings(chat_id, session, scam_mute_text=new_text)
    await state.clear()

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при муте установлен:\n«{new_text}»" if new_text else "✅ Текст при муте сброшен на стандартный"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:scadv:{chat_id}")]
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
# FSM: ВВОД ТЕКСТА УВЕДОМЛЕНИЯ ПРИ БАНЕ (АНТИСКАМ)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scbt:-?\d+$"))
async def request_scam_ban_text_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста уведомления при бане для антискама.

    Callback: cf:scbt:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"📝 <b>Текст уведомления при бане</b>\n\n"
        f"Введите текст, который будет показан при бане за скам.\n"
        f"Используйте <code>%user%</code> для упоминания нарушителя.\n\n"
        f"<b>Пример:</b>\n"
        f"<code>%user% забанен за скам</code>\n\n"
        f"Отправьте <code>-</code> чтобы сбросить на стандартный текст."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await state.set_state(ScamTextStates.waiting_for_ban_text)
    await state.update_data(chat_id=chat_id, instruction_message_id=callback.message.message_id)
    await callback.answer()


@settings_handler_router.message(ScamTextStates.waiting_for_ban_text)
async def process_scam_ban_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста уведомления при бане для антискама."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    text_input = message.text.strip()
    if text_input == "-":
        new_text = None
    else:
        if len(text_input) > 500:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text="❌ Текст слишком длинный (макс. 500 символов).\n\nПопробуйте ещё раз:",
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            return
        new_text = text_input

    await _filter_manager.update_settings(chat_id, session, scam_ban_text=new_text)
    await state.clear()

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при бане установлен:\n«{new_text}»" if new_text else "✅ Текст при бане сброшен на стандартный"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:scadv:{chat_id}")]
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
# FSM: ЗАДЕРЖКА УДАЛЕНИЯ СООБЩЕНИЯ НАРУШИТЕЛЯ (АНТИСКАМ)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scdd:-?\d+$"))
async def request_scam_delete_delay_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод задержки удаления сообщения для антискама.

    Callback: cf:scdd:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"⏱️ <b>Задержка удаления сообщения</b>\n\n"
        f"Введите время, через которое сообщение нарушителя будет удалено.\n\n"
        f"<b>Форматы:</b>\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n\n"
        f"Отправьте <code>-</code> чтобы удалять сразу."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await state.set_state(ScamDelayStates.waiting_for_delete_delay)
    await state.update_data(chat_id=chat_id, instruction_message_id=callback.message.message_id)
    await callback.answer()


@settings_handler_router.message(ScamDelayStates.waiting_for_delete_delay)
async def process_scam_delete_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод задержки удаления сообщения для антискама."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    text_input = message.text.strip()
    if text_input == "-":
        delay_seconds = None
    else:
        delay_seconds = parse_delay_seconds(text_input)
        if delay_seconds is None:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text="❌ Неверный формат. Используйте: 30s, 5min, 1h\nИли отправьте - чтобы удалять сразу.\n\nПопробуйте ещё раз:",
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            return

    await _filter_manager.update_settings(chat_id, session, scam_delete_delay=delay_seconds)
    await state.clear()

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Задержка удаления сообщения: {delay_seconds} сек" if delay_seconds else "✅ Сообщения будут удаляться сразу"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:scadv:{chat_id}")]
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
# FSM: АВТОУДАЛЕНИЕ УВЕДОМЛЕНИЯ БОТА (АНТИСКАМ)
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:scnd:-?\d+$"))
async def request_scam_notification_delay_input(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод задержки автоудаления уведомления для антискама.

    Callback: cf:scnd:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"🗑️ <b>Автоудаление уведомления бота</b>\n\n"
        f"Введите время, через которое уведомление бота будет удалено.\n\n"
        f"<b>Форматы:</b>\n"
        f"• <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n\n"
        f"Отправьте <code>-</code> чтобы не удалять уведомления."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await state.set_state(ScamDelayStates.waiting_for_notification_delay)
    await state.update_data(chat_id=chat_id, instruction_message_id=callback.message.message_id)
    await callback.answer()


@settings_handler_router.message(ScamDelayStates.waiting_for_notification_delay)
async def process_scam_notification_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод задержки автоудаления уведомления для антискама."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    text_input = message.text.strip()
    if text_input == "-":
        delay_seconds = None
    else:
        delay_seconds = parse_delay_seconds(text_input)
        if delay_seconds is None:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            error_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:scadv:{chat_id}")]
            ])
            if instruction_message_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=instruction_message_id,
                        text="❌ Неверный формат. Используйте: 30s, 5min, 1h\nИли отправьте - чтобы не удалять уведомления.\n\nПопробуйте ещё раз:",
                        reply_markup=error_keyboard,
                        parse_mode="HTML"
                    )
                    return
                except TelegramAPIError:
                    pass
            return

    await _filter_manager.update_settings(chat_id, session, scam_notification_delete_delay=delay_seconds)
    await state.clear()

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Автоудаление уведомления через: {delay_seconds} сек" if delay_seconds else "✅ Уведомления не будут удаляться автоматически"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:scadv:{chat_id}")]
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
# РАСШИРЕННЫЙ АНТИФЛУД: ПЕРЕКЛЮЧАТЕЛИ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:t:flany:-?\d+$"))
async def toggle_flood_any_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает детекцию флуда любых сообщений.

    Callback: cf:t:flany:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.flood_detect_any_messages
    await _filter_manager.update_settings(chat_id, session, flood_detect_any_messages=new_value)

    # Получаем обновлённые настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем статус расширенного антифлуда
    any_status = "✅ Вкл" if settings.flood_detect_any_messages else "❌ Выкл"
    media_status = "✅ Вкл" if settings.flood_detect_media else "❌ Выкл"

    text = (
        f"📢 <b>Настройки антифлуда</b>\n\n"
        f"Флуд — это когда пользователь отправляет одинаковые "
        f"сообщения несколько раз подряд.\n\n"
        f"<b>Макс. повторов:</b> {settings.flood_max_repeats}\n"
        f"<b>Временное окно:</b> {settings.flood_time_window} сек.\n\n"
        f"<b>Расширенный антифлуд:</b>\n"
        f"• Любые сообщения подряд: {any_status}\n"
        f"• Медиа-флуд: {media_status}\n\n"
        f"Если пользователь отправит больше {settings.flood_max_repeats} "
        f"одинаковых сообщений за {settings.flood_time_window} секунд — "
        f"сработает фильтр."
    )

    keyboard = create_flood_settings_menu(
        chat_id,
        settings.flood_max_repeats,
        settings.flood_time_window,
        settings.flood_action,
        settings.flood_mute_duration,
        settings.flood_detect_any_messages,
        settings.flood_any_max_messages,
        settings.flood_any_time_window,
        settings.flood_detect_media
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    status_text = "включена" if new_value else "выключена"
    await callback.answer(f"Детекция любых сообщений {status_text}")


@settings_handler_router.callback_query(F.data.regexp(r"^cf:t:flmedia:-?\d+$"))
async def toggle_flood_media(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает детекцию медиа-флуда.

    Callback: cf:t:flmedia:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.flood_detect_media
    await _filter_manager.update_settings(chat_id, session, flood_detect_media=new_value)

    # Получаем обновлённые настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем статус расширенного антифлуда
    any_status = "✅ Вкл" if settings.flood_detect_any_messages else "❌ Выкл"
    media_status = "✅ Вкл" if settings.flood_detect_media else "❌ Выкл"

    text = (
        f"📢 <b>Настройки антифлуда</b>\n\n"
        f"Флуд — это когда пользователь отправляет одинаковые "
        f"сообщения несколько раз подряд.\n\n"
        f"<b>Макс. повторов:</b> {settings.flood_max_repeats}\n"
        f"<b>Временное окно:</b> {settings.flood_time_window} сек.\n\n"
        f"<b>Расширенный антифлуд:</b>\n"
        f"• Любые сообщения подряд: {any_status}\n"
        f"• Медиа-флуд: {media_status}\n\n"
        f"Если пользователь отправит больше {settings.flood_max_repeats} "
        f"одинаковых сообщений за {settings.flood_time_window} секунд — "
        f"сработает фильтр."
    )

    keyboard = create_flood_settings_menu(
        chat_id,
        settings.flood_max_repeats,
        settings.flood_time_window,
        settings.flood_action,
        settings.flood_mute_duration,
        settings.flood_detect_any_messages,
        settings.flood_any_max_messages,
        settings.flood_any_time_window,
        settings.flood_detect_media
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    status_text = "включена" if new_value else "выключена"
    await callback.answer(f"Детекция медиа-флуда {status_text}")


# ============================================================
# РАСШИРЕННЫЙ АНТИФЛУД: МЕНЮ "ДОПОЛНИТЕЛЬНО"
# ============================================================
# ПРИМЕЧАНИЕ: Отдельное меню cf:flanycfg было удалено как дублирующее
# Настройки flood_any_max_messages и flood_any_time_window теперь в меню "Дополнительно"

@settings_handler_router.callback_query(F.data.regexp(r"^cf:fladv:-?\d+$"))
async def flood_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает расширенные настройки антифлуда.

    Callback: cf:fladv:{chat_id}

    Настройки:
    - Настройки "любые сообщения": лимит и окно
    - Текст при предупреждении
    - Текст при муте
    - Текст при бане
    - Задержка удаления сообщения
    - Автоудаление уведомления

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id из callback данных
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки группы из БД
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # ============================================================
    # НАСТРОЙКИ БАЗОВОГО АНТИФЛУДА (перенесены сюда из главного меню)
    # ============================================================
    max_repeats = settings.flood_max_repeats or 3
    time_window = settings.flood_time_window or 60
    flood_action = settings.flood_action or 'mute'
    mute_duration = settings.flood_mute_duration

    # Форматируем действие
    action_map = {
        'delete': '🗑️ Удалить',
        'warn': '⚠️ Предупредить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }
    action_text = action_map.get(flood_action, '🔇 Мут')
    if flood_action == 'mute' and mute_duration:
        if mute_duration < 60:
            action_text += f" ({mute_duration}мин)"
        elif mute_duration < 1440:
            action_text += f" ({mute_duration // 60}ч)"
        else:
            action_text += f" ({mute_duration // 1440}д)"

    # ============================================================
    # НАСТРОЙКИ "ЛЮБЫЕ СООБЩЕНИЯ"
    # ============================================================
    any_limit = settings.flood_any_max_messages or 5
    any_window = settings.flood_any_time_window or 10

    # Форматируем кастомные тексты уведомлений
    # Обрезаем длинные тексты для превью
    warn_text = settings.flood_warn_text or "По умолчанию"
    if len(warn_text) > 30:
        warn_text = warn_text[:30] + "..."

    mute_text = settings.flood_mute_text or "По умолчанию"
    if len(mute_text) > 30:
        mute_text = mute_text[:30] + "..."

    ban_text = settings.flood_ban_text or "По умолчанию"
    if len(ban_text) > 30:
        ban_text = ban_text[:30] + "..."

    # Форматируем задержки
    delete_delay = settings.flood_delete_delay or 0
    delete_delay_text = f"{delete_delay} сек" if delete_delay else "Сразу"

    notification_delay = settings.flood_notification_delete_delay or 0
    notification_delay_text = f"{notification_delay} сек" if notification_delay else "Не удалять"

    # Формируем текст меню
    text = (
        f"⚙️ <b>Дополнительные настройки антифлуда</b>\n\n"
        f"<b>━━━ Базовый антифлуд ━━━</b>\n"
        f"<b>Макс. повторов:</b> {max_repeats}\n"
        f"<b>Временное окно:</b> {time_window} сек\n"
        f"<b>Действие:</b> {action_text}\n\n"
        f"<b>━━━ Любые сообщения ━━━</b>\n"
        f"<b>Лимит:</b> {any_limit} за {any_window}с\n\n"
        f"<b>━━━ Тексты уведомлений ━━━</b>\n"
        f"При предупреждении: {warn_text}\n"
        f"При муте: {mute_text}\n"
        f"При бане: {ban_text}\n\n"
        f"<b>━━━ Удаление ━━━</b>\n"
        f"<b>Задержка удаления:</b> {delete_delay_text}\n"
        f"<b>Автоудаление уведомления:</b> {notification_delay_text}"
    )

    # Определяем галочки для текущих значений max_repeats
    rep2_check = " ✓" if max_repeats == 2 else ""
    rep3_check = " ✓" if max_repeats == 3 else ""
    rep5_check = " ✓" if max_repeats == 5 else ""
    rep_custom = max_repeats not in [2, 3, 5]
    rep_custom_text = f"✏️ {max_repeats} ✓" if rep_custom else "✏️"

    # Определяем галочки для time_window
    win30_check = " ✓" if time_window == 30 else ""
    win60_check = " ✓" if time_window == 60 else ""
    win120_check = " ✓" if time_window == 120 else ""
    win180_check = " ✓" if time_window == 180 else ""
    win_custom = time_window not in [30, 60, 120, 180]
    win_custom_text = f"✏️ {time_window}с ✓" if win_custom else "✏️"

    # Формируем клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # БАЗОВЫЙ АНТИФЛУД (перенесено из главного меню)
            # ─────────────────────────────────────────────────────
            # Заголовок: Максимум повторов
            [
                InlineKeyboardButton(
                    text="📢 Макс. повторов:",
                    callback_data="cf:noop"
                )
            ],
            # Ряд выбора повторов
            [
                InlineKeyboardButton(
                    text=f"2{rep2_check}",
                    callback_data=f"cf:flr:2:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"3{rep3_check}",
                    callback_data=f"cf:flr:3:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"5{rep5_check}",
                    callback_data=f"cf:flr:5:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=rep_custom_text,
                    callback_data=f"cf:flrc:{chat_id}"
                )
            ],
            # Заголовок: Временное окно
            [
                InlineKeyboardButton(
                    text="⏱️ Временное окно:",
                    callback_data="cf:noop"
                )
            ],
            # Ряд выбора окна
            [
                InlineKeyboardButton(
                    text=f"30с{win30_check}",
                    callback_data=f"cf:flw:30:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"60с{win60_check}",
                    callback_data=f"cf:flw:60:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"120с{win120_check}",
                    callback_data=f"cf:flw:120:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"180с{win180_check}",
                    callback_data=f"cf:flw:180:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=win_custom_text,
                    callback_data=f"cf:flwc:{chat_id}"
                )
            ],
            # Действие при срабатывании
            [
                InlineKeyboardButton(
                    text=f"⚡ Действие: {action_text}",
                    callback_data=f"cf:fact:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Настройки "любые сообщения"
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📢 Лимит сообщений: {any_limit}",
                    callback_data=f"cf:flanylim:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⏱️ Временное окно: {any_window}с",
                    callback_data=f"cf:flanywin:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Кастомные тексты уведомлений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Текст при предупреждении",
                    callback_data=f"cf:flwt:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Текст при муте",
                    callback_data=f"cf:flmt:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Текст при бане",
                    callback_data=f"cf:flbt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Задержки
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⏱️ Задержка удаления: {delete_delay_text}",
                    callback_data=f"cf:fldd:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🗑️ Автоудаление уведомления: {notification_delay_text}",
                    callback_data=f"cf:flnd:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"cf:fls:{chat_id}"
                )
            ]
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ НАСТРОЕК АНТИФЛУДА
# ============================================================

class FloodTextStates(StatesGroup):
    """Состояния для ввода текстов антифлуда."""
    # Ожидание ввода текста при предупреждении
    waiting_warn_text = State()
    # Ожидание ввода текста при муте
    waiting_mute_text = State()
    # Ожидание ввода текста при бане
    waiting_ban_text = State()


class FloodDelayStates(StatesGroup):
    """Состояния для ввода задержек антифлуда."""
    # Ожидание ввода задержки удаления
    waiting_delete_delay = State()
    # Ожидание ввода задержки автоудаления уведомления
    waiting_notification_delay = State()


class FloodAnySettingsStates(StatesGroup):
    """Состояния для настроек 'любые сообщения'."""
    # Ожидание ввода лимита сообщений
    waiting_any_limit = State()
    # Ожидание ввода временного окна
    waiting_any_window = State()


# ============================================================
# ВВОД ТЕКСТА МУТА ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flmt:-?\d+$"))
async def request_flood_mute_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста для мута при флуде.

    Callback: cf:flmt:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    current_text = settings.flood_mute_text or "Не задан"

    text = (
        f"📝 <b>Текст при муте за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление, "
        f"когда пользователь получит мут за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%, %time%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние
    await state.set_state(FloodTextStates.waiting_mute_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodTextStates.waiting_mute_text)
async def process_flood_mute_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста мута для антифлуда."""
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Очищаем состояние
    await state.clear()

    # Получаем текст
    text = message.text.strip() if message.text else ""

    # Если "-" - сбрасываем
    if text == "-":
        text = None

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_mute_text=text)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при муте сохранён" if text else "✅ Текст при муте сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
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
# ВВОД ТЕКСТА БАНА ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flbt:-?\d+$"))
async def request_flood_ban_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста для бана при флуде.

    Callback: cf:flbt:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    current_text = settings.flood_ban_text or "Не задан"

    text = (
        f"📝 <b>Текст при бане за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление, "
        f"когда пользователь получит бан за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние
    await state.set_state(FloodTextStates.waiting_ban_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodTextStates.waiting_ban_text)
async def process_flood_ban_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста бана для антифлуда."""
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Очищаем состояние
    await state.clear()

    # Получаем текст
    text = message.text.strip() if message.text else ""

    # Если "-" - сбрасываем
    if text == "-":
        text = None

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_ban_text=text)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при бане сохранён" if text else "✅ Текст при бане сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
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
# ВВОД ЗАДЕРЖКИ УДАЛЕНИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:fldd:-?\d+$"))
async def request_flood_delete_delay_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод задержки удаления при флуде.

    Callback: cf:fldd:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    current_delay = settings.flood_delete_delay or 0

    text = (
        f"⏱️ <b>Задержка удаления сообщения</b>\n\n"
        f"Задержка перед удалением сообщения-флуда.\n"
        f"Полезно, чтобы пользователь увидел что его сообщение "
        f"было обнаружено как флуд.\n\n"
        f"<b>Текущая задержка:</b> {current_delay} сек\n\n"
        f"Введите задержку в секундах или <code>0</code> для мгновенного удаления."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние
    await state.set_state(FloodDelayStates.waiting_delete_delay)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodDelayStates.waiting_delete_delay)
async def process_flood_delete_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод задержки удаления для антифлуда."""
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Кнопка отмены для редактирования сообщения при ошибке
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Пробуем получить число (без верхнего лимита — админ решает сам)
    try:
        delay_seconds = int(message.text.strip())
        if delay_seconds < 0:
            raise ValueError("Значение должно быть неотрицательным")
    except (ValueError, TypeError):
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Ошибка валидации — редактируем сообщение-инструкцию
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text=(
                        f"❌ <b>Ошибка:</b> введите неотрицательное число.\n\n"
                        f"Введите задержку в секундах:"
                    ),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите неотрицательное число")
        return

    # Очищаем состояние
    await state.clear()

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_delete_delay=delay_seconds)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Задержка удаления: {delay_seconds} сек" if delay_seconds else "✅ Мгновенное удаление"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
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
# ВВОД АВТОУДАЛЕНИЯ УВЕДОМЛЕНИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flnd:-?\d+$"))
async def request_flood_notification_delay_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод времени автоудаления уведомления.

    Callback: cf:flnd:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    current_delay = settings.flood_notification_delete_delay or 0

    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Через сколько секунд удалять уведомление о флуде.\n"
        f"Полезно, чтобы не засорять чат.\n\n"
        f"<b>Текущее значение:</b> {current_delay} сек\n\n"
        f"Введите значение в секундах или <code>0</code> чтобы не удалять."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние
    await state.set_state(FloodDelayStates.waiting_notification_delay)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodDelayStates.waiting_notification_delay)
async def process_flood_notification_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод времени автоудаления уведомления."""
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Кнопка отмены для редактирования сообщения при ошибке
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Пробуем получить число (без верхнего лимита — админ решает сам)
    try:
        delay_seconds = int(message.text.strip())
        if delay_seconds < 0:
            raise ValueError("Значение должно быть неотрицательным")
    except (ValueError, TypeError):
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Ошибка валидации — редактируем сообщение-инструкцию
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text=(
                        f"❌ <b>Ошибка:</b> введите неотрицательное число.\n\n"
                        f"Введите время автоудаления в секундах:"
                    ),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите неотрицательное число")
        return

    # Очищаем состояние
    await state.clear()

    # Обновляем настройки
    await _filter_manager.update_settings(chat_id, session, flood_notification_delete_delay=delay_seconds)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Автоудаление уведомления через: {delay_seconds} сек" if delay_seconds else "✅ Уведомления не будут удаляться автоматически"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
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
# НАСТРОЙКИ "ЛЮБЫЕ СООБЩЕНИЯ": ЛИМИТ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flanylim:-?\d+$"))
async def request_flood_any_limit_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод лимита для детекции любых сообщений.

    Callback: cf:flanylim:{chat_id}

    Лимит — максимальное количество любых сообщений подряд
    за временное окно. При превышении срабатывает фильтр.

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст
    """
    # Парсим chat_id из callback данных
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем текущие настройки группы
    settings = await _filter_manager.get_or_create_settings(chat_id, session)
    # Получаем текущий лимит
    current_limit = settings.flood_any_max_messages or 5

    # Формируем текст инструкции
    text = (
        f"📢 <b>Лимит сообщений (любые сообщения)</b>\n\n"
        f"Введите максимальное количество любых сообщений подряд,\n"
        f"после которого сработает фильтр.\n\n"
        f"<b>Текущее значение:</b> {current_limit}\n\n"
        f"Введите положительное число (минимум 2):"
    )

    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние FSM
    await state.set_state(FloodAnySettingsStates.waiting_any_limit)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodAnySettingsStates.waiting_any_limit)
async def process_flood_any_limit_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод лимита для детекции любых сообщений.

    Проверяет что введено положительное число (минимум 2).
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Кнопка отмены для редактирования сообщения при ошибке
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Пробуем преобразовать в число
    try:
        # Извлекаем и проверяем число
        limit = int(message.text.strip())
        # Проверяем минимум (без верхнего лимита — админ решает сам)
        if limit < 2:
            raise ValueError("Значение должно быть минимум 2")
    except (ValueError, TypeError):
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Ошибка валидации — редактируем сообщение-инструкцию вместо нового сообщения
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text=(
                        f"❌ <b>Ошибка:</b> введите число (минимум 2).\n\n"
                        f"Введите лимит сообщений:"
                    ),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        # Fallback если не получилось отредактировать
        await message.answer("❌ Введите число (минимум 2)")
        return

    # Очищаем состояние FSM
    await state.clear()

    # Обновляем настройки в БД
    await _filter_manager.update_settings(chat_id, session, flood_any_max_messages=limit)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем подтверждение
    confirm_text = f"✅ Лимит сообщений установлен: {limit}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Редактируем сообщение-инструкцию
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
# НАСТРОЙКИ "ЛЮБЫЕ СООБЩЕНИЯ": ВРЕМЕННОЕ ОКНО
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flanywin:-?\d+$"))
async def request_flood_any_window_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод временного окна для детекции любых сообщений.

    Callback: cf:flanywin:{chat_id}

    Временное окно — период в секундах за который считаются сообщения.
    Если за это время пользователь отправит больше лимита — фильтр сработает.

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст
    """
    # Парсим chat_id из callback данных
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем текущие настройки группы
    settings = await _filter_manager.get_or_create_settings(chat_id, session)
    # Получаем текущее временное окно
    current_window = settings.flood_any_time_window or 10

    # Формируем текст инструкции
    text = (
        f"⏱️ <b>Временное окно (любые сообщения)</b>\n\n"
        f"Введите временное окно в секундах.\n\n"
        f"Если пользователь отправит больше лимита сообщений\n"
        f"за это время — сработает фильтр.\n\n"
        f"<b>Текущее значение:</b> {current_window} сек\n\n"
        f"Введите положительное число в секундах:"
    )

    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние FSM
    await state.set_state(FloodAnySettingsStates.waiting_any_window)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodAnySettingsStates.waiting_any_window)
async def process_flood_any_window_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод временного окна для детекции любых сообщений.

    Проверяет что введено положительное число.
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Кнопка отмены для редактирования сообщения при ошибке
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Пробуем преобразовать в число
    try:
        # Извлекаем и проверяем число
        window = int(message.text.strip())
        # Проверяем что число положительное (без верхнего лимита — админ решает сам)
        if window < 1:
            raise ValueError("Значение должно быть положительным")
    except (ValueError, TypeError):
        # Удаляем сообщение пользователя чтобы не засорять чат
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        # Ошибка валидации — редактируем сообщение-инструкцию вместо нового сообщения
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text=(
                        f"❌ <b>Ошибка:</b> введите положительное число.\n\n"
                        f"Введите временное окно в секундах:"
                    ),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        # Fallback если не получилось отредактировать
        await message.answer("❌ Введите положительное число")
        return

    # Очищаем состояние FSM
    await state.clear()

    # Обновляем настройки в БД
    await _filter_manager.update_settings(chat_id, session, flood_any_time_window=window)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем подтверждение
    confirm_text = f"✅ Временное окно установлено: {window} сек"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Редактируем сообщение-инструкцию
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
# ВВОД ТЕКСТА ПРЕДУПРЕЖДЕНИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:flwt:-?\d+$"))
async def request_flood_warn_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Запрашивает ввод текста для предупреждения при флуде.

    Callback: cf:flwt:{chat_id}

    Этот текст отправляется когда действие = "предупреждение".

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст
    """
    # Парсим chat_id из callback данных
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем текущие настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)
    # Получаем текущий текст или "Не задан"
    current_text = settings.flood_warn_text or "Не задан"

    # Формируем текст инструкции
    text = (
        f"📝 <b>Текст при предупреждении за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление,\n"
        f"когда пользователь получит предупреждение за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%, %time%"
    )

    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Сохраняем chat_id и message_id в состояние FSM
    await state.set_state(FloodTextStates.waiting_warn_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@settings_handler_router.message(FloodTextStates.waiting_warn_text)
async def process_flood_warn_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Обрабатывает ввод текста предупреждения для антифлуда.

    Если введён "-" — сбрасывает текст на дефолтный.
    """
    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    # Очищаем состояние FSM
    await state.clear()

    # Получаем введённый текст
    text = message.text.strip() if message.text else ""

    # Если "-" — сбрасываем на NULL
    if text == "-":
        text = None

    # Обновляем настройки в БД
    await _filter_manager.update_settings(chat_id, session, flood_warn_text=text)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Формируем подтверждение
    confirm_text = f"✅ Текст при предупреждении сохранён" if text else "✅ Текст при предупреждении сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    # Редактируем сообщение-инструкцию
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
# МОДУЛЬ УДАЛЕНИЯ СООБЩЕНИЙ
# ============================================================

@settings_handler_router.callback_query(F.data.regexp(r"^cf:cleanup:-?\d+$"))
async def cleanup_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек модуля удаления сообщений.

    Callback: cf:cleanup:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Формируем статусы
    commands_status = "✅ Вкл" if settings.delete_user_commands else "❌ Выкл"
    system_status = "✅ Вкл" if settings.delete_system_messages else "❌ Выкл"

    text = (
        f"🗑️ <b>Удаление сообщений</b>\n\n"
        f"Этот модуль автоматически удаляет лишние сообщения в группе.\n\n"
        f"<b>Команды от пользователей:</b> {commands_status}\n"
        f"Удаляет команды типа /start, /help, /settings от обычных пользователей.\n"
        f"Команды от админов выполняются, но тоже удаляются.\n\n"
        f"<b>Системные сообщения:</b> {system_status}\n"
        f"Удаляет сообщения о входе/выходе участников, закреплённые и т.д."
    )

    # Создаём клавиатуру
    cmd_emoji = "✅" if settings.delete_user_commands else "❌"
    sys_emoji = "✅" if settings.delete_system_messages else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Удаление команд
            [
                InlineKeyboardButton(
                    text=f"📝 Команды {cmd_emoji}",
                    callback_data=f"cf:t:delcmd:{chat_id}"
                )
            ],
            # Удаление системных сообщений
            [
                InlineKeyboardButton(
                    text=f"⚙️ Системные {sys_emoji}",
                    callback_data=f"cf:t:delsys:{chat_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"cf:s:{chat_id}"
                )
            ]
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_handler_router.callback_query(F.data.regexp(r"^cf:t:delcmd:-?\d+$"))
async def toggle_delete_user_commands(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление команд от пользователей.

    Callback: cf:t:delcmd:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.delete_user_commands
    await _filter_manager.update_settings(chat_id, session, delete_user_commands=new_value)

    # Возвращаемся в меню
    callback.data = f"cf:cleanup:{chat_id}"
    await cleanup_settings_menu(callback, session)

    status_text = "включено" if new_value else "выключено"
    await callback.answer(f"Удаление команд {status_text}")


@settings_handler_router.callback_query(F.data.regexp(r"^cf:t:delsys:-?\d+$"))
async def toggle_delete_system_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление системных сообщений.

    Callback: cf:t:delsys:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.delete_system_messages
    await _filter_manager.update_settings(chat_id, session, delete_system_messages=new_value)

    # Возвращаемся в меню
    callback.data = f"cf:cleanup:{chat_id}"
    await cleanup_settings_menu(callback, session)

    status_text = "включено" if new_value else "выключено"
    await callback.answer(f"Удаление системных сообщений {status_text}")
