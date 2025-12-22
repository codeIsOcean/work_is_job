# ============================================================
# SETTINGS HANDLER - ПОЛНЫЙ UI НАСТРОЕК MUTE BY REACTION
# ============================================================
# Callback формат: rm:{action}:{params}:{chat_id}
# ============================================================

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError
import logging
import json
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.groups_settings_in_private_logic import (
    check_granular_permissions,
    get_reaction_mute_settings,
    set_reaction_mute_enabled,
    set_reaction_mute_announce_enabled,
)
from bot.keyboards.reaction_mute_keyboards import (
    create_reaction_mute_main_menu,
    create_reaction_edit_menu,
    create_action_select_menu,
    create_duration_select_menu,
    create_delete_delay_menu,
    create_notification_delay_menu,
    create_cancel_keyboard,
    REACTIONS_INFO,
    ACTIONS,
    format_duration,
    get_default_reaction_settings,
)
from bot.services.redis_conn import redis

logger = logging.getLogger(__name__)

reaction_mute_settings_router = Router(name='reaction_mute_settings')

REACTION_CONFIG_KEY = "reaction_config:{chat_id}"


# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================

class ReactionSettingsStates(StatesGroup):
    """Состояния FSM для настроек реакций."""
    waiting_for_duration = State()
    waiting_for_custom_text = State()
    waiting_for_delete_delay = State()
    waiting_for_notification_delay = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def get_reaction_config(chat_id: int) -> Dict[str, Any]:
    """Получает настройки реакций из Redis."""
    key = REACTION_CONFIG_KEY.format(chat_id=chat_id)
    try:
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.error(f"Ошибка чтения настроек реакций: {e}")

    # Возвращаем дефолтные настройки
    return {emoji: get_default_reaction_settings(emoji) for emoji in REACTIONS_INFO}


async def save_reaction_config(chat_id: int, config: Dict[str, Any]) -> bool:
    """Сохраняет настройки реакций в Redis."""
    key = REACTION_CONFIG_KEY.format(chat_id=chat_id)
    try:
        await redis.set(key, json.dumps(config))
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")
        return False


async def get_emoji_settings(chat_id: int, emoji: str) -> Dict[str, Any]:
    """Получает настройки для конкретной реакции."""
    config = await get_reaction_config(chat_id)
    return config.get(emoji, get_default_reaction_settings(emoji))


async def update_emoji_settings(chat_id: int, emoji: str, **kwargs) -> bool:
    """Обновляет настройки для конкретной реакции."""
    config = await get_reaction_config(chat_id)
    if emoji not in config:
        config[emoji] = get_default_reaction_settings(emoji)
    config[emoji].update(kwargs)
    return await save_reaction_config(chat_id, config)


def parse_delay_input(text: str) -> Optional[int]:
    """Парсит ввод задержки (секунды). Возвращает None при ошибке."""
    import re
    text = text.strip().lower()

    if text in ("-", "0", "нет", "no", "none"):
        return 0

    # Формат: 30, 30s, 30sec, 30сек
    match = re.match(r'^(\d+)\s*(s|sec|сек)?$', text)
    if match:
        return int(match.group(1))

    return None


def parse_duration_input(text: str) -> Optional[int]:
    """Парсит ввод длительности (минуты). Возвращает -1 при ошибке."""
    import re
    text = text.strip().lower()

    if text in ("inf", "навсегда", "forever", "0"):
        return None  # None = навсегда

    # Формат с единицами
    match = re.match(r'^(\d+)\s*(m|min|мин|h|час|hour|d|день|day)?$', text)
    if match:
        value = int(match.group(1))
        unit = match.group(2) or "min"

        if unit in ("m", "min", "мин"):
            return value
        elif unit in ("h", "час", "hour"):
            return value * 60
        elif unit in ("d", "день", "day"):
            return value * 24 * 60

    return -1  # Ошибка


# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

async def _show_main_menu(callback: CallbackQuery, session: AsyncSession, chat_id: int) -> None:
    """
    Вспомогательная функция для отображения главного меню.
    Вынесена отдельно чтобы можно было вызывать с chat_id напрямую,
    без изменения callback.data (который frozen в aiogram 3.x).
    """
    # Получаем настройки из БД и Redis
    enabled, announce_enabled = await get_reaction_mute_settings(session, chat_id)
    reaction_config = await get_reaction_config(chat_id)

    # Формируем текст меню
    status = "включён" if enabled else "выключен"
    text = (
        f"<b>Мьют по реакциям</b>\n\n"
        f"Статус: {status}\n\n"
        f"Администраторы могут ставить реакции на сообщения для модерации.\n\n"
        f"Выберите реакцию для настройки:"
    )

    # Создаём клавиатуру
    keyboard = create_reaction_mute_main_menu(chat_id, enabled, announce_enabled, reaction_config)

    # Обновляем сообщение
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:m:"))
async def reaction_mute_main_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Показывает главное меню настроек."""
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    user_id = callback.from_user.id

    # Проверяем права
    if not await check_granular_permissions(callback.bot, user_id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    # Показываем меню
    await _show_main_menu(callback, session, chat_id)
    await callback.answer()


# ============================================================
# ПЕРЕКЛЮЧАТЕЛИ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:t:on:") | F.data.startswith("rm:t:off:"))
async def toggle_reaction_mute(callback: CallbackQuery, session: AsyncSession) -> None:
    """Включает/выключает модуль."""
    parts = callback.data.split(":")
    action = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    new_value = action == "on"
    await set_reaction_mute_enabled(session, chat_id, new_value)

    # Обновляем меню (используем _show_main_menu вместо изменения callback.data)
    await _show_main_menu(callback, session, chat_id)
    await callback.answer(f"Модуль {'включён' if new_value else 'выключен'}")


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:t:ann:"))
async def toggle_announce(callback: CallbackQuery, session: AsyncSession) -> None:
    """Переключает уведомления в группу."""
    parts = callback.data.split(":")
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    _, announce_enabled = await get_reaction_mute_settings(session, chat_id)
    await set_reaction_mute_announce_enabled(session, chat_id, not announce_enabled)

    # Обновляем меню
    await _show_main_menu(callback, session, chat_id)
    await callback.answer(f"Уведомления {'включены' if not announce_enabled else 'выключены'}")


# ============================================================
# МЕНЮ РЕДАКТИРОВАНИЯ РЕАКЦИИ
# ============================================================

async def _show_edit_menu(callback: CallbackQuery, session: AsyncSession, chat_id: int, emoji: str) -> None:
    """
    Вспомогательная функция для отображения меню редактирования реакции.
    Вынесена отдельно чтобы можно было вызывать с параметрами напрямую,
    без изменения callback.data (который frozen в aiogram 3.x).
    """
    # Получаем настройки реакции
    settings = await get_emoji_settings(chat_id, emoji)
    info = REACTIONS_INFO.get(emoji, {"name": emoji})

    # Формируем текст
    action_info = ACTIONS.get(settings["action"], ACTIONS["mute"])
    duration_text = format_duration(settings.get("duration")) if settings["action"] == "mute" else "—"
    delete_msg = "да" if settings.get("delete_message", True) else "нет"

    text = (
        f"<b>Настройка реакции {emoji} {info.get('name', '')}</b>\n\n"
        f"Действие: {action_info['emoji']} {action_info['name']}\n"
        f"Длительность: {duration_text}\n"
        f"Удалять сообщение: {delete_msg}\n\n"
        f"Выберите параметр для изменения:"
    )

    # Создаём клавиатуру
    keyboard = create_reaction_edit_menu(chat_id, emoji, settings)

    # Обновляем сообщение
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:e:"))
async def edit_reaction_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Открывает меню редактирования реакции."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    # Проверяем права
    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    # Показываем меню
    await _show_edit_menu(callback, session, chat_id, emoji)
    await callback.answer()


# ============================================================
# ВЫБОР ДЕЙСТВИЯ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:a:"))
async def action_select_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Меню выбора действия."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    settings = await get_emoji_settings(chat_id, emoji)
    current_action = settings.get("action", "mute")

    text = f"<b>Выберите действие для {emoji}</b>\n\nТекущее: {ACTIONS.get(current_action, {}).get('name', current_action)}"
    keyboard = create_action_select_menu(chat_id, emoji, current_action)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:sa:"))
async def set_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Устанавливает действие."""
    parts = callback.data.split(":")
    emoji = parts[2]
    new_action = parts[3]
    chat_id = int(parts[4])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    # Обновляем действие
    update_data = {"action": new_action}
    if new_action in ("mute_forever", "warn", "delete", "ban"):
        update_data["duration"] = None

    await update_emoji_settings(chat_id, emoji, **update_data)

    action_info = ACTIONS.get(new_action, {})
    await callback.answer(f"Действие: {action_info.get('name', new_action)}")

    # Возвращаемся к меню редактирования
    await _show_edit_menu(callback, session, chat_id, emoji)


# ============================================================
# ВЫБОР ДЛИТЕЛЬНОСТИ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:d:"))
async def duration_select_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Меню выбора длительности."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    settings = await get_emoji_settings(chat_id, emoji)
    current_duration = settings.get("duration")

    text = f"<b>Длительность мута для {emoji}</b>\n\nТекущая: {format_duration(current_duration)}"
    keyboard = create_duration_select_menu(chat_id, emoji, current_duration)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:sd:"))
async def set_duration(callback: CallbackQuery, session: AsyncSession) -> None:
    """Устанавливает длительность из пресета."""
    parts = callback.data.split(":")
    emoji = parts[2]
    duration_str = parts[3]
    chat_id = int(parts[4])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    new_duration = None if duration_str == "inf" else int(duration_str)
    await update_emoji_settings(chat_id, emoji, duration=new_duration)

    await callback.answer(f"Длительность: {format_duration(new_duration)}")

    # Возвращаемся к меню редактирования
    await _show_edit_menu(callback, session, chat_id, emoji)


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:cd:"))
async def custom_duration_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запрос кастомной длительности."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.update_data(emoji=emoji, chat_id=chat_id)
    await state.set_state(ReactionSettingsStates.waiting_for_duration)

    text = (
        f"<b>Введите длительность для {emoji}</b>\n\n"
        f"Форматы:\n"
        f"- <code>30</code> или <code>30m</code> - 30 минут\n"
        f"- <code>1h</code> - 1 час\n"
        f"- <code>1d</code> - 1 день\n"
        f"- <code>навсегда</code> - бессрочно"
    )

    keyboard = create_cancel_keyboard(chat_id, emoji)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.message(ReactionSettingsStates.waiting_for_duration)
async def process_custom_duration(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обрабатывает кастомную длительность."""
    data = await state.get_data()
    emoji = data.get("emoji")
    chat_id = data.get("chat_id")

    if not emoji or not chat_id:
        await state.clear()
        return

    duration = parse_duration_input(message.text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if duration == -1:
        await message.answer("Неверный формат. Попробуйте: 30m, 1h, 1d, навсегда")
        return

    await update_emoji_settings(chat_id, emoji, duration=duration)
    await state.clear()

    settings = await get_emoji_settings(chat_id, emoji)
    info = REACTIONS_INFO.get(emoji, {"name": emoji})
    action_info = ACTIONS.get(settings["action"], ACTIONS["mute"])

    text = (
        f"Длительность установлена: {format_duration(duration)}\n\n"
        f"<b>Настройка реакции {emoji} {info.get('name', '')}</b>\n\n"
        f"Действие: {action_info['emoji']} {action_info['name']}"
    )

    keyboard = create_reaction_edit_menu(chat_id, emoji, settings)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# ПЕРЕКЛЮЧАТЕЛЬ УДАЛЕНИЯ СООБЩЕНИЯ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:tdm:"))
async def toggle_delete_message(callback: CallbackQuery, session: AsyncSession) -> None:
    """Переключает удаление сообщения нарушителя."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    settings = await get_emoji_settings(chat_id, emoji)
    new_value = not settings.get("delete_message", True)
    await update_emoji_settings(chat_id, emoji, delete_message=new_value)

    await callback.answer(f"Удалять сообщение: {'да' if new_value else 'нет'}")

    # Возвращаемся к меню редактирования
    await _show_edit_menu(callback, session, chat_id, emoji)


# ============================================================
# ЗАДЕРЖКА УДАЛЕНИЯ СООБЩЕНИЯ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:dd:"))
async def delete_delay_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Меню задержки удаления."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    settings = await get_emoji_settings(chat_id, emoji)
    current_delay = settings.get("delete_delay", 0)

    text = f"<b>Задержка удаления для {emoji}</b>\n\nТекущая: {current_delay} сек"
    keyboard = create_delete_delay_menu(chat_id, emoji, current_delay)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:sdd:"))
async def set_delete_delay(callback: CallbackQuery, session: AsyncSession) -> None:
    """Устанавливает задержку удаления из пресета."""
    parts = callback.data.split(":")
    emoji = parts[2]
    delay = int(parts[3])
    chat_id = int(parts[4])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await update_emoji_settings(chat_id, emoji, delete_delay=delay)
    await callback.answer(f"Задержка: {delay} сек" if delay else "Удаление сразу")

    # Возвращаемся к меню редактирования
    await _show_edit_menu(callback, session, chat_id, emoji)


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:cdd:"))
async def custom_delete_delay_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запрос кастомной задержки удаления."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.update_data(emoji=emoji, chat_id=chat_id)
    await state.set_state(ReactionSettingsStates.waiting_for_delete_delay)

    text = f"<b>Задержка удаления для {emoji}</b>\n\nВведите число секунд (0 = сразу):"
    keyboard = create_cancel_keyboard(chat_id, emoji)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.message(ReactionSettingsStates.waiting_for_delete_delay)
async def process_delete_delay(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обрабатывает кастомную задержку."""
    data = await state.get_data()
    emoji = data.get("emoji")
    chat_id = data.get("chat_id")

    if not emoji or not chat_id:
        await state.clear()
        return

    delay = parse_delay_input(message.text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if delay is None:
        await message.answer("Неверный формат. Введите число секунд.")
        return

    await update_emoji_settings(chat_id, emoji, delete_delay=delay)
    await state.clear()

    settings = await get_emoji_settings(chat_id, emoji)
    keyboard = create_reaction_edit_menu(chat_id, emoji, settings)
    await message.answer(f"Задержка: {delay} сек", reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# КАСТОМНЫЙ ТЕКСТ УВЕДОМЛЕНИЯ
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:ct:"))
async def custom_text_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запрос кастомного текста."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.update_data(emoji=emoji, chat_id=chat_id)
    await state.set_state(ReactionSettingsStates.waiting_for_custom_text)

    text = (
        f"<b>Текст уведомления для {emoji}</b>\n\n"
        f"Введите текст уведомления.\n"
        f"Используйте <code>%user%</code> для упоминания пользователя.\n"
        f"Используйте <code>%time%</code> для длительности.\n\n"
        f"Пример: <code>%user% получил мут на %time% за реакцию {emoji}</code>\n\n"
        f"Отправьте <code>-</code> чтобы сбросить на стандартный текст."
    )

    keyboard = create_cancel_keyboard(chat_id, emoji)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.message(ReactionSettingsStates.waiting_for_custom_text)
async def process_custom_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обрабатывает кастомный текст."""
    data = await state.get_data()
    emoji = data.get("emoji")
    chat_id = data.get("chat_id")

    if not emoji or not chat_id:
        await state.clear()
        return

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    text_input = message.text.strip()
    new_text = None if text_input == "-" else text_input

    if new_text and len(new_text) > 500:
        await message.answer("Текст слишком длинный (макс. 500 символов)")
        return

    await update_emoji_settings(chat_id, emoji, custom_text=new_text)
    await state.clear()

    settings = await get_emoji_settings(chat_id, emoji)
    keyboard = create_reaction_edit_menu(chat_id, emoji, settings)

    confirm = "Текст установлен" if new_text else "Текст сброшен на стандартный"
    await message.answer(confirm, reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# АВТОУДАЛЕНИЕ УВЕДОМЛЕНИЯ БОТА
# ============================================================

@reaction_mute_settings_router.callback_query(F.data.startswith("rm:nd:"))
async def notification_delay_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Меню автоудаления уведомления."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    settings = await get_emoji_settings(chat_id, emoji)
    current_delay = settings.get("notification_delete_delay")

    delay_text = f"{current_delay} сек" if current_delay else "не удалять"
    text = f"<b>Автоудаление уведомления для {emoji}</b>\n\nТекущее: {delay_text}"
    keyboard = create_notification_delay_menu(chat_id, emoji, current_delay)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:snd:"))
async def set_notification_delay(callback: CallbackQuery, session: AsyncSession) -> None:
    """Устанавливает автоудаление из пресета."""
    parts = callback.data.split(":")
    emoji = parts[2]
    delay_str = parts[3]
    chat_id = int(parts[4])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    new_delay = None if delay_str == "none" else int(delay_str)
    await update_emoji_settings(chat_id, emoji, notification_delete_delay=new_delay)

    delay_text = f"{new_delay} сек" if new_delay else "не удалять"
    await callback.answer(f"Автоудаление: {delay_text}")

    # Возвращаемся к меню редактирования
    await _show_edit_menu(callback, session, chat_id, emoji)


@reaction_mute_settings_router.callback_query(F.data.startswith("rm:cnd:"))
async def custom_notification_delay_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запрос кастомного автоудаления."""
    parts = callback.data.split(":")
    emoji = parts[2]
    chat_id = int(parts[3])

    if not await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "restrict_members", session):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.update_data(emoji=emoji, chat_id=chat_id)
    await state.set_state(ReactionSettingsStates.waiting_for_notification_delay)

    text = f"<b>Автоудаление уведомления для {emoji}</b>\n\nВведите секунды (0 = не удалять):"
    keyboard = create_cancel_keyboard(chat_id, emoji)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        pass
    await callback.answer()


@reaction_mute_settings_router.message(ReactionSettingsStates.waiting_for_notification_delay)
async def process_notification_delay(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обрабатывает кастомное автоудаление."""
    data = await state.get_data()
    emoji = data.get("emoji")
    chat_id = data.get("chat_id")

    if not emoji or not chat_id:
        await state.clear()
        return

    delay = parse_delay_input(message.text)

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if delay is None:
        await message.answer("Неверный формат. Введите число секунд.")
        return

    new_delay = delay if delay > 0 else None
    await update_emoji_settings(chat_id, emoji, notification_delete_delay=new_delay)
    await state.clear()

    settings = await get_emoji_settings(chat_id, emoji)
    keyboard = create_reaction_edit_menu(chat_id, emoji, settings)

    delay_text = f"{new_delay} сек" if new_delay else "не удалять"
    await message.answer(f"Автоудаление: {delay_text}", reply_markup=keyboard, parse_mode="HTML")


# ============================================================
# NOOP
# ============================================================

@reaction_mute_settings_router.callback_query(F.data == "rm:noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """Ничего не делает."""
    await callback.answer()
