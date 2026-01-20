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
from bot.handlers.content_filter.common import AddCrossMessagePatternStates

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
    create_cross_message_delete_confirm_menu
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
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора временного окна.

    Callback: cf:cmw:{chat_id} или cf:cmw:s:{seconds}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
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
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора порога срабатывания.

    Callback: cf:cmt:{chat_id} или cf:cmt:s:{value}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
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
