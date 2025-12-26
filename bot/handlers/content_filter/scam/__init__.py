# ============================================================
# SCAM - МОДУЛЬ АНТИСКАМА
# ============================================================
# Этот модуль содержит хендлеры для управления антискамом:
# - settings.py: настройки антискама (действия, чувствительность)
# - patterns.py: паттерны скама (добавление, удаление, импорт)
# - thresholds.py: пороги баллов для разных действий
# - base_signals.py: настройка базовых сигналов детектора
#
# Вынесено из settings_handler.py для соблюдения SRP (Правило 30)
# ============================================================

# Импортируем Router
from aiogram import Router

# Создаём главный роутер модуля
scam_router = Router(name='scam')

# Импортируем дочерние роутеры
from bot.handlers.content_filter.scam.settings import settings_router
from bot.handlers.content_filter.scam.patterns import patterns_router
from bot.handlers.content_filter.scam.thresholds import thresholds_router
from bot.handlers.content_filter.scam.base_signals import base_signals_router

# Подключаем дочерние роутеры
scam_router.include_router(settings_router)
scam_router.include_router(patterns_router)
scam_router.include_router(thresholds_router)
scam_router.include_router(base_signals_router)

# Экспортируем главный роутер
__all__ = ['scam_router']