"""
Хендлеры для управления настройками антиспам.

Этот модуль содержит все обработчики callback-запросов для:
- Навигации по меню антиспам
- Настройки правил антиспам (действия, удаление сообщений, длительность)
- Управления белыми списками (добавление, удаление исключений)

ВАЖНО: Используем короткие callback_data из-за лимита Telegram в 64 байта!
Схема сокращений:
- as = antispam (главный префикс)
- m = main_menu, a = set_action, d = toggle_delete, t = duration
- tl = telegram_links, al = any_links
- fc/fg/fu/fb = forward_channel/group/user/bot
- qc/qg/qu/qb = quote_channel/group/user/bot
- wl = whitelist, wa = whitelist_add, wd = whitelist_delete
"""

# Импорт типов aiogram
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
# Импорт асинхронной сессии SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession
# Импорт select для запросов
from sqlalchemy import select
# Импорт логгера
import logging

# Импорт функций проверки прав
from bot.services.groups_settings_in_private_logic import (
    check_granular_permissions,
)

# Импорт сервиса антиспам
from bot.services.antispam import (
    get_rule_by_type,
    upsert_rule,
    list_whitelist_patterns,
    add_whitelist_pattern,
    remove_whitelist_pattern,
    get_whitelist_by_id,
)

# Импорт клавиатур антиспам
from bot.keyboards.antispam_keyboards import (
    create_antispam_main_menu,
    create_action_settings_keyboard,
    create_duration_keyboard,
    create_warning_ttl_keyboard,
    create_forward_sources_menu,
    create_quotes_sources_menu,
    create_whitelist_menu,
    create_delete_confirmation_keyboard,
    get_short_code_for_rule_type,
    get_rule_type_from_short_code,
    RULE_TYPE_TO_SHORT,
    SHORT_TO_RULE_TYPE,
)

# Импорт моделей антиспам
from bot.database.models_antispam import (
    RuleType,
    ActionType,
    WhitelistScope,
)

# Импорт модели настроек чата для TTL
from bot.database.models import ChatSettings

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаем роутер для хендлеров антиспам
antispam_router = Router()


# ============================================================
# FSM STATES ДЛЯ ДОБАВЛЕНИЯ В БЕЛЫЙ СПИСОК
# ============================================================

# Класс состояний FSM для процесса добавления в белый список
class WhitelistAddStates(StatesGroup):
    # Состояние ожидания ввода паттерна от пользователя
    waiting_for_pattern = State()


# Класс состояний FSM для удаления записи по номеру
class WhitelistDeleteStates(StatesGroup):
    # Состояние ожидания ввода номера записи для удаления
    waiting_for_number = State()


# Класс состояний FSM для ввода произвольной длительности
class CustomDurationStates(StatesGroup):
    # Состояние ожидания ввода длительности от пользователя
    waiting_for_duration = State()


# Класс состояний FSM для ввода произвольного TTL авто-удаления
class CustomTtlStates(StatesGroup):
    # Состояние ожидания ввода TTL от пользователя
    waiting_for_ttl = State()


# ============================================================
# МАППИНГ КОРОТКИХ КОДОВ НА ТИПЫ ПРАВИЛ
# ============================================================

# Маппинг источника пересылки (c/g/u/b) на короткий код правила
FORWARD_SOURCE_TO_SHORT = {
    "c": "fc",  # channel -> forward_channel
    "g": "fg",  # group -> forward_group
    "u": "fu",  # user -> forward_user
    "b": "fb",  # bot -> forward_bot
}

# Маппинг источника цитаты (c/g/u/b) на короткий код правила
QUOTE_SOURCE_TO_SHORT = {
    "c": "qc",  # channel -> quote_channel
    "g": "qg",  # group -> quote_group
    "u": "qu",  # user -> quote_user
    "b": "qb",  # bot -> quote_bot
}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_whitelist_scope_from_short_code(short_code: str) -> WhitelistScope:
    """
    Получить scope белого списка по короткому коду.

    Args:
        short_code: Короткий код правила (tl, al, fc, qc и т.д.)

    Returns:
        Соответствующий WhitelistScope
    """
    # Telegram ссылки
    if short_code == "tl":
        return WhitelistScope.TELEGRAM_LINK
    # Любые ссылки
    elif short_code == "al":
        return WhitelistScope.ANY_LINK
    # Пересылки (fc, fg, fu, fb)
    elif short_code.startswith("f"):
        return WhitelistScope.FORWARD
    # Цитаты (qc, qg, qu, qb)
    elif short_code.startswith("q"):
        return WhitelistScope.QUOTE
    # По умолчанию
    else:
        return WhitelistScope.ANY_LINK


def get_rule_display_name(rule_type: RuleType) -> str:
    """
    Получить отображаемое название для типа правила.

    Args:
        rule_type: Тип правила

    Returns:
        Читаемое название правила
    """
    # Словарь соответствия типов правил и названий
    names = {
        RuleType.TELEGRAM_LINK: "Telegram ссылки",
        RuleType.ANY_LINK: "Блок всех ссылок",
        RuleType.FORWARD_CHANNEL: "Пересылка из каналов",
        RuleType.FORWARD_GROUP: "Пересылка из групп",
        RuleType.FORWARD_USER: "Пересылка от пользователей",
        RuleType.FORWARD_BOT: "Пересылка от ботов",
        RuleType.QUOTE_CHANNEL: "Цитаты из каналов",
        RuleType.QUOTE_GROUP: "Цитаты из групп",
        RuleType.QUOTE_USER: "Цитаты от пользователей",
        RuleType.QUOTE_BOT: "Цитаты от ботов",
    }
    return names.get(rule_type, str(rule_type))


async def format_rule_status_message(
    session: AsyncSession,
    chat_id: int,
    rule_type: RuleType,
) -> str:
    """
    Сформировать текст сообщения с текущим статусом правила.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        rule_type: Тип правила

    Returns:
        Форматированный текст сообщения
    """
    # Получаем правило из БД
    rule = await get_rule_by_type(session, chat_id, rule_type)
    # Получаем читаемое название правила
    rule_name = get_rule_display_name(rule_type)

    # Если правило существует
    if rule:
        action = rule.action
        delete_msg = rule.delete_message
        duration = rule.restrict_minutes

        # Формируем текст действия
        if action == ActionType.OFF:
            action_text = "❌ Выключено"
        elif action == ActionType.WARN:
            action_text = "❗ Предупреждение"
        elif action == ActionType.KICK:
            action_text = "🚪 Исключить из группы"
        elif action == ActionType.RESTRICT:
            action_text = f"🔇 Ограничить на {duration or 30} мин"
        elif action == ActionType.BAN:
            action_text = "🚫 Заблокировать навсегда"
        else:
            action_text = "Неизвестно"

        delete_text = "✅ Да" if delete_msg else "❌ Нет"

        message = (
            f"🚫 <b>Антиспам: {rule_name}</b>\n\n"
            f"<b>Текущие настройки:</b>\n"
            f"• Действие: {action_text}\n"
            f"• Удалять сообщения: {delete_text}\n\n"
            f"Выберите действие для настройки:"
        )
    else:
        # Правило не найдено - используются настройки по умолчанию (OFF)
        message = (
            f"🚫 <b>Антиспам: {rule_name}</b>\n\n"
            f"<b>Текущие настройки:</b>\n"
            f"• Действие: ❌ Выключено (по умолчанию)\n"
            f"• Удалять сообщения: ❌ Нет\n\n"
            f"Выберите действие для настройки:"
        )

    return message


async def safe_edit_message(
    callback: types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup = None,
    parse_mode: str = "HTML",
) -> bool:
    """
    Безопасно редактировать сообщение с обработкой ошибки 'message is not modified'.

    Args:
        callback: Объект callback запроса
        text: Текст сообщения
        reply_markup: Клавиатура
        parse_mode: Режим парсинга

    Returns:
        True если сообщение было отредактировано, False если нет
    """
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except TelegramBadRequest as e:
        # Проверяем, является ли это ошибкой "message is not modified"
        if "message is not modified" in str(e):
            # Это не ошибка - просто сообщение не изменилось
            logger.debug(f"Message not modified (same content): {e}")
            return False
        else:
            # Другая ошибка - пробрасываем дальше
            raise


# ============================================================
# ХЕНДЛЕР: ГЛАВНОЕ МЕНЮ АНТИСПАМ (as:m:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:m:"))
async def antispam_main_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик открытия главного меню антиспам.
    Callback формат: as:m:{chat_id}
    """
    logger.info(f"[ANTISPAM] Opening main menu for user {callback.from_user.id}")
    logger.debug(f"[ANTISPAM] Callback data: {callback.data}")

    try:
        # Извлекаем chat_id из callback_data
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id
        logger.debug(f"[ANTISPAM] Parsed chat_id={chat_id}, user_id={user_id}")

        # Проверяем права администратора
        logger.debug(f"[ANTISPAM] Checking permissions for user {user_id} in chat {chat_id}")
        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            logger.warning(f"[ANTISPAM] Permission denied for user {user_id}")
            await callback.answer(
                "❌ Недостаточно прав! Нужно право 'Изменять информацию о группе'",
                show_alert=True
            )
            return

        logger.debug(f"[ANTISPAM] Permissions OK, fetching TTL for chat {chat_id}")

        # Получаем текущий TTL из настроек чата
        result = await session.execute(
            select(ChatSettings.antispam_warning_ttl_seconds)
            .where(ChatSettings.chat_id == chat_id)
        )
        warning_ttl = result.scalar_one_or_none() or 0
        logger.debug(f"[ANTISPAM] Got TTL={warning_ttl} for chat {chat_id}")

        # Создаем клавиатуру главного меню с текущим TTL
        keyboard = create_antispam_main_menu(chat_id, warning_ttl)
        logger.debug(f"[ANTISPAM] Keyboard created for chat {chat_id}")

        text = (
            "🚫 <b>Антиспам</b>\n\n"
            "В этом меню вы можете решить, защищать ли вашу группу от "
            "нежелательных ссылок, пересылок и цитат.\n\n"
            "Выберите раздел для настройки:"
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()
        logger.info(f"[ANTISPAM] Main menu displayed successfully for chat {chat_id}")

    except Exception as e:
        logger.error(f"[ANTISPAM] Error in main_menu_handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: МЕНЮ АВТО-УДАЛЕНИЯ УВЕДОМЛЕНИЙ (as:ttl:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:ttl:"))
async def antispam_ttl_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик открытия меню настройки TTL уведомлений.
    Callback формат: as:ttl:{chat_id}
    """
    logger.info(f"Opening TTL menu for user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Получаем текущий TTL
        result = await session.execute(
            select(ChatSettings.antispam_warning_ttl_seconds)
            .where(ChatSettings.chat_id == chat_id)
        )
        current_ttl = result.scalar_one_or_none() or 0

        keyboard = create_warning_ttl_keyboard(chat_id, current_ttl)

        text = (
            "⏱️ <b>Авто-удаление уведомлений</b>\n\n"
            "Через какое время удалять уведомления антиспам "
            "(предупреждения, сообщения о муте/кике/бане)?\n\n"
            "Выберите время или 'Не удалять' чтобы оставлять сообщения:"
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_ttl_menu_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: УСТАНОВКА TTL (as:sttl:{seconds}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:sttl:"))
async def antispam_set_ttl_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик установки TTL уведомлений.
    Callback формат: as:sttl:{seconds}:{chat_id}
    """
    logger.info(f"Setting TTL for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        ttl_seconds = int(parts[2])
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Проверяем существует ли запись ChatSettings
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == chat_id)
        )
        chat_settings = result.scalar_one_or_none()

        if chat_settings:
            # Обновляем существующую запись
            chat_settings.antispam_warning_ttl_seconds = ttl_seconds
        else:
            # Создаём новую запись
            chat_settings = ChatSettings(
                chat_id=chat_id,
                antispam_warning_ttl_seconds=ttl_seconds,
            )
            session.add(chat_settings)

        await session.commit()

        logger.info(f"Set warning TTL: chat_id={chat_id}, ttl={ttl_seconds}")

        # Формируем текст для ответа
        if ttl_seconds == 0:
            ttl_text = "Уведомления не удаляются"
        elif ttl_seconds < 60:
            ttl_text = f"{ttl_seconds} секунд"
        elif ttl_seconds < 3600:
            ttl_text = f"{ttl_seconds // 60} минут"
        elif ttl_seconds < 86400:
            ttl_text = f"{ttl_seconds // 3600} часов"
        else:
            ttl_text = f"{ttl_seconds // 86400} дней"

        await callback.answer(f"✅ {ttl_text}")

        # Возвращаемся к главному меню
        keyboard = create_antispam_main_menu(chat_id, ttl_seconds)

        text = (
            "🚫 <b>Антиспам</b>\n\n"
            "В этом меню вы можете решить, защищать ли вашу группу от "
            "нежелательных ссылок, пересылок и цитат.\n\n"
            "Выберите раздел для настройки:"
        )

        await safe_edit_message(callback, text, keyboard)

    except Exception as e:
        logger.error(f"Error in antispam_set_ttl_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ВВОД TTL ВРУЧНУЮ (as:cttl:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:cttl:"))
async def antispam_custom_ttl_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
):
    """
    Обработчик для ввода TTL вручную.
    Callback формат: as:cttl:{chat_id}
    """
    logger.info(f"[ANTISPAM] Custom TTL input requested by user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Сохраняем chat_id в состояние FSM
        await state.update_data(antispam_chat_id=chat_id)
        await state.set_state(CustomTtlStates.waiting_for_ttl)

        # Создаем клавиатуру с кнопкой отмены
        cancel_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Отмена", callback_data=f"as:ttl:{chat_id}")]
        ])

        text = (
            "⏱️ <b>Введите время авто-удаления</b>\n\n"
            "Введите время в формате:\n"
            "• <code>30</code> или <code>30с</code> - секунды\n"
            "• <code>5м</code> или <code>5мин</code> - минуты\n"
            "• <code>2ч</code> или <code>2час</code> - часы\n"
            "• <code>1д</code> или <code>1день</code> - дни\n\n"
            "Пример: <code>10м</code> = 10 минут"
        )

        await safe_edit_message(callback, text, cancel_keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"[ANTISPAM] Error in custom_ttl_handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@antispam_router.message(CustomTtlStates.waiting_for_ttl)
async def antispam_custom_ttl_input_handler(
    message: types.Message,
    session: AsyncSession,
    state: FSMContext,
):
    """
    Обработчик текстового ввода TTL.
    """
    logger.info(f"[ANTISPAM] Custom TTL input received: {message.text}")

    try:
        data = await state.get_data()
        chat_id = data.get("antispam_chat_id")

        if not chat_id:
            await message.answer("❌ Ошибка: не найден ID чата. Попробуйте снова.")
            await state.clear()
            return

        # Парсим введённое значение
        input_text = message.text.strip().lower()
        ttl_seconds = parse_duration_input(input_text)

        if ttl_seconds is None or ttl_seconds < 0:
            await message.answer(
                "❌ Неверный формат. Введите число с единицей измерения:\n"
                "• <code>30с</code> - секунды\n"
                "• <code>5м</code> - минуты\n"
                "• <code>2ч</code> - часы\n"
                "• <code>1д</code> - дни",
                parse_mode="HTML"
            )
            return

        # Ограничиваем максимальное значение (1 год)
        max_ttl = 365 * 24 * 3600
        if ttl_seconds > max_ttl:
            ttl_seconds = max_ttl

        # Сохраняем TTL в БД
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == chat_id)
        )
        chat_settings = result.scalar_one_or_none()

        if chat_settings:
            chat_settings.antispam_warning_ttl_seconds = ttl_seconds
        else:
            chat_settings = ChatSettings(
                chat_id=chat_id,
                antispam_warning_ttl_seconds=ttl_seconds,
            )
            session.add(chat_settings)

        await session.commit()
        await state.clear()

        logger.info(f"[ANTISPAM] Custom TTL set: chat_id={chat_id}, ttl={ttl_seconds}")

        # Формируем текст подтверждения
        ttl_text = format_ttl_display(ttl_seconds)

        # Создаем клавиатуру главного меню
        keyboard = create_antispam_main_menu(chat_id, ttl_seconds)

        text = (
            f"✅ Время авто-удаления установлено: <b>{ttl_text}</b>\n\n"
            "🚫 <b>Антиспам</b>\n\n"
            "В этом меню вы можете решить, защищать ли вашу группу от "
            "нежелательных ссылок, пересылок и цитат.\n\n"
            "Выберите раздел для настройки:"
        )

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.error(f"[ANTISPAM] Error in custom_ttl_input_handler: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка")
        await state.clear()


def parse_duration_input(text: str) -> int | None:
    """
    Парсит ввод длительности от пользователя.
    Поддерживает форматы: 30, 30с, 5м, 5мин, 2ч, 2час, 1д, 1день
    Возвращает количество секунд или None если формат неверный.
    """
    import re

    text = text.strip().lower()

    # Попытка распарсить как число (считаем секундами)
    if text.isdigit():
        return int(text)

    # Регулярки для разных единиц
    patterns = [
        (r'^(\d+)\s*с(?:ек(?:унд[аы]?)?)?$', 1),        # секунды
        (r'^(\d+)\s*м(?:ин(?:ут[аы]?)?)?$', 60),        # минуты
        (r'^(\d+)\s*ч(?:ас(?:а|ов)?)?$', 3600),         # часы
        (r'^(\d+)\s*д(?:н(?:ей|я)?|ень)?$', 86400),     # дни
    ]

    for pattern, multiplier in patterns:
        match = re.match(pattern, text)
        if match:
            return int(match.group(1)) * multiplier

    return None


def format_ttl_display(ttl_seconds: int) -> str:
    """Форматирует TTL для отображения пользователю."""
    if ttl_seconds == 0:
        return "Не удалять"
    elif ttl_seconds < 60:
        return f"{ttl_seconds} сек"
    elif ttl_seconds < 3600:
        mins = ttl_seconds // 60
        return f"{mins} мин"
    elif ttl_seconds < 86400:
        hours = ttl_seconds // 3600
        return f"{hours} ч"
    else:
        days = ttl_seconds // 86400
        return f"{days} дн"


# ============================================================
# ХЕНДЛЕР: TELEGRAM ССЫЛКИ (as:tl:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:tl:"))
async def antispam_telegram_links_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик раздела Telegram ссылок.
    Callback формат: as:tl:{chat_id}
    """
    logger.info(f"Opening Telegram links settings for user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        rule_type = RuleType.TELEGRAM_LINK
        short_code = "tl"

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            current_action = rule.action
            delete_message = rule.delete_message
            restrict_minutes = rule.restrict_minutes
        else:
            current_action = ActionType.OFF
            delete_message = False
            restrict_minutes = 30

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=current_action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_telegram_links_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПЕРЕСЫЛКА МЕНЮ (as:fwd:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:fwd:"))
async def antispam_forward_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик меню выбора источника пересылки.
    Callback формат: as:fwd:{chat_id}
    """
    logger.info(f"Opening forward sources menu for user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        keyboard = create_forward_sources_menu(chat_id)

        text = (
            "📨 <b>Пересылка</b>\n\n"
            "Выберите тип источника пересылки для настройки:\n\n"
            "• <b>Каналы</b> - пересылки из каналов\n"
            "• <b>Группы</b> - пересылки из других групп\n"
            "• <b>Пользователи</b> - пересылки от пользователей\n"
            "• <b>Боты</b> - пересылки от ботов"
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_forward_menu_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ВЫБОР ИСТОЧНИКА ПЕРЕСЫЛКИ (as:fs:{source}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:fs:"))
async def antispam_forward_source_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик выбора конкретного источника пересылки.
    Callback формат: as:fs:{source}:{chat_id}
    source: c=channel, g=group, u=user, b=bot
    """
    logger.info(f"Opening forward source settings for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        source = parts[2]  # c/g/u/b
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Получаем короткий код правила из источника
        short_code = FORWARD_SOURCE_TO_SHORT.get(source)
        if not short_code:
            await callback.answer("❌ Неизвестный источник", show_alert=True)
            return

        # Получаем тип правила из короткого кода
        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            current_action = rule.action
            delete_message = rule.delete_message
            restrict_minutes = rule.restrict_minutes
        else:
            current_action = ActionType.OFF
            delete_message = False
            restrict_minutes = 30

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=current_action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_forward_source_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ЦИТАТЫ МЕНЮ (as:qt:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:qt:"))
async def antispam_quotes_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик меню выбора источника цитаты.
    Callback формат: as:qt:{chat_id}
    """
    logger.info(f"Opening quotes sources menu for user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        keyboard = create_quotes_sources_menu(chat_id)

        text = (
            "💬 <b>Цитаты</b>\n\n"
            "Выберите тип источника цитаты для настройки:\n\n"
            "• <b>Каналы</b> - цитаты из каналов\n"
            "• <b>Группы</b> - цитаты из других групп\n"
            "• <b>Пользователи</b> - цитаты от пользователей\n"
            "• <b>Боты</b> - цитаты от ботов"
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_quotes_menu_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ВЫБОР ИСТОЧНИКА ЦИТАТЫ (as:qs:{source}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:qs:"))
async def antispam_quote_source_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик выбора конкретного источника цитаты.
    Callback формат: as:qs:{source}:{chat_id}
    source: c=channel, g=group, u=user, b=bot
    """
    logger.info(f"Opening quote source settings for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        source = parts[2]  # c/g/u/b
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Получаем короткий код правила из источника
        short_code = QUOTE_SOURCE_TO_SHORT.get(source)
        if not short_code:
            await callback.answer("❌ Неизвестный источник", show_alert=True)
            return

        # Получаем тип правила из короткого кода
        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            current_action = rule.action
            delete_message = rule.delete_message
            restrict_minutes = rule.restrict_minutes
        else:
            current_action = ActionType.OFF
            delete_message = False
            restrict_minutes = 30

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=current_action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_quote_source_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: БЛОК ВСЕХ ССЫЛОК (as:al:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:al:"))
async def antispam_any_links_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик раздела блокировки всех ссылок.
    Callback формат: as:al:{chat_id}
    """
    logger.info(f"Opening any links settings for user {callback.from_user.id}")

    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        rule_type = RuleType.ANY_LINK
        short_code = "al"

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            current_action = rule.action
            delete_message = rule.delete_message
            restrict_minutes = rule.restrict_minutes
        else:
            current_action = ActionType.OFF
            delete_message = False
            restrict_minutes = 30

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=current_action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_any_links_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: УСТАНОВКА ДЕЙСТВИЯ (as:a:{short_code}:{action}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:a:"))
async def antispam_set_action_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик установки действия для правила антиспам.
    Callback формат: as:a:{short_code}:{ACTION}:{chat_id}
    """
    logger.info(f"Setting antispam action for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        action_str = parts[3]
        chat_id = int(parts[4])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Преобразуем строку действия в enum
        action = ActionType[action_str]

        # Получаем тип правила из короткого кода
        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        # Получаем текущее правило
        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            delete_message = rule.delete_message
            restrict_minutes = rule.restrict_minutes or 30
        else:
            delete_message = False
            restrict_minutes = 30

        # Создаем или обновляем правило
        await upsert_rule(
            session=session,
            chat_id=chat_id,
            rule_type=rule_type,
            action=action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes if action == ActionType.RESTRICT else None,
        )

        await session.commit()

        logger.info(
            f"Updated antispam rule: chat_id={chat_id}, "
            f"rule_type={rule_type}, action={action}"
        )

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=action,
            delete_message=delete_message,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        edited = await safe_edit_message(callback, text, keyboard)

        if edited:
            await callback.answer("✅ Действие обновлено")
        else:
            await callback.answer("Действие уже установлено")

    except Exception as e:
        logger.error(f"Error in antispam_set_action_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПЕРЕКЛЮЧЕНИЕ УДАЛЕНИЯ (as:d:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:d:"))
async def antispam_toggle_delete_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик переключения флага удаления сообщений.
    Callback формат: as:d:{short_code}:{chat_id}
    """
    logger.info(f"Toggling delete message for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            new_delete_value = not rule.delete_message
            action = rule.action
            restrict_minutes = rule.restrict_minutes
        else:
            new_delete_value = True
            action = ActionType.OFF
            restrict_minutes = 30

        await upsert_rule(
            session=session,
            chat_id=chat_id,
            rule_type=rule_type,
            action=action,
            delete_message=new_delete_value,
            restrict_minutes=restrict_minutes,
        )

        await session.commit()

        logger.info(
            f"Toggled delete_message: chat_id={chat_id}, "
            f"rule_type={rule_type}, delete={new_delete_value}"
        )

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=action,
            delete_message=new_delete_value,
            restrict_minutes=restrict_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)

        if new_delete_value:
            await callback.answer("✅ Удаление сообщений включено")
        else:
            await callback.answer("❌ Удаление сообщений выключено")

    except Exception as e:
        logger.error(f"Error in antispam_toggle_delete_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: МЕНЮ ДЛИТЕЛЬНОСТИ (as:t:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:t:"))
async def antispam_duration_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик открытия меню выбора длительности ограничения.
    Callback формат: as:t:{short_code}:{chat_id}
    """
    logger.info(f"Opening duration menu for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule and rule.restrict_minutes:
            current_duration = rule.restrict_minutes
        else:
            current_duration = 30

        keyboard = create_duration_keyboard(
            chat_id=chat_id,
            short_code=short_code,
            current_duration=current_duration,
        )

        rule_name = get_rule_display_name(rule_type)
        text = (
            f"⏱️ <b>Длительность ограничения</b>\n\n"
            f"Правило: {rule_name}\n\n"
            f"Текущая длительность: <b>{current_duration} минут</b>\n\n"
            f"Выберите новую длительность:"
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_duration_menu_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: УСТАНОВКА ДЛИТЕЛЬНОСТИ (as:sd:{short_code}:{minutes}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:sd:"))
async def antispam_set_duration_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик установки длительности ограничения.
    Callback формат: as:sd:{short_code}:{minutes}:{chat_id}
    """
    logger.info(f"Setting duration for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        duration_minutes = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await callback.answer("❌ Неизвестный тип правила", show_alert=True)
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            action = rule.action
            delete_message = rule.delete_message
        else:
            action = ActionType.RESTRICT
            delete_message = False

        await upsert_rule(
            session=session,
            chat_id=chat_id,
            rule_type=rule_type,
            action=action,
            delete_message=delete_message,
            restrict_minutes=duration_minutes,
        )

        await session.commit()

        logger.info(
            f"Updated duration: chat_id={chat_id}, "
            f"rule_type={rule_type}, duration={duration_minutes}"
        )

        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=action,
            delete_message=delete_message,
            restrict_minutes=duration_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)
        await safe_edit_message(callback, text, keyboard)
        await callback.answer(f"✅ Длительность установлена: {duration_minutes} мин")

    except Exception as e:
        logger.error(f"Error in antispam_set_duration_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ВВОД ПРОИЗВОЛЬНОЙ ДЛИТЕЛЬНОСТИ (as:sdc:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:sdc:"))
async def antispam_custom_duration_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик начала процесса ввода произвольной длительности.
    Callback формат: as:sdc:{short_code}:{chat_id}
    """
    logger.info(f"Starting custom duration input for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Сохраняем данные в FSM
        await state.update_data(
            chat_id=chat_id,
            short_code=short_code,
            message_id=callback.message.message_id,
        )

        await state.set_state(CustomDurationStates.waiting_for_duration)

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        text = (
            f"⏱️ <b>Ввод длительности ограничения</b>\n\n"
            f"Правило: {rule_name}\n\n"
            f"Отправьте длительность в минутах (число).\n"
            f"Примеры:\n"
            f"• <code>5</code> — 5 минут\n"
            f"• <code>60</code> — 1 час\n"
            f"• <code>1440</code> — 1 день\n"
            f"• <code>10080</code> — 1 неделя\n\n"
            f"Отправьте /cancel для отмены."
        )

        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_custom_duration_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПОЛУЧЕНИЕ ПРОИЗВОЛЬНОЙ ДЛИТЕЛЬНОСТИ ОТ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@antispam_router.message(CustomDurationStates.waiting_for_duration)
async def antispam_custom_duration_received_handler(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик получения произвольной длительности от пользователя.
    """
    logger.info(f"Received custom duration from user {message.from_user.id}")

    try:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        short_code = data.get("short_code")
        instruction_message_id = data.get("message_id")

        # Проверяем команду отмены
        if message.text and message.text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Ввод длительности отменён")
            return

        # Парсим число
        try:
            duration_minutes = int(message.text.strip())
        except (ValueError, AttributeError):
            await message.answer(
                "❌ Введите число минут. Попробуйте еще раз или отправьте /cancel"
            )
            return

        # Валидируем значение
        if duration_minutes < 0:
            await message.answer(
                "❌ Длительность не может быть отрицательной. "
                "Попробуйте еще раз или отправьте /cancel"
            )
            return

        if duration_minutes > 525600:  # Больше года (365 * 24 * 60)
            await message.answer(
                "❌ Максимальная длительность — 525600 минут (1 год). "
                "Попробуйте еще раз или отправьте /cancel"
            )
            return

        rule_type = get_rule_type_from_short_code(short_code)
        if not rule_type:
            await message.answer("❌ Неизвестный тип правила")
            await state.clear()
            return

        rule = await get_rule_by_type(session, chat_id, rule_type)

        if rule:
            action = rule.action
            delete_message = rule.delete_message
        else:
            action = ActionType.RESTRICT
            delete_message = False

        await upsert_rule(
            session=session,
            chat_id=chat_id,
            rule_type=rule_type,
            action=action,
            delete_message=delete_message,
            restrict_minutes=duration_minutes,
        )

        await session.commit()

        logger.info(
            f"Set custom duration: chat_id={chat_id}, "
            f"rule_type={rule_type}, duration={duration_minutes}"
        )

        await state.clear()

        # Удаляем сообщение пользователя
        try:
            await message.delete()
        except Exception:
            pass

        # Формируем читаемую длительность
        if duration_minutes == 0:
            duration_text = "Навсегда"
        elif duration_minutes < 60:
            duration_text = f"{duration_minutes} мин"
        elif duration_minutes < 1440:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            duration_text = f"{hours} ч" + (f" {mins} мин" if mins else "")
        else:
            days = duration_minutes // 1440
            hours = (duration_minutes % 1440) // 60
            duration_text = f"{days} дн" + (f" {hours} ч" if hours else "")

        success_msg = await message.answer(
            f"✅ Длительность установлена: {duration_text}",
            parse_mode="HTML"
        )

        # Возвращаемся к меню настройки правила
        keyboard = create_action_settings_keyboard(
            chat_id=chat_id,
            rule_type=rule_type,
            current_action=action,
            delete_message=delete_message,
            restrict_minutes=duration_minutes,
            short_code=short_code,
        )

        text = await format_rule_status_message(session, chat_id, rule_type)

        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to edit instruction message: {e}")

        # Удаляем уведомление об успехе через 3 секунды
        import asyncio
        await asyncio.sleep(3)
        try:
            await success_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in antispam_custom_duration_received_handler: {e}")
        await message.answer("❌ Произошла ошибка при установке длительности")
        await state.clear()


# ============================================================
# ХЕНДЛЕР: МЕНЮ ИСКЛЮЧЕНИЙ (as:wl:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:wl:"))
async def antispam_whitelist_menu_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик открытия меню управления исключениями (белым списком).
    Callback формат: as:wl:{short_code}:{chat_id}

    ИЗМЕНЕНО: Записи показываются как текстовый список, не кнопки.
    Для удаления - кнопка "Удалить по номеру" с FSM.
    """
    logger.info(f"Opening whitelist menu for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        scope = get_whitelist_scope_from_short_code(short_code)

        whitelist_entries_raw = await list_whitelist_patterns(
            session=session,
            chat_id=chat_id,
            scope=scope,
        )

        # Преобразуем в формат: list of (id, pattern)
        whitelist_entries = [
            (entry.id, entry.pattern)
            for entry in whitelist_entries_raw
        ]

        # Создаём клавиатуру - передаём только количество записей
        keyboard = create_whitelist_menu(
            chat_id=chat_id,
            short_code=short_code,
            entries_count=len(whitelist_entries),
        )

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        if whitelist_entries:
            # Формируем текстовый список записей
            entries_text = "\n".join([
                f"<b>{i+1}.</b> <code>{pattern}</code>"
                for i, (entry_id, pattern) in enumerate(whitelist_entries)
            ])
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Найдено записей: <b>{len(whitelist_entries)}</b>\n\n"
                f"Эти паттерны <b>не будут</b> считаться спамом:\n\n"
                f"{entries_text}"
            )
        else:
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Белый список пуст.\n\n"
                f"Вы можете добавить исключения, которые не будут "
                f"считаться спамом."
            )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_menu_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ДОБАВЛЕНИЕ В БЕЛЫЙ СПИСОК (as:wa:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:wa:"))
async def antispam_whitelist_add_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик начала процесса добавления паттерна в белый список.
    Callback формат: as:wa:{short_code}:{chat_id}
    """
    logger.info(f"Starting whitelist add for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        # Сохраняем данные в FSM
        await state.update_data(
            chat_id=chat_id,
            short_code=short_code,
            message_id=callback.message.message_id,
        )

        await state.set_state(WhitelistAddStates.waiting_for_pattern)

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        # Определяем что нужно ввести в зависимости от типа правила
        if short_code in ("tl", "al"):
            input_hint = (
                "часть URL или домен\n"
                "Примеры: <code>t.me/mygroup</code>, <code>youtube.com</code>"
            )
        else:
            input_hint = (
                "ID канала/группы или юзернейм\n"
                "Примеры: <code>-1001234567890</code>, <code>@mychannel</code>"
            )

        text = (
            f"➕ <b>Добавление исключения</b>\n\n"
            f"Правило: {rule_name}\n\n"
            f"Отправьте {input_hint}\n\n"
            f"Отправьте /cancel для отмены."
        )

        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_add_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПОЛУЧЕНИЕ ПАТТЕРНА ОТ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@antispam_router.message(WhitelistAddStates.waiting_for_pattern)
async def antispam_whitelist_pattern_received_handler(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик получения паттерна для добавления в белый список.
    """
    logger.info(f"Received whitelist pattern from user {message.from_user.id}")

    try:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        short_code = data.get("short_code")
        instruction_message_id = data.get("message_id")

        # Проверяем команду отмены
        if message.text and message.text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Добавление отменено")
            return

        pattern = message.text.strip() if message.text else ""

        if not pattern:
            await message.answer(
                "❌ Паттерн не может быть пустым. Попробуйте еще раз или отправьте /cancel"
            )
            return

        if len(pattern) > 200:
            await message.answer(
                "❌ Паттерн слишком длинный (макс 200 символов). "
                "Попробуйте еще раз или отправьте /cancel"
            )
            return

        scope = get_whitelist_scope_from_short_code(short_code)

        await add_whitelist_pattern(
            session=session,
            chat_id=chat_id,
            scope=scope,
            pattern=pattern,
            added_by=message.from_user.id,
        )

        await session.commit()

        logger.info(
            f"Added whitelist pattern: chat_id={chat_id}, "
            f"scope={scope}, pattern={pattern}"
        )

        await state.clear()

        # Удаляем сообщение пользователя
        try:
            await message.delete()
        except Exception:
            pass

        success_msg = await message.answer(
            f"✅ Паттерн добавлен в белый список:\n<code>{pattern}</code>",
            parse_mode="HTML"
        )

        # Возвращаемся к меню исключений
        whitelist_entries_raw = await list_whitelist_patterns(
            session=session,
            chat_id=chat_id,
            scope=scope,
        )

        whitelist_entries = [
            (entry.id, entry.pattern)
            for entry in whitelist_entries_raw
        ]

        # Создаём клавиатуру - передаём только количество записей
        keyboard = create_whitelist_menu(
            chat_id=chat_id,
            short_code=short_code,
            entries_count=len(whitelist_entries),
        )

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        # Формируем текстовый список записей
        entries_text = "\n".join([
            f"<b>{i+1}.</b> <code>{pattern}</code>"
            for i, (entry_id, pattern) in enumerate(whitelist_entries)
        ])
        text = (
            f"⭐ <b>Исключения: {rule_name}</b>\n\n"
            f"Найдено записей: <b>{len(whitelist_entries)}</b>\n\n"
            f"Эти паттерны <b>не будут</b> считаться спамом:\n\n"
            f"{entries_text}"
        )

        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to edit instruction message: {e}")

        # Удаляем уведомление об успехе через 3 секунды
        import asyncio
        await asyncio.sleep(3)
        try:
            await success_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_pattern_received_handler: {e}")
        await message.answer("❌ Произошла ошибка при добавлении паттерна")
        await state.clear()


# ============================================================
# ХЕНДЛЕР: УДАЛЕНИЕ ИЗ БЕЛОГО СПИСКА (as:wd:{short_code}:{entry_id}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:wd:"))
async def antispam_whitelist_delete_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик запроса на удаление записи из белого списка.
    Callback формат: as:wd:{short_code}:{entry_id}:{chat_id}
    """
    logger.info(f"Whitelist delete requested by user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        entry_id = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        entry = await get_whitelist_by_id(session, entry_id)

        if not entry:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        keyboard = create_delete_confirmation_keyboard(
            chat_id=chat_id,
            short_code=short_code,
            whitelist_id=entry_id,
        )

        text = (
            f"🗑️ <b>Удаление исключения</b>\n\n"
            f"Вы уверены что хотите удалить паттерн:\n"
            f"<code>{entry.pattern}</code>\n\n"
            f"После удаления этот паттерн будет считаться спамом."
        )

        await safe_edit_message(callback, text, keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_delete_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ (as:wdc:{short_code}:{entry_id}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:wdc:"))
async def antispam_whitelist_delete_confirm_handler(
    callback: types.CallbackQuery,
    session: AsyncSession,
):
    """
    Обработчик подтверждения удаления записи из белого списка.
    Callback формат: as:wdc:{short_code}:{entry_id}:{chat_id}
    """
    logger.info(f"Whitelist delete confirmed by user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        entry_id = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        success = await remove_whitelist_pattern(
            session=session,
            chat_id=chat_id,
            whitelist_id=entry_id,
        )

        if not success:
            await callback.answer("❌ Не удалось удалить запись", show_alert=True)
            return

        await session.commit()

        logger.info(
            f"Deleted whitelist entry: chat_id={chat_id}, "
            f"entry_id={entry_id}"
        )

        await callback.answer("✅ Паттерн удален из белого списка")

        # Возвращаемся к меню исключений
        scope = get_whitelist_scope_from_short_code(short_code)

        whitelist_entries_raw = await list_whitelist_patterns(
            session=session,
            chat_id=chat_id,
            scope=scope,
        )

        whitelist_entries = [
            (entry.id, entry.pattern)
            for entry in whitelist_entries_raw
        ]

        # Создаём клавиатуру - передаём только количество записей
        keyboard = create_whitelist_menu(
            chat_id=chat_id,
            short_code=short_code,
            entries_count=len(whitelist_entries),
        )

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        if whitelist_entries:
            # Формируем текстовый список записей
            entries_text = "\n".join([
                f"<b>{i+1}.</b> <code>{pattern}</code>"
                for i, (entry_id, pattern) in enumerate(whitelist_entries)
            ])
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Найдено записей: <b>{len(whitelist_entries)}</b>\n\n"
                f"Эти паттерны <b>не будут</b> считаться спамом:\n\n"
                f"{entries_text}"
            )
        else:
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Белый список пуст.\n\n"
                f"Вы можете добавить исключения, которые не будут "
                f"считаться спамом."
            )

        await safe_edit_message(callback, text, keyboard)

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_delete_confirm_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: УДАЛЕНИЕ ПО НОМЕРУ - НАЧАЛО (as:wdn:{short_code}:{chat_id})
# ============================================================

@antispam_router.callback_query(F.data.startswith("as:wdn:"))
async def antispam_whitelist_delete_by_number_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик начала процесса удаления записи по номеру.
    Callback формат: as:wdn:{short_code}:{chat_id}
    """
    logger.info(f"Starting whitelist delete by number for user {callback.from_user.id}")

    try:
        parts = callback.data.split(":")
        short_code = parts[2]
        chat_id = int(parts[3])
        user_id = callback.from_user.id

        if not await check_granular_permissions(
            callback.bot, user_id, chat_id, "change_info", session
        ):
            await callback.answer("❌ Недостаточно прав!", show_alert=True)
            return

        scope = get_whitelist_scope_from_short_code(short_code)

        # Получаем записи для показа
        whitelist_entries_raw = await list_whitelist_patterns(
            session=session,
            chat_id=chat_id,
            scope=scope,
        )

        if not whitelist_entries_raw:
            await callback.answer("❌ Белый список пуст", show_alert=True)
            return

        whitelist_entries = [
            (entry.id, entry.pattern)
            for entry in whitelist_entries_raw
        ]

        # Сохраняем данные в FSM для последующего использования
        await state.update_data(
            chat_id=chat_id,
            short_code=short_code,
            message_id=callback.message.message_id,
            # Сохраняем список entry_id для валидации номера
            entry_ids=[entry_id for entry_id, _ in whitelist_entries],
        )

        await state.set_state(WhitelistDeleteStates.waiting_for_number)

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        # Формируем текстовый список записей с номерами
        entries_text = "\n".join([
            f"<b>{i+1}.</b> <code>{pattern}</code>"
            for i, (entry_id, pattern) in enumerate(whitelist_entries)
        ])

        text = (
            f"🗑️ <b>Удаление исключения</b>\n\n"
            f"Правило: {rule_name}\n\n"
            f"Текущие записи:\n{entries_text}\n\n"
            f"Отправьте <b>номер</b> записи для удаления (1-{len(whitelist_entries)}).\n\n"
            f"Отправьте /cancel для отмены."
        )

        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_delete_by_number_handler: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПОЛУЧЕНИЕ НОМЕРА ДЛЯ УДАЛЕНИЯ
# ============================================================

@antispam_router.message(WhitelistDeleteStates.waiting_for_number)
async def antispam_whitelist_number_received_handler(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Обработчик получения номера записи для удаления из белого списка.
    """
    logger.info(f"Received whitelist delete number from user {message.from_user.id}")

    try:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        short_code = data.get("short_code")
        instruction_message_id = data.get("message_id")
        entry_ids = data.get("entry_ids", [])

        # Проверяем команду отмены
        if message.text and message.text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Удаление отменено")
            return

        # Парсим номер
        try:
            number = int(message.text.strip())
        except (ValueError, AttributeError):
            await message.answer(
                "❌ Введите число. Попробуйте еще раз или отправьте /cancel"
            )
            return

        # Валидируем номер
        if number < 1 or number > len(entry_ids):
            await message.answer(
                f"❌ Номер должен быть от 1 до {len(entry_ids)}. "
                f"Попробуйте еще раз или отправьте /cancel"
            )
            return

        # Получаем entry_id по номеру (номер с 1, индекс с 0)
        entry_id = entry_ids[number - 1]

        # Получаем запись для показа в подтверждении
        entry = await get_whitelist_by_id(session, entry_id)

        if not entry:
            await message.answer("❌ Запись не найдена")
            await state.clear()
            return

        # Удаляем запись
        success = await remove_whitelist_pattern(
            session=session,
            chat_id=chat_id,
            whitelist_id=entry_id,
        )

        if not success:
            await message.answer("❌ Не удалось удалить запись")
            await state.clear()
            return

        await session.commit()

        logger.info(
            f"Deleted whitelist entry by number: chat_id={chat_id}, "
            f"entry_id={entry_id}, number={number}"
        )

        await state.clear()

        # Удаляем сообщение пользователя с номером
        try:
            await message.delete()
        except Exception:
            pass

        success_msg = await message.answer(
            f"✅ Удалено исключение #{number}:\n<code>{entry.pattern}</code>",
            parse_mode="HTML"
        )

        # Возвращаемся к меню исключений
        scope = get_whitelist_scope_from_short_code(short_code)

        whitelist_entries_raw = await list_whitelist_patterns(
            session=session,
            chat_id=chat_id,
            scope=scope,
        )

        whitelist_entries = [
            (entry.id, entry.pattern)
            for entry in whitelist_entries_raw
        ]

        keyboard = create_whitelist_menu(
            chat_id=chat_id,
            short_code=short_code,
            entries_count=len(whitelist_entries),
        )

        rule_type = get_rule_type_from_short_code(short_code)
        rule_name = get_rule_display_name(rule_type) if rule_type else "Неизвестно"

        if whitelist_entries:
            entries_text = "\n".join([
                f"<b>{i+1}.</b> <code>{pattern}</code>"
                for i, (entry_id, pattern) in enumerate(whitelist_entries)
            ])
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Найдено записей: <b>{len(whitelist_entries)}</b>\n\n"
                f"Эти паттерны <b>не будут</b> считаться спамом:\n\n"
                f"{entries_text}"
            )
        else:
            text = (
                f"⭐ <b>Исключения: {rule_name}</b>\n\n"
                f"Белый список пуст.\n\n"
                f"Вы можете добавить исключения, которые не будут "
                f"считаться спамом."
            )

        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=instruction_message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to edit instruction message: {e}")

        # Удаляем уведомление об успехе через 3 секунды
        import asyncio
        await asyncio.sleep(3)
        try:
            await success_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in antispam_whitelist_number_received_handler: {e}")
        await message.answer("❌ Произошла ошибка при удалении")
        await state.clear()
