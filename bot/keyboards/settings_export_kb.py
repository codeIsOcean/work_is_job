# ============================================================
# КЛАВИАТУРЫ ДЛЯ ЭКСПОРТА/ИМПОРТА НАСТРОЕК
# ============================================================
# Этот модуль содержит все inline клавиатуры для:
# - Выбора группы для экспорта/импорта
# - Подтверждения экспорта/импорта
# - Отмены операций
# ============================================================

# Импортируем типы для клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импортируем typing для аннотаций
from typing import List, Any, Set


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ЭКСПОРТА
# ============================================================

def create_export_groups_keyboard(groups: List[Any]) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру со списком групп для экспорта.

    Каждая кнопка содержит название группы и callback_data с chat_id.

    Args:
        groups: Список групп (объекты с chat_id и title)

    Returns:
        InlineKeyboardMarkup с кнопками групп
    """
    # Создаём список кнопок (каждая кнопка в отдельном ряду)
    buttons = []

    for group in groups:
        # Получаем название группы
        title = getattr(group, 'title', None) or f"Группа {group.chat_id}"

        # Ограничиваем длину названия (максимум 30 символов)
        if len(title) > 30:
            title = title[:27] + "..."

        # Создаём кнопку с callback_data содержащим chat_id
        button = InlineKeyboardButton(
            text=f"📤 {title}",
            callback_data=f"export_select:{group.chat_id}",
        )

        # Добавляем кнопку как отдельный ряд
        buttons.append([button])

    # Добавляем кнопку отмены в конце
    buttons.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="export_cancel")
    ])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_export_confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру подтверждения экспорта.

    Args:
        chat_id: ID группы для экспорта

    Returns:
        InlineKeyboardMarkup с кнопками подтверждения и отмены
    """
    # Создаём кнопки
    buttons = [
        # Первый ряд: кнопка подтверждения
        [
            InlineKeyboardButton(
                text="✅ Экспортировать",
                callback_data=f"export_confirm:{chat_id}",
            )
        ],
        # Второй ряд: кнопка назад к настройкам группы
        [
            InlineKeyboardButton(
                text="🔙 Назад к настройкам",
                callback_data=f"export_back:{chat_id}",
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ИМПОРТА
# ============================================================

def create_import_groups_keyboard(groups: List[Any]) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру со списком групп для импорта.

    Каждая кнопка содержит название группы и callback_data с chat_id.

    Args:
        groups: Список групп (объекты с chat_id и title)

    Returns:
        InlineKeyboardMarkup с кнопками групп
    """
    # Создаём список кнопок (каждая кнопка в отдельном ряду)
    buttons = []

    for group in groups:
        # Получаем название группы
        title = getattr(group, 'title', None) or f"Группа {group.chat_id}"

        # Ограничиваем длину названия (максимум 30 символов)
        if len(title) > 30:
            title = title[:27] + "..."

        # Создаём кнопку с callback_data содержащим chat_id
        button = InlineKeyboardButton(
            text=f"📥 {title}",
            callback_data=f"import_select:{group.chat_id}",
        )

        # Добавляем кнопку как отдельный ряд
        buttons.append([button])

    # Добавляем кнопку отмены в конце
    buttons.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="import_cancel")
    ])

    # Возвращаем клавиатуру
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_import_type_select_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру выбора типа импорта.

    Показывает два варианта:
    - Импорт в текущую группу
    - Массовый импорт во все группы

    Args:
        chat_id: ID текущей группы

    Returns:
        InlineKeyboardMarkup с кнопками выбора
    """
    buttons = [
        [
            InlineKeyboardButton(
                text="📥 В эту группу",
                callback_data=f"import_single:{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="📤 Массовый импорт",
                callback_data="import_mass",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"import_back:{chat_id}",
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_import_confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру подтверждения импорта.

    Args:
        chat_id: ID группы для импорта

    Returns:
        InlineKeyboardMarkup с кнопками подтверждения и отмены
    """
    # Создаём кнопки
    buttons = [
        # Первый ряд: кнопка подтверждения
        [
            InlineKeyboardButton(
                text="✅ Импортировать",
                callback_data=f"import_confirm:{chat_id}",
            )
        ],
        # Второй ряд: кнопка назад к настройкам группы (через FSM-aware callback)
        [
            InlineKeyboardButton(
                text="🔙 Назад к настройкам",
                callback_data=f"import_back:{chat_id}",
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# ОБЩИЕ КЛАВИАТУРЫ
# ============================================================

def create_cancel_keyboard(chat_id: int = None) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой отмены/назад.

    Используется когда FSM ожидает ввода от пользователя.

    Args:
        chat_id: ID группы для возврата к настройкам (опционально)

    Returns:
        InlineKeyboardMarkup с кнопкой отмены
    """
    if chat_id:
        # Если есть chat_id - кнопка возврата к настройкам (через FSM-aware callback)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад к настройкам",
                    callback_data=f"import_back:{chat_id}",
                )]
            ]
        )
    else:
        # Без chat_id - просто отмена
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="import_cancel")]
            ]
        )


# ============================================================
# КНОПКИ ДЛЯ МЕНЮ НАСТРОЕК ГРУППЫ
# ============================================================

def get_export_import_buttons(chat_id: int) -> List[List[InlineKeyboardButton]]:
    """
    Возвращает кнопки экспорта/импорта для добавления в меню настроек группы.

    Эти кнопки можно добавить в существующую клавиатуру настроек группы.

    Args:
        chat_id: ID группы

    Returns:
        Список рядов кнопок для добавления в клавиатуру
    """
    return [
        # Ряд с кнопками экспорта и импорта
        [
            InlineKeyboardButton(
                text="📤 Экспорт",
                callback_data=f"export_select:{chat_id}",
            ),
            InlineKeyboardButton(
                text="📥 Импорт",
                callback_data=f"import_select:{chat_id}",
            ),
        ],
    ]


# ============================================================
# КЛАВИАТУРА ВЫБОРА ГРУПП ДЛЯ МАССОВОГО ИМПОРТА
# ============================================================

def create_import_result_keyboard(chat_id: int = None) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для экрана результатов импорта.

    Args:
        chat_id: ID группы для возврата к настройкам (опционально)

    Returns:
        InlineKeyboardMarkup с кнопкой назад
    """
    if chat_id:
        # Кнопка возврата к настройкам группы
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад к настройкам",
                    callback_data=f"import_back:{chat_id}",
                )]
            ]
        )
    else:
        # Просто информационное сообщение без кнопки
        return InlineKeyboardMarkup(inline_keyboard=[])


def create_multi_group_select_keyboard(
    groups: List[Any],
    selected_ids: Set[int],
    origin_chat_id: int = None,
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с галочками для выбора нескольких групп.

    Используется для массового импорта настроек во все выбранные группы.

    Args:
        groups: Список групп (объекты с chat_id и title)
        selected_ids: Множество chat_id выбранных групп

    Returns:
        InlineKeyboardMarkup с галочками и кнопками управления
    """
    buttons = []

    # Кнопки групп с галочками
    for group in groups:
        chat_id = group.chat_id
        title = getattr(group, 'title', None) or f"Группа {chat_id}"

        # Ограничиваем длину названия (максимум 25 символов из-за галочки)
        if len(title) > 25:
            title = title[:22] + "..."

        # Определяем статус галочки
        is_selected = chat_id in selected_ids
        checkbox = "✅" if is_selected else "⬜"

        # Создаём кнопку
        button = InlineKeyboardButton(
            text=f"{checkbox} {title}",
            callback_data=f"import_toggle:{chat_id}",
        )
        buttons.append([button])

    # Разделитель (пустая строка через текст)
    # Кнопки "Выбрать все" / "Снять все"
    all_selected = len(selected_ids) == len(groups) and len(groups) > 0
    buttons.append([
        InlineKeyboardButton(
            text="☑️ Выбрать все" if not all_selected else "✅ Все выбраны",
            callback_data="import_select_all",
        ),
        InlineKeyboardButton(
            text="⬜ Снять все",
            callback_data="import_deselect_all",
        ),
    ])

    # Кнопка импорта с количеством выбранных групп
    selected_count = len(selected_ids)
    import_text = f"📤 Импортировать ({selected_count})" if selected_count > 0 else "📤 Выберите группы"

    buttons.append([
        InlineKeyboardButton(
            text=import_text,
            callback_data="import_execute",
        ),
    ])

    # Кнопка назад/отмены (если есть origin_chat_id - возврат к настройкам)
    if origin_chat_id:
        buttons.append([
            InlineKeyboardButton(
                text="🔙 Назад к настройкам",
                callback_data=f"import_back:{origin_chat_id}",
            ),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="import_cancel",
            ),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
