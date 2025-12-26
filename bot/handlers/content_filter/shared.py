# ============================================================
# SHARED - ОБЩИЕ ОБЪЕКТЫ ДЛЯ CONTENT FILTER ХЕНДЛЕРОВ
# ============================================================
# Этот модуль содержит общие объекты, которые используются
# всеми хендлерами content_filter:
# - filter_manager: FilterManager с Redis для FloodDetector
# - logger: логгер модуля
#
# Вынесено для избежания циклических импортов и дублирования.
# ============================================================

# Импортируем логгер
import logging

# Импортируем FilterManager и сервисы
from bot.services.content_filter import FilterManager
# Импортируем Redis клиент для FloodDetector
from bot.services.redis_conn import redis

# Создаём логгер для модуля настроек
logger = logging.getLogger(__name__)

# Глобальный FilterManager с Redis для FloodDetector
# Используется всеми хендлерами content_filter
filter_manager = FilterManager(redis=redis)
