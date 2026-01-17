# ============================================================
# ОБРАБОТЧИКИ ANTI-RAID
# ============================================================
# Роутеры для обработки событий модуля Anti-Raid:
# - Callback кнопки в журнале (разбан, OK, и т.д.)
# - Обработка выходов из группы (join_exit_tracker)
# - (Будет добавлено) UI настроек в ЛС
# ============================================================

# Импортируем роутер callback обработчиков
from bot.handlers.antiraid.journal_callbacks import antiraid_callbacks_router

# Импортируем роутер событий входа/выхода
from bot.handlers.antiraid.join_exit_handler import (
    join_exit_router,
    track_join_event,  # Функция для вызова из captcha_coordinator
)

# Список публичных экспортов
__all__ = [
    'antiraid_callbacks_router',
    'join_exit_router',
    'track_join_event',
]
