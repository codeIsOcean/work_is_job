# bot/handlers/profile_monitor/settings_handler.py
"""
Обработчики настроек Profile Monitor в ЛС бота.

Позволяет админам настраивать:
- Включение/выключение модуля
- Параметры логирования (имя, username, фото)
- Параметры автомута (пороги, удаление сообщений)
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.profile_monitor.profile_monitor_service import (
    get_profile_monitor_settings,
    create_or_update_settings,
)
from bot.keyboards.profile_monitor_kb import (
    get_settings_main_kb,
    get_log_settings_kb,
    get_mute_settings_kb,
    get_age_threshold_kb,
    # Клавиатура для выбора порога свежести фото (критерии 4,5)
    get_photo_freshness_threshold_kb,
)

# Логгер модуля
logger = logging.getLogger(__name__)

# Роутер для настроек
router = Router(name="profile_monitor_settings")


# ============================================================
# CALLBACK: ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================
@router.callback_query(F.data.startswith("pm_settings_main:"))
async def callback_settings_main(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает главное меню настроек Profile Monitor.

    Формат callback_data: pm_settings_main:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка: неверный формат данных")
        return

    chat_id = int(parts[1])

    # Получаем или создаём настройки
    settings = await get_profile_monitor_settings(session, chat_id)
    if not settings:
        settings = await create_or_update_settings(session, chat_id)

    # Формируем текст
    status_emoji = "🟢" if settings.enabled else "🔴"
    status_text = "Включён" if settings.enabled else "Выключен"

    text = (
        f"📊 <b>Profile Monitor</b>\n\n"
        f"Статус: {status_emoji} {status_text}\n\n"
        f"Модуль отслеживает изменения профилей пользователей "
        f"и автоматически применяет меры к подозрительным аккаунтам."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_settings_main_kb(chat_id, settings.enabled),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# CALLBACK: ВКЛЮЧИТЬ/ВЫКЛЮЧИТЬ МОДУЛЬ
# ============================================================
@router.callback_query(F.data.startswith("pm_toggle:"))
async def callback_toggle_module(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Включает или выключает модуль Profile Monitor.

    Формат callback_data: pm_toggle:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    # Обновляем настройки
    settings = await create_or_update_settings(session, chat_id, enabled=enabled)

    logger.info(
        f"[PROFILE_MONITOR] Module {'enabled' if enabled else 'disabled'}: "
        f"chat={chat_id} by admin={callback.from_user.id}"
    )

    # Формируем текст
    status_emoji = "🟢" if settings.enabled else "🔴"
    status_text = "Включён" if settings.enabled else "Выключен"

    text = (
        f"📊 <b>Profile Monitor</b>\n\n"
        f"Статус: {status_emoji} {status_text}\n\n"
        f"Модуль отслеживает изменения профилей пользователей "
        f"и автоматически применяет меры к подозрительным аккаунтам."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_settings_main_kb(chat_id, settings.enabled),
        parse_mode="HTML",
    )
    await callback.answer(f"Модуль {'включён' if enabled else 'выключен'}")


# ============================================================
# CALLBACK: НАСТРОЙКИ ЛОГИРОВАНИЯ
# ============================================================
@router.callback_query(F.data.startswith("pm_settings_log:"))
async def callback_log_settings(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает настройки логирования.

    Формат callback_data: pm_settings_log:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка: неверный формат данных")
        return

    chat_id = int(parts[1])

    # Получаем настройки
    settings = await get_profile_monitor_settings(session, chat_id)
    if not settings:
        settings = await create_or_update_settings(session, chat_id)

    text = (
        f"📝 <b>Настройки логирования</b>\n\n"
        f"Выберите какие изменения профиля отслеживать "
        f"и отправлять в журнал группы."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ЛОГИРОВАНИЯ ИМЕНИ
# ============================================================
@router.callback_query(F.data.startswith("pm_log_name:"))
async def callback_toggle_log_name(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает логирование изменения имени.

    Формат callback_data: pm_log_name:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    # Обновляем настройки
    settings = await create_or_update_settings(
        session, chat_id, log_name_changes=enabled
    )

    # Обновляем клавиатуру
    await callback.message.edit_reply_markup(
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
    )
    await callback.answer(f"Логирование имён {'включено' if enabled else 'выключено'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ЛОГИРОВАНИЯ USERNAME
# ============================================================
@router.callback_query(F.data.startswith("pm_log_username:"))
async def callback_toggle_log_username(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает логирование изменения username.

    Формат callback_data: pm_log_username:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, log_username_changes=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
    )
    await callback.answer(f"Логирование username {'включено' if enabled else 'выключено'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ЛОГИРОВАНИЯ ФОТО
# ============================================================
@router.callback_query(F.data.startswith("pm_log_photo:"))
async def callback_toggle_log_photo(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает логирование изменения фото.

    Формат callback_data: pm_log_photo:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, log_photo_changes=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
    )
    await callback.answer(f"Логирование фото {'включено' if enabled else 'выключено'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ОТПРАВКИ В ЖУРНАЛ
# ============================================================
@router.callback_query(F.data.startswith("pm_send_journal:"))
async def callback_toggle_send_journal(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает отправку в журнал.

    Формат callback_data: pm_send_journal:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, send_to_journal=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
    )
    await callback.answer(f"Отправка в журнал {'включена' if enabled else 'выключена'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ОТПРАВКИ В ГРУППУ
# ============================================================
# Простые уведомления об изменениях профиля для всех участников группы
# Формат: "Пользователь X сменил имя на Y" + история имён
@router.callback_query(F.data.startswith("pm_send_grp:"))
async def callback_toggle_send_to_group(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает отправку простых уведомлений в группу.

    Формат callback_data: pm_send_grp:on|off:chat_id

    Когда включено: отправляет простые уведомления в саму группу
    (видно всем участникам) при изменении профиля.
    """
    # Разбираем callback_data на части
    parts = callback.data.split(":")
    # Проверяем корректность формата (должно быть 3 части)
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    # Извлекаем действие (on/off) и chat_id
    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    # Определяем новое значение настройки
    enabled = action == "on"

    # Обновляем настройку send_to_group в базе данных
    settings = await create_or_update_settings(
        session, chat_id, send_to_group=enabled
    )

    # Логируем изменение настройки
    logger.info(
        f"[PROFILE_MONITOR] Send to group {'enabled' if enabled else 'disabled'}: "
        f"chat={chat_id} by admin={callback.from_user.id}"
    )

    # Обновляем клавиатуру с новым состоянием
    await callback.message.edit_reply_markup(
        reply_markup=get_log_settings_kb(
            chat_id=chat_id,
            log_name=settings.log_name_changes,
            log_username=settings.log_username_changes,
            log_photo=settings.log_photo_changes,
            send_to_journal=settings.send_to_journal,
            send_to_group=settings.send_to_group,
        ),
    )
    # Показываем уведомление админу
    await callback.answer(f"Отправка в группу {'включена' if enabled else 'выключена'}")


# ============================================================
# CALLBACK: НАСТРОЙКИ АВТОМУТА
# ============================================================
@router.callback_query(F.data.startswith("pm_settings_mute:"))
async def callback_mute_settings(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает настройки автомута.

    Формат callback_data: pm_settings_mute:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка")
        return

    chat_id = int(parts[1])

    settings = await get_profile_monitor_settings(session, chat_id)
    if not settings:
        settings = await create_or_update_settings(session, chat_id)

    # Формируем текст с описанием всех критериев
    # ВАЖНО: используем &lt; вместо < для HTML, иначе Telegram ошибка
    text = (
        f"⚡ <b>Настройки автомута</b>\n\n"
        f"Автоматический мут пользователей по критериям:\n\n"
        f"<b>Критерий 1:</b> Смена имени + смена фото + сообщение ≤"
        f"{settings.first_message_window_minutes} мин\n"
        f"<b>Критерий 2:</b> Смена имени + сообщение ≤"
        f"{settings.first_message_window_minutes} мин\n"
        f"<b>Критерий 3:</b> Добавление фото + сообщение ≤"
        f"{settings.first_message_window_minutes} мин\n"
        f"<b>Критерий 4:</b> Свежее фото (&lt;{settings.photo_freshness_threshold_days} дн) + "
        f"смена имени + сообщение ≤{settings.first_message_window_minutes} мин\n"
        f"<b>Критерий 5:</b> Свежее фото (&lt;{settings.photo_freshness_threshold_days} дн) + "
        f"сообщение ≤{settings.first_message_window_minutes} мин"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_mute_settings_kb(
            chat_id=chat_id,
            auto_mute_young=settings.auto_mute_no_photo_young,
            auto_mute_name_change=settings.auto_mute_name_change_fast_msg,
            delete_messages=settings.auto_mute_delete_messages,
            account_age_days=settings.auto_mute_account_age_days,
            # Передаём порог свежести фото для критериев 4 и 5
            photo_freshness_threshold_days=settings.photo_freshness_threshold_days,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ АВТОМУТА МОЛОДЫХ АККАУНТОВ
# ============================================================
@router.callback_query(F.data.startswith("pm_mute_young:"))
async def callback_toggle_mute_young(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает автомут молодых аккаунтов без фото.

    Формат callback_data: pm_mute_young:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, auto_mute_no_photo_young=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_mute_settings_kb(
            chat_id=chat_id,
            auto_mute_young=settings.auto_mute_no_photo_young,
            auto_mute_name_change=settings.auto_mute_name_change_fast_msg,
            delete_messages=settings.auto_mute_delete_messages,
            account_age_days=settings.auto_mute_account_age_days,
            photo_freshness_threshold_days=settings.photo_freshness_threshold_days,
        ),
    )
    await callback.answer(f"Автомут молодых аккаунтов {'включён' if enabled else 'выключен'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ АВТОМУТА ПРИ СМЕНЕ ИМЕНИ
# ============================================================
@router.callback_query(F.data.startswith("pm_mute_name:"))
async def callback_toggle_mute_name_change(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает автомут при смене имени.

    Формат callback_data: pm_mute_name:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, auto_mute_name_change_fast_msg=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_mute_settings_kb(
            chat_id=chat_id,
            auto_mute_young=settings.auto_mute_no_photo_young,
            auto_mute_name_change=settings.auto_mute_name_change_fast_msg,
            delete_messages=settings.auto_mute_delete_messages,
            account_age_days=settings.auto_mute_account_age_days,
            photo_freshness_threshold_days=settings.photo_freshness_threshold_days,
        ),
    )
    await callback.answer(f"Автомут при смене имени {'включён' if enabled else 'выключен'}")


# ============================================================
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ УДАЛЕНИЯ СООБЩЕНИЙ
# ============================================================
@router.callback_query(F.data.startswith("pm_delete_msgs:"))
async def callback_toggle_delete_messages(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает удаление сообщений при автомуте.

    Формат callback_data: pm_delete_msgs:on|off:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, action, chat_id_str = parts
    chat_id = int(chat_id_str)
    enabled = action == "on"

    settings = await create_or_update_settings(
        session, chat_id, auto_mute_delete_messages=enabled
    )

    await callback.message.edit_reply_markup(
        reply_markup=get_mute_settings_kb(
            chat_id=chat_id,
            auto_mute_young=settings.auto_mute_no_photo_young,
            auto_mute_name_change=settings.auto_mute_name_change_fast_msg,
            delete_messages=settings.auto_mute_delete_messages,
            account_age_days=settings.auto_mute_account_age_days,
            photo_freshness_threshold_days=settings.photo_freshness_threshold_days,
        ),
    )
    await callback.answer(f"Удаление сообщений {'включено' if enabled else 'выключено'}")


# ============================================================
# CALLBACK: МЕНЮ ВЫБОРА ПОРОГА ВОЗРАСТА
# ============================================================
@router.callback_query(F.data.startswith("pm_age_threshold:"))
async def callback_age_threshold_menu(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает меню выбора порога возраста аккаунта.

    Формат callback_data: pm_age_threshold:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка")
        return

    chat_id = int(parts[1])

    settings = await get_profile_monitor_settings(session, chat_id)
    if not settings:
        settings = await create_or_update_settings(session, chat_id)

    text = (
        f"📅 <b>Порог возраста аккаунта</b>\n\n"
        f"Текущий порог: <b>{settings.auto_mute_account_age_days} дней</b>\n\n"
        f"Если у пользователя нет фото и его аккаунт младше указанного порога, "
        f"будет применён автоматический мут."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_age_threshold_kb(
            chat_id=chat_id,
            current_days=settings.auto_mute_account_age_days,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# CALLBACK: УСТАНОВКА ПОРОГА ВОЗРАСТА
# ============================================================
@router.callback_query(F.data.startswith("pm_set_age:"))
async def callback_set_age_threshold(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает порог возраста аккаунта.

    Формат callback_data: pm_set_age:days:chat_id
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    _, days_str, chat_id_str = parts
    days = int(days_str)
    chat_id = int(chat_id_str)

    settings = await create_or_update_settings(
        session, chat_id, auto_mute_account_age_days=days
    )

    logger.info(
        f"[PROFILE_MONITOR] Age threshold set to {days} days: "
        f"chat={chat_id} by admin={callback.from_user.id}"
    )

    # Обновляем клавиатуру
    await callback.message.edit_reply_markup(
        reply_markup=get_age_threshold_kb(
            chat_id=chat_id,
            current_days=settings.auto_mute_account_age_days,
        ),
    )
    await callback.answer(f"Порог установлен: {days} дней")


# ============================================================
# CALLBACK: МЕНЮ ВЫБОРА ПОРОГА СВЕЖЕСТИ ФОТО
# ============================================================
@router.callback_query(F.data.startswith("pm_photo_fresh_threshold:"))
async def callback_photo_freshness_threshold_menu(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает меню выбора порога свежести фото.

    Используется для критериев автомута 4 и 5:
    - Критерий 4: Свежее фото + смена имени + сообщение ≤30 мин
    - Критерий 5: Свежее фото + сообщение ≤30 мин

    Формат callback_data: pm_photo_fresh_threshold:chat_id
    """
    # Разбираем callback_data на части
    parts = callback.data.split(":")
    # Проверяем корректность формата (должно быть 2 части)
    if len(parts) != 2:
        await callback.answer("Ошибка: неверный формат данных")
        return

    # Извлекаем chat_id
    chat_id = int(parts[1])

    # Получаем настройки из БД
    settings = await get_profile_monitor_settings(session, chat_id)
    # Если настроек нет - создаём с дефолтными значениями
    if not settings:
        settings = await create_or_update_settings(session, chat_id)

    # Формируем текст с описанием настройки
    text = (
        f"📸 <b>Порог свежести фото</b>\n\n"
        f"Текущий порог: <b>{settings.photo_freshness_threshold_days} "
        f"{'день' if settings.photo_freshness_threshold_days == 1 else 'дней'}</b>\n\n"
        f"Фото считается «свежим» если его возраст меньше порога.\n\n"
        f"<b>Критерий 4:</b> Свежее фото + смена имени → мут\n"
        f"<b>Критерий 5:</b> Свежее фото (стало свежее чем при входе) → мут"
    )

    # Показываем клавиатуру выбора порога
    await callback.message.edit_text(
        text=text,
        reply_markup=get_photo_freshness_threshold_kb(
            chat_id=chat_id,
            current_days=settings.photo_freshness_threshold_days,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# CALLBACK: УСТАНОВКА ПОРОГА СВЕЖЕСТИ ФОТО
# ============================================================
@router.callback_query(F.data.startswith("pm_set_photo_fresh:"))
async def callback_set_photo_freshness_threshold(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает порог свежести фото.

    Формат callback_data: pm_set_photo_fresh:days:chat_id
    """
    # Разбираем callback_data на части
    parts = callback.data.split(":")
    # Проверяем корректность формата (должно быть 3 части)
    if len(parts) != 3:
        await callback.answer("Ошибка: неверный формат данных")
        return

    # Извлекаем количество дней и chat_id
    _, days_str, chat_id_str = parts
    days = int(days_str)
    chat_id = int(chat_id_str)

    # Обновляем настройку в БД
    settings = await create_or_update_settings(
        session, chat_id, photo_freshness_threshold_days=days
    )

    # Логируем изменение настройки
    logger.info(
        f"[PROFILE_MONITOR] Photo freshness threshold set to {days} days: "
        f"chat={chat_id} by admin={callback.from_user.id}"
    )

    # Обновляем клавиатуру с новым состоянием
    await callback.message.edit_reply_markup(
        reply_markup=get_photo_freshness_threshold_kb(
            chat_id=chat_id,
            current_days=settings.photo_freshness_threshold_days,
        ),
    )
    # Показываем уведомление админу
    await callback.answer(f"Порог свежести фото: {days} дней")
