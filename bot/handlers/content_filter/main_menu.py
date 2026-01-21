# ============================================================
# MAIN MENU - ГЛАВНОЕ МЕНЮ CONTENT FILTER
# ============================================================
# Этот модуль содержит хендлеры главного меню:
# - content_filter_main_menu: показ главного меню
# - toggle_module: включение/выключение всего модуля
# - settings_menu: меню настроек подмодулей
# - toggle_submodule: переключение подмодулей
# - sensitivity_menu, set_sensitivity: чувствительность антискама
# - action_menu, set_action: действие по умолчанию
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery, Message
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError
# Импортируем FSM
from aiogram.fsm.context import FSMContext

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем FSM состояния
from bot.handlers.content_filter.common import (
    AddCrossMessagePatternStates,
    CrossMessageNotificationStates,
    # Новые состояния для кастомного ввода значений
    CrossMessageWindowInputStates,
    CrossMessageThresholdInputStates,
    CrossMessageCustomScoreStates,
    CrossMessageNotificationDelayInputStates,
    CrossMessageThresholdMuteInputStates,
    # Функции парсинга
    parse_delay_seconds,
    parse_duration,
)

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_content_filter_main_menu,
    create_content_filter_settings_menu,
    create_sensitivity_menu,
    create_action_menu,
    create_word_filter_settings_menu,
    # Кросс-сообщение детекция
    create_cross_message_settings_menu,
    create_cross_message_window_menu,
    create_cross_message_threshold_menu,
    create_cross_message_action_menu,
    # Кросс-сообщение паттерны (NEW!)
    create_cross_message_patterns_menu,
    create_cross_message_patterns_list_menu,
    create_cross_message_pattern_detail_menu,
    create_cross_message_pattern_type_menu,
    create_cross_message_cancel_input_menu,
    create_cross_message_delete_confirm_menu,
    # Кросс-сообщение пороги баллов (CrossMessageThreshold)
    create_cross_message_score_thresholds_menu,
    create_cross_message_threshold_edit_menu,
    create_cross_message_add_threshold_menu,
    create_cross_message_add_threshold_max_menu,
    create_cross_message_add_threshold_action_menu,
    # Кросс-сообщение уведомления
    create_cross_message_notifications_menu,
    create_cross_message_notification_delay_menu,
    create_cross_message_notification_text_back_menu,
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger

# Создаём роутер для главного меню
main_menu_router = Router(name='content_filter_main_menu')


# ============================================================
# ГЛАВНОЕ МЕНЮ МОДУЛЯ
# ============================================================

@main_menu_router.callback_query(F.data.startswith("cf:m:"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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

    # DEBUG: логируем клавиатуру
    print(f"[DEBUG] cf:m: keyboard rows: {len(keyboard.inline_keyboard)}", flush=True)
    for i, row in enumerate(keyboard.inline_keyboard):
        print(f"[DEBUG] Row {i}: {[btn.text for btn in row]}", flush=True)

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

@main_menu_router.callback_query(F.data.startswith("cf:t:on:") | F.data.startswith("cf:t:off:"))
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
    await filter_manager.toggle_module(chat_id, enabled, session)

    # Показываем обновлённое главное меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)
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

@main_menu_router.callback_query(F.data.startswith("cf:s:"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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

@main_menu_router.callback_query(F.data.startswith("cf:t:wf:") | F.data.startswith("cf:t:sc:") |
                                 F.data.startswith("cf:t:fl:") | F.data.startswith("cf:t:log:") |
                                 F.data.startswith("cf:t:sw:") | F.data.startswith("cf:t:hw:") |
                                 F.data.startswith("cf:t:ow:") | F.data.startswith("cf:t:cm:"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
        'ow': 'obfuscated_words_enabled',
        # Кросс-сообщение детекция
        'cm': 'cross_message_enabled'
    }

    # Категории которые возвращают в меню настроек слов
    word_categories = {'sw', 'hw', 'ow'}

    field_name = field_map.get(submodule)
    if field_name:
        # Получаем текущее значение и инвертируем
        current_value = getattr(settings, field_name, True)
        new_value = not current_value

        # Обновляем
        await filter_manager.update_settings(chat_id, session, **{field_name: new_value})

    # Показываем обновлённое меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# МЕНЮ ЧУВСТВИТЕЛЬНОСТИ
# ============================================================

@main_menu_router.callback_query(F.data.regexp(r"^cf:sens:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@main_menu_router.callback_query(F.data.regexp(r"^cf:sens:\d+:-?\d+$"))
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
    await filter_manager.update_settings(chat_id, session, scam_sensitivity=value)

    # Показываем обновлённое меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# МЕНЮ ДЕЙСТВИЯ ПО УМОЛЧАНИЮ
# ============================================================

@main_menu_router.callback_query(F.data.regexp(r"^cf:act:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@main_menu_router.callback_query(F.data.regexp(r"^cf:act:\w+:-?\d+$"))
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
    await filter_manager.update_settings(chat_id, session, default_action=action)

    # Показываем обновлённое меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# КРОСС-СООБЩЕНИЕ ДЕТЕКЦИЯ - НАСТРОЙКИ
# ============================================================

@main_menu_router.callback_query(F.data.startswith("cf:cms:"))
async def cross_message_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек кросс-сообщение детекции.

    Callback: cf:cms:{chat_id}

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
    enabled_status = "✅ Включено" if getattr(settings, 'cross_message_enabled', False) else "❌ Выключено"
    text = (
        f"📊 <b>Кросс-сообщение детекция</b>\n\n"
        f"Статус: {enabled_status}\n\n"
        f"Накапливает баллы паттернов через несколько сообщений.\n"
        f"Когда накопленный скор превышает порог — применяется действие.\n\n"
        f"Это позволяет ловить спаммеров которые разбивают спам на части."
    )

    # Клавиатура
    keyboard = create_cross_message_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmw:"))
async def cross_message_window_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора временного окна.

    Callback: cf:cmw:{chat_id} или cf:cmw:s:{seconds}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст (для очистки при возврате)
    """
    # Очищаем FSM state если был в режиме ввода
    await state.clear()

    parts = callback.data.split(":")

    # Проверяем это выбор или показ меню
    if len(parts) == 5 and parts[2] == 's':
        # Формат: cf:cmw:s:{seconds}:{chat_id} — устанавливаем значение
        seconds = int(parts[3])
        chat_id = int(parts[4])

        # Обновляем настройки
        await filter_manager.update_settings(chat_id, session, cross_message_window_seconds=seconds)

        await callback.answer(f"Окно установлено: {seconds // 3600}ч" if seconds >= 3600 else f"Окно: {seconds // 60}мин")
    else:
        # Формат: cf:cmw:{chat_id} — показываем меню
        chat_id = int(parts[2])

    # Получаем настройки и показываем меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⏱️ <b>Временное окно накопления</b>\n\n"
        f"За какое время накапливать баллы.\n"
        f"После истечения — счётчик сбрасывается."
    )

    keyboard = create_cross_message_window_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmt:"))
async def cross_message_threshold_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора порога срабатывания.

    Callback: cf:cmt:{chat_id} или cf:cmt:s:{value}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст (для очистки при возврате)
    """
    # Очищаем FSM state если был в режиме ввода
    await state.clear()

    parts = callback.data.split(":")

    # Проверяем это выбор или показ меню
    if len(parts) == 5 and parts[2] == 's':
        # Формат: cf:cmt:s:{value}:{chat_id} — устанавливаем значение
        value = int(parts[3])
        chat_id = int(parts[4])

        # Обновляем настройки
        await filter_manager.update_settings(chat_id, session, cross_message_threshold=value)

        await callback.answer(f"Порог установлен: {value} баллов")
    else:
        # Формат: cf:cmt:{chat_id} — показываем меню
        chat_id = int(parts[2])

    # Получаем настройки и показываем меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"📊 <b>Порог срабатывания</b>\n\n"
        f"Сколько накопленных баллов нужно для применения действия.\n"
        f"Пример: 3 сообщения по 35 баллов = 105 → превышает порог 100."
    )

    keyboard = create_cross_message_threshold_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cma:"))
async def cross_message_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия.

    Callback: cf:cma:{chat_id} или cf:cma:s:{action}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    parts = callback.data.split(":")

    # Проверяем это выбор или показ меню
    if len(parts) == 5 and parts[2] == 's':
        # Формат: cf:cma:s:{action}:{chat_id} — устанавливаем значение
        action = parts[3]
        chat_id = int(parts[4])

        # Обновляем настройки
        await filter_manager.update_settings(chat_id, session, cross_message_action=action)

        action_names = {'mute': 'Мут', 'ban': 'Бан', 'kick': 'Кик'}
        await callback.answer(f"Действие: {action_names.get(action, action)}")
    else:
        # Формат: cf:cma:{chat_id} — показываем меню
        chat_id = int(parts[2])

    # Получаем настройки и показываем меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"⚡ <b>Действие при превышении порога</b>\n\n"
        f"Что делать когда накопленный скор превышает порог."
    )

    keyboard = create_cross_message_action_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# КРОСС-СООБЩЕНИЕ: КАСТОМНЫЙ ВВОД ЗНАЧЕНИЙ
# ============================================================
# Хендлеры для ввода произвольных значений (вместо хардкоженных)
# ============================================================

@main_menu_router.callback_query(F.data.startswith("cf:cmwc:"))
async def cross_message_window_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для кастомного ввода временного окна.

    Callback: cf:cmwc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSM контекст
        session: Сессия БД
    """
    # Парсим chat_id из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления в FSM данных
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    # Устанавливаем состояние ожидания ввода
    await state.set_state(CrossMessageWindowInputStates.waiting_for_window)

    # Показываем инструкцию с клавиатурой отмены
    text = (
        f"⏱️ <b>Введите временное окно</b>\n\n"
        f"Укажите время в одном из форматов:\n"
        f"• <code>3600</code> — секунды\n"
        f"• <code>30min</code> — минуты\n"
        f"• <code>2h</code> — часы\n"
        f"• <code>1d</code> — дни\n\n"
        f"Пример: <code>4h</code> = 4 часа"
    )

    # Клавиатура с кнопкой назад
    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmw')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.message(CrossMessageWindowInputStates.waiting_for_window)
async def cross_message_window_custom_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает введённое значение временного окна.

    Args:
        message: Сообщение с введённым значением
        state: FSM контекст
        session: Сессия БД
    """
    # Проверка на команду — очищаем FSM и игнорируем
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим введённое значение
    input_text = message.text.strip()
    seconds = parse_delay_seconds(input_text)

    if seconds is None or seconds < 60:
        # Ошибка парсинга или слишком маленькое значение
        await message.answer(
            "❌ Неверный формат. Введите число в секундах или с суффиксом:\n"
            "<code>30min</code>, <code>2h</code>, <code>1d</code>\n\n"
            "Минимум: 60 секунд (1 минута)"
        , parse_mode="HTML")
        return

    # Ограничение: максимум 365 дней (для временного окна)
    max_seconds = 365 * 24 * 3600  # 365 дней
    if seconds > max_seconds:
        await message.answer(
            f"❌ Слишком большое значение. Максимум: 365 дней"
        )
        return

    # Обновляем настройки
    await filter_manager.update_settings(chat_id, session, cross_message_window_seconds=seconds)

    # Удаляем сообщение с запросом ввода (State Leak fix)
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя с введённым значением
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сбрасываем FSM
    await state.clear()

    # Формируем текст подтверждения
    if seconds >= 86400:
        time_str = f"{seconds // 86400}д"
    elif seconds >= 3600:
        time_str = f"{seconds // 3600}ч"
    elif seconds >= 60:
        time_str = f"{seconds // 60}мин"
    else:
        time_str = f"{seconds}сек"

    await message.answer(f"✅ Временное окно установлено: {time_str} ({seconds} сек)")

    # Показываем обновлённое меню настроек
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    keyboard = create_cross_message_settings_menu(chat_id, settings)
    text = _get_cross_message_settings_text(settings)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.callback_query(F.data.startswith("cf:cmtc:"))
async def cross_message_threshold_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для кастомного ввода порога срабатывания.

    Callback: cf:cmtc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSM контекст
        session: Сессия БД
    """
    # Парсим chat_id из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления в FSM данных
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    # Устанавливаем состояние ожидания ввода
    await state.set_state(CrossMessageThresholdInputStates.waiting_for_threshold)

    # Показываем инструкцию
    text = (
        f"📊 <b>Введите порог срабатывания</b>\n\n"
        f"Укажите количество баллов (число от 10 до 10000).\n\n"
        f"Пример: <code>150</code>"
    )

    # Клавиатура с кнопкой назад
    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmt')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.message(CrossMessageThresholdInputStates.waiting_for_threshold)
async def cross_message_threshold_custom_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает введённое значение порога.

    Args:
        message: Сообщение с введённым значением
        state: FSM контекст
        session: Сессия БД
    """
    # Проверка на команду — очищаем FSM и игнорируем
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим введённое значение
    input_text = message.text.strip()

    try:
        value = int(input_text)
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return

    # Проверяем диапазон
    if value < 10:
        await message.answer("❌ Минимальный порог: 10 баллов")
        return
    if value > 10000:
        await message.answer("❌ Максимальный порог: 10000 баллов")
        return

    # Обновляем настройки
    await filter_manager.update_settings(chat_id, session, cross_message_threshold=value)

    # Удаляем сообщение с запросом ввода (State Leak fix)
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя с введённым значением
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сбрасываем FSM
    await state.clear()

    await message.answer(f"✅ Порог срабатывания установлен: {value} баллов")

    # Показываем обновлённое меню настроек
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    keyboard = create_cross_message_settings_menu(chat_id, settings)
    text = _get_cross_message_settings_text(settings)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.callback_query(F.data.startswith("cf:cmstamc:"))
async def cross_message_add_threshold_min_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для кастомного ввода минимального скора порога.

    Callback: cf:cmstamc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSM контекст
        session: Сессия БД
    """
    # Парсим chat_id из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления в FSM данных
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    # Устанавливаем состояние ожидания ввода
    await state.set_state(CrossMessageCustomScoreStates.waiting_for_min_score)

    # Показываем инструкцию
    text = (
        f"📊 <b>Введите минимальный скор</b>\n\n"
        f"Порог начнёт работать когда скор >= этого значения.\n\n"
        f"Пример: <code>100</code>"
    )

    # Клавиатура с кнопкой назад
    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmsta')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.message(CrossMessageCustomScoreStates.waiting_for_min_score)
async def cross_message_add_threshold_min_custom_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает введённое значение минимального скора.

    Args:
        message: Сообщение с введённым значением
        state: FSM контекст
        session: Сессия БД
    """
    # Проверка на команду — очищаем FSM и игнорируем
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим введённое значение
    input_text = message.text.strip()

    try:
        min_score = int(input_text)
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return

    # Проверяем диапазон
    if min_score < 1:
        await message.answer("❌ Минимальное значение: 1")
        return
    if min_score > 10000:
        await message.answer("❌ Максимальное значение: 10000")
        return

    # Удаляем сообщение с запросом ввода (State Leak fix)
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя с введённым значением
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сохраняем min_score и очищаем FSM
    await state.clear()

    # Показываем меню выбора максимального скора (без отдельного подтверждения)
    keyboard = create_cross_message_add_threshold_max_menu(chat_id, min_score)
    text = (
        f"📊 <b>Выберите максимальный скор</b>\n\n"
        f"Минимальный: {min_score}\n\n"
        f"Выберите верхнюю границу диапазона или «∞ (без лимита)»."
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.callback_query(F.data.startswith("cf:cmstaxc:"))
async def cross_message_add_threshold_max_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для кастомного ввода максимального скора порога.

    Callback: cf:cmstaxc:{chat_id}:{min_score}

    Args:
        callback: CallbackQuery
        state: FSM контекст
        session: Сессия БД
    """
    # Парсим данные из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    min_score = int(parts[3])

    # Сохраняем в FSM данных (включая prompt для удаления)
    await state.update_data(
        chat_id=chat_id,
        min_score=min_score,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    # Устанавливаем состояние ожидания ввода
    await state.set_state(CrossMessageCustomScoreStates.waiting_for_max_score)

    # Показываем инструкцию
    text = (
        f"📊 <b>Введите максимальный скор</b>\n\n"
        f"Минимальный скор: {min_score}\n\n"
        f"Введите верхнюю границу диапазона (больше {min_score}).\n"
        f"Пример: <code>{min_score + 100}</code>"
    )

    # Клавиатура с кнопкой назад
    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmsta')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.message(CrossMessageCustomScoreStates.waiting_for_max_score)
async def cross_message_add_threshold_max_custom_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает введённое значение максимального скора.

    Args:
        message: Сообщение с введённым значением
        state: FSM контекст
        session: Сессия БД
    """
    # Проверка на команду — очищаем FSM и игнорируем
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    min_score = data.get('min_score')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id or min_score is None:
        await message.answer("❌ Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим введённое значение
    input_text = message.text.strip()

    try:
        max_score = int(input_text)
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return

    # Проверяем диапазон
    if max_score <= min_score:
        await message.answer(f"❌ Максимальный скор должен быть больше минимального ({min_score})")
        return
    if max_score > 100000:
        await message.answer("❌ Слишком большое значение. Максимум: 100000")
        return

    # Удаляем сообщение с запросом ввода (State Leak fix)
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя с введённым значением
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сбрасываем FSM
    await state.clear()

    # Показываем меню выбора действия (без отдельного подтверждения)
    keyboard = create_cross_message_add_threshold_action_menu(chat_id, min_score, max_score)
    text = (
        f"📊 <b>Выберите действие для порога</b>\n\n"
        f"Диапазон: {min_score} — {max_score} баллов"
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


def _get_cross_message_settings_text(settings) -> str:
    """
    Формирует текст меню настроек кросс-сообщений.

    Args:
        settings: Объект ContentFilterSettings

    Returns:
        str: Текст для сообщения
    """
    # Статус
    status = "✅ Включено" if settings.cross_message_enabled else "❌ Выключено"

    # Форматируем временное окно
    window_sec = settings.cross_message_window_seconds or 7200
    if window_sec >= 86400:
        window_str = f"{window_sec // 86400}д"
    elif window_sec >= 3600:
        window_str = f"{window_sec // 3600}ч"
    else:
        window_str = f"{window_sec // 60}мин"

    # Порог
    threshold = settings.cross_message_threshold or 100

    # Действие
    action_map = {'mute': 'Мут', 'ban': 'Бан', 'kick': 'Кик'}
    action = action_map.get(settings.cross_message_action or 'mute', 'Мут')

    text = (
        f"📊 <b>Кросс-сообщение детекция</b>\n\n"
        f"Накапливает баллы через несколько сообщений.\n"
        f"Ловит спам, разбитый на части.\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Окно:</b> {window_str}\n"
        f"<b>Порог:</b> {threshold} баллов\n"
        f"<b>Действие:</b> {action}"
    )

    return text


# ============================================================
# КРОСС-СООБЩЕНИЕ ПАТТЕРНЫ - УПРАВЛЕНИЕ
# ============================================================
# Хендлеры для работы с ОТДЕЛЬНЫМИ паттернами кросс-сообщений
# (НЕ паттерны разделов!)
# ============================================================

# Импортируем сервис кросс-сообщений для работы с паттернами
from bot.services.content_filter.cross_message_service import (
    get_cross_message_service,
    create_cross_message_service,
    CrossMessageService
)

# Импортируем Redis для создания сервиса (если не инициализирован)
from bot.handlers.group_message_coordinator import redis


@main_menu_router.callback_query(F.data.startswith("cf:cmp:"))
async def cross_message_patterns_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает главное меню управления паттернами кросс-сообщений.

    Callback: cf:cmp:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем или создаём сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    # Получаем количество паттернов
    patterns_count = 0
    active_count = 0
    if service:
        all_patterns = await service.get_patterns(chat_id, session, active_only=False)
        patterns_count = len(all_patterns)
        active_count = len([p for p in all_patterns if p.is_active])

    # Формируем текст
    text = (
        f"📝 <b>Паттерны кросс-сообщений</b>\n\n"
        f"Всего: {patterns_count} | Активных: {active_count}\n\n"
        f"Эти паттерны используются для накопления скора.\n"
        f"Они НЕ связаны с паттернами разделов!\n\n"
        f"<b>Веса должны быть НИЖЕ</b> чем в разделах,\n"
        f"чтобы обычные пользователи не набирали баллы."
    )

    # Клавиатура
    keyboard = create_cross_message_patterns_menu(chat_id, patterns_count, active_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmpl:"))
async def cross_message_patterns_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список паттернов кросс-сообщений с пагинацией.

    Callback: cf:cmpl:{chat_id}:{page}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Получаем все паттерны (включая неактивные)
    patterns = await service.get_patterns(chat_id, session, active_only=False)

    # Пагинация
    per_page = 10
    total_pages = max(1, (len(patterns) + per_page - 1) // per_page)

    # Ограничиваем страницу
    page = max(0, min(page, total_pages - 1))

    # Получаем паттерны для текущей страницы
    start = page * per_page
    end = start + per_page
    page_patterns = patterns[start:end]

    # Формируем текст
    if not patterns:
        text = (
            f"📝 <b>Паттерны кросс-сообщений</b>\n\n"
            f"Список пуст.\n\n"
            f"Добавьте паттерны для накопления скора."
        )
    else:
        lines = [f"📝 <b>Паттерны кросс-сообщений</b>\n"]
        lines.append(f"Страница {page + 1}/{total_pages}\n")

        for i, p in enumerate(page_patterns, start=start + 1):
            # Статус активности
            status = "✅" if p.is_active else "⏸️"
            # Тип паттерна
            type_emoji = {"word": "📖", "phrase": "📝", "regex": "🔣"}.get(p.pattern_type, "📝")
            # Формируем строку
            lines.append(
                f"{i}. {status} {type_emoji} <code>{p.pattern[:30]}{'...' if len(p.pattern) > 30 else ''}</code> "
                f"[{p.weight}] (x{p.triggers_count})"
            )

        lines.append(f"\n<i>Нажмите на номер для управления</i>")
        text = "\n".join(lines)

    # Клавиатура
    keyboard = create_cross_message_patterns_list_menu(chat_id, page, total_pages)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmpa:"))
async def cross_message_pattern_add_start(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Начинает процесс добавления паттерна — показывает выбор типа.

    Callback: cf:cmpa:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Формируем текст
    text = (
        f"📝 <b>Добавление паттерна</b>\n\n"
        f"Выберите тип паттерна:\n\n"
        f"📝 <b>Фраза</b> — ищет подстроку в тексте\n"
        f"📖 <b>Слово</b> — ищет только как отдельное слово\n"
        f"🔣 <b>Regex</b> — регулярное выражение"
    )

    # Клавиатура выбора типа
    keyboard = create_cross_message_pattern_type_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmpd:"))
async def cross_message_patterns_delete_confirm(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления всех паттернов.

    Callback: cf:cmpd:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Формируем текст
    text = (
        f"⚠️ <b>Удаление всех паттернов</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ паттерны\n"
        f"кросс-сообщений для этой группы?\n\n"
        f"<b>Это действие нельзя отменить!</b>"
    )

    # Клавиатура подтверждения
    keyboard = create_cross_message_delete_confirm_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmpdc:"))
async def cross_message_patterns_delete_all(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все паттерны кросс-сообщений.

    Callback: cf:cmpdc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Получаем все паттерны и удаляем
    patterns = await service.get_patterns(chat_id, session, active_only=False)
    deleted_count = 0
    for p in patterns:
        await service.delete_pattern(p.id, session)
        deleted_count += 1

    await callback.answer(f"Удалено паттернов: {deleted_count}")

    # Возвращаем в меню паттернов
    # Формируем текст
    text = (
        f"📝 <b>Паттерны кросс-сообщений</b>\n\n"
        f"Всего: 0 | Активных: 0\n\n"
        f"Все паттерны удалены."
    )

    keyboard = create_cross_message_patterns_menu(chat_id, 0, 0)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmpt:"))
async def cross_message_pattern_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает активность паттерна.

    Callback: cf:cmpt:{pattern_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим pattern_id
    parts = callback.data.split(":")
    pattern_id = int(parts[2])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Получаем паттерн
    pattern = await service.get_pattern_by_id(pattern_id, session)
    if not pattern:
        await callback.answer("Паттерн не найден", show_alert=True)
        return

    # Переключаем статус
    new_status = not pattern.is_active
    await service.toggle_pattern(pattern_id, new_status, session)

    status_text = "Включён" if new_status else "Выключен"
    await callback.answer(f"Паттерн {status_text}")

    # Обновляем клавиатуру
    keyboard = create_cross_message_pattern_detail_menu(pattern.chat_id, pattern_id, new_status)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmpx:"))
async def cross_message_pattern_delete(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет конкретный паттерн.

    Callback: cf:cmpx:{pattern_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим pattern_id
    parts = callback.data.split(":")
    pattern_id = int(parts[2])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Получаем паттерн (для chat_id)
    pattern = await service.get_pattern_by_id(pattern_id, session)
    if not pattern:
        await callback.answer("Паттерн не найден", show_alert=True)
        return

    chat_id = pattern.chat_id

    # Удаляем
    await service.delete_pattern(pattern_id, session)

    await callback.answer("Паттерн удалён")

    # Возвращаем в список
    # Получаем обновлённый список
    patterns = await service.get_patterns(chat_id, session, active_only=False)
    patterns_count = len(patterns)
    active_count = len([p for p in patterns if p.is_active])

    text = (
        f"📝 <b>Паттерны кросс-сообщений</b>\n\n"
        f"Всего: {patterns_count} | Активных: {active_count}\n\n"
        f"Паттерн удалён."
    )

    keyboard = create_cross_message_patterns_menu(chat_id, patterns_count, active_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# КРОСС-СООБЩЕНИЕ ПАТТЕРНЫ - FSM ВВОД
# ============================================================
# Обработчики для ввода паттернов через FSM
# ============================================================

@main_menu_router.callback_query(F.data.startswith("cf:cmpty:"))
async def cross_message_pattern_type_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает выбор типа паттерна и запрашивает ввод текста.

    Callback: cf:cmpty:{type}:{chat_id}
    где type = phrase | word | regex

    Args:
        callback: CallbackQuery
        state: FSMContext для хранения данных
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_type = parts[2]  # phrase, word, regex
    chat_id = int(parts[3])

    # Валидируем тип
    if pattern_type not in ('phrase', 'word', 'regex'):
        await callback.answer("Неверный тип паттерна", show_alert=True)
        return

    # Сохраняем данные в state
    await state.update_data(
        chat_id=chat_id,
        pattern_type=pattern_type,
        user_id=callback.from_user.id
    )

    # Переходим в состояние ожидания паттерна
    await state.set_state(AddCrossMessagePatternStates.waiting_for_pattern)

    # Формируем текст
    type_names = {'phrase': 'Фраза', 'word': 'Слово', 'regex': 'Regex'}
    type_hints = {
        'phrase': 'Будет искаться как подстрока в тексте.',
        'word': 'Будет искаться только как отдельное слово (с границами).',
        'regex': 'Регулярное выражение Python. Пример: пиш[ие]\\s*в\\s*л[с]'
    }

    text = (
        f"📝 <b>Ввод паттерна</b>\n\n"
        f"Тип: <b>{type_names.get(pattern_type, pattern_type)}</b>\n"
        f"<i>{type_hints.get(pattern_type, '')}</i>\n\n"
        f"Введите текст паттерна:"
    )

    # Клавиатура отмены
    keyboard = create_cross_message_cancel_input_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmpcan:"))
async def cross_message_pattern_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Отменяет ввод паттерна и возвращает в меню.

    Callback: cf:cmpcan:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Очищаем state
    await state.clear()

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    # Получаем количество паттернов
    patterns_count = 0
    active_count = 0
    if service:
        all_patterns = await service.get_patterns(chat_id, session, active_only=False)
        patterns_count = len(all_patterns)
        active_count = len([p for p in all_patterns if p.is_active])

    # Возвращаем в меню паттернов
    text = (
        f"📝 <b>Паттерны кросс-сообщений</b>\n\n"
        f"Всего: {patterns_count} | Активных: {active_count}\n\n"
        f"Ввод отменён."
    )

    keyboard = create_cross_message_patterns_menu(chat_id, patterns_count, active_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Отменено")


@main_menu_router.message(AddCrossMessagePatternStates.waiting_for_pattern)
async def cross_message_pattern_text_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Получает текст паттерна и запрашивает вес.

    Args:
        message: Сообщение от пользователя
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из state
    data = await state.get_data()
    chat_id = data.get('chat_id')
    pattern_type = data.get('pattern_type', 'phrase')

    if not chat_id:
        await message.answer("Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Получаем текст паттерна
    pattern_text = message.text.strip() if message.text else ""

    if not pattern_text:
        await message.answer("Паттерн не может быть пустым. Введите текст:")
        return

    # Проверяем длину
    if len(pattern_text) > 500:
        await message.answer("Паттерн слишком длинный (макс 500 символов). Введите короче:")
        return

    # Для regex — проверяем валидность
    if pattern_type == 'regex':
        import re
        try:
            re.compile(pattern_text)
        except re.error as e:
            await message.answer(f"Некорректное регулярное выражение:\n<code>{e}</code>\n\nВведите снова:", parse_mode="HTML")
            return

    # Сохраняем паттерн в state
    await state.update_data(pattern_text=pattern_text)

    # Переходим к вводу веса
    await state.set_state(AddCrossMessagePatternStates.waiting_for_weight)

    # Формируем текст
    text = (
        f"📝 <b>Ввод веса</b>\n\n"
        f"Паттерн: <code>{pattern_text[:100]}{'...' if len(pattern_text) > 100 else ''}</code>\n\n"
        f"Введите вес (от 1 до 100):\n\n"
        f"<i>Рекомендации:\n"
        f"• 5-10 — слабый сигнал (пиши в лс)\n"
        f"• 15-25 — средний сигнал (заработок)\n"
        f"• 30-50 — сильный сигнал (telegram каналы)</i>"
    )

    keyboard = create_cross_message_cancel_input_menu(chat_id)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.message(AddCrossMessagePatternStates.waiting_for_weight)
async def cross_message_pattern_weight_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Получает вес и сохраняет паттерн в БД.

    Args:
        message: Сообщение от пользователя
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из state
    data = await state.get_data()
    chat_id = data.get('chat_id')
    pattern_type = data.get('pattern_type', 'phrase')
    pattern_text = data.get('pattern_text')
    user_id = data.get('user_id')

    if not chat_id or not pattern_text:
        await message.answer("Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим вес
    weight_text = message.text.strip() if message.text else ""

    if not weight_text.isdigit():
        await message.answer("Вес должен быть числом. Введите от 1 до 100:")
        return

    weight = int(weight_text)

    if weight < 1 or weight > 100:
        await message.answer("Вес должен быть от 1 до 100. Введите снова:")
        return

    # Очищаем state
    await state.clear()

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await message.answer("Сервис недоступен. Попробуйте позже.")
        return

    # Сохраняем паттерн
    try:
        new_pattern = await service.add_pattern(
            chat_id=chat_id,
            pattern=pattern_text,
            weight=weight,
            pattern_type=pattern_type,
            created_by=user_id,
            session=session
        )

        if new_pattern:
            result_text = (
                f"✅ <b>Паттерн добавлен!</b>\n\n"
                f"Текст: <code>{pattern_text[:100]}{'...' if len(pattern_text) > 100 else ''}</code>\n"
                f"Тип: {pattern_type}\n"
                f"Вес: {weight}"
            )
        else:
            result_text = (
                f"⚠️ <b>Паттерн уже существует!</b>\n\n"
                f"Такой паттерн уже есть в базе."
            )

    except Exception as e:
        logger.error(f"[CrossMessagePatterns] Error adding pattern: {e}")
        result_text = f"❌ Ошибка при добавлении: {e}"

    # Получаем количество паттернов
    all_patterns = await service.get_patterns(chat_id, session, active_only=False)
    patterns_count = len(all_patterns)
    active_count = len([p for p in all_patterns if p.is_active])

    # Клавиатура меню
    keyboard = create_cross_message_patterns_menu(chat_id, patterns_count, active_count)

    await message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# КРОСС-СООБЩЕНИЕ: ПОРОГИ БАЛЛОВ (CrossMessageThreshold)
# ============================================================
# Хендлеры для управления порогами баллов с разными действиями
# ============================================================

# Импортируем модель CrossMessageThreshold
from bot.database.models_content_filter import CrossMessageThreshold


@main_menu_router.callback_query(F.data.startswith("cf:cmst:"))
async def cross_message_score_thresholds_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню порогов баллов кросс-сообщений.

    Callback: cf:cmst:{chat_id}

    Args:
        callback: CallbackQuery
        session: AsyncSession
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    # Получаем список порогов
    thresholds = []
    if service:
        thresholds = await service.get_thresholds(chat_id, session)

    # Формируем текст
    if thresholds:
        text = (
            f"📈 <b>Пороги баллов</b>\n\n"
            f"Настройте разные действия для разных диапазонов скора.\n\n"
            f"Всего порогов: {len(thresholds)}"
        )
    else:
        text = (
            f"📈 <b>Пороги баллов</b>\n\n"
            f"Пороги не настроены.\n\n"
            f"Будет использоваться общее действие из настроек.\n\n"
            f"Добавьте пороги для тонкой настройки:\n"
            f"• 100-149 баллов → мут 30 мин\n"
            f"• 150-199 баллов → мут 2 часа\n"
            f"• 200+ баллов → бан"
        )

    keyboard = create_cross_message_score_thresholds_menu(chat_id, thresholds)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmsta:"))
async def cross_message_add_threshold_start(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Начинает добавление порога — показывает выбор минимального скора.

    Callback: cf:cmsta:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст (для очистки при возврате)
    """
    # Очищаем FSM state если был в режиме ввода
    await state.clear()

    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"📈 <b>Добавление порога</b>\n\n"
        f"Шаг 1/3: Выберите <b>минимальный</b> скор.\n\n"
        f"Порог сработает когда накопленный скор\n"
        f"достигнет этого значения."
    )

    keyboard = create_cross_message_add_threshold_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmstam:"))
async def cross_message_add_threshold_min_selected(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Выбран минимальный скор — показывает выбор максимального.

    Callback: cf:cmstam:{chat_id}:{min_score}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    min_score = int(parts[3])

    text = (
        f"📈 <b>Добавление порога</b>\n\n"
        f"Шаг 2/3: Выберите <b>максимальный</b> скор.\n\n"
        f"Минимум: {min_score} баллов\n\n"
        f"Порог сработает для скора в диапазоне\n"
        f"от {min_score} до выбранного максимума."
    )

    keyboard = create_cross_message_add_threshold_max_menu(chat_id, min_score)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmstax:"))
async def cross_message_add_threshold_max_selected(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Выбран максимальный скор — показывает выбор действия.

    Callback: cf:cmstax:{chat_id}:{min_score}:{max_score}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    min_score = int(parts[3])
    max_score_str = parts[4]
    max_score = None if max_score_str == 'inf' else int(max_score_str)

    # Форматируем диапазон
    if max_score is None:
        range_text = f"{min_score}+ баллов"
    else:
        range_text = f"{min_score}-{max_score} баллов"

    text = (
        f"📈 <b>Добавление порога</b>\n\n"
        f"Шаг 3/3: Выберите <b>действие</b>.\n\n"
        f"Диапазон: {range_text}\n\n"
        f"Какое действие применить при достижении порога?"
    )

    keyboard = create_cross_message_add_threshold_action_menu(chat_id, min_score, max_score)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmstaa:"))
async def cross_message_add_threshold_action_selected(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Выбрано действие — создаёт порог.

    Callback: cf:cmstaa:{chat_id}:{min_score}:{max_score}:{action}:{duration}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    min_score = int(parts[3])
    max_score_str = parts[4]
    max_score = None if max_score_str == 'inf' else int(max_score_str)
    action = parts[5]
    mute_duration = int(parts[6]) if parts[6] != '0' else None

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Создаём порог
    try:
        new_threshold = await service.add_threshold(
            chat_id=chat_id,
            min_score=min_score,
            max_score=max_score,
            action=action,
            mute_duration=mute_duration,
            created_by=callback.from_user.id,
            session=session
        )

        if new_threshold:
            await callback.answer("✅ Порог добавлен!")
        else:
            await callback.answer("⚠️ Не удалось добавить порог", show_alert=True)

    except Exception as e:
        logger.error(f"[CrossMessageThreshold] Error adding: {e}")
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        return

    # Обновляем список
    thresholds = await service.get_thresholds(chat_id, session)

    text = (
        f"📈 <b>Пороги баллов</b>\n\n"
        f"Порог добавлен!\n\n"
        f"Всего порогов: {len(thresholds)}"
    )

    keyboard = create_cross_message_score_thresholds_menu(chat_id, thresholds)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmstam_c:"))
async def cross_message_custom_mute_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает ввод кастомного времени мута для порога.

    Callback: cf:cmstam_c:{chat_id}:{min_score}:{max_score}
    """
    from bot.handlers.content_filter.common import CrossMessageThresholdMuteInputStates

    parts = callback.data.split(":")
    chat_id = int(parts[2])
    min_score = int(parts[3])
    max_score_str = parts[4]

    # Сохраняем данные в FSM
    await state.update_data(
        chat_id=chat_id,
        min_score=min_score,
        max_score_str=max_score_str,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    await state.set_state(CrossMessageThresholdMuteInputStates.waiting_for_mute_duration)

    text = (
        f"⏱️ <b>Время мута</b>\n\n"
        f"Введите время мута для диапазона {min_score}—{max_score_str} баллов.\n\n"
        f"<b>Форматы:</b>\n"
        f"• <code>30</code> — 30 минут\n"
        f"• <code>2h</code> — 2 часа\n"
        f"• <code>1d</code> — 1 день\n"
        f"• <code>7d</code> — 7 дней"
    )

    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmsta')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.message(CrossMessageThresholdMuteInputStates.waiting_for_mute_duration)
async def cross_message_custom_mute_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод кастомного времени мута.
    """
    from bot.handlers.content_filter.common import parse_duration, CrossMessageThresholdMuteInputStates

    # Проверка на команду
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get('chat_id')
    min_score = data.get('min_score')
    max_score_str = data.get('max_score_str')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: потеряны данные сессии.")
        await state.clear()
        return

    # Парсим время
    input_text = message.text.strip()
    minutes = parse_duration(input_text)

    if minutes is None or minutes < 1:
        await message.answer(
            "❌ Неверный формат. Используйте:\n"
            "<code>30</code>, <code>2h</code>, <code>1d</code>\n"
            "Минимум: 1 минута",
            parse_mode="HTML"
        )
        return

    # Нет ограничения по времени мута — админ решает сам

    # Удаляем prompt сообщение
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await state.clear()

    # Получаем сервис и создаём порог
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await message.answer("❌ Сервис недоступен")
        return

    max_score = None if max_score_str == 'inf' else int(max_score_str)

    try:
        new_threshold = await service.add_threshold(
            chat_id=chat_id,
            min_score=min_score,
            max_score=max_score,
            action='mute',
            mute_duration=minutes,
            created_by=message.from_user.id,
            session=session
        )

        if not new_threshold:
            await message.answer("⚠️ Не удалось добавить порог")
            return

        time_str = f"{minutes}мин" if minutes < 60 else (
            f"{minutes // 60}ч" if minutes < 1440 else f"{minutes // 1440}д"
        )

    except Exception as e:
        logger.error(f"[CrossMessageThreshold] Error adding custom: {e}")
        await message.answer(f"❌ Ошибка: {e}")
        return

    # Показываем обновлённый список (одно сообщение с подтверждением)
    thresholds = await service.get_thresholds(chat_id, session)

    text = (
        f"📈 <b>Пороги баллов</b>\n\n"
        f"✅ Добавлен: {min_score}—{max_score_str} → мут {time_str}\n\n"
        f"Всего порогов: {len(thresholds)}"
    )

    keyboard = create_cross_message_score_thresholds_menu(chat_id, thresholds)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")




@main_menu_router.callback_query(F.data.startswith("cf:cmste:"))
async def cross_message_threshold_edit(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает детали порога для редактирования.

    Callback: cf:cmste:{chat_id}:{threshold_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    threshold_id = int(parts[3])

    # Получаем порог из БД
    from sqlalchemy import select
    query = select(CrossMessageThreshold).where(CrossMessageThreshold.id == threshold_id)
    result = await session.execute(query)
    threshold = result.scalar_one_or_none()

    if not threshold:
        await callback.answer("Порог не найден", show_alert=True)
        return

    # Форматируем диапазон
    if threshold.max_score is None:
        range_text = f"{threshold.min_score}+"
    else:
        range_text = f"{threshold.min_score}-{threshold.max_score}"

    # Форматируем действие
    action_map = {'mute': 'Мут', 'ban': 'Бан', 'kick': 'Кик'}
    action_text = action_map.get(threshold.action, threshold.action)

    # Форматируем длительность
    if threshold.action == 'mute' and threshold.mute_duration:
        if threshold.mute_duration >= 1440:
            duration_text = f"{threshold.mute_duration // 1440} дн."
        elif threshold.mute_duration >= 60:
            duration_text = f"{threshold.mute_duration // 60} ч."
        else:
            duration_text = f"{threshold.mute_duration} мин."
        action_text = f"{action_text} на {duration_text}"

    # Статус
    status = "✅ Активен" if threshold.enabled else "⏸️ Отключён"

    text = (
        f"📈 <b>Порог баллов #{threshold_id}</b>\n\n"
        f"Диапазон: {range_text} баллов\n"
        f"Действие: {action_text}\n"
        f"Статус: {status}"
    )

    keyboard = create_cross_message_threshold_edit_menu(chat_id, threshold_id, threshold)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmstt:"))
async def cross_message_threshold_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает активность порога.

    Callback: cf:cmstt:{chat_id}:{threshold_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    threshold_id = int(parts[3])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Переключаем
    new_status = await service.toggle_threshold(threshold_id, session)

    if new_status is not None:
        status_text = "включён" if new_status else "отключён"
        await callback.answer(f"Порог {status_text}")
    else:
        await callback.answer("Порог не найден", show_alert=True)
        return

    # Обновляем список
    thresholds = await service.get_thresholds(chat_id, session)

    text = (
        f"📈 <b>Пороги баллов</b>\n\n"
        f"Всего порогов: {len(thresholds)}"
    )

    keyboard = create_cross_message_score_thresholds_menu(chat_id, thresholds)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmstd:"))
async def cross_message_threshold_delete(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет порог.

    Callback: cf:cmstd:{chat_id}:{threshold_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    threshold_id = int(parts[3])

    # Получаем сервис
    service = get_cross_message_service()
    if not service and redis:
        service = create_cross_message_service(redis)

    if not service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Удаляем
    success = await service.delete_threshold(threshold_id, session)

    if success:
        await callback.answer("🗑️ Порог удалён")
    else:
        await callback.answer("Порог не найден", show_alert=True)
        return

    # Обновляем список
    thresholds = await service.get_thresholds(chat_id, session)

    text = (
        f"📈 <b>Пороги баллов</b>\n\n"
        f"Порог удалён.\n\n"
        f"Всего порогов: {len(thresholds)}"
    )

    keyboard = create_cross_message_score_thresholds_menu(chat_id, thresholds)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# КРОСС-СООБЩЕНИЕ: УВЕДОМЛЕНИЯ
# ============================================================
# Хендлеры для настройки текстов уведомлений
# ============================================================

@main_menu_router.callback_query(F.data.startswith("cf:cmn:"))
async def cross_message_notifications_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настройки уведомлений.

    Callback: cf:cmn:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Текущие значения
    mute_text = getattr(settings, 'cross_message_mute_text', None) if settings else None
    ban_text = getattr(settings, 'cross_message_ban_text', None) if settings else None

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"Настройте тексты уведомлений при срабатывании.\n\n"
        f"<b>Плейсхолдеры:</b>\n"
        f"• <code>%user%</code> — имя пользователя\n"
        f"• <code>%time%</code> — время мута\n\n"
        f"<b>Текст мута:</b>\n"
        f"{mute_text or '❌ Не задан'}\n\n"
        f"<b>Текст бана:</b>\n"
        f"{ban_text or '❌ Не задан'}"
    )

    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmnc:"))
async def cross_message_notification_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Отменяет FSM ввод текста уведомления и возвращает в меню.

    По CHECKLIST.md: кнопка "Назад" должна очищать FSM!

    Callback: cf:cmnc:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # ОБЯЗАТЕЛЬНО: Очищаем FSM состояние
    await state.clear()

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"Ввод отменён."
    )

    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmnm:"))
async def cross_message_notification_mute_text_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает ввод текста уведомления при муте.

    Callback: cf:cmnm:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления (CHECKLIST: State Leak)
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    await state.set_state(CrossMessageNotificationStates.waiting_for_mute_text)

    text = (
        f"📝 <b>Текст уведомления при муте</b>\n\n"
        f"Отправьте текст уведомления.\n\n"
        f"<b>Плейсхолдеры:</b>\n"
        f"• <code>%user%</code> — имя пользователя\n"
        f"• <code>%time%</code> — время мута\n\n"
        f"<b>Пример:</b>\n"
        f"<code>🔇 %user% замучен на %time% за нарушения</code>\n\n"
        f"Отправьте <code>-</code> чтобы отключить уведомления."
    )

    keyboard = create_cross_message_notification_text_back_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.message(CrossMessageNotificationStates.waiting_for_mute_text)
async def cross_message_notification_mute_text_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод текста уведомления при муте.

    По CHECKLIST.md: удаляем prompt сообщение чтобы не засорять чат.
    """
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("Ошибка: потерян контекст. Начните заново.")
        await state.clear()
        return

    # CHECKLIST: Удаляем prompt сообщение
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except Exception:
            pass  # Сообщение могло быть уже удалено

    # Удаляем сообщение пользователя с текстом
    try:
        await message.delete()
    except Exception:
        pass

    # Получаем текст
    new_text = message.text.strip()

    # "-" = отключить
    if new_text == '-':
        new_text = None

    # Обновляем настройки
    await filter_manager.update_settings(
        chat_id, session,
        cross_message_mute_text=new_text
    )

    # Очищаем FSM
    await state.clear()

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    result_text = "✅ Текст мута обновлён!" if new_text else "✅ Уведомление при муте отключено"

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"{result_text}"
    )

    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.callback_query(F.data.startswith("cf:cmnb:"))
async def cross_message_notification_ban_text_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает ввод текста уведомления при бане.

    Callback: cf:cmnb:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления (CHECKLIST: State Leak)
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    await state.set_state(CrossMessageNotificationStates.waiting_for_ban_text)

    text = (
        f"📝 <b>Текст уведомления при бане</b>\n\n"
        f"Отправьте текст уведомления.\n\n"
        f"<b>Плейсхолдеры:</b>\n"
        f"• <code>%user%</code> — имя пользователя\n\n"
        f"<b>Пример:</b>\n"
        f"<code>🚫 %user% забанен за нарушения</code>\n\n"
        f"Отправьте <code>-</code> чтобы отключить уведомления."
    )

    keyboard = create_cross_message_notification_text_back_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.message(CrossMessageNotificationStates.waiting_for_ban_text)
async def cross_message_notification_ban_text_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод текста уведомления при бане.

    По CHECKLIST.md: удаляем prompt сообщение чтобы не засорять чат.
    """
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("Ошибка: потерян контекст. Начните заново.")
        await state.clear()
        return

    # CHECKLIST: Удаляем prompt сообщение
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except Exception:
            pass  # Сообщение могло быть уже удалено

    # Удаляем сообщение пользователя с текстом
    try:
        await message.delete()
    except Exception:
        pass

    # Получаем текст
    new_text = message.text.strip()

    # "-" = отключить
    if new_text == '-':
        new_text = None

    # Обновляем настройки
    await filter_manager.update_settings(
        chat_id, session,
        cross_message_ban_text=new_text
    )

    # Очищаем FSM
    await state.clear()

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    result_text = "✅ Текст бана обновлён!" if new_text else "✅ Уведомление при бане отключено"

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"{result_text}"
    )

    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@main_menu_router.callback_query(F.data.startswith("cf:cmnd:"))
async def cross_message_notification_delay_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню выбора задержки автоудаления.

    Callback: cf:cmnd:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSM контекст (для очистки при возврате)
    """
    # Очищаем FSM state если был в режиме ввода
    await state.clear()

    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    current = getattr(settings, 'cross_message_notification_delete_delay', None) if settings else None
    current_text = f"{current} сек" if current else "выключено"

    text = (
        f"🕐 <b>Автоудаление уведомлений</b>\n\n"
        f"Текущее значение: {current_text}\n\n"
        f"Уведомление будет автоматически удалено\n"
        f"через выбранное время."
    )

    keyboard = create_cross_message_notification_delay_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@main_menu_router.callback_query(F.data.startswith("cf:cmnds:"))
async def cross_message_notification_delay_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает задержку автоудаления.

    Callback: cf:cmnds:{chat_id}:{delay}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    delay = int(parts[3])

    # 0 = отключить
    delay_value = delay if delay > 0 else None

    # Обновляем настройки
    await filter_manager.update_settings(
        chat_id, session,
        cross_message_notification_delete_delay=delay_value
    )

    delay_text = f"{delay} сек" if delay > 0 else "выключено"
    await callback.answer(f"✅ Автоудаление: {delay_text}")

    # Обновляем меню
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"Автоудаление: {delay_text}"
    )

    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@main_menu_router.callback_query(F.data.startswith("cf:cmndc:"))
async def cross_message_notification_delay_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для кастомного ввода задержки автоудаления.

    Callback: cf:cmndc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSM контекст
        session: Сессия БД
    """
    # Парсим chat_id из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id и message_id для удаления в FSM данных
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )
    # Устанавливаем состояние ожидания ввода
    await state.set_state(CrossMessageNotificationDelayInputStates.waiting_for_delay)

    # Показываем инструкцию
    text = (
        f"🕐 <b>Введите задержку автоудаления</b>\n\n"
        f"Укажите время в одном из форматов:\n"
        f"• <code>30</code> — секунды\n"
        f"• <code>5min</code> — минуты\n"
        f"• <code>1h</code> — часы\n\n"
        f"Пример: <code>2min</code> = 2 минуты\n\n"
        f"Для отключения введите <code>0</code>"
    )

    # Клавиатура с кнопкой назад
    keyboard = create_cross_message_cancel_input_menu(chat_id, 'cmnd')

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@main_menu_router.message(CrossMessageNotificationDelayInputStates.waiting_for_delay)
async def cross_message_notification_delay_custom_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает введённое значение задержки.

    Args:
        message: Сообщение с введённым значением
        state: FSM контекст
        session: Сессия БД
    """
    # Проверка на команду — очищаем FSM и игнорируем
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    prompt_message_id = data.get('prompt_message_id')
    prompt_chat_id = data.get('prompt_chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: потеряны данные сессии. Начните заново.")
        await state.clear()
        return

    # Парсим введённое значение
    input_text = message.text.strip()

    # Проверяем на 0 (отключить)
    if input_text == "0":
        delay = 0
    else:
        delay = parse_delay_seconds(input_text)

        if delay is None or delay < 0:
            await message.answer(
                "❌ Неверный формат. Введите число в секундах или с суффиксом:\n"
                "<code>30</code>, <code>2min</code>, <code>1h</code>\n\n"
                "Для отключения введите <code>0</code>"
            , parse_mode="HTML")
            return

        # Ограничение: максимум 1 час
        if delay > 3600:
            await message.answer("❌ Слишком большое значение. Максимум: 1 час (3600 сек)")
            return

    # Обновляем настройки (0 = None = отключено)
    delay_value = delay if delay > 0 else None
    await filter_manager.update_settings(
        chat_id, session,
        cross_message_notification_delete_delay=delay_value
    )

    # Удаляем сообщение с запросом ввода (State Leak fix)
    if prompt_message_id and prompt_chat_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_message_id)
        except TelegramAPIError:
            pass

    # Удаляем сообщение пользователя с введённым значением
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сбрасываем FSM
    await state.clear()

    delay_text = f"{delay} сек" if delay > 0 else "выключено"
    await message.answer(f"✅ Автоудаление: {delay_text}")

    # Показываем обновлённое меню уведомлений
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    keyboard = create_cross_message_notifications_menu(chat_id, settings)

    mute_text = getattr(settings, 'cross_message_mute_text', None) if settings else None
    ban_text = getattr(settings, 'cross_message_ban_text', None) if settings else None

    text = (
        f"📢 <b>Уведомления кросс-сообщений</b>\n\n"
        f"Автоудаление: {delay_text}\n\n"
        f"<b>Текст мута:</b>\n"
        f"{mute_text or '❌ Не задан'}\n\n"
        f"<b>Текст бана:</b>\n"
        f"{ban_text or '❌ Не задан'}"
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
