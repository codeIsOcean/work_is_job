# ============================================================
# МОДУЛЬ SCAM MEDIA FILTER - ФИЛЬТР СКАМ-ФОТО
# ============================================================
# Этот модуль обнаруживает и блокирует повторяющиеся скам-фото
# используя perceptual hashing (pHash + dHash).
#
# Компоненты модуля:
# - hash_service.py: вычисление и сравнение хешей изображений
# - filter_manager.py: координация фильтрации и применение действий
# - db_service.py: операции с базой данных хешей
#
# Интеграция:
# - Вызывается из group_message_coordinator.py
# - НЕ является частью content_filter (отдельный модуль)
# ============================================================

# Экспортируем основные классы и функции для удобного импорта
# from bot.services.scam_media import HashService, compute_image_hash
from .hash_service import (
    HashService,
    compute_image_hash,
    compare_hashes,
    compute_logo_hash,
    get_available_logo_regions,
    ImageHashes,
    LOGO_REGIONS,
)

# Экспортируем сервисы работы с БД
from .db_service import (
    SettingsService,
    BannedHashService,
    ViolationService,
)

# Экспортируем менеджер фильтрации
from .filter_manager import (
    ScamMediaFilterManager,
    MatchResult,
    FilterResult,
)