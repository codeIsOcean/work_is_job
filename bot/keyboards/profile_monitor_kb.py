# bot/keyboards/profile_monitor_kb.py
"""
Клавиатуры для модуля Profile Monitor.

Содержит:
- Клавиатуры для уведомлений в журнале
- Клавиатуры для настроек в ЛС
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# КЛАВИАТУРА: ДЕЙСТВИЯ В ЖУРНАЛЕ
# ============================================================
def get_journal_action_kb(
    chat_id: int,
    user_id: int,
    log_id: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура для действий в журнале при обнаружении изменения профиля.

    Кнопки:
    - Мут | Бан | Кик
    - Отправить в группу | ОК

    Args:
        chat_id: ID группы
        user_id: ID пользователя
        log_id: ID записи в журнале (для отслеживания)

    Returns:
        InlineKeyboardMarkup с кнопками действий
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Первая строка: Модерация
            [
                InlineKeyboardButton(
                    text="🔇 Мут",
                    callback_data=f"pm_mute:{chat_id}:{user_id}:{log_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"pm_ban:{chat_id}:{user_id}:{log_id}"
                ),
                InlineKeyboardButton(
                    text="👢 Кик",
                    callback_data=f"pm_kick:{chat_id}:{user_id}:{log_id}"
                ),
            ],
            # Вторая строка: Отправка и подтверждение
            [
                InlineKeyboardButton(
                    text="📢 В группу",
                    callback_data=f"pm_send_group:{chat_id}:{user_id}:{log_id}"
                ),
                InlineKeyboardButton(
                    text="✅ ОК",
                    callback_data=f"pm_ok:{chat_id}:{user_id}:{log_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: ПОСЛЕ АВТОМУТА
# ============================================================
def get_auto_mute_kb(
    chat_id: int,
    user_id: int,
    log_id: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура после автоматического мута.

    Кнопки:
    - Размут | Бан
    - Отправить в группу | ОК

    Args:
        chat_id: ID группы
        user_id: ID пользователя
        log_id: ID записи в журнале

    Returns:
        InlineKeyboardMarkup
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Первая строка: Отмена или усиление
            [
                InlineKeyboardButton(
                    text="🔊 Размут",
                    callback_data=f"pm_unmute:{chat_id}:{user_id}:{log_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"pm_ban:{chat_id}:{user_id}:{log_id}"
                ),
            ],
            # Вторая строка: Отправка и подтверждение
            [
                InlineKeyboardButton(
                    text="📢 В группу",
                    callback_data=f"pm_send_group:{chat_id}:{user_id}:{log_id}"
                ),
                InlineKeyboardButton(
                    text="✅ ОК",
                    callback_data=f"pm_ok:{chat_id}:{user_id}:{log_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: CRITERION_6 (ЗАПРЕЩЁННЫЙ КОНТЕНТ В ПРОФИЛЕ)
# ============================================================
def get_criterion6_kb(
    chat_id: int,
    user_id: int,
    log_id: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура для журнала при срабатывании CRITERION_6.

    CRITERION_6 срабатывает когда в имени или bio пользователя
    обнаружено запрещённое слово (harmful/obfuscated категории).

    Кнопки:
    - Анмут | Мут 7д | Мут ∞
    - Бан (заглушка) | Анбан (заглушка) | ОК

    Args:
        chat_id: ID группы где сработал критерий
        user_id: ID пользователя с запрещённым контентом
        log_id: ID записи в журнале (для отслеживания действий)

    Returns:
        InlineKeyboardMarkup с кнопками модерации
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Первая строка: Управление мутом
            [
                # Кнопка размута - снимает ограничения с пользователя
                InlineKeyboardButton(
                    text="🔊 Анмут",
                    callback_data=f"pm_unmute:{chat_id}:{user_id}:{log_id}"
                ),
                # Кнопка мута на 7 дней
                InlineKeyboardButton(
                    text="🔇 Мут 7д",
                    callback_data=f"pm_mute7d:{chat_id}:{user_id}:{log_id}"
                ),
                # Кнопка мута навсегда
                InlineKeyboardButton(
                    text="🔇 Мут ∞",
                    callback_data=f"pm_mute_forever:{chat_id}:{user_id}:{log_id}"
                ),
            ],
            # Вторая строка: Бан/Анбан (заглушки) и подтверждение
            [
                # Кнопка бана - пока заглушка
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"pm_ban:{chat_id}:{user_id}:{log_id}"
                ),
                # Кнопка разбана - пока заглушка
                InlineKeyboardButton(
                    text="🔓 Анбан",
                    callback_data=f"pm_unban:{chat_id}:{user_id}:{log_id}"
                ),
                # Кнопка подтверждения - просто убирает кнопки
                InlineKeyboardButton(
                    text="✅ ОК",
                    callback_data=f"pm_ok:{chat_id}:{user_id}:{log_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: НАСТРОЙКИ МОДУЛЯ В ЛС
# ============================================================
def get_settings_main_kb(
    chat_id: int,
    enabled: bool,
) -> InlineKeyboardMarkup:
    """
    Главная клавиатура настроек Profile Monitor.

    Args:
        chat_id: ID группы
        enabled: Включён ли модуль

    Returns:
        InlineKeyboardMarkup
    """
    # Текст кнопки включения/выключения
    toggle_text = "🔴 Выключить" if enabled else "🟢 Включить"
    toggle_value = "off" if enabled else "on"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Переключатель модуля
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"pm_toggle:{toggle_value}:{chat_id}"
                ),
            ],
            # Настройки логирования
            [
                InlineKeyboardButton(
                    text="📝 Настройки логирования",
                    callback_data=f"pm_settings_log:{chat_id}"
                ),
            ],
            # Настройки автомута
            [
                InlineKeyboardButton(
                    text="⚡ Настройки автомута",
                    callback_data=f"pm_settings_mute:{chat_id}"
                ),
            ],
            # Назад к меню настроек группы
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"manage_group_{chat_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: НАСТРОЙКИ ЛОГИРОВАНИЯ
# ============================================================
def get_log_settings_kb(
    chat_id: int,
    log_name: bool,
    log_username: bool,
    log_photo: bool,
    send_to_journal: bool,
    send_to_group: bool,
) -> InlineKeyboardMarkup:
    """
    Клавиатура настроек логирования.

    Args:
        chat_id: ID группы
        log_name: Логировать имена
        log_username: Логировать username
        log_photo: Логировать фото
        send_to_journal: Отправлять в журнал (для админов)
        send_to_group: Отправлять простые уведомления в группу (для всех)

    Returns:
        InlineKeyboardMarkup
    """
    # Формируем иконки состояния для каждой опции
    name_icon = "✅" if log_name else "❌"
    username_icon = "✅" if log_username else "❌"
    photo_icon = "✅" if log_photo else "❌"
    journal_icon = "✅" if send_to_journal else "❌"
    # Иконка для отправки в группу (новая опция)
    group_icon = "✅" if send_to_group else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Кнопка: логирование имён
            [
                InlineKeyboardButton(
                    text=f"{name_icon} Имена",
                    callback_data=f"pm_log_name:{'off' if log_name else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка: логирование username
            [
                InlineKeyboardButton(
                    text=f"{username_icon} Username",
                    callback_data=f"pm_log_username:{'off' if log_username else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка: логирование фото
            [
                InlineKeyboardButton(
                    text=f"{photo_icon} Фото",
                    callback_data=f"pm_log_photo:{'off' if log_photo else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка: отправка в журнал (для админов)
            [
                InlineKeyboardButton(
                    text=f"{journal_icon} В журнал (админам)",
                    callback_data=f"pm_send_journal:{'off' if send_to_journal else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка: отправка в группу (для всех участников)
            # Простые уведомления: "Пользователь X сменил имя на Y"
            [
                InlineKeyboardButton(
                    text=f"{group_icon} В группу (всем)",
                    callback_data=f"pm_send_grp:{'off' if send_to_group else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка назад к главному меню настроек
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"pm_settings_main:{chat_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: НАСТРОЙКИ АВТОМУТА
# ============================================================
def get_mute_settings_kb(
    chat_id: int,
    auto_mute_young: bool,
    auto_mute_name_change: bool,
    delete_messages: bool,
    account_age_days: int,
    photo_freshness_threshold_days: int = 1,
    auto_mute_forbidden_content: bool = False,
    check_profile_photo_filter: bool = False,
) -> InlineKeyboardMarkup:
    """
    Клавиатура настроек автомута.

    Args:
        chat_id: ID группы
        auto_mute_young: Автомут молодых аккаунтов без фото
        auto_mute_name_change: Автомут при смене имени
        delete_messages: Удалять сообщения
        account_age_days: Порог возраста аккаунта
        photo_freshness_threshold_days: Порог свежести фото для критериев 4,5
        auto_mute_forbidden_content: Автомут за запрещённый контент в имени/bio
        check_profile_photo_filter: Проверка фото профиля через Scam Media Filter

    Returns:
        InlineKeyboardMarkup
    """
    # Иконки состояния
    young_icon = "✅" if auto_mute_young else "❌"
    name_icon = "✅" if auto_mute_name_change else "❌"
    delete_icon = "✅" if delete_messages else "❌"
    content_icon = "✅" if auto_mute_forbidden_content else "❌"
    # Иконка для проверки фото профиля
    photo_filter_icon = "✅" if check_profile_photo_filter else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Критерий: нет фото + молодой аккаунт
            [
                InlineKeyboardButton(
                    text=f"{young_icon} Мут: нет фото + молодой аккаунт",
                    callback_data=f"pm_mute_young:{'off' if auto_mute_young else 'on'}:{chat_id}"
                ),
            ],
            # Порог возраста аккаунта
            [
                InlineKeyboardButton(
                    text=f"📅 Порог аккаунта: {account_age_days} дней",
                    callback_data=f"pm_age_threshold:{chat_id}"
                ),
            ],
            # Порог свежести фото (для критериев 4,5)
            [
                InlineKeyboardButton(
                    text=f"📸 Порог фото: {photo_freshness_threshold_days} дней",
                    callback_data=f"pm_photo_fresh_threshold:{chat_id}"
                ),
            ],
            # Критерий: смена имени + быстрые сообщения
            [
                InlineKeyboardButton(
                    text=f"{name_icon} Мут: смена имени + быстрые сообщения",
                    callback_data=f"pm_mute_name:{'off' if auto_mute_name_change else 'on'}:{chat_id}"
                ),
            ],
            # Удаление сообщений
            [
                InlineKeyboardButton(
                    text=f"{delete_icon} Удалять сообщения спаммеров",
                    callback_data=f"pm_delete_msgs:{'off' if delete_messages else 'on'}:{chat_id}"
                ),
            ],
            # Критерий 6: запрещённый контент в имени/bio
            [
                InlineKeyboardButton(
                    text=f"{content_icon} Мут: запрещённый контент в имени/bio",
                    callback_data=f"pm_mute_content:{'off' if auto_mute_forbidden_content else 'on'}:{chat_id}"
                ),
            ],
            # Проверка фото профиля через Scam Media Filter
            [
                InlineKeyboardButton(
                    text=f"{photo_filter_icon} Проверка фото на скам-фильтр",
                    callback_data=f"pm_photo_filter:{'off' if check_profile_photo_filter else 'on'}:{chat_id}"
                ),
            ],
            # Кнопка назад
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"pm_settings_main:{chat_id}"
                ),
            ],
        ]
    )


# ============================================================
# КЛАВИАТУРА: ВЫБОР ПОРОГА ВОЗРАСТА
# ============================================================
def get_age_threshold_kb(
    chat_id: int,
    current_days: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора порога возраста аккаунта.

    Args:
        chat_id: ID группы
        current_days: Текущий порог в днях

    Returns:
        InlineKeyboardMarkup
    """
    # Варианты порогов
    options = [7, 15, 30, 60, 90]

    buttons = []
    for days in options:
        # Отмечаем текущий выбор
        icon = "✅" if days == current_days else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {days} дней",
                callback_data=f"pm_set_age:{days}:{chat_id}"
            )
        ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"pm_settings_mute:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# КЛАВИАТУРА: ВЫБОР ПОРОГА СВЕЖЕСТИ ФОТО
# ============================================================
def get_photo_freshness_threshold_kb(
    chat_id: int,
    current_days: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора порога свежести фото.

    Используется для критериев автомута 4 и 5:
    - Критерий 4: Свежее фото + смена имени + сообщение ≤30 мин
    - Критерий 5: Свежее фото + сообщение ≤30 мин

    Фото считается "свежим" если его возраст меньше выбранного порога.

    Args:
        chat_id: ID группы
        current_days: Текущий порог в днях

    Returns:
        InlineKeyboardMarkup с вариантами порогов
    """
    # Варианты порогов свежести фото (в днях)
    options = [1, 3, 7, 14]

    buttons = []
    for days in options:
        # Отмечаем текущий выбор галочкой
        icon = "✅" if days == current_days else ""
        # Формируем текст кнопки с правильным склонением
        if days == 1:
            day_text = "день"
        else:
            day_text = "дней"
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {days} {day_text}",
                callback_data=f"pm_set_photo_fresh:{days}:{chat_id}"
            )
        ])

    # Кнопка назад к настройкам автомута
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"pm_settings_mute:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
