# bot/handlers/profile_monitor/__init__.py
"""
Модуль Profile Monitor - обработчики для мониторинга профилей.

Содержит:
- monitor_handler.py - функция проверки профиля (вызывается из coordinator)
- callbacks_handler.py - обработка кнопок в журнале
- settings_handler.py - настройки в ЛС бота

ВАЖНО: monitor_handler НЕ является самостоятельным хендлером!
Функция process_message_profile_check() вызывается напрямую
из group_message_coordinator.py для избежания конфликта хендлеров.
"""

from aiogram import Router

# НЕ импортируем monitor_router - он пустой и вызывается из coordinator
from bot.handlers.profile_monitor.callbacks_handler import router as callbacks_router
from bot.handlers.profile_monitor.settings_handler import router as settings_router

# Главный роутер модуля
# Содержит только callbacks и settings (UI в ЛС бота)
router = Router(name="profile_monitor")

# Включаем только роутеры с реальными хендлерами
# monitor_handler вызывается из coordinator, а не через роутер
router.include_router(callbacks_router)
router.include_router(settings_router)

__all__ = ['router']
