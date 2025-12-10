# ============================================================
# МОДУЛЬ CONTENT FILTER - HANDLERS
# ============================================================
# Этот модуль содержит обработчики событий для фильтра контента:
# - settings_handler: UI настроек через callback query
#
# ВАЖНО: filter_handler (фильтрация сообщений) перенесён в
# group_message_coordinator.py для решения конфликта хендлеров.
# Подробнее в docs/ARCHITECTURE.md
# ============================================================

# Импортируем Router из aiogram для создания группы хендлеров
from aiogram import Router

# Создаём главный роутер модуля content_filter
# Этот роутер содержит только UI настроек (callback query)
content_filter_router = Router(name='content_filter')

# Импортируем роутер настроек
# settings_handler - обработка callback query для настроек UI
from bot.handlers.content_filter.settings_handler import settings_handler_router

# Подключаем роутер настроек к главному роутеру
# ПРИМЕЧАНИЕ: filter_handler_router НЕ подключаем - он в координаторе
content_filter_router.include_router(settings_handler_router)

# Экспортируем главный роутер
__all__ = ['content_filter_router']
