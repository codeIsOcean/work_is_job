# ============================================================
# МОДУЛЬ ЭКСПОРТА/ИМПОРТА НАСТРОЕК ГРУППЫ (v2.0)
# ============================================================
# Этот модуль предоставляет функционал для:
# - Экспорта всех настроек группы в JSON файл
# - Импорта настроек из JSON файла в другую группу
# - Проверки прав доступа (только владелец или полный админ)
#
# Архитектура v2.0: модели с ExportableMixin автоматически
# регистрируются для экспорта. Добавьте миксин к модели
# и она автоматически появится в экспорте.
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
    # Функция валидации данных перед импортом
    validate_import_data,
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

# Экспортируем функции работы с реестром моделей
from bot.database.exportable_mixin import (
    # Получить список всех экспортируемых моделей
    get_exportable_models,
    # Найти модель по ключу экспорта
    get_model_by_export_key,
)

# Список всех публичных символов модуля
__all__ = [
    # Функции экспорта/импорта
    'export_group_settings',
    'import_group_settings',
    'serialize_settings_to_json',
    'deserialize_settings_from_json',
    'validate_import_data',
    # Функции проверки прав
    'is_chat_owner',
    'has_full_admin_rights',
    'can_export_import_settings',
    # Реестр моделей
    'get_exportable_models',
    'get_model_by_export_key',
]
