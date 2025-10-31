# Импорт всех роутеров для удобного подключения
from .bot_activity_handlers import bot_activity_handlers_router
from .bot_activity_journal.bot_activity_journal import bot_activity_journal_router
from .deep_link_handlers import universal_deeplink_router
from .group_settings_handler import group_settings_router
from .moderation_handlers import moderation_handlers_router
from .visual_captcha import visual_captcha_router
from .broadcast_handlers.broadcast_handlers import broadcast_router
from .bot_moderation_handlers.new_member_requested_to_join_mute_handlers import new_member_requested_handler
from .auto_mute_scammers_handlers import auto_mute_scammers_router
from .admin_log_handlers import admin_log_router
from .enhanced_analysis_test_handler import enhanced_analysis_router
from .journal_link_handler import journal_link_router

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
handlers_router.include_router(visual_captcha_router)
handlers_router.include_router(broadcast_router)
handlers_router.include_router(new_member_requested_handler)  # Ручной мут ПЕРВЫМ
handlers_router.include_router(auto_mute_scammers_router)     # Автомут ВТОРЫМ
handlers_router.include_router(admin_log_router)
handlers_router.include_router(enhanced_analysis_router)
handlers_router.include_router(journal_link_router)           # Привязка журнала через пересылку


def create_fresh_handlers_router():
    """Создает новый экземпляр handlers_router с подключенными роутерами"""
    from aiogram import Router
    fresh_router = Router()
    fresh_router.include_router(bot_activity_handlers_router)
    fresh_router.include_router(bot_activity_journal_router)
    fresh_router.include_router(universal_deeplink_router)
    fresh_router.include_router(group_settings_router)
    fresh_router.include_router(moderation_handlers_router)
    fresh_router.include_router(visual_captcha_router)
    fresh_router.include_router(broadcast_router)
    fresh_router.include_router(new_member_requested_handler)
    fresh_router.include_router(auto_mute_scammers_router)
    fresh_router.include_router(admin_log_router)
    fresh_router.include_router(enhanced_analysis_router)
    fresh_router.include_router(journal_link_router)
    return fresh_router


# Общий обработчик для неизвестных callback-запросов УДАЛЕН
# Он мешал работе специфических обработчиков
# Если нужна отладка неизвестных callback-запросов, можно добавить отдельный роутер