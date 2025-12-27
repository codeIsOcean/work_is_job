# ============================================================
# PATTERNS - УПРАВЛЕНИЕ ПАТТЕРНАМИ СКАМА
# ============================================================
# Этот модуль содержит хендлеры для управления паттернами:
# - scam_patterns_menu: меню паттернов
# - start_add_pattern: добавление паттерна
# - process_add_pattern: обработка ввода
# - start_import_patterns: импорт паттернов
# - show_patterns_list: список с пагинацией
# - delete_pattern_confirmed: удаление паттерна
# - export_patterns: экспорт паттернов
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

# Импортируем модели
from bot.database.models_content_filter import ScamPattern

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_scam_patterns_menu,
    create_patterns_list_menu,
    create_pattern_delete_confirm_menu,
    create_clear_patterns_confirm_menu,
    create_import_preview_menu,
    create_cancel_pattern_input_menu,
    create_import_weight_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и constants
from bot.handlers.content_filter.common import AddPatternStates, PATTERNS_PER_PAGE
# Импортируем сервис паттернов
from bot.services.content_filter import get_pattern_service

# Создаём роутер для паттернов
patterns_router = Router(name='scam_patterns')


# ============================================================
# МЕНЮ ПАТТЕРНОВ СКАМА
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scp:-?\d+$"))
async def scam_patterns_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню управления паттернами скама.

    Callback: cf:scp:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при возврате)
    """
    # Очищаем FSM при возврате в меню
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Получаем количество паттернов
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)

    # Формируем текст
    text = (
        f"📋 <b>Паттерны скама</b>\n\n"
        f"Всего паттернов: {patterns_count}\n\n"
        f"Паттерны — ключевые фразы для обнаружения скама.\n"
        f"Каждый паттерн имеет вес (баллы)."
    )

    # Клавиатура
    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ ПАТТЕРНА (FSM)
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scpa:-?\d+$"))
async def start_add_pattern(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления паттерна.

    Callback: cf:scpa:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(AddPatternStates.waiting_for_pattern)

    text = (
        f"📝 <b>Добавление паттерна</b>\n\n"
        f"Отправьте фразу-паттерн для обнаружения скама.\n"
        f"Можно несколько паттернов, каждый с новой строки."
    )

    keyboard = create_cancel_pattern_input_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.message(AddPatternStates.waiting_for_pattern)
async def process_add_pattern(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод паттерна.

    Args:
        message: Сообщение с паттерном
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id.")
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем паттерны
    text = message.text.strip()
    patterns = [p.strip() for p in text.split('\n') if p.strip()]

    if not patterns:
        await message.answer("❌ Не указано ни одного паттерна.")
        return

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Добавляем паттерны с дефолтным весом
    added = 0
    skipped = 0

    for pattern in patterns:
        try:
            await pattern_service.add_pattern(
                chat_id=chat_id,
                pattern=pattern,
                weight=100,  # дефолтный вес
                pattern_type='custom',
                created_by=message.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            logger.warning(f"Не удалось добавить паттерн '{pattern}': {e}")
            skipped += 1

    await state.clear()

    # Формируем ответ
    if added > 0 and skipped == 0:
        response = f"✅ Добавлено паттернов: {added}"
    elif added > 0 and skipped > 0:
        response = f"✅ Добавлено: {added}, пропущено: {skipped}"
    else:
        response = f"⚠️ Все паттерны уже существуют"

    # Показываем меню паттернов
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)
    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    await message.answer(
        f"{response}\n\n📋 <b>Паттерны скама</b>\nВсего: {patterns_count}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# СПИСОК ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scpl:-?\d+:\d+$"))
async def show_patterns_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список паттернов с пагинацией.

    Callback: cf:scpl:{chat_id}:{page}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Получаем все паттерны
    patterns = await pattern_service.get_patterns(chat_id, session, active_only=False)

    # Вычисляем пагинацию
    total_pages = max(1, (len(patterns) + PATTERNS_PER_PAGE - 1) // PATTERNS_PER_PAGE)
    page = min(page, total_pages - 1)

    # Получаем паттерны для страницы
    start_idx = page * PATTERNS_PER_PAGE
    end_idx = start_idx + PATTERNS_PER_PAGE
    page_patterns = patterns[start_idx:end_idx]

    # Формируем текст
    if not page_patterns:
        text = "📋 <b>Паттерны скама</b>\n\nСписок пуст."
    else:
        text = f"📋 <b>Паттерны скама</b> (стр. {page + 1}/{total_pages})\n\n"
        for i, p in enumerate(page_patterns, start=start_idx + 1):
            weight_emoji = "🔴" if p.weight >= 200 else "🟡" if p.weight >= 100 else "🟢"
            text += f"{i}. {weight_emoji} <code>{p.pattern}</code> ({p.weight})\n"

    # Клавиатура - передаём ID паттернов для кнопок удаления
    pattern_ids = [p.id for p in page_patterns]
    keyboard = create_patterns_list_menu(chat_id, page, total_pages, pattern_ids)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ПАТТЕРНА
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scpd:\d+:-?\d+$"))
async def confirm_delete_pattern(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления паттерна.

    Callback: cf:scpd:{pattern_id}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    chat_id = int(parts[3])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Получаем паттерн
    pattern = await pattern_service.get_pattern_by_id(pattern_id, session)

    if not pattern:
        await callback.answer("❌ Паттерн не найден", show_alert=True)
        return

    text = (
        f"🗑️ <b>Удаление паттерна</b>\n\n"
        f"Паттерн: <code>{pattern.pattern}</code>\n"
        f"Вес: {pattern.weight}\n\n"
        f"Подтвердите удаление."
    )

    keyboard = create_pattern_delete_confirm_menu(pattern_id, chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.callback_query(F.data.regexp(r"^cf:scpdc:\d+:-?\d+$"))
async def delete_pattern_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет паттерн после подтверждения.

    Callback: cf:scpdc:{pattern_id}:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    chat_id = int(parts[3])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Удаляем паттерн
    await pattern_service.delete_pattern(pattern_id, session)

    logger.info(f"[ContentFilter] Удалён паттерн {pattern_id} из чата {chat_id}")

    # Показываем меню паттернов
    patterns_count = await pattern_service.get_patterns_count(chat_id, session)
    keyboard = create_scam_patterns_menu(chat_id, patterns_count)

    await callback.message.edit_text(
        f"✅ Паттерн удалён.\n\n"
        f"📋 <b>Паттерны скама</b>\nВсего: {patterns_count}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Паттерн удалён")


# ============================================================
# ОЧИСТКА ВСЕХ ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scpc:-?\d+$"))
async def confirm_clear_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение очистки всех паттернов.

    Callback: cf:scpc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"⚠️ <b>Удаление всех паттернов</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ паттерны скама?\n\n"
        f"Это действие нельзя отменить."
    )

    keyboard = create_clear_patterns_confirm_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.callback_query(F.data.regexp(r"^cf:scpcc:-?\d+$"))
async def clear_all_patterns_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все паттерны после подтверждения.

    Callback: cf:scpcc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Удаляем все паттерны
    await pattern_service.clear_all_patterns(chat_id, session)

    logger.info(f"[ContentFilter] Удалены все паттерны из чата {chat_id}")

    # Показываем меню паттернов
    keyboard = create_scam_patterns_menu(chat_id, 0)

    await callback.message.edit_text(
        f"✅ Все паттерны удалены.\n\n"
        f"📋 <b>Паттерны скама</b>\nВсего: 0",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Все паттерны удалены")


# ============================================================
# ЭКСПОРТ ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:scpe:-?\d+$"))
async def export_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Экспортирует паттерны в текстовом формате.

    Callback: cf:scpe:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Получаем все паттерны
    patterns = await pattern_service.get_patterns(chat_id, session, active_only=False)

    if not patterns:
        await callback.answer("❌ Нет паттернов для экспорта", show_alert=True)
        return

    # Формируем текст экспорта
    export_text = "📋 Экспорт паттернов:\n\n"
    for p in patterns:
        export_text += f"{p.pattern} ({p.weight})\n"

    # Отправляем как новое сообщение
    await callback.message.answer(export_text)

    await callback.answer("Экспортировано")


# ============================================================
# ИМПОРТ ПАТТЕРНОВ
# ============================================================
# Хендлеры импорта вынесены в отдельный модуль import_patterns.py
# для соблюдения SRP (Правило 30). Там реализован полный flow:
# - Анализ текста (extract_patterns_from_text)
# - Preview найденных паттернов
# - Выбор веса (15/25/40)
# - Подтверждение импорта
# ============================================================
