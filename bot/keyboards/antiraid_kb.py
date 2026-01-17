# bot/keyboards/antiraid_kb.py
"""
Клавиатуры для UI настроек модуля Anti-Raid.

Все клавиатуры для настроек Anti-Raid в ЛС бота:
- Главное меню (список компонентов)
- Настройки каждого компонента
- Выбор действий и значений
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, List

# Импортируем модели для типизации
from bot.database.models_antiraid import AntiRaidSettings, AntiRaidNamePattern


def create_antiraid_main_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings]
) -> InlineKeyboardMarkup:
    """
    Создаёт главное меню настроек Anti-Raid.

    Показывает список компонентов с их статусами (вкл/выкл).

    Args:
        chat_id: ID чата
        settings: Текущие настройки группы (может быть None)

    Returns:
        InlineKeyboardMarkup с кнопками компонентов
    """
    # Определяем статусы компонентов
    if settings:
        je_status = "✅" if settings.join_exit_enabled else "❌"
        np_status = "✅" if settings.name_pattern_enabled else "❌"
        mj_status = "✅" if settings.mass_join_enabled else "❌"
        mi_status = "✅" if settings.mass_invite_enabled else "❌"
        mr_status = "✅" if settings.mass_reaction_enabled else "❌"
    else:
        je_status = np_status = mj_status = mi_status = mr_status = "❌"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Компоненты защиты
        [InlineKeyboardButton(
            text=f"{je_status} Частые входы/выходы",
            callback_data=f"ars:je:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"{np_status} Бан по имени",
            callback_data=f"ars:np:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"{mj_status} Массовые вступления",
            callback_data=f"ars:mj:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"{mi_status} Массовые инвайты",
            callback_data=f"ars:mi:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"{mr_status} Массовые реакции",
            callback_data=f"ars:mr:{chat_id}"
        )],
        # Назад к настройкам группы
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"manage_group_{chat_id}"
        )],
    ])

    return keyboard


def create_join_exit_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек компонента Join/Exit.

    Args:
        chat_id: ID чата
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup
    """
    if settings:
        enabled = settings.join_exit_enabled
        action = settings.join_exit_action
        threshold = settings.join_exit_threshold
        window = settings.join_exit_window
        duration = settings.join_exit_ban_duration
    else:
        enabled = False
        action = "ban"
        threshold = 3
        window = 60
        duration = 168

    toggle_text = "Выключить" if enabled else "Включить"
    action_text = {"ban": "Бан", "kick": "Кик", "mute": "Мут"}.get(action, action)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Переключатель
        [InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} {toggle_text}",
            callback_data=f"ars:je:toggle:{chat_id}"
        )],
        # Настройки (только если включён)
        [InlineKeyboardButton(
            text=f"Порог: {threshold} событий",
            callback_data=f"ars:je:threshold:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Окно: {window} сек",
            callback_data=f"ars:je:window:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Действие: {action_text}",
            callback_data=f"ars:je:action:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Длит. бана: {duration}ч" if duration > 0 else "Длит. бана: навсегда",
            callback_data=f"ars:je:duration:{chat_id}"
        )],
        # Назад
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:m:{chat_id}"
        )],
    ])

    return keyboard


def create_name_pattern_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings],
    patterns_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек компонента Name Pattern.

    Args:
        chat_id: ID чата
        settings: Текущие настройки
        patterns_count: Количество паттернов

    Returns:
        InlineKeyboardMarkup
    """
    if settings:
        enabled = settings.name_pattern_enabled
        action = settings.name_pattern_action
        duration = settings.name_pattern_ban_duration
    else:
        enabled = False
        action = "ban"
        duration = 0

    toggle_text = "Выключить" if enabled else "Включить"
    action_text = {"ban": "Бан", "kick": "Кик"}.get(action, action)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Переключатель
        [InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} {toggle_text}",
            callback_data=f"ars:np:toggle:{chat_id}"
        )],
        # Управление паттернами
        [InlineKeyboardButton(
            text=f"Паттерны ({patterns_count})",
            callback_data=f"ars:np:patterns:{chat_id}"
        )],
        # Настройки действия
        [InlineKeyboardButton(
            text=f"Действие: {action_text}",
            callback_data=f"ars:np:action:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Длит. бана: {duration}ч" if duration > 0 else "Длит. бана: навсегда",
            callback_data=f"ars:np:duration:{chat_id}"
        )],
        # Назад
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:m:{chat_id}"
        )],
    ])

    return keyboard


def create_mass_join_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек компонента Mass Join (рейд) v2.

    v2 ИЗМЕНЕНИЯ:
    - Новый режим "protection mode": при детекции рейда банятся ВСЕ новые вступления
    - protection_duration: сколько секунд держать режим защиты
    - ban_duration: длительность бана (0 = навсегда)
    - Дефолтное действие теперь "ban" вместо "slowmode"

    Args:
        chat_id: ID чата
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup
    """
    # ─────────────────────────────────────────────────────────
    # Извлекаем настройки или используем дефолты
    # ─────────────────────────────────────────────────────────
    if settings:
        # Включён ли модуль
        enabled = settings.mass_join_enabled
        # Действие при срабатывании (ban/slowmode/lock/notify)
        action = settings.mass_join_action
        # Порог — количество вступлений за окно для детекции рейда
        threshold = settings.mass_join_threshold
        # Временное окно в секундах
        window = settings.mass_join_window
        # v2: длительность режима защиты в секундах
        protection_duration = settings.mass_join_protection_duration
        # v2: длительность бана в часах (0 = навсегда)
        ban_duration = settings.mass_join_ban_duration
        # Slowmode значение (для action=slowmode)
        slowmode = settings.mass_join_slowmode
        # Авто-снятие в минутах (для action=slowmode/lock)
        auto_unlock = settings.mass_join_auto_unlock
    else:
        # Дефолты если настроек нет
        enabled = False
        action = "ban"
        threshold = 10
        window = 60
        protection_duration = 180
        ban_duration = 0
        slowmode = 60
        auto_unlock = 30

    # ─────────────────────────────────────────────────────────
    # Формируем тексты для кнопок
    # ─────────────────────────────────────────────────────────
    # Текст переключателя
    toggle_text = "Выключить" if enabled else "Включить"
    # Текст действия (человекочитаемый)
    action_text = {
        "ban": "Бан",
        "slowmode": "Slowmode",
        "lock": "Закрыть группу",
        "notify": "Уведомить"
    }.get(action, action)
    # Текст длительности бана
    ban_text = f"Длит. бана: {ban_duration}ч" if ban_duration > 0 else "Длит. бана: навсегда"

    # ─────────────────────────────────────────────────────────
    # Создаём клавиатуру
    # ─────────────────────────────────────────────────────────
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Переключатель включения/выключения модуля
        [InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} {toggle_text}",
            callback_data=f"ars:mj:toggle:{chat_id}"
        )],
        # Порог детекции рейда
        [InlineKeyboardButton(
            text=f"Порог: {threshold} вступлений",
            callback_data=f"ars:mj:threshold:{chat_id}"
        )],
        # Временное окно детекции
        [InlineKeyboardButton(
            text=f"Окно: {window} сек",
            callback_data=f"ars:mj:window:{chat_id}"
        )],
        # Действие при срабатывании
        [InlineKeyboardButton(
            text=f"Действие: {action_text}",
            callback_data=f"ars:mj:action:{chat_id}"
        )],
        # v2: длительность режима защиты (для action=ban)
        [InlineKeyboardButton(
            text=f"Режим защиты: {protection_duration} сек",
            callback_data=f"ars:mj:protection:{chat_id}"
        )],
        # v2: длительность бана (для action=ban)
        [InlineKeyboardButton(
            text=ban_text,
            callback_data=f"ars:mj:banduration:{chat_id}"
        )],
        # Slowmode значение (для action=slowmode)
        [InlineKeyboardButton(
            text=f"Slowmode: {slowmode} сек",
            callback_data=f"ars:mj:slowmode:{chat_id}"
        )],
        # Авто-снятие (для action=slowmode/lock)
        [InlineKeyboardButton(
            text=f"Авто-снятие: {auto_unlock} мин" if auto_unlock > 0 else "Авто-снятие: выкл",
            callback_data=f"ars:mj:autounlock:{chat_id}"
        )],
        # Кнопка назад в главное меню Anti-Raid
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:m:{chat_id}"
        )],
    ])

    return keyboard


def create_mass_invite_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек компонента Mass Invite.

    Args:
        chat_id: ID чата
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup
    """
    if settings:
        enabled = settings.mass_invite_enabled
        action = settings.mass_invite_action
        threshold = settings.mass_invite_threshold
        window = settings.mass_invite_window
        duration = settings.mass_invite_ban_duration
    else:
        enabled = False
        action = "warn"
        threshold = 5
        window = 300
        duration = 24

    toggle_text = "Выключить" if enabled else "Включить"
    action_text = {"warn": "Предупредить", "kick": "Кик", "ban": "Бан", "mute": "Мут"}.get(action, action)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Переключатель
        [InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} {toggle_text}",
            callback_data=f"ars:mi:toggle:{chat_id}"
        )],
        # Настройки детекции
        [InlineKeyboardButton(
            text=f"Порог: {threshold} инвайтов",
            callback_data=f"ars:mi:threshold:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Окно: {window} сек",
            callback_data=f"ars:mi:window:{chat_id}"
        )],
        # Настройки действия
        [InlineKeyboardButton(
            text=f"Действие: {action_text}",
            callback_data=f"ars:mi:action:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=f"Длит. бана: {duration}ч" if duration > 0 else "Длит. бана: навсегда",
            callback_data=f"ars:mi:duration:{chat_id}"
        )],
        # Назад
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:m:{chat_id}"
        )],
    ])

    return keyboard


def create_mass_reaction_keyboard(
    chat_id: int,
    settings: Optional[AntiRaidSettings]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек компонента Mass Reaction v2.

    v2 ИЗМЕНЕНИЯ:
    - Один порог threshold (на сколько РАЗНЫХ сообщений юзер поставил реакции)
    - ban_duration вместо mute_duration (дефолт action = ban)

    Args:
        chat_id: ID чата
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup
    """
    # ─────────────────────────────────────────────────────────
    # Извлекаем настройки или используем дефолты
    # ─────────────────────────────────────────────────────────
    if settings:
        # Включён ли модуль
        enabled = settings.mass_reaction_enabled
        # Действие при срабатывании (ban/kick/mute/warn)
        action = settings.mass_reaction_action
        # v2: порог — на сколько РАЗНЫХ сообщений юзер поставил реакции
        threshold = settings.mass_reaction_threshold
        # Временное окно в секундах
        window = settings.mass_reaction_window
        # v2: длительность бана в часах (0 = навсегда)
        ban_duration = settings.mass_reaction_ban_duration
    else:
        # Дефолты если настроек нет
        enabled = False
        action = "ban"
        threshold = 5
        window = 60
        ban_duration = 0

    # ─────────────────────────────────────────────────────────
    # Формируем тексты для кнопок
    # ─────────────────────────────────────────────────────────
    # Текст переключателя
    toggle_text = "Выключить" if enabled else "Включить"
    # Текст действия (человекочитаемый)
    action_text = {
        "ban": "Бан",
        "kick": "Кик",
        "mute": "Мут",
        "warn": "Предупредить"
    }.get(action, action)
    # Текст длительности бана
    ban_text = f"Длит. бана: {ban_duration}ч" if ban_duration > 0 else "Длит. бана: навсегда"

    # ─────────────────────────────────────────────────────────
    # Создаём клавиатуру
    # ─────────────────────────────────────────────────────────
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Переключатель включения/выключения модуля
        [InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} {toggle_text}",
            callback_data=f"ars:mr:toggle:{chat_id}"
        )],
        # v2: ОДИН порог — разных сообщений за окно
        [InlineKeyboardButton(
            text=f"Порог: {threshold} сообщений",
            callback_data=f"ars:mr:threshold:{chat_id}"
        )],
        # Временное окно в секундах
        [InlineKeyboardButton(
            text=f"Окно: {window} сек",
            callback_data=f"ars:mr:window:{chat_id}"
        )],
        # Действие при срабатывании
        [InlineKeyboardButton(
            text=f"Действие: {action_text}",
            callback_data=f"ars:mr:action:{chat_id}"
        )],
        # v2: длительность бана (только для action=ban)
        [InlineKeyboardButton(
            text=ban_text,
            callback_data=f"ars:mr:duration:{chat_id}"
        )],
        # Кнопка назад в главное меню Anti-Raid
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:m:{chat_id}"
        )],
    ])

    return keyboard


def create_action_selection_keyboard(
    chat_id: int,
    component: str,
    available_actions: List[str]
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора действия.

    Args:
        chat_id: ID чата
        component: Код компонента (je, np, mj, mi, mr)
        available_actions: Список доступных действий

    Returns:
        InlineKeyboardMarkup
    """
    action_names = {
        "warn": "Предупредить",
        "mute": "Мут",
        "kick": "Кик",
        "ban": "Бан",
        "slowmode": "Slowmode",
        "lock": "Закрыть группу",
        "notify": "Только уведомить",
    }

    buttons = []
    for action in available_actions:
        buttons.append([InlineKeyboardButton(
            text=action_names.get(action, action),
            callback_data=f"ars:{component}:setaction:{action}:{chat_id}"
        )])

    # Кнопка отмены
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"ars:{component}:{chat_id}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_value_selection_keyboard(
    chat_id: int,
    component: str,
    param: str,
    values: List[int],
    unit: str = ""
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора числового значения.

    v2: Добавлена кнопка "Своё значение" для ввода произвольного числа.

    Args:
        chat_id: ID чата
        component: Код компонента
        param: Код параметра
        values: Список предустановленных значений для быстрого выбора
        unit: Единица измерения (для отображения)

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    # Группируем по 3 кнопки в ряд
    row = []
    for value in values:
        # Специальный текст для нулевого значения
        if value == 0:
            text = "Навсегда" if "duration" in param else "Выкл"
        else:
            text = f"{value}{unit}"

        # Добавляем кнопку выбора значения
        row.append(InlineKeyboardButton(
            text=text,
            callback_data=f"ars:{component}:set{param}:{value}:{chat_id}"
        ))

        # Переносим на новую строку каждые 3 кнопки
        if len(row) == 3:
            buttons.append(row)
            row = []

    # Добавляем остаток если есть
    if row:
        buttons.append(row)

    # v2: Кнопка для ввода произвольного значения
    buttons.append([InlineKeyboardButton(
        text="✏️ Своё значение",
        callback_data=f"ars:{component}:custom{param}:{chat_id}"
    )])

    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"ars:{component}:{chat_id}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_patterns_list_keyboard(
    chat_id: int,
    patterns: List[AntiRaidNamePattern],
    page: int = 0,
    per_page: int = 5
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру списка паттернов с пагинацией.

    Args:
        chat_id: ID чата
        patterns: Список паттернов
        page: Текущая страница (0-indexed)
        per_page: Паттернов на страницу

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    # Вычисляем срез для текущей страницы
    start = page * per_page
    end = start + per_page
    page_patterns = patterns[start:end]
    total_pages = (len(patterns) + per_page - 1) // per_page

    # Добавляем паттерны
    for pattern in page_patterns:
        status = "✅" if pattern.is_enabled else "❌"
        text = f"{status} {pattern.pattern[:20]}{'...' if len(pattern.pattern) > 20 else ''}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"ars:np:pattern:{pattern.id}:{chat_id}"
        )])

    # Пагинация
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text="« Пред",
                callback_data=f"ars:np:plist:{page-1}:{chat_id}"
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"{page+1}/{total_pages}",
            callback_data="ars:noop"
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="След »",
                callback_data=f"ars:np:plist:{page+1}:{chat_id}"
            ))
        buttons.append(nav_row)

    # Добавить паттерн
    buttons.append([InlineKeyboardButton(
        text="+ Добавить паттерн",
        callback_data=f"ars:np:addpat:{chat_id}"
    )])

    # Назад
    buttons.append([InlineKeyboardButton(
        text="« Назад",
        callback_data=f"ars:np:{chat_id}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_pattern_edit_keyboard(
    chat_id: int,
    pattern: AntiRaidNamePattern
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру редактирования паттерна.

    Args:
        chat_id: ID чата
        pattern: Паттерн для редактирования

    Returns:
        InlineKeyboardMarkup
    """
    toggle_text = "Выключить" if pattern.is_enabled else "Включить"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if pattern.is_enabled else '❌'} {toggle_text}",
            callback_data=f"ars:np:ptoggle:{pattern.id}:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"ars:np:pdel:{pattern.id}:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"ars:np:patterns:{chat_id}"
        )],
    ])

    return keyboard
