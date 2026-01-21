# ═══════════════════════════════════════════════════════════════════════════
# UI НАСТРОЕК МОДУЛЯ РУЧНЫХ КОМАНД (/amute, /aban, /akick)
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит обработчики для настроек модуля:
# - Включить/выключить удаление сообщения нарушителя
# - Включить/выключить уведомление в группу
# - Время мута по умолчанию
#
# Callback формат: mcs:{action}:{param}:{chat_id}
# mcs = manual command settings
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

import logging
import re
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы
from bot.services.manual_commands import (
    get_manual_command_settings,
    update_mute_settings,
    format_duration,
)
from bot.services.groups_settings_in_private_logic import check_granular_permissions

# Создаём роутер
settings_router = Router(name="manual_commands_settings")

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# FSM ДЛЯ ВВОДА НАСТРОЕК
# ═══════════════════════════════════════════════════════════════════════════
class ManualCommandsSettingsStates(StatesGroup):
    """FSM для ввода настроек."""
    waiting_for_duration = State()
    waiting_for_notify_text = State()
    waiting_for_delete_delay = State()
    waiting_for_notify_delay = State()


# ═══════════════════════════════════════════════════════════════════════════
# СОЗДАНИЕ КЛАВИАТУРЫ НАСТРОЕК
# ═══════════════════════════════════════════════════════════════════════════
def format_delay(seconds: int) -> str:
    """Форматирует задержку в секундах для отображения."""
    if seconds == 0:
        return "сразу"
    elif seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins} мин"
    else:
        hours = seconds // 3600
        return f"{hours} ч"


def create_settings_keyboard(
    chat_id: int,
    delete_message: bool,
    notify_group: bool,
    default_duration: int,
    delete_delay: int = 0,
    notify_text: str | None = None,
    notify_delete_delay: int = 0,
    send_delete_command: bool = True,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру настроек модуля.

    Args:
        chat_id: ID группы
        delete_message: Удалять сообщение нарушителя
        notify_group: Уведомлять группу
        default_duration: Время мута по умолчанию (минуты)
        delete_delay: Задержка удаления сообщения (секунды)
        notify_text: Кастомный текст уведомления
        notify_delete_delay: Задержка удаления уведомления (секунды)
        send_delete_command: Удалять команду /asend после отправки
    """
    buttons = []

    # ─── БЛОК 1: Удаление сообщения нарушителя ───
    delete_icon = "✅" if delete_message else "❌"
    delete_btn = InlineKeyboardButton(
        text=f"{delete_icon} Удалять сообщение",
        callback_data=f"mcs:toggle:delete:{chat_id}"
    )
    buttons.append([delete_btn])

    # Показываем настройку задержки только если удаление включено
    if delete_message:
        delay_text = format_delay(delete_delay)
        delay_btn = InlineKeyboardButton(
            text=f"    ⏳ Задержка удаления: {delay_text}",
            callback_data=f"mcs:deldelay:{chat_id}"
        )
        buttons.append([delay_btn])

    # ─── БЛОК 2: Уведомление в группу ───
    notify_icon = "✅" if notify_group else "❌"
    notify_btn = InlineKeyboardButton(
        text=f"{notify_icon} Уведомлять группу",
        callback_data=f"mcs:toggle:notify:{chat_id}"
    )
    buttons.append([notify_btn])

    # Показываем настройки уведомления только если включено
    if notify_group:
        # Кастомный текст
        text_preview = "📝 По умолчанию" if not notify_text else f"📝 «{notify_text[:20]}...»"
        text_btn = InlineKeyboardButton(
            text=f"    {text_preview}",
            callback_data=f"mcs:notifytext:{chat_id}"
        )
        buttons.append([text_btn])

        # Задержка удаления уведомления
        if notify_delete_delay > 0:
            notify_del_text = format_delay(notify_delete_delay)
        else:
            notify_del_text = "не удалять"
        notify_del_btn = InlineKeyboardButton(
            text=f"    🗑 Удалить через: {notify_del_text}",
            callback_data=f"mcs:notifydelay:{chat_id}"
        )
        buttons.append([notify_del_btn])

    # ─── БЛОК 3: Время мута по умолчанию ───
    duration_text = format_duration(default_duration) if default_duration > 0 else "навсегда"
    duration_btn = InlineKeyboardButton(
        text=f"⏱️ Время по умолчанию: {duration_text}",
        callback_data=f"mcs:duration:{chat_id}"
    )
    buttons.append([duration_btn])

    # ─── БЛОК 4: Команда /asend ───
    send_icon = "✅" if send_delete_command else "❌"
    send_btn = InlineKeyboardButton(
        text=f"{send_icon} /asend: удалять команду",
        callback_data=f"mcs:toggle:senddelete:{chat_id}"
    )
    buttons.append([send_btn])

    # ─── Кнопка назад ───
    back_btn = InlineKeyboardButton(
        text="« Назад",
        callback_data=f"manage_group_{chat_id}"
    )
    buttons.append([back_btn])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_duration_keyboard(chat_id: int, current_duration: int = 1440) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора времени мута по умолчанию.

    Args:
        chat_id: ID группы
        current_duration: Текущее значение в минутах
    """
    # Предустановленные значения
    presets = [30, 60, 240, 720, 1440, 10080]
    preset_labels = {
        30: "30 мин",
        60: "1 час",
        240: "4 часа",
        720: "12 часов",
        1440: "1 день",
        10080: "7 дней",
    }

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 30 else ''}30 мин",
                callback_data=f"mcs:setdur:30:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 60 else ''}1 час",
                callback_data=f"mcs:setdur:60:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 240 else ''}4 часа",
                callback_data=f"mcs:setdur:240:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 720 else ''}12 часов",
                callback_data=f"mcs:setdur:720:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 1440 else ''}1 день",
                callback_data=f"mcs:setdur:1440:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 10080 else ''}7 дней",
                callback_data=f"mcs:setdur:10080:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_duration == 0 else ''}Навсегда",
                callback_data=f"mcs:setdur:0:{chat_id}"
            ),
        ],
    ]

    # Кнопка "Другое" для произвольного ввода
    if current_duration not in presets and current_duration != 0:
        other_text = f"✏️ Другое (✓ {format_duration(current_duration)})"
    else:
        other_text = "✏️ Другое"

    buttons.append([
        InlineKeyboardButton(text=other_text, callback_data=f"mcs:customdur:{chat_id}")
    ])

    buttons.append([
        InlineKeyboardButton(text="« Назад", callback_data=f"mcs:m:{chat_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ═══════════════════════════════════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:m:"))
async def handle_main_menu(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Показывает главное меню настроек модуля."""
    try:
        # Парсим chat_id
        chat_id = int(callback.data.split(":")[-1])

        # Проверяем права
        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        # Получаем настройки
        settings = await get_manual_command_settings(session, chat_id)

        # Формируем текст
        text = (
            "⚙️ <b>Настройки ручных команд</b>\n\n"
            "Команды: /amute, /aunmute, /asend\n\n"
            "<b>Опции:</b>\n"
            "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
            "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
            "• <b>Время по умолчанию</b> — время мута если не указано в команде\n\n"
            "<i>Используйте кнопки ниже для изменения настроек.</i>"
        )

        # Создаём клавиатуру
        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Settings menu error: {e}")
        await callback.answer("❌ Ошибка загрузки настроек", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# TOGGLE НАСТРОЕК
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:toggle:"))
async def handle_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Переключает boolean настройки."""
    try:
        # Парсим данные: mcs:toggle:delete:chat_id или mcs:toggle:notify:chat_id
        parts = callback.data.split(":")
        toggle_type = parts[2]
        chat_id = int(parts[3])

        # Проверяем права
        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        # Получаем текущие настройки
        settings = await get_manual_command_settings(session, chat_id)

        # Переключаем нужную настройку
        if toggle_type == "delete":
            new_value = not settings.mute_delete_message
            await update_mute_settings(session, chat_id, mute_delete_message=new_value)
            msg = "Удаление сообщений включено" if new_value else "Удаление сообщений выключено"
        elif toggle_type == "notify":
            new_value = not settings.mute_notify_group
            await update_mute_settings(session, chat_id, mute_notify_group=new_value)
            msg = "Уведомления включены" if new_value else "Уведомления выключены"
        elif toggle_type == "senddelete":
            new_value = not settings.send_delete_command
            await update_mute_settings(session, chat_id, send_delete_command=new_value)
            msg = "/asend: команда удаляется" if new_value else "/asend: команда остаётся"
        else:
            await callback.answer("❌ Неизвестный параметр", show_alert=True)
            return

        await session.commit()

        # Обновляем настройки
        settings = await get_manual_command_settings(session, chat_id)

        # Обновляем клавиатуру
        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer(f"✅ {msg}")

        logger.info(f"[MCS] Toggle {toggle_type}: chat_id={chat_id}, new_value={new_value}")

    except Exception as e:
        logger.error(f"[MCS] Toggle error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# МЕНЮ ВЫБОРА ВРЕМЕНИ
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:duration:"))
async def handle_duration_menu(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Показывает меню выбора времени мута по умолчанию."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        # Проверяем права
        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        # Получаем текущие настройки
        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⏱️ <b>Время мута по умолчанию</b>\n\n"
            "Это время будет использоваться когда команда /amute "
            "выполняется без указания времени.\n\n"
            "Выберите время:"
        )

        keyboard = create_duration_keyboard(chat_id, settings.mute_default_duration)

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Duration menu error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# УСТАНОВКА ВРЕМЕНИ
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:setdur:"))
async def handle_set_duration(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Устанавливает время мута по умолчанию."""
    try:
        # Парсим данные: mcs:setdur:1440:chat_id
        parts = callback.data.split(":")
        duration = int(parts[2])
        chat_id = int(parts[3])

        # Проверяем права
        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        # Сохраняем настройку
        await update_mute_settings(session, chat_id, mute_default_duration=duration)
        await session.commit()

        # Формируем сообщение
        duration_text = format_duration(duration) if duration > 0 else "навсегда"
        await callback.answer(f"✅ Время по умолчанию: {duration_text}")

        # Возвращаемся в главное меню
        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⚙️ <b>Настройки ручных команд</b>\n\n"
            "Команды: /amute, /aunmute, /asend\n\n"
            "<b>Опции:</b>\n"
            "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
            "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
            "• <b>Время по умолчанию</b> — время мута если не указано в команде\n\n"
            "<i>Используйте кнопки ниже для изменения настроек.</i>"
        )

        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(f"[MCS] Set duration: chat_id={chat_id}, duration={duration}")

    except Exception as e:
        logger.error(f"[MCS] Set duration error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# FSM: КАСТОМНЫЙ ВВОД ВРЕМЕНИ
# ═══════════════════════════════════════════════════════════════════════════
def create_back_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой Назад для FSM."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"mcs:duration:{chat_id}")]
    ])


@settings_router.callback_query(F.data.startswith("mcs:customdur:"))
async def handle_custom_duration_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Начинает FSM ввод кастомного времени."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        # Проверяем права
        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        # Сохраняем chat_id в состояние
        await state.update_data(chat_id=chat_id)
        await state.set_state(ManualCommandsSettingsStates.waiting_for_duration)

        text = (
            "⏱️ <b>Введите время мута</b>\n\n"
            "Формат: число + единица измерения\n"
            "• <code>30m</code> — 30 минут\n"
            "• <code>2h</code> — 2 часа\n"
            "• <code>1d</code> — 1 день\n"
            "• <code>7d</code> — 7 дней\n"
            "• <code>0</code> или <code>навсегда</code> — навсегда\n\n"
            "Или просто число (в минутах): <code>90</code> = 1.5 часа"
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=create_back_keyboard(chat_id),
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Custom duration start error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


def parse_duration_input(text: str) -> int | None:
    """
    Парсит ввод времени и возвращает минуты.

    Returns:
        int: минуты (0 = навсегда)
        None: ошибка парсинга
    """
    text = text.strip().lower()

    # Навсегда
    if text in ("0", "навсегда", "forever", "inf"):
        return 0

    # Формат с единицами: 30m, 2h, 1d, 7d
    match = re.match(r'^(\d+)\s*(m|min|мин|h|час|hour|d|день|day|w|week|нед)?$', text)
    if match:
        value = int(match.group(1))
        unit = match.group(2) or "m"

        if unit in ("m", "min", "мин"):
            return value
        elif unit in ("h", "час", "hour"):
            return value * 60
        elif unit in ("d", "день", "day"):
            return value * 1440
        elif unit in ("w", "week", "нед"):
            return value * 10080

        # Без единицы — минуты
        return value

    return None


@settings_router.message(ManualCommandsSettingsStates.waiting_for_duration)
async def handle_custom_duration_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
):
    """Обрабатывает ввод кастомного времени."""
    # Если команда — очищаем FSM
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте снова")
        return

    # Парсим ввод
    duration = parse_duration_input(message.text)

    if duration is None:
        await message.answer(
            "❌ Неверный формат. Примеры: <code>30m</code>, <code>2h</code>, <code>1d</code>, <code>навсегда</code>",
            parse_mode="HTML"
        )
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сохраняем настройку
    await update_mute_settings(session, chat_id, mute_default_duration=duration)
    await session.commit()

    # Очищаем FSM
    await state.clear()

    # Показываем обновлённое меню настроек
    settings = await get_manual_command_settings(session, chat_id)

    duration_text = format_duration(duration) if duration > 0 else "навсегда"

    text = (
        "⚙️ <b>Настройки ручных команд</b>\n\n"
        f"✅ Время по умолчанию установлено: <b>{duration_text}</b>\n\n"
        "Команды: /amute, /aunmute, /asend\n\n"
        "<b>Опции:</b>\n"
        "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
        "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
        "• <b>Время по умолчанию</b> — время мута если не указано в команде"
    )

    keyboard = create_settings_keyboard(
        chat_id=chat_id,
        delete_message=settings.mute_delete_message,
        notify_group=settings.mute_notify_group,
        default_duration=settings.mute_default_duration,
        delete_delay=settings.mute_delete_delay,
        notify_text=settings.mute_notify_text,
        notify_delete_delay=settings.mute_notify_delete_delay,
        send_delete_command=settings.send_delete_command,
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    logger.info(f"[MCS] Custom duration set: chat_id={chat_id}, duration={duration}")


# ═══════════════════════════════════════════════════════════════════════════
# МЕНЮ ЗАДЕРЖКИ УДАЛЕНИЯ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
def create_delete_delay_keyboard(chat_id: int, current_delay: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура выбора задержки удаления сообщения."""
    presets = [0, 3, 5, 10, 30, 60]

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 0 else ''}Сразу",
                callback_data=f"mcs:setdeldelay:0:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 3 else ''}3 сек",
                callback_data=f"mcs:setdeldelay:3:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 5 else ''}5 сек",
                callback_data=f"mcs:setdeldelay:5:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 10 else ''}10 сек",
                callback_data=f"mcs:setdeldelay:10:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 30 else ''}30 сек",
                callback_data=f"mcs:setdeldelay:30:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 60 else ''}1 мин",
                callback_data=f"mcs:setdeldelay:60:{chat_id}"
            ),
        ],
    ]

    # Кнопка "Другое" для кастомного значения
    if current_delay not in presets:
        other_text = f"✏️ Другое (✓ {format_delay(current_delay)})"
    else:
        other_text = "✏️ Другое"

    buttons.append([
        InlineKeyboardButton(text=other_text, callback_data=f"mcs:customdeldelay:{chat_id}")
    ])

    buttons.append([
        InlineKeyboardButton(text="« Назад", callback_data=f"mcs:m:{chat_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@settings_router.callback_query(F.data.startswith("mcs:deldelay:"))
async def handle_delete_delay_menu(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Показывает меню выбора задержки удаления сообщения."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⏳ <b>Задержка удаления сообщения</b>\n\n"
            "Через сколько секунд удалять сообщение нарушителя?\n\n"
            "<b>Сразу</b> — сообщение удаляется мгновенно\n"
            "<b>3-60 сек</b> — задержка перед удалением"
        )

        keyboard = create_delete_delay_keyboard(chat_id, settings.mute_delete_delay)

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Delete delay menu error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.callback_query(F.data.startswith("mcs:setdeldelay:"))
async def handle_set_delete_delay(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Устанавливает задержку удаления сообщения."""
    try:
        parts = callback.data.split(":")
        delay = int(parts[2])
        chat_id = int(parts[3])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await update_mute_settings(session, chat_id, mute_delete_delay=delay)
        await session.commit()

        delay_text = format_delay(delay)
        await callback.answer(f"✅ Задержка: {delay_text}")

        # Возвращаемся в главное меню
        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⚙️ <b>Настройки ручных команд</b>\n\n"
            "Команды: /amute, /aunmute, /asend\n\n"
            "<b>Опции:</b>\n"
            "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
            "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
            "• <b>Время по умолчанию</b> — время мута если не указано в команде\n\n"
            "<i>Используйте кнопки ниже для изменения настроек.</i>"
        )

        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(f"[MCS] Set delete delay: chat_id={chat_id}, delay={delay}")

    except Exception as e:
        logger.error(f"[MCS] Set delete delay error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# МЕНЮ ЗАДЕРЖКИ УДАЛЕНИЯ УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
def create_notify_delay_keyboard(chat_id: int, current_delay: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура выбора задержки удаления уведомления."""
    presets = [0, 10, 30, 60, 300, 600]

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 0 else ''}Не удалять",
                callback_data=f"mcs:setnotifydelay:0:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 10 else ''}10 сек",
                callback_data=f"mcs:setnotifydelay:10:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 30 else ''}30 сек",
                callback_data=f"mcs:setnotifydelay:30:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 60 else ''}1 мин",
                callback_data=f"mcs:setnotifydelay:60:{chat_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 300 else ''}5 мин",
                callback_data=f"mcs:setnotifydelay:300:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if current_delay == 600 else ''}10 мин",
                callback_data=f"mcs:setnotifydelay:600:{chat_id}"
            ),
        ],
    ]

    # Кнопка "Другое"
    if current_delay not in presets:
        other_text = f"✏️ Другое (✓ {format_delay(current_delay)})"
    else:
        other_text = "✏️ Другое"

    buttons.append([
        InlineKeyboardButton(text=other_text, callback_data=f"mcs:customnotifydelay:{chat_id}")
    ])

    buttons.append([
        InlineKeyboardButton(text="« Назад", callback_data=f"mcs:m:{chat_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@settings_router.callback_query(F.data.startswith("mcs:notifydelay:"))
async def handle_notify_delay_menu(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Показывает меню выбора задержки удаления уведомления."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "🗑 <b>Удалить уведомление через...</b>\n\n"
            "Через сколько удалять уведомление о муте из группы?\n\n"
            "<b>Не удалять</b> — уведомление останется в группе навсегда\n"
            "<b>10 сек — 10 мин</b> — автоматическое удаление через указанное время"
        )

        keyboard = create_notify_delay_keyboard(chat_id, settings.mute_notify_delete_delay)

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Notify delay menu error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.callback_query(F.data.startswith("mcs:setnotifydelay:"))
async def handle_set_notify_delay(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Устанавливает задержку удаления уведомления."""
    try:
        parts = callback.data.split(":")
        delay = int(parts[2])
        chat_id = int(parts[3])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await update_mute_settings(session, chat_id, mute_notify_delete_delay=delay)
        await session.commit()

        delay_text = "не удалять" if delay == 0 else format_delay(delay)
        await callback.answer(f"✅ Удалить через: {delay_text}")

        # Возвращаемся в главное меню
        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⚙️ <b>Настройки ручных команд</b>\n\n"
            "Команды: /amute, /aunmute, /asend\n\n"
            "<b>Опции:</b>\n"
            "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
            "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
            "• <b>Время по умолчанию</b> — время мута если не указано в команде\n\n"
            "<i>Используйте кнопки ниже для изменения настроек.</i>"
        )

        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(f"[MCS] Set notify delay: chat_id={chat_id}, delay={delay}")

    except Exception as e:
        logger.error(f"[MCS] Set notify delay error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# КАСТОМНЫЙ ТЕКСТ УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:notifytext:"))
async def handle_notify_text_menu(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Показывает меню для ввода кастомного текста уведомления."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        settings = await get_manual_command_settings(session, chat_id)

        current_text = settings.mute_notify_text or "(по умолчанию)"

        text = (
            "📝 <b>Текст уведомления о муте</b>\n\n"
            f"<b>Текущий:</b> <i>{current_text}</i>\n\n"
            "<b>Доступные переменные:</b>\n"
            "• <code>%user%</code> — ссылка на пользователя\n"
            "• <code>%time%</code> — время мута\n"
            "• <code>%reason%</code> — причина мута\n"
            "• <code>%admin%</code> — ссылка на админа\n\n"
            "<b>Пример:</b>\n"
            "<code>🔇 %user% замучен на %time%. Причина: %reason%</code>\n\n"
            "Отправьте новый текст или нажмите кнопку ниже:"
        )

        # Сохраняем chat_id и переходим в состояние ожидания
        await state.update_data(chat_id=chat_id)
        await state.set_state(ManualCommandsSettingsStates.waiting_for_notify_text)

        buttons = []
        if settings.mute_notify_text:
            buttons.append([
                InlineKeyboardButton(
                    text="🔄 Сбросить на стандартный",
                    callback_data=f"mcs:resetnotifytext:{chat_id}"
                )
            ])
        buttons.append([
            InlineKeyboardButton(text="« Назад", callback_data=f"mcs:m:{chat_id}")
        ])

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Notify text menu error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.callback_query(F.data.startswith("mcs:resetnotifytext:"))
async def handle_reset_notify_text(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Сбрасывает кастомный текст уведомления на стандартный."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await update_mute_settings(session, chat_id, mute_notify_text=None)
        await session.commit()
        await state.clear()

        await callback.answer("✅ Текст сброшен на стандартный")

        # Возвращаемся в главное меню
        settings = await get_manual_command_settings(session, chat_id)

        text = (
            "⚙️ <b>Настройки ручных команд</b>\n\n"
            "Команды: /amute, /aunmute, /asend\n\n"
            "<b>Опции:</b>\n"
            "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
            "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
            "• <b>Время по умолчанию</b> — время мута если не указано в команде\n\n"
            "<i>Используйте кнопки ниже для изменения настроек.</i>"
        )

        keyboard = create_settings_keyboard(
            chat_id=chat_id,
            delete_message=settings.mute_delete_message,
            notify_group=settings.mute_notify_group,
            default_duration=settings.mute_default_duration,
            delete_delay=settings.mute_delete_delay,
            notify_text=settings.mute_notify_text,
            notify_delete_delay=settings.mute_notify_delete_delay,
            send_delete_command=settings.send_delete_command,
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(f"[MCS] Reset notify text: chat_id={chat_id}")

    except Exception as e:
        logger.error(f"[MCS] Reset notify text error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.message(ManualCommandsSettingsStates.waiting_for_notify_text)
async def handle_notify_text_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
):
    """Обрабатывает ввод кастомного текста уведомления."""
    # Если команда — очищаем FSM
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте снова")
        return

    # Проверяем длину текста
    notify_text = message.text.strip()
    if len(notify_text) > 500:
        await message.answer("❌ Текст слишком длинный (макс. 500 символов)")
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Сохраняем настройку
    await update_mute_settings(session, chat_id, mute_notify_text=notify_text)
    await session.commit()

    # Очищаем FSM
    await state.clear()

    # Показываем обновлённое меню настроек
    settings = await get_manual_command_settings(session, chat_id)

    text = (
        "⚙️ <b>Настройки ручных команд</b>\n\n"
        f"✅ Текст уведомления сохранён:\n<i>«{notify_text[:50]}...»</i>\n\n"
        "Команды: /amute, /aunmute, /asend\n\n"
        "<b>Опции:</b>\n"
        "• <b>Удалять сообщение</b> — удалять сообщение нарушителя при муте\n"
        "• <b>Уведомлять группу</b> — отправлять уведомление о муте в группу\n"
        "• <b>Время по умолчанию</b> — время мута если не указано в команде"
    )

    keyboard = create_settings_keyboard(
        chat_id=chat_id,
        delete_message=settings.mute_delete_message,
        notify_group=settings.mute_notify_group,
        default_duration=settings.mute_default_duration,
        delete_delay=settings.mute_delete_delay,
        notify_text=settings.mute_notify_text,
        notify_delete_delay=settings.mute_notify_delete_delay,
        send_delete_command=settings.send_delete_command,
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    logger.info(f"[MCS] Set notify text: chat_id={chat_id}, text={notify_text[:30]}...")


# ═══════════════════════════════════════════════════════════════════════════
# FSM: КАСТОМНЫЙ ВВОД ЗАДЕРЖКИ УДАЛЕНИЯ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:customdeldelay:"))
async def handle_custom_delete_delay_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Начинает FSM ввод кастомной задержки удаления сообщения."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await state.update_data(chat_id=chat_id)
        await state.set_state(ManualCommandsSettingsStates.waiting_for_delete_delay)

        text = (
            "⏳ <b>Введите задержку удаления</b>\n\n"
            "Введите число секунд (0 = сразу):\n\n"
            "Примеры: <code>0</code>, <code>5</code>, <code>30</code>, <code>120</code>"
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data=f"mcs:deldelay:{chat_id}")]
            ]),
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Custom delete delay start error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.message(ManualCommandsSettingsStates.waiting_for_delete_delay)
async def handle_custom_delete_delay_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
):
    """Обрабатывает ввод кастомной задержки удаления."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте снова")
        return

    try:
        delay = int(message.text.strip())
        if delay < 0:
            await message.answer("❌ Задержка не может быть отрицательной")
            return
    except ValueError:
        await message.answer("❌ Введите целое число секунд")
        return

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await update_mute_settings(session, chat_id, mute_delete_delay=delay)
    await session.commit()
    await state.clear()

    settings = await get_manual_command_settings(session, chat_id)
    delay_text = format_delay(delay)

    text = (
        "⚙️ <b>Настройки ручных команд</b>\n\n"
        f"✅ Задержка удаления: <b>{delay_text}</b>\n\n"
        "Команды: /amute, /aunmute, /asend"
    )

    keyboard = create_settings_keyboard(
        chat_id=chat_id,
        delete_message=settings.mute_delete_message,
        notify_group=settings.mute_notify_group,
        default_duration=settings.mute_default_duration,
        delete_delay=settings.mute_delete_delay,
        notify_text=settings.mute_notify_text,
        notify_delete_delay=settings.mute_notify_delete_delay,
        send_delete_command=settings.send_delete_command,
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    logger.info(f"[MCS] Custom delete delay set: chat_id={chat_id}, delay={delay}")


# ═══════════════════════════════════════════════════════════════════════════
# FSM: КАСТОМНЫЙ ВВОД ЗАДЕРЖКИ УДАЛЕНИЯ УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
@settings_router.callback_query(F.data.startswith("mcs:customnotifydelay:"))
async def handle_custom_notify_delay_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Начинает FSM ввод кастомной задержки удаления уведомления."""
    try:
        chat_id = int(callback.data.split(":")[-1])

        if not await check_granular_permissions(
            callback.bot, callback.from_user.id, chat_id, "restrict_members", session
        ):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await state.update_data(chat_id=chat_id)
        await state.set_state(ManualCommandsSettingsStates.waiting_for_notify_delay)

        text = (
            "🗑 <b>Введите время удаления уведомления</b>\n\n"
            "Введите число секунд (0 = не удалять):\n\n"
            "Примеры: <code>0</code>, <code>30</code>, <code>60</code>, <code>300</code>"
        )

        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data=f"mcs:notifydelay:{chat_id}")]
            ]),
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"[MCS] Custom notify delay start error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@settings_router.message(ManualCommandsSettingsStates.waiting_for_notify_delay)
async def handle_custom_notify_delay_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
):
    """Обрабатывает ввод кастомной задержки удаления уведомления."""
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте снова")
        return

    try:
        delay = int(message.text.strip())
        if delay < 0:
            await message.answer("❌ Задержка не может быть отрицательной")
            return
    except ValueError:
        await message.answer("❌ Введите целое число секунд")
        return

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await update_mute_settings(session, chat_id, mute_notify_delete_delay=delay)
    await session.commit()
    await state.clear()

    settings = await get_manual_command_settings(session, chat_id)
    delay_text = "не удалять" if delay == 0 else format_delay(delay)

    text = (
        "⚙️ <b>Настройки ручных команд</b>\n\n"
        f"✅ Удалить уведомление через: <b>{delay_text}</b>\n\n"
        "Команды: /amute, /aunmute, /asend"
    )

    keyboard = create_settings_keyboard(
        chat_id=chat_id,
        delete_message=settings.mute_delete_message,
        notify_group=settings.mute_notify_group,
        default_duration=settings.mute_default_duration,
        delete_delay=settings.mute_delete_delay,
        notify_text=settings.mute_notify_text,
        notify_delete_delay=settings.mute_notify_delete_delay,
        send_delete_command=settings.send_delete_command,
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    logger.info(f"[MCS] Custom notify delay set: chat_id={chat_id}, delay={delay}")
