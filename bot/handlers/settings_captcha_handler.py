from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.group_display import build_group_header
from bot.services.groups_settings_in_private_logic import (
    get_group_by_chat_id,
    get_captcha_settings,
    set_visual_captcha_enabled,
    set_captcha_join_enabled,
    set_captcha_invite_enabled,
    set_captcha_timeout,
    set_captcha_message_ttl,
    # Новые сеттеры для TTL сообщений в группе
    set_join_captcha_message_ttl,
    set_invite_captcha_message_ttl,
    set_captcha_flood_threshold,
    set_captcha_flood_window,
    set_captcha_flood_action,
    set_system_mute_announcements_enabled,
    # Сеттер для действия при провале капчи (decline/keep)
    set_captcha_failure_action,
    get_captcha_failure_action,
    check_granular_permissions,
)
from bot.services.visual_captcha_logic import get_visual_captcha_status
from bot.services.bot_activity_journal.bot_activity_journal_logic import (
    log_captcha_setting_change,
    log_system_announcement_toggle,
)


logger = logging.getLogger(__name__)


captcha_settings_router = Router(name="captcha_settings_router")


class CaptchaSettingsStates(StatesGroup):
    waiting_for_value = State()


@dataclass
class CaptchaSettingsContext:
    chat_id: int
    parameter: str
    message_id: int


_DURATION_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>[smhd])", re.IGNORECASE)
_FLOOD_ACTIONS = ["warn", "mute", "ban"]


def _parse_duration_to_seconds(value: str) -> Optional[int]:
    total = 0
    for match in _DURATION_PATTERN.finditer(value.strip()):
        amount = int(match.group("value"))
        unit = match.group("unit").lower()
        if unit == "s":
            total += amount
        elif unit == "m":
            total += amount * 60
        elif unit == "h":
            total += amount * 3600
        elif unit == "d":
            total += amount * 86400
    return total or None


def _format_duration(seconds: int) -> str:
    parts = []
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if seconds or not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


async def _render_settings_text(chat, settings, *, visual_enabled: bool, failure_action: str = "decline") -> str:
    header = build_group_header(chat)
    lines = [header, "", "⚙️ <b>Настройки капчи</b>"]

    # Человекопонятное отображение failure_action
    # "decline" = отклонить заявку, "keep" = оставить висеть
    failure_action_display = "🚫 Отклонить" if failure_action == "decline" else "📌 Оставить"

    lines.extend(
        [
            f"Визуальная капча: {'🟢 включена' if visual_enabled else '🔴 выключена'}",
            f"Капча при вступлении: {'🟢' if settings.captcha_join_enabled else '🔴'}",
            f"Капча для инвайтов: {'🟢' if settings.captcha_invite_enabled else '🔴'}",
            f"При провале капчи: {failure_action_display}",
            f"Время на решение: {_format_duration(settings.captcha_timeout_seconds)}",
            f"Удаление сообщения: {_format_duration(settings.captcha_message_ttl_seconds)}",
            f"Анти-флуд порог: {settings.captcha_flood_threshold}",
            f"Анти-флуд окно: {_format_duration(settings.captcha_flood_window_seconds)}",
            f"Анти-флуд действие: {settings.captcha_flood_action}",
            f"Системные сообщения о мьютах: {'🟢' if settings.system_mute_announcements_enabled else '🔴'}",
        ]
    )
    return "\n\n".join(lines)


def _build_keyboard(chat_id: int, settings) -> list[list[tuple[str, str]]]:
    """
    Строит клавиатуру настроек капчи.

    Кнопки:
    - Переключатели режимов капчи (Visual, Join, Invite)
    - Настройка действия при провале капчи
    - Настройки времени и TTL
    - Настройки анти-флуда
    """
    return [
        # Переключатели режимов капчи
        [("Визуальная капча", f"captcha_toggle:visual:{chat_id}"), ("Капча при вступлении", f"captcha_toggle:join:{chat_id}")],
        [("Капча для инвайтов", f"captcha_toggle:invite:{chat_id}"), ("Системные сообщения", f"captcha_toggle:announce:{chat_id}")],
        # Действие при провале капчи (decline/keep)
        [("🚫 При провале капчи", f"captcha_cycle:failure_action:{chat_id}")],
        # Общее время на решение и legacy TTL
        [("⏳ Время на решение", f"captcha_input:timeout:{chat_id}"), ("🗑 TTL сообщения", f"captcha_input:ttl:{chat_id}")],
        # TTL автоудаления сообщений в группе для Join и Invite капчи
        [("🗑 TTL Join капчи", f"captcha_input:join_ttl:{chat_id}"), ("🗑 TTL Invite капчи", f"captcha_input:invite_ttl:{chat_id}")],
        # Настройки анти-флуда
        [("🛡 Порог анти-флуда", f"captcha_input:flood_threshold:{chat_id}"), ("⏱ Окно анти-флуда", f"captcha_input:flood_window:{chat_id}")],
        [("⚡️ Действие анти-флуда", f"captcha_cycle:flood_action:{chat_id}")],
        # Кнопка назад
        [("🔙 Назад", f"captcha_back:{chat_id}")],
    ]


async def _send_or_edit(callback: CallbackQuery, text: str, keyboard, *, parse_mode: str = "HTML") -> None:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data=data) for btn_text, data in row]
            for row in keyboard
        ]
    )
    # ФИКС №9: Убрать превью ссылки в названии группы
    await callback.message.edit_text(text, reply_markup=markup, parse_mode=parse_mode, disable_web_page_preview=True)


async def _refresh_view(callback: CallbackQuery, session: AsyncSession, chat_id: int) -> None:
    # Получаем информацию о группе и настройки капчи
    group = await get_group_by_chat_id(session, chat_id)
    settings = await get_captcha_settings(session, chat_id)
    # Получаем статус визуальной капчи из Redis
    visual_enabled = await get_visual_captcha_status(chat_id)
    # Получаем действие при провале капчи (decline/keep)
    failure_action = await get_captcha_failure_action(session, chat_id)
    # Рендерим текст с настройками и клавиатуру
    text = await _render_settings_text(group, settings, visual_enabled=visual_enabled, failure_action=failure_action)
    keyboard = _build_keyboard(chat_id, settings)
    await _send_or_edit(callback, text, keyboard)


@captcha_settings_router.callback_query(F.data.startswith("captcha_settings:"))
async def open_captcha_settings(callback: CallbackQuery, session: AsyncSession):
    chat_id = int(callback.data.split(":")[-1])
    has_permissions = await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "change_info", session)
    if not has_permissions:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    await _refresh_view(callback, session, chat_id)
    await callback.answer()


@captcha_settings_router.callback_query(F.data.startswith("captcha_toggle:"))
async def toggle_captcha_setting(callback: CallbackQuery, session: AsyncSession):
    _, toggle_type, chat_id_str = callback.data.split(":")
    chat_id = int(chat_id_str)

    has_permissions = await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "change_info", session)
    if not has_permissions:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return

    chat_info = await callback.bot.get_chat(chat_id)

    if toggle_type == "visual":
        # Проверяем текущее состояние
        visual_enabled = await get_visual_captcha_status(chat_id)

        # Если пытаемся ВКЛЮЧИТЬ - проверяем что группа ЗАКРЫТА
        if not visual_enabled:
            # Импортируем функцию проверки типа группы
            from bot.services.captcha.flow_service import is_group_closed

            # Проверяем закрыта ли группа (есть ли Join Request)
            is_closed = await is_group_closed(callback.bot, chat_id)

            # Visual Captcha работает ТОЛЬКО в закрытой группе
            if not is_closed:
                await callback.answer(
                    "❌ Visual Captcha работает только в закрытых группах.\n\n"
                    "Включите 'Одобрение заявок' в настройках группы.",
                    show_alert=True,
                )
                return

        logger.info(
            f"🔄 [CAPTCHA_TOGGLE] Переключение visual_captcha для chat={chat_id}: "
            f"текущее значение={visual_enabled}, новое значение={not visual_enabled}"
        )
        new_value = await set_visual_captcha_enabled(session, chat_id, not visual_enabled)
        logger.info(
            f"✅ [CAPTCHA_TOGGLE] visual_captcha обновлено для chat={chat_id}: "
            f"новое значение={new_value}. Проверяем Redis..."
        )
        # Проверяем, что Redis обновлён (используем уже импортированную функцию)
        redis_value = await get_visual_captcha_status(chat_id)
        if redis_value != new_value:
            logger.error(
                f"❌ [CAPTCHA_TOGGLE] КРИТИЧЕСКАЯ ОШИБКА: Redis не синхронизирован! "
                f"chat={chat_id}, ожидалось={new_value}, в Redis={redis_value}"
            )
        else:
            logger.info(
                f"✅ [CAPTCHA_TOGGLE] Redis синхронизирован для chat={chat_id}: {redis_value}"
            )
        await log_captcha_setting_change(
            bot=callback.bot,
            user=callback.from_user,
            chat=chat_info,
            setting="visual_captcha",
            value="on" if new_value else "off",
            session=session,
        )
    elif toggle_type == "join":
        settings = await get_captcha_settings(session, chat_id)

        # Если пытаемся ВКЛЮЧИТЬ - проверяем что группа ОТКРЫТА
        if not settings.captcha_join_enabled:
            # Импортируем функцию проверки типа группы
            from bot.services.captcha.flow_service import is_group_closed

            # Проверяем закрыта ли группа (есть ли Join Request)
            is_closed = await is_group_closed(callback.bot, chat_id)

            # Join Captcha работает ТОЛЬКО в открытой группе
            if is_closed:
                await callback.answer(
                    "❌ Капча при вступлении работает только в открытых группах.\n\n"
                    "Отключите 'Одобрение заявок' в настройках группы.",
                    show_alert=True,
                )
                return

        new_value = await set_captcha_join_enabled(session, chat_id, not settings.captcha_join_enabled)
        await log_captcha_setting_change(
            bot=callback.bot,
            user=callback.from_user,
            chat=chat_info,
            setting="captcha_join_enabled",
            value="on" if new_value else "off",
            session=session,
        )
    elif toggle_type == "invite":
        settings = await get_captcha_settings(session, chat_id)
        new_value = await set_captcha_invite_enabled(session, chat_id, not settings.captcha_invite_enabled)
        await log_captcha_setting_change(
            bot=callback.bot,
            user=callback.from_user,
            chat=chat_info,
            setting="captcha_invite_enabled",
            value="on" if new_value else "off",
            session=session,
        )
    elif toggle_type == "announce":
        settings = await get_captcha_settings(session, chat_id)
        new_value = await set_system_mute_announcements_enabled(session, chat_id, not settings.system_mute_announcements_enabled)
        await log_system_announcement_toggle(
            bot=callback.bot,
            user=callback.from_user,
            chat=chat_info,
            enabled=new_value,
            session=session,
        )
    else:
        await callback.answer("Неизвестный параметр", show_alert=True)
        return

    await _refresh_view(callback, session, chat_id)
    await callback.answer("✅ Настройка обновлена", show_alert=True)


# Варианты действий при провале капчи для циклического переключения
# "decline" = отклонить заявку (заявка удаляется из Telegram)
# "keep" = оставить заявку висеть (админ может одобрить вручную)
_FAILURE_ACTIONS = ["decline", "keep"]

# Человекопонятные названия для действий при провале
_FAILURE_ACTION_NAMES = {
    "decline": "Отклонить заявку",
    "keep": "Оставить заявку",
}


@captcha_settings_router.callback_query(F.data.startswith("captcha_cycle:"))
async def cycle_captcha_setting(callback: CallbackQuery, session: AsyncSession):
    """
    Циклически переключает настройку капчи.

    Поддерживает:
    - flood_action: warn → mute → ban → warn...
    - failure_action: decline → keep → decline...
    """
    _, param, chat_id_str = callback.data.split(":")
    chat_id = int(chat_id_str)

    # Проверяем права пользователя на изменение настроек
    has_permissions = await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "change_info", session)
    if not has_permissions:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return

    # Обрабатываем разные параметры
    if param == "flood_action":
        # Циклическое переключение действия анти-флуда: warn → mute → ban
        settings = await get_captcha_settings(session, chat_id)
        current = settings.captcha_flood_action
        try:
            index = _FLOOD_ACTIONS.index(current)
        except ValueError:
            index = 0
        new_action = _FLOOD_ACTIONS[(index + 1) % len(_FLOOD_ACTIONS)]

        await set_captcha_flood_action(session, chat_id, new_action)
        await log_captcha_setting_change(
            bot=callback.bot,
            user=callback.from_user,
            chat=await callback.bot.get_chat(chat_id),
            setting="captcha_flood_action",
            value=new_action,
            session=session,
        )
        notification = "✅ Действие анти-флуда обновлено"

    elif param == "failure_action":
        # Циклическое переключение действия при провале капчи: decline → keep
        current = await get_captcha_failure_action(session, chat_id)
        try:
            index = _FAILURE_ACTIONS.index(current)
        except ValueError:
            index = 0
        new_action = _FAILURE_ACTIONS[(index + 1) % len(_FAILURE_ACTIONS)]

        await set_captcha_failure_action(session, chat_id, new_action)
        await log_captcha_setting_change(
            bot=callback.bot,
            user=callback.from_user,
            chat=await callback.bot.get_chat(chat_id),
            setting="captcha_failure_action",
            value=new_action,
            session=session,
        )
        # Показываем человекопонятное название
        action_name = _FAILURE_ACTION_NAMES.get(new_action, new_action)
        notification = f"✅ При провале: {action_name}"

    else:
        # Неизвестный параметр
        await callback.answer("❌ Неизвестный параметр", show_alert=True)
        return

    await _refresh_view(callback, session, chat_id)
    await callback.answer(notification, show_alert=True)


@captcha_settings_router.callback_query(F.data.startswith("captcha_input:"))
async def request_value_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, parameter, chat_id_str = callback.data.split(":")
    chat_id = int(chat_id_str)

    has_permissions = await check_granular_permissions(callback.bot, callback.from_user.id, chat_id, "change_info", session)
    if not has_permissions:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return

    await state.set_state(CaptchaSettingsStates.waiting_for_value)
    await state.set_data(
        CaptchaSettingsContext(
            chat_id=chat_id,
            parameter=parameter,
            message_id=callback.message.message_id,
        ).__dict__
    )

    # Подсказки для каждого параметра
    prompts = {
        # Общее время на решение капчи
        "timeout": "Введите время на решение капчи (например, 2m, 3h, 1h30m)",
        # Legacy TTL сообщения
        "ttl": "Введите TTL удаления сообщения с капчей",
        # TTL сообщения Join Captcha в группе (автоудаление)
        "join_ttl": "Введите TTL автоудаления сообщения Join капчи в группе (например, 5m, 10m)",
        # TTL сообщения Invite Captcha в группе (автоудаление)
        "invite_ttl": "Введите TTL автоудаления сообщения Invite капчи в группе (например, 5m, 10m)",
        # Анти-флуд настройки
        "flood_threshold": "Введите порог анти-флуда (количество приглашений)",
        "flood_window": "Введите окно анти-флуда (например, 10m, 1h)",
    }

    await callback.message.answer(prompts.get(parameter, "Введите значение"))
    await callback.answer()


@captcha_settings_router.message(CaptchaSettingsStates.waiting_for_value)
async def process_value_input(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    context = CaptchaSettingsContext(**data)
    chat_id = context.chat_id
    parameter = context.parameter
    value_text = message.text.strip()

    try:
        # Обработка параметров с длительностью (timeout, ttl, flood_window, join_ttl, invite_ttl)
        if parameter in {"timeout", "ttl", "flood_window", "join_ttl", "invite_ttl"}:
            # Парсим введённое значение в секунды
            seconds = _parse_duration_to_seconds(value_text)
            # Проверяем что значение корректное
            if seconds is None or seconds <= 0:
                await message.reply("❌ Неверный формат длительности")
                return

            # Применяем настройку в зависимости от параметра
            if parameter == "timeout":
                # Общее время на решение капчи
                await set_captcha_timeout(session, chat_id, seconds)
                setting_name = "captcha_timeout_seconds"
            elif parameter == "ttl":
                # Legacy TTL сообщения
                await set_captcha_message_ttl(session, chat_id, seconds)
                setting_name = "captcha_message_ttl_seconds"
            elif parameter == "join_ttl":
                # TTL автоудаления сообщения Join Captcha в группе
                await set_join_captcha_message_ttl(session, chat_id, seconds)
                setting_name = "join_captcha_message_ttl_seconds"
            elif parameter == "invite_ttl":
                # TTL автоудаления сообщения Invite Captcha в группе
                await set_invite_captcha_message_ttl(session, chat_id, seconds)
                setting_name = "invite_captcha_message_ttl_seconds"
            else:
                # flood_window - окно анти-флуда
                await set_captcha_flood_window(session, chat_id, seconds)
                setting_name = "captcha_flood_window_seconds"

            # Логируем изменение настройки
            await log_captcha_setting_change(
                bot=message.bot,
                user=message.from_user,
                chat=await message.bot.get_chat(chat_id),
                setting=setting_name,
                value=seconds,
                session=session,
            )

        elif parameter == "flood_threshold":
            threshold = int(value_text)
            await set_captcha_flood_threshold(session, chat_id, threshold)
            await log_captcha_setting_change(
                bot=message.bot,
                user=message.from_user,
                chat=await message.bot.get_chat(chat_id),
                setting="captcha_flood_threshold",
                value=threshold,
                session=session,
            )
        else:
            await message.reply("❌ Неизвестный параметр")
            return

        await message.reply("✅ Значение обновлено")
    except ValueError:
        await message.reply("❌ Неверное значение")
        return
    finally:
        await state.clear()

    group = await get_group_by_chat_id(session, chat_id)
    settings = await get_captcha_settings(session, chat_id)
    visual_enabled = await get_visual_captcha_status(chat_id)
    text = await _render_settings_text(group, settings, visual_enabled=visual_enabled)
    keyboard = _build_keyboard(chat_id, settings)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data=data) for btn_text, data in row]
            for row in keyboard
        ]
    )

    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=context.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")


@captcha_settings_router.callback_query(F.data.startswith("captcha_back:"))
async def captcha_back(callback: CallbackQuery, session: AsyncSession):
    from bot.handlers.group_settings_handler.groups_settings_in_private_handler import create_group_management_keyboard, send_group_management_menu
    chat_id = int(callback.data.split(":")[-1])
    group = await get_group_by_chat_id(session, chat_id)
    
    # КРИТИЧЕСКИЙ ФИКС: Проверяем, что группа найдена
    if not group:
        logger.error(f"❌ [CAPTCHA_BACK] Группа с chat_id={chat_id} не найдена в БД")
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return
    
    # БАГ #11 ФИКС: Передаем user_id напрямую из callback.from_user.id
    await send_group_management_menu(callback.message, session, group, user_id=callback.from_user.id)
    await callback.answer()
