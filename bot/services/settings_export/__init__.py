# ============================================================
# МОДУЛЬ ЭКСПОРТА/ИМПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль предоставляет функционал для:
# - Экспорта всех настроек группы в JSON файл
# - Импорта настроек из JSON файла в другую группу
# - Проверки прав доступа (только владелец или полный админ)
#
# Расширяемая архитектура через реестр таблиц (TABLE_REGISTRY)
# Для добавления новой таблицы достаточно зарегистрировать её в реестре
# ============================================================

# Экспортируем основные функции для использования из других модулей
from bot.services.settings_export.export_service import (
    # Функция экспорта настроек группы в словарь
    export_group_settings,
    # Функция импорта настроек из словаря в группу
    import_group_settings,
    # Функция сериализации настроек в JSON строку
    serialize_settings_to_json,
    # Функция десериализации настроек из JSON строки
    deserialize_settings_from_json,
)

# Экспортируем функции проверки прав доступа
from bot.services.settings_export.permissions import (
    # Проверка: является ли пользователь владельцем группы
    is_chat_owner,
    # Проверка: имеет ли пользователь ВСЕ права администратора
    has_full_admin_rights,
    # Комбинированная проверка: владелец ИЛИ полный админ
    can_export_import_settings,
)

# Экспортируем реестр таблиц для расширяемости
from bot.services.settings_export.export_service import TABLE_REGISTRY

# Список всех публичных символов модуля
__all__ = [
    # Функции экспорта/импорта
    'export_group_settings',
    'import_group_settings',
    'serialize_settings_to_json',
    'deserialize_settings_from_json',
    # Функции проверки прав
    'is_chat_owner',
    'has_full_admin_rights',
    'can_export_import_settings',
    # Реестр таблиц
    'TABLE_REGISTRY',
]
