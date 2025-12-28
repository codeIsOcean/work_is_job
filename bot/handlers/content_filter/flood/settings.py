# ============================================================
# SETTINGS - ОСНОВНЫЕ НАСТРОЙКИ АНТИФЛУДА
# ============================================================
# Этот модуль содержит хендлеры для основных настроек:
# - flood_settings_menu: меню настроек антифлуда
# - set_flood_max_repeats: установка max_repeats
# - set_flood_time_window: установка time_window
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery
# Импортируем FSM
from aiogram.fsm.context import FSMContext
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import create_flood_settings_menu

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger

# Создаём роутер для настроек
settings_router = Router(name='flood_settings')


# ============================================================
# МЕНЮ НАСТРОЕК АНТИФЛУДА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:fls:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@settings_router.callback_query(F.data.regexp(r"^cf:flr:\d+:-?\d+$"))
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
    # Импортируем flood_advanced_menu для возврата
    from bot.handlers.content_filter.flood.advanced import flood_advanced_menu

    # Парсим данные
    parts = callback.data.split(":")
    value = int(parts[2])
    chat_id = int(parts[3])

    # Обновляем настройки
    await filter_manager.update_settings(chat_id, session, flood_max_repeats=value)

    # Показываем уведомление
    await callback.answer(f"✅ Макс. повторов: {value}")

    # Возвращаемся в меню "Дополнительно" через копию callback (pydantic frozen)
    fake_callback = callback.model_copy(update={"data": f"cf:fladv:{chat_id}"})
    await flood_advanced_menu(fake_callback, session)


@settings_router.callback_query(F.data.regexp(r"^cf:flw:\d+:-?\d+$"))
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
    # Импортируем flood_advanced_menu для возврата
    from bot.handlers.content_filter.flood.advanced import flood_advanced_menu

    # Парсим данные
    parts = callback.data.split(":")
    value = int(parts[2])
    chat_id = int(parts[3])

    # Обновляем настройки
    await filter_manager.update_settings(chat_id, session, flood_time_window=value)

    # Показываем уведомление
    await callback.answer(f"✅ Временное окно: {value} сек.")

    # Возвращаемся в меню "Дополнительно" через копию callback (pydantic frozen)
    fake_callback = callback.model_copy(update={"data": f"cf:fladv:{chat_id}"})
    await flood_advanced_menu(fake_callback, session)


# ============================================================
# ПЕРЕКЛЮЧАТЕЛИ РАСШИРЕННОГО АНТИФЛУДА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:t:flany:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.flood_detect_any_messages
    await filter_manager.update_settings(chat_id, session, flood_detect_any_messages=new_value)

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@settings_router.callback_query(F.data.regexp(r"^cf:t:flmedia:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.flood_detect_media
    await filter_manager.update_settings(chat_id, session, flood_detect_media=new_value)

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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
# ПЕРЕКЛЮЧАТЕЛЬ УДАЛЕНИЯ ФЛУД-СООБЩЕНИЙ
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:t:fldel:-?\d+$"))
async def toggle_flood_delete_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает настройку удаления флуд-сообщений.

    Callback: cf:t:fldel:{chat_id}

    Когда включено (по умолчанию) - флуд-сообщения удаляются.
    Когда выключено - применяется только действие (мут/бан/warn),
    сообщения остаются в чате.

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Импортируем flood_advanced_menu для возврата
    from bot.handlers.content_filter.flood.advanced import flood_advanced_menu

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем значение (по умолчанию True если не задано)
    current_value = getattr(settings, 'flood_delete_messages', True)
    new_value = not current_value

    # Сохраняем в БД
    await filter_manager.update_settings(chat_id, session, flood_delete_messages=new_value)

    # Логируем изменение
    logger.info(
        f"[FloodSettings] flood_delete_messages изменено: "
        f"chat_id={chat_id}, {current_value} -> {new_value}"
    )

    # Показываем уведомление
    status_text = "включено" if new_value else "выключено"
    await callback.answer(f"Удаление флуд-сообщений {status_text}")

    # Возвращаемся в меню "Дополнительно" через симуляцию callback
    # Создаём копию callback с новым data (pydantic frozen workaround)
    fake_callback = callback.model_copy(update={"data": f"cf:fladv:{chat_id}"})
    await flood_advanced_menu(fake_callback, session)
