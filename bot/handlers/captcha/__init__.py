# bot/handlers/captcha/__init__.py
"""
Модуль хендлеров капчи - единая точка входа для всех событий капчи.

Архитектура:
- captcha_coordinator.py - ЕДИНАЯ ТОЧКА ВХОДА (single entry point)
- captcha_callbacks.py - обработка callback кнопок
- captcha_keyboards.py - клавиатуры для капчи и настроек

Принцип работы:
1. Координатор перехватывает chat_join_request и new_chat_members
2. Определяет нужный режим капчи через сервис
3. Вызывает соответствующую логику из services/captcha/
4. Callback обработчики обрабатывают нажатия кнопок
"""

from aiogram import Router

# Создаём главный роутер модуля капчи
captcha_router = Router(name="captcha")

# Импортируем и подключаем роутеры компонентов
from bot.handlers.captcha.captcha_coordinator import coordinator_router
from bot.handlers.captcha.captcha_callbacks import callbacks_router
from bot.handlers.captcha.captcha_fsm_handler import fsm_router

# Подключаем роутеры к главному
# Порядок важен:
# 1. coordinator - перехватывает join_request/new_chat_members первым
# 2. callbacks - FSM handlers для настроек (должны быть ДО fsm_router!)
# 3. fsm_router - deep link и текстовый ввод капчи (ловит все числа)
captcha_router.include_router(coordinator_router)
captcha_router.include_router(callbacks_router)  # FSM для настроек диалогов
captcha_router.include_router(fsm_router)  # FSM для deep link и текстового ввода

# Экспортируем главный роутер
__all__ = ["captcha_router"]
