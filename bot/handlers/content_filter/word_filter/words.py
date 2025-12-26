# ============================================================
# WORDS - УПРАВЛЕНИЕ СЛОВАМИ (DEPRECATED)
# ============================================================
# Этот модуль содержит хендлеры для устаревшего управления словами:
# - words_menu: меню управления словами
# - start_add_word: начало добавления слова
# - process_add_word: обработка ввода слова
# - confirm_add_word: подтверждение добавления
# - edit_add_word: редактирование слова
# - show_words_list: список слов с пагинацией
# - confirm_clear_words: подтверждение очистки
# - clear_all_words: удаление всех слов
# - show_stats: статистика нарушений
#
# DEPRECATED: Используйте categories.py для управления словами
# по категориям (simple, harmful, obfuscated).
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
from sqlalchemy import delete

# Импортируем модели
from bot.database.models_content_filter import FilterWord

# Импортируем клавиатуры
from bot.keyboards.content_filter_keyboards import (
    create_words_menu,
    create_words_list_menu,
    create_clear_words_confirm_menu
)

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states и constants
from bot.handlers.content_filter.common import AddWordStates, WORDS_PER_PAGE
# Импортируем нормализатор для preview
from bot.services.content_filter.text_normalizer import get_normalizer

# Создаём роутер для слов
words_router = Router(name='word_filter_words')


# ============================================================
# МЕНЮ УПРАВЛЕНИЯ СЛОВАМИ
# ============================================================

@words_router.callback_query(F.data.regexp(r"^cf:w:-?\d+$"))
async def words_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """
    Показывает меню управления словами.

    Callback: cf:w:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
        state: FSMContext (для очистки при отмене)
    """
    # Очищаем FSM состояние если оно было активно (при отмене)
    await state.clear()

    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем количество слов
    words_count = await filter_manager.word_filter.get_words_count(chat_id, session)

    text = (
        f"🔤 <b>Запрещённые слова</b>\n\n"
        f"Всего слов: {words_count}\n\n"
        f"Добавьте слова которые будут удаляться из сообщений."
    )

    keyboard = create_words_menu(chat_id, words_count)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ СЛОВА (FSM)
# ============================================================

@words_router.callback_query(F.data.regexp(r"^cf:wa:-?\d+$"))
async def start_add_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает процесс добавления слова (FSM).

    Callback: cf:wa:{chat_id}

    Args:
        callback: CallbackQuery
        state: FSMContext для сохранения состояния
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Сохраняем chat_id в состояние
    await state.update_data(chat_id=chat_id)

    # Переводим в состояние ожидания слова
    await state.set_state(AddWordStates.waiting_for_word)

    text = (
        f"📝 <b>Добавление слова</b>\n\n"
        f"Отправьте слово или фразу которую нужно заблокировать.\n\n"
        f"Можно отправить несколько слов, каждое с новой строки."
    )

    # Кнопка отмены для возврата к меню слов
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:w:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@words_router.message(AddWordStates.waiting_for_word)
async def process_add_word(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод слова от пользователя.
    Показывает preview нормализации и просит подтвердить.

    Args:
        message: Сообщение с текстом слова
        state: FSMContext
        session: Сессия БД
    """
    # Получаем chat_id из состояния
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await message.answer("❌ Ошибка: не найден chat_id. Попробуйте снова.")
        await state.clear()
        return

    # Получаем текст и разбиваем на строки (несколько слов)
    text = message.text.strip()
    words = [w.strip() for w in text.split('\n') if w.strip()]

    if not words:
        await message.answer("❌ Не указано ни одного слова. Попробуйте снова.")
        return

    # Получаем нормализатор для preview
    normalizer = get_normalizer()

    # Формируем preview для каждого слова
    preview_lines = []
    for word in words:
        normalized = normalizer.normalize(word)
        if word.lower() != normalized:
            # Показываем разницу если есть изменения
            preview_lines.append(f"• <code>{word}</code> → <code>{normalized}</code>")
        else:
            preview_lines.append(f"• <code>{word}</code>")

    # Сохраняем слова в состояние для подтверждения
    await state.update_data(words_to_add=words)
    await state.set_state(AddWordStates.waiting_for_confirmation)

    # Формируем сообщение preview
    preview_text = (
        f"🔍 <b>Предпросмотр нормализации</b>\n\n"
        f"Так фильтр будет искать эти слова:\n\n"
        + "\n".join(preview_lines) +
        f"\n\n"
        f"💡 <i>Обфускация (зачёркивание, fullwidth, circled и т.д.) "
        f"будет автоматически нормализована при проверке сообщений.</i>"
    )

    # Кнопки подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Добавить",
                callback_data=f"cf:wac:{chat_id}"  # word add confirm
            ),
            InlineKeyboardButton(
                text="✏️ Изменить",
                callback_data=f"cf:wae:{chat_id}"  # word add edit
            )
        ],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:w:{chat_id}"
        )]
    ])

    await message.answer(preview_text, reply_markup=keyboard, parse_mode="HTML")


@words_router.callback_query(F.data.regexp(r"^cf:wac:-?\d+$"))
async def confirm_add_word(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Подтверждает добавление слов после preview.

    Callback: cf:wac:{chat_id} (word add confirm)

    Args:
        callback: CallbackQuery
        state: FSMContext
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем слова из состояния
    data = await state.get_data()
    words = data.get('words_to_add', [])

    if not words:
        await callback.answer("❌ Нет слов для добавления", show_alert=True)
        await state.clear()
        return

    # Добавляем каждое слово
    added = 0
    skipped = 0

    for word in words:
        try:
            await filter_manager.word_filter.add_word(
                chat_id=chat_id,
                word=word,
                created_by=callback.from_user.id,
                session=session
            )
            added += 1
        except Exception as e:
            # Скорее всего дубликат
            logger.warning(f"Не удалось добавить слово '{word}': {e}")
            skipped += 1

    # Очищаем состояние
    await state.clear()

    # Формируем ответ
    if added > 0 and skipped == 0:
        response = f"✅ Добавлено слов: {added}"
    elif added > 0 and skipped > 0:
        response = f"✅ Добавлено: {added}, пропущено (дубликаты): {skipped}"
    else:
        response = f"⚠️ Все слова уже были добавлены ранее"

    # Показываем меню слов
    words_count = await filter_manager.word_filter.get_words_count(chat_id, session)
    keyboard = create_words_menu(chat_id, words_count)

    try:
        await callback.message.edit_text(
            f"{response}\n\n"
            f"🔤 <b>Запрещённые слова</b>\n"
            f"Всего слов: {words_count}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        pass

    await callback.answer()


@words_router.callback_query(F.data.regexp(r"^cf:wae:-?\d+$"))
async def edit_add_word(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Возвращает к вводу слова для редактирования.

    Callback: cf:wae:{chat_id} (word add edit)

    Args:
        callback: CallbackQuery
        state: FSMContext
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Возвращаем в состояние ввода слова
    await state.set_state(AddWordStates.waiting_for_word)

    text = (
        f"📝 <b>Добавление слова</b>\n\n"
        f"Отправьте слово или фразу которую нужно заблокировать.\n\n"
        f"Можно отправить несколько слов, каждое с новой строки."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:w:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# СПИСОК СЛОВ
# ============================================================

@words_router.callback_query(F.data.regexp(r"^cf:wl:-?\d+:\d+$"))
async def show_words_list(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список слов с пагинацией.

    Callback: cf:wl:{chat_id}:{page}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим данные
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])

    # Получаем все слова
    words = await filter_manager.word_filter.get_words_list(chat_id, session)

    # Вычисляем пагинацию
    total_pages = max(1, (len(words) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
    page = min(page, total_pages - 1)  # Не выходим за границы

    # Получаем слова для текущей страницы
    start_idx = page * WORDS_PER_PAGE
    end_idx = start_idx + WORDS_PER_PAGE
    page_words = words[start_idx:end_idx]

    # Формируем текст
    if not page_words:
        text = "🔤 <b>Запрещённые слова</b>\n\nСписок пуст."
    else:
        text = f"🔤 <b>Запрещённые слова</b> (стр. {page + 1}/{total_pages})\n\n"
        for i, fw in enumerate(page_words, start=start_idx + 1):
            # Показываем слово и категорию если есть
            category_text = f" [{fw.category}]" if fw.category else ""
            text += f"{i}. <code>{fw.word}</code>{category_text}\n"

    # Клавиатура
    keyboard = create_words_list_menu(chat_id, page, total_pages, len(page_words) > 0)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ВСЕХ СЛОВ
# ============================================================

@words_router.callback_query(F.data.regexp(r"^cf:wc:-?\d+$"))
async def confirm_clear_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления всех слов.

    Callback: cf:wc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    text = (
        f"⚠️ <b>Удаление всех слов</b>\n\n"
        f"Вы уверены что хотите удалить ВСЕ запрещённые слова?\n\n"
        f"Это действие нельзя отменить."
    )

    keyboard = create_clear_words_confirm_menu(chat_id)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@words_router.callback_query(F.data.regexp(r"^cf:wcc:-?\d+$"))
async def clear_all_words(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все слова из группы.

    Callback: cf:wcc:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Удаляем все слова
    query = delete(FilterWord).where(FilterWord.chat_id == chat_id)
    await session.execute(query)
    await session.commit()

    logger.info(f"[ContentFilter] Удалены все слова из чата {chat_id}")

    # Показываем меню слов
    keyboard = create_words_menu(chat_id, 0)

    await callback.message.edit_text(
        "✅ Все слова удалены.\n\n"
        "🔤 <b>Запрещённые слова</b>\n"
        "Всего слов: 0",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Все слова удалены")


# ============================================================
# СТАТИСТИКА
# ============================================================

@words_router.callback_query(F.data.regexp(r"^cf:stats:-?\d+$"))
async def show_stats(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает статистику нарушений.

    Callback: cf:stats:{chat_id}

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем статистику за 7 дней
    stats = await filter_manager.get_violation_stats(chat_id, session, days=7)

    # Формируем текст
    text = (
        f"📊 <b>Статистика за 7 дней</b>\n\n"
        f"Всего срабатываний: {stats['total']}\n\n"
    )

    if stats['by_detector']:
        text += "<b>По типу:</b>\n"
        detector_names = {
            'word_filter': '🔤 Слова',
            'scam_detector': '💰 Скам',
            'flood_detector': '📢 Флуд',
            'referral_detector': '👤 Referral'
        }
        for detector, count in stats['by_detector'].items():
            name = detector_names.get(detector, detector)
            text += f"  {name}: {count}\n"
        text += "\n"

    if stats['by_action']:
        text += "<b>По действию:</b>\n"
        action_names = {
            'delete': '🗑️ Удаление',
            'warn': '⚠️ Предупреждение',
            'mute': '🔇 Мут',
            'kick': '👢 Кик',
            'ban': '🚫 Бан'
        }
        for action, count in stats['by_action'].items():
            name = action_names.get(action, action)
            text += f"  {name}: {count}\n"

    # Кнопка назад
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:m:{chat_id}")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()
