# ============================================================
# МОДУЛЬ CONTENT FILTER - ИНИЦИАЛИЗАЦИЯ
# ============================================================
# Этот модуль предоставляет функциональность фильтрации контента:
# - text_normalizer: нормализация текста (l33tspeak, разделители)
# - word_filter: проверка на запрещённые слова
# - scam_detector: эвристический детектор скама
# - flood_detector: детектор повторяющихся сообщений
# - filter_manager: координатор всех подмодулей
# ============================================================

# Импортируем основные компоненты для удобного доступа извне
# Пример: from bot.services.content_filter import FilterManager
from bot.services.content_filter.text_normalizer import TextNormalizer
from bot.services.content_filter.word_filter import WordFilter
from bot.services.content_filter.filter_manager import FilterManager

# Импортируем детекторы Phase 2
from bot.services.content_filter.scam_detector import ScamDetector, get_scam_detector
from bot.services.content_filter.flood_detector import FloodDetector, create_flood_detector

# Импортируем сервис кастомных паттернов скама
from bot.services.content_filter.scam_pattern_service import (
    ScamPatternService,
    get_pattern_service
)

# Импортируем сервис кросс-сообщение детекции
from bot.services.content_filter.cross_message_service import (
    CrossMessageService,
    create_cross_message_service,
    get_cross_message_service
)

# Экспортируем публичные компоненты модуля
# __all__ определяет что будет импортировано при "from module import *"
__all__ = [
    # Базовые компоненты
    'TextNormalizer',
    'WordFilter',
    'FilterManager',
    # Детекторы Phase 2
    'ScamDetector',
    'get_scam_detector',
    'FloodDetector',
    'create_flood_detector',
    # Сервис кастомных паттернов
    'ScamPatternService',
    'get_pattern_service',
    # Сервис кросс-сообщение детекции
    'CrossMessageService',
    'create_cross_message_service',
    'get_cross_message_service',
]
