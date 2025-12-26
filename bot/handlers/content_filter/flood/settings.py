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

    # Создаём фейковый callback для вызова flood_advanced_menu
    # Меняем data на cf:fladv:{chat_id}
    callback.data = f"cf:fladv:{chat_id}"

    # Вызываем меню "Дополнительно"
    await flood_advanced_menu(callback, session)


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

    # Создаём фейковый callback для вызова flood_advanced_menu
    callback.data = f"cf:fladv:{chat_id}"

    # Вызываем меню "Дополнительно"
    await flood_advanced_menu(callback, session)
