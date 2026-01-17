# ============================================================
# МОДУЛЬ ANTI-RAID: ЗАЩИТА ОТ МАССОВЫХ АТАК
# ============================================================
# Этот модуль защищает группу от различных типов атак:
# 1. Частые входы/выходы (join/exit abuse) — боты засвечивают имя
# 2. Бан по паттернам имени (name pattern ban) — педо-контент и т.д.
# 3. Массовые вступления (mass join / raid) — координированные атаки
# 4. Массовые инвайты (mass invite) — один юзер приглашает много людей
# 5. Массовые реакции (mass reaction) — спам реакциями
#
# Все настройки гибкие — админ может менять через UI (без хардкода!)
# ============================================================

# Экспортируем функции для работы с настройками
from bot.services.antiraid.settings_service import (
    # CRUD для настроек группы
    get_antiraid_settings,
    get_or_create_antiraid_settings,
    update_antiraid_settings,
    # CRUD для паттернов имён
    get_name_patterns,
    get_enabled_name_patterns,
    add_name_pattern,
    remove_name_pattern,
    toggle_name_pattern,
)

# Экспортируем функции проверки имени по паттернам
from bot.services.antiraid.name_pattern_checker import (
    # Результат проверки имени (dataclass)
    NameCheckResult,
    # Основная функция проверки имени
    check_name_against_patterns,
    # Упрощённая обёртка (True/False)
    is_name_banned,
    # Вспомогательные функции
    get_full_name,
    normalize_name,
)

# Экспортируем функции применения действий
from bot.services.antiraid.action_service import (
    # Результат действия (dataclass)
    ActionResult,
    # Базовые действия
    ban_user,
    kick_user,
    mute_user,
    decline_join_request,
    # Главная функция применения действия по настройкам
    apply_name_pattern_action,
    # Функция применения действия для join/exit
    apply_join_exit_action,
)

# Экспортируем функции отправки в журнал
from bot.services.antiraid.journal_service import (
    # Уведомление о бане по имени
    send_name_pattern_journal,
    # Уведомление о частых входах/выходах
    send_join_exit_journal,
    # Уведомление о детекции рейда
    send_raid_detected_journal,
)

# Экспортируем трекер входов/выходов
from bot.services.antiraid.join_exit_tracker import (
    # Результат проверки (NamedTuple)
    JoinExitCheckResult,
    # Класс трекера
    JoinExitTracker,
    # Главная функция проверки (с настройками из БД)
    check_join_exit_abuse,
    # Фабричная функция
    create_join_exit_tracker,
)

# Список публичных экспортов модуля
__all__ = [
    # ─────────────────────────────────────────────────────────
    # Настройки (settings_service)
    # ─────────────────────────────────────────────────────────
    'get_antiraid_settings',
    'get_or_create_antiraid_settings',
    'update_antiraid_settings',
    # Паттерны имён
    'get_name_patterns',
    'get_enabled_name_patterns',
    'add_name_pattern',
    'remove_name_pattern',
    'toggle_name_pattern',
    # ─────────────────────────────────────────────────────────
    # Проверка имени (name_pattern_checker)
    # ─────────────────────────────────────────────────────────
    'NameCheckResult',
    'check_name_against_patterns',
    'is_name_banned',
    'get_full_name',
    'normalize_name',
    # ─────────────────────────────────────────────────────────
    # Применение действий (action_service)
    # ─────────────────────────────────────────────────────────
    'ActionResult',
    'ban_user',
    'kick_user',
    'mute_user',
    'decline_join_request',
    'apply_name_pattern_action',
    'apply_join_exit_action',
    # ─────────────────────────────────────────────────────────
    # Журнал (journal_service)
    # ─────────────────────────────────────────────────────────
    'send_name_pattern_journal',
    'send_join_exit_journal',
    'send_raid_detected_journal',
    # ─────────────────────────────────────────────────────────
    # Трекер входов/выходов (join_exit_tracker)
    # ─────────────────────────────────────────────────────────
    'JoinExitCheckResult',
    'JoinExitTracker',
    'check_join_exit_abuse',
    'create_join_exit_tracker',
]
