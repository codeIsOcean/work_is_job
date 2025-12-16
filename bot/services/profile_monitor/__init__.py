# bot/services/profile_monitor/__init__.py
"""
Модуль Profile Monitor - мониторинг изменений профиля пользователей.

Отслеживает изменения:
- Имени (first_name, last_name)
- Username (@username)
- Фото профиля

Автоматические действия:
- Мут пользователей без фото с молодым аккаунтом
- Мут при смене имени + быстрых сообщениях без фото
- Удаление всех сообщений спаммеров
"""

from bot.services.profile_monitor.profile_monitor_service import (
    get_profile_monitor_settings,
    create_or_update_settings,
    create_profile_snapshot,
    create_snapshot_on_join,
    get_profile_snapshot,
    update_profile_snapshot,
    check_profile_changes,
    log_profile_change,
    get_user_change_history,
    check_auto_mute_criteria,
    apply_auto_mute,
    delete_user_messages,
    track_user_message,
)

__all__ = [
    'get_profile_monitor_settings',
    'create_or_update_settings',
    'create_profile_snapshot',
    'create_snapshot_on_join',
    'get_profile_snapshot',
    'update_profile_snapshot',
    'check_profile_changes',
    'log_profile_change',
    'get_user_change_history',
    'check_auto_mute_criteria',
    'apply_auto_mute',
    'delete_user_messages',
    'track_user_message',
]
