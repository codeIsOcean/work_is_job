# ============================================================
# CLEANUP - МОДУЛЬ УДАЛЕНИЯ СООБЩЕНИЙ
# ============================================================
# Этот модуль содержит хендлеры для настроек удаления сообщений:
# - cleanup_settings_menu: меню настроек
# - toggle_delete_user_commands: переключение удаления команд
# - toggle_delete_system_messages: переключение удаления системных
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger

# Создаём роутер для cleanup
cleanup_router = Router(name='cleanup')


# ============================================================
# МЕНЮ НАСТРОЕК УДАЛЕНИЯ СООБЩЕНИЙ
# ============================================================

@cleanup_router.callback_query(F.data.regexp(r"^cf:cleanup:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

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


@cleanup_router.callback_query(F.data.regexp(r"^cf:t:delcmd:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.delete_user_commands
    await filter_manager.update_settings(chat_id, session, delete_user_commands=new_value)

    # Возвращаемся в меню
    callback.data = f"cf:cleanup:{chat_id}"
    await cleanup_settings_menu(callback, session)

    status_text = "включено" if new_value else "выключено"
    await callback.answer(f"Удаление команд {status_text}")


@cleanup_router.callback_query(F.data.regexp(r"^cf:t:delsys:-?\d+$"))
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
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # Переключаем
    new_value = not settings.delete_system_messages
    await filter_manager.update_settings(chat_id, session, delete_system_messages=new_value)

    # Возвращаемся в меню
    callback.data = f"cf:cleanup:{chat_id}"
    await cleanup_settings_menu(callback, session)

    status_text = "включено" if new_value else "выключено"
    await callback.answer(f"Удаление системных сообщений {status_text}")
