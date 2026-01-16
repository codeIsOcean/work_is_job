# bot/services/cross_group/__init__.py
"""
Модуль кросс-групповой детекции скамеров.

Содержит:
- settings_service.py - CRUD настроек модуля
- detection_service.py - логика детекции скамеров
- action_service.py - применение действий (мут/бан/удаление)

Критерии детекции (ВСЕ должны выполниться):
1. Вход в 2+ группы в настраиваемом интервале
2. Смена профиля (имя ИЛИ фото) в настраиваемом окне
3. Сообщения в 2+ группах в настраиваемом интервале
"""

# Импортируем сервисы для удобного доступа извне модуля
from bot.services.cross_group.settings_service import (
    get_cross_group_settings,
    update_cross_group_settings,
    toggle_cross_group_detection,
    add_excluded_group,
    remove_excluded_group,
)

from bot.services.cross_group.detection_service import (
    track_user_join,
    track_profile_change,
    track_user_message,
    check_cross_group_detection,
    get_user_activity,
    clear_old_activity,
)

from bot.services.cross_group.action_service import (
    apply_cross_group_action,
    send_journal_notification,
)

__all__ = [
    # Settings
    'get_cross_group_settings',
    'update_cross_group_settings',
    'toggle_cross_group_detection',
    'add_excluded_group',
    'remove_excluded_group',
    # Detection
    'track_user_join',
    'track_profile_change',
    'track_user_message',
    'check_cross_group_detection',
    'get_user_activity',
    'clear_old_activity',
    # Action
    'apply_cross_group_action',
    'send_journal_notification',
]
