# Импорт всех роутеров для удобного подключения
from .bot_activity_handlers import bot_activity_handlers_router
from .bot_activity_journal.bot_activity_journal import bot_activity_journal_router
from .deep_link_handlers import universal_deeplink_router
from .group_settings_handler import group_settings_router
from .moderation_handlers import moderation_handlers_router
# РЕДИЗАЙН КАПЧИ: Новый модуль капчи (единая точка входа)
# Полностью заменяет старый visual_captcha
from .captcha import captcha_router
from .broadcast_handlers.broadcast_handlers import broadcast_router
from .bot_moderation_handlers.new_member_requested_to_join_mute_handlers import new_member_requested_handler
from .auto_mute_scammers_handlers import auto_mute_scammers_router
from .mute_by_reaction import reaction_mute_router
from .admin_log_handlers import admin_log_router
from .enhanced_analysis_test_handler import enhanced_analysis_router
from .settings_captcha_handler import captcha_settings_router
from .journal_link_handler import journal_link_router
from .unscam_handler import unscam_router
# Импортируем только antispam_router (настройки UI)
# antispam_filter_router перенесён в group_message_coordinator
from .antispam_handlers import antispam_router
# Импортируем роутер модуля content_filter (только UI настроек)
# filter_handler перенесён в group_message_coordinator
from .content_filter import content_filter_router
# Импортируем роутер модуля message_management (UI + команды)
# filter_handler вызывается из group_message_coordinator
from .message_management import message_management_router
# Импортируем роутер модуля profile_monitor (callbacks + settings UI)
# monitor_handler вызывается из group_message_coordinator
from .profile_monitor import router as profile_monitor_router
# Импортируем координатор сообщений в группах
# Это единая точка входа для ContentFilter, Antispam, ProfileMonitor
from .group_message_coordinator import group_message_coordinator_router

# Объединяем все роутеры в один
from aiogram import Router, F
from aiogram.types import CallbackQuery
import logging

logger = logging.getLogger(__name__)

handlers_router = Router()
handlers_router.include_router(bot_activity_handlers_router)
handlers_router.include_router(bot_activity_journal_router)
handlers_router.include_router(universal_deeplink_router)
handlers_router.include_router(group_settings_router)
handlers_router.include_router(moderation_handlers_router)
# РЕДИЗАЙН КАПЧИ: Новый модуль капчи (единая точка входа)
handlers_router.include_router(captcha_router)
handlers_router.include_router(broadcast_router)
handlers_router.include_router(new_member_requested_handler)  # Ручной мут ПЕРВЫМ
handlers_router.include_router(auto_mute_scammers_router)     # Автомут ВТОРЫМ
handlers_router.include_router(admin_log_router)
handlers_router.include_router(enhanced_analysis_router)
handlers_router.include_router(journal_link_router)           # Привязка журнала через пересылку
handlers_router.include_router(reaction_mute_router)
handlers_router.include_router(captcha_settings_router)
handlers_router.include_router(unscam_router)                 # Команда /unscam в ЛС
handlers_router.include_router(antispam_router)               # Антиспам настройки UI
handlers_router.include_router(content_filter_router)         # Content filter настройки UI
handlers_router.include_router(message_management_router)     # Message management UI + команды
handlers_router.include_router(profile_monitor_router)        # Profile monitor callbacks + settings
# ============================================================
# GROUP MESSAGE COORDINATOR - единый хендлер для сообщений в группах
# ============================================================
# Координирует работу ContentFilter, Antispam и ProfileMonitor.
# Решает проблему конфликта хендлеров с одинаковыми фильтрами.
# Подробнее: docs/ARCHITECTURE.md
handlers_router.include_router(group_message_coordinator_router)


def create_fresh_handlers_router():
    """Создает новый экземпляр handlers_router с подключенными роутерами"""
    from aiogram import Router
    fresh_router = Router()
    fresh_router.include_router(bot_activity_handlers_router)
    fresh_router.include_router(bot_activity_journal_router)
    fresh_router.include_router(universal_deeplink_router)
    fresh_router.include_router(group_settings_router)
    fresh_router.include_router(moderation_handlers_router)
    # РЕДИЗАЙН КАПЧИ: Новый модуль капчи (единая точка входа)
    fresh_router.include_router(captcha_router)
    fresh_router.include_router(broadcast_router)
    fresh_router.include_router(new_member_requested_handler)
    fresh_router.include_router(auto_mute_scammers_router)
    fresh_router.include_router(admin_log_router)
    fresh_router.include_router(enhanced_analysis_router)
    fresh_router.include_router(journal_link_router)
    fresh_router.include_router(reaction_mute_router)
    fresh_router.include_router(captcha_settings_router)
    fresh_router.include_router(unscam_router)
    fresh_router.include_router(antispam_router)
    fresh_router.include_router(content_filter_router)
    fresh_router.include_router(message_management_router)
    fresh_router.include_router(profile_monitor_router)
    # Group Message Coordinator - единый хендлер для групповых сообщений
    fresh_router.include_router(group_message_coordinator_router)
    return fresh_router


# Общий обработчик для неизвестных callback-запросов УДАЛЕН
# Он мешал работе специфических обработчиков
# Если нужна отладка неизвестных callback-запросов, можно добавить отдельный роутер