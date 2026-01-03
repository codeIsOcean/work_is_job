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

# Импортируем re для валидации regex паттернов
import re

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
    create_import_weight_menu,
    create_pattern_type_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и constants
from bot.handlers.content_filter.common import AddPatternStates, PATTERNS_PER_PAGE
# Импортируем сервис паттернов
from bot.services.content_filter import get_pattern_service
# Импортируем нормализатор и генератор примеров
from bot.services.content_filter.text_normalizer import get_normalizer, generate_catch_examples

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
    Начинает процесс добавления паттерна - показывает выбор типа.

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
    await state.set_state(AddPatternStates.waiting_for_type)

    text = (
        f"📝 <b>Добавление паттерна</b>\n\n"
        f"Выберите тип паттерна:\n\n"
        f"📝 <b>Фраза (fuzzy)</b> — ищет похожий текст\n"
        f"<i>Пример: «травка» найдёт «тр@вк@», «травку»</i>\n\n"
        f"⚙️ <b>Regex (точный)</b> — регулярное выражение\n"
        f"<i>Пример: \\bтравк[ауие]\\b — точное слово</i>"
    )

    keyboard = create_pattern_type_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.callback_query(F.data.regexp(r"^cf:scpat:(phrase|regex):-?\d+$"))
async def select_pattern_type(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Обрабатывает выбор типа паттерна.

    Callback: cf:scpat:{type}:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    pattern_type = parts[2]  # phrase или regex
    chat_id = int(parts[3])

    # Сохраняем тип в FSM
    await state.update_data(pattern_type=pattern_type)
    await state.set_state(AddPatternStates.waiting_for_pattern)

    # Текст зависит от типа
    if pattern_type == 'regex':
        text = (
            f"⚙️ <b>Добавление Regex паттерна</b>\n\n"
            f"Отправьте регулярное выражение.\n"
            f"Можно несколько, каждое с новой строки.\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>\\bтравк[ауие]\\b</code> — слово травка/травку/травки\n"
            f"<code>\\bгаш(иш)?\\b</code> — гаш или гашиш\n"
            f"<code>\\d{{3,}}\\$</code> — сумма от 100$"
        )
    else:
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
    Обрабатывает ввод паттерна - показывает preview.

    Args:
        message: Сообщение с паттерном
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    # Получаем тип паттерна из FSM (phrase → custom, regex → regex)
    selected_type = data.get('pattern_type', 'phrase')
    is_regex = (selected_type == 'regex')

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
    input_text = message.text.strip()
    patterns = [p.strip() for p in input_text.split('\n') if p.strip()]

    if not patterns:
        await message.answer("❌ Не указано ни одного паттерна.")
        return

    # Сохраняем паттерны в FSM для ввода веса
    await state.update_data(pending_patterns=patterns)
    await state.set_state(AddPatternStates.waiting_for_weight)

    # Получаем нормализатор
    normalizer = get_normalizer()

    # Формируем превью
    if is_regex:
        text = f"⚙️ <b>Превью Regex паттернов</b>\n\n"
    else:
        text = f"📝 <b>Превью паттернов</b>\n\n"

    invalid_count = 0
    for i, p in enumerate(patterns[:10], 1):
        # Нормализуем паттерн для показа
        normalized = normalizer.normalize(p).lower().strip()

        if is_regex:
            # Для regex - показываем как есть и проверяем валидность
            try:
                re.compile(p)
                text += f"{i}. <code>{p}</code> ✓\n"
            except re.error as e:
                text += f"{i}. <code>{p}</code> ❌ <i>(ошибка: {str(e)[:30]})</i>\n"
                invalid_count += 1
                continue

            # Показываем как правильно записать и что будет ловиться
            if p != normalized and not any(c in p for c in r'\[](){}*+?.^$|'):
                # Это не regex-синтаксис, а простое слово - показываем подсказку
                text += f"   💡 <i>Запишите как: <code>{normalized}</code></i>\n"
                examples = generate_catch_examples(normalized, max_examples=6)
                if examples:
                    examples_str = ', '.join(examples[:6])
                    text += f"   📋 <i>Ловит: {examples_str}</i>\n"
        else:
            # Для фразы - показываем нормализованный вид
            text += f"{i}. <code>{normalized}</code>\n"
            if p != normalized:
                text += f"   <i>(из: {p[:30]}{'...' if len(p) > 30 else ''})</i>\n"
            # Показываем примеры что будет ловиться
            examples = generate_catch_examples(normalized, max_examples=6)
            if examples and len(normalized) <= 15:
                examples_str = ', '.join(examples[:6])
                text += f"   📋 <i>Ловит: {examples_str}</i>\n"

    if len(patterns) > 10:
        text += f"\n<i>...и ещё {len(patterns) - 10} паттернов</i>\n"

    if invalid_count > 0:
        text += f"\n⚠️ <b>Невалидных regex: {invalid_count}</b> (будут пропущены)\n"

    text += (
        f"\n<b>Всего:</b> {len(patterns)} паттернов\n\n"
        f"Введите вес (1-1000):\n\n"
        f"<i>Рекомендации:\n"
        f"• 15-30 — обычные фразы\n"
        f"• 50-100 — подозрительные\n"
        f"• 100-200 — явный скам\n"
        f"• 200+ — 100% спам</i>"
    )

    # Кнопка "◀️ Назад" возвращает к вводу паттерна
    pattern_type = 'regex' if is_regex else 'phrase'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:scpat:{pattern_type}:{chat_id}")]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@patterns_router.message(AddPatternStates.waiting_for_weight)
async def process_pattern_weight(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод веса и сохраняет паттерны.
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    patterns = data.get('pending_patterns', [])
    selected_type = data.get('pattern_type', 'phrase')
    db_pattern_type = 'regex' if selected_type == 'regex' else 'custom'

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not chat_id or not patterns:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Парсим вес
    try:
        weight = int(message.text.strip())
        if weight < 1 or weight > 1000:
            raise ValueError("Вес вне диапазона")
    except (ValueError, AttributeError):
        # Сообщаем об ошибке, остаёмся в том же состоянии
        pattern_type = 'regex' if selected_type == 'regex' else 'phrase'
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:scpat:{pattern_type}:{chat_id}")]
        ])
        await message.answer(
            f"❌ <b>Ошибка</b>\n\n"
            f"Введите целое число от 1 до 1000.\n\n"
            f"<i>Например: 100</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    await state.clear()

    # Получаем сервис паттернов
    pattern_service = get_pattern_service()

    # Добавляем паттерны с указанным весом
    added = 0
    skipped = 0
    invalid_regex = 0

    for pattern in patterns:
        # Для regex проверяем валидность
        if db_pattern_type == 'regex':
            try:
                re.compile(pattern)
            except re.error as e:
                logger.warning(f"Невалидный regex '{pattern}': {e}")
                invalid_regex += 1
                continue

        try:
            await pattern_service.add_pattern(
                chat_id=chat_id,
                pattern=pattern,
                weight=weight,
                pattern_type=db_pattern_type,
                created_by=message.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            logger.warning(f"Не удалось добавить паттерн '{pattern}': {e}")
            skipped += 1

    # Формируем ответ
    type_label = "regex" if db_pattern_type == 'regex' else "фраз"
    if added > 0 and skipped == 0 and invalid_regex == 0:
        response = f"✅ Добавлено {type_label}-паттернов: {added} (вес: {weight})"
    elif added > 0:
        parts = [f"✅ Добавлено: {added} (вес: {weight})"]
        if skipped > 0:
            parts.append(f"пропущено: {skipped}")
        if invalid_regex > 0:
            parts.append(f"невалидных regex: {invalid_regex}")
        response = ", ".join(parts)
    elif invalid_regex > 0:
        response = f"❌ Все regex невалидны ({invalid_regex})"
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
