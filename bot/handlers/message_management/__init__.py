# ============================================================
# МОДУЛЬ "УПРАВЛЕНИЕ СООБЩЕНИЯМИ" - HANDLERS
# ============================================================
# Этот модуль содержит обработчики событий для функционала
# управления сообщениями:
# - settings_handler: UI настроек через callback query
# - command_handler: Команды /repin, /unrepin
# - filter_handler: Фильтрация сообщений в группах
#
# Модуль объединяет все роутеры в один для подключения
# к главному роутеру приложения.
# ============================================================

# Импортируем Router из aiogram для создания группы хендлеров
from aiogram import Router

# Создаём главный роутер модуля message_management
# Этот роутер объединяет все подроутеры модуля
message_management_router = Router(name='message_management')

# ─────────────────────────────────────────────────────────
# ИМПОРТ ПОДРОУТЕРОВ
# ─────────────────────────────────────────────────────────

# Импортируем роутер настроек UI (callback query хендлеры)
from bot.handlers.message_management.settings_handler import mm_settings_router

# Импортируем роутер команд (/repin, /unrepin)
from bot.handlers.message_management.command_handler import mm_command_router

# Импортируем роутер фильтрации сообщений
from bot.handlers.message_management.filter_handler import mm_filter_router

# ─────────────────────────────────────────────────────────
# ПОДКЛЮЧЕНИЕ ПОДРОУТЕРОВ
# ─────────────────────────────────────────────────────────

# Подключаем роутер настроек (callback query для UI)
message_management_router.include_router(mm_settings_router)

# Подключаем роутер команд (/repin, /unrepin в группах)
message_management_router.include_router(mm_command_router)

# Подключаем роутер фильтрации
# (удаление команд, системных сообщений, репин)
message_management_router.include_router(mm_filter_router)

# ─────────────────────────────────────────────────────────
# ЭКСПОРТ
# ─────────────────────────────────────────────────────────

# Экспортируем главный роутер модуля
__all__ = ['message_management_router']
