# ============================================================
# ХЕНДЛЕРЫ ЭКСПОРТА/ИМПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль содержит обработчики для:
# - Команды /export_settings и /import_settings
# - UI кнопки в меню настроек
# - FSM для процесса импорта
#
# Все хендлеры работают в ЛС бота (private chat)
# ============================================================

# Импортируем Router для создания единого роутера модуля
from aiogram import Router

# Импортируем роутеры из подмодулей
from bot.handlers.settings_export.export_handlers import export_router
from bot.handlers.settings_export.import_handlers import import_router

# Создаём главный роутер модуля
settings_export_router = Router(name="settings_export")

# Подключаем роутеры подмодулей
settings_export_router.include_router(export_router)
settings_export_router.include_router(import_router)

# Экспортируем главный роутер для подключения в handlers/__init__.py
__all__ = ['settings_export_router']
