# ============================================================
# КЛАВИАТУРЫ ДЛЯ МОДУЛЯ CONTENT FILTER
# ============================================================
# Этот модуль содержит все inline клавиатуры для настройки фильтра контента:
# - Главное меню модуля
# - Настройки подмодулей (word_filter, scam, flood)
# - Управление запрещёнными словами
# - Выбор чувствительности и действий
#
# ВАЖНО: Используем короткие callback_data из-за лимита Telegram в 64 байта!
# Схема сокращений:
# - cf = content_filter (главный префикс)
# - m = main_menu, s = settings, w = words
# - t = toggle, a = action, sens = sensitivity
# ============================================================

# Импорт типов для создания клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# Импорт типов для аннотаций
from typing import Optional, List

# Импорт модели настроек для получения текущих значений
from bot.database.models_content_filter import ContentFilterSettings


# ============================================================
# ЭМОДЗИ ДЛЯ СТАТУСОВ
# ============================================================
# Используем для визуального отображения вкл/выкл

# Включено
EMOJI_ON = "✅"
# Выключено
EMOJI_OFF = "❌"
# Настройки
EMOJI_SETTINGS = "⚙️"
# Слова
EMOJI_WORDS = "🔤"
# Статистика
EMOJI_STATS = "📊"
# Назад
EMOJI_BACK = "◀️"
# Добавить
EMOJI_ADD = "➕"
# Список
EMOJI_LIST = "📋"
# Удалить
EMOJI_DELETE = "🗑️"
# Чувствительность
EMOJI_SENS_HIGH = "🔴"
EMOJI_SENS_MEDIUM = "🟡"
EMOJI_SENS_LOW = "🟢"
# Паттерны скама
EMOJI_PATTERNS = "🎯"
EMOJI_IMPORT = "📥"
EMOJI_EXPORT = "📤"
EMOJI_ANALYZE = "🔍"


# ============================================================
# ГЛАВНОЕ МЕНЮ CONTENT FILTER
# ============================================================

def create_content_filter_main_menu(
    chat_id: int,
    settings: Optional[ContentFilterSettings] = None
) -> InlineKeyboardMarkup:
    """
    Создаёт главное меню модуля content_filter.

    НОВАЯ СТРУКТУРА (по схеме пользователя):
    - Фильтр слов ✅/❌ == настройки
    - Антискам ✅/❌ == настройки
    - Антифлуд ✅/❌ == настройки
    - Статистика
    - Включить модуль ✅/❌

    Args:
        chat_id: ID группы для формирования callback_data
        settings: Текущие настройки (для отображения статуса)

    Returns:
        InlineKeyboardMarkup: Клавиатура главного меню

    Callback format: cf:{action}:{chat_id}
    """
    # Определяем статусы подмодулей
    word_status = EMOJI_ON if settings and settings.word_filter_enabled else EMOJI_OFF
    scam_status = EMOJI_ON if settings and settings.scam_detection_enabled else EMOJI_OFF
    flood_status = EMOJI_ON if settings and settings.flood_detection_enabled else EMOJI_OFF
    # Кросс-сообщение детекция
    cross_msg_status = EMOJI_ON if settings and getattr(settings, 'cross_message_enabled', False) else EMOJI_OFF

    # Определяем текст кнопки включения/выключения модуля
    if settings and settings.enabled:
        toggle_text = f"{EMOJI_ON} Модуль включён"
        toggle_action = "off"
    else:
        toggle_text = f"{EMOJI_OFF} Модуль выключен"
        toggle_action = "on"

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Фильтр слов (toggle + настройки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔤 Фильтр слов {word_status}",
                    callback_data=f"cf:t:wf:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:wfs:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Антискам (toggle + настройки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🎯 Антискам {scam_status}",
                    callback_data=f"cf:t:sc:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:scs:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Антифлуд (toggle + настройки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🌊 Антифлуд {flood_status}",
                    callback_data=f"cf:t:fl:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:fls:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3.5: Кросс-сообщение детекция (toggle + настройки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📊 Кросс-сообщение {cross_msg_status}",
                    callback_data=f"cf:t:cm:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:cms:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Скам-изображения (переход в отдельный модуль)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🖼️ Скам-изображения",
                    callback_data=f"sm:settings:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 5: Статистика
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_STATS} Статистика",
                    callback_data=f"cf:stats:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 6: Включить/Выключить модуль
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"cf:t:{toggle_action}:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 7: Назад к основным настройкам группы
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"manage_group_{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ НАСТРОЕК ПОДМОДУЛЕЙ
# ============================================================

def create_content_filter_settings_menu(
    chat_id: int,
    settings: ContentFilterSettings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек подмодулей.

    Позволяет включать/выключать отдельные детекторы:
    - Фильтр слов
    - Антискам
    - Антифлуд

    Args:
        chat_id: ID группы
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек
    """
    # Формируем текст для каждого подмодуля с текущим статусом
    word_status = EMOJI_ON if settings.word_filter_enabled else EMOJI_OFF
    scam_status = EMOJI_ON if settings.scam_detection_enabled else EMOJI_OFF
    flood_status = EMOJI_ON if settings.flood_detection_enabled else EMOJI_OFF

    # Формируем текст раздельных действий
    action_map = {
        'delete': '🗑️ Удалить',
        'warn': '⚠️ Предупредить',
        'mute': '🔇 Мут',
        'kick': '👢 Кик',
        'ban': '🚫 Бан'
    }
    # Если NULL — используется default, показываем "(общее)"
    word_action = settings.word_filter_action if settings.word_filter_action else None
    word_action_text = action_map.get(word_action, '(общее)') if word_action else '(общее)'

    flood_action = settings.flood_action if settings.flood_action else None
    flood_action_text = action_map.get(flood_action, '(общее)') if flood_action else '(общее)'

    # Формируем текст нормализатора
    normalize_status = EMOJI_ON if settings.word_filter_normalize else EMOJI_OFF

    # Формируем текст логирования
    log_status = EMOJI_ON if settings.log_violations else EMOJI_OFF

    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Фильтр слов (с кнопкой действия и нормализатора)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Фильтр слов {word_status}",
                    callback_data=f"cf:t:wf:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"⚡{word_action_text[:3]}",
                    callback_data=f"cf:wact:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"📝{normalize_status}",
                    callback_data=f"cf:wnorm:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Антискам (с кнопкой настроек)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Антискам {scam_status}",
                    callback_data=f"cf:t:sc:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:scs:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Антифлуд (с доп. кнопками настроек и действия)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Антифлуд {flood_status}",
                    callback_data=f"cf:t:fl:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_SETTINGS}",
                    callback_data=f"cf:fls:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"⚡{flood_action_text[:3]}",
                    callback_data=f"cf:fact:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Разделитель
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="─────────────────",
                    callback_data="cf:noop"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Логирование
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Логирование {log_status}",
                    callback_data=f"cf:t:log:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 5: Удаление сообщений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🗑️ Удаление сообщений",
                    callback_data=f"cf:cleanup:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 6: Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ НАСТРОЕК ФИЛЬТРА СЛОВ (3 КАТЕГОРИИ)
# ============================================================

def create_word_filter_settings_menu(
    chat_id: int,
    settings: ContentFilterSettings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек фильтра слов с 3 категориями:
    - Простые слова (реклама, спам) - по умолчанию: удалить
    - Вредные слова (наркотики) - по умолчанию: бан
    - Обфускация (l33tspeak) - по умолчанию: мут

    Каждая категория имеет:
    - Переключатель вкл/выкл
    - Список слов
    - Настройки действия

    Args:
        chat_id: ID группы
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек фильтра слов
    """
    # Статусы категорий (используем новые поля или дефолт True)
    simple_status = EMOJI_ON if getattr(settings, 'simple_words_enabled', True) else EMOJI_OFF
    harmful_status = EMOJI_ON if getattr(settings, 'harmful_words_enabled', True) else EMOJI_OFF
    obfuscated_status = EMOJI_ON if getattr(settings, 'obfuscated_words_enabled', True) else EMOJI_OFF

    # Действия для категорий
    action_map = {
        'delete': '🗑️',
        'warn': '⚠️',
        'mute': '🔇',
        'kick': '👢',
        'ban': '🚫'
    }
    simple_action = getattr(settings, 'simple_words_action', 'delete') or 'delete'
    harmful_action = getattr(settings, 'harmful_words_action', 'ban') or 'ban'
    obfuscated_action = getattr(settings, 'obfuscated_words_action', 'mute') or 'mute'

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Категория 1: Простые слова (реклама, спам)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📝 Простые {simple_status}",
                    callback_data=f"cf:t:sw:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_LIST}",
                    callback_data=f"cf:swl:{chat_id}:0"
                ),
                InlineKeyboardButton(
                    text=f"{action_map.get(simple_action, '🗑️')}",
                    callback_data=f"cf:swa:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Категория 2: Вредные слова (наркотики)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"💊 Вредные {harmful_status}",
                    callback_data=f"cf:t:hw:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_LIST}",
                    callback_data=f"cf:hwl:{chat_id}:0"
                ),
                InlineKeyboardButton(
                    text=f"{action_map.get(harmful_action, '🚫')}",
                    callback_data=f"cf:hwa:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Категория 3: Обфускация (l33tspeak)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔀 Обфускация {obfuscated_status}",
                    callback_data=f"cf:t:ow:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_LIST}",
                    callback_data=f"cf:owl:{chat_id}:0"
                ),
                InlineKeyboardButton(
                    text=f"{action_map.get(obfuscated_action, '🔇')}",
                    callback_data=f"cf:owa:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад к главному меню
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ ДЛЯ КАТЕГОРИИ СЛОВ
# ============================================================

def create_category_action_menu(
    chat_id: int,
    category: str,
    current_action: str = None,
    current_duration: int = None,
    mute_text: str = None,
    notification_delay: int = None
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для категории слов.

    Действия с ручным вводом времени:
    - Удалить (+ опциональная задержка)
    - Мут (+ ручной ввод времени)
    - Бан (+ ручной ввод времени)
    - Кастомный текст мута (%user%, %time%)
    - Задержка удаления уведомления

    Args:
        chat_id: ID группы
        category: Категория (sw=simple, hw=harmful, ow=obfuscated)
        current_action: Текущее действие
        current_duration: Текущая длительность (в минутах)
        mute_text: Кастомный текст мута или None
        notification_delay: Задержка удаления уведомления в секундах или None

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Формируем текст длительности
    duration_text = ""
    if current_duration:
        if current_duration < 60:
            duration_text = f" ({current_duration}мин)"
        elif current_duration < 1440:
            duration_text = f" ({current_duration // 60}ч)"
        else:
            duration_text = f" ({current_duration // 1440}д)"

    # Галочки
    delete_check = " ✓" if current_action == 'delete' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Только удалить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🗑️ Только удалить{delete_check}",
                    callback_data=f"cf:{category}a:delete:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Мут + ручной ввод времени
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔇 Мут{mute_check}{duration_text if current_action == 'mute' else ''}",
                    callback_data=f"cf:{category}a:mute:{chat_id}"
                ),
                InlineKeyboardButton(
                    text="⏱️",
                    callback_data=f"cf:{category}t:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Бан + ручной ввод времени
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🚫 Бан{ban_check}{duration_text if current_action == 'ban' else ''}",
                    callback_data=f"cf:{category}a:ban:{chat_id}"
                ),
                InlineKeyboardButton(
                    text="⏱️",
                    callback_data=f"cf:{category}bt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Кастомный текст мута
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📝 Текст мута: {'✅' if mute_text else '❌'}",
                    callback_data=f"cf:{category}mt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Задержка удаления уведомления
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⏰ Удалять уведомление: {f'{notification_delay}с' if notification_delay else 'Нет'}",
                    callback_data=f"cf:{category}nd:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:wfs:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ НАСТРОЕК АНТИСКАМА
# ============================================================

def create_scam_settings_menu(
    chat_id: int,
    settings: ContentFilterSettings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек антискама.

    Включает:
    - Паттерны (добавление/список)
    - Чувствительность
    - Действие
    - Логирование

    Args:
        chat_id: ID группы
        settings: Текущие настройки

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек антискама
    """
    # Формируем текст чувствительности
    if settings.scam_sensitivity <= 40:
        sens_text = f"{EMOJI_SENS_HIGH} Высокая"
    elif settings.scam_sensitivity <= 70:
        sens_text = f"{EMOJI_SENS_MEDIUM} Средняя"
    else:
        sens_text = f"{EMOJI_SENS_LOW} Низкая"

    # Формируем текст действия
    action_map = {
        'delete': '🗑️ Удалить',
        'warn': '⚠️ Предупредить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }
    action_text = action_map.get(settings.default_action, '🗑️ Удалить')

    # Статус toggle кнопок
    scam_detector_on = getattr(settings, 'scam_detector_enabled', True)
    custom_sections_on = getattr(settings, 'custom_sections_enabled', True)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Toggle: Общий скам-детектор и Кастомные разделы
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Общий детектор {EMOJI_ON if scam_detector_on else EMOJI_OFF}",
                    callback_data=f"cf:t:scamdet:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"Разделы {EMOJI_ON if custom_sections_on else EMOJI_OFF}",
                    callback_data=f"cf:t:custsec:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Паттерны
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_PATTERNS} Паттерны",
                    callback_data=f"cf:scp:{chat_id}"
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI_IMPORT} Импорт",
                    callback_data=f"cf:spi:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Чувствительность
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Чувствительность: {sens_text}",
                    callback_data=f"cf:sens:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Действие (по умолчанию, если нет подходящего порога)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Действие: {action_text}",
                    callback_data=f"cf:scact:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Пороги баллов (градация действий по скору)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📊 Пороги баллов",
                    callback_data=f"cf:scthr:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Логирование
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"Логирование {EMOJI_ON if settings.log_violations else EMOJI_OFF}",
                    callback_data=f"cf:t:log:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Категории сигналов (кастомные наборы ключевых слов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📂 Категории сигналов",
                    callback_data=f"cf:sccat:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Базовые сигналы (настройка весов и включение/отключение)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🔧 Базовые сигналы",
                    callback_data=f"cf:bsig:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Дополнительно (тексты уведомлений, задержки удаления)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚙️ Дополнительно",
                    callback_data=f"cf:scadv:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ АНТИСКАМА
# ============================================================

def create_scam_action_menu(
    chat_id: int,
    current_action: str = 'delete',
    current_duration: int = None
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для антискама.

    Действия:
    - Удалить
    - Мут (+ ручной ввод времени)
    - Бан

    Args:
        chat_id: ID группы
        current_action: Текущее действие (delete/mute/ban)
        current_duration: Длительность мута в минутах

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Формируем текст длительности для мута
    duration_text = ""
    if current_duration and current_action == 'mute':
        if current_duration < 60:
            duration_text = f" ({current_duration}мин)"
        elif current_duration < 1440:
            duration_text = f" ({current_duration // 60}ч)"
        else:
            duration_text = f" ({current_duration // 1440}д)"

    # Галочки для текущего действия
    delete_check = " ✓" if current_action == 'delete' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Только удалить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🗑️ Только удалить{delete_check}",
                    callback_data=f"cf:scact:delete:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Мут + ручной ввод времени
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔇 Мут{mute_check}{duration_text}",
                    callback_data=f"cf:scact:mute:{chat_id}"
                ),
                InlineKeyboardButton(
                    text="⏱️",
                    callback_data=f"cf:scact:time:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Бан
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🚫 Бан{ban_check}",
                    callback_data=f"cf:scact:ban:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад к настройкам антискама
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:scs:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ ДОПОЛНИТЕЛЬНЫХ НАСТРОЕК АНТИСКАМА
# ============================================================

def create_scam_advanced_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню дополнительных настроек антискама.

    Показывает:
    - Текст уведомления при муте
    - Текст уведомления при бане
    - Задержка удаления уведомления

    Args:
        chat_id: ID группы
        settings: Объект ContentFilterSettings

    Returns:
        InlineKeyboardMarkup: Клавиатура дополнительных настроек
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Текст при муте
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Текст при муте",
                    callback_data=f"cf:scmt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Текст при бане
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Текст при бане",
                    callback_data=f"cf:scbt:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Задержка удаления уведомления
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🗑️ Автоудаление уведомления",
                    callback_data=f"cf:scnd:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:scs:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_scam_notification_delay_menu(
    chat_id: int,
    current_delay: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора задержки автоудаления уведомления для скама.

    Args:
        chat_id: ID группы
        current_delay: Текущая задержка в секундах

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора задержки
    """
    delays = [0, 5, 10, 15, 30, 60]

    rows = []
    for delay in delays:
        check = " ✓" if delay == current_delay else ""
        label = "Не удалять" if delay == 0 else f"{delay} сек"
        rows.append([
            InlineKeyboardButton(
                text=f"{label}{check}",
                callback_data=f"cf:scnd:{delay}:{chat_id}"
            )
        ])

    # ─────────────────────────────────────────────────────
    # Кнопка ручного ввода (чтобы избежать хардкода, Правило 22)
    # ─────────────────────────────────────────────────────
    rows.append([
        InlineKeyboardButton(
            text="✏️ Ввести своё значение",
            callback_data=f"cf:scndc:{chat_id}"
        )
    ])

    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:scadv:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# МЕНЮ УПРАВЛЕНИЯ СЛОВАМИ
# ============================================================

def create_words_menu(
    chat_id: int,
    words_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню управления запрещёнными словами.

    Показывает количество слов и действия:
    - Добавить слово
    - Показать список
    - Удалить все

    Args:
        chat_id: ID группы
        words_count: Текущее количество слов

    Returns:
        InlineKeyboardMarkup: Клавиатура управления словами
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Добавить слово
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_ADD} Добавить слово",
                    callback_data=f"cf:wa:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Показать список
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_LIST} Показать список ({words_count})",
                    callback_data=f"cf:wl:{chat_id}:0"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Удалить все (только если есть слова)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_DELETE} Удалить все",
                    callback_data=f"cf:wc:{chat_id}"
                )
            ] if words_count > 0 else [],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    # Убираем пустые ряды (если words_count == 0)
    keyboard.inline_keyboard = [
        row for row in keyboard.inline_keyboard if row
    ]

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ЧУВСТВИТЕЛЬНОСТИ
# ============================================================

def create_sensitivity_menu(
    chat_id: int,
    current_sensitivity: int = 60
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора чувствительности антискама.

    Три уровня:
    - Высокая (40): ловит больше, но могут быть ложные
    - Средняя (60): рекомендуется
    - Низкая (90): только явный скам

    Args:
        chat_id: ID группы
        current_sensitivity: Текущий порог

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора чувствительности
    """
    # Определяем галочку для текущего выбора
    high_check = " ✓" if current_sensitivity <= 40 else ""
    medium_check = " ✓" if 40 < current_sensitivity <= 70 else ""
    low_check = " ✓" if current_sensitivity > 70 else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Высокая чувствительность
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_HIGH} Высокая (порог 40){high_check}",
                    callback_data=f"cf:sens:40:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Средняя чувствительность
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_MEDIUM} Средняя (порог 60){medium_check}",
                    callback_data=f"cf:sens:60:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Низкая чувствительность
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_LOW} Низкая (порог 90){low_check}",
                    callback_data=f"cf:sens:90:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Назад к настройкам антискама
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:scs:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ ДЛЯ ФИЛЬТРА СЛОВ
# ============================================================

def create_word_filter_action_menu(
    chat_id: int,
    current_action: str = None
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для фильтра запрещённых слов.

    Args:
        chat_id: ID группы
        current_action: Текущее действие (None = использовать общее)

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Определяем галочки
    default_check = " ✓" if current_action is None else ""
    delete_check = " ✓" if current_action == 'delete' else ""
    warn_check = " ✓" if current_action == 'warn' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Использовать общее действие
            [
                InlineKeyboardButton(
                    text=f"🔗 Использовать общее{default_check}",
                    callback_data=f"cf:wact:default:{chat_id}"
                )
            ],
            # Только удалить
            [
                InlineKeyboardButton(
                    text=f"🗑️ Только удалить{delete_check}",
                    callback_data=f"cf:wact:delete:{chat_id}"
                )
            ],
            # Предупреждение
            [
                InlineKeyboardButton(
                    text=f"⚠️ Удалить + Предупреждение{warn_check}",
                    callback_data=f"cf:wact:warn:{chat_id}"
                )
            ],
            # Мут
            [
                InlineKeyboardButton(
                    text=f"🔇 Удалить + Мут 24ч{mute_check}",
                    callback_data=f"cf:wact:mute:{chat_id}"
                )
            ],
            # Бан
            [
                InlineKeyboardButton(
                    text=f"🚫 Удалить + Бан{ban_check}",
                    callback_data=f"cf:wact:ban:{chat_id}"
                )
            ],
            # Назад к настройкам фильтра слов
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:wfs:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ ДЛЯ АНТИФЛУДА
# ============================================================

def create_flood_action_menu(
    chat_id: int,
    current_action: str = None,
    mute_duration: int = None
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для антифлуда.

    Args:
        chat_id: ID группы
        current_action: Текущее действие (None = использовать общее)
        mute_duration: Длительность мута в минутах (для отображения)

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Определяем галочки для каждого действия
    delete_check = " ✓" if current_action == 'delete' or current_action is None else ""
    warn_check = " ✓" if current_action == 'warn' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    # Формируем список кнопок
    buttons = [
        # Только удалить (по умолчанию)
        [
            InlineKeyboardButton(
                text=f"🗑️ Только удалить{delete_check}",
                callback_data=f"cf:fact:delete:{chat_id}"
            )
        ],
        # Предупреждение
        [
            InlineKeyboardButton(
                text=f"⚠️ Удалить + Предупреждение{warn_check}",
                callback_data=f"cf:fact:warn:{chat_id}"
            )
        ],
        # Мут (с ручным вводом времени)
        [
            InlineKeyboardButton(
                text=f"🔇 Удалить + Мут{mute_check}",
                callback_data=f"cf:fact:mute:{chat_id}"
            )
        ],
    ]

    # Если выбран мут - показываем кнопку настройки времени
    if current_action == 'mute':
        # Форматируем текущее время мута для отображения
        if mute_duration:
            # Переводим минуты в читаемый формат
            if mute_duration >= 1440:
                # 24 часа и более - показываем в днях/часах
                days = mute_duration // 1440
                hours = (mute_duration % 1440) // 60
                if days > 0 and hours > 0:
                    duration_text = f"{days}д {hours}ч"
                elif days > 0:
                    duration_text = f"{days}д"
                else:
                    duration_text = f"{hours}ч"
            elif mute_duration >= 60:
                # Часы
                hours = mute_duration // 60
                mins = mute_duration % 60
                if mins > 0:
                    duration_text = f"{hours}ч {mins}мин"
                else:
                    duration_text = f"{hours}ч"
            else:
                # Минуты
                duration_text = f"{mute_duration}мин"
        else:
            # Время не задано - используется общее
            duration_text = "24ч (по умолчанию)"

        # Кнопка настройки времени мута
        buttons.append([
            InlineKeyboardButton(
                text=f"⏱️ Время мута: {duration_text}",
                callback_data=f"cf:fldur:{chat_id}"
            )
        ])

    # Бан
    buttons.append([
        InlineKeyboardButton(
            text=f"🚫 Удалить + Бан{ban_check}",
            callback_data=f"cf:fact:ban:{chat_id}"
        )
    ])

    # Назад к меню "Дополнительно" антифлуда
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:fladv:{chat_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    return keyboard


# ============================================================
# МЕНЮ ВЫБОРА ВРЕМЕНИ МУТА ДЛЯ АНТИФЛУДА
# ============================================================

def create_flood_mute_duration_menu(
    chat_id: int,
    current_duration: int = None
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора времени мута для антифлуда.

    Args:
        chat_id: ID группы
        current_duration: Текущая длительность в минутах (для галочки)

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора времени
    """
    # Варианты времени: значение в минутах -> текст для кнопки
    duration_options = [
        (10, "10 мин"),
        (30, "30 мин"),
        (60, "1 час"),
        (180, "3 часа"),
        (360, "6 часов"),
        (720, "12 часов"),
        (1440, "24 часа"),
        (4320, "3 дня"),
        (10080, "7 дней"),
    ]

    # Формируем кнопки по 3 в ряд
    buttons = []
    row = []

    for duration_min, duration_text in duration_options:
        # Добавляем галочку если это текущее значение
        check = " ✓" if current_duration == duration_min else ""

        row.append(InlineKeyboardButton(
            text=f"{duration_text}{check}",
            callback_data=f"cf:fldur:{duration_min}:{chat_id}"
        ))

        # По 3 кнопки в ряд
        if len(row) == 3:
            buttons.append(row)
            row = []

    # Добавляем оставшиеся кнопки
    if row:
        buttons.append(row)

    # Кнопка назад к меню действий
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:fact:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ВЫБОРА ДЕЙСТВИЯ
# ============================================================

def create_action_menu(
    chat_id: int,
    current_action: str = 'delete'
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия по умолчанию.

    Действия:
    - Удалить: только удалить сообщение
    - Предупреждение: удалить + отправить предупреждение
    - Мут: удалить + замутить пользователя
    - Бан: удалить + забанить пользователя

    Args:
        chat_id: ID группы
        current_action: Текущее действие

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Определяем галочки
    delete_check = " ✓" if current_action == 'delete' else ""
    warn_check = " ✓" if current_action == 'warn' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Только удалить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🗑️ Только удалить{delete_check}",
                    callback_data=f"cf:act:delete:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Предупреждение
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⚠️ Удалить + Предупреждение{warn_check}",
                    callback_data=f"cf:act:warn:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Мут
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔇 Удалить + Мут 24ч{mute_check}",
                    callback_data=f"cf:act:mute:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Бан
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🚫 Удалить + Бан{ban_check}",
                    callback_data=f"cf:act:ban:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 5: Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:s:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ НАСТРОЕК ФЛУДА
# ============================================================

def create_flood_settings_menu(
    chat_id: int,
    max_repeats: int = 2,
    time_window: int = 60,
    action: str = None,
    mute_duration: int = None,
    detect_any_messages: bool = False,
    any_max_messages: int = 5,
    any_time_window: int = 10,
    detect_media: bool = False
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек антифлуда.

    СТРУКТУРА МЕНЮ (по запросу пользователя):
    - Расширенный антифлуд: любые сообщения (toggle)
    - Расширенный антифлуд: медиа (toggle)
    - Дополнительно (ведёт в детальные настройки)
    - Назад

    ВАЖНО: Настройки "Макс. повторов", "Временное окно", "Действие"
    теперь ТОЛЬКО в меню "Дополнительно" (cf:fladv), чтобы не было дублирования!

    Args:
        chat_id: ID группы
        max_repeats: Текущий порог повторов (отображается в тексте сообщения)
        time_window: Текущее временное окно в секундах (отображается в тексте)
        action: Текущее действие (для отображения в тексте)
        mute_duration: Длительность мута в минутах (для отображения)
        detect_any_messages: Включена ли детекция любых сообщений
        any_max_messages: Лимит любых сообщений (для отображения)
        any_time_window: Временное окно для любых сообщений (для отображения)
        detect_media: Включена ли детекция медиа-флуда

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек флуда
    """
    # УБРАНЫ: кнопки "Макс. повторов", "Временное окно", "Действие"
    # Теперь они ТОЛЬКО в меню "Дополнительно" (cf:fladv)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Разделитель: Расширенный антифлуд
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="─── Расширенный антифлуд ───",
                    callback_data="cf:noop"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Любые сообщения подряд
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"💬 Любые сообщения {EMOJI_ON if detect_any_messages else EMOJI_OFF}",
                    callback_data=f"cf:t:flany:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Медиа-флуд (фото, стикеры, видео, войсы)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🖼️ Медиа-флуд {EMOJI_ON if detect_media else EMOJI_OFF}",
                    callback_data=f"cf:t:flmedia:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Дополнительно (здесь ВСЕ детальные настройки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚙️ Дополнительно",
                    callback_data=f"cf:fladv:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Назад к главному меню фильтра контента
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def _format_flood_action(action: str, mute_duration: int = None) -> str:
    """Форматирует текст действия для антифлуда.

    Args:
        action: Действие (delete/mute/ban или None)
        mute_duration: Длительность мута в минутах

    Returns:
        str: Отформатированный текст действия
    """
    # Если действие не задано - показываем "Удалить" как дефолт
    if not action:
        return "🗑️ Удалить"

    action_texts = {
        'delete': '🗑️ Удалить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }

    text = action_texts.get(action, '🗑️ Удалить')

    # Добавляем длительность если есть мут
    if action == 'mute' and mute_duration:
        if mute_duration < 60:
            text += f" ({mute_duration}мин)"
        elif mute_duration < 1440:
            text += f" ({mute_duration // 60}ч)"
        else:
            text += f" ({mute_duration // 1440}д)"

    return text


# ============================================================
# КРОСС-СООБЩЕНИЕ ДЕТЕКЦИЯ - МЕНЮ НАСТРОЕК
# ============================================================

def create_cross_message_settings_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек кросс-сообщение детекции.

    Позволяет настроить:
    - Временное окно накопления (1ч, 2ч, 4ч, 8ч)
    - Порог срабатывания (50, 75, 100, 150 баллов)
    - Действие (mute/ban/kick)

    Args:
        chat_id: ID группы
        settings: Настройки ContentFilter

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек
    """
    # Получаем текущие значения
    window_seconds = getattr(settings, 'cross_message_window_seconds', 7200) if settings else 7200
    threshold = getattr(settings, 'cross_message_threshold', 100) if settings else 100
    action = getattr(settings, 'cross_message_action', 'mute') if settings else 'mute'

    # Форматируем окно в читаемый вид
    window_hours = window_seconds // 3600
    if window_hours == 0:
        window_text = f"{window_seconds // 60}мин"
    else:
        window_text = f"{window_hours}ч"

    # Форматируем действие
    action_map = {
        'mute': '🔇 Мут',
        'ban': '🚫 Бан',
        'kick': '👢 Кик'
    }
    action_text = action_map.get(action, '🔇 Мут')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # НОВОЕ: Кнопка паттернов кросс-сообщений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Паттерны",
                    callback_data=f"cf:cmp:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Заголовок: текущие настройки
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⏱️ Окно: {window_text}",
                    callback_data=f"cf:cmw:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📊 Порог: {threshold} баллов",
                    callback_data=f"cf:cmt:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⚡ Действие: {action_text}",
                    callback_data=f"cf:cma:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # НОВОЕ: Пороги баллов (разные действия для разных диапазонов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📈 Пороги баллов",
                    callback_data=f"cf:cmst:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # НОВОЕ: Настройка уведомлений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📢 Уведомления",
                    callback_data=f"cf:cmn:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад к главному меню
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:m:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_window_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора временного окна для кросс-сообщение детекции.

    Args:
        chat_id: ID группы
        settings: Настройки ContentFilter

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора окна
    """
    # Текущее значение
    current = getattr(settings, 'cross_message_window_seconds', 7200) if settings else 7200

    # Варианты окон (секунды)
    windows = [
        (1800, "30мин"),    # 30 минут
        (3600, "1ч"),       # 1 час
        (7200, "2ч"),       # 2 часа
        (14400, "4ч"),      # 4 часа
        (28800, "8ч"),      # 8 часов
    ]

    rows = []
    # Флаг: текущее значение есть в списке?
    current_in_list = current in [w[0] for w in windows]

    for seconds, label in windows:
        # Отмечаем текущий выбор
        marker = "✓ " if seconds == current else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{marker}{label}",
                callback_data=f"cf:cmw:s:{seconds}:{chat_id}"
            )
        ])

    # Кнопка "Другое" для кастомного ввода
    # Если текущее значение не в списке — показываем его
    if not current_in_list:
        # Форматируем текущее кастомное значение
        if current >= 86400:
            custom_label = f"✓ {current // 86400}д"
        elif current >= 3600:
            custom_label = f"✓ {current // 3600}ч"
        elif current >= 60:
            custom_label = f"✓ {current // 60}мин"
        else:
            custom_label = f"✓ {current}сек"
        other_text = f"✏️ Другое ({custom_label})"
    else:
        other_text = "✏️ Другое"

    rows.append([
        InlineKeyboardButton(
            text=other_text,
            callback_data=f"cf:cmwc:{chat_id}"  # c = custom input
        )
    ])

    # Кнопка назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cms:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_threshold_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора порога срабатывания.

    Args:
        chat_id: ID группы
        settings: Настройки ContentFilter

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора порога
    """
    # Текущее значение
    current = getattr(settings, 'cross_message_threshold', 100) if settings else 100

    # Варианты порогов
    thresholds = [50, 75, 100, 125, 150, 200]

    rows = []
    # Флаг: текущее значение есть в списке?
    current_in_list = current in thresholds

    for value in thresholds:
        marker = "✓ " if value == current else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{marker}{value} баллов",
                callback_data=f"cf:cmt:s:{value}:{chat_id}"
            )
        ])

    # Кнопка "Другое" для кастомного ввода
    # Если текущее значение не в списке — показываем его
    if not current_in_list:
        other_text = f"✏️ Другое (✓ {current})"
    else:
        other_text = "✏️ Другое"

    rows.append([
        InlineKeyboardButton(
            text=other_text,
            callback_data=f"cf:cmtc:{chat_id}"  # c = custom input
        )
    ])

    # Кнопка назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cms:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_action_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия.

    Args:
        chat_id: ID группы
        settings: Настройки ContentFilter

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    # Текущее значение
    current = getattr(settings, 'cross_message_action', 'mute') if settings else 'mute'

    # Варианты действий
    actions = [
        ('mute', '🔇 Мут'),
        ('ban', '🚫 Бан'),
        ('kick', '👢 Кик'),
    ]

    rows = []
    for action_value, label in actions:
        marker = "✓ " if action_value == current else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{marker}{label}",
                callback_data=f"cf:cma:s:{action_value}:{chat_id}"
            )
        ])

    # Кнопка назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cms:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ВСЕХ СЛОВ
# ============================================================

def create_clear_words_confirm_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню подтверждения удаления всех слов.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура подтверждения
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подтвердить удаление
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить все слова",
                    callback_data=f"cf:wcc:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:w:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ПАГИНАЦИЯ СПИСКА СЛОВ
# ============================================================

def create_words_list_menu(
    chat_id: int,
    page: int,
    total_pages: int,
    has_words: bool = True
) -> InlineKeyboardMarkup:
    """
    Создаёт меню пагинации для списка слов.

    Args:
        chat_id: ID группы
        page: Текущая страница (0-based)
        total_pages: Общее количество страниц
        has_words: Есть ли слова на странице

    Returns:
        InlineKeyboardMarkup: Клавиатура пагинации
    """
    buttons = []

    # ─────────────────────────────────────────────────────
    # Ряд навигации (если больше 1 страницы)
    # ─────────────────────────────────────────────────────
    if total_pages > 1:
        nav_row = []

        # Кнопка "Назад" (если не первая страница)
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"cf:wl:{chat_id}:{page - 1}"
                )
            )

        # Номер страницы
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cf:noop"
            )
        )

        # Кнопка "Вперёд" (если не последняя страница)
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"cf:wl:{chat_id}:{page + 1}"
                )
            )

        buttons.append(nav_row)

    # ─────────────────────────────────────────────────────
    # Ряд "Назад"
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:w:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# СПИСОК СЛОВ ПО КАТЕГОРИИ (с удалением)
# ============================================================

def create_category_words_list_menu(
    chat_id: int,
    category: str,
    page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню управления списком слов категории.

    Слова отображаются в ТЕКСТЕ сообщения, а не кнопками.
    Клавиатура содержит только кнопки управления.

    Args:
        chat_id: ID группы
        category: Код категории (sw, hw, ow)
        page: Текущая страница (0-based)
        total_pages: Общее количество страниц

    Returns:
        InlineKeyboardMarkup: Клавиатура управления
    """
    buttons = []

    # ─────────────────────────────────────────────────────
    # Ряд навигации (если больше 1 страницы)
    # ─────────────────────────────────────────────────────
    if total_pages > 1:
        nav_row = []

        # Кнопка "Назад" (если не первая страница)
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"cf:{category}l:{chat_id}:{page - 1}"
                )
            )

        # Номер страницы
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cf:noop"
            )
        )

        # Кнопка "Вперёд" (если не последняя страница)
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"cf:{category}l:{chat_id}:{page + 1}"
                )
            )

        buttons.append(nav_row)

    # ─────────────────────────────────────────────────────
    # Кнопка "Добавить слово"
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_ADD} Добавить слово",
            callback_data=f"cf:{category}w:{chat_id}"
        )
    ])

    # ─────────────────────────────────────────────────────
    # Кнопки удаления слов (FSM ввод и удалить все)
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text="🗑️ Удалить слово",
            callback_data=f"cf:{category}dw:{chat_id}"
        ),
        InlineKeyboardButton(
            text="🗑️ Удалить все",
            callback_data=f"cf:{category}da:{chat_id}"
        )
    ])

    # ─────────────────────────────────────────────────────
    # Ряд "Назад" к настройкам фильтра слов
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:wfs:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# МЕНЮ ПАТТЕРНОВ СКАМА
# ============================================================

def create_scam_patterns_menu(
    chat_id: int,
    patterns_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню управления кастомными паттернами скама.

    Показывает количество паттернов и действия:
    - Добавить паттерн (ручной ввод)
    - Импорт из текста (анализ)
    - Показать список
    - Экспорт
    - Удалить все

    Args:
        chat_id: ID группы
        patterns_count: Текущее количество паттернов

    Returns:
        InlineKeyboardMarkup: Клавиатура управления паттернами
    """
    keyboard_rows = [
        # ─────────────────────────────────────────────────────
        # Ряд 1: Добавить паттерн
        # ─────────────────────────────────────────────────────
        [
            InlineKeyboardButton(
                text=f"{EMOJI_ADD} Добавить паттерн",
                callback_data=f"cf:scpa:{chat_id}"
            )
        ],
        # ─────────────────────────────────────────────────────
        # Ряд 2: Импорт из текста (анализ)
        # ─────────────────────────────────────────────────────
        [
            InlineKeyboardButton(
                text=f"{EMOJI_IMPORT} Импорт из текста",
                callback_data=f"cf:spi:{chat_id}"
            )
        ],
        # ─────────────────────────────────────────────────────
        # Ряд 3: Показать список
        # ─────────────────────────────────────────────────────
        [
            InlineKeyboardButton(
                text=f"{EMOJI_LIST} Список ({patterns_count})",
                callback_data=f"cf:scpl:{chat_id}:0"
            )
        ],
    ]

    # ─────────────────────────────────────────────────────
    # Ряд 4: Экспорт (только если есть паттерны)
    # ─────────────────────────────────────────────────────
    if patterns_count > 0:
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"{EMOJI_EXPORT} Экспорт",
                callback_data=f"cf:scpe:{chat_id}"
            )
        ])

    # ─────────────────────────────────────────────────────
    # Ряд 5: Удалить все (только если есть паттерны)
    # ─────────────────────────────────────────────────────
    if patterns_count > 0:
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"{EMOJI_DELETE} Удалить все",
                callback_data=f"cf:scpc:{chat_id}"
            )
        ])

    # ─────────────────────────────────────────────────────
    # Ряд: Назад к настройкам антискама
    # ─────────────────────────────────────────────────────
    keyboard_rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:scs:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


# ============================================================
# ВЫБОР ТИПА ПАТТЕРНА
# ============================================================

def create_pattern_type_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора типа паттерна.

    Типы:
    - phrase: как подстрока (по умолчанию)
    - word: как отдельное слово
    - regex: регулярное выражение

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора типа
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подстрока (по умолчанию)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Подстрока (часть текста)",
                    callback_data=f"cf:spt:phrase:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Отдельное слово
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🔤 Отдельное слово",
                    callback_data=f"cf:spt:word:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Регулярное выражение
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚙️ Регулярное выражение",
                    callback_data=f"cf:spt:regex:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ВЫБОР ВЕСА ПАТТЕРНА
# ============================================================

def create_pattern_weight_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора веса паттерна.

    Веса:
    - 15: слабый сигнал
    - 25: средний сигнал (по умолчанию)
    - 40: сильный сигнал

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора веса
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Слабый
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🟢 Слабый (15 баллов)",
                    callback_data=f"cf:spw:15:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Средний (по умолчанию)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🟡 Средний (25 баллов) ✓",
                    callback_data=f"cf:spw:25:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Сильный
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🔴 Сильный (40 баллов)",
                    callback_data=f"cf:spw:40:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ВЫБОР ВЕСА ПРИ ИМПОРТЕ
# ============================================================

def create_import_weight_menu(
    chat_id: int,
    current_weight: int = 25
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора веса для импортируемых паттернов.

    Отличается от create_pattern_weight_menu тем, что
    кнопка "Назад" возвращает к превью импорта, а не к меню паттернов.

    Args:
        chat_id: ID группы
        current_weight: Текущий выбранный вес

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора веса
    """
    # Галочки для выбранного веса
    weak_check = " ✓" if current_weight == 15 else ""
    medium_check = " ✓" if current_weight == 25 else ""
    strong_check = " ✓" if current_weight == 40 else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Слабый (15 баллов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🟢 Слабый (15 баллов){weak_check}",
                    callback_data=f"cf:spw:15:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Средний (25 баллов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🟡 Средний (25 баллов){medium_check}",
                    callback_data=f"cf:spw:25:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Сильный (40 баллов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔴 Сильный (40 баллов){strong_check}",
                    callback_data=f"cf:spw:40:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 4: Назад (возврат к превью импорта)
            # Используем тот же callback что и выбор веса,
            # но с текущим весом — это вернёт к превью
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:spw:{current_weight}:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ПАГИНАЦИЯ СПИСКА ПАТТЕРНОВ
# ============================================================

def create_patterns_list_menu(
    chat_id: int,
    page: int,
    total_pages: int,
    pattern_ids: List[int]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню пагинации для списка паттернов.

    Каждый паттерн отображается как кнопка для удаления.

    Args:
        chat_id: ID группы
        page: Текущая страница (0-based)
        total_pages: Общее количество страниц
        pattern_ids: Список ID паттернов на текущей странице

    Returns:
        InlineKeyboardMarkup: Клавиатура пагинации
    """
    buttons = []

    # ─────────────────────────────────────────────────────
    # Кнопки удаления для каждого паттерна
    # ─────────────────────────────────────────────────────
    for pattern_id in pattern_ids:
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ Удалить #{pattern_id}",
                callback_data=f"cf:scpd:{pattern_id}:{chat_id}"
            )
        ])

    # ─────────────────────────────────────────────────────
    # Ряд навигации (если больше 1 страницы)
    # ─────────────────────────────────────────────────────
    if total_pages > 1:
        nav_row = []

        # Кнопка "Назад" (если не первая страница)
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"cf:scpl:{chat_id}:{page - 1}"
                )
            )

        # Номер страницы
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cf:noop"
            )
        )

        # Кнопка "Вперёд" (если не последняя страница)
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"cf:scpl:{chat_id}:{page + 1}"
                )
            )

        buttons.append(nav_row)

    # ─────────────────────────────────────────────────────
    # Ряд "Назад"
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:scp:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ПАТТЕРНА
# ============================================================

def create_pattern_delete_confirm_menu(
    pattern_id: int,
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню подтверждения удаления паттерна.

    Args:
        pattern_id: ID паттерна для удаления
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура подтверждения
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подтвердить удаление
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить",
                    callback_data=f"cf:scpdc:{pattern_id}:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scpl:{chat_id}:0"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ВСЕХ ПАТТЕРНОВ
# ============================================================

def create_clear_patterns_confirm_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню подтверждения удаления всех паттернов.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура подтверждения
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подтвердить удаление
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить все паттерны",
                    callback_data=f"cf:scpcc:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ПРЕВЬЮ ИМПОРТА ПАТТЕРНОВ
# ============================================================

def create_import_preview_menu(
    chat_id: int,
    phrases_count: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню превью импортированных паттернов.

    Показывает количество найденных фраз и кнопки подтверждения.

    Args:
        chat_id: ID группы
        phrases_count: Количество найденных фраз

    Returns:
        InlineKeyboardMarkup: Клавиатура превью
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подтвердить импорт
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"✅ Импортировать ({phrases_count} фраз)",
                    callback_data=f"cf:spic:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Выбрать вес для всех
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚖️ Выбрать вес",
                    callback_data=f"cf:spiw:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ВЫБОР ТИПА ПАТТЕРНА
# ============================================================

def create_pattern_type_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора типа паттерна.

    Типы:
    - phrase: Фраза (fuzzy matching) - текущее поведение
    - regex: Регулярное выражение - точный контроль

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора типа
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Фраза (fuzzy)",
                    callback_data=f"cf:scpat:phrase:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Regex (точный)",
                    callback_data=f"cf:scpat:regex:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# ОТМЕНА FSM (добавление паттерна)
# ============================================================

def create_cancel_pattern_input_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню отмены ввода паттерна (для FSM).

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура отмены
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:scp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# МЕНЮ КАСТОМНЫХ РАЗДЕЛОВ СПАМА
# ============================================================

def create_custom_sections_menu(
    chat_id: int,
    sections: list
) -> InlineKeyboardMarkup:
    """
    Создаёт меню списка кастомных разделов.

    Каждый раздел отображается как кнопка с вкл/выкл статусом.
    Внизу кнопка добавления нового раздела.

    Args:
        chat_id: ID группы
        sections: Список объектов CustomSpamSection

    Returns:
        InlineKeyboardMarkup: Клавиатура со списком разделов
    """
    buttons = []

    # Кнопки для каждого раздела
    for section in sections:
        status = EMOJI_ON if section.enabled else EMOJI_OFF
        # Показываем название и количество паттернов (если есть атрибут)
        name = section.name[:20] + "..." if len(section.name) > 20 else section.name
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {name}",
                callback_data=f"cf:sec:{section.id}"
            ),
            InlineKeyboardButton(
                text=f"{EMOJI_SETTINGS}",
                callback_data=f"cf:secs:{section.id}"
            )
        ])

    # Кнопка добавления нового раздела
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_ADD} Создать раздел",
            callback_data=f"cf:secn:{chat_id}"
        )
    ])

    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:scs:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_section_settings_menu(
    section_id: int,
    section,
    chat_id: int,
    patterns_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настроек раздела.

    Показывает:
    - Паттерны (добавление/импорт/список)
    - Порог чувствительности
    - Действие (с указанием пересылки)
    - Дополнительно (тексты уведомлений, задержки)
    - Удалить

    НЕ показывает кнопку Вкл/Выкл - она уже есть в списке разделов.

    Args:
        section_id: ID раздела
        section: Объект CustomSpamSection
        chat_id: ID группы
        patterns_count: Количество паттернов в разделе

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек раздела
    """
    # Формируем текст действия
    action_map = {
        'delete': '🗑️ Удалить',
        'mute': '🔇 Мут',
        'ban': '🚫 Бан'
    }
    action_text = action_map.get(section.action, '🗑️ Удалить')

    # Показываем статус пересылки для текущего действия
    forward_status = ""
    if section.action == 'delete' and section.forward_on_delete:
        forward_status = " 📤"
    elif section.action == 'mute' and section.forward_on_mute:
        forward_status = " 📤"
    elif section.action == 'ban' and section.forward_on_ban:
        forward_status = " 📤"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Паттерны (кнопки добавления/импорта ВНУТРИ patterns menu)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_PATTERNS} Паттерны ({patterns_count})",
                    callback_data=f"cf:secp:{section_id}:0"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Порог чувствительности
            # ─────────────────────────────────────────────────────
            [
                # Кнопка порога с понятным текстом (Баг 2 fix)
                InlineKeyboardButton(
                    text=f"Чувствительность: 🔢 {section.threshold} баллов",
                    callback_data=f"cf:secth:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Действие (с иконкой пересылки если включена)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    # Баг 2 fix: убран лишний emoji, добавлено слово "Действие"
                    text=f"Действие: {action_text}{forward_status}",
                    callback_data=f"cf:secac:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Пороги баллов (разные действия для разных диапазонов)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📊 Пороги баллов",
                    callback_data=f"cf:secthr:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Дополнительно (тексты уведомлений, задержки)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚙️ Дополнительно",
                    callback_data=f"cf:secadv:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Удалить раздел
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_DELETE} Удалить раздел",
                    callback_data=f"cf:secd:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад к списку разделов
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:sccat:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_action_menu(
    section_id: int,
    section
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для раздела.

    Новая структура:
    - Выбор действия (delete/mute/ban) с галочкой
    - Toggle пересылки для каждого действия (независимо!)
    - Настройка канала пересылки (общая для всех действий)
    - Кнопка времени мута (если выбран mute)

    Args:
        section_id: ID раздела
        section: Объект CustomSpamSection с полями:
            - action: текущее действие ('delete', 'mute', 'ban')
            - mute_duration: длительность мута в минутах
            - forward_on_delete: пересылать при удалении
            - forward_on_mute: пересылать при муте
            - forward_on_ban: пересылать при бане
            - forward_channel_id: ID канала для пересылки

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    current_action = section.action or 'delete'
    current_duration = section.mute_duration

    # Формируем текст длительности для мута
    duration_text = ""
    if current_duration and current_action == 'mute':
        if current_duration < 60:
            duration_text = f" ({current_duration}мин)"
        elif current_duration < 1440:
            duration_text = f" ({current_duration // 60}ч)"
        else:
            duration_text = f" ({current_duration // 1440}д)"

    # Галочки выбора действия
    delete_check = " ✓" if current_action == 'delete' else ""
    mute_check = " ✓" if current_action == 'mute' else ""
    ban_check = " ✓" if current_action == 'ban' else ""

    # Статусы пересылки для каждого действия
    fwd_del = EMOJI_ON if section.forward_on_delete else EMOJI_OFF
    fwd_mute = EMOJI_ON if section.forward_on_mute else EMOJI_OFF
    fwd_ban = EMOJI_ON if section.forward_on_ban else EMOJI_OFF

    # Формируем текст канала
    channel_text = section.forward_channel_id or "не задан"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Действие: Удалить + toggle пересылки
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🗑️ Удалить{delete_check}",
                    callback_data=f"cf:secac:delete:{section_id}"
                ),
                InlineKeyboardButton(
                    text=f"📤 {fwd_del}",
                    callback_data=f"cf:secfd:delete:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Действие: Мут + toggle пересылки + время
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔇 Мут{mute_check}{duration_text}",
                    callback_data=f"cf:secac:mute:{section_id}"
                ),
                InlineKeyboardButton(
                    text=f"📤 {fwd_mute}",
                    callback_data=f"cf:secfd:mute:{section_id}"
                ),
                InlineKeyboardButton(
                    text="⏱️",
                    callback_data=f"cf:secmt:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Действие: Бан + toggle пересылки
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🚫 Бан{ban_check}",
                    callback_data=f"cf:secac:ban:{section_id}"
                ),
                InlineKeyboardButton(
                    text=f"📤 {fwd_ban}",
                    callback_data=f"cf:secfd:ban:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Канал пересылки (общий для всех действий)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📢 Канал: {channel_text}",
                    callback_data=f"cf:secch:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secs:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_threshold_menu(
    section_id: int,
    current_threshold: int = 60
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора порога чувствительности раздела.

    Args:
        section_id: ID раздела
        current_threshold: Текущий порог

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора порога
    """
    # Определяем галочку для текущего выбора
    high_check = " ✓" if current_threshold <= 40 else ""
    medium_check = " ✓" if 40 < current_threshold <= 70 else ""
    low_check = " ✓" if current_threshold > 70 else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Высокая чувствительность (порог 40)
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_HIGH} Высокая (порог 40){high_check}",
                    callback_data=f"cf:secth:40:{section_id}"
                )
            ],
            # Средняя чувствительность (порог 60)
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_MEDIUM} Средняя (порог 60){medium_check}",
                    callback_data=f"cf:secth:60:{section_id}"
                )
            ],
            # Низкая чувствительность (порог 90)
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_SENS_LOW} Низкая (порог 90){low_check}",
                    callback_data=f"cf:secth:90:{section_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secs:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_advanced_menu(
    section_id: int,
    section
) -> InlineKeyboardMarkup:
    """
    Создаёт меню дополнительных настроек раздела.

    Показывает:
    - Текст уведомления при муте (%user% заменится на @username)
    - Текст уведомления при бане (%user% заменится на @username)
    - Задержка удаления уведомления бота

    Args:
        section_id: ID раздела
        section: Объект CustomSpamSection с полями:
            - mute_text: текст уведомления при муте
            - ban_text: текст уведомления при бане
            - notification_delete_delay: задержка удаления в секундах

    Returns:
        InlineKeyboardMarkup: Клавиатура дополнительных настроек
    """
    # Текст задержки удаления
    delay = getattr(section, 'notification_delete_delay', None) or 0
    if delay == 0:
        delay_text = "не удалять"
    elif delay < 60:
        delay_text = f"{delay}сек"
    else:
        delay_text = f"{delay // 60}мин"

    # Укороченные тексты уведомлений для отображения
    mute_text_display = getattr(section, 'mute_text', None) or "не задан"
    ban_text_display = getattr(section, 'ban_text', None) or "не задан"

    # Обрезаем если слишком длинные
    if len(mute_text_display) > 15:
        mute_text_display = mute_text_display[:15] + "..."
    if len(ban_text_display) > 15:
        ban_text_display = ban_text_display[:15] + "..."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Текст уведомления при муте
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🔇 Текст мута: {mute_text_display}",
                    callback_data=f"cf:secmt:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Текст уведомления при бане
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🚫 Текст бана: {ban_text_display}",
                    callback_data=f"cf:secbt:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Задержка удаления уведомления бота
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"⏱️ Удалить уведомление: {delay_text}",
                    callback_data=f"cf:secnd:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # CAS (Combot Anti-Spam) — проверка в глобальной базе
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"🛡️ CAS: {'✅' if getattr(section, 'cas_enabled', False) else '❌'}",
                    callback_data=f"cf:seccas:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Добавление в глобальную БД спаммеров бота
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"📋 БД спаммеров: {'✅' if getattr(section, 'add_to_spammer_db', False) else '❌'}",
                    callback_data=f"cf:secspdb:{section_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Назад к настройкам раздела
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secs:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_notification_delay_menu(
    section_id: int,
    current_delay: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора задержки удаления уведомления бота.

    Использует inline кнопки вместо FSM для выбора времени.

    Args:
        section_id: ID раздела
        current_delay: Текущая задержка в секундах

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора задержки
    """
    # Галочки для текущего выбора
    check_0 = " ✓" if current_delay == 0 else ""
    check_10 = " ✓" if current_delay == 10 else ""
    check_30 = " ✓" if current_delay == 30 else ""
    check_60 = " ✓" if current_delay == 60 else ""
    check_300 = " ✓" if current_delay == 300 else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Не удалять
            [
                InlineKeyboardButton(
                    text=f"🚫 Не удалять{check_0}",
                    callback_data=f"cf:secnd:0:{section_id}"
                )
            ],
            # 10 секунд
            [
                InlineKeyboardButton(
                    text=f"⏱️ 10 секунд{check_10}",
                    callback_data=f"cf:secnd:10:{section_id}"
                )
            ],
            # 30 секунд
            [
                InlineKeyboardButton(
                    text=f"⏱️ 30 секунд{check_30}",
                    callback_data=f"cf:secnd:30:{section_id}"
                )
            ],
            # 1 минута
            [
                InlineKeyboardButton(
                    text=f"⏱️ 1 минута{check_60}",
                    callback_data=f"cf:secnd:60:{section_id}"
                )
            ],
            # 5 минут
            [
                InlineKeyboardButton(
                    text=f"⏱️ 5 минут{check_300}",
                    callback_data=f"cf:secnd:300:{section_id}"
                )
            ],
            # Ручной ввод
            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную",
                    callback_data=f"cf:secndc:{section_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secadv:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_mute_duration_menu(
    section_id: int,
    current_duration: int = 60
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора длительности мута.

    Использует inline кнопки вместо FSM для выбора времени.

    Args:
        section_id: ID раздела
        current_duration: Текущая длительность в минутах

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора длительности
    """
    # Галочки для текущего выбора
    check_30 = " ✓" if current_duration == 30 else ""
    check_60 = " ✓" if current_duration == 60 else ""
    check_180 = " ✓" if current_duration == 180 else ""
    check_720 = " ✓" if current_duration == 720 else ""
    check_1440 = " ✓" if current_duration == 1440 else ""
    check_10080 = " ✓" if current_duration == 10080 else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # 30 минут
            [
                InlineKeyboardButton(
                    text=f"⏱️ 30 минут{check_30}",
                    callback_data=f"cf:secmt:30:{section_id}"
                )
            ],
            # 1 час
            [
                InlineKeyboardButton(
                    text=f"⏱️ 1 час{check_60}",
                    callback_data=f"cf:secmt:60:{section_id}"
                )
            ],
            # 3 часа
            [
                InlineKeyboardButton(
                    text=f"⏱️ 3 часа{check_180}",
                    callback_data=f"cf:secmt:180:{section_id}"
                )
            ],
            # 12 часов
            [
                InlineKeyboardButton(
                    text=f"⏱️ 12 часов{check_720}",
                    callback_data=f"cf:secmt:720:{section_id}"
                )
            ],
            # 1 день
            [
                InlineKeyboardButton(
                    text=f"⏱️ 1 день{check_1440}",
                    callback_data=f"cf:secmt:1440:{section_id}"
                )
            ],
            # 7 дней
            [
                InlineKeyboardButton(
                    text=f"⏱️ 7 дней{check_10080}",
                    callback_data=f"cf:secmt:10080:{section_id}"
                )
            ],
            # Ручной ввод времени (Правило 22: запрет хардкода - даём возможность вводить своё)
            [
                InlineKeyboardButton(
                    text="⌨️ Ввести своё",
                    callback_data=f"cf:secmdc:{section_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secac:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_patterns_menu(
    section_id: int,
    page: int,
    total_pages: int,
    pattern_data: List[tuple]
) -> InlineKeyboardMarkup:
    """
    Создаёт меню пагинации для паттернов раздела.

    Args:
        section_id: ID раздела
        page: Текущая страница (0-based)
        total_pages: Общее количество страниц
        pattern_data: Список кортежей (display_num, pattern_id, pattern_text)

    Returns:
        InlineKeyboardMarkup: Клавиатура пагинации
    """
    buttons = []

    # Кнопки для каждого паттерна: изменить вес + удалить
    for display_num, pattern_id, pattern_text in pattern_data:
        # Обрезаем паттерн до 15 символов для кнопки
        short_pattern = pattern_text[:15] + "…" if len(pattern_text) > 15 else pattern_text
        buttons.append([
            InlineKeyboardButton(
                text=f"{display_num}. ⚖️ {short_pattern}",
                callback_data=f"cf:secpw:{pattern_id}:{section_id}"
            ),
            InlineKeyboardButton(
                text=f"❌",
                callback_data=f"cf:secpd:{pattern_id}:{section_id}"
            )
        ])

    # Ряд навигации
    if total_pages > 1:
        nav_row = []

        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"cf:secp:{section_id}:{page - 1}"
                )
            )

        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cf:noop"
            )
        )

        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"cf:secp:{section_id}:{page + 1}"
                )
            )

        buttons.append(nav_row)

    # ─────────────────────────────────────────────────────
    # Кнопки действий с паттернами
    # ─────────────────────────────────────────────────────
    # Добавить + Поиск + Импорт из текста
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_ADD} Добавить",
            callback_data=f"cf:secpa:{section_id}"
        ),
        InlineKeyboardButton(
            text="🔍 Поиск",
            callback_data=f"cf:secpsrch:{section_id}"
        ),
        InlineKeyboardButton(
            text="📥 Импорт",
            callback_data=f"cf:secpi:{section_id}"
        )
    ])

    # Удалить все паттерны (только если есть паттерны)
    if pattern_data:
        buttons.append([
            InlineKeyboardButton(
                text="🗑️ Удалить все паттерны",
                callback_data=f"cf:secpda:{section_id}"
            )
        ])

    # Назад к настройкам раздела
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:secs:{section_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_section_delete_confirm_menu(
    section_id: int,
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню подтверждения удаления раздела.

    Args:
        section_id: ID раздела
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура подтверждения
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить раздел",
                    # ВАЖНО: добавляем chat_id для хендлера cf:secdc:\d+:-?\d+$
                    callback_data=f"cf:secdc:{section_id}:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:secs:{section_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cancel_section_input_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню отмены ввода для раздела (FSM).

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура отмены
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:sccat:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_section_pattern_type_menu(
    section_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора типа паттерна для раздела.

    Args:
        section_id: ID раздела

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора типа
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Фраза (fuzzy)",
                    callback_data=f"cf:secpat:phrase:{section_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Regex (точный)",
                    callback_data=f"cf:secpat:regex:{section_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:secp:{section_id}:0"
                )
            ]
        ]
    )

    return keyboard


def create_cancel_section_pattern_input_menu(
    section_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню отмены ввода паттерна раздела (FSM).

    Args:
        section_id: ID раздела

    Returns:
        InlineKeyboardMarkup: Клавиатура отмены
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:secs:{section_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# КРОСС-СООБЩЕНИЕ ПАТТЕРНЫ - МЕНЮ УПРАВЛЕНИЯ
# ============================================================
# Эти клавиатуры используются для управления ОТДЕЛЬНЫМИ паттернами
# кросс-сообщение детекции (НЕ паттерны разделов!)
# ============================================================

def create_cross_message_patterns_menu(
    chat_id: int,
    patterns_count: int = 0,
    active_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Создаёт главное меню управления паттернами кросс-сообщений.

    Args:
        chat_id: ID группы
        patterns_count: Общее количество паттернов
        active_count: Количество активных паттернов

    Returns:
        InlineKeyboardMarkup: Клавиатура управления
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Добавить паттерн
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_ADD} Добавить паттерн",
                    callback_data=f"cf:cmpa:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Список паттернов
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_LIST} Список ({active_count}/{patterns_count})",
                    callback_data=f"cf:cmpl:{chat_id}:0"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Удалить всё (только если есть паттерны)
            # ─────────────────────────────────────────────────────
            *([
                [
                    InlineKeyboardButton(
                        text=f"{EMOJI_DELETE} Очистить все",
                        callback_data=f"cf:cmpd:{chat_id}"
                    )
                ]
            ] if patterns_count > 0 else []),
            # ─────────────────────────────────────────────────────
            # Ряд: Назад к настройкам кросс-сообщений
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:cms:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_patterns_list_menu(
    chat_id: int,
    page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню пагинации для списка паттернов кросс-сообщений.

    Args:
        chat_id: ID группы
        page: Текущая страница (0-based)
        total_pages: Общее количество страниц

    Returns:
        InlineKeyboardMarkup: Клавиатура пагинации
    """
    buttons = []

    # ─────────────────────────────────────────────────────
    # Ряд навигации (если больше 1 страницы)
    # ─────────────────────────────────────────────────────
    if total_pages > 1:
        nav_row = []

        # Кнопка "Назад" (если не первая страница)
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"cf:cmpl:{chat_id}:{page - 1}"
                )
            )

        # Номер страницы
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cf:noop"
            )
        )

        # Кнопка "Вперёд" (если не последняя страница)
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"cf:cmpl:{chat_id}:{page + 1}"
                )
            )

        buttons.append(nav_row)

    # ─────────────────────────────────────────────────────
    # Кнопка добавления
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_ADD} Добавить паттерн",
            callback_data=f"cf:cmpa:{chat_id}"
        )
    ])

    # ─────────────────────────────────────────────────────
    # Ряд "Назад" к меню паттернов
    # ─────────────────────────────────────────────────────
    buttons.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cmp:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_cross_message_pattern_detail_menu(
    chat_id: int,
    pattern_id: int,
    is_active: bool
) -> InlineKeyboardMarkup:
    """
    Создаёт меню детали паттерна кросс-сообщений.

    Args:
        chat_id: ID группы
        pattern_id: ID паттерна
        is_active: Текущий статус активности

    Returns:
        InlineKeyboardMarkup: Клавиатура управления паттерном
    """
    # Текст кнопки вкл/выкл
    toggle_text = "⏸️ Выключить" if is_active else "▶️ Включить"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Включить/Выключить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"cf:cmpt:{pattern_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Удалить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_DELETE} Удалить",
                    callback_data=f"cf:cmpx:{pattern_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Назад к списку
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:cmpl:{chat_id}:0"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_pattern_type_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора типа паттерна.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора типа
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Тип "phrase" (подстрока)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📝 Фраза (подстрока)",
                    callback_data=f"cf:cmpty:phrase:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 2: Тип "word" (отдельное слово)
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="📖 Слово (границы)",
                    callback_data=f"cf:cmpty:word:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд 3: Тип "regex"
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="🔣 Regex",
                    callback_data=f"cf:cmpty:regex:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:cmp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_cancel_input_menu(
    chat_id: int,
    return_to: str = 'cmp'
) -> InlineKeyboardMarkup:
    """
    Создаёт меню отмены ввода (FSM) для кросс-сообщений.

    По CHECKLIST.md: кнопка должна быть "🔙 Назад", НЕ "Отмена"!

    Args:
        chat_id: ID группы
        return_to: Куда возвращаться при отмене:
            - 'cmp' = паттерны (cf:cmpcan:{chat_id}) — default
            - 'cmw' = меню окна (cf:cmw:{chat_id})
            - 'cmt' = меню порога (cf:cmt:{chat_id})
            - 'cmsta' = добавление порога (cf:cmsta:{chat_id})
            - 'cms' = настройки кросс-сообщений (cf:cms:{chat_id})

    Returns:
        InlineKeyboardMarkup: Клавиатура отмены
    """
    # Определяем callback_data в зависимости от return_to
    if return_to == 'cmp':
        callback = f"cf:cmpcan:{chat_id}"
    elif return_to == 'cmw':
        callback = f"cf:cmw:{chat_id}"
    elif return_to == 'cmt':
        callback = f"cf:cmt:{chat_id}"
    elif return_to == 'cmsta':
        callback = f"cf:cmsta:{chat_id}"
    elif return_to == 'cms':
        callback = f"cf:cms:{chat_id}"
    elif return_to == 'cmnd':
        callback = f"cf:cmnd:{chat_id}"
    elif return_to == 'cmn':
        callback = f"cf:cmn:{chat_id}"
    else:
        # По умолчанию — паттерны
        callback = f"cf:cmpcan:{chat_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=callback
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_delete_confirm_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню подтверждения удаления всех паттернов.

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура подтверждения
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # ─────────────────────────────────────────────────────
            # Ряд 1: Подтвердить
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить все",
                    callback_data=f"cf:cmpdc:{chat_id}"
                )
            ],
            # ─────────────────────────────────────────────────────
            # Ряд: Отмена
            # ─────────────────────────────────────────────────────
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Отмена",
                    callback_data=f"cf:cmp:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# КРОСС-СООБЩЕНИЕ: ПОРОГИ БАЛЛОВ (CrossMessageThreshold)
# ============================================================
# Клавиатуры для управления порогами баллов с разными действиями
# для разных диапазонов накопленного скора.
# ============================================================

def create_cross_message_score_thresholds_menu(
    chat_id: int,
    thresholds: list
) -> InlineKeyboardMarkup:
    """
    Создаёт меню списка порогов баллов.

    Args:
        chat_id: ID группы
        thresholds: Список CrossMessageThreshold объектов

    Returns:
        InlineKeyboardMarkup: Клавиатура со списком порогов
    """
    rows = []

    # Кнопка добавления нового порога
    rows.append([
        InlineKeyboardButton(
            text="➕ Добавить порог",
            callback_data=f"cf:cmsta:{chat_id}"
        )
    ])

    # Список существующих порогов
    for t in thresholds:
        # Форматируем диапазон
        if t.max_score is None:
            range_text = f"{t.min_score}+"
        else:
            range_text = f"{t.min_score}-{t.max_score}"

        # Форматируем действие
        action_map = {'mute': '🔇', 'ban': '🚫', 'kick': '👢'}
        action_emoji = action_map.get(t.action, '❓')

        # Форматируем длительность мута
        if t.action == 'mute' and t.mute_duration:
            if t.mute_duration >= 1440:
                duration_text = f"{t.mute_duration // 1440}д"
            elif t.mute_duration >= 60:
                duration_text = f"{t.mute_duration // 60}ч"
            else:
                duration_text = f"{t.mute_duration}мин"
            action_text = f"{action_emoji} {duration_text}"
        else:
            action_text = action_emoji

        # Статус активности
        status = "✅" if t.enabled else "⏸️"

        # Кнопка порога
        rows.append([
            InlineKeyboardButton(
                text=f"{status} {range_text} → {action_text}",
                callback_data=f"cf:cmste:{chat_id}:{t.id}"
            )
        ])

    # Кнопка назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cms:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_threshold_edit_menu(
    chat_id: int,
    threshold_id: int,
    threshold
) -> InlineKeyboardMarkup:
    """
    Создаёт меню редактирования порога баллов.

    Args:
        chat_id: ID группы
        threshold_id: ID порога
        threshold: Объект CrossMessageThreshold

    Returns:
        InlineKeyboardMarkup: Клавиатура редактирования
    """
    # Статус активности
    toggle_text = "⏸️ Отключить" if threshold.enabled else "✅ Включить"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Переключить активность
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"cf:cmstt:{chat_id}:{threshold_id}"
                )
            ],
            # Удалить
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить",
                    callback_data=f"cf:cmstd:{chat_id}:{threshold_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:cmst:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_add_threshold_menu(
    chat_id: int,
    step: str = 'min_score'
) -> InlineKeyboardMarkup:
    """
    Создаёт меню добавления порога — выбор минимального скора.

    Args:
        chat_id: ID группы
        step: Текущий шаг ('min_score')

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора
    """
    # Предустановленные значения минимального скора
    min_scores = [50, 75, 100, 150, 200, 300]

    rows = []

    # По 3 кнопки в ряд
    for i in range(0, len(min_scores), 3):
        row = []
        for score in min_scores[i:i+3]:
            row.append(
                InlineKeyboardButton(
                    text=f"{score}",
                    callback_data=f"cf:cmstam:{chat_id}:{score}"
                )
            )
        rows.append(row)

    # Кнопка "Другое" для кастомного ввода минимального скора
    rows.append([
        InlineKeyboardButton(
            text="✏️ Другое",
            callback_data=f"cf:cmstamc:{chat_id}"  # c = custom input
        )
    ])

    # Кнопка назад (по CHECKLIST.md: "Назад", НЕ "Отмена")
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cmst:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_add_threshold_max_menu(
    chat_id: int,
    min_score: int
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора максимального скора для порога.

    Args:
        chat_id: ID группы
        min_score: Выбранный минимальный скор

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора
    """
    # Максимальные значения относительно минимального
    max_options = [
        (min_score + 49, f"{min_score + 49}"),
        (min_score + 99, f"{min_score + 99}"),
        (min_score + 199, f"{min_score + 199}"),
        (None, "∞ (без лимита)")
    ]

    rows = []

    for max_score, text in max_options:
        max_val = max_score if max_score else 'inf'
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"cf:cmstax:{chat_id}:{min_score}:{max_val}"
            )
        ])

    # Кнопка "Другое" для кастомного ввода максимального скора
    rows.append([
        InlineKeyboardButton(
            text="✏️ Другое",
            callback_data=f"cf:cmstaxc:{chat_id}:{min_score}"  # c = custom input
        )
    ])

    # Кнопка назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cmsta:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_add_threshold_action_menu(
    chat_id: int,
    min_score: int,
    max_score
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора действия для порога.

    Args:
        chat_id: ID группы
        min_score: Минимальный скор
        max_score: Максимальный скор (или None)

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора действия
    """
    max_val = max_score if max_score else 'inf'

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Только удалить (без мута/бана)
            [
                InlineKeyboardButton(
                    text="🗑️ Только удалить",
                    callback_data=f"cf:cmstaa:{chat_id}:{min_score}:{max_val}:delete:0"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔇 Мут 30 мин",
                    callback_data=f"cf:cmstaa:{chat_id}:{min_score}:{max_val}:mute:30"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔇 Мут 2 часа",
                    callback_data=f"cf:cmstaa:{chat_id}:{min_score}:{max_val}:mute:120"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔇 Мут 1 день",
                    callback_data=f"cf:cmstaa:{chat_id}:{min_score}:{max_val}:mute:1440"
                )
            ],
            # Кастомное время мута
            [
                InlineKeyboardButton(
                    text="✏️ Другое (мут)",
                    callback_data=f"cf:cmstam_c:{chat_id}:{min_score}:{max_val}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"cf:cmstaa:{chat_id}:{min_score}:{max_val}:ban:0"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:cmstam:{chat_id}:{min_score}"
                )
            ]
        ]
    )

    return keyboard


# ============================================================
# КРОСС-СООБЩЕНИЕ: УВЕДОМЛЕНИЯ
# ============================================================
# Клавиатуры для настройки текстов уведомлений
# ============================================================

def create_cross_message_notifications_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню настройки уведомлений кросс-сообщений.

    Args:
        chat_id: ID группы
        settings: ContentFilterSettings

    Returns:
        InlineKeyboardMarkup: Клавиатура настроек уведомлений
    """
    # Получаем текущие значения
    mute_text = getattr(settings, 'cross_message_mute_text', None) if settings else None
    ban_text = getattr(settings, 'cross_message_ban_text', None) if settings else None
    delete_delay = getattr(settings, 'cross_message_notification_delete_delay', None) if settings else None

    # Статусы
    mute_status = "✅" if mute_text else "❌"
    ban_status = "✅" if ban_text else "❌"
    delay_text = f"{delete_delay}сек" if delete_delay else "Выкл"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            # Текст при муте
            [
                InlineKeyboardButton(
                    text=f"{mute_status} Текст мута",
                    callback_data=f"cf:cmnm:{chat_id}"
                )
            ],
            # Текст при бане
            [
                InlineKeyboardButton(
                    text=f"{ban_status} Текст бана",
                    callback_data=f"cf:cmnb:{chat_id}"
                )
            ],
            # Автоудаление
            [
                InlineKeyboardButton(
                    text=f"🕐 Автоудаление: {delay_text}",
                    callback_data=f"cf:cmnd:{chat_id}"
                )
            ],
            # Назад
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    callback_data=f"cf:cms:{chat_id}"
                )
            ]
        ]
    )

    return keyboard


def create_cross_message_notification_delay_menu(
    chat_id: int,
    settings
) -> InlineKeyboardMarkup:
    """
    Создаёт меню выбора задержки автоудаления уведомления.

    Args:
        chat_id: ID группы
        settings: ContentFilterSettings

    Returns:
        InlineKeyboardMarkup: Клавиатура выбора задержки
    """
    current = getattr(settings, 'cross_message_notification_delete_delay', None) if settings else None

    # Варианты задержки
    delays = [
        (None, "Выключено"),
        (10, "10 сек"),
        (30, "30 сек"),
        (60, "1 мин"),
        (120, "2 мин"),
        (300, "5 мин")
    ]

    rows = []
    # Флаг: текущее значение есть в списке?
    delay_values = [d[0] for d in delays]
    current_in_list = current in delay_values

    for delay, text in delays:
        # Отметка текущего значения
        marker = " ✓" if delay == current else ""
        delay_val = delay if delay else 0

        rows.append([
            InlineKeyboardButton(
                text=f"{text}{marker}",
                callback_data=f"cf:cmnds:{chat_id}:{delay_val}"
            )
        ])

    # Кнопка "Другое" для кастомного ввода
    if not current_in_list and current is not None:
        other_text = f"✏️ Другое (✓ {current}сек)"
    else:
        other_text = "✏️ Другое"

    rows.append([
        InlineKeyboardButton(
            text=other_text,
            callback_data=f"cf:cmndc:{chat_id}"  # c = custom input
        )
    ])

    # Назад
    rows.append([
        InlineKeyboardButton(
            text=f"{EMOJI_BACK} Назад",
            callback_data=f"cf:cmn:{chat_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_cross_message_notification_text_back_menu(
    chat_id: int
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой "Назад" для FSM ввода текста уведомления.

    По CHECKLIST.md: кнопка должна быть "🔙 Назад", НЕ "Отмена"!

    Args:
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой назад
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{EMOJI_BACK} Назад",
                    # Специальный callback для очистки FSM состояния
                    callback_data=f"cf:cmnc:{chat_id}"
                )
            ]
        ]
    )
