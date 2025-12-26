# ============================================================
# PATTERNS - ПАТТЕРНЫ РАЗДЕЛА
# ============================================================
# Этот модуль содержит хендлеры для управления паттернами раздела:
# - section_patterns_list: список паттернов
# - start_add_section_pattern: добавление паттерна (FSM)
# - process_section_pattern: обработка паттерна
# - delete_section_pattern: удаление паттерна
# - import_section_patterns: импорт паттернов
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
    create_section_patterns_menu,
    create_cancel_section_pattern_input_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import logger
# Импортируем FSM states и константы
from bot.handlers.content_filter.common import (
    AddSectionPatternStates,
    SectionImportPatternsStates,
    SECTION_PATTERNS_PER_PAGE
)
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service

# Создаём роутер для паттернов
patterns_router = Router(name='sections_patterns')


# ============================================================
# СПИСОК ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secp:\d+:\d+$"))
async def section_patterns_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список паттернов раздела с пагинацией.

    Callback: cf:secp:{section_id}:{page}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])
    page = int(parts[3])

    section_service = get_section_service()

    # Получаем раздел
    section = await section_service.get_section_by_id(section_id, session)
    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Получаем паттерны
    patterns = await section_service.get_section_patterns(section_id, session)

    # Вычисляем пагинацию
    total_pages = max(1, (len(patterns) + SECTION_PATTERNS_PER_PAGE - 1) // SECTION_PATTERNS_PER_PAGE)
    page = min(page, total_pages - 1)

    # Получаем паттерны для страницы
    start_idx = page * SECTION_PATTERNS_PER_PAGE
    end_idx = start_idx + SECTION_PATTERNS_PER_PAGE
    page_patterns = patterns[start_idx:end_idx]

    # Формируем текст
    if not page_patterns:
        text = (
            f"📋 <b>Паттерны раздела «{section.name}»</b>\n\n"
            f"Список пуст. Добавьте паттерны для детекции спама."
        )
    else:
        text = f"📋 <b>Паттерны раздела «{section.name}»</b> (стр. {page + 1}/{total_pages})\n\n"
        for i, p in enumerate(page_patterns, start=start_idx + 1):
            weight_emoji = "🔴" if p.weight >= 200 else "🟡" if p.weight >= 100 else "🟢"
            text += f"{i}. {weight_emoji} <code>{p.pattern}</code> ({p.weight})\n"

    keyboard = create_section_patterns_menu(section_id, page, total_pages, len(page_patterns) > 0)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ ПАТТЕРНА
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpa:\d+$"))
async def start_add_section_pattern(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для добавления паттерна в раздел.

    Callback: cf:secpa:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(AddSectionPatternStates.waiting_for_pattern)

    text = (
        f"📝 <b>Добавление паттерна</b>\n\n"
        f"Отправьте фразу или слово для детекции.\n\n"
        f"<i>Можно отправить несколько фраз, каждую с новой строки.</i>\n\n"
        f"Каждый паттерн добавится с весом 100 баллов."
    )

    keyboard = create_cancel_section_pattern_input_menu(section_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.message(AddSectionPatternStates.waiting_for_pattern)
async def process_section_pattern(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод паттерна раздела.
    """
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Парсим паттерны (каждая строка = отдельный паттерн)
    patterns_text = message.text.strip()
    patterns = [p.strip() for p in patterns_text.split('\n') if p.strip()]

    if not patterns:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secp:{section_id}:0")]
        ])
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text="❌ Не указано ни одного паттерна.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    await state.clear()

    # Добавляем паттерны
    section_service = get_section_service()
    added = 0
    skipped = 0

    for pattern in patterns:
        success, _, error = await section_service.add_pattern(
            section_id=section_id,
            pattern=pattern,
            weight=100,
            session=session,
            created_by=message.from_user.id
        )
        if success:
            added += 1
        else:
            skipped += 1

    # Формируем ответ
    if added > 0 and skipped == 0:
        text = f"✅ Добавлено паттернов: {added}"
    elif added > 0 and skipped > 0:
        text = f"✅ Добавлено: {added}, пропущено: {skipped}"
    else:
        text = f"⚠️ Все паттерны уже существуют"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 К списку паттернов", callback_data=f"cf:secp:{section_id}:0")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# УДАЛЕНИЕ ПАТТЕРНА
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpd:\d+:\d+$"))
async def delete_section_pattern(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет паттерн раздела.

    Callback: cf:secpd:{pattern_id}:{section_id}
    """
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()

    # Удаляем паттерн
    success = await section_service.delete_pattern(pattern_id, session)

    if success:
        await callback.answer("Паттерн удалён")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

    # Возвращаемся к списку
    callback.data = f"cf:secp:{section_id}:0"
    await section_patterns_list(callback, session)


# ============================================================
# ОЧИСТКА ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpc:\d+$"))
async def confirm_clear_section_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение очистки всех паттернов раздела.

    Callback: cf:secpc:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    text = (
        f"⚠️ <b>Удаление всех паттернов</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ паттерны раздела?\n\n"
        f"Это действие нельзя отменить."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"cf:secpcc:{section_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:secp:{section_id}:0")
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.callback_query(F.data.regexp(r"^cf:secpcc:\d+$"))
async def clear_section_patterns_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все паттерны раздела после подтверждения.

    Callback: cf:secpcc:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()

    # Удаляем все паттерны
    success = await section_service.clear_section_patterns(section_id, session)

    if success:
        await callback.answer("✅ Все паттерны удалены")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)

    # Возвращаемся к списку
    callback.data = f"cf:secp:{section_id}:0"
    await section_patterns_list(callback, session)


# ============================================================
# ИМПОРТ ПАТТЕРНОВ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpi:\d+$"))
async def start_import_section_patterns(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает FSM для импорта паттернов.

    Callback: cf:secpi:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    await state.update_data(
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(SectionImportPatternsStates.waiting_for_patterns)

    text = (
        f"📥 <b>Импорт паттернов</b>\n\n"
        f"Отправьте список паттернов для импорта.\n\n"
        f"Форматы:\n"
        f"• Каждая строка = паттерн (вес 100)\n"
        f"• <code>паттерн (200)</code> — с указанием веса\n\n"
        f"<i>Дубликаты будут пропущены.</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cf:secp:{section_id}:0")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.message(SectionImportPatternsStates.waiting_for_patterns)
async def process_import_section_patterns(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает импорт паттернов.
    """
    import re

    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    await state.clear()

    # Парсим паттерны
    lines = message.text.strip().split('\n')
    section_service = get_section_service()

    added = 0
    skipped = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Пробуем парсить формат "паттерн (вес)"
        match = re.match(r'^(.+?)\s*\((\d+)\)$', line)
        if match:
            pattern = match.group(1).strip()
            weight = int(match.group(2))
        else:
            pattern = line
            weight = 100

        if pattern:
            success, _, _ = await section_service.add_pattern(
                section_id=section_id,
                pattern=pattern,
                weight=weight,
                session=session,
                created_by=message.from_user.id
            )
            if success:
                added += 1
            else:
                skipped += 1

    # Формируем ответ
    if added > 0:
        text = f"✅ Импортировано: {added}"
        if skipped > 0:
            text += f", пропущено: {skipped}"
    else:
        text = "⚠️ Не удалось импортировать ни одного паттерна"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 К списку паттернов", callback_data=f"cf:secp:{section_id}:0")]
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=bot_chat_id,
            message_id=bot_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
