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
    # Действия для рейд-защиты
    set_slowmode,
    remove_slowmode,
    lock_group,
    unlock_group,
    apply_raid_action,
    # Действие для массовых инвайтов
    apply_mass_invite_action,
    # Действие для массовых реакций
    apply_mass_reaction_action,
)

# Экспортируем функции отправки в журнал
from bot.services.antiraid.journal_service import (
    # Уведомление о бане по имени
    send_name_pattern_journal,
    # Уведомление о частых входах/выходах
    send_join_exit_journal,
    # Уведомление о детекции рейда (агрегированное)
    send_raid_detected_journal,
    # Обновление агрегированного уведомления о рейде
    update_raid_journal,
    # Уведомление о массовых инвайтах
    send_mass_invite_journal,
    # Уведомление о массовых реакциях
    send_mass_reaction_journal,
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

# Экспортируем трекер массовых вступлений (рейд-детектор) v2
from bot.services.antiraid.mass_join_tracker import (
    # Результат проверки (NamedTuple)
    MassJoinCheckResult,
    # Класс трекера
    MassJoinTracker,
    # Главная функция проверки (с настройками из БД)
    check_mass_join,
    # Функции управления protection mode (v2)
    is_protection_active,
    deactivate_protection,
    get_protection_ttl,
    activate_protection,
    activate_raid_mode,  # алиас для обратной совместимости
    # Фабричная функция
    create_mass_join_tracker,
)

# Экспортируем трекер массовых инвайтов
from bot.services.antiraid.mass_invite_tracker import (
    # Результат проверки (NamedTuple)
    MassInviteCheckResult,
    # Класс трекера
    MassInviteTracker,
    # Главная функция проверки (с настройками из БД)
    check_mass_invite,
    # Фабричная функция
    create_mass_invite_tracker,
)

# Экспортируем трекер массовых реакций
from bot.services.antiraid.mass_reaction_tracker import (
    # Результат проверки (NamedTuple)
    MassReactionCheckResult,
    # Класс трекера
    MassReactionTracker,
    # Главная функция проверки (с настройками из БД)
    check_mass_reaction,
    # Фабричная функция
    create_mass_reaction_tracker,
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
    # Действия для рейд-защиты
    'set_slowmode',
    'remove_slowmode',
    'lock_group',
    'unlock_group',
    'apply_raid_action',
    # Действие для массовых инвайтов
    'apply_mass_invite_action',
    # Действие для массовых реакций
    'apply_mass_reaction_action',
    # ─────────────────────────────────────────────────────────
    # Журнал (journal_service)
    # ─────────────────────────────────────────────────────────
    'send_name_pattern_journal',
    'send_join_exit_journal',
    'send_raid_detected_journal',
    'update_raid_journal',
    'send_mass_invite_journal',
    'send_mass_reaction_journal',
    # ─────────────────────────────────────────────────────────
    # Трекер входов/выходов (join_exit_tracker)
    # ─────────────────────────────────────────────────────────
    'JoinExitCheckResult',
    'JoinExitTracker',
    'check_join_exit_abuse',
    'create_join_exit_tracker',
    # ─────────────────────────────────────────────────────────
    # Трекер массовых вступлений (mass_join_tracker) v2
    # ─────────────────────────────────────────────────────────
    'MassJoinCheckResult',
    'MassJoinTracker',
    'check_mass_join',
    # Функции protection mode (v2)
    'is_protection_active',
    'deactivate_protection',
    'get_protection_ttl',
    'activate_protection',
    'activate_raid_mode',
    'create_mass_join_tracker',
    # ─────────────────────────────────────────────────────────
    # Трекер массовых инвайтов (mass_invite_tracker)
    # ─────────────────────────────────────────────────────────
    'MassInviteCheckResult',
    'MassInviteTracker',
    'check_mass_invite',
    'create_mass_invite_tracker',
    # ─────────────────────────────────────────────────────────
    # Трекер массовых реакций (mass_reaction_tracker)
    # ─────────────────────────────────────────────────────────
    'MassReactionCheckResult',
    'MassReactionTracker',
    'check_mass_reaction',
    'create_mass_reaction_tracker',
]
