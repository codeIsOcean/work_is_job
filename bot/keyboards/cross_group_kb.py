# bot/keyboards/cross_group_kb.py
"""
Клавиатуры для модуля кросс-групповой детекции.

Содержит функции создания inline-клавиатур для:
- Главного меню настроек
- Настроек интервалов
- Настроек действий
- Управления исключениями
"""

# Импортируем типы aiogram для клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импортируем модели для типизации
from bot.database.models_cross_group import (
    CrossGroupScammerSettings,
    CrossGroupActionType,
)

# Импортируем форматирование времени
from bot.services.cross_group.settings_service import format_seconds_to_human


def create_cross_group_main_keyboard(
    settings: CrossGroupScammerSettings
) -> InlineKeyboardMarkup:
    """
    Создаёт главную клавиатуру настроек кросс-групповой детекции.

    Args:
        settings: Объект настроек модуля

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками настроек
    """
    # Определяем текст кнопки включения/выключения
    if settings.enabled:
        toggle_text = "🔴 Выключить детекцию"
    else:
        toggle_text = "🟢 Включить детекцию"

    # Форматируем интервалы для отображения
    join_interval = format_seconds_to_human(settings.join_interval_seconds)
    profile_window = format_seconds_to_human(settings.profile_change_window_seconds)
    message_interval = format_seconds_to_human(settings.message_interval_seconds)

    # Определяем текст действия
    action_names = {
        CrossGroupActionType.delete: "Удаление",
        CrossGroupActionType.mute: "Мут",
        CrossGroupActionType.ban: "Бан",
        CrossGroupActionType.kick: "Кик",
    }
    action_text = action_names.get(settings.action_type, "Неизвестно")

    # Количество исключённых групп
    excluded_count = len(settings.excluded_groups or [])

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Кнопка включения/выключения
        [InlineKeyboardButton(
            text=toggle_text,
            callback_data="cg:toggle"
        )],
        # Настройка интервала входов
        [InlineKeyboardButton(
            text=f"⏱ Интервал входов: {join_interval}",
            callback_data="cg:set:join_interval"
        )],
        # Настройка окна смены профиля
        [InlineKeyboardButton(
            text=f"📝 Окно смены профиля: {profile_window}",
            callback_data="cg:set:profile_window"
        )],
        # Настройка интервала сообщений
        [InlineKeyboardButton(
            text=f"💬 Интервал сообщений: {message_interval}",
            callback_data="cg:set:message_interval"
        )],
        # Настройка минимального количества групп
        [InlineKeyboardButton(
            text=f"🔢 Мин. групп: {settings.min_groups}",
            callback_data="cg:set:min_groups"
        )],
        # Настройка действия при детекции
        [InlineKeyboardButton(
            text=f"⚡ Действие: {action_text}",
            callback_data="cg:set:action"
        )],
        # Управление исключениями
        [InlineKeyboardButton(
            text=f"📋 Исключения ({excluded_count})",
            callback_data="cg:exclusions"
        )],
        # Кнопка назад
        [InlineKeyboardButton(
            text="🔙 Назад к списку групп",
            callback_data="back_to_groups"
        )],
    ])

    return keyboard


def create_interval_selection_keyboard(
    setting_name: str
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора интервала времени.

    Args:
        setting_name: Название настройки (join_interval, profile_window, message_interval)

    Returns:
        InlineKeyboardMarkup: Клавиатура с вариантами интервалов
    """
    # Определяем варианты в зависимости от типа настройки
    if setting_name == "join_interval":
        # Варианты для интервала входов (большие значения)
        options = [
            ("1 час", 3600),
            ("6 часов", 21600),
            ("12 часов", 43200),
            ("24 часа", 86400),
            ("48 часов", 172800),
            ("7 дней", 604800),
        ]
    elif setting_name == "profile_window":
        # Варианты для окна смены профиля (средние значения)
        options = [
            ("1 час", 3600),
            ("3 часа", 10800),
            ("6 часов", 21600),
            ("12 часов", 43200),
            ("24 часа", 86400),
        ]
    elif setting_name == "message_interval":
        # Варианты для интервала сообщений (маленькие значения)
        options = [
            ("15 минут", 900),
            ("30 минут", 1800),
            ("1 час", 3600),
            ("2 часа", 7200),
            ("6 часов", 21600),
        ]
    else:
        # По умолчанию — часовые интервалы
        options = [
            ("1 час", 3600),
            ("6 часов", 21600),
            ("12 часов", 43200),
            ("24 часа", 86400),
        ]

    # Создаём кнопки (по 2 в ряд)
    rows = []
    current_row = []

    for label, value in options:
        # Создаём кнопку
        button = InlineKeyboardButton(
            text=label,
            callback_data=f"cg:set_value:{setting_name}:{value}"
        )
        current_row.append(button)

        # Если в ряду 2 кнопки — добавляем ряд и начинаем новый
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    # Добавляем оставшиеся кнопки
    if current_row:
        rows.append(current_row)

    # Добавляем кнопку "Ввести вручную"
    rows.append([InlineKeyboardButton(
        text="✏️ Ввести вручную",
        callback_data=f"cg:input:{setting_name}"
    )])

    # Добавляем кнопку назад
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="cg:back_to_main"
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_min_groups_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора минимального количества групп.

    Returns:
        InlineKeyboardMarkup: Клавиатура с вариантами количества
    """
    # Варианты количества групп (от 2 до 5)
    options = [2, 3, 4, 5]

    # Создаём кнопки (по 2 в ряд)
    rows = []
    current_row = []

    for value in options:
        # Создаём кнопку
        button = InlineKeyboardButton(
            text=str(value),
            callback_data=f"cg:set_value:min_groups:{value}"
        )
        current_row.append(button)

        # Если в ряду 2 кнопки — добавляем ряд и начинаем новый
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    # Добавляем оставшиеся кнопки
    if current_row:
        rows.append(current_row)

    # Добавляем кнопку назад
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="cg:back_to_main"
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_action_selection_keyboard(
    current_action: CrossGroupActionType
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора действия при детекции.

    Args:
        current_action: Текущее выбранное действие

    Returns:
        InlineKeyboardMarkup: Клавиатура с вариантами действий
    """
    # Список действий
    actions = [
        (CrossGroupActionType.mute, "🔇 Мут", "mute"),
        (CrossGroupActionType.ban, "Бан", "ban"),
        (CrossGroupActionType.kick, "👢 Кик", "kick"),
        (CrossGroupActionType.delete, "🗑 Только удаление", "delete"),
    ]

    # Создаём кнопки
    rows = []

    for action, label, value in actions:
        # Добавляем отметку для текущего действия
        if action == current_action:
            label = f"✅ {label}"

        # Создаём кнопку
        button = InlineKeyboardButton(
            text=label,
            callback_data=f"cg:set_value:action:{value}"
        )
        rows.append([button])

    # Добавляем кнопку назад
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="cg:back_to_main"
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_exclusions_keyboard(
    excluded_groups: list,
    groups_info: dict
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру управления исключениями.

    Args:
        excluded_groups: Список исключённых chat_id
        groups_info: Словарь {chat_id: title} для отображения названий

    Returns:
        InlineKeyboardMarkup: Клавиатура со списком исключений
    """
    rows = []

    # Если есть исключения — показываем список с кнопками удаления
    if excluded_groups:
        for chat_id in excluded_groups:
            # Получаем название группы или ID
            title = groups_info.get(chat_id, f"ID: {chat_id}")
            # Ограничиваем длину названия
            if len(title) > 25:
                title = title[:22] + "..."

            # Создаём кнопку удаления
            button = InlineKeyboardButton(
                text=f"❌ {title}",
                callback_data=f"cg:remove_exclusion:{chat_id}"
            )
            rows.append([button])
    else:
        # Если исключений нет — показываем информационную кнопку
        rows.append([InlineKeyboardButton(
            text="Нет исключений",
            callback_data="cg:noop"
        )])

    # Добавляем кнопку добавления исключения
    rows.append([InlineKeyboardButton(
        text="➕ Добавить группу",
        callback_data="cg:add_exclusion"
    )])

    # Добавляем кнопку назад
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="cg:back_to_main"
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_add_exclusion_keyboard(
    available_groups: list
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора группы для добавления в исключения.

    Args:
        available_groups: Список словарей {chat_id, title} доступных групп

    Returns:
        InlineKeyboardMarkup: Клавиатура со списком групп
    """
    rows = []

    # Если есть доступные группы — показываем список
    for group in available_groups:
        chat_id = group.get("chat_id")
        title = group.get("title", f"ID: {chat_id}")

        # Ограничиваем длину названия
        if len(title) > 30:
            title = title[:27] + "..."

        # Создаём кнопку добавления
        button = InlineKeyboardButton(
            text=title,
            callback_data=f"cg:add_exclusion:{chat_id}"
        )
        rows.append([button])

    # Если групп нет — показываем информационную кнопку
    if not rows:
        rows.append([InlineKeyboardButton(
            text="Нет доступных групп",
            callback_data="cg:noop"
        )])

    # Добавляем кнопку назад
    rows.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="cg:exclusions"
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_back_to_main_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой возврата к главному меню.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой назад
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="cg:back_to_main"
        )]
    ])