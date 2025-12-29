# bot/handlers/captcha/captcha_keyboards.py
"""
Клавиатуры для капчи - кнопки ответов и настроек.

Содержит:
- Клавиатуры для прохождения капчи (варианты ответов)
- Клавиатуры настроек капчи для админов
- Вспомогательные функции построения callback_data
"""

import logging
from typing import List, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.services.captcha import (
    CaptchaSettings,
    CaptchaMode,
)


# Логгер для отслеживания создания клавиатур
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ CALLBACK_DATA
# Формат: captcha:{action}:{owner_id}:{chat_id}:{extra}
# owner_id включён для проверки принадлежности капчи
# ═══════════════════════════════════════════════════════════════════════════

# Действия с капчей
CALLBACK_VERIFY = "captcha:verify:{owner_id}:{chat_id}:{answer_hash}"
CALLBACK_REFRESH = "captcha:refresh:{owner_id}:{chat_id}"
CALLBACK_CANCEL = "captcha:cancel:{owner_id}:{chat_id}"

# Настройки (для админов)
CALLBACK_SETTINGS_MENU = "captcha:settings:{chat_id}"
CALLBACK_TOGGLE_MODE = "captcha:toggle:{mode}:{chat_id}"
CALLBACK_SET_TIMEOUT = "captcha:timeout:{mode}:{chat_id}"
CALLBACK_SET_LIMIT = "captcha:limit:{chat_id}"
CALLBACK_SET_OVERFLOW = "captcha:overflow:{chat_id}"
CALLBACK_TIMEOUT_VALUE = "captcha:timeout_val:{mode}:{chat_id}:{value}"
CALLBACK_LIMIT_VALUE = "captcha:limit_val:{chat_id}:{value}"
CALLBACK_OVERFLOW_VALUE = "captcha:overflow_val:{chat_id}:{value}"
CALLBACK_BACK = "captcha:back:{chat_id}"


def build_captcha_verify_keyboard(
    owner_id: int,
    chat_id: int,
    options: List[dict],
    buttons_per_row: int = 2,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с вариантами ответов на капчу.

    Кнопки располагаются по buttons_per_row в ряд (по умолчанию 2).
    Каждая кнопка содержит owner_id для проверки принадлежности.

    Args:
        owner_id: ID пользователя которому принадлежит капча
        chat_id: ID группы для которой капча
        options: Список вариантов [{text, hash, is_correct}]
        buttons_per_row: Количество кнопок в ряду (по умолчанию 2)

    Returns:
        InlineKeyboardMarkup с кнопками вариантов

    Пример результата (6 кнопок, 2 в ряд):
        ┌─────────────────────────────────┐
        │  [ 42 ]        [ 17 ]          │  ← ряд 1
        │  [ 85 ]        [ 63 ]          │  ← ряд 2
        │  [ 29 ]        [ 91 ]          │  ← ряд 3
        └─────────────────────────────────┘
    """
    # Создаём кнопки с группировкой по рядам
    buttons = []
    # Текущий ряд кнопок
    current_row = []

    for option in options:
        # Формируем callback_data с защитой владельца
        # Формат: captcha:verify:{owner_id}:{chat_id}:{answer_hash}
        callback_data = f"captcha:verify:{owner_id}:{chat_id}:{option['hash']}"

        # Добавляем кнопку в текущий ряд
        current_row.append(
            InlineKeyboardButton(
                text=option["text"],
                callback_data=callback_data,
            )
        )

        # Если ряд заполнен - добавляем в список и начинаем новый
        if len(current_row) == buttons_per_row:
            buttons.append(current_row)
            current_row = []

    # Добавляем оставшиеся кнопки (неполный ряд)
    if current_row:
        buttons.append(current_row)

    # Логируем создание клавиатуры
    logger.debug(
        f"🎹 [KEYBOARD] Создана клавиатура капчи: "
        f"owner_id={owner_id}, chat_id={chat_id}, "
        f"options={len(options)}, rows={len(buttons)}"
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_captcha_settings_keyboard(
    chat_id: int,
    settings: CaptchaSettings,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру настроек капчи для админа.

    Показывает текущее состояние каждого режима и позволяет
    включать/выключать и настраивать параметры.

    Args:
        chat_id: ID группы
        settings: Текущие настройки капчи

    Returns:
        InlineKeyboardMarkup с кнопками настроек
    """
    # Иконки состояния
    def get_status_icon(enabled: Optional[bool]) -> str:
        """Возвращает иконку состояния"""
        if enabled is True:
            return "✅"
        elif enabled is False:
            return "❌"
        else:
            # None = не настроено
            return "⚙️"

    # Форматирование таймаута
    def format_timeout(seconds: Optional[int]) -> str:
        """Форматирует таймаут для отображения"""
        if seconds is None:
            return "не задан"
        elif seconds >= 60:
            return f"{seconds // 60} мин"
        else:
            return f"{seconds} сек"

    # Форматирование TTL сообщений
    def format_ttl(seconds: int) -> str:
        """Форматирует TTL для отображения"""
        if seconds >= 60:
            return f"{seconds // 60} мин"
        else:
            return f"{seconds} сек"

    # ═══════════════════════════════════════════════════════════════════════
    # Кнопки режимов
    # ═══════════════════════════════════════════════════════════════════════

    # Visual Captcha (ЛС)
    visual_icon = get_status_icon(settings.visual_captcha_enabled)
    visual_timeout = format_timeout(settings.visual_captcha_timeout)
    visual_text = f"{visual_icon} Visual Captcha (ЛС) [{visual_timeout}]"

    # Join Captcha (группа, самовход)
    join_icon = get_status_icon(settings.join_captcha_enabled)
    join_timeout = format_timeout(settings.join_captcha_timeout)
    join_text = f"{join_icon} Join Captcha [{join_timeout}]"

    # TTL сообщения Join Captcha в группе
    join_ttl = format_ttl(settings.join_captcha_message_ttl)
    join_ttl_text = f"   🗑️ Удалить через: {join_ttl}"

    # Invite Captcha (группа, инвайт)
    invite_icon = get_status_icon(settings.invite_captcha_enabled)
    invite_timeout = format_timeout(settings.invite_captcha_timeout)
    invite_text = f"{invite_icon} Invite Captcha [{invite_timeout}]"

    # TTL сообщения Invite Captcha в группе
    invite_ttl = format_ttl(settings.invite_captcha_message_ttl)
    invite_ttl_text = f"   🗑️ Удалить через: {invite_ttl}"

    # ═══════════════════════════════════════════════════════════════════════
    # Кнопки лимитов
    # ═══════════════════════════════════════════════════════════════════════

    # Лимит капч
    limit_text = settings.max_pending or "не задан"
    limit_btn_text = f"📊 Макс. капч: {limit_text}"

    # Действие при переполнении
    overflow_map = {
        "remove_oldest": "удалять старые",
        "auto_decline": "отклонять новые",
        "queue": "очередь",
        None: "не задано",
    }
    overflow_text = overflow_map.get(settings.overflow_action, "не задано")
    overflow_btn_text = f"⚡ При переполнении: {overflow_text}"

    # Действие при провале капчи (decline/keep)
    failure_action_map = {
        "decline": "Отклонить",
        "keep": "Оставить",
    }
    failure_action_text = failure_action_map.get(settings.failure_action, "Оставить")

    # ═══════════════════════════════════════════════════════════════════════
    # Собираем клавиатуру
    # ═══════════════════════════════════════════════════════════════════════

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Режимы капчи
        [InlineKeyboardButton(
            text=visual_text,
            callback_data=f"captcha:toggle:visual_dm:{chat_id}",
        )],

        # Join Captcha + TTL
        [InlineKeyboardButton(
            text=join_text,
            callback_data=f"captcha:toggle:join_group:{chat_id}",
        )],
        [InlineKeyboardButton(
            text=join_ttl_text,
            callback_data=f"captcha:msg_ttl:join_group:{chat_id}",
        )],

        # Invite Captcha + TTL
        [InlineKeyboardButton(
            text=invite_text,
            callback_data=f"captcha:toggle:invite_group:{chat_id}",
        )],
        [InlineKeyboardButton(
            text=invite_ttl_text,
            callback_data=f"captcha:msg_ttl:invite_group:{chat_id}",
        )],

        # Разделитель (пустая строка)
        [InlineKeyboardButton(
            text="─────────────────",
            callback_data="captcha:noop",
        )],

        # Лимиты
        [InlineKeyboardButton(
            text=limit_btn_text,
            callback_data=f"captcha:limit:{chat_id}",
        )],
        [InlineKeyboardButton(
            text=overflow_btn_text,
            callback_data=f"captcha:overflow:{chat_id}",
        )],

        # Действие при провале капчи (decline/keep)
        [InlineKeyboardButton(
            text=f"🚫 При провале: {failure_action_text}",
            callback_data=f"captcha_cycle:failure_action:{chat_id}",
        )],

        # Разделитель
        [InlineKeyboardButton(
            text="─────────────────",
            callback_data="captcha:noop",
        )],

        # Настройки диалогов (НОВЫЙ раздел)
        [InlineKeyboardButton(
            text="💬 Настройки диалогов",
            callback_data=f"captcha:dialog:{chat_id}",
        )],

        # Назад в меню группы
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"manage_group_{chat_id}",
        )],
    ])

    return keyboard


def build_timeout_input_keyboard(
    chat_id: int,
    mode: str,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора таймаута капчи.

    Предлагает готовые значения + возможность ввода вручную.

    Args:
        chat_id: ID группы
        mode: Режим капчи (visual_dm, join_group, invite_group)

    Returns:
        InlineKeyboardMarkup с кнопками выбора таймаута
    """
    # Готовые значения таймаута (секунды)
    presets = [
        (30, "30 сек"),
        (60, "1 мин"),
        (120, "2 мин"),
        (300, "5 мин"),
        (600, "10 мин"),
    ]

    # Создаём кнопки с готовыми значениями (по 2 в ряд)
    buttons = []
    row = []

    for value, label in presets:
        callback = f"captcha:timeout_val:{mode}:{chat_id}:{value}"
        row.append(InlineKeyboardButton(text=label, callback_data=callback))

        # По 2 кнопки в ряду
        if len(row) == 2:
            buttons.append(row)
            row = []

    # Добавляем оставшиеся кнопки
    if row:
        buttons.append(row)

    # Кнопка ручного ввода
    buttons.append([
        InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:timeout_input:{mode}:{chat_id}",
        )
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:settings:{chat_id}",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_limit_input_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора лимита капч.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора лимита
    """
    # Готовые значения лимита
    presets = [5, 10, 20, 50, 100]

    # Создаём кнопки (по 3 в ряд)
    buttons = []
    row = []

    for value in presets:
        callback = f"captcha:limit_val:{chat_id}:{value}"
        row.append(InlineKeyboardButton(text=str(value), callback_data=callback))

        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Кнопка ручного ввода
    buttons.append([
        InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:limit_input:{chat_id}",
        )
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:settings:{chat_id}",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_overflow_action_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора действия при переполнении.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора действия
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗑️ Удалять старые капчи",
            callback_data=f"captcha:overflow_val:{chat_id}:remove_oldest",
        )],
        [InlineKeyboardButton(
            text="❌ Отклонять новые запросы",
            callback_data=f"captcha:overflow_val:{chat_id}:auto_decline",
        )],
        [InlineKeyboardButton(
            text="📋 Ставить в очередь",
            callback_data=f"captcha:overflow_val:{chat_id}:queue",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:settings:{chat_id}",
        )],
    ])


def build_mode_settings_keyboard(
    chat_id: int,
    mode: str,
    is_enabled: bool,
    timeout: Optional[int],
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру настроек конкретного режима капчи.

    Args:
        chat_id: ID группы
        mode: Режим капчи
        is_enabled: Включён ли режим
        timeout: Текущий таймаут

    Returns:
        InlineKeyboardMarkup с кнопками настроек режима
    """
    # Текст кнопки включения/выключения
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"

    # Форматирование таймаута
    timeout_text = f"{timeout} сек" if timeout else "не задан"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"captcha:toggle:{mode}:{chat_id}",
        )],
        [InlineKeyboardButton(
            text=f"⏱ Таймаут: {timeout_text}",
            callback_data=f"captcha:timeout:{mode}:{chat_id}",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам капчи",
            callback_data=f"captcha:settings:{chat_id}",
        )],
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ НАСТРОЕК ДИАЛОГОВ
# ═══════════════════════════════════════════════════════════════════════════════

def build_dialog_settings_keyboard(
    chat_id: int,
    settings: CaptchaSettings,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру настроек диалогов капчи.

    Показывает текущие значения настроек и позволяет их изменить.

    Args:
        chat_id: ID группы
        settings: Текущие настройки капчи

    Returns:
        InlineKeyboardMarkup с кнопками настроек диалогов
    """
    # Форматируем текущие значения

    # Ручной ввод: включён/выключен
    manual_icon = "✅" if settings.manual_input_enabled else "❌"
    manual_text = f"{manual_icon} Ручной ввод"

    # Количество кнопок
    buttons_text = f"🔢 Кнопок: {settings.button_count}"

    # Количество попыток
    attempts_text = f"🔄 Попыток: {settings.max_attempts}"

    # Напоминание (интервал в секундах)
    if settings.reminder_seconds > 0:
        reminder_text = f"🔔 Напоминание: {settings.reminder_seconds} сек"
    else:
        reminder_text = "🔔 Напоминание: выкл"

    # Количество напоминаний
    if settings.reminder_count > 0:
        reminder_count_text = f"📢 Кол-во напоминаний: {settings.reminder_count}"
    else:
        reminder_count_text = "📢 Кол-во напоминаний: безлимит"

    # Чистка диалога
    cleanup_text = f"🧹 Чистка: {settings.dialog_cleanup_seconds} сек"

    return InlineKeyboardMarkup(inline_keyboard=[
        # Ручной ввод
        [InlineKeyboardButton(
            text=manual_text,
            callback_data=f"captcha:dialog:manual:{chat_id}",
        )],
        # Количество кнопок
        [InlineKeyboardButton(
            text=buttons_text,
            callback_data=f"captcha:dialog:buttons:{chat_id}",
        )],
        # Количество попыток
        [InlineKeyboardButton(
            text=attempts_text,
            callback_data=f"captcha:dialog:attempts:{chat_id}",
        )],
        # Напоминание (интервал)
        [InlineKeyboardButton(
            text=reminder_text,
            callback_data=f"captcha:dialog:reminder:{chat_id}",
        )],
        # Количество напоминаний
        [InlineKeyboardButton(
            text=reminder_count_text,
            callback_data=f"captcha:dialog:reminder_count:{chat_id}",
        )],
        # Чистка диалога
        [InlineKeyboardButton(
            text=cleanup_text,
            callback_data=f"captcha:dialog:cleanup:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад к настройкам капчи",
            callback_data=f"captcha:settings:{chat_id}",
        )],
    ])


def build_button_count_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора количества кнопок.

    Варианты: 4, 6, 9 + ручной ввод.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Готовые значения в один ряд
        [
            InlineKeyboardButton(
                text="4",
                callback_data=f"captcha:dialog:buttons_val:{chat_id}:4",
            ),
            InlineKeyboardButton(
                text="6",
                callback_data=f"captcha:dialog:buttons_val:{chat_id}:6",
            ),
            InlineKeyboardButton(
                text="9",
                callback_data=f"captcha:dialog:buttons_val:{chat_id}:9",
            ),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:dialog:buttons_input:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:dialog:{chat_id}",
        )],
    ])


def build_attempts_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора количества попыток.

    Варианты: 2, 3, 5 + ручной ввод.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Готовые значения в один ряд
        [
            InlineKeyboardButton(
                text="2",
                callback_data=f"captcha:dialog:attempts_val:{chat_id}:2",
            ),
            InlineKeyboardButton(
                text="3",
                callback_data=f"captcha:dialog:attempts_val:{chat_id}:3",
            ),
            InlineKeyboardButton(
                text="5",
                callback_data=f"captcha:dialog:attempts_val:{chat_id}:5",
            ),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:dialog:attempts_input:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:dialog:{chat_id}",
        )],
    ])


def build_reminder_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора времени напоминания.

    Варианты: 30, 60, 90 сек + выключить + ручной ввод.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Готовые значения
        [
            InlineKeyboardButton(
                text="30 сек",
                callback_data=f"captcha:dialog:reminder_val:{chat_id}:30",
            ),
            InlineKeyboardButton(
                text="60 сек",
                callback_data=f"captcha:dialog:reminder_val:{chat_id}:60",
            ),
        ],
        [
            InlineKeyboardButton(
                text="90 сек",
                callback_data=f"captcha:dialog:reminder_val:{chat_id}:90",
            ),
            InlineKeyboardButton(
                text="❌ Выкл",
                callback_data=f"captcha:dialog:reminder_val:{chat_id}:0",
            ),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:dialog:reminder_input:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:dialog:{chat_id}",
        )],
    ])


def build_cleanup_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора времени чистки диалога.

    Варианты: 60, 120, 300 сек + ручной ввод.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Готовые значения
        [
            InlineKeyboardButton(
                text="1 мин",
                callback_data=f"captcha:dialog:cleanup_val:{chat_id}:60",
            ),
            InlineKeyboardButton(
                text="2 мин",
                callback_data=f"captcha:dialog:cleanup_val:{chat_id}:120",
            ),
        ],
        [
            InlineKeyboardButton(
                text="5 мин",
                callback_data=f"captcha:dialog:cleanup_val:{chat_id}:300",
            ),
            InlineKeyboardButton(
                text="10 мин",
                callback_data=f"captcha:dialog:cleanup_val:{chat_id}:600",
            ),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:dialog:cleanup_input:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:dialog:{chat_id}",
        )],
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ TTL СООБЩЕНИЙ КАПЧИ В ГРУППЕ
# ═══════════════════════════════════════════════════════════════════════════════

def build_message_ttl_keyboard(chat_id: int, mode: str) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора TTL сообщения капчи в группе.

    TTL определяет через сколько секунд автоматически удалить
    сообщение капчи из группы.

    Варианты: 1, 2, 5, 10 мин + ручной ввод.

    Args:
        chat_id: ID группы
        mode: Режим капчи (join_group, invite_group)

    Returns:
        InlineKeyboardMarkup с кнопками выбора TTL
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Готовые значения
        [
            InlineKeyboardButton(
                text="1 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:60",
            ),
            InlineKeyboardButton(
                text="2 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:120",
            ),
        ],
        [
            InlineKeyboardButton(
                text="5 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:300",
            ),
            InlineKeyboardButton(
                text="10 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:600",
            ),
        ],
        [
            InlineKeyboardButton(
                text="15 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:900",
            ),
            InlineKeyboardButton(
                text="30 мин",
                callback_data=f"captcha:msg_ttl_val:{mode}:{chat_id}:1800",
            ),
        ],
        # Ручной ввод
        [InlineKeyboardButton(
            text="✏️ Ввести вручную",
            callback_data=f"captcha:msg_ttl_input:{mode}:{chat_id}",
        )],
        # Назад
        [InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"captcha:settings:{chat_id}",
        )],
    ])
