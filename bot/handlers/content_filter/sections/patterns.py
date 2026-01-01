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
    EditPatternWeightStates,
    SECTION_PATTERNS_PER_PAGE
)
# Импортируем сервис разделов
from bot.services.content_filter.scam_pattern_service import get_section_service
# Импортируем сервис паттернов для extract_patterns_from_text
from bot.services.content_filter import get_pattern_service
# Импортируем нормализатор для показа нормализованного вида паттерна
from bot.services.content_filter.text_normalizer import get_normalizer

# Создаём роутер для паттернов
patterns_router = Router(name='sections_patterns')


# ============================================================
# СПИСОК ПАТТЕРНОВ
# ============================================================

async def _show_patterns_list(
    callback: CallbackQuery,
    session: AsyncSession,
    section_id: int,
    page: int = 0
) -> None:
    """
    Helper: показывает список паттернов раздела.

    Используется из callback handler и после удаления/добавления.
    """
    section_service = get_section_service()

    # Получаем раздел
    section = await section_service.get_section_by_id(section_id, session)
    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    # Получаем паттерны
    patterns = await section_service.get_section_patterns(section_id, session)

    # Пагинация
    total_patterns = len(patterns)
    total_pages = max(1, (total_patterns + SECTION_PATTERNS_PER_PAGE - 1) // SECTION_PATTERNS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

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

    # Передаём данные паттернов для кнопок: (номер, id, текст)
    pattern_data = [
        (i, p.id, p.pattern)
        for i, p in enumerate(page_patterns, start=start_idx + 1)
    ]
    keyboard = create_section_patterns_menu(section_id, page, total_pages, pattern_data)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


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

    await _show_patterns_list(callback, session, section_id, page)
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
        f"После ввода вы сможете указать вес паттерна."
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
    Показывает превью и запрашивает вес.
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
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secp:{section_id}:0")]
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

    # Получаем нормализатор для показа как паттерн будет выглядеть в БД
    normalizer = get_normalizer()

    # Сохраняем паттерны в FSM и переходим к вводу веса
    await state.update_data(pending_patterns=patterns)
    await state.set_state(AddSectionPatternStates.waiting_for_weight)

    # Формируем превью с показом нормализованного вида
    text = f"📝 <b>Превью паттернов</b>\n\n"
    for i, p in enumerate(patterns[:10], 1):
        # Нормализуем паттерн для показа как он будет искаться
        normalized = normalizer.normalize(p).lower().strip()
        # Показываем оригинал → нормализованный вид
        text += f"{i}. <code>{normalized}</code>\n"
        # Если оригинал отличается - показываем его мелким шрифтом
        if p != normalized:
            text += f"   <i>(из: {p[:30]}{'...' if len(p) > 30 else ''})</i>\n"

    if len(patterns) > 10:
        text += f"\n<i>...и ещё {len(patterns) - 10} паттернов</i>\n"

    text += (
        f"\n<b>Всего:</b> {len(patterns)} паттернов\n\n"
        f"Введите вес (1-1000):\n\n"
        f"<i>Рекомендации:\n"
        f"• 15-30 — обычные фразы\n"
        f"• 50-100 — подозрительные\n"
        f"• 100-200 — явный скам\n"
        f"• 200+ — 100% спам</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secp:{section_id}:0")]
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
        pass


@patterns_router.message(AddSectionPatternStates.waiting_for_weight)
async def process_section_pattern_weight(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод веса и сохраняет паттерны.
    """
    data = await state.get_data()
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')
    patterns = data.get('pending_patterns', [])

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id or not patterns:
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
        text = (
            f"❌ <b>Ошибка</b>\n\n"
            f"Введите целое число от 1 до 1000.\n\n"
            f"<i>Например: 100</i>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cf:secp:{section_id}:0")]
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
            pass
        return

    await state.clear()

    # Получаем нормализатор для показа нормализованного вида
    normalizer = get_normalizer()

    # Добавляем паттерны с указанным весом
    section_service = get_section_service()
    added = 0
    skipped = 0
    # Храним кортежи (ID, нормализованный_паттерн)
    added_patterns = []

    for pattern in patterns:
        # add_section_pattern возвращает (success, pattern_id, error)
        success, pattern_id, error = await section_service.add_section_pattern(
            section_id=section_id,
            pattern=pattern,
            session=session,
            weight=weight,
            created_by=message.from_user.id
        )
        if success:
            added += 1
            # Нормализуем для отображения (такой же как в БД)
            normalized = normalizer.normalize(pattern).lower().strip()
            # Сохраняем ID и нормализованный паттерн
            added_patterns.append((pattern_id, normalized))
        else:
            skipped += 1

    # Формируем ответ с показом ID и нормализованных паттернов
    if added > 0:
        text = f"✅ <b>Добавлено паттернов: {added}</b> (вес: {weight})\n\n"
        for pattern_id, normalized in added_patterns[:10]:
            # Показываем ID и нормализованный паттерн
            text += f"#{pattern_id}: <code>{normalized}</code>\n"
        if len(added_patterns) > 10:
            text += f"\n<i>...и ещё {len(added_patterns) - 10}</i>\n"
        if skipped > 0:
            text += f"\n<i>Пропущено (дубликаты): {skipped}</i>"
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

    # Удаляем паттерн раздела
    success = await section_service.delete_section_pattern(pattern_id, session)

    if success:
        await callback.answer("Паттерн удалён")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

    # Возвращаемся к списку используя helper
    await _show_patterns_list(callback, session, section_id, page=0)


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

    # Возвращаемся к списку используя helper
    await _show_patterns_list(callback, session, section_id, page=0)


# ============================================================
# ИМПОРТ ПАТТЕРНОВ (с extract_patterns_from_text как в главном антискаме)
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpi:\d+$"))
async def start_import_section_patterns(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для импорта паттернов.

    Callback: cf:secpi:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    # Получаем раздел для отображения названия
    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    await state.update_data(
        section_id=section_id,
        instruction_message_id=callback.message.message_id
    )
    await state.set_state(SectionImportPatternsStates.waiting_for_patterns)

    text = (
        f"📥 <b>Импорт паттернов</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n\n"
        f"Вставьте скам-текст целиком.\n"
        f"Система автоматически извлечёт ключевые фразы.\n\n"
        f"💡 Работает как главное меню антискама —\n"
        f"анализирует текст и находит паттерны."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:secs:{section_id}"
        )]
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
    Обрабатывает импорт паттернов - показывает ПРЕВЬЮ перед добавлением.
    Аналогично главному антискаму: сначала показываем список, потом подтверждение.
    """
    data = await state.get_data()
    section_id = data.get('section_id')
    instruction_message_id = data.get('instruction_message_id')

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if not section_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Парсим паттерны с нормализацией (как на главном меню антискама)
    # Используем extract_patterns_from_text для единообразной обработки
    pattern_service = get_pattern_service()
    extracted = pattern_service.extract_patterns_from_text(message.text)

    if not extracted:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"cf:secs:{section_id}"
            )]
        ])
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ Не удалось извлечь паттерны из текста.\n\nПопробуйте вставить другой скам-текст.",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        return

    # Сохраняем извлечённые паттерны в FSM state для подтверждения
    await state.update_data(extracted_patterns=extracted)

    # Показываем превью паттернов (как в главном антискаме)
    text = f"🔍 <b>Найденные паттерны</b>\n\n"
    for i, (phrase, phrase_weight) in enumerate(extracted[:10], 1):
        text += f"{i}. <code>{phrase}</code> (+{phrase_weight})\n"

    if len(extracted) > 10:
        text += f"\n<i>...и ещё {len(extracted) - 10} паттернов</i>\n"

    text += f"\n<b>Всего найдено:</b> {len(extracted)} паттернов"

    # Клавиатура с кнопками подтверждения и отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Импортировать ({len(extracted)} паттернов)",
            callback_data=f"cf:secimc:{section_id}"
        )],
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:secs:{section_id}"
        )]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ПОДТВЕРЖДЕНИЕ ИМПОРТА ПАТТЕРНОВ В РАЗДЕЛ
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secimc:\d+$"))
async def confirm_section_import_patterns(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Подтверждает импорт паттернов в раздел.
    Вызывается после превью, когда пользователь нажимает "Импортировать".

    Callback: cf:secimc:{section_id}
    """
    await callback.answer()

    # Получаем section_id из callback
    parts = callback.data.split(":")
    section_id = int(parts[2])

    # Получаем сохранённые паттерны из FSM state
    data = await state.get_data()
    extracted = data.get('extracted_patterns', [])

    if not extracted:
        await callback.message.edit_text(
            "❌ Данные сессии потеряны. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"cf:secs:{section_id}"
                )]
            ])
        )
        await state.clear()
        return

    # Импортируем паттерны с проверкой дубликатов
    section_service = get_section_service()
    added_count = 0
    skipped_count = 0
    added_patterns = []
    skipped_patterns = []

    for phrase, phrase_weight in extracted:
        success, _, error = await section_service.add_section_pattern(
            section_id=section_id,
            pattern=phrase,
            session=session,
            weight=phrase_weight,
            created_by=callback.from_user.id
        )
        if success:
            added_count += 1
            added_patterns.append(phrase)
        else:
            skipped_count += 1
            if "уже существует" in (error or ""):
                skipped_patterns.append(phrase[:20])

    # Очищаем FSM
    await state.clear()

    # Формируем текст результата с показом добавленных паттернов
    confirm_text = f"✅ <b>Импорт завершён!</b>\n\n"

    # Показываем список добавленных паттернов (до 15 штук)
    if added_patterns:
        confirm_text += f"<b>Добавлено ({added_count}):</b>\n"
        for i, pattern in enumerate(added_patterns[:15], 1):
            confirm_text += f"  {i}. <code>{pattern[:40]}</code>\n"
        if len(added_patterns) > 15:
            confirm_text += f"  <i>...и ещё {len(added_patterns) - 15}</i>\n"

    if skipped_count > 0:
        confirm_text += f"\n<b>Пропущено (дубликаты):</b> {skipped_count}"
        if skipped_patterns and len(skipped_patterns) <= 5:
            confirm_text += f"\n<i>{', '.join(skipped_patterns)}...</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚙️ К настройкам раздела",
            callback_data=f"cf:secs:{section_id}"
        )]
    ])

    try:
        await callback.message.edit_text(
            text=confirm_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except TelegramAPIError:
        await callback.message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# УДАЛЕНИЕ ВСЕХ ПАТТЕРНОВ (альтернативный callback)
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpda:\d+$"))
async def confirm_delete_all_patterns(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает подтверждение удаления всех паттернов раздела.

    Callback: cf:secpda:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    section = await section_service.get_section_by_id(section_id, session)

    if not section:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    patterns_count = await section_service.get_patterns_count(section_id, session)

    if patterns_count == 0:
        await callback.answer("В разделе нет паттернов", show_alert=True)
        return

    text = (
        f"⚠️ <b>Удаление всех паттернов</b>\n\n"
        f"Раздел: <b>{section.name}</b>\n"
        f"Паттернов для удаления: <b>{patterns_count}</b>\n\n"
        f"<b>Вы уверены?</b>\n"
        f"Это действие необратимо."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⚠️ Да, удалить все",
                callback_data=f"cf:secpdac:{section_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="◀️ Отмена",
                callback_data=f"cf:secp:{section_id}:0"
            )
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.callback_query(F.data.regexp(r"^cf:secpdac:\d+$"))
async def delete_all_patterns_confirmed(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет все паттерны раздела после подтверждения.

    Callback: cf:secpdac:{section_id}
    """
    parts = callback.data.split(":")
    section_id = int(parts[2])

    section_service = get_section_service()
    deleted_count = await section_service.delete_all_section_patterns(section_id, session)

    if deleted_count > 0:
        await callback.answer(f"✅ Удалено {deleted_count} паттернов")
    else:
        await callback.answer("Нет паттернов для удаления", show_alert=True)

    # Возвращаемся к списку паттернов используя helper
    await _show_patterns_list(callback, session, section_id, page=0)


# ============================================================
# РЕДАКТИРОВАНИЕ ВЕСА ПАТТЕРНА
# ============================================================

@patterns_router.callback_query(F.data.regexp(r"^cf:secpw:\d+:\d+$"))
async def start_edit_pattern_weight(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Начинает FSM для редактирования веса паттерна.

    Callback: cf:secpw:{pattern_id}:{section_id}
    """
    parts = callback.data.split(":")
    pattern_id = int(parts[2])
    section_id = int(parts[3])

    section_service = get_section_service()
    pattern = await section_service.get_section_pattern_by_id(pattern_id, session)

    if not pattern:
        await callback.answer("❌ Паттерн не найден", show_alert=True)
        return

    # Сохраняем данные в FSM
    await state.update_data(
        pattern_id=pattern_id,
        section_id=section_id,
        bot_message_id=callback.message.message_id,
        bot_chat_id=callback.message.chat.id
    )
    await state.set_state(EditPatternWeightStates.waiting_for_weight)

    text = (
        f"⚖️ <b>Изменение веса паттерна</b>\n\n"
        f"Паттерн: <code>{pattern.pattern}</code>\n"
        f"Текущий вес: <b>{pattern.weight}</b> баллов\n\n"
        f"Введите новый вес (1-1000):\n\n"
        f"<i>Рекомендации:\n"
        f"• 15-30 — обычные фразы\n"
        f"• 50-100 — подозрительные\n"
        f"• 100-200 — явный скам\n"
        f"• 200+ — 100% наркотики/скам</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"cf:secp:{section_id}:0"
            )
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@patterns_router.message(EditPatternWeightStates.waiting_for_weight)
async def process_pattern_weight(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод нового веса паттерна.
    """
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Получаем данные FSM
    data = await state.get_data()
    pattern_id = data.get('pattern_id')
    section_id = data.get('section_id')
    bot_message_id = data.get('bot_message_id')
    bot_chat_id = data.get('bot_chat_id')

    if not pattern_id or not section_id:
        await state.clear()
        return

    # Парсим вес
    try:
        new_weight = int(message.text.strip())
    except (ValueError, AttributeError):
        # Сообщаем об ошибке
        try:
            await message.bot.edit_message_text(
                chat_id=bot_chat_id,
                message_id=bot_message_id,
                text=(
                    f"❌ <b>Ошибка</b>\n\n"
                    f"Введите целое число от 1 до 1000.\n\n"
                    f"<i>Например: 150</i>"
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад",
                            callback_data=f"cf:secp:{section_id}:0"
                        )
                    ]
                ]),
                parse_mode="HTML"
            )
        except TelegramAPIError:
            pass
        return

    # Обновляем вес
    section_service = get_section_service()
    success, error = await section_service.update_pattern_weight(pattern_id, new_weight, session)

    await state.clear()

    if success:
        text = f"✅ Вес паттерна изменён на <b>{new_weight}</b> баллов"
    else:
        text = f"❌ Ошибка: {error or 'неизвестная ошибка'}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️ К паттернам",
                callback_data=f"cf:secp:{section_id}:0"
            )
        ]
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
        pass
