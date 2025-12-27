# ============================================================
# ACTION - ВЫБОР ДЕЙСТВИЯ ДЛЯ АНТИФЛУДА
# ============================================================
# Этот модуль содержит хендлеры для выбора действия:
# - flood_action_menu: меню выбора действия
# - set_flood_action: установка действия
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
    create_flood_action_menu,
    create_flood_mute_duration_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger

# Создаём роутер для действий
action_router = Router(name='flood_action')


# ============================================================
# МЕНЮ ДЕЙСТВИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@action_router.callback_query(F.data.regexp(r"^cf:fact:-?\d+$"))
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

    # Получаем настройки группы
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        f"⚡ <b>Действие для антифлуда</b>\n\n"
        f"Выберите действие при обнаружении флуда.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    # Создаём клавиатуру с учётом текущего времени мута
    keyboard = create_flood_action_menu(
        chat_id,
        settings.flood_action,
        settings.flood_mute_duration
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.callback_query(F.data.regexp(r"^cf:fact:\w+:-?\d+$"))
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

    # Сохраняем новое действие в БД
    await filter_manager.update_settings(chat_id, session, flood_action=new_action)

    # Получаем обновлённые настройки
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        f"⚡ <b>Действие для антифлуда</b>\n\n"
        f"Выберите действие при обнаружении флуда.\n"
        f"Если выбрать 'общее' - будет использоваться действие по умолчанию."
    )

    # Создаём клавиатуру с учётом текущего времени мута
    keyboard = create_flood_action_menu(
        chat_id,
        settings.flood_action,
        settings.flood_mute_duration
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    # Маппинг действий на читаемые названия
    action_names = {
        'default': 'Общее',
        'delete': 'Удаление',
        'warn': 'Предупреждение',
        'mute': 'Мут',
        'ban': 'Бан'
    }
    await callback.answer(f"Действие для флуда: {action_names.get(action, action)}")


# ============================================================
# МЕНЮ ВРЕМЕНИ МУТА ДЛЯ АНТИФЛУДА
# ============================================================

@action_router.callback_query(F.data.regexp(r"^cf:fldur:-?\d+$"))
async def flood_mute_duration_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора времени мута для антифлуда.

    Callback: cf:fldur:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id из callback data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки группы
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        f"⏱️ <b>Время мута для антифлуда</b>\n\n"
        f"Выберите на какое время мутить нарушителя.\n"
        f"Текущее значение: "
    )

    # Добавляем текущее значение в текст
    if settings.flood_mute_duration:
        # Форматируем время
        mins = settings.flood_mute_duration
        if mins >= 1440:
            days = mins // 1440
            hours = (mins % 1440) // 60
            if hours > 0:
                text += f"{days}д {hours}ч"
            else:
                text += f"{days}д"
        elif mins >= 60:
            hours = mins // 60
            remaining = mins % 60
            if remaining > 0:
                text += f"{hours}ч {remaining}мин"
            else:
                text += f"{hours}ч"
        else:
            text += f"{mins}мин"
    else:
        text += "24ч (по умолчанию)"

    # Создаём клавиатуру выбора времени
    keyboard = create_flood_mute_duration_menu(chat_id, settings.flood_mute_duration)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@action_router.callback_query(F.data.regexp(r"^cf:fldur:\d+:-?\d+$"))
async def set_flood_mute_duration(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает время мута для антифлуда.

    Callback: cf:fldur:{duration_minutes}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные из callback
    parts = callback.data.split(":")
    # duration_minutes - время мута в минутах
    duration_minutes = int(parts[2])
    # chat_id - ID группы
    chat_id = int(parts[3])

    # Сохраняем новое время мута в БД
    await filter_manager.update_settings(
        chat_id,
        session,
        flood_mute_duration=duration_minutes
    )

    # Логируем изменение
    logger.info(
        f"[FloodAction] Установлено время мута для антифлуда: "
        f"chat_id={chat_id}, duration={duration_minutes}min"
    )

    # Форматируем время для уведомления
    if duration_minutes >= 1440:
        days = duration_minutes // 1440
        hours = (duration_minutes % 1440) // 60
        if hours > 0:
            duration_text = f"{days}д {hours}ч"
        else:
            duration_text = f"{days}д"
    elif duration_minutes >= 60:
        hours = duration_minutes // 60
        remaining = duration_minutes % 60
        if remaining > 0:
            duration_text = f"{hours}ч {remaining}мин"
        else:
            duration_text = f"{hours}ч"
    else:
        duration_text = f"{duration_minutes}мин"

    # Показываем уведомление об успехе
    await callback.answer(f"✅ Время мута: {duration_text}")

    # Возвращаемся в меню выбора действия через копию callback (pydantic frozen)
    fake_callback = callback.model_copy(update={"data": f"cf:fact:{chat_id}"})
    await flood_action_menu(fake_callback, session)