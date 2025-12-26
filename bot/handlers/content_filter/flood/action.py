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
from bot.keyboards.content_filter_keyboards import create_flood_action_menu

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

    settings = await filter_manager.get_or_create_settings(chat_id, session)

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

    await filter_manager.update_settings(chat_id, session, flood_action=new_action)

    settings = await filter_manager.get_or_create_settings(chat_id, session)

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