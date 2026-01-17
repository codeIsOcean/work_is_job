# bot/handlers/antiraid/settings_handler.py
"""
Хендлеры настроек модуля Anti-Raid.

Обрабатывает callback запросы для UI настроек:
- Главное меню Anti-Raid
- Настройки каждого компонента
- Переключение включён/выключен
- Изменение параметров
- Управление паттернами имён
"""

# Импортируем логгер для записи событий
import logging

# Импортируем типы aiogram
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы настроек
from bot.services.antiraid import (
    get_antiraid_settings,
    get_or_create_antiraid_settings,
    update_antiraid_settings,
    get_name_patterns,
    add_name_pattern,
    remove_name_pattern,
    toggle_name_pattern,
)

# Импортируем клавиатуры
from bot.keyboards.antiraid_kb import (
    create_antiraid_main_keyboard,
    create_join_exit_keyboard,
    create_name_pattern_keyboard,
    create_mass_join_keyboard,
    create_mass_invite_keyboard,
    create_mass_reaction_keyboard,
    create_action_selection_keyboard,
    create_value_selection_keyboard,
    create_patterns_list_keyboard,
    create_pattern_edit_keyboard,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для хендлеров настроек
antiraid_settings_router = Router(name="antiraid_settings")


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ ВВОДА ЗНАЧЕНИЙ
# ============================================================
class AntiRaidSettingsStates(StatesGroup):
    """Состояния FSM для ввода пользовательских значений."""
    # Ожидание ввода паттерна имени
    waiting_pattern_input = State()
    # v2: Ожидание ввода произвольного числового значения
    waiting_custom_value = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def _parse_callback_chat_id(data: str) -> int:
    """Извлекает chat_id из callback_data."""
    # Формат: ars:...:chat_id
    parts = data.split(":")
    return int(parts[-1])


# ============================================================
# ГЛАВНОЕ МЕНЮ ANTI-RAID
# ============================================================
@antiraid_settings_router.callback_query(F.data.startswith("ars:m:"))
async def antiraid_main_menu(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Показывает главное меню настроек Anti-Raid.
    """
    try:
        chat_id = _parse_callback_chat_id(callback.data)

        # Получаем настройки
        settings = await get_antiraid_settings(session, chat_id)

        # Формируем текст
        text = (
            "<b>Anti-Raid защита</b>\n\n"
            "Выберите компонент для настройки:\n\n"
            "• <b>Частые входы/выходы</b> — защита от ботов\n"
            "• <b>Бан по имени</b> — блокировка по паттернам\n"
            "• <b>Массовые вступления</b> — защита от рейдов\n"
            "• <b>Массовые инвайты</b> — лимит инвайтов\n"
            "• <b>Массовые реакции</b> — защита от спама"
        )

        # Создаём клавиатуру
        keyboard = create_antiraid_main_keyboard(chat_id, settings)

        # Обновляем сообщение
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в antiraid_main_menu: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# JOIN/EXIT — ЧАСТЫЕ ВХОДЫ/ВЫХОДЫ
# ============================================================
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:-?\d+$"))
async def join_exit_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
):
    """Показывает меню настроек Join/Exit."""
    try:
        # Очищаем FSM если был активен (возврат по кнопке "Назад")
        await state.clear()
        chat_id = _parse_callback_chat_id(callback.data)
        settings = await get_antiraid_settings(session, chat_id)

        text = (
            "<b>Частые входы/выходы</b>\n\n"
            "Защита от ботов, которые быстро входят и выходят "
            "чтобы засветить имя с рекламой.\n\n"
            f"Статус: {'Включён' if settings and settings.join_exit_enabled else 'Выключен'}"
        )

        keyboard = create_join_exit_keyboard(chat_id, settings)
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в join_exit_menu: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:toggle:-?\d+$"))
async def toggle_join_exit(
    callback: CallbackQuery,
    session: AsyncSession
):
    """Переключает статус Join/Exit."""
    try:
        chat_id = _parse_callback_chat_id(callback.data)
        settings = await get_or_create_antiraid_settings(session, chat_id)

        # Переключаем
        new_value = not settings.join_exit_enabled
        await update_antiraid_settings(session, chat_id, join_exit_enabled=new_value)

        await callback.answer(f"Join/Exit {'включён' if new_value else 'выключен'}")

        # Обновляем меню
        settings = await get_antiraid_settings(session, chat_id)
        text = (
            "<b>Частые входы/выходы</b>\n\n"
            "Защита от ботов, которые быстро входят и выходят.\n\n"
            f"Статус: {'Включён' if settings.join_exit_enabled else 'Выключен'}"
        )
        keyboard = create_join_exit_keyboard(chat_id, settings)
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в toggle_join_exit: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:action:-?\d+$"))
async def je_select_action(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор действия для Join/Exit."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_action_selection_keyboard(chat_id, "je", ["ban", "kick", "mute"])
    await callback.message.edit_text(
        "Выберите действие при частых входах/выходах:",
        reply_markup=keyboard
    )
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:setaction:(ban|kick|mute):-?\d+$"))
async def je_set_action(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает действие для Join/Exit."""
    parts = callback.data.split(":")
    action = parts[3]
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, join_exit_action=action)
    await callback.answer(f"Действие: {action}")

    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_join_exit_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Частые входы/выходы</b>\n\nСтатус: {'Включён' if settings.join_exit_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:threshold:-?\d+$"))
async def je_select_threshold(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор порога для Join/Exit."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "je", "threshold", [2, 3, 4, 5, 7, 10])
    await callback.message.edit_text("Выберите порог (событий):", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:setthreshold:\d+:-?\d+$"))
async def je_set_threshold(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает порог для Join/Exit."""
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, join_exit_threshold=value)
    await callback.answer(f"Порог: {value}")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_join_exit_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Частые входы/выходы</b>\n\nСтатус: {'Включён' if settings.join_exit_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:window:-?\d+$"))
async def je_select_window(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор окна для Join/Exit."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "je", "window", [30, 60, 120, 180, 300], " сек")
    await callback.message.edit_text("Выберите временное окно:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:setwindow:\d+:-?\d+$"))
async def je_set_window(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает окно для Join/Exit."""
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, join_exit_window=value)
    await callback.answer(f"Окно: {value} сек")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_join_exit_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Частые входы/выходы</b>\n\nСтатус: {'Включён' if settings.join_exit_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:duration:-?\d+$"))
async def je_select_duration(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор длительности бана для Join/Exit."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "je", "duration", [0, 1, 6, 24, 72, 168], "ч")
    await callback.message.edit_text("Выберите длительность бана:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:je:setduration:\d+:-?\d+$"))
async def je_set_duration(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает длительность бана для Join/Exit."""
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, join_exit_ban_duration=value)
    await callback.answer(f"Длительность: {value}ч" if value > 0 else "Длительность: навсегда")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_join_exit_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Частые входы/выходы</b>\n\nСтатус: {'Включён' if settings.join_exit_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


# ============================================================
# NAME PATTERN — БАН ПО ИМЕНИ
# ============================================================
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:-?\d+$"))
async def name_pattern_menu(callback: CallbackQuery, session: AsyncSession):
    """Показывает меню настроек Name Pattern."""
    try:
        chat_id = _parse_callback_chat_id(callback.data)
        settings = await get_antiraid_settings(session, chat_id)
        patterns = await get_name_patterns(session, chat_id)

        text = (
            "<b>Бан по имени</b>\n\n"
            "Мгновенный бан при входе если имя содержит "
            "запрещённые паттерны (с нормализацией).\n\n"
            f"Статус: {'Включён' if settings and settings.name_pattern_enabled else 'Выключен'}\n"
            f"Паттернов: {len(patterns)}"
        )

        keyboard = create_name_pattern_keyboard(chat_id, settings, len(patterns))
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в name_pattern_menu: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:toggle:-?\d+$"))
async def toggle_name_pattern(callback: CallbackQuery, session: AsyncSession):
    """Переключает статус Name Pattern."""
    try:
        chat_id = _parse_callback_chat_id(callback.data)
        settings = await get_or_create_antiraid_settings(session, chat_id)

        new_value = not settings.name_pattern_enabled
        await update_antiraid_settings(session, chat_id, name_pattern_enabled=new_value)

        await callback.answer(f"Name Pattern {'включён' if new_value else 'выключен'}")

        settings = await get_antiraid_settings(session, chat_id)
        patterns = await get_name_patterns(session, chat_id)
        keyboard = create_name_pattern_keyboard(chat_id, settings, len(patterns))
        await callback.message.edit_text(
            f"<b>Бан по имени</b>\n\nСтатус: {'Включён' if settings.name_pattern_enabled else 'Выключен'}\nПаттернов: {len(patterns)}",
            reply_markup=keyboard, parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка в toggle_name_pattern: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:action:-?\d+$"))
async def np_select_action(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор действия для Name Pattern."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_action_selection_keyboard(chat_id, "np", ["ban", "kick"])
    await callback.message.edit_text("Выберите действие при совпадении имени:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:setaction:(ban|kick):-?\d+$"))
async def np_set_action(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает действие для Name Pattern."""
    parts = callback.data.split(":")
    action = parts[3]
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, name_pattern_action=action)
    await callback.answer(f"Действие: {action}")

    settings = await get_antiraid_settings(session, chat_id)
    patterns = await get_name_patterns(session, chat_id)
    keyboard = create_name_pattern_keyboard(chat_id, settings, len(patterns))
    await callback.message.edit_text(
        f"<b>Бан по имени</b>\n\nСтатус: {'Включён' if settings.name_pattern_enabled else 'Выключен'}\nПаттернов: {len(patterns)}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:duration:-?\d+$"))
async def np_select_duration(callback: CallbackQuery, session: AsyncSession):
    """Показывает выбор длительности бана для Name Pattern."""
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "np", "duration", [0, 1, 6, 24, 72, 168], "ч")
    await callback.message.edit_text("Выберите длительность бана:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:setduration:\d+:-?\d+$"))
async def np_set_duration(callback: CallbackQuery, session: AsyncSession):
    """Устанавливает длительность бана для Name Pattern."""
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])

    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, name_pattern_ban_duration=value)
    await callback.answer(f"Длительность: {value}ч" if value > 0 else "Длительность: навсегда")

    settings = await get_antiraid_settings(session, chat_id)
    patterns = await get_name_patterns(session, chat_id)
    keyboard = create_name_pattern_keyboard(chat_id, settings, len(patterns))
    await callback.message.edit_text(
        f"<b>Бан по имени</b>\n\nСтатус: {'Включён' if settings.name_pattern_enabled else 'Выключен'}\nПаттернов: {len(patterns)}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:patterns:-?\d+$"))
async def np_patterns_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Показывает список паттернов."""
    # Очищаем FSM если был активен (возврат по кнопке "Назад")
    await state.clear()
    chat_id = _parse_callback_chat_id(callback.data)
    patterns = await get_name_patterns(session, chat_id)

    text = f"<b>Паттерны имён</b>\n\nВсего: {len(patterns)}"
    keyboard = create_patterns_list_keyboard(chat_id, patterns, page=0)
    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:plist:\d+:-?\d+$"))
async def np_patterns_page(callback: CallbackQuery, session: AsyncSession):
    """Переключает страницу паттернов."""
    parts = callback.data.split(":")
    page = int(parts[3])
    chat_id = int(parts[4])

    patterns = await get_name_patterns(session, chat_id)
    keyboard = create_patterns_list_keyboard(chat_id, patterns, page=page)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:addpat:-?\d+$"))
async def np_add_pattern_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начинает процесс добавления паттерна."""
    chat_id = _parse_callback_chat_id(callback.data)

    await state.set_state(AntiRaidSettingsStates.waiting_pattern_input)
    # Сохраняем chat_id и message_id для удаления после ввода
    await state.update_data(
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )

    # Кнопка "Назад" вместо /cancel
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"ars:np:patterns:{chat_id}")]
    ])

    await callback.message.edit_text(
        "Отправьте текст паттерна для добавления.\n\n"
        "Паттерн будет искаться в нормализованном имени пользователя.",
        reply_markup=keyboard
    )
    await callback.answer()


@antiraid_settings_router.message(AntiRaidSettingsStates.waiting_pattern_input)
async def np_add_pattern_finish(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Завершает добавление паттерна."""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    prompt_message_id = data.get("prompt_message_id")
    prompt_chat_id = data.get("prompt_chat_id")

    # Вспомогательная функция для удаления сообщения запроса
    async def delete_prompt():
        if prompt_message_id and prompt_chat_id:
            try:
                await bot.delete_message(prompt_chat_id, prompt_message_id)
            except TelegramAPIError:
                pass

    # Проверяем команды — любая команда отменяет FSM
    if message.text and message.text.startswith("/"):
        await delete_prompt()
        await state.clear()
        # Другие команды (/settings и т.д.) обработаются своими хэндлерами
        return

    if not chat_id:
        await delete_prompt()
        await state.clear()
        await message.answer("Ошибка: chat_id не найден")
        return

    pattern_text = message.text.strip() if message.text else ""
    if not pattern_text:
        # Не удаляем prompt — даём ещё попытку
        await message.answer("Паттерн не может быть пустым. Попробуйте ещё раз.")
        return

    # Добавляем паттерн
    await add_name_pattern(
        session=session,
        chat_id=chat_id,
        pattern=pattern_text,
        pattern_type="contains",
        created_by=message.from_user.id
    )

    # Удаляем сообщение с запросом
    await delete_prompt()
    await state.clear()

    # Показываем список паттернов с клавиатурой
    patterns = await get_name_patterns(session, chat_id)
    keyboard = create_patterns_list_keyboard(chat_id, patterns, page=0)
    await message.answer(
        f"✅ Паттерн '<code>{pattern_text}</code>' добавлен.\n\n"
        f"<b>Паттерны имён</b>\nВсего: {len(patterns)}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:pattern:\d+:-?\d+$"))
async def np_pattern_edit(callback: CallbackQuery, session: AsyncSession):
    """Показывает редактирование паттерна."""
    parts = callback.data.split(":")
    pattern_id = int(parts[3])
    chat_id = int(parts[4])

    patterns = await get_name_patterns(session, chat_id)
    pattern = next((p for p in patterns if p.id == pattern_id), None)

    if not pattern:
        await callback.answer("Паттерн не найден", show_alert=True)
        return

    text = (
        f"<b>Паттерн</b>\n\n"
        f"Текст: <code>{pattern.pattern}</code>\n"
        f"Тип: {pattern.pattern_type}\n"
        f"Статус: {'Включён' if pattern.is_enabled else 'Выключен'}"
    )

    keyboard = create_pattern_edit_keyboard(chat_id, pattern)
    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:ptoggle:\d+:-?\d+$"))
async def np_pattern_toggle(callback: CallbackQuery, session: AsyncSession):
    """Переключает статус паттерна."""
    parts = callback.data.split(":")
    pattern_id = int(parts[3])
    chat_id = int(parts[4])

    await toggle_name_pattern(session, pattern_id)
    await callback.answer("Статус изменён")

    # Обновляем меню
    patterns = await get_name_patterns(session, chat_id)
    pattern = next((p for p in patterns if p.id == pattern_id), None)
    if pattern:
        keyboard = create_pattern_edit_keyboard(chat_id, pattern)
        await callback.message.edit_reply_markup(reply_markup=keyboard)


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:np:pdel:\d+:-?\d+$"))
async def np_pattern_delete(callback: CallbackQuery, session: AsyncSession):
    """Удаляет паттерн."""
    parts = callback.data.split(":")
    pattern_id = int(parts[3])
    chat_id = int(parts[4])

    await remove_name_pattern(session, pattern_id)
    await callback.answer("Паттерн удалён")

    # Возвращаемся к списку
    patterns = await get_name_patterns(session, chat_id)
    keyboard = create_patterns_list_keyboard(chat_id, patterns, page=0)
    await callback.message.edit_text(
        f"<b>Паттерны имён</b>\n\nВсего: {len(patterns)}",
        reply_markup=keyboard, parse_mode="HTML"
    )


# ============================================================
# MASS JOIN — МАССОВЫЕ ВСТУПЛЕНИЯ v2
# ============================================================
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:-?\d+$"))
async def mass_join_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """
    Показывает меню настроек Mass Join v2.

    v2: При детекции рейда включается "режим защиты" —
    ВСЕ новые вступления в течение protection_duration секунд
    автоматически банятся.
    """
    # Очищаем FSM если был активен (возврат по кнопке "Назад")
    await state.clear()
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # Получаем настройки
    settings = await get_antiraid_settings(session, chat_id)

    # Формируем текст описания v2
    text = (
        "<b>Массовые вступления (рейд) v2</b>\n\n"
        "Защита от координированных атак.\n\n"
        "При детекции рейда (много вступлений за короткое время) "
        "включается «режим защиты» — ВСЕ новые вступления "
        "автоматически банятся на заданное время.\n\n"
        f"Статус: {'Включён' if settings and settings.mass_join_enabled else 'Выключен'}"
    )

    # Создаём клавиатуру
    keyboard = create_mass_join_keyboard(chat_id, settings)
    # Обновляем сообщение
    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:toggle:-?\d+$"))
async def toggle_mass_join(callback: CallbackQuery, session: AsyncSession):
    """Переключает статус Mass Join."""
    chat_id = _parse_callback_chat_id(callback.data)
    settings = await get_or_create_antiraid_settings(session, chat_id)

    new_value = not settings.mass_join_enabled
    await update_antiraid_settings(session, chat_id, mass_join_enabled=new_value)

    await callback.answer(f"Mass Join {'включён' if new_value else 'выключен'}")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:action:-?\d+$"))
async def mj_select_action(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор действия для Mass Join v2.

    v2: добавлен "ban" как дефолтное действие (режим защиты).
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # v2: добавлен "ban" в список действий (первый = рекомендуемый)
    keyboard = create_action_selection_keyboard(chat_id, "mj", ["ban", "slowmode", "lock", "notify"])
    # Показываем выбор
    await callback.message.edit_text("Выберите действие при рейде:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setaction:(ban|slowmode|lock|notify):-?\d+$"))
async def mj_set_action(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает действие для Mass Join v2.

    v2: добавлен "ban" в regex (режим защиты — банит ВСЕ новые вступления).
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    action = parts[3]
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # Обновляем действие
    await update_antiraid_settings(session, chat_id, mass_join_action=action)
    await callback.answer(f"Действие: {action}")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:threshold:-?\d+$"))
async def mj_select_threshold(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mj", "threshold", [5, 10, 15, 20, 30, 50])
    await callback.message.edit_text("Выберите порог (вступлений):", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setthreshold:\d+:-?\d+$"))
async def mj_set_threshold(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_join_threshold=value)
    await callback.answer(f"Порог: {value}")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:window:-?\d+$"))
async def mj_select_window(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mj", "window", [30, 60, 120, 180, 300], " сек")
    await callback.message.edit_text("Выберите временное окно:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setwindow:\d+:-?\d+$"))
async def mj_set_window(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_join_window=value)
    await callback.answer(f"Окно: {value} сек")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:slowmode:-?\d+$"))
async def mj_select_slowmode(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mj", "slowmode", [10, 30, 60, 300, 900, 3600], " сек")
    await callback.message.edit_text("Выберите значение slowmode:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setslowmode:\d+:-?\d+$"))
async def mj_set_slowmode(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_join_slowmode=value)
    await callback.answer(f"Slowmode: {value} сек")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:autounlock:-?\d+$"))
async def mj_select_autounlock(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mj", "autounlock", [0, 15, 30, 60, 120], " мин")
    await callback.message.edit_text("Выберите время авто-снятия:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setautounlock:\d+:-?\d+$"))
async def mj_set_autounlock(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_join_auto_unlock=value)
    await callback.answer(f"Авто-снятие: {value} мин" if value > 0 else "Авто-снятие: выкл")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


# ─────────────────────────────────────────────────────────
# v2: НОВЫЕ ХЭНДЛЕРЫ ДЛЯ РЕЖИМА ЗАЩИТЫ
# ─────────────────────────────────────────────────────────
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:protection:-?\d+$"))
async def mj_select_protection(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор длительности режима защиты для Mass Join v2.

    v2: protection_duration — сколько секунд держать режим защиты
    после детекции рейда (все новые вступления в этот период = бан).
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # Варианты длительности режима защиты в секундах
    keyboard = create_value_selection_keyboard(chat_id, "mj", "protection", [60, 120, 180, 300, 600, 900], " сек")
    # Показываем выбор
    await callback.message.edit_text(
        "Выберите длительность режима защиты:\n\n"
        "В течение этого времени после детекции рейда ВСЕ "
        "новые вступления будут автоматически заблокированы.",
        reply_markup=keyboard
    )
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setprotection:\d+:-?\d+$"))
async def mj_set_protection(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает длительность режима защиты для Mass Join v2.

    v2: mass_join_protection_duration в секундах.
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # v2: обновляем protection_duration
    await update_antiraid_settings(session, chat_id, mass_join_protection_duration=value)
    await callback.answer(f"Режим защиты: {value} сек")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:banduration:-?\d+$"))
async def mj_select_banduration(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор длительности бана для Mass Join v2.

    v2: ban_duration — длительность бана в часах (0 = навсегда)
    для action=ban.
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # Варианты длительности бана в часах
    keyboard = create_value_selection_keyboard(chat_id, "mj", "banduration", [0, 1, 6, 24, 72, 168], "ч")
    # Показываем выбор
    await callback.message.edit_text("Выберите длительность бана:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mj:setbanduration:\d+:-?\d+$"))
async def mj_set_banduration(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает длительность бана для Mass Join v2.

    v2: mass_join_ban_duration в часах (0 = навсегда).
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # v2: обновляем ban_duration
    await update_antiraid_settings(session, chat_id, mass_join_ban_duration=value)
    # Текст подтверждения
    await callback.answer(f"Длительность: {value}ч" if value > 0 else "Длительность: навсегда")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_join_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые вступления</b>\n\nСтатус: {'Включён' if settings.mass_join_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# MASS INVITE — МАССОВЫЕ ИНВАЙТЫ
# ============================================================
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:-?\d+$"))
async def mass_invite_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Показывает меню настроек Mass Invite."""
    # Очищаем FSM если был активен (возврат по кнопке "Назад")
    await state.clear()
    chat_id = _parse_callback_chat_id(callback.data)
    settings = await get_antiraid_settings(session, chat_id)

    text = (
        "<b>Массовые инвайты</b>\n\n"
        "Защита когда один пользователь приглашает "
        "слишком много людей за короткое время.\n\n"
        f"Статус: {'Включён' if settings and settings.mass_invite_enabled else 'Выключен'}"
    )

    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:toggle:-?\d+$"))
async def toggle_mass_invite(callback: CallbackQuery, session: AsyncSession):
    """Переключает статус Mass Invite."""
    chat_id = _parse_callback_chat_id(callback.data)
    settings = await get_or_create_antiraid_settings(session, chat_id)

    new_value = not settings.mass_invite_enabled
    await update_antiraid_settings(session, chat_id, mass_invite_enabled=new_value)

    await callback.answer(f"Mass Invite {'включён' if new_value else 'выключен'}")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые инвайты</b>\n\nСтатус: {'Включён' if settings.mass_invite_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:action:-?\d+$"))
async def mi_select_action(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_action_selection_keyboard(chat_id, "mi", ["warn", "mute", "kick", "ban"])
    await callback.message.edit_text("Выберите действие:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:setaction:(warn|mute|kick|ban):-?\d+$"))
async def mi_set_action(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    action = parts[3]
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_invite_action=action)
    await callback.answer(f"Действие: {action}")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые инвайты</b>\n\nСтатус: {'Включён' if settings.mass_invite_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:threshold:-?\d+$"))
async def mi_select_threshold(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mi", "threshold", [3, 5, 7, 10, 15, 20])
    await callback.message.edit_text("Выберите порог (инвайтов):", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:setthreshold:\d+:-?\d+$"))
async def mi_set_threshold(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_invite_threshold=value)
    await callback.answer(f"Порог: {value}")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые инвайты</b>\n\nСтатус: {'Включён' if settings.mass_invite_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:window:-?\d+$"))
async def mi_select_window(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mi", "window", [60, 120, 300, 600, 900], " сек")
    await callback.message.edit_text("Выберите временное окно:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:setwindow:\d+:-?\d+$"))
async def mi_set_window(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_invite_window=value)
    await callback.answer(f"Окно: {value} сек")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые инвайты</b>\n\nСтатус: {'Включён' if settings.mass_invite_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:duration:-?\d+$"))
async def mi_select_duration(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mi", "duration", [0, 1, 6, 24, 72, 168], "ч")
    await callback.message.edit_text("Выберите длительность бана:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mi:setduration:\d+:-?\d+$"))
async def mi_set_duration(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_invite_ban_duration=value)
    await callback.answer(f"Длительность: {value}ч" if value > 0 else "Длительность: навсегда")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_invite_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые инвайты</b>\n\nСтатус: {'Включён' if settings.mass_invite_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# MASS REACTION — МАССОВЫЕ РЕАКЦИИ v2
# ============================================================
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:-?\d+$"))
async def mass_reaction_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """
    Показывает меню настроек Mass Reaction v2.

    v2: Детектируем паттерн спаммера — ставит по 1 реакции
    на РАЗНЫЕ сообщения, идя вниз по чату.
    """
    # Очищаем FSM если был активен (возврат по кнопке "Назад")
    await state.clear()
    # Извлекаем chat_id из callback_data
    chat_id = _parse_callback_chat_id(callback.data)
    # Получаем настройки группы
    settings = await get_antiraid_settings(session, chat_id)

    # Формируем текст описания v2
    text = (
        "<b>Массовые реакции v2</b>\n\n"
        "Защита от спама реакциями.\n\n"
        "Детектирует паттерн спаммера: ставит по 1 реакции на РАЗНЫЕ "
        "сообщения, идя вниз по чату. Цель — заставить авторов зайти "
        "в профиль спаммера.\n\n"
        f"Статус: {'Включён' if settings and settings.mass_reaction_enabled else 'Выключен'}"
    )

    # Создаём клавиатуру
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    # Обновляем сообщение
    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:toggle:-?\d+$"))
async def toggle_mass_reaction(callback: CallbackQuery, session: AsyncSession):
    """Переключает статус Mass Reaction."""
    chat_id = _parse_callback_chat_id(callback.data)
    settings = await get_or_create_antiraid_settings(session, chat_id)

    new_value = not settings.mass_reaction_enabled
    await update_antiraid_settings(session, chat_id, mass_reaction_enabled=new_value)

    await callback.answer(f"Mass Reaction {'включён' if new_value else 'выключен'}")

    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые реакции</b>\n\nСтатус: {'Включён' if settings.mass_reaction_enabled else 'Выключен'}",
        reply_markup=keyboard, parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:action:-?\d+$"))
async def mr_select_action(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор действия для Mass Reaction v2.

    v2: добавлен "ban" как дефолтное действие.
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # v2: добавлен "ban" в список действий (первый = рекомендуемый)
    keyboard = create_action_selection_keyboard(chat_id, "mr", ["ban", "kick", "mute", "warn"])
    # Показываем выбор
    await callback.message.edit_text("Выберите действие:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:setaction:(ban|kick|mute|warn):-?\d+$"))
async def mr_set_action(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает действие для Mass Reaction v2.

    v2: добавлен "ban" в regex.
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    action = parts[3]
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # Обновляем действие
    await update_antiraid_settings(session, chat_id, mass_reaction_action=action)
    await callback.answer(f"Действие: {action}")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые реакции</b>\n\nСтатус: {'Включён' if settings.mass_reaction_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────
# v2: ОДИН порог — количество РАЗНЫХ сообщений
# (заменяет старые thuser/thmsg)
# ─────────────────────────────────────────────────────────
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:threshold:-?\d+$"))
async def mr_select_threshold(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор порога для Mass Reaction v2.

    v2: один порог — на сколько РАЗНЫХ сообщений юзер поставил реакции.
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # Создаём клавиатуру с вариантами (без хардкода — пока кнопки)
    keyboard = create_value_selection_keyboard(chat_id, "mr", "threshold", [3, 5, 7, 10, 15, 20])
    # Показываем выбор
    await callback.message.edit_text(
        "Выберите порог (разных сообщений за окно):",
        reply_markup=keyboard
    )
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:setthreshold:\d+:-?\d+$"))
async def mr_set_threshold(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает порог для Mass Reaction v2.

    v2: один порог mass_reaction_threshold (разных сообщений).
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # v2: обновляем mass_reaction_threshold (не threshold_user!)
    await update_antiraid_settings(session, chat_id, mass_reaction_threshold=value)
    await callback.answer(f"Порог: {value} сообщений")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые реакции</b>\n\nСтатус: {'Включён' if settings.mass_reaction_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:window:-?\d+$"))
async def mr_select_window(callback: CallbackQuery, session: AsyncSession):
    chat_id = _parse_callback_chat_id(callback.data)
    keyboard = create_value_selection_keyboard(chat_id, "mr", "window", [30, 60, 120, 180, 300], " сек")
    await callback.message.edit_text("Выберите временное окно:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:setwindow:\d+:-?\d+$"))
async def mr_set_window(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, mass_reaction_window=value)
    await callback.answer(f"Окно: {value} сек")
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    await callback.message.edit_text(f"<b>Массовые реакции</b>\n\nСтатус: {'Включён' if settings.mass_reaction_enabled else 'Выключен'}", reply_markup=keyboard, parse_mode="HTML")


# ─────────────────────────────────────────────────────────
# v2: ban_duration в ЧАСАХ (было mute_duration в минутах)
# ─────────────────────────────────────────────────────────
@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:duration:-?\d+$"))
async def mr_select_duration(callback: CallbackQuery, session: AsyncSession):
    """
    Показывает выбор длительности бана для Mass Reaction v2.

    v2: теперь ban_duration в ЧАСАХ (0 = навсегда), а не mute_duration в минутах.
    """
    # Извлекаем chat_id
    chat_id = _parse_callback_chat_id(callback.data)
    # v2: длительность в часах (0, 1, 6, 24, 72, 168)
    keyboard = create_value_selection_keyboard(chat_id, "mr", "duration", [0, 1, 6, 24, 72, 168], "ч")
    # Показываем выбор
    await callback.message.edit_text("Выберите длительность бана:", reply_markup=keyboard)
    await callback.answer()


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:mr:setduration:\d+:-?\d+$"))
async def mr_set_duration(callback: CallbackQuery, session: AsyncSession):
    """
    Устанавливает длительность бана для Mass Reaction v2.

    v2: mass_reaction_ban_duration в ЧАСАХ (было mute_duration в минутах).
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    value = int(parts[3])
    chat_id = int(parts[4])
    # Создаём настройки если нет
    await get_or_create_antiraid_settings(session, chat_id)
    # v2: обновляем mass_reaction_ban_duration (не mute_duration!)
    await update_antiraid_settings(session, chat_id, mass_reaction_ban_duration=value)
    # Текст подтверждения
    await callback.answer(f"Длительность: {value}ч" if value > 0 else "Длительность: навсегда")
    # Возвращаемся в меню
    settings = await get_antiraid_settings(session, chat_id)
    keyboard = create_mass_reaction_keyboard(chat_id, settings)
    await callback.message.edit_text(
        f"<b>Массовые реакции</b>\n\nСтатус: {'Включён' if settings.mass_reaction_enabled else 'Выключен'}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# v2: ВВОД ПРОИЗВОЛЬНОГО ЗНАЧЕНИЯ (FSM)
# ============================================================

# Маппинг параметров на имена полей в БД
_PARAM_TO_FIELD = {
    # Join/Exit
    "je:threshold": "join_exit_threshold",
    "je:window": "join_exit_window",
    "je:duration": "join_exit_ban_duration",
    # Name Pattern
    "np:duration": "name_pattern_ban_duration",
    # Mass Join
    "mj:threshold": "mass_join_threshold",
    "mj:window": "mass_join_window",
    "mj:slowmode": "mass_join_slowmode",
    "mj:autounlock": "mass_join_auto_unlock",
    "mj:protection": "mass_join_protection_duration",
    "mj:banduration": "mass_join_ban_duration",
    # Mass Invite
    "mi:threshold": "mass_invite_threshold",
    "mi:window": "mass_invite_window",
    "mi:duration": "mass_invite_ban_duration",
    # Mass Reaction
    "mr:threshold": "mass_reaction_threshold",
    "mr:window": "mass_reaction_window",
    "mr:duration": "mass_reaction_ban_duration",
}

# Маппинг параметров на читаемые названия
_PARAM_TO_NAME = {
    "threshold": "порог",
    "window": "временное окно (сек)",
    "duration": "длительность бана (часы, 0=навсегда)",
    "slowmode": "slowmode (сек)",
    "autounlock": "авто-снятие (мин, 0=выкл)",
    "protection": "режим защиты (сек)",
    "banduration": "длительность бана (часы, 0=навсегда)",
}

# Маппинг компонентов на функции клавиатур
_COMPONENT_TO_KEYBOARD = {
    "je": create_join_exit_keyboard,
    "np": create_name_pattern_keyboard,
    "mj": create_mass_join_keyboard,
    "mi": create_mass_invite_keyboard,
    "mr": create_mass_reaction_keyboard,
}


@antiraid_settings_router.callback_query(F.data.regexp(r"^ars:(je|np|mj|mi|mr):custom(\w+):-?\d+$"))
async def custom_value_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """
    Начинает ввод произвольного значения.

    Паттерн callback_data: ars:{component}:custom{param}:{chat_id}
    Например: ars:mr:customthreshold:-123456789
    """
    # Парсим callback_data
    parts = callback.data.split(":")
    component = parts[1]
    # param = customthreshold -> threshold (убираем "custom")
    param = parts[2].replace("custom", "")
    chat_id = int(parts[3])

    # Проверяем что параметр валидный
    field_key = f"{component}:{param}"
    if field_key not in _PARAM_TO_FIELD:
        await callback.answer("Неизвестный параметр", show_alert=True)
        return

    # Сохраняем в состояние FSM + message_id для удаления
    await state.set_state(AntiRaidSettingsStates.waiting_custom_value)
    await state.update_data(
        component=component,
        param=param,
        chat_id=chat_id,
        prompt_message_id=callback.message.message_id,
        prompt_chat_id=callback.message.chat.id
    )

    # Получаем читаемое название параметра
    param_name = _PARAM_TO_NAME.get(param, param)

    # Кнопка "Назад" — возвращает в меню компонента
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"ars:{component}:{chat_id}")]
    ])

    # Отправляем запрос на ввод
    await callback.message.edit_text(
        f"Введите {param_name}:",
        reply_markup=keyboard
    )
    await callback.answer()


@antiraid_settings_router.message(AntiRaidSettingsStates.waiting_custom_value)
async def custom_value_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot
):
    """
    Завершает ввод произвольного значения.

    Получает число от пользователя, валидирует и сохраняет.
    """
    # Получаем данные из состояния
    data = await state.get_data()
    component = data.get("component")
    param = data.get("param")
    chat_id = data.get("chat_id")
    prompt_message_id = data.get("prompt_message_id")
    prompt_chat_id = data.get("prompt_chat_id")

    # Вспомогательная функция для удаления сообщения запроса
    async def delete_prompt():
        if prompt_message_id and prompt_chat_id:
            try:
                await bot.delete_message(prompt_chat_id, prompt_message_id)
            except TelegramAPIError:
                pass

    # Проверяем команды — любая команда отменяет FSM
    if message.text and message.text.strip().startswith("/"):
        await delete_prompt()
        await state.clear()
        # Другие команды (/settings и т.д.) обработаются своими хэндлерами
        return

    if not all([component, param, chat_id]):
        await delete_prompt()
        await state.clear()
        await message.answer("Ошибка: данные сессии потеряны.")
        return

    # Парсим и валидируем значение
    text = message.text.strip() if message.text else ""
    try:
        value = int(text)
        if value < 0:
            raise ValueError("Значение должно быть >= 0")
    except ValueError:
        # Не удаляем prompt — даём ещё попытку
        await message.answer("Некорректное значение. Введите целое число >= 0.")
        return

    # Удаляем сообщение с запросом
    await delete_prompt()
    await state.clear()

    # Получаем имя поля в БД
    field_key = f"{component}:{param}"
    field_name = _PARAM_TO_FIELD.get(field_key)

    if not field_name:
        await message.answer("Ошибка: неизвестный параметр.")
        return

    # Обновляем настройки
    await get_or_create_antiraid_settings(session, chat_id)
    await update_antiraid_settings(session, chat_id, **{field_name: value})

    # Формируем текст подтверждения
    param_name = _PARAM_TO_NAME.get(param, param)
    confirm_text = f"✅ {param_name.capitalize()} установлен: {value}"

    # Возвращаемся в меню компонента
    if component in _COMPONENT_TO_KEYBOARD:
        settings = await get_antiraid_settings(session, chat_id)
        keyboard_func = _COMPONENT_TO_KEYBOARD[component]
        # Специальная обработка для np (требует patterns_count)
        if component == "np":
            patterns = await get_name_patterns(session, chat_id)
            keyboard = keyboard_func(chat_id, settings, len(patterns))
        else:
            keyboard = keyboard_func(chat_id, settings)
        await message.answer(confirm_text, reply_markup=keyboard)
    else:
        await message.answer(confirm_text)


# ============================================================
# NOOP — пустой обработчик для информационных кнопок
# ============================================================
@antiraid_settings_router.callback_query(F.data == "ars:noop")
async def noop_handler(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок (напр. номер страницы)."""
    await callback.answer()
