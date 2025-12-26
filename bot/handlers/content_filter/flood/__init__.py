# ============================================================
# FLOOD - МОДУЛЬ АНТИФЛУДА
# ============================================================
# Этот модуль содержит хендлеры для управления антифлудом:
# - settings.py: основные настройки (max_repeats, time_window)
# - action.py: выбор действия при срабатывании
# - advanced.py: расширенные настройки (тексты, задержки, "любые сообщения")
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router
from aiogram import Router

# Создаём главный роутер модуля
flood_router = Router(name='flood')

# Импортируем дочерние роутеры
from bot.handlers.content_filter.flood.settings import settings_router
from bot.handlers.content_filter.flood.action import action_router
from bot.handlers.content_filter.flood.advanced import advanced_router

# Подключаем дочерние роутеры
flood_router.include_router(settings_router)
flood_router.include_router(action_router)
flood_router.include_router(advanced_router)

# Экспортируем главный роутер
__all__ = ['flood_router']
