# ============================================================
# ADVANCED - РАСШИРЕННЫЕ НАСТРОЙКИ АНТИФЛУДА
# ============================================================
# Этот модуль содержит хендлеры для расширенных настроек:
# - flood_advanced_menu: меню "Дополнительно"
# - Ручной ввод max_repeats, time_window
# - Тексты уведомлений (warn, mute, ban)
# - Задержки (delete_delay, notification_delay)
# - Настройки "любые сообщения" (limit, window)
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

# Импортируем общие объекты
from bot.handlers.content_filter.shared import filter_manager, logger
# Импортируем FSM states
from bot.handlers.content_filter.common import (
    FloodCustomInputStates,
    FloodTextStates,
    FloodDelayStates,
    FloodAnySettingsStates
)

# Создаём роутер для расширенных настроек
advanced_router = Router(name='flood_advanced')


# ============================================================
# МЕНЮ "ДОПОЛНИТЕЛЬНО"
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:fladv:-?\d+$"))
async def flood_advanced_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает расширенные настройки антифлуда.

    Callback: cf:fladv:{chat_id}

    Настройки:
    - Настройки "любые сообщения": лимит и окно
    - Текст при предупреждении
    - Текст при муте
    - Текст при бане
    - Задержка удаления сообщения
    - Автоудаление уведомления

    Args:
        callback: CallbackQuery
        session: Сессия БД
    """
    # Парсим chat_id из callback данных
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Получаем настройки группы из БД
    settings = await filter_manager.get_or_create_settings(chat_id, session)

    # ============================================================
    # НАСТРОЙКИ БАЗОВОГО АНТИФЛУДА
    # ============================================================
    max_repeats = settings.flood_max_repeats or 3
    time_window = settings.flood_time_window or 60
    flood_action = settings.flood_action or 'mute'
    mute_duration = settings.flood_mute_duration

    # Форматируем действие
    action_map = {
        'delete': '🗑️ Удалить',
        'warn': '⚠️ Предупредить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }
    action_text = action_map.get(flood_action, '🔇 Мут')
    if flood_action == 'mute' and mute_duration:
        if mute_duration < 60:
            action_text += f" ({mute_duration}мин)"
        elif mute_duration < 1440:
            action_text += f" ({mute_duration // 60}ч)"
        else:
            action_text += f" ({mute_duration // 1440}д)"

    # ============================================================
    # НАСТРОЙКИ "ЛЮБЫЕ СООБЩЕНИЯ"
    # ============================================================
    any_limit = settings.flood_any_max_messages or 5
    any_window = settings.flood_any_time_window or 10

    # Форматируем кастомные тексты уведомлений
    warn_text = settings.flood_warn_text or "По умолчанию"
    if len(warn_text) > 30:
        warn_text = warn_text[:30] + "..."

    mute_text = settings.flood_mute_text or "По умолчанию"
    if len(mute_text) > 30:
        mute_text = mute_text[:30] + "..."

    ban_text = settings.flood_ban_text or "По умолчанию"
    if len(ban_text) > 30:
        ban_text = ban_text[:30] + "..."

    # Форматируем задержки
    delete_delay = settings.flood_delete_delay or 0
    delete_delay_text = f"{delete_delay} сек" if delete_delay else "Сразу"

    notification_delay = settings.flood_notification_delete_delay or 0
    notification_delay_text = f"{notification_delay} сек" if notification_delay else "Не удалять"

    # Формируем текст меню
    text = (
        f"⚙️ <b>Дополнительные настройки антифлуда</b>\n\n"
        f"<b>━━━ Базовый антифлуд ━━━</b>\n"
        f"<b>Макс. повторов:</b> {max_repeats}\n"
        f"<b>Временное окно:</b> {time_window} сек\n"
        f"<b>Действие:</b> {action_text}\n\n"
        f"<b>━━━ Любые сообщения ━━━</b>\n"
        f"<b>Лимит:</b> {any_limit} за {any_window}с\n\n"
        f"<b>━━━ Тексты уведомлений ━━━</b>\n"
        f"При предупреждении: {warn_text}\n"
        f"При муте: {mute_text}\n"
        f"При бане: {ban_text}\n\n"
        f"<b>━━━ Удаление ━━━</b>\n"
        f"<b>Задержка удаления:</b> {delete_delay_text}\n"
        f"<b>Автоудаление уведомления:</b> {notification_delay_text}"
    )

    # Определяем галочки для текущих значений max_repeats
    rep2_check = " ✓" if max_repeats == 2 else ""
    rep3_check = " ✓" if max_repeats == 3 else ""
    rep5_check = " ✓" if max_repeats == 5 else ""
    rep_custom = max_repeats not in [2, 3, 5]
    rep_custom_text = f"✏️ {max_repeats} ✓" if rep_custom else "✏️"

    # Определяем галочки для time_window
    win30_check = " ✓" if time_window == 30 else ""
    win60_check = " ✓" if time_window == 60 else ""
    win120_check = " ✓" if time_window == 120 else ""
    win180_check = " ✓" if time_window == 180 else ""
    win_custom = time_window not in [30, 60, 120, 180]
    win_custom_text = f"✏️ {time_window}с ✓" if win_custom else "✏️"

    # Формируем клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # БАЗОВЫЙ АНТИФЛУД
            # ─────────────────────────────────────────────────────
            # Заголовок: Максимум повторов
            [
                InlineKeyboardButton(
                    text="📢 Макс. повторов:",
                    callback_data="cf:noop"
                )
            ],
            # Ряд выбора повторов
            [
                InlineKeyboardButton(
                    text=f"2{rep2_check}",
                    callback_data=f"cf:flr:2:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"3{rep3_check}",
                    callback_data=f"cf:flr:3:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"5{rep5_check}",
                    callback_data=f"cf:flr:5:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=rep_custom_text,
                    callback_data=f"cf:flrc:{chat_id}"
                )
            ],
            # Заголовок: Временное окно
            [
                InlineKeyboardButton(
                    text="⏱️ Временное окно:",
                    callback_data="cf:noop"
                )
            ],
            # Ряд выбора окна
            [
                InlineKeyboardButton(
                    text=f"30с{win30_check}",
                    callback_data=f"cf:flw:30:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"60с{win60_check}",
                    callback_data=f"cf:flw:60:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"120с{win120_check}",
                    callback_data=f"cf:flw:120:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"180с{win180_check}",
                    callback_data=f"cf:flw:180:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=win_custom_text,
                    callback_data=f"cf:flwc:{chat_id}"
                )
            ],
            # Действие при срабатывании
            [
                InlineKeyboardButton(
                    text=f"⚡ Действие: {action_text}",
                    callback_data=f"cf:fact:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Настройки "любые сообщения"
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📢 Лимит сообщений: {any_limit}",
                    callback_data=f"cf:flanylim:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⏱️ Временное окно: {any_window}с",
                    callback_data=f"cf:flanywin:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Кастомные тексты уведомлений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Текст при предупреждении",
                    callback_data=f"cf:flwt:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Текст при муте",
                    callback_data=f"cf:flmt:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Текст при бане",
                    callback_data=f"cf:flbt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Задержки
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⏱️ Задержка удаления: {delete_delay_text}",
                    callback_data=f"cf:fldd:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🗑️ Автоудаление уведомления: {notification_delay_text}",
                    callback_data=f"cf:flnd:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"cf:fls:{chat_id}"
                )
            ]
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


# ============================================================
# РУЧНОЙ ВВОД MAX_REPEATS
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flrc:-?\d+$"))
async def start_custom_max_repeats(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает ручной ввод максимального количества повторов.

    Callback: cf:flrc:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(chat_id=chat_id)
    await state.set_state(FloodCustomInputStates.waiting_for_max_repeats)

    text = (
        "📢 <b>Ручной ввод: Макс. повторов</b>\n\n"
        "Введите положительное число.\n"
        "После стольких одинаковых сообщений сработает антифлуд.\n\n"
        "<i>Рекомендуется: 2-5</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(FloodCustomInputStates.waiting_for_max_repeats)
async def process_custom_max_repeats(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ручной ввод max_repeats."""
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Валидация ввода
    try:
        value = int(message.text.strip())
        if value < 1:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            await message.answer("❌ Введите положительное число.")
            return
    except ValueError:
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        await message.answer("❌ Введите целое число.")
        return

    # Сохраняем значение
    await filter_manager.update_settings(chat_id, session, flood_max_repeats=value)
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    await message.answer(
        f"✅ Установлено: {value} повторов",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# РУЧНОЙ ВВОД TIME_WINDOW
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flwc:-?\d+$"))
async def start_custom_time_window(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """
    Начинает ручной ввод временного окна.

    Callback: cf:flwc:{chat_id}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    await state.update_data(chat_id=chat_id)
    await state.set_state(FloodCustomInputStates.waiting_for_time_window)

    text = (
        "⏱️ <b>Ручной ввод: Временное окно</b>\n\n"
        "Введите положительное число в секундах.\n"
        "За это время считаются повторы.\n\n"
        "<i>Рекомендуется: 30-120 секунд</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Отмена",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass

    await callback.answer()


@advanced_router.message(FloodCustomInputStates.waiting_for_time_window)
async def process_custom_time_window(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """Обрабатывает ручной ввод time_window."""
    data = await state.get_data()
    chat_id = data.get('chat_id')

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка: данные сессии потеряны.")
        return

    # Валидация ввода
    try:
        value = int(message.text.strip())
        if value < 1:
            try:
                await message.delete()
            except TelegramAPIError:
                pass
            await message.answer("❌ Введите положительное число.")
            return
    except ValueError:
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        await message.answer("❌ Введите целое число.")
        return

    # Сохраняем значение
    await filter_manager.update_settings(chat_id, session, flood_time_window=value)
    await state.clear()

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам",
            callback_data=f"cf:fladv:{chat_id}"
        )]
    ])

    await message.answer(
        f"✅ Установлено: {value} сек.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# NOOP CALLBACK
# ============================================================

@advanced_router.callback_query(F.data == "cf:noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """Обрабатывает пустые callback (например, разделители)."""
    await callback.answer()


# ============================================================
# ТЕКСТ МУТА ДЛЯ АНТИФЛУДА
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flmt:-?\d+$"))
async def request_flood_mute_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод текста для мута при флуде."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = settings.flood_mute_text or "Не задан"

    text = (
        f"📝 <b>Текст при муте за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление, "
        f"когда пользователь получит мут за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%, %time%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodTextStates.waiting_mute_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodTextStates.waiting_mute_text)
async def process_flood_mute_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста мута для антифлуда."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    await state.clear()

    text = message.text.strip() if message.text else ""
    if text == "-":
        text = None

    await filter_manager.update_settings(chat_id, session, flood_mute_text=text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при муте сохранён" if text else "✅ Текст при муте сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ТЕКСТ БАНА ДЛЯ АНТИФЛУДА
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flbt:-?\d+$"))
async def request_flood_ban_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод текста для бана при флуде."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = settings.flood_ban_text or "Не задан"

    text = (
        f"📝 <b>Текст при бане за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление, "
        f"когда пользователь получит бан за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodTextStates.waiting_ban_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodTextStates.waiting_ban_text)
async def process_flood_ban_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста бана для антифлуда."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    await state.clear()

    text = message.text.strip() if message.text else ""
    if text == "-":
        text = None

    await filter_manager.update_settings(chat_id, session, flood_ban_text=text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при бане сохранён" if text else "✅ Текст при бане сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ЗАДЕРЖКА УДАЛЕНИЯ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:fldd:-?\d+$"))
async def request_flood_delete_delay_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод задержки удаления при флуде."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_delay = settings.flood_delete_delay or 0

    text = (
        f"⏱️ <b>Задержка удаления сообщения</b>\n\n"
        f"Задержка перед удалением сообщения-флуда.\n"
        f"Полезно, чтобы пользователь увидел что его сообщение "
        f"было обнаружено как флуд.\n\n"
        f"<b>Текущая задержка:</b> {current_delay} сек\n\n"
        f"Введите задержку в секундах или <code>0</code> для мгновенного удаления."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodDelayStates.waiting_delete_delay)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodDelayStates.waiting_delete_delay)
async def process_flood_delete_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод задержки удаления для антифлуда."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    try:
        delay_seconds = int(message.text.strip())
        if delay_seconds < 0:
            raise ValueError("Значение должно быть неотрицательным")
    except (ValueError, TypeError):
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ <b>Ошибка:</b> введите неотрицательное число.\n\nВведите задержку в секундах:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите неотрицательное число")
        return

    await state.clear()
    await filter_manager.update_settings(chat_id, session, flood_delete_delay=delay_seconds)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Задержка удаления: {delay_seconds} сек" if delay_seconds else "✅ Мгновенное удаление"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# АВТОУДАЛЕНИЕ УВЕДОМЛЕНИЯ
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flnd:-?\d+$"))
async def request_flood_notification_delay_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод времени автоудаления уведомления."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_delay = settings.flood_notification_delete_delay or 0

    text = (
        f"🗑️ <b>Автоудаление уведомления</b>\n\n"
        f"Через сколько секунд удалять уведомление о флуде.\n"
        f"Полезно, чтобы не засорять чат.\n\n"
        f"<b>Текущее значение:</b> {current_delay} сек\n\n"
        f"Введите значение в секундах или <code>0</code> чтобы не удалять."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodDelayStates.waiting_notification_delay)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodDelayStates.waiting_notification_delay)
async def process_flood_notification_delay_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод времени автоудаления уведомления."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    try:
        delay_seconds = int(message.text.strip())
        if delay_seconds < 0:
            raise ValueError("Значение должно быть неотрицательным")
    except (ValueError, TypeError):
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ <b>Ошибка:</b> введите неотрицательное число.\n\nВведите время автоудаления в секундах:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите неотрицательное число")
        return

    await state.clear()
    await filter_manager.update_settings(chat_id, session, flood_notification_delete_delay=delay_seconds)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Автоудаление уведомления через: {delay_seconds} сек" if delay_seconds else "✅ Уведомления не будут удаляться автоматически"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ЛИМИТ СООБЩЕНИЙ (ЛЮБЫЕ СООБЩЕНИЯ)
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flanylim:-?\d+$"))
async def request_flood_any_limit_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод лимита для детекции любых сообщений."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_limit = settings.flood_any_max_messages or 5

    text = (
        f"📢 <b>Лимит сообщений (любые сообщения)</b>\n\n"
        f"Введите максимальное количество любых сообщений подряд,\n"
        f"после которого сработает фильтр.\n\n"
        f"<b>Текущее значение:</b> {current_limit}\n\n"
        f"Введите положительное число (минимум 2):"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodAnySettingsStates.waiting_any_limit)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodAnySettingsStates.waiting_any_limit)
async def process_flood_any_limit_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод лимита для детекции любых сообщений."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    try:
        limit = int(message.text.strip())
        if limit < 2:
            raise ValueError("Значение должно быть минимум 2")
    except (ValueError, TypeError):
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ <b>Ошибка:</b> введите число (минимум 2).\n\nВведите лимит сообщений:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите число (минимум 2)")
        return

    await state.clear()
    await filter_manager.update_settings(chat_id, session, flood_any_max_messages=limit)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Лимит сообщений установлен: {limit}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ВРЕМЕННОЕ ОКНО (ЛЮБЫЕ СООБЩЕНИЯ)
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flanywin:-?\d+$"))
async def request_flood_any_window_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод временного окна для детекции любых сообщений."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_window = settings.flood_any_time_window or 10

    text = (
        f"⏱️ <b>Временное окно (любые сообщения)</b>\n\n"
        f"Введите временное окно в секундах.\n\n"
        f"Если пользователь отправит больше лимита сообщений\n"
        f"за это время — сработает фильтр.\n\n"
        f"<b>Текущее значение:</b> {current_window} сек\n\n"
        f"Введите положительное число в секундах:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodAnySettingsStates.waiting_any_window)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodAnySettingsStates.waiting_any_window)
async def process_flood_any_window_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод временного окна для детекции любых сообщений."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    try:
        window = int(message.text.strip())
        if window < 1:
            raise ValueError("Значение должно быть положительным")
    except (ValueError, TypeError):
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        if instruction_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id,
                    text="❌ <b>Ошибка:</b> введите положительное число.\n\nВведите временное окно в секундах:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            except TelegramAPIError:
                pass
        await message.answer("❌ Введите положительное число")
        return

    await state.clear()
    await filter_manager.update_settings(chat_id, session, flood_any_time_window=window)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Временное окно установлено: {window} сек"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ТЕКСТ ПРЕДУПРЕЖДЕНИЯ ДЛЯ АНТИФЛУДА
# ============================================================

@advanced_router.callback_query(F.data.regexp(r"^cf:flwt:-?\d+$"))
async def request_flood_warn_text_input(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Запрашивает ввод текста для предупреждения при флуде."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await filter_manager.get_or_create_settings(chat_id, session)
    current_text = settings.flood_warn_text or "Не задан"

    text = (
        f"📝 <b>Текст при предупреждении за флуд</b>\n\n"
        f"Этот текст будет отправлен как уведомление,\n"
        f"когда пользователь получит предупреждение за флуд.\n\n"
        f"<b>Текущий текст:</b>\n<code>{current_text}</code>\n\n"
        f"Введите новый текст или отправьте <code>-</code> чтобы сбросить.\n"
        f"Доступные переменные: %user%, %time%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cf:fladv:{chat_id}")]
    ])

    await state.set_state(FloodTextStates.waiting_warn_text)
    msg = await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(chat_id=chat_id, instruction_message_id=msg.message_id)

    await callback.answer()


@advanced_router.message(FloodTextStates.waiting_warn_text)
async def process_flood_warn_text_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext
) -> None:
    """Обрабатывает ввод текста предупреждения для антифлуда."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    instruction_message_id = data.get("instruction_message_id")

    await state.clear()

    text = message.text.strip() if message.text else ""
    if text == "-":
        text = None

    await filter_manager.update_settings(chat_id, session, flood_warn_text=text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    confirm_text = f"✅ Текст при предупреждении сохранён" if text else "✅ Текст при предупреждении сброшен"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"cf:fladv:{chat_id}")]
    ])

    if instruction_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                text=confirm_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        except TelegramAPIError:
            pass

    await message.answer(confirm_text, reply_markup=keyboard, parse_mode="HTML")
