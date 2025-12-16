# bot/handlers/captcha/captcha_callbacks.py
"""
Callback обработчики капчи - обработка нажатий кнопок.

Содержит:
- Обработка ответов на капчу (verify)
- Обработка настроек капчи для админов
- Проверка принадлежности капчи (антихайджек)

ВАЖНО: Все callback_data содержат owner_id для проверки владельца!
"""

import logging
import re

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.captcha import (
    CaptchaMode,
    get_captcha_settings,
    update_captcha_setting,
    verify_captcha_answer,
    check_captcha_ownership_by_callback_data,
    process_captcha_success,
    process_captcha_failure,
    increment_attempts,
    get_captcha_data,
)
from bot.handlers.captcha.captcha_keyboards import (
    build_captcha_settings_keyboard,
    build_timeout_input_keyboard,
    build_limit_input_keyboard,
    build_overflow_action_keyboard,
    build_mode_settings_keyboard,
    build_message_ttl_keyboard,
)


# Логгер для отслеживания callback обработки
logger = logging.getLogger(__name__)

# Роутер для callback обработчиков
callbacks_router = Router(name="captcha_callbacks")


# ═══════════════════════════════════════════════════════════════════════════
# FSM СОСТОЯНИЯ ДЛЯ РУЧНОГО ВВОДА
# Используются только для ввода кастомных значений, сразу очищаются
# ═══════════════════════════════════════════════════════════════════════════

class CaptchaInputStates(StatesGroup):
    """Состояния для ручного ввода настроек капчи"""
    # Ввод таймаута
    waiting_timeout_input = State()
    # Ввод лимита
    waiting_limit_input = State()


# ═══════════════════════════════════════════════════════════════════════════
# ОБРАБОТКА ОТВЕТОВ НА КАПЧУ
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.startswith("captcha:verify:"))
async def handle_verify_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Обрабатывает нажатие кнопки с вариантом ответа.

    Формат callback_data: captcha:verify:{owner_id}:{chat_id}:{answer_hash}

    КРИТИЧНО: Проверяем что кнопку нажимает владелец капчи!

    Args:
        callback: Событие callback
        session: Сессия БД
    """
    # Парсим callback_data
    # Формат: captcha:verify:{owner_id}:{chat_id}:{answer_hash}
    parts = callback.data.split(":")
    if len(parts) < 5:
        await callback.answer("❌ Ошибка: неверный формат данных")
        return

    try:
        owner_id = int(parts[2])
        chat_id = int(parts[3])
        answer_hash = parts[4]
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка: неверные данные")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # ПРОВЕРКА ВЛАДЕЛЬЦА - КРИТИЧЕСКИ ВАЖНО!
    # ═══════════════════════════════════════════════════════════════════════
    clicker_id = callback.from_user.id

    is_owner = check_captcha_ownership_by_callback_data(
        clicker_user_id=clicker_id,
        owner_from_callback=owner_id,
        chat_id=chat_id,
    )

    if not is_owner:
        # Пытаются нажать чужую капчу!
        await callback.answer(
            "❌ Эта капча предназначена для другого пользователя",
            show_alert=True,
        )
        logger.warning(
            f"🚫 [CAPTCHA_HIJACK] Попытка нажать чужую капчу: "
            f"clicker={clicker_id}, owner={owner_id}, chat={chat_id}"
        )
        return

    # ═══════════════════════════════════════════════════════════════════════
    # ОТМЕЧАЕМ ЧТО ПОЛЬЗОВАТЕЛЬ НАЧАЛ РЕШАТЬ - ОСТАНАВЛИВАЕТ НАПОМИНАНИЯ
    # ═══════════════════════════════════════════════════════════════════════
    from bot.services.captcha.reminder_service import mark_user_interacted
    await mark_user_interacted(owner_id, chat_id)

    # ═══════════════════════════════════════════════════════════════════════
    # ПРОВЕРКА ОТВЕТА
    # ═══════════════════════════════════════════════════════════════════════
    is_correct = await verify_captcha_answer(
        user_id=owner_id,
        chat_id=chat_id,
        answer_hash=answer_hash,
    )

    # Получаем данные капчи для определения режима
    captcha_data = await get_captcha_data(owner_id, chat_id)
    if not captcha_data:
        await callback.answer("⏰ Время капчи истекло", show_alert=True)
        try:
            await callback.message.delete()
        except:
            pass
        return

    # Определяем режим
    mode_str = captcha_data.get("mode", "visual_dm")
    mode = CaptchaMode(mode_str)

    if is_correct:
        # ✅ ПРАВИЛЬНЫЙ ОТВЕТ
        await callback.answer("✅ Капча пройдена!")

        # Обрабатываем успех
        await process_captcha_success(
            bot=callback.bot,
            session=session,
            chat_id=chat_id,
            user_id=owner_id,
            mode=mode,
        )

        logger.info(
            f"✅ [CAPTCHA_VERIFY] Правильный ответ: "
            f"user_id={owner_id}, chat_id={chat_id}"
        )

    else:
        # ❌ НЕПРАВИЛЬНЫЙ ОТВЕТ
        # Получаем настройки группы для max_attempts
        from bot.services.captcha.settings_service import get_captcha_settings
        settings = await get_captcha_settings(session, chat_id)

        # Увеличиваем счётчик попыток (используем значение из настроек)
        attempts, exceeded = await increment_attempts(
            user_id=owner_id,
            chat_id=chat_id,
            max_attempts=settings.max_attempts,
        )

        if exceeded:
            # Исчерпаны попытки
            await callback.answer(
                "❌ Вы исчерпали все попытки",
                show_alert=True,
            )

            # Обрабатываем провал
            await process_captcha_failure(
                bot=callback.bot,
                session=session,
                chat_id=chat_id,
                user_id=owner_id,
                mode=mode,
                reason="max_attempts",
            )

            logger.info(
                f"❌ [CAPTCHA_VERIFY] Исчерпаны попытки: "
                f"user_id={owner_id}, chat_id={chat_id}"
            )

        else:
            # Ещё есть попытки - используем max_attempts из настроек
            remaining = settings.max_attempts - attempts
            await callback.answer(
                f"❌ Неверно! Осталось попыток: {remaining}",
                show_alert=True,
            )

            logger.info(
                f"⚠️ [CAPTCHA_VERIFY] Неверный ответ: "
                f"user_id={owner_id}, attempts={attempts}/{settings.max_attempts}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ КАПЧИ
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:settings:-?\d+$"))
async def handle_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает главное меню настроек капчи.

    Формат callback_data: captcha:settings:{chat_id}
    """
    # Парсим chat_id
    chat_id = int(callback.data.split(":")[-1])

    # Получаем настройки
    settings = await get_captcha_settings(session, chat_id)

    # Создаём клавиатуру
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    # Формируем текст
    text = (
        "⚙️ <b>Настройки капчи</b>\n\n"
        "Выберите режим для настройки:\n\n"
        "• <b>Visual Captcha</b> - капча в ЛС (требует Join Requests)\n"
        "• <b>Join Captcha</b> - капча в группе при входе\n"
        "• <b>Invite Captcha</b> - капча при приглашении"
    )

    # Обновляем сообщение
    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:toggle:[\w_]+:-?\d+$"))
async def handle_toggle_mode(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает режим капчи (вкл/выкл).

    Формат callback_data: captcha:toggle:{mode}:{chat_id}
    """
    # Парсим данные
    parts = callback.data.split(":")
    mode_str = parts[2]
    chat_id = int(parts[3])

    # Маппинг режимов на поля настроек
    mode_to_field = {
        "visual_dm": "visual_captcha_enabled",
        "join_group": "join_captcha_enabled",
        "invite_group": "invite_captcha_enabled",
    }

    field = mode_to_field.get(mode_str)
    if not field:
        await callback.answer("❌ Неизвестный режим")
        return

    # Получаем текущие настройки
    settings = await get_captcha_settings(session, chat_id)

    # Определяем текущее состояние
    current_map = {
        "visual_dm": settings.visual_captcha_enabled,
        "join_group": settings.join_captcha_enabled,
        "invite_group": settings.invite_captcha_enabled,
    }
    current = current_map.get(mode_str)

    # ═══════════════════════════════════════════════════════════════════════
    # ПРОВЕРКА ТИПА ГРУППЫ ПРИ ВКЛЮЧЕНИИ РЕЖИМА
    # ═══════════════════════════════════════════════════════════════════════

    # Если пытаемся ВКЛЮЧИТЬ режим (current=False/None → хотим включить)
    if not current:
        # Импортируем функцию проверки типа группы
        from bot.services.captcha.flow_service import is_group_closed

        # Определяем закрыта ли группа (есть ли одобрение заявок)
        is_closed = await is_group_closed(callback.bot, chat_id)

        # Visual DM работает только в ЗАКРЫТЫХ группах
        if mode_str == "visual_dm" and not is_closed:
            await callback.answer(
                "Visual Captcha работает только в закрытых группах.\n"
                "Включите 'Одобрение заявок' в настройках группы Telegram.",
                show_alert=True,
            )
            return

        # Join Group работает только в ОТКРЫТЫХ группах
        if mode_str == "join_group" and is_closed:
            await callback.answer(
                "Join Captcha работает только в открытых группах.\n"
                "Отключите 'Одобрение заявок' в настройках группы Telegram.",
                show_alert=True,
            )
            return

    # Инвертируем значение (None → True, True → False, False → True)
    new_value = not bool(current)

    # Обновляем настройку
    await update_captcha_setting(session, chat_id, field, new_value)
    await session.commit()

    # Обновляем клавиатуру
    updated_settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, updated_settings)

    # Показываем подтверждение
    status = "включён" if new_value else "выключен"
    await callback.answer(f"Режим {mode_str} {status}")

    # Обновляем сообщение
    text = (
        "⚙️ <b>Настройки капчи</b>\n\n"
        "Выберите режим для настройки:\n\n"
        "• <b>Visual Captcha</b> - капча в ЛС (требует Join Requests)\n"
        "• <b>Join Captcha</b> - капча в группе при входе\n"
        "• <b>Invite Captcha</b> - капча при приглашении"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:timeout:[\w_]+:-?\d+$"))
async def handle_timeout_menu(
    callback: CallbackQuery,
) -> None:
    """
    Показывает меню выбора таймаута.

    Формат callback_data: captcha:timeout:{mode}:{chat_id}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])

    # Создаём клавиатуру выбора таймаута
    keyboard = build_timeout_input_keyboard(chat_id, mode)

    # Текст
    mode_names = {
        "visual_dm": "Visual Captcha",
        "join_group": "Join Captcha",
        "invite_group": "Invite Captcha",
    }
    mode_name = mode_names.get(mode, mode)

    text = (
        f"⏱ <b>Таймаут для {mode_name}</b>\n\n"
        f"Выберите время или введите вручную:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:timeout_val:[\w_]+:-?\d+:\d+$"))
async def handle_timeout_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает выбранный таймаут.

    Формат callback_data: captcha:timeout_val:{mode}:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])
    value = int(parts[4])

    # Маппинг режимов на поля
    mode_to_field = {
        "visual_dm": "visual_captcha_timeout",
        "join_group": "join_captcha_timeout",
        "invite_group": "invite_captcha_timeout",
    }

    field = mode_to_field.get(mode)
    if not field:
        await callback.answer("❌ Ошибка")
        return

    # Сохраняем значение
    await update_captcha_setting(session, chat_id, field, value)
    await session.commit()

    # Показываем подтверждение
    await callback.answer(f"✅ Таймаут установлен: {value} сек")

    # Возвращаемся в меню настроек
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    text = (
        "⚙️ <b>Настройки капчи</b>\n\n"
        "Выберите режим для настройки:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:limit:-?\d+$"))
async def handle_limit_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора лимита капч.

    Формат callback_data: captcha:limit:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_limit_input_keyboard(chat_id)

    text = (
        "📊 <b>Лимит одновременных капч</b>\n\n"
        "Выберите максимальное количество активных капч в группе:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:limit_val:-?\d+:\d+$"))
async def handle_limit_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает выбранный лимит.

    Формат callback_data: captcha:limit_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    value = int(parts[3])

    # Сохраняем
    await update_captcha_setting(session, chat_id, "max_pending", value)
    await session.commit()

    await callback.answer(f"✅ Лимит установлен: {value}")

    # Возвращаемся в меню
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    await callback.message.edit_text(
        text="⚙️ <b>Настройки капчи</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:overflow:-?\d+$"))
async def handle_overflow_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора действия при переполнении.

    Формат callback_data: captcha:overflow:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_overflow_action_keyboard(chat_id)

    text = (
        "⚡ <b>Действие при переполнении</b>\n\n"
        "Что делать когда достигнут лимит активных капч:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:overflow_val:-?\d+:\w+$"))
async def handle_overflow_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает действие при переполнении.

    Формат callback_data: captcha:overflow_val:{chat_id}:{action}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    action = parts[3]

    # Валидация действия
    valid_actions = ["remove_oldest", "auto_decline", "queue"]
    if action not in valid_actions:
        await callback.answer("❌ Неверное действие")
        return

    # Сохраняем
    await update_captcha_setting(session, chat_id, "overflow_action", action)
    await session.commit()

    # Маппинг для отображения
    action_names = {
        "remove_oldest": "удалять старые",
        "auto_decline": "отклонять новые",
        "queue": "очередь",
    }

    await callback.answer(f"✅ Действие: {action_names[action]}")

    # Возвращаемся в меню
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    await callback.message.edit_text(
        text="⚙️ <b>Настройки капчи</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data == "captcha:noop")
async def handle_noop(callback: CallbackQuery) -> None:
    """Обработчик для декоративных кнопок (разделителей)"""
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════
# FSM ДЛЯ РУЧНОГО ВВОДА
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:timeout_input:[\w_]+:-?\d+$"))
async def handle_timeout_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода таймаута.

    Формат callback_data: captcha:timeout_input:{mode}:{chat_id}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])

    # Сохраняем контекст в FSM
    await state.update_data(mode=mode, chat_id=chat_id)
    await state.set_state(CaptchaInputStates.waiting_timeout_input)

    await callback.message.edit_text(
        "✏️ <b>Введите таймаут</b>\n\n"
        "Введите значение в секундах (например: 120):",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(CaptchaInputStates.waiting_timeout_input)
async def handle_timeout_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """
    Обрабатывает ввод таймаута пользователем.
    """
    from aiogram.types import Message

    # Получаем контекст
    data = await state.get_data()
    mode = data.get("mode")
    chat_id = data.get("chat_id")

    # Парсим значение
    try:
        value = int(message.text.strip())
        if value < 10:
            await message.answer("❌ Минимальное значение: 10 секунд")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    # Маппинг режимов на поля
    mode_to_field = {
        "visual_dm": "visual_captcha_timeout",
        "join_group": "join_captcha_timeout",
        "invite_group": "invite_captcha_timeout",
    }

    field = mode_to_field.get(mode)
    if field:
        await update_captcha_setting(session, chat_id, field, value)
        await session.commit()

    # Очищаем FSM сразу
    await state.clear()

    # Показываем результат
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ Таймаут установлен: {value} сек\n\n"
        "⚙️ <b>Настройки капчи</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:limit_input:-?\d+$"))
async def handle_limit_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода лимита.

    Формат callback_data: captcha:limit_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    # Сохраняем контекст
    await state.update_data(chat_id=chat_id)
    await state.set_state(CaptchaInputStates.waiting_limit_input)

    await callback.message.edit_text(
        "✏️ <b>Введите лимит</b>\n\n"
        "Введите максимальное количество капч (например: 15):",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(CaptchaInputStates.waiting_limit_input)
async def handle_limit_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """
    Обрабатывает ввод лимита пользователем.
    """
    from aiogram.types import Message

    # Получаем контекст
    data = await state.get_data()
    chat_id = data.get("chat_id")

    # Парсим значение
    try:
        value = int(message.text.strip())
        if value < 1:
            await message.answer("❌ Минимальное значение: 1")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    # Сохраняем
    await update_captcha_setting(session, chat_id, "max_pending", value)
    await session.commit()

    # Очищаем FSM сразу
    await state.clear()

    # Показываем результат
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ Лимит установлен: {value}\n\n"
        "⚙️ <b>Настройки капчи</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ ДИАЛОГОВ
# ═══════════════════════════════════════════════════════════════════════════

from bot.handlers.captcha.captcha_keyboards import (
    build_dialog_settings_keyboard,
    build_button_count_keyboard,
    build_attempts_keyboard,
    build_reminder_keyboard,
    build_cleanup_keyboard,
)


class DialogInputStates(StatesGroup):
    """Состояния для ручного ввода настроек диалогов"""
    waiting_buttons_input = State()
    waiting_attempts_input = State()
    waiting_reminder_input = State()
    waiting_reminder_count_input = State()
    waiting_cleanup_input = State()
    waiting_msg_ttl_input = State()  # TTL сообщения капчи в группе


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:-?\d+$"))
async def handle_dialog_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Показывает меню настроек диалогов.

    Формат callback_data: captcha:dialog:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    # Получаем настройки
    settings = await get_captcha_settings(session, chat_id)

    # Создаём клавиатуру
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    # Текст
    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        "Параметры взаимодействия с пользователем:\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:manual:-?\d+$"))
async def handle_toggle_manual_input(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Переключает ручной ввод капчи (вкл/выкл).

    Формат callback_data: captcha:dialog:manual:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    # Получаем текущие настройки
    settings = await get_captcha_settings(session, chat_id)

    # Инвертируем значение
    new_value = not settings.manual_input_enabled

    # Сохраняем
    await update_captcha_setting(session, chat_id, "manual_input_enabled", new_value)
    await session.commit()

    # Обновляем
    updated_settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, updated_settings)

    status = "включён" if new_value else "выключен"
    await callback.answer(f"Ручной ввод {status}")

    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        "Параметры взаимодействия с пользователем:\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if updated_settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {updated_settings.button_count}\n"
        f"• <b>Попыток</b> - {updated_settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {updated_settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {updated_settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# КОЛИЧЕСТВО КНОПОК
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:buttons:-?\d+$"))
async def handle_buttons_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора количества кнопок.

    Формат callback_data: captcha:dialog:buttons:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_button_count_keyboard(chat_id)

    text = (
        "🔢 <b>Количество кнопок</b>\n\n"
        "Выберите количество вариантов ответа:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:buttons_val:-?\d+:\d+$"))
async def handle_buttons_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает количество кнопок.

    Формат callback_data: captcha:dialog:buttons_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])

    # Сохраняем
    await update_captcha_setting(session, chat_id, "button_count", value)
    await session.commit()

    await callback.answer(f"✅ Кнопок: {value}")

    # Возвращаемся в меню диалогов
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:buttons_input:-?\d+$"))
async def handle_buttons_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода количества кнопок.

    Формат callback_data: captcha:dialog:buttons_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    await state.update_data(chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_buttons_input)

    await callback.message.edit_text(
        "✏️ <b>Введите количество кнопок</b>\n\n"
        "Введите число от 2 до 12:",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_buttons_input)
async def handle_buttons_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ввод количества кнопок."""
    from aiogram.types import Message

    data = await state.get_data()
    chat_id = data.get("chat_id")

    try:
        value = int(message.text.strip())
        if value < 2 or value > 12:
            await message.answer("❌ Введите число от 2 до 12")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    await update_captcha_setting(session, chat_id, "button_count", value)
    await session.commit()
    await state.clear()

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ Кнопок: {value}\n\n"
        "💬 <b>Настройки диалогов</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# КОЛИЧЕСТВО ПОПЫТОК
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:attempts:-?\d+$"))
async def handle_attempts_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора количества попыток.

    Формат callback_data: captcha:dialog:attempts:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_attempts_keyboard(chat_id)

    text = (
        "🔄 <b>Количество попыток</b>\n\n"
        "Выберите максимальное количество попыток:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:attempts_val:-?\d+:\d+$"))
async def handle_attempts_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает количество попыток.

    Формат callback_data: captcha:dialog:attempts_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])

    await update_captcha_setting(session, chat_id, "max_attempts", value)
    await session.commit()

    await callback.answer(f"✅ Попыток: {value}")

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:attempts_input:-?\d+$"))
async def handle_attempts_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода количества попыток.

    Формат callback_data: captcha:dialog:attempts_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    await state.update_data(chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_attempts_input)

    await callback.message.edit_text(
        "✏️ <b>Введите количество попыток</b>\n\n"
        "Введите число от 1 до 10:",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_attempts_input)
async def handle_attempts_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ввод количества попыток."""
    from aiogram.types import Message

    data = await state.get_data()
    chat_id = data.get("chat_id")

    try:
        value = int(message.text.strip())
        if value < 1 or value > 10:
            await message.answer("❌ Введите число от 1 до 10")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    await update_captcha_setting(session, chat_id, "max_attempts", value)
    await session.commit()
    await state.clear()

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ Попыток: {value}\n\n"
        "💬 <b>Настройки диалогов</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# НАПОМИНАНИЕ
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder:-?\d+$"))
async def handle_reminder_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора времени напоминания.

    Формат callback_data: captcha:dialog:reminder:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_reminder_keyboard(chat_id)

    text = (
        "🔔 <b>Напоминание</b>\n\n"
        "Через сколько секунд отправить напоминание:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder_val:-?\d+:\d+$"))
async def handle_reminder_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает время напоминания.

    Формат callback_data: captcha:dialog:reminder_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])

    await update_captcha_setting(session, chat_id, "reminder_seconds", value)
    await session.commit()

    if value > 0:
        await callback.answer(f"✅ Напоминание: {value} сек")
    else:
        await callback.answer("✅ Напоминание выключено")

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder_input:-?\d+$"))
async def handle_reminder_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода времени напоминания.

    Формат callback_data: captcha:dialog:reminder_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    await state.update_data(chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_reminder_input)

    await callback.message.edit_text(
        "✏️ <b>Введите время напоминания</b>\n\n"
        "Введите число в секундах (0 = выключить):",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_reminder_input)
async def handle_reminder_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ввод времени напоминания."""
    from aiogram.types import Message

    data = await state.get_data()
    chat_id = data.get("chat_id")

    try:
        value = int(message.text.strip())
        if value < 0:
            await message.answer("❌ Значение не может быть отрицательным")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    await update_captcha_setting(session, chat_id, "reminder_seconds", value)
    await session.commit()
    await state.clear()

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    status = f"{value} сек" if value > 0 else "выключено"
    await message.answer(
        f"✅ Напоминание: {status}\n\n"
        "💬 <b>Настройки диалогов</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# КОЛИЧЕСТВО НАПОМИНАНИЙ
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder_count:-?\d+$"))
async def handle_reminder_count_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора количества напоминаний.

    Формат callback_data: captcha:dialog:reminder_count:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="1",
                callback_data=f"captcha:dialog:reminder_count_val:{chat_id}:1",
            ),
            InlineKeyboardButton(
                text="2",
                callback_data=f"captcha:dialog:reminder_count_val:{chat_id}:2",
            ),
            InlineKeyboardButton(
                text="3",
                callback_data=f"captcha:dialog:reminder_count_val:{chat_id}:3",
            ),
        ],
        [
            InlineKeyboardButton(
                text="5",
                callback_data=f"captcha:dialog:reminder_count_val:{chat_id}:5",
            ),
            InlineKeyboardButton(
                text="🔄 Безлимит",
                callback_data=f"captcha:dialog:reminder_count_val:{chat_id}:0",
            ),
        ],
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:dialog:reminder_count_input:{chat_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:dialog:{chat_id}",
        )],
    ])

    text = (
        "📢 <b>Количество напоминаний</b>\n\n"
        "Сколько раз напомнить о капче:\n"
        "0 = безлимит (до таймаута)"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder_count_val:-?\d+:\d+$"))
async def handle_reminder_count_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает количество напоминаний.

    Формат callback_data: captcha:dialog:reminder_count_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])

    await update_captcha_setting(session, chat_id, "reminder_count", value)
    await session.commit()

    if value > 0:
        await callback.answer(f"✅ Напоминаний: {value}")
    else:
        await callback.answer("✅ Напоминания: безлимит")

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    reminder_count_display = settings.reminder_count if settings.reminder_count > 0 else "безлимит"
    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Кол-во напоминаний</b> - {reminder_count_display}\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:reminder_count_input:-?\d+$"))
async def handle_reminder_count_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода количества напоминаний.

    Формат callback_data: captcha:dialog:reminder_count_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    await state.update_data(chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_reminder_count_input)

    await callback.message.edit_text(
        "📢 <b>Количество напоминаний</b>\n\n"
        "Введите число (0 = безлимит):",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_reminder_count_input, F.text)
async def handle_reminder_count_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ввод количества напоминаний."""
    try:
        value = int(message.text.strip())
        if value < 0:
            raise ValueError("Отрицательное значение")
    except ValueError:
        await message.answer(
            "❌ Введите число от 0 до 99\n"
            "(0 = безлимит)",
        )
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")

    await update_captcha_setting(session, chat_id, "reminder_count", value)
    await session.commit()
    await state.clear()

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    reminder_count_display = settings.reminder_count if settings.reminder_count > 0 else "безлимит"
    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Кол-во напоминаний</b> - {reminder_count_display}\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await message.answer(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# ЧИСТКА ДИАЛОГА
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:cleanup:-?\d+$"))
async def handle_cleanup_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора времени чистки диалога.

    Формат callback_data: captcha:dialog:cleanup:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    keyboard = build_cleanup_keyboard(chat_id)

    text = (
        "🧹 <b>Чистка диалога</b>\n\n"
        "Через сколько секунд удалить сообщения капчи:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:cleanup_val:-?\d+:\d+$"))
async def handle_cleanup_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает время чистки диалога.

    Формат callback_data: captcha:dialog:cleanup_val:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])

    await update_captcha_setting(session, chat_id, "dialog_cleanup_seconds", value)
    await session.commit()

    await callback.answer(f"✅ Чистка: {value} сек")

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    text = (
        "💬 <b>Настройки диалогов</b>\n\n"
        f"• <b>Ручной ввод</b> - {'включён' if settings.manual_input_enabled else 'выключен'}\n"
        f"• <b>Кнопок</b> - {settings.button_count}\n"
        f"• <b>Попыток</b> - {settings.max_attempts}\n"
        f"• <b>Напоминание</b> - {settings.reminder_seconds} сек\n"
        f"• <b>Чистка</b> - {settings.dialog_cleanup_seconds} сек"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:dialog:cleanup_input:-?\d+$"))
async def handle_cleanup_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода времени чистки.

    Формат callback_data: captcha:dialog:cleanup_input:{chat_id}
    """
    chat_id = int(callback.data.split(":")[-1])

    await state.update_data(chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_cleanup_input)

    await callback.message.edit_text(
        "✏️ <b>Введите время чистки</b>\n\n"
        "Введите число в секундах (мин. 30):",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_cleanup_input)
async def handle_cleanup_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ввод времени чистки."""
    from aiogram.types import Message

    data = await state.get_data()
    chat_id = data.get("chat_id")

    try:
        value = int(message.text.strip())
        if value < 30:
            await message.answer("❌ Минимальное значение: 30 секунд")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    await update_captcha_setting(session, chat_id, "dialog_cleanup_seconds", value)
    await session.commit()
    await state.clear()

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_dialog_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ Чистка: {value} сек\n\n"
        "💬 <b>Настройки диалогов</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════
# TTL СООБЩЕНИЙ КАПЧИ В ГРУППЕ
# ═══════════════════════════════════════════════════════════════════════════

@callbacks_router.callback_query(F.data.regexp(r"^captcha:msg_ttl:[\w_]+:-?\d+$"))
async def handle_msg_ttl_menu(callback: CallbackQuery) -> None:
    """
    Показывает меню выбора TTL сообщения капчи в группе.

    TTL определяет через сколько секунд автоматически удалить
    сообщение капчи из группы.

    Формат callback_data: captcha:msg_ttl:{mode}:{chat_id}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])

    keyboard = build_message_ttl_keyboard(chat_id, mode)

    mode_names = {
        "join_group": "Join Captcha",
        "invite_group": "Invite Captcha",
    }
    mode_name = mode_names.get(mode, mode)

    text = (
        f"🗑️ <b>TTL сообщения {mode_name}</b>\n\n"
        "Через сколько удалить сообщение капчи из группы:\n"
        "(после отправки капчи в группу)"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.callback_query(F.data.regexp(r"^captcha:msg_ttl_val:[\w_]+:-?\d+:\d+$"))
async def handle_msg_ttl_value(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Устанавливает TTL сообщения капчи в группе.

    Формат callback_data: captcha:msg_ttl_val:{mode}:{chat_id}:{value}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])
    value = int(parts[4])

    # Маппинг режимов на поля
    mode_to_field = {
        "join_group": "join_captcha_message_ttl",
        "invite_group": "invite_captcha_message_ttl",
    }

    field = mode_to_field.get(mode)
    if not field:
        await callback.answer("❌ Ошибка: неизвестный режим")
        return

    # Сохраняем значение
    await update_captcha_setting(session, chat_id, field, value)
    await session.commit()

    # Форматируем для отображения
    if value >= 60:
        display_value = f"{value // 60} мин"
    else:
        display_value = f"{value} сек"

    await callback.answer(f"✅ TTL установлен: {display_value}")

    # Возвращаемся в меню настроек
    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    text = (
        "⚙️ <b>Настройки капчи</b>\n\n"
        "Выберите режим для настройки:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@callbacks_router.callback_query(F.data.regexp(r"^captcha:msg_ttl_input:[\w_]+:-?\d+$"))
async def handle_msg_ttl_input_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Начинает процесс ручного ввода TTL сообщения.

    Формат callback_data: captcha:msg_ttl_input:{mode}:{chat_id}
    """
    parts = callback.data.split(":")
    mode = parts[2]
    chat_id = int(parts[3])

    await state.update_data(mode=mode, chat_id=chat_id)
    await state.set_state(DialogInputStates.waiting_msg_ttl_input)

    mode_names = {
        "join_group": "Join Captcha",
        "invite_group": "Invite Captcha",
    }
    mode_name = mode_names.get(mode, mode)

    await callback.message.edit_text(
        f"✏️ <b>TTL сообщения {mode_name}</b>\n\n"
        "Введите значение в секундах (мин. 30):\n"
        "Например: 300 = 5 минут",
        parse_mode="HTML",
    )
    await callback.answer()


@callbacks_router.message(DialogInputStates.waiting_msg_ttl_input)
async def handle_msg_ttl_input_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает ручной ввод TTL сообщения."""
    data = await state.get_data()
    mode = data.get("mode")
    chat_id = data.get("chat_id")

    try:
        value = int(message.text.strip())
        if value < 30:
            await message.answer("❌ Минимальное значение: 30 секунд")
            return
    except ValueError:
        await message.answer("❌ Введите число")
        return

    # Маппинг режимов на поля
    mode_to_field = {
        "join_group": "join_captcha_message_ttl",
        "invite_group": "invite_captcha_message_ttl",
    }

    field = mode_to_field.get(mode)
    if field:
        await update_captcha_setting(session, chat_id, field, value)
        await session.commit()

    await state.clear()

    # Форматируем для отображения
    if value >= 60:
        display_value = f"{value // 60} мин"
    else:
        display_value = f"{value} сек"

    settings = await get_captcha_settings(session, chat_id)
    keyboard = build_captcha_settings_keyboard(chat_id, settings)

    await message.answer(
        f"✅ TTL установлен: {display_value}\n\n"
        "⚙️ <b>Настройки капчи</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
