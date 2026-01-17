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
from .mute_by_reaction import reaction_mute_router, reaction_mute_settings_router
# Удалено: admin_log_handlers (мёртвый код - обрабатывал несуществующие callbacks)
from .enhanced_analysis_test_handler import enhanced_analysis_router
from .settings_captcha_handler import captcha_settings_router
from .journal_link_handler import journal_link_router
from .unscam_handler import unscam_router
# Импортируем только antispam_router (настройки UI)
# antispam_filter_router перенесён в group_message_coordinator
# antispam_journal_actions_router - обработка кнопок действий в журнале
from .antispam_handlers import antispam_router, antispam_journal_actions_router
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
# Импортируем роутер команд ScamMedia (/mutein, /banin, /scamrm, /scamlogo)
from .scam_media.commands_handler import router as scam_media_commands_router
# Импортируем роутер callbacks ScamMedia (обработка кнопок настроек)
from .scam_media.callbacks_handler import router as scam_media_callbacks_router
# Импортируем роутер FSM ScamMedia (загрузка/удаление фото через UI)
from .scam_media.fsm_handler import router as scam_media_fsm_router
# Импортируем роутер команды /stat (статистика пользователя)
from .user_stats_handler import router as user_stats_router
# Импортируем роутер экспорта/импорта настроек
from .settings_export import settings_export_router
# Импортируем роутер модуля кросс-групповой детекции (настройки + callbacks журнала)
from .cross_group import router as cross_group_router
# Импортируем роутеры модуля Anti-Raid
from .antiraid import antiraid_callbacks_router, antiraid_settings_router, join_exit_router, reaction_router

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
# Удалено: admin_log_router (мёртвый код)
handlers_router.include_router(enhanced_analysis_router)
handlers_router.include_router(journal_link_router)           # Привязка журнала через пересылку
handlers_router.include_router(reaction_mute_router)
handlers_router.include_router(reaction_mute_settings_router)  # UI настроек мута по реакциям
handlers_router.include_router(captcha_settings_router)
handlers_router.include_router(unscam_router)                 # Команда /unscam в ЛС
handlers_router.include_router(antispam_router)               # Антиспам настройки UI
handlers_router.include_router(antispam_journal_actions_router)  # Кнопки действий в журнале антиспам
handlers_router.include_router(content_filter_router)         # Content filter настройки UI
handlers_router.include_router(message_management_router)     # Message management UI + команды
handlers_router.include_router(profile_monitor_router)        # Profile monitor callbacks + settings
# Команда /stat - статистика пользователя в группе
# ВАЖНО: должен быть ДО group_message_coordinator, иначе команда будет удалена
handlers_router.include_router(user_stats_router)
# ScamMedia команды (/mutein, /banin, /scamrm, /scamlogo)
# ВАЖНО: должен быть ДО group_message_coordinator
handlers_router.include_router(scam_media_commands_router)
# ScamMedia callbacks (обработка кнопок настроек)
handlers_router.include_router(scam_media_callbacks_router)
# ScamMedia FSM (загрузка/удаление фото через UI)
handlers_router.include_router(scam_media_fsm_router)
# Экспорт/импорт настроек групп (работает в ЛС бота)
handlers_router.include_router(settings_export_router)
# Кросс-групповая детекция скамеров (настройки UI + callbacks журнала)
handlers_router.include_router(cross_group_router)
# Anti-Raid callbacks журнала (разбан, OK, permban, и т.д.)
handlers_router.include_router(antiraid_callbacks_router)
# Anti-Raid настройки UI (в ЛС бота)
handlers_router.include_router(antiraid_settings_router)
# Anti-Raid join/exit трекер (обработка выходов из группы)
handlers_router.include_router(join_exit_router)
# Anti-Raid reaction трекер (обработка массовых реакций)
handlers_router.include_router(reaction_router)
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
    # Удалено: admin_log_router (мёртвый код)
    fresh_router.include_router(enhanced_analysis_router)
    fresh_router.include_router(journal_link_router)
    fresh_router.include_router(reaction_mute_router)
    fresh_router.include_router(reaction_mute_settings_router)  # UI настроек мута по реакциям
    fresh_router.include_router(captcha_settings_router)
    fresh_router.include_router(unscam_router)
    fresh_router.include_router(antispam_router)
    fresh_router.include_router(antispam_journal_actions_router)  # Кнопки действий в журнале антиспам
    fresh_router.include_router(content_filter_router)
    fresh_router.include_router(message_management_router)
    fresh_router.include_router(profile_monitor_router)
    # Команда /stat - статистика пользователя (ДО coordinator!)
    fresh_router.include_router(user_stats_router)
    # ScamMedia команды (/mutein, /banin, /scamrm, /scamlogo)
    fresh_router.include_router(scam_media_commands_router)
    # ScamMedia callbacks (обработка кнопок настроек)
    fresh_router.include_router(scam_media_callbacks_router)
    # ScamMedia FSM (загрузка/удаление фото через UI)
    fresh_router.include_router(scam_media_fsm_router)
    # Экспорт/импорт настроек групп (работает в ЛС бота)
    fresh_router.include_router(settings_export_router)
    # Кросс-групповая детекция скамеров (настройки UI + callbacks журнала)
    fresh_router.include_router(cross_group_router)
    # Anti-Raid callbacks журнала (разбан, OK, permban, и т.д.)
    fresh_router.include_router(antiraid_callbacks_router)
    # Anti-Raid настройки UI (в ЛС бота)
    fresh_router.include_router(antiraid_settings_router)
    # Anti-Raid join/exit трекер (обработка выходов из группы)
    fresh_router.include_router(join_exit_router)
    # Anti-Raid reaction трекер (обработка массовых реакций)
    fresh_router.include_router(reaction_router)
    # Group Message Coordinator - единый хендлер для групповых сообщений
    fresh_router.include_router(group_message_coordinator_router)
    return fresh_router


# Общий обработчик для неизвестных callback-запросов УДАЛЕН
# Он мешал работе специфических обработчиков
# Если нужна отладка неизвестных callback-запросов, можно добавить отдельный роутер