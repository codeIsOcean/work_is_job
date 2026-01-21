# ============================================================
# МОДУЛЬ CONTENT FILTER - HANDLERS
# ============================================================
# Этот модуль содержит обработчики событий для фильтра контента.
#
# Структура модуля (после рефакторинга по Правилу 30 - SRP):
# - main_menu.py: главное меню настроек
# - word_filter/: настройки фильтра слов
# - scam/: настройки скам-детектора
# - flood/: настройки антифлуда
# - sections/: кастомные разделы
# - cleanup.py: настройки очистки
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

# ============================================================
# ИМПОРТ РОУТЕРОВ ИЗ ПОДМОДУЛЕЙ
# ============================================================

# Главное меню настроек
from bot.handlers.content_filter.main_menu import main_menu_router

# Модуль word_filter - настройки фильтра слов
from bot.handlers.content_filter.word_filter import word_filter_router

# Модуль scam - настройки скам-детектора
from bot.handlers.content_filter.scam import scam_router

# Модуль flood - настройки антифлуда
from bot.handlers.content_filter.flood import flood_router

# Модуль sections - кастомные разделы
from bot.handlers.content_filter.sections import sections_router

# Модуль cleanup - настройки очистки
from bot.handlers.content_filter.cleanup import cleanup_router

# Callback обработчики для кнопок журнала кросс-сообщений
from bot.handlers.content_filter.crossmsg_callbacks import crossmsg_callbacks_router

# ============================================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ
# ============================================================
# ПРИМЕЧАНИЕ: filter_handler_router НЕ подключаем - он в координаторе

content_filter_router.include_router(main_menu_router)
content_filter_router.include_router(word_filter_router)
content_filter_router.include_router(scam_router)
content_filter_router.include_router(flood_router)
content_filter_router.include_router(sections_router)
content_filter_router.include_router(cleanup_router)
content_filter_router.include_router(crossmsg_callbacks_router)

# Экспортируем главный роутер
__all__ = ['content_filter_router']
