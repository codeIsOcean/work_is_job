"""
Клавиатуры для антиспам модуля.

Этот модуль содержит все inline клавиатуры для настройки антиспам:
- Главное меню антиспам
- Настройки Telegram ссылок
- Настройки пересылок (каналы, группы, пользователи, боты)
- Настройки цитат (каналы, группы, пользователи, боты)
- Настройки блокировки всех ссылок
- Управление белыми списками (исключениями)

ВАЖНО: Используем короткие callback_data из-за лимита Telegram в 64 байта!
Схема сокращений:
- as = antispam (главный префикс)
- m = main_menu, a = set_action, d = toggle_delete, t = duration
- tl = telegram_links, al = any_links
- fc/fg/fu/fb = forward_channel/group/user/bot
- qc/qg/qu/qb = quote_channel/group/user/bot
- wl = whitelist, wa = whitelist_add, wd = whitelist_delete
"""

# Импорт типов для создания клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# Импорт типов из модулей антиспам
from typing import Optional, List, Dict
# Импорт enum типов для правил и действий
from bot.database.models_antispam import RuleType, ActionType, WhitelistScope


# ============================================================
# МАППИНГ ТИПОВ ПРАВИЛ НА КОРОТКИЕ КОДЫ
# ============================================================

# Словарь для преобразования RuleType в короткий код
RULE_TYPE_TO_SHORT = {
    RuleType.TELEGRAM_LINK: "tl",
    RuleType.ANY_LINK: "al",
    RuleType.FORWARD_CHANNEL: "fc",
    RuleType.FORWARD_GROUP: "fg",
    RuleType.FORWARD_USER: "fu",
    RuleType.FORWARD_BOT: "fb",
    RuleType.QUOTE_CHANNEL: "qc",
    RuleType.QUOTE_GROUP: "qg",
    RuleType.QUOTE_USER: "qu",
    RuleType.QUOTE_BOT: "qb",
}

# Обратный словарь для преобразования короткого кода в RuleType
SHORT_TO_RULE_TYPE = {v: k for k, v in RULE_TYPE_TO_SHORT.items()}


# ============================================================
# ГЛАВНОЕ МЕНЮ АНТИСПАМ
# ============================================================

def create_antispam_main_menu(
    # ID чата для формирования callback_data
    chat_id: int,
    # Текущий TTL предупреждений (для отображения)
    warning_ttl_seconds: int = 0,
) -> InlineKeyboardMarkup:
    """
    Создать главное меню антиспам с основными разделами.

    Callback формат: as:m:{chat_id} или as:{section}:{chat_id}
    """
    # Формируем текст TTL для кнопки
    if warning_ttl_seconds == 0:
        ttl_text = "Не удалять"
    elif warning_ttl_seconds < 60:
        ttl_text = f"{warning_ttl_seconds} сек"
    elif warning_ttl_seconds < 3600:
        ttl_text = f"{warning_ttl_seconds // 60} мин"
    elif warning_ttl_seconds < 86400:
        ttl_text = f"{warning_ttl_seconds // 3600} ч"
    else:
        ttl_text = f"{warning_ttl_seconds // 86400} дн"

    # Создаем объект клавиатуры
    keyboard = InlineKeyboardMarkup(
        # Массив рядов кнопок
        inline_keyboard=[
            # Кнопка "Telegram ссылки"
            [InlineKeyboardButton(
                text="📱 Telegram ссылки",
                callback_data=f"as:tl:{chat_id}"
            )],
            # Кнопка "Пересылка"
            [InlineKeyboardButton(
                text="📨 Пересылка",
                callback_data=f"as:fwd:{chat_id}"
            )],
            # Кнопка "Цитаты"
            [InlineKeyboardButton(
                text="💬 Цитаты",
                callback_data=f"as:qt:{chat_id}"
            )],
            # Кнопка "Блок всех ссылок"
            [InlineKeyboardButton(
                text="🔗 Блок всех ссылок",
                callback_data=f"as:al:{chat_id}"
            )],
            # Кнопка "Авто-удаление уведомлений"
            [InlineKeyboardButton(
                text=f"⏱️ Авто-удаление ({ttl_text})",
                callback_data=f"as:ttl:{chat_id}"
            )],
            # Кнопка "Назад к настройкам группы"
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"manage_group_{chat_id}"
            )]
        ]
    )
    # Возвращаем созданную клавиатуру
    return keyboard


# ============================================================
# КЛАВИАТУРА НАСТРОЕК ДЕЙСТВИЯ (ОБЩАЯ)
# ============================================================

def create_action_settings_keyboard(
    # ID чата
    chat_id: int,
    # Тип правила (для формирования callback_data)
    rule_type: RuleType,
    # Текущее действие
    current_action: ActionType,
    # Флаг удаления сообщения
    delete_message: bool,
    # Длительность ограничения в минутах
    restrict_minutes: Optional[int],
    # Короткий код правила (например "tl", "fc")
    short_code: str,
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру для настройки действий антиспам.

    Callback формат: as:a:{short_code}:{ACTION}:{chat_id}
    """
    # Список рядов кнопок
    rows = []

    # Кнопка "Выкл"
    off_text = "✅ Выкл" if current_action == ActionType.OFF else "❌ Выкл"
    rows.append([InlineKeyboardButton(
        text=off_text,
        callback_data=f"as:a:{short_code}:OFF:{chat_id}"
    )])

    # Кнопка "Только удалить" (без наказания)
    delete_only_text = "✅ Только удалить" if current_action == ActionType.DELETE else "🗑️ Только удалить"
    rows.append([InlineKeyboardButton(
        text=delete_only_text,
        callback_data=f"as:a:{short_code}:DELETE:{chat_id}"
    )])

    # Кнопка "Предупреждение"
    warn_text = "✅ Предупреждение" if current_action == ActionType.WARN else "❗ Предупреждение"
    rows.append([InlineKeyboardButton(
        text=warn_text,
        callback_data=f"as:a:{short_code}:WARN:{chat_id}"
    )])

    # Кнопка "Исключить"
    kick_text = "✅ Исключить" if current_action == ActionType.KICK else "🚪 Исключить"
    rows.append([InlineKeyboardButton(
        text=kick_text,
        callback_data=f"as:a:{short_code}:KICK:{chat_id}"
    )])

    # Кнопка "Ограничить"
    if current_action == ActionType.RESTRICT:
        restrict_text = f"✅ Ограничить ({restrict_minutes or 30} мин)"
    else:
        restrict_text = "🔇 Ограничить"
    rows.append([InlineKeyboardButton(
        text=restrict_text,
        callback_data=f"as:a:{short_code}:RESTRICT:{chat_id}"
    )])

    # Кнопка "Заблокировать"
    ban_text = "✅ Заблокировать" if current_action == ActionType.BAN else "🚫 Заблокировать"
    rows.append([InlineKeyboardButton(
        text=ban_text,
        callback_data=f"as:a:{short_code}:BAN:{chat_id}"
    )])

    # Кнопка переключения удаления сообщений
    delete_text = "🗑️ Удалять сообщения ✅" if delete_message else "🗑️ Удалять сообщения ❌"
    rows.append([InlineKeyboardButton(
        text=delete_text,
        callback_data=f"as:d:{short_code}:{chat_id}"
    )])

    # Кнопка длительности (только для RESTRICT)
    if current_action == ActionType.RESTRICT:
        rows.append([InlineKeyboardButton(
            text="⏱️ Длительность ограничения",
            callback_data=f"as:t:{short_code}:{chat_id}"
        )])

    # Кнопка исключений (белый список)
    rows.append([InlineKeyboardButton(
        text="📋 Исключения",
        callback_data=f"as:wl:{short_code}:{chat_id}"
    )])

    # Кнопка "Назад"
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"as:m:{chat_id}"
    )])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# КЛАВИАТУРА ВЫБОРА ДЛИТЕЛЬНОСТИ
# ============================================================

def create_duration_keyboard(
    # ID чата
    chat_id: int,
    # Короткий код правила
    short_code: str,
    # Текущая длительность
    current_duration: Optional[int],
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру для выбора длительности ограничения.

    Callback формат:
    - as:sd:{short_code}:{minutes}:{chat_id} - выбор предустановленной длительности
    - as:sdc:{short_code}:{chat_id} - ввод произвольной длительности
    """
    # Доступные варианты длительности в минутах
    durations = [
        (15, "15 мин"),
        (30, "30 мин"),
        (60, "1 час"),
        (180, "3 часа"),
        (720, "12 часов"),
        (1440, "1 день"),
        (10080, "1 неделя"),
        (0, "Навсегда"),
    ]

    # Список рядов кнопок
    rows = []

    # Создаем кнопки для каждой длительности
    for minutes, label in durations:
        # Определяем является ли это текущее значение
        is_current = (minutes == current_duration) or (minutes == 0 and current_duration is None)
        # Формируем текст кнопки
        text = f"✅ {label}" if is_current else label
        # Добавляем кнопку
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"as:sd:{short_code}:{minutes}:{chat_id}"
        )])

    # Кнопка "Ввести вручную"
    rows.append([InlineKeyboardButton(
        text="✏️ Ввести вручную",
        callback_data=f"as:sdc:{short_code}:{chat_id}"
    )])

    # Кнопка "Назад"
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"as:{short_code}:{chat_id}"
    )])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# КЛАВИАТУРА ВЫБОРА TTL УВЕДОМЛЕНИЙ
# ============================================================

def create_warning_ttl_keyboard(
    # ID чата
    chat_id: int,
    # Текущий TTL в секундах
    current_ttl: int = 0,
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру для выбора времени жизни уведомлений.

    Callback формат: as:sttl:{seconds}:{chat_id}
    """
    # Доступные варианты TTL в секундах
    ttl_options = [
        (0, "Не удалять"),
        (30, "30 секунд"),
        (60, "1 минута"),
        (300, "5 минут"),
        (3600, "1 час"),
        (86400, "1 день"),
        (2592000, "1 месяц"),
    ]

    # Список рядов кнопок
    rows = []

    # Создаем кнопки для каждого варианта
    for seconds, label in ttl_options:
        # Определяем является ли это текущее значение
        is_current = seconds == current_ttl
        # Формируем текст кнопки
        text = f"✅ {label}" if is_current else label
        # Добавляем кнопку
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"as:sttl:{seconds}:{chat_id}"
        )])

    # Кнопка "Ввести вручную"
    rows.append([InlineKeyboardButton(
        text="✏️ Ввести вручную",
        callback_data=f"as:cttl:{chat_id}"
    )])

    # Кнопка "Назад"
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"as:m:{chat_id}"
    )])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# МЕНЮ ИСТОЧНИКОВ ПЕРЕСЫЛКИ
# ============================================================

def create_forward_sources_menu(
    # ID чата
    chat_id: int,
) -> InlineKeyboardMarkup:
    """
    Создать меню выбора источника пересылки.

    Callback формат: as:fs:{source}:{chat_id}
    """
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Кнопка "Из каналов"
            [InlineKeyboardButton(
                text="📢 Из каналов",
                callback_data=f"as:fs:c:{chat_id}"
            )],
            # Кнопка "Из групп"
            [InlineKeyboardButton(
                text="👥 Из групп",
                callback_data=f"as:fs:g:{chat_id}"
            )],
            # Кнопка "От пользователей"
            [InlineKeyboardButton(
                text="👤 От пользователей",
                callback_data=f"as:fs:u:{chat_id}"
            )],
            # Кнопка "От ботов"
            [InlineKeyboardButton(
                text="🤖 От ботов",
                callback_data=f"as:fs:b:{chat_id}"
            )],
            # Кнопка "Назад"
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"as:m:{chat_id}"
            )]
        ]
    )
    # Возвращаем клавиатуру
    return keyboard


# ============================================================
# МЕНЮ ИСТОЧНИКОВ ЦИТАТ
# ============================================================

def create_quotes_sources_menu(
    # ID чата
    chat_id: int,
) -> InlineKeyboardMarkup:
    """
    Создать меню выбора источника цитаты.

    Callback формат: as:qs:{source}:{chat_id}
    """
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Кнопка "Из каналов"
            [InlineKeyboardButton(
                text="📢 Из каналов",
                callback_data=f"as:qs:c:{chat_id}"
            )],
            # Кнопка "Из групп"
            [InlineKeyboardButton(
                text="👥 Из групп",
                callback_data=f"as:qs:g:{chat_id}"
            )],
            # Кнопка "От пользователей"
            [InlineKeyboardButton(
                text="👤 От пользователей",
                callback_data=f"as:qs:u:{chat_id}"
            )],
            # Кнопка "От ботов"
            [InlineKeyboardButton(
                text="🤖 От ботов",
                callback_data=f"as:qs:b:{chat_id}"
            )],
            # Кнопка "Назад"
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"as:m:{chat_id}"
            )]
        ]
    )
    # Возвращаем клавиатуру
    return keyboard


# ============================================================
# МЕНЮ БЕЛОГО СПИСКА
# ============================================================

def create_whitelist_menu(
    # ID чата
    chat_id: int,
    # Короткий код правила
    short_code: str,
    # Количество записей (для показа кнопки удаления)
    entries_count: int = 0,
) -> InlineKeyboardMarkup:
    """
    Создать меню белого списка.

    ИЗМЕНЕНО: Записи показываются как текстовый список в сообщении,
    не как кнопки. Это решает проблему со слишком большим количеством кнопок.

    Callback формат:
    - as:wdn:{short_code}:{chat_id} - удалить по номеру
    - as:wa:{short_code}:{chat_id} - добавить
    """
    # Список рядов кнопок
    rows = []

    # Кнопка "Удалить по номеру" (только если есть записи)
    if entries_count > 0:
        rows.append([InlineKeyboardButton(
            text="🗑️ Удалить по номеру",
            callback_data=f"as:wdn:{short_code}:{chat_id}"
        )])

    # Кнопка "Добавить"
    rows.append([InlineKeyboardButton(
        text="➕ Добавить исключение",
        callback_data=f"as:wa:{short_code}:{chat_id}"
    )])

    # Кнопка "Назад"
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"as:{short_code}:{chat_id}"
    )])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ
# ============================================================

def create_delete_confirmation_keyboard(
    # ID чата
    chat_id: int,
    # Короткий код правила
    short_code: str,
    # ID записи белого списка
    whitelist_id: int,
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру подтверждения удаления.

    Callback формат: as:wdc:{short_code}:{entry_id}:{chat_id} для подтверждения
    """
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Кнопка подтверждения
            [InlineKeyboardButton(
                text="✅ Да, удалить",
                callback_data=f"as:wdc:{short_code}:{whitelist_id}:{chat_id}"
            )],
            # Кнопка отмены
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"as:wl:{short_code}:{chat_id}"
            )]
        ]
    )
    # Возвращаем клавиатуру
    return keyboard


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_short_code_for_rule_type(rule_type: RuleType) -> str:
    """Получить короткий код для типа правила."""
    return RULE_TYPE_TO_SHORT.get(rule_type, "tl")


def get_rule_type_from_short_code(short_code: str) -> Optional[RuleType]:
    """Получить тип правила по короткому коду."""
    return SHORT_TO_RULE_TYPE.get(short_code)
