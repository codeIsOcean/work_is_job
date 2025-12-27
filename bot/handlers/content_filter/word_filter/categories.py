# ============================================================
# CATEGORIES - УПРАВЛЕНИЕ СЛОВАМИ ПО КАТЕГОРИЯМ
# ============================================================
# Этот модуль содержит хендлеры для управления словами по категориям:
# - show_category_words_list: список слов категории
# - start_add_category_word: добавление слова в категорию
# - process_add_category_word: обработка ввода
# - confirm_add_category_word: подтверждение добавления
# - start_delete_category_word: удаление слова
# - delete_all_category_words: удаление всех слов категории
# - category_advanced_menu: расширенные настройки категории
# - request/process для mute_text, ban_text, delete_delay, notification_delay
#
# Категории:
# - sw (simple_words): Простые слова (реклама, спам)
# - hw (harmful_words): Вредные слова (наркотики, запрещённое)
# - ow (obfuscated_words): Обфускация (l33tspeak)
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
from sqlalchemy import select, delete

# Импортируем модели
from bot.database.models_content_filter import FilterWord

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_category_words_list_menu,
    create_word_filter_settings_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и helpers
from bot.handlers.content_filter.common import (
    AddCategoryWordStates,
    DeleteCategoryWordStates,
    CategoryTextStates,
    CategoryDelayStates,
    WORDS_PER_PAGE,
    parse_delay_seconds
)
# Импортируем нормализатор для preview
from bot.services.content_filter.text_normalizer import get_normalizer

# Создаём роутер для категорий
categories_router = Router(name='word_filter_categories')

# Маппинг категорий на поля БД
CATEGORY_MAP = {
    'sw': 'simple',
    'hw': 'harmful',
    'ow': 'obfuscated'
}
CATEGORY_NAMES = {
    'sw': 'Простые слова',
    'hw': 'Вредные слова',
    'ow': 'Обфускация'
}


# ============================================================
# СПИСОК СЛОВ КАТЕГОРИИ
# ============================================================

@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)l:-?\d+:\d+$"))
async def show_category_words_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список слов категории с пагинацией.

    Callback: cf:{category}l:{chat_id}:{page}
    Примеры: cf:swl:-1001234567890:0, cf:hwl:-1001234567890:1

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    # cf:swl:-1001234567890:0 -> ['cf', 'swl', '-1001234567890', '0']
    category_full = parts[1]  # swl, hwl, owl
    category = category_full[:-1]  # sw, hw, ow
    chat_id = int(parts[2])
    page = int(parts[3])

    # Маппинг категории на значение в БД
    db_category = CATEGORY_MAP.get(category, 'simple')
    category_name = CATEGORY_NAMES.get(category, 'Слова')

    # Получаем слова категории
    result = await session.execute(
        select(FilterWord)
        .where(FilterWord.chat_id == chat_id)
        .where(FilterWord.category == db_category)
        .order_by(FilterWord.id.desc())
    )
    words = result.scalars().all()

    # Вычисляем пагинацию
    total_pages = max(1, (len(words) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
    page = min(page, total_pages - 1)  # Не выходим за границы

    # Получаем слова для текущей страницы
    start_idx = page * WORDS_PER_PAGE
    end_idx = start_idx + WORDS_PER_PAGE
    page_words = words[start_idx:end_idx]

    # Формируем текст
    if not page_words:
        text = f"📝 <b>{category_name}</b>\n\nСписок пуст."
    else:
        text = f"📝 <b>{category_name}</b> (стр. {page + 1}/{total_pages})\n\n"
        for i, fw in enumerate(page_words, start=start_idx + 1):
            # Показываем слово и тип матчинга
            match_info = ""
            if fw.match_type == 'exact':
                match_info = " [точное]"
            elif fw.match_type == 'contains':
                match_info = " [вхождение]"
            text += f"{i}. <code>{fw.word}</code>{match_info}\n"

    # Клавиатура
    keyboard = create_category_words_list_menu(chat_id, category, page, total_pages)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ СЛОВА В КАТЕГОРИЮ (FSM)
# ============================================================

@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)w:-?\d+$"))
async def start_add_category_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления слова в категорию.

    Callback: cf:{category}w:{chat_id}
    Примеры: cf:sww:-1001234567890

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_full = parts[1]  # sww, hww, oww
    category = category_full[:-1]  # sw, hw, ow
    chat_id = int(parts[2])

    category_name = CATEGORY_NAMES.get(category, 'Слова')

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        category=category,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(AddCategoryWordStates.waiting_for_word)

    text = (
        f"📝 <b>Добавление слова: {category_name}</b>\n\n"
        f"Отправьте слово или фразу.\n"
        f"Можно несколько слов, каждое с новой строки."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:{category}l:{chat_id}:0"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@categories_router.message(AddCategoryWordStates.waiting_for_word)
async def process_add_category_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод слова для категории.
    Показывает preview и просит подтвердить.

    Args:
        message: Сообщение со словом
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')

    if not chat_id or not category:
        await message.answer("❌ Ошибка: не найдены данные. Попробуйте снова.")
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем текст и разбиваем на строки
    text = message.text.strip()
    words = [w.strip() for w in text.split('\n') if w.strip()]

    if not words:
        await message.answer("❌ Не указано ни одного слова.")
        return

    # Получаем нормализатор для preview
    normalizer = get_normalizer()

    # Формируем preview
    preview_lines = []
    for word in words:
        normalized = normalizer.normalize(word)
        if word.lower() != normalized:
            preview_lines.append(f"• <code>{word}</code> → <code>{normalized}</code>")
        else:
            preview_lines.append(f"• <code>{word}</code>")

    # Сохраняем слова в состояние
    await state.update_data(words_to_add=words, match_type='contains')
    await state.set_state(AddCategoryWordStates.waiting_for_confirmation)

    category_name = CATEGORY_NAMES.get(category, 'Слова')

    preview_text = (
        f"🔍 <b>Предпросмотр: {category_name}</b>\n\n"
        + "\n".join(preview_lines) +
        f"\n\n"
        f"Тип поиска: <b>вхождение</b> (слово внутри текста)"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Добавить",
                callback_data=f"cf:{category}wc:{chat_id}"
            ),
            InlineKeyboardButton(
                text="⚙️ Точное",
                callback_data=f"cf:{category}wm:{chat_id}"
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:{category}l:{chat_id}:0"
        )]
    ])

    await message.answer(preview_text, reply_markup=keyboard, parse_mode="HTML")


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)wc:-?\d+$"))
async def confirm_add_category_word(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Подтверждает добавление слов в категорию.

    Callback: cf:{category}wc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_full = parts[1]  # swwc, hwwc, owwc
    category = category_full[:-2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Получаем данные из FSM
    data = await state.get_data()
    words = data.get('words_to_add', [])
    match_type = data.get('match_type', 'contains')

    if not words:
        await callback.answer("❌ Нет слов для добавления", show_alert=True)
        await state.clear()
        return

    # Маппинг категории на значение в БД
    db_category = CATEGORY_MAP.get(category, 'simple')

    # Добавляем каждое слово
    added = 0
    skipped = 0
    normalizer = get_normalizer()

    for word in words:
        # Проверяем дубликат
        existing = await session.execute(
            select(FilterWord).where(
                FilterWord.chat_id == chat_id,
                FilterWord.word == word.lower(),
                FilterWord.category == db_category
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        # Создаём запись
        normalized = normalizer.normalize(word)
        new_word = FilterWord(
            chat_id=chat_id,
            word=word.lower(),
            normalized=normalized,
            category=db_category,
            match_type=match_type,
            created_by=callback.from_user.id
        )
        session.add(new_word)
        added += 1

    await session.commit()
    await state.clear()

    # Формируем ответ
    if added > 0 and skipped == 0:
        response = f"✅ Добавлено: {added}"
    elif added > 0 and skipped > 0:
        response = f"✅ Добавлено: {added}, пропущено: {skipped}"
    else:
        response = f"⚠️ Все слова уже были добавлены"

    # Показываем список слов категории
    result = await session.execute(
        select(FilterWord)
        .where(FilterWord.chat_id == chat_id)
        .where(FilterWord.category == db_category)
    )
    total_words = len(result.scalars().all())

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    total_pages = max(1, (total_words + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
    keyboard = create_category_words_list_menu(chat_id, category, 0, total_pages)

    try:
        await callback.message.edit_text(
            f"{response}\n\n"
            f"📝 <b>{category_name}</b>\n"
            f"Всего слов: {total_words}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        pass

    await callback.answer()


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)wm:-?\d+$"))
async def select_word_match_type(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Переключает тип матчинга между 'contains' и 'exact'.

    Callback: cf:{category}wm:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_full = parts[1]  # swwm, hwwm, owwm
    category = category_full[:-2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Получаем данные из FSM
    data = await state.get_data()
    current_match_type = data.get('match_type', 'contains')
    words = data.get('words_to_add', [])

    # Переключаем тип
    new_match_type = 'exact' if current_match_type == 'contains' else 'contains'
    await state.update_data(match_type=new_match_type)

    # Обновляем preview
    normalizer = get_normalizer()
    preview_lines = []
    for word in words:
        normalized = normalizer.normalize(word)
        if word.lower() != normalized:
            preview_lines.append(f"• <code>{word}</code> → <code>{normalized}</code>")
        else:
            preview_lines.append(f"• <code>{word}</code>")

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    match_text = "точное совпадение" if new_match_type == 'exact' else "вхождение"

    preview_text = (
        f"🔍 <b>Предпросмотр: {category_name}</b>\n\n"
        + "\n".join(preview_lines) +
        f"\n\n"
        f"Тип поиска: <b>{match_text}</b>"
    )

    button_text = "⚙️ Вхождение" if new_match_type == 'exact' else "⚙️ Точное"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Добавить",
                callback_data=f"cf:{category}wc:{chat_id}"
            ),
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"cf:{category}wm:{chat_id}"
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:{category}l:{chat_id}:0"
        )]
    ])

    try:
        await callback.message.edit_text(preview_text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer(f"Тип поиска: {match_text}")


# ============================================================
# УДАЛЕНИЕ СЛОВ ИЗ КАТЕГОРИИ
# ============================================================

@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)dw:-?\d+$"))
async def start_delete_category_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс удаления слова из категории по вводу.

    Callback: cf:{category}dw:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_full = parts[1]  # swdw, hwdw, owdw
    category = category_full[:-2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_name = CATEGORY_NAMES.get(category, 'Слова')

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        category=category,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(DeleteCategoryWordStates.waiting_for_word)

    text = (
        f"🗑️ <b>Удаление слова: {category_name}</b>\n\n"
        f"Отправьте слово которое нужно удалить.\n"
        f"Можно несколько слов, каждое с новой строки."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:{category}l:{chat_id}:0"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@categories_router.message(DeleteCategoryWordStates.waiting_for_word)
async def process_delete_category_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод слов для удаления.

    Args:
        message: Сообщение со словами
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await message.answer("❌ Ошибка: не найдены данные.")
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем слова для удаления
    text = message.text.strip()
    words_to_delete = [w.strip().lower() for w in text.split('\n') if w.strip()]

    if not words_to_delete:
        await message.answer("❌ Не указано ни одного слова.")
        return

    # Маппинг категории на значение в БД
    db_category = CATEGORY_MAP.get(category, 'simple')

    # Удаляем слова
    deleted = 0
    not_found = 0

    for word in words_to_delete:
        result = await session.execute(
            delete(FilterWord).where(
                FilterWord.chat_id == chat_id,
                FilterWord.word == word,
                FilterWord.category == db_category
            )
        )
        if result.rowcount > 0:
            deleted += 1
        else:
            not_found += 1

    await session.commit()
    await state.clear()

    # Формируем ответ
    if deleted > 0 and not_found == 0:
        response = f"✅ Удалено: {deleted}"
    elif deleted > 0 and not_found > 0:
        response = f"✅ Удалено: {deleted}, не найдено: {not_found}"
    else:
        response = f"⚠️ Слова не найдены"

    # Показываем список слов категории
    result = await session.execute(
        select(FilterWord)
        .where(FilterWord.chat_id == chat_id)
        .where(FilterWord.category == db_category)
    )
    total_words = len(result.scalars().all())

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    total_pages = max(1, (total_words + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
    keyboard = create_category_words_list_menu(chat_id, category, 0, total_pages)

    try:
        await message.bot.edit_message_text(
            text=f"{response}\n\n📝 <b>{category_name}</b>\nВсего слов: {total_words}",
            chat_id=message.chat.id,
            message_id=instruction_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(response)


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)da:-?\d+$"))
async def delete_all_category_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все слова из категории.

    Callback: cf:{category}da:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    category_full = parts[1]  # swda, hwda, owda
    category = category_full[:-2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Маппинг категории на значение в БД
    db_category = CATEGORY_MAP.get(category, 'simple')

    # Удаляем все слова категории
    await session.execute(
        delete(FilterWord).where(
            FilterWord.chat_id == chat_id,
            FilterWord.category == db_category
        )
    )
    await session.commit()

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Удалены все слова категории {db_category} из чата {chat_id}")

    # Возвращаемся к настройкам фильтра слов
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    text = (
        f"✅ Все слова категории «{category_name}» удалены.\n\n"
        f"🔤 <b>Настройки фильтра слов</b>\n\n"
        f"Три категории с разными действиями:\n"
        f"• 📝 Простые — реклама, спам\n"
        f"• 💊 Вредные — наркотики, запрещённое\n"
        f"• 🔀 Обфускация — l33tspeak обходы"
    )
    keyboard = create_word_filter_settings_menu(chat_id, settings)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Все слова удалены")


# ============================================================
# КАСТОМНЫЙ ТЕКСТ МУТА ДЛЯ КАТЕГОРИИ
# ============================================================

# Маппинг категории на поле в БД
MUTE_TEXT_FIELD_MAP = {
    'sw': 'simple_words_mute_text',
    'hw': 'harmful_words_mute_text',
    'ow': 'obfuscated_words_mute_text'
}

NOTIFICATION_DELAY_FIELD_MAP = {
    'sw': 'simple_words_notification_delete_delay',
    'hw': 'harmful_words_notification_delete_delay',
    'ow': 'obfuscated_words_notification_delete_delay'
}


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)mt:-?\d+$"))
async def request_mute_text_input(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Показывает меню для ввода кастомного текста мута.

    Callback: cf:{category}mt:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    category = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_name = CATEGORY_NAMES.get(category, 'Слова')

    # Получаем текущий текст
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = getattr(settings, MUTE_TEXT_FIELD_MAP[category], None)

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        category=category,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(CategoryTextStates.waiting_for_mute_text)

    text = (
        f"📝 <b>Текст мута: {category_name}</b>\n\n"
        f"Отправьте текст уведомления при муте.\n\n"
        f"<b>Плейсхолдеры:</b>\n"
        f"• <code>%user%</code> — упоминание пользователя\n"
        f"• <code>%time%</code> — время мута (например, 1ч)\n\n"
        f"<b>Пример:</b>\n"
        f"<i>%user%, вы получили мут на %time% за нарушение правил.</i>\n\n"
    )
    if current_text:
        text += f"<b>Текущий текст:</b>\n<i>{current_text[:200]}</i>"
    else:
        text += "<b>Текущий текст:</b> <i>не задан (стандартный)</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑️ Сбросить",
                callback_data=f"cf:{category}mtc:{chat_id}"
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category}a:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@categories_router.message(CategoryTextStates.waiting_for_mute_text)
async def process_mute_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод кастомного текста мута.

    Args:
        message: Сообщение с текстом
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await message.answer("❌ Ошибка: не найдены данные.")
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем текст и ограничиваем 500 символов
    mute_text = message.text.strip()[:500]

    # Сохраняем в БД
    field_name = MUTE_TEXT_FIELD_MAP[category]
    await filter_manager.update_settings(chat_id, session, **{field_name: mute_text})

    await state.clear()

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Установлен текст мута для {category}: chat={chat_id}")

    # Возвращаемся в меню действия категории
    # Используем callback simulation
    from bot.keyboards.content_filter_keyboards import create_category_action_menu

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    action_field_map = {'sw': 'simple_words_action', 'hw': 'harmful_words_action', 'ow': 'obfuscated_words_action'}
    duration_field_map = {'sw': 'simple_words_mute_duration', 'hw': 'harmful_words_mute_duration', 'ow': 'obfuscated_words_mute_duration'}

    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    notification_delay = getattr(settings, NOTIFICATION_DELAY_FIELD_MAP[category], None)

    text = (
        f"✅ Текст мута сохранён!\n\n"
        f"⚡ <b>Действие: {category_name}</b>\n\n"
        f"Выберите действие при срабатывании:\n"
        f"• 🗑️ Удалить — только удалить сообщение\n"
        f"• 🔇 Мут — удалить + мут на время\n"
        f"• 🚫 Бан — удалить + бан"
    )

    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        mute_text, notification_delay
    )

    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=instruction_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer("✅ Текст мута сохранён!")


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)mtc:-?\d+$"))
async def clear_mute_text(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Сбрасывает кастомный текст мута.

    Callback: cf:{category}mtc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    category = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Сбрасываем в БД
    field_name = MUTE_TEXT_FIELD_MAP[category]
    await filter_manager.update_settings(chat_id, session, **{field_name: None})

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Сброшен текст мута для {category}: chat={chat_id}")

    # Возвращаемся в меню действия категории
    from bot.keyboards.content_filter_keyboards import create_category_action_menu

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    action_field_map = {'sw': 'simple_words_action', 'hw': 'harmful_words_action', 'ow': 'obfuscated_words_action'}
    duration_field_map = {'sw': 'simple_words_mute_duration', 'hw': 'harmful_words_mute_duration', 'ow': 'obfuscated_words_mute_duration'}

    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    notification_delay = getattr(settings, NOTIFICATION_DELAY_FIELD_MAP[category], None)

    text = (
        f"🗑️ Текст мута сброшен!\n\n"
        f"⚡ <b>Действие: {category_name}</b>\n\n"
        f"Выберите действие при срабатывании:\n"
        f"• 🗑️ Удалить — только удалить сообщение\n"
        f"• 🔇 Мут — удалить + мут на время\n"
        f"• 🚫 Бан — удалить + бан"
    )

    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        None, notification_delay
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Текст мута сброшен")


# ============================================================
# ЗАДЕРЖКА УДАЛЕНИЯ УВЕДОМЛЕНИЯ ДЛЯ КАТЕГОРИИ
# ============================================================

@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)nd:-?\d+$"))
async def request_notification_delay_input(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Показывает меню для ввода задержки удаления уведомления.

    Callback: cf:{category}nd:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    category = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    category_name = CATEGORY_NAMES.get(category, 'Слова')

    # Получаем текущую задержку
    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_delay = getattr(settings, NOTIFICATION_DELAY_FIELD_MAP[category], None)

    # Сохраняем в FSM
    await state.update_data(
        chat_id=chat_id,
        category=category,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(CategoryDelayStates.waiting_for_notification_delay)

    delay_text = f"{current_delay}с" if current_delay else "не удаляется"

    text = (
        f"⏰ <b>Удаление уведомления: {category_name}</b>\n\n"
        f"Через сколько секунд удалять уведомление бота после мута?\n\n"
        f"Выберите кнопку или <b>отправьте своё значение</b>.\n\n"
        f"<b>Форматы:</b>\n"
        f"• <code>30</code> или <code>30s</code> — 30 секунд\n"
        f"• <code>5min</code> — 5 минут\n"
        f"• <code>1h</code> — 1 час\n\n"
        f"<b>Текущее:</b> {delay_text}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="30с", callback_data=f"cf:{category}nds:30:{chat_id}"),
            InlineKeyboardButton(text="1мин", callback_data=f"cf:{category}nds:60:{chat_id}"),
            InlineKeyboardButton(text="5мин", callback_data=f"cf:{category}nds:300:{chat_id}")
        ],
        [
            InlineKeyboardButton(
                text="🗑️ Не удалять",
                callback_data=f"cf:{category}ndc:{chat_id}"
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cf:{category}a:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)nds:\d+:-?\d+$"))
async def set_notification_delay_quick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Быстрая установка задержки удаления уведомления.

    Callback: cf:{category}nds:{seconds}:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    category = parts[1][:2]  # sw, hw, ow
    delay_seconds = int(parts[2])
    chat_id = int(parts[3])

    # Сохраняем в БД
    field_name = NOTIFICATION_DELAY_FIELD_MAP[category]
    await filter_manager.update_settings(chat_id, session, **{field_name: delay_seconds})

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Установлена задержка уведомления {delay_seconds}s для {category}: chat={chat_id}")

    # Возвращаемся в меню действия категории
    from bot.keyboards.content_filter_keyboards import create_category_action_menu

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    action_field_map = {'sw': 'simple_words_action', 'hw': 'harmful_words_action', 'ow': 'obfuscated_words_action'}
    duration_field_map = {'sw': 'simple_words_mute_duration', 'hw': 'harmful_words_mute_duration', 'ow': 'obfuscated_words_mute_duration'}

    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    mute_text = getattr(settings, MUTE_TEXT_FIELD_MAP[category], None)

    text = (
        f"✅ Задержка установлена: {delay_seconds}с\n\n"
        f"⚡ <b>Действие: {category_name}</b>"
    )

    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        mute_text, delay_seconds
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer(f"Задержка: {delay_seconds}с")


@categories_router.message(CategoryDelayStates.waiting_for_notification_delay)
async def process_notification_delay_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ручной ввод задержки удаления уведомления.

    Args:
        message: Сообщение с задержкой
        state: FSMContext
        session: Сессия БД
    """
    # Получаем данные из FSM
    data = await state.get_data()
    chat_id = data.get('chat_id')
    category = data.get('category')
    instruction_message_id = data.get('instruction_message_id')

    if not chat_id or not category:
        await message.answer("❌ Ошибка: не найдены данные.")
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Парсим задержку
    delay_seconds = parse_delay_seconds(message.text.strip())

    if delay_seconds is None:
        await message.answer(
            "❌ Неверный формат. Используйте:\n"
            "• 30 или 30s — секунды\n"
            "• 5min — минуты\n"
            "• 1h — часы"
        )
        return

    # Сохраняем в БД
    field_name = NOTIFICATION_DELAY_FIELD_MAP[category]
    await filter_manager.update_settings(chat_id, session, **{field_name: delay_seconds})

    await state.clear()

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Установлена задержка уведомления {delay_seconds}s для {category}: chat={chat_id}")

    # Возвращаемся в меню действия категории
    from bot.keyboards.content_filter_keyboards import create_category_action_menu

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    action_field_map = {'sw': 'simple_words_action', 'hw': 'harmful_words_action', 'ow': 'obfuscated_words_action'}
    duration_field_map = {'sw': 'simple_words_mute_duration', 'hw': 'harmful_words_mute_duration', 'ow': 'obfuscated_words_mute_duration'}

    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    mute_text = getattr(settings, MUTE_TEXT_FIELD_MAP[category], None)

    text = (
        f"✅ Задержка установлена: {delay_seconds}с\n\n"
        f"⚡ <b>Действие: {category_name}</b>"
    )

    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        mute_text, delay_seconds
    )

    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=instruction_message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await message.answer(f"✅ Задержка: {delay_seconds}с")


@categories_router.callback_query(F.data.regexp(r"^cf:(sw|hw|ow)ndc:-?\d+$"))
async def clear_notification_delay(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Сбрасывает задержку удаления уведомления (не удалять).

    Callback: cf:{category}ndc:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    await state.clear()

    # Парсим данные
    parts = callback.data.split(":")
    category = parts[1][:2]  # sw, hw, ow
    chat_id = int(parts[2])

    # Сбрасываем в БД
    field_name = NOTIFICATION_DELAY_FIELD_MAP[category]
    await filter_manager.update_settings(chat_id, session, **{field_name: None})

    category_name = CATEGORY_NAMES.get(category, 'Слова')
    logger.info(f"[ContentFilter] Сброшена задержка уведомления для {category}: chat={chat_id}")

    # Возвращаемся в меню действия категории
    from bot.keyboards.content_filter_keyboards import create_category_action_menu

    settings = await filter_manager.get_or_create_settings(chat_id, session)

    action_field_map = {'sw': 'simple_words_action', 'hw': 'harmful_words_action', 'ow': 'obfuscated_words_action'}
    duration_field_map = {'sw': 'simple_words_mute_duration', 'hw': 'harmful_words_mute_duration', 'ow': 'obfuscated_words_mute_duration'}

    current_action = getattr(settings, action_field_map[category], 'delete')
    current_duration = getattr(settings, duration_field_map[category], None)
    mute_text = getattr(settings, MUTE_TEXT_FIELD_MAP[category], None)

    text = (
        f"🗑️ Уведомление не будет удаляться\n\n"
        f"⚡ <b>Действие: {category_name}</b>"
    )

    keyboard = create_category_action_menu(
        chat_id, category, current_action, current_duration,
        mute_text, None
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer("Уведомление не будет удаляться")
