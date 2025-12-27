# ============================================================
# SETTINGS - НАСТРОЙКИ ФИЛЬТРА СЛОВ
# ============================================================
# Этот модуль содержит хендлеры для настроек фильтра слов:
# - word_filter_settings_menu: меню настроек с 3 категориями
# - word_filter_action_menu: выбор действия для фильтра слов
# - set_word_filter_action: установка действия
# - category_action_menu: выбор действия для категории
# - set_category_action: установка действия для категории
# - request_duration_input: запрос ввода времени
# - process_duration_input: обработка ввода времени
# - toggle_word_normalizer: переключение нормализатора
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
    create_word_filter_settings_menu,
    create_word_filter_action_menu,
    create_category_action_menu,
    create_content_filter_settings_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и helpers
from bot.handlers.content_filter.common import DurationInputStates, parse_duration

# Создаём роутер для настроек
settings_router = Router(name='word_filter_settings')


# ============================================================
# МЕНЮ НАСТРОЕК ФИЛЬТРА СЛОВ (3 КАТЕГОРИИ)
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:wfs:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# МЕНЮ ДЕЙСТВИЯ ДЛЯ ФИЛЬТРА СЛОВ
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:wact:-?\d+$"))
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

    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@settings_router.callback_query(F.data.regexp(r"^cf:wact:\w+:-?\d+$"))
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

    await filter_manager.update_settings(chat_id, session, word_filter_action=new_action)

    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# ВЫБОР ДЕЙСТВИЯ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)a:-?\d+$"))
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
    mute_text_field_map = {
        'sw': 'simple_words_mute_text',
        'hw': 'harmful_words_mute_text',
        'ow': 'obfuscated_words_mute_text'
    }
    notification_delay_field_map = {
        'sw': 'simple_words_notification_delete_delay',
        'hw': 'harmful_words_notification_delete_delay',
        'ow': 'obfuscated_words_notification_delete_delay'
    }
    category_names = {
        'sw': 'Простые слова',
        'hw': 'Вредные слова',
        'ow': 'Обфускация'
    }

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Получаем текущие значения
    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    mute_text = getattr(settings, mute_text_field_map[category], None)
    notification_delay = getattr(settings, notification_delay_field_map[category], None)

    # Формируем текст
    text = (
        f"⚡ <b>Действие: {category_names[category]}</b>\n\n"
        f"Выберите действие при срабатывании:\n"
        f"• 🗑️ Удалить — только удалить сообщение\n"
        f"• 🔇 Мут — удалить + мут на время\n"
        f"• 🚫 Бан — удалить + бан\n\n"
        f"📝 Текст мута — своё уведомление (%user%, %time%)\n"
        f"⏰ Удалять уведомление — через сколько секунд\n\n"
        f"⏱️ — задать время вручную\n"
        f"Форматы: 30s, 5min, 1h, 1d, 1m"
    )

    # Клавиатура
    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        mute_text, notification_delay
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УСТАНОВКА ДЕЙСТВИЯ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)a:(delete|mute|ban):-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
    await filter_manager.update_settings(chat_id, session, **update_data)

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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

@settings_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)(t|bt):-?\d+$"))
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


@settings_router.message(DurationInputStates.waiting_for_duration)
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
    duration_minutes = parse_duration(message.text)
    if duration_minutes is None:
        await message.answer(
            f"❌ Неверный формат времени\n\n"
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
    await filter_manager.update_settings(
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
# ПЕРЕКЛЮЧАТЕЛЬ НОРМАЛИЗАТОРА ДЛЯ СЛОВ
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:wnorm:-?\d+$"))
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

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем значение
    new_value = not settings.word_filter_normalize

    await filter_manager.update_settings(chat_id, session, word_filter_normalize=new_value)

    # Возвращаемся в меню настроек
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
