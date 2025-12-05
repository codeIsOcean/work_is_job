# Инициализационный файл для пакета antispam handlers
# Импортируем роутер настроек для регистрации в главном диспетчере
from .antispam_settings_handler import antispam_router
# Импортируем роутер фильтрации сообщений для проверки на спам
from .antispam_filter_handler import antispam_filter_router

# Определяем список экспортируемых имен
__all__ = ["antispam_router", "antispam_filter_router"]
