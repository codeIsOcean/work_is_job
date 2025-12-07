# ============================================================
# МОДУЛЬ CONTENT FILTER - HANDLERS
# ============================================================
# Этот модуль содержит все обработчики событий для фильтра контента:
# - filter_handler: фильтрация сообщений в группах
# - settings_handler: UI настроек через callback query
# ============================================================

# Импортируем Router из aiogram для создания группы хендлеров
from aiogram import Router

# Создаём главный роутер модуля content_filter
# Все хендлеры модуля будут подключены к этому роутеру
content_filter_router = Router(name='content_filter')

# Импортируем роутеры подмодулей
# filter_handler - обработка сообщений в группах
from bot.handlers.content_filter.filter_handler import filter_handler_router
# settings_handler - обработка callback query для настроек
from bot.handlers.content_filter.settings_handler import settings_handler_router

# Подключаем роутеры подмодулей к главному роутеру
# Порядок важен: сначала settings (callback), потом filter (messages)
content_filter_router.include_router(settings_handler_router)
content_filter_router.include_router(filter_handler_router)

# Экспортируем главный роутер
__all__ = ['content_filter_router']
