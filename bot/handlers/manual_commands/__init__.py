# ═══════════════════════════════════════════════════════════════════════════
# МОДУЛЬ ХЕНДЛЕРОВ РУЧНЫХ КОМАНД МОДЕРАЦИИ
# ═══════════════════════════════════════════════════════════════════════════
# Этот модуль содержит обработчики команд /amute, /aban, /akick, /asend.
# Все хендлеры регистрируются в одном роутере для удобства.
#
# Создано: 2026-01-21
# Обновлено: 2026-01-22 — добавлены /aban и /akick
# ═══════════════════════════════════════════════════════════════════════════

from aiogram import Router

# Создаём роутер для модуля ручных команд
manual_commands_router = Router(name="manual_commands")

# Импортируем хендлеры и добавляем их роутеры
# Хендлер команды /amute и /aunmute
from bot.handlers.manual_commands.mute_command import mute_router
# Хендлер команды /aban
from bot.handlers.manual_commands.ban_command import ban_router
# Хендлер команды /akick
from bot.handlers.manual_commands.kick_command import kick_router
# Хендлер команды /asend (отправка от имени бота)
from bot.handlers.manual_commands.send_command import send_router
# Хендлер callback-кнопок журнала
from bot.handlers.manual_commands.callbacks_handler import callbacks_router
# Хендлер UI настроек модуля
from bot.handlers.manual_commands.settings_handler import settings_router

# Регистрируем sub-роутеры
manual_commands_router.include_router(mute_router)
manual_commands_router.include_router(ban_router)
manual_commands_router.include_router(kick_router)
manual_commands_router.include_router(send_router)
manual_commands_router.include_router(callbacks_router)
manual_commands_router.include_router(settings_router)

# Экспортируем главный роутер
__all__ = ['manual_commands_router']
