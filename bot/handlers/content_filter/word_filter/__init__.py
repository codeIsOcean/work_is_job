# ============================================================
# WORD FILTER - МОДУЛЬ ФИЛЬТРА СЛОВ
# ============================================================
# Этот модуль содержит хендлеры для управления фильтром слов:
# - settings.py: настройки фильтра слов и категорий
# - words.py: добавление/удаление слов (deprecated - используйте categories)
# - categories.py: управление словами по категориям
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router
from aiogram import Router

# Создаём главный роутер модуля
word_filter_router = Router(name='word_filter')

# Импортируем дочерние роутеры
from bot.handlers.content_filter.word_filter.settings import settings_router
from bot.handlers.content_filter.word_filter.words import words_router
from bot.handlers.content_filter.word_filter.categories import categories_router

# Подключаем дочерние роутеры
word_filter_router.include_router(settings_router)
word_filter_router.include_router(words_router)
word_filter_router.include_router(categories_router)

# Экспортируем главный роутер
__all__ = ['word_filter_router']
