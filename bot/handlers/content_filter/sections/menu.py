# ============================================================
# MENU - МЕНЮ КАСТОМНЫХ РАЗДЕЛОВ
# ============================================================
# Этот модуль содержит хендлеры для меню разделов:
# - custom_sections_menu: список разделов
# - toggle_custom_section: переключение раздела
# - start_add_section: начало создания раздела (FSM)
# - process_section_name: обработка названия
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router и F для фильтров
from aiogram import Router, F
# Импортируем типы
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем FSM
from aiogram.fsm.context import FSMContext
# Импортируем исключения
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_custom_sections_menu,
    create_cancel_section_input_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем FSM states
from bot.handlers.content_filter.common import AddSectionStates
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для меню
menu_router = Router(name='sections_menu')


# ============================================================
# СПИСОК РАЗДЕЛОВ
# ============================================================

@menu_router.callback_query(F.data.regexp(r"^cf:sccat:-?\d+$"))
async def custom_sections_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает список кастомных разделов спама.

    Callback: cf:sccat:{chat_id}
    """
    # Очищаем FSM состояние
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис и разделы
    section_service = get_section_service()
    sections = await section_service.get_sections(chat_id, session, enabled_only=False)

    # Формируем текст
    if sections:
        text = (
            f"📂 <b>Кастомные разделы спама</b>\n\n"
            f"Здесь вы можете создавать отдельные разделы для разных типов спама:\n"
            f"• Такси — реклама такси\n"
            f"• Жильё — аренда/продажа\n"
            f"• Наркотики — запрещённые вещества\n\n"
            f"Каждый раздел имеет свои паттерны и настройки.\n\n"
            f"<b>Ваши разделы:</b> {len(sections)}"
        )
    else:
        text = (
            f"📂 <b>Кастомные разделы спама</b>\n\n"
            f"У вас пока нет кастомных разделов.\n\n"
            f"Создайте первый раздел для детекции определённого типа спама.\n\n"
            f"<i>Например: «Такси» с паттернами типа «срочно водитель», «подработка такси»</i>"
        )

    keyboard = create_custom_sections_menu(chat_id, sections)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@menu_router.callback_query(F.data.regexp(r"^cf:sec:\d+$"))
async def toggle_custom_section(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает активность кастомного раздела.

    Callback: cf:sec:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()

    # Получаем раздел чтобы узнать chat_id
    section = await section_service.get_section_by_id(section_id, session)
    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    chat_id = section.chat_id

    # Переключаем
    success = await section_service.toggle_section(section_id, session)

    if success:
        new_status = "включён" if not section.enabled else "выключен"
        await callback.answer(f"Раздел {new_status}")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)

    # Перерисовываем меню
    sections = await section_service.get_sections(chat_id, session, enabled_only=False)
    keyboard = create_custom_sections_menu(chat_id, sections)

    text = (
        f"📂 <b>Кастомные разделы спама</b>\n\n"
        f"<b>Ваши разделы:</b> {len(sections)}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


# ============================================================
# СОЗДАНИЕ РАЗДЕЛА (FSM)
# ============================================================

@menu_router.callback_query(F.data.regexp(r"^cf:secn:-?\d+$"))
async def start_add_section(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для создания нового раздела.

    Callback: cf:secn:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(
        chat_id=chat_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(AddSectionStates.waiting_for_name)

    text = (
        f"📂 <b>Новый раздел спама</b>\n\n"
        f"Введите название раздела.\n\n"
        f"<i>Например: «Такси», «Жильё», «Наркотики»</i>"
    )

    keyboard = create_cancel_section_input_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@menu_router.message(AddSectionStates.waiting_for_name)
async def process_section_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод названия раздела и создаёт его.
    """
    data = await state.get_data()
    chat_id = data.get('chat_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Получаем название
    name = message.text.strip()

    # Создаём раздел
    section_service = get_section_service()
    success, section_id, error = await section_service.create_section(
        chat_id=chat_id,
        name=name,
        session=session,
        created_by=message.from_user.id
    )

    # Очищаем FSM
    await state.clear()

    if success:
        text = (
            f"✅ Раздел <b>«{name}»</b> создан!\n\n"
            f"Теперь добавьте паттерны для детекции спама этого типа."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⚙️ Настроить раздел",
                callback_data=f"cf:secs:{section_id}"
            )],
            [InlineKeyboardButton(
                text="📂 К списку разделов",
                callback_data=f"cf:sccat:{chat_id}"
            )]
        ])
    else:
        text = f"❌ Ошибка: {error or 'Не удалось создать раздел'}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📂 К списку разделов",
                callback_data=f"cf:sccat:{chat_id}"
            )]
        ])

    # Редактируем сообщение
    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
