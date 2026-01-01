# Инициализационный файл для пакета antispam handlers
# Импортируем роутер настроек для регистрации в главном диспетчере
from .antispam_settings_handler import antispam_router
# Импортируем роутер фильтрации сообщений для проверки на спам
from .antispam_filter_handler import antispam_filter_router
# Импортируем роутер обработки кнопок действий из журнала антиспам
from .antispam_journal_actions import antispam_journal_actions_router

# Определяем список экспортируемых имен
__all__ = ["antispam_router", "antispam_filter_router", "antispam_journal_actions_router"]
