# bot/handlers/cross_group/__init__.py
"""
Модуль хендлеров кросс-групповой детекции скамеров.

Содержит:
- settings_handler.py - UI настроек в ЛС бота
- callbacks_handler.py - обработка кнопок в журнале

ВАЖНО: Функции трекинга вызываются из других модулей:
- track_user_join() вызывается из profile_monitor/join_handler.py
- track_profile_change() вызывается из profile_monitor/monitor_handler.py
- track_user_message() вызывается из group_message_coordinator.py
"""

# Импортируем Router из aiogram
from aiogram import Router

# Импортируем роутеры из хендлеров
from bot.handlers.cross_group.settings_handler import router as settings_router
from bot.handlers.cross_group.callbacks_handler import router as callbacks_router

# Создаём главный роутер модуля
router = Router(name="cross_group")

# Включаем роутеры с хендлерами
router.include_router(settings_router)
router.include_router(callbacks_router)

# Экспортируем роутер
__all__ = ['router']