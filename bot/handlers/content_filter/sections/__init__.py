# ============================================================
# SECTIONS - МОДУЛЬ КАСТОМНЫХ РАЗДЕЛОВ СПАМА
# ============================================================
# Этот модуль содержит хендлеры для управления кастомными разделами:
# - menu.py: список разделов, создание
# - settings.py: настройки раздела
# - action.py: выбор действия и пересылки
# - patterns.py: управление паттернами раздела
# - thresholds.py: пороги баллов раздела
# - advanced.py: расширенные настройки (тексты, задержки)
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router
from aiogram import Router

# Создаём главный роутер модуля
sections_router = Router(name='sections')

# Импортируем дочерние роутеры
from bot.handlers.content_filter.sections.menu import menu_router
from bot.handlers.content_filter.sections.settings import settings_router
from bot.handlers.content_filter.sections.action import action_router
from bot.handlers.content_filter.sections.patterns import patterns_router
from bot.handlers.content_filter.sections.thresholds import thresholds_router
from bot.handlers.content_filter.sections.advanced import advanced_router

# Подключаем дочерние роутеры
sections_router.include_router(menu_router)
sections_router.include_router(settings_router)
sections_router.include_router(action_router)
sections_router.include_router(patterns_router)
sections_router.include_router(thresholds_router)
sections_router.include_router(advanced_router)

# Экспортируем главный роутер
__all__ = ['sections_router']
