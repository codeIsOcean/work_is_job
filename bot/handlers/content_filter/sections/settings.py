# ============================================================
# SETTINGS - НАСТРОЙКИ РАЗДЕЛА
# ============================================================
# Этот модуль содержит хендлеры для настроек раздела:
# - section_settings_menu: меню настроек
# - toggle_section_status: переключение вкл/выкл
# - delete_section: удаление раздела
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем FSM
from aiogram.fsm.context import FSMContext
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_section_settings_menu,
    create_section_delete_confirm_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для настроек
settings_router = Router(name='sections_settings')


# ============================================================
# МЕНЮ НАСТРОЕК РАЗДЕЛА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:secs:\d+$"))
async def section_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню настроек раздела.

    Callback: cf:secs:{section_id}
    """
    # Очищаем FSM если передан
    if state:
        await state.clear()

    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()

    # Получаем раздел
    section = await section_service.get_section_by_id(section_id, session)
    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Получаем количество паттернов
    patterns_count = await section_service.get_patterns_count(section_id, session)

    # Формируем текст
    status = "Включён ✅" if section.enabled else "Выключен ❌"
    action_map = {
        'delete': '🗑️ Удалить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан',
        'forward_delete': '📤 Переслать + удалить'
    }
    action_text = action_map.get(section.action, '🗑️ Удалить')

    text = (
        f"📂 <b>Раздел: {section.name}</b>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Паттернов:</b> {patterns_count}\n"
        f"<b>Порог:</b> {section.threshold} баллов\n"
        f"<b>Действие:</b> {action_text}\n"
    )

    if section.description:
        text += f"\n<i>{section.description}</i>\n"

    if section.action == 'mute' and section.mute_duration:
        if section.mute_duration < 60:
            text += f"\n<b>Длительность мута:</b> {section.mute_duration} мин"
        elif section.mute_duration < 1440:
            text += f"\n<b>Длительность мута:</b> {section.mute_duration // 60} ч"
        else:
            text += f"\n<b>Длительность мута:</b> {section.mute_duration // 1440} д"

    if section.action == 'forward_delete' and section.forward_channel_id:
        text += f"\n<b>Канал пересылки:</b> <code>{section.forward_channel_id}</code>"

    keyboard = create_section_settings_menu(section_id, section, section.chat_id, patterns_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.callback_query(F.data.regexp(r"^cf:sect:\d+$"))
async def toggle_section_status(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает статус раздела (вкл/выкл).

    Callback: cf:sect:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    success = await section_service.toggle_section(section_id, session)

    if success:
        new_status = "включён" if not section.enabled else "выключен"
        await callback.answer(f"Раздел {new_status}")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)

    # Перерисовываем меню настроек
    callback.data = f"cf:secs:{section_id}"
    await section_settings_menu(callback, session, None)


# ============================================================
# УДАЛЕНИЕ РАЗДЕЛА
# ============================================================

@settings_router.callback_query(F.data.regexp(r"^cf:secd:\d+$"))
async def confirm_delete_section(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления раздела.

    Callback: cf:secd:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    text = (
        f"⚠️ <b>Удаление раздела</b>\n\n"
        f"Вы уверены что хотите удалить раздел «{section.name}»?\n\n"
        f"Это действие нельзя отменить. Все паттерны раздела будут удалены."
    )

    keyboard = create_section_delete_confirm_menu(section_id, section.chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@settings_router.callback_query(F.data.regexp(r"^cf:secdc:\d+:-?\d+$"))
async def delete_section_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет раздел после подтверждения.

    Callback: cf:secdc:{section_id}:{chat_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])
    chat_id = int(parts[3])

    section_service = get_section_service()

    # Получаем название перед удалением
    section = await section_service.get_section_by_id(section_id, session)
    section_name = section.name if section else "Неизвестный"

    # Удаляем
    success = await section_service.delete_section(section_id, session)

    if success:
        logger.info(f"[Sections] Удалён раздел '{section_name}' (id={section_id}) из чата {chat_id}")
        await callback.answer(f"Раздел «{section_name}» удалён")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    # Возвращаемся к списку разделов
    from bot.handlers.content_filter.sections.menu import custom_sections_menu
    callback.data = f"cf:sccat:{chat_id}"
    await custom_sections_menu(callback, session, None)
