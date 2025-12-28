# ============================================================
# КЛАВИАТУРЫ SCAM MEDIA FILTER
# ============================================================
# Клавиатуры для настроек модуля фильтрации скам-изображений.
#
# Содержит:
# - Главное меню настроек
# - Выбор действия (delete, warn, mute, ban)
# - Настройка времени мута/бана
# - Настройка порога срабатывания
# ============================================================

# Импорт для логирования
import logging
# Импорт для аннотации типов
from typing import Optional

# Импорт aiogram клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импорт модели настроек
from bot.database.models_scam_media import ScamMediaSettings


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# КОНСТАНТЫ CALLBACK_DATA
# ============================================================
# Префикс для всех callback_data модуля
PREFIX = "sm"

# Действия
CB_TOGGLE = f"{PREFIX}:toggle:{{chat_id}}"
CB_ACTION = f"{PREFIX}:action:{{chat_id}}"
CB_ACTION_SET = f"{PREFIX}:action_set:{{chat_id}}:{{action}}"
CB_THRESHOLD = f"{PREFIX}:threshold:{{chat_id}}"
CB_THRESHOLD_SET = f"{PREFIX}:threshold_set:{{chat_id}}:{{value}}"
CB_MUTE_TIME = f"{PREFIX}:mute_time:{{chat_id}}"
CB_MUTE_TIME_SET = f"{PREFIX}:mute_time_set:{{chat_id}}:{{value}}"
CB_BAN_TIME = f"{PREFIX}:ban_time:{{chat_id}}"
CB_BAN_TIME_SET = f"{PREFIX}:ban_time_set:{{chat_id}}:{{value}}"
CB_CUSTOM_TIME = f"{PREFIX}:custom_time:{{chat_id}}:{{type}}"
CB_GLOBAL = f"{PREFIX}:global:{{chat_id}}"
CB_JOURNAL = f"{PREFIX}:journal:{{chat_id}}"
CB_SCAMMER_DB = f"{PREFIX}:scammer_db:{{chat_id}}"
CB_NOTIFICATION = f"{PREFIX}:notification:{{chat_id}}"
CB_BACK = f"{PREFIX}:back:{{chat_id}}"
CB_CLOSE = f"{PREFIX}:close:{{chat_id}}"


# ============================================================
# ПРЕДУСТАНОВЛЕННЫЕ ЗНАЧЕНИЯ ВРЕМЕНИ
# ============================================================
# Время мута (в секундах)
MUTE_DURATIONS = [
    (300, "5 мин"),
    (900, "15 мин"),
    (1800, "30 мин"),
    (3600, "1 час"),
    (7200, "2 часа"),
    (21600, "6 часов"),
    (43200, "12 часов"),
    (86400, "24 часа"),
    (259200, "3 дня"),
    (604800, "7 дней"),
    (0, "Навсегда"),
]

# Время бана (в секундах)
BAN_DURATIONS = [
    (86400, "1 день"),
    (259200, "3 дня"),
    (604800, "7 дней"),
    (1209600, "14 дней"),
    (2592000, "30 дней"),
    (7776000, "90 дней"),
    (0, "Навсегда"),
]

# Пороги срабатывания (расстояние Хэмминга)
THRESHOLD_VALUES = [
    (5, "5 (строгий)"),
    (8, "8 (умеренный)"),
    (10, "10 (стандарт)"),
    (12, "12 (мягкий)"),
    (15, "15 (свободный)"),
]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _get_status_icon(enabled: bool) -> str:
    """
    Возвращает иконку состояния.

    Args:
        enabled: Включено/выключено

    Returns:
        Строка с эмодзи
    """
    return "✅" if enabled else "❌"


def _format_duration(seconds: int) -> str:
    """
    Форматирует длительность в человекочитаемый формат.

    Args:
        seconds: Длительность в секундах

    Returns:
        Строка вида "24 часа", "7 дней", "навсегда"
    """
    if seconds == 0:
        return "навсегда"
    if seconds < 60:
        return f"{seconds} сек."
    if seconds < 3600:
        return f"{seconds // 60} мин."
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} ч."
    days = seconds // 86400
    return f"{days} дн."


def _get_action_label(action: str) -> str:
    """
    Возвращает человекочитаемое название действия.

    Args:
        action: Код действия

    Returns:
        Название на русском
    """
    labels = {
        "delete": "Удалить",
        "delete_warn": "Удалить + предупреждение",
        "delete_mute": "Удалить + мут",
        "delete_ban": "Удалить + бан",
    }
    return labels.get(action, action)


# ============================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================

def build_settings_keyboard(
    chat_id: int,
    settings: ScamMediaSettings
) -> InlineKeyboardMarkup:
    """
    Создаёт главное меню настроек ScamMedia.

    Args:
        chat_id: ID группы
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup с кнопками настроек
    """
    # Состояние модуля
    status_icon = _get_status_icon(settings.enabled)
    status_text = "Включено" if settings.enabled else "Выключено"

    # Текущее действие
    action_label = _get_action_label(settings.action)

    # Формируем кнопки
    buttons = [
        # Статус модуля
        [
            InlineKeyboardButton(
                text=f"{status_icon} Модуль: {status_text}",
                callback_data=CB_TOGGLE.format(chat_id=chat_id)
            )
        ],
        # Действие при срабатывании
        [
            InlineKeyboardButton(
                text=f"⚡ Действие: {action_label}",
                callback_data=CB_ACTION.format(chat_id=chat_id)
            )
        ],
        # Порог срабатывания
        [
            InlineKeyboardButton(
                text=f"📊 Порог: {settings.threshold}",
                callback_data=CB_THRESHOLD.format(chat_id=chat_id)
            )
        ],
    ]

    # Время мута (если действие = delete_mute)
    if settings.action == "delete_mute":
        mute_text = _format_duration(settings.mute_duration)
        buttons.append([
            InlineKeyboardButton(
                text=f"🔇 Время мута: {mute_text}",
                callback_data=CB_MUTE_TIME.format(chat_id=chat_id)
            )
        ])

    # Время бана (если действие = delete_ban)
    if settings.action == "delete_ban":
        ban_text = _format_duration(settings.ban_duration)
        buttons.append([
            InlineKeyboardButton(
                text=f"🚫 Время бана: {ban_text}",
                callback_data=CB_BAN_TIME.format(chat_id=chat_id)
            )
        ])

    # Глобальные хеши
    global_icon = _get_status_icon(settings.use_global_hashes)
    buttons.append([
        InlineKeyboardButton(
            text=f"{global_icon} Глобальная база",
            callback_data=CB_GLOBAL.format(chat_id=chat_id)
        )
    ])

    # Журнал
    journal_icon = _get_status_icon(settings.log_to_journal)
    buttons.append([
        InlineKeyboardButton(
            text=f"{journal_icon} Журнал",
            callback_data=CB_JOURNAL.format(chat_id=chat_id)
        )
    ])

    # БД скаммеров
    scammer_icon = _get_status_icon(settings.add_to_scammer_db)
    buttons.append([
        InlineKeyboardButton(
            text=f"{scammer_icon} Добавлять в БД скаммеров",
            callback_data=CB_SCAMMER_DB.format(chat_id=chat_id)
        )
    ])

    # Кнопка закрытия
    buttons.append([
        InlineKeyboardButton(
            text="✖️ Закрыть",
            callback_data=CB_CLOSE.format(chat_id=chat_id)
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ
# ============================================================

def build_action_keyboard(
    chat_id: int,
    current_action: str
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия при срабатывании.

    Args:
        chat_id: ID группы
        current_action: Текущее действие

    Returns:
        InlineKeyboardMarkup с вариантами действий
    """
    actions = [
        ("delete", "🗑️ Только удалить"),
        ("delete_warn", "⚠️ Удалить + предупреждение"),
        ("delete_mute", "🔇 Удалить + мут"),
        ("delete_ban", "🚫 Удалить + бан"),
    ]

    buttons = []
    for action_code, action_text in actions:
        # Отмечаем текущее действие
        icon = "✅ " if action_code == current_action else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon}{action_text}",
                callback_data=CB_ACTION_SET.format(chat_id=chat_id, action=action_code)
            )
        ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=CB_BACK.format(chat_id=chat_id)
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ПОРОГА
# ============================================================

def build_threshold_keyboard(
    chat_id: int,
    current_threshold: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора порога срабатывания.

    Args:
        chat_id: ID группы
        current_threshold: Текущий порог

    Returns:
        InlineKeyboardMarkup с вариантами порогов
    """
    buttons = []
    for value, label in THRESHOLD_VALUES:
        # Отмечаем текущее значение
        icon = "✅ " if value == current_threshold else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon}{label}",
                callback_data=CB_THRESHOLD_SET.format(chat_id=chat_id, value=value)
            )
        ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=CB_BACK.format(chat_id=chat_id)
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ВРЕМЕНИ МУТА
# ============================================================

def build_mute_time_keyboard(
    chat_id: int,
    current_duration: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора времени мута.

    Args:
        chat_id: ID группы
        current_duration: Текущая длительность в секундах

    Returns:
        InlineKeyboardMarkup с вариантами времени
    """
    buttons = []

    # Группируем по 2 кнопки в ряд для компактности
    row = []
    for value, label in MUTE_DURATIONS:
        # Отмечаем текущее значение
        icon = "✅ " if value == current_duration else ""
        row.append(
            InlineKeyboardButton(
                text=f"{icon}{label}",
                callback_data=CB_MUTE_TIME_SET.format(chat_id=chat_id, value=value)
            )
        )
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
            callback_data=CB_CUSTOM_TIME.format(chat_id=chat_id, type="mute")
        )
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=CB_BACK.format(chat_id=chat_id)
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ВРЕМЕНИ БАНА
# ============================================================

def build_ban_time_keyboard(
    chat_id: int,
    current_duration: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора времени бана.

    Args:
        chat_id: ID группы
        current_duration: Текущая длительность в секундах

    Returns:
        InlineKeyboardMarkup с вариантами времени
    """
    buttons = []

    # Группируем по 2 кнопки в ряд
    row = []
    for value, label in BAN_DURATIONS:
        # Отмечаем текущее значение
        icon = "✅ " if value == current_duration else ""
        row.append(
            InlineKeyboardButton(
                text=f"{icon}{label}",
                callback_data=CB_BAN_TIME_SET.format(chat_id=chat_id, value=value)
            )
        )
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
            callback_data=CB_CUSTOM_TIME.format(chat_id=chat_id, type="ban")
        )
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=CB_BACK.format(chat_id=chat_id)
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
