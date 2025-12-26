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
from aiogram.types import CallbackQuery
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_content_filter_main_menu,
    create_content_filter_settings_menu,
    create_sensitivity_menu,
    create_action_menu,
    create_word_filter_settings_menu
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
