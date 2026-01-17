# ============================================================
# ОБРАБОТЧИКИ ANTI-RAID
# ============================================================
# Роутеры для обработки событий модуля Anti-Raid:
# - Callback кнопки в журнале (разбан, OK, и т.д.)
# - Обработка выходов из группы (join_exit_tracker)
# - Обработка реакций на сообщения (mass_reaction)
# - UI настроек в ЛС бота
# ============================================================

# Импортируем роутер callback обработчиков
from bot.handlers.antiraid.journal_callbacks import antiraid_callbacks_router

# Импортируем роутер событий входа/выхода
from bot.handlers.antiraid.join_exit_handler import (
    join_exit_router,
    track_join_event,  # Функция для вызова из captcha_coordinator
    track_mass_join,   # Функция для детекции рейда
    track_mass_invite,  # Функция для детекции массовых инвайтов
)

# Импортируем роутер событий реакций
from bot.handlers.antiraid.reaction_handler import (
    reaction_router,
    track_reaction,  # Функция для вызова из других мест
)

# Импортируем роутер настроек Anti-Raid (UI в ЛС)
from bot.handlers.antiraid.settings_handler import antiraid_settings_router

# Список публичных экспортов
__all__ = [
    'antiraid_callbacks_router',
    'antiraid_settings_router',
    'join_exit_router',
    'reaction_router',
    'track_join_event',
    'track_mass_join',
    'track_mass_invite',
    'track_reaction',
]
