# ============================================================
# UI ХЕНДЛЕРЫ МОДУЛЯ "УПРАВЛЕНИЕ СООБЩЕНИЯМИ"
# ============================================================
# Этот файл содержит callback query хендлеры для UI настроек:
# - Главное меню модуля
# - Меню удаления команд
# - Меню системных сообщений
# - Меню репина
# - Toggle хендлеры для переключения настроек
#
# Callback data формат: mm:{action}:{chat_id}
# mm = message_management (префикс модуля)
# ============================================================

# Импортируем логгер для записи событий
import logging

# Импортируем Router и фильтр F из aiogram
from aiogram import Router, F

# Импортируем типы для хендлеров
from aiogram.types import CallbackQuery

# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError

# Импортируем типы SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис для работы с настройками
from bot.services import message_management_service as mm_service

# Импортируем клавиатуры
from bot.keyboards.message_management_keyboards import (
    create_main_menu,
    create_commands_menu,
    create_system_messages_menu,
    create_repin_menu,
)

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для UI настроек
mm_settings_router = Router(name='mm_settings')


# ============================================================
# ГЛАВНОЕ МЕНЮ МОДУЛЯ
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:m:-?\d+$"))
async def show_main_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает главное меню модуля "Управление сообщениями".

    Callback: mm:m:{chat_id}

    Args:
        callback: Callback query от нажатия кнопки
        session: Сессия БД (инжектится middleware)
    """
    # Парсим chat_id из callback_data
    # Формат: mm:m:{chat_id}
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем или создаём настройки группы
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Формируем текст главного меню
    text = (
        "📨 <b>Управление сообщениями</b>\n\n"
        "Настройте автоматическое удаление сообщений\n"
        "и репин (автозакрепление).\n\n"
        "Выберите раздел:"
    )

    # Создаём клавиатуру главного меню
    keyboard = create_main_menu(chat_id, settings)

    # Редактируем сообщение с новым меню
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        # Если сообщение не изменилось — это нормально
        logger.debug(f"[MM] Сообщение не изменено: {e}")

    # Отвечаем на callback чтобы убрать "часики" в Telegram
    await callback.answer()


# ============================================================
# МЕНЮ УДАЛЕНИЯ КОМАНД
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:cmd:-?\d+$"))
async def show_commands_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек удаления команд.

    Callback: mm:cmd:{chat_id}

    Args:
        callback: Callback query
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        "🤖 <b>Удаление команд</b>\n\n"
        "Бот будет автоматически удалять сообщения,\n"
        "начинающиеся с <code>/</code> (команды).\n\n"
        "Настройте отдельно для админов и пользователей:"
    )

    # Создаём клавиатуру
    keyboard = create_commands_menu(chat_id, settings)

    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        logger.debug(f"[MM] Сообщение не изменено: {e}")

    await callback.answer()


# ============================================================
# МЕНЮ СИСТЕМНЫХ СООБЩЕНИЙ
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:sys:-?\d+$"))
async def show_system_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек удаления системных сообщений.

    Callback: mm:sys:{chat_id}

    Args:
        callback: Callback query
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        "🗨️ <b>Системные сообщения</b>\n\n"
        "Бот будет автоматически удалять\n"
        "системные сообщения выбранных типов.\n\n"
        "Выберите какие сообщения удалять:"
    )

    # Создаём клавиатуру
    keyboard = create_system_messages_menu(chat_id, settings)

    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        logger.debug(f"[MM] Сообщение не изменено: {e}")

    await callback.answer()


# ============================================================
# МЕНЮ РЕПИНА
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:repin:-?\d+$"))
async def show_repin_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню настроек репина (автозакрепления).

    Callback: mm:repin:{chat_id}

    Args:
        callback: Callback query
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Формируем текст меню
    text = (
        "📌 <b>Репин (автозакрепление)</b>\n\n"
        "Когда кто-то закрепляет другое сообщение,\n"
        "бот автоматически перезакрепит ваше.\n\n"
        "<b>Как использовать:</b>\n"
        "1. Закрепите нужное сообщение в группе\n"
        "2. Ответьте на него командой <code>/repin</code>\n"
        "3. Бот будет защищать это сообщение\n\n"
        "<i>Закрепы от связанного канала игнорируются.</i>"
    )

    # Создаём клавиатуру
    keyboard = create_repin_menu(chat_id, settings)

    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        logger.debug(f"[MM] Сообщение не изменено: {e}")

    await callback.answer()


# ============================================================
# TOGGLE ХЕНДЛЕРЫ - УДАЛЕНИЕ КОМАНД
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:adm:-?\d+$"))
async def toggle_admin_commands(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает настройку удаления команд от админов.

    Callback: mm:t:adm:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем текущие настройки
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Инвертируем значение
    new_value = not settings.delete_admin_commands

    # Обновляем настройки
    settings = await mm_service.update_settings(
        chat_id, session,
        delete_admin_commands=new_value
    )

    # Логируем изменение
    logger.info(
        f"[MM] Изменена настройка delete_admin_commands: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    # Обновляем клавиатуру с новым состоянием
    keyboard = create_commands_menu(chat_id, settings)

    # Редактируем сообщение (только клавиатуру)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    # Показываем уведомление
    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление команд админов: {status}")


@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:usr:-?\d+$"))
async def toggle_user_commands(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает настройку удаления команд от пользователей.

    Callback: mm:t:usr:{chat_id}
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    # Получаем текущие настройки
    settings = await mm_service.get_or_create_settings(chat_id, session)

    # Инвертируем значение
    new_value = not settings.delete_user_commands

    # Обновляем настройки
    settings = await mm_service.update_settings(
        chat_id, session,
        delete_user_commands=new_value
    )

    # Логируем изменение
    logger.info(
        f"[MM] Изменена настройка delete_user_commands: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    # Обновляем клавиатуру
    keyboard = create_commands_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление команд пользователей: {status}")


# ============================================================
# TOGGLE ХЕНДЛЕРЫ - СИСТЕМНЫЕ СООБЩЕНИЯ
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:join:-?\d+$"))
async def toggle_join_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление сообщений о входе участников.

    Callback: mm:t:join:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    settings = await mm_service.get_or_create_settings(chat_id, session)
    new_value = not settings.delete_join_messages

    settings = await mm_service.update_settings(
        chat_id, session,
        delete_join_messages=new_value
    )

    logger.info(
        f"[MM] Изменена настройка delete_join_messages: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    keyboard = create_system_messages_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление сообщений о входе: {status}")


@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:leave:-?\d+$"))
async def toggle_leave_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление сообщений о выходе участников.

    Callback: mm:t:leave:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    settings = await mm_service.get_or_create_settings(chat_id, session)
    new_value = not settings.delete_leave_messages

    settings = await mm_service.update_settings(
        chat_id, session,
        delete_leave_messages=new_value
    )

    logger.info(
        f"[MM] Изменена настройка delete_leave_messages: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    keyboard = create_system_messages_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление сообщений о выходе: {status}")


@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:pin:-?\d+$"))
async def toggle_pin_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление уведомлений о закрепе.

    Callback: mm:t:pin:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    settings = await mm_service.get_or_create_settings(chat_id, session)
    new_value = not settings.delete_pin_messages

    settings = await mm_service.update_settings(
        chat_id, session,
        delete_pin_messages=new_value
    )

    logger.info(
        f"[MM] Изменена настройка delete_pin_messages: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    keyboard = create_system_messages_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление уведомлений о закрепе: {status}")


@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:photo:-?\d+$"))
async def toggle_photo_messages(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает удаление сообщений об изменении фото/названия.

    Callback: mm:t:photo:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    settings = await mm_service.get_or_create_settings(chat_id, session)
    new_value = not settings.delete_chat_photo_messages

    settings = await mm_service.update_settings(
        chat_id, session,
        delete_chat_photo_messages=new_value
    )

    logger.info(
        f"[MM] Изменена настройка delete_chat_photo_messages: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    keyboard = create_system_messages_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Удаление сообщений о фото/названии: {status}")


# ============================================================
# TOGGLE ХЕНДЛЕР - РЕПИН
# ============================================================

@mm_settings_router.callback_query(F.data.regexp(r"^mm:t:repin:-?\d+$"))
async def toggle_repin(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает статус репина (вкл/выкл).

    Callback: mm:t:repin:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    settings = await mm_service.get_or_create_settings(chat_id, session)
    new_value = not settings.repin_enabled

    # Если включаем репин но сообщение не задано — предупреждаем
    if new_value and not settings.repin_message_id:
        await callback.answer(
            "⚠️ Репин включён, но сообщение не задано.\n"
            "Используйте /repin в группе.",
            show_alert=True
        )

    settings = await mm_service.update_settings(
        chat_id, session,
        repin_enabled=new_value
    )

    logger.info(
        f"[MM] Изменена настройка repin_enabled: "
        f"chat_id={chat_id}, new_value={new_value}"
    )

    keyboard = create_repin_menu(chat_id, settings)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        pass

    if not (new_value and not settings.repin_message_id):
        status = "включён ✅" if new_value else "выключен ❌"
        await callback.answer(f"Репин: {status}")


# ============================================================
# NOOP ХЕНДЛЕР (для информационных кнопок)
# ============================================================

@mm_settings_router.callback_query(F.data == "mm:noop")
async def noop_handler(callback: CallbackQuery) -> None:
    """
    Обработчик для информационных кнопок (ничего не делает).

    Callback: mm:noop
    """
    # Просто отвечаем на callback чтобы убрать "часики"
    await callback.answer()
