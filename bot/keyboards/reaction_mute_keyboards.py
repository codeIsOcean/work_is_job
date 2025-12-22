# ============================================================
# КЛАВИАТУРЫ ДЛЯ МОДУЛЯ REACTION MUTE (МЬЮТ ПО РЕАКЦИЯМ)
# ============================================================
# Полный UI настроек по аналогии с content_filter:
# - Главное меню модуля
# - Список реакций с возможностью настройки каждой
# - Меню редактирования: действие, длительность, удаление, текст
#
# Callback формат: rm:{action}:{params}:{chat_id}
# ============================================================

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, Dict, Any


# ============================================================
# КОНСТАНТЫ
# ============================================================

# Список поддерживаемых реакций с описаниями
REACTIONS_INFO = {
    "👎": {"name": "Дизлайк", "default_action": "mute", "default_duration": 3 * 24 * 60},
    "🤢": {"name": "Тошнота", "default_action": "mute", "default_duration": 7 * 24 * 60},
    "🤮": {"name": "Рвота", "default_action": "mute", "default_duration": 7 * 24 * 60},
    "💩": {"name": "Какашка", "default_action": "mute_forever", "default_duration": None},
    "😡": {"name": "Злость", "default_action": "warn", "default_duration": None},
}

# Доступные действия
ACTIONS = {
    "delete": {"name": "Только удалить", "emoji": "🗑️"},
    "warn": {"name": "Предупреждение", "emoji": "⚠️"},
    "mute": {"name": "Мьют", "emoji": "🔇"},
    "mute_forever": {"name": "Мьют навсегда", "emoji": "♾️"},
    "ban": {"name": "Бан", "emoji": "🚫"},
}

# Предустановленные длительности (в минутах)
DURATIONS = [
    {"value": 60, "label": "1 час"},
    {"value": 3 * 60, "label": "3 часа"},
    {"value": 12 * 60, "label": "12 часов"},
    {"value": 24 * 60, "label": "1 день"},
    {"value": 3 * 24 * 60, "label": "3 дня"},
    {"value": 7 * 24 * 60, "label": "7 дней"},
    {"value": 14 * 24 * 60, "label": "14 дней"},
    {"value": 30 * 24 * 60, "label": "30 дней"},
    {"value": None, "label": "Навсегда"},
]


def format_duration(minutes: Optional[int]) -> str:
    """Форматирует длительность в читаемый вид."""
    if minutes is None:
        return "навсегда"
    if minutes < 60:
        return f"{minutes} мин"
    elif minutes < 24 * 60:
        hours = minutes // 60
        return f"{hours} ч"
    else:
        days = minutes // (24 * 60)
        return f"{days} д"


def get_default_reaction_settings(emoji: str) -> Dict[str, Any]:
    """Возвращает дефолтные настройки для реакции."""
    info = REACTIONS_INFO.get(emoji, {"default_action": "warn", "default_duration": None})
    return {
        "action": info.get("default_action", "warn"),
        "duration": info.get("default_duration"),
        "delete_message": True,  # Удалять сообщение нарушителя
        "custom_text": None,  # Кастомный текст уведомления
        "notification_delete_delay": None,  # Автоудаление уведомления бота
        "delete_delay": 0,  # Задержка перед удалением (0 = сразу)
    }


# ============================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК РЕАКЦИЙ
# ============================================================

def create_reaction_mute_main_menu(
    chat_id: int,
    enabled: bool,
    announce_enabled: bool,
    reaction_settings: Optional[Dict[str, Any]] = None
) -> InlineKeyboardMarkup:
    """
    Создает главное меню настроек мута по реакциям.
    """
    if reaction_settings is None:
        reaction_settings = {}

    buttons = []

    # Статус модуля
    status_text = "✅ Модуль включён" if enabled else "❌ Модуль выключен"
    toggle_action = "off" if enabled else "on"
    buttons.append([
        InlineKeyboardButton(
            text=status_text,
            callback_data=f"rm:t:{toggle_action}:{chat_id}"
        )
    ])

    # Разделитель
    buttons.append([
        InlineKeyboardButton(text="───── Реакции ─────", callback_data="rm:noop")
    ])

    # Список реакций
    for emoji, info in REACTIONS_INFO.items():
        settings = reaction_settings.get(emoji, get_default_reaction_settings(emoji))
        action = settings.get("action", info["default_action"])
        duration = settings.get("duration", info.get("default_duration"))

        action_info = ACTIONS.get(action, ACTIONS["mute"])
        if action in ("mute_forever", "warn", "delete", "ban"):
            duration_text = ""
        else:
            duration_text = f" ({format_duration(duration)})"

        button_text = f"{emoji} {info['name']}: {action_info['emoji']} {action_info['name']}{duration_text}"

        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"rm:e:{emoji}:{chat_id}"
            )
        ])

    # Разделитель
    buttons.append([
        InlineKeyboardButton(text="───── Настройки ─────", callback_data="rm:noop")
    ])

    # Уведомления в группу
    announce_text = "🔔 Уведомления в группу: ВКЛ" if announce_enabled else "🔕 Уведомления в группу: ВЫКЛ"
    buttons.append([
        InlineKeyboardButton(text=announce_text, callback_data=f"rm:t:ann:{chat_id}")
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_group_{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ РЕДАКТИРОВАНИЯ РЕАКЦИИ (ПОЛНОЕ)
# ============================================================

def create_reaction_edit_menu(
    chat_id: int,
    emoji: str,
    settings: Dict[str, Any]
) -> InlineKeyboardMarkup:
    """
    Создает полное меню редактирования реакции.
    Включает: действие, длительность, удаление сообщения, текст, задержки.
    """
    info = REACTIONS_INFO.get(emoji, {"name": emoji})
    buttons = []

    action = settings.get("action", "mute")
    duration = settings.get("duration")
    delete_message = settings.get("delete_message", True)
    custom_text = settings.get("custom_text")
    notification_delay = settings.get("notification_delete_delay")
    delete_delay = settings.get("delete_delay", 0)

    action_info = ACTIONS.get(action, ACTIONS["mute"])

    # 1. Действие
    buttons.append([
        InlineKeyboardButton(
            text=f"⚡ Действие: {action_info['emoji']} {action_info['name']}",
            callback_data=f"rm:a:{emoji}:{chat_id}"
        )
    ])

    # 2. Длительность (только для mute)
    if action == "mute":
        duration_text = format_duration(duration)
        buttons.append([
            InlineKeyboardButton(
                text=f"⏱️ Длительность: {duration_text}",
                callback_data=f"rm:d:{emoji}:{chat_id}"
            )
        ])

    # 3. Удаление сообщения нарушителя
    delete_msg_text = "🗑️ Удалять сообщение: ДА" if delete_message else "🗑️ Удалять сообщение: НЕТ"
    buttons.append([
        InlineKeyboardButton(
            text=delete_msg_text,
            callback_data=f"rm:tdm:{emoji}:{chat_id}"
        )
    ])

    # 4. Задержка удаления сообщения
    if delete_message:
        delay_text = f"{delete_delay} сек" if delete_delay else "сразу"
        buttons.append([
            InlineKeyboardButton(
                text=f"⏳ Задержка удаления: {delay_text}",
                callback_data=f"rm:dd:{emoji}:{chat_id}"
            )
        ])

    # 5. Кастомный текст уведомления
    if action not in ("delete",):  # Для "только удалить" текст не нужен
        text_preview = f"«{custom_text[:20]}...»" if custom_text and len(custom_text) > 20 else (f"«{custom_text}»" if custom_text else "по умолчанию")
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Текст: {text_preview}",
                callback_data=f"rm:ct:{emoji}:{chat_id}"
            )
        ])

    # 6. Автоудаление уведомления бота
    if action not in ("delete",):
        notif_text = f"{notification_delay} сек" if notification_delay else "не удалять"
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑️ Автоудаление уведомления: {notif_text}",
                callback_data=f"rm:nd:{emoji}:{chat_id}"
            )
        ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"rm:m:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ
# ============================================================

def create_action_select_menu(
    chat_id: int,
    emoji: str,
    current_action: str
) -> InlineKeyboardMarkup:
    """Создает меню выбора действия для реакции."""
    buttons = []

    for action_key, action_info in ACTIONS.items():
        check = " ✓" if action_key == current_action else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{action_info['emoji']} {action_info['name']}{check}",
                callback_data=f"rm:sa:{emoji}:{action_key}:{chat_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"rm:e:{emoji}:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ДЛИТЕЛЬНОСТИ
# ============================================================

def create_duration_select_menu(
    chat_id: int,
    emoji: str,
    current_duration: Optional[int]
) -> InlineKeyboardMarkup:
    """Создает меню выбора длительности мута."""
    buttons = []

    # Кнопки с предустановленными длительностями (по 2 в ряд)
    row = []
    for i, dur in enumerate(DURATIONS):
        check = " ✓" if dur["value"] == current_duration else ""
        value_str = str(dur["value"]) if dur["value"] is not None else "inf"

        row.append(
            InlineKeyboardButton(
                text=f"{dur['label']}{check}",
                callback_data=f"rm:sd:{emoji}:{value_str}:{chat_id}"
            )
        )

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Кастомная длительность
    buttons.append([
        InlineKeyboardButton(
            text="✏️ Своё значение...",
            callback_data=f"rm:cd:{emoji}:{chat_id}"
        )
    ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"rm:e:{emoji}:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ЗАДЕРЖКИ УДАЛЕНИЯ СООБЩЕНИЯ
# ============================================================

def create_delete_delay_menu(
    chat_id: int,
    emoji: str,
    current_delay: int
) -> InlineKeyboardMarkup:
    """Создает меню выбора задержки удаления."""
    buttons = []

    delays = [
        {"value": 0, "label": "Сразу"},
        {"value": 3, "label": "3 сек"},
        {"value": 5, "label": "5 сек"},
        {"value": 10, "label": "10 сек"},
        {"value": 30, "label": "30 сек"},
    ]

    row = []
    for delay in delays:
        check = " ✓" if delay["value"] == current_delay else ""
        row.append(
            InlineKeyboardButton(
                text=f"{delay['label']}{check}",
                callback_data=f"rm:sdd:{emoji}:{delay['value']}:{chat_id}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="✏️ Своё значение...", callback_data=f"rm:cdd:{emoji}:{chat_id}")
    ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"rm:e:{emoji}:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ АВТОУДАЛЕНИЯ УВЕДОМЛЕНИЯ БОТА
# ============================================================

def create_notification_delay_menu(
    chat_id: int,
    emoji: str,
    current_delay: Optional[int]
) -> InlineKeyboardMarkup:
    """Создает меню выбора времени автоудаления уведомления."""
    buttons = []

    delays = [
        {"value": None, "label": "Не удалять"},
        {"value": 10, "label": "10 сек"},
        {"value": 30, "label": "30 сек"},
        {"value": 60, "label": "1 мин"},
        {"value": 300, "label": "5 мин"},
    ]

    row = []
    for delay in delays:
        check = " ✓" if delay["value"] == current_delay else ""
        value_str = str(delay["value"]) if delay["value"] is not None else "none"
        row.append(
            InlineKeyboardButton(
                text=f"{delay['label']}{check}",
                callback_data=f"rm:snd:{emoji}:{value_str}:{chat_id}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="✏️ Своё значение...", callback_data=f"rm:cnd:{emoji}:{chat_id}")
    ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"rm:e:{emoji}:{chat_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# КЛАВИАТУРА ОТМЕНЫ (ДЛЯ FSM)
# ============================================================

def create_cancel_keyboard(chat_id: int, emoji: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой отмены."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"rm:e:{emoji}:{chat_id}")]
        ]
    )
