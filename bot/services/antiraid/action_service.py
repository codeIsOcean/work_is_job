# bot/services/antiraid/action_service.py
"""
Сервис применения действий модуля Anti-Raid.

Выполняет:
- Бан пользователя (временный или постоянный)
- Кик пользователя
- Мут пользователя
- Отклонение заявки на вступление

ВАЖНО: Проверяет edge cases:
- Пользователь заблокировал бота → действие всё равно применяется (бан в группе)
- Telegram API недоступен → логируем ошибку, НЕ пропускаем пользователя
"""

# Импортируем логгер для записи событий
import logging
# Импортируем datetime для расчёта времени бана
from datetime import datetime, timedelta
# Импортируем типы для аннотаций
from typing import Optional
# Импортируем dataclass для результата действия
from dataclasses import dataclass

# Импортируем Bot и типы из aiogram
from aiogram import Bot
from aiogram.types import ChatPermissions
# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис настроек
from bot.services.antiraid.settings_service import get_antiraid_settings


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """
    Результат применения действия.

    Attributes:
        success: True если действие применено успешно
        action_type: Тип действия ('ban', 'kick', 'mute')
        duration_hours: Длительность (для бана/мута), 0 = навсегда
        error_message: Сообщение об ошибке (если success=False)
    """
    success: bool
    action_type: str
    duration_hours: int = 0
    error_message: Optional[str] = None


async def ban_user(
    bot: Bot,
    chat_id: int,
    user_id: int,
    duration_hours: int = 0,
    reason: str = ""
) -> ActionResult:
    """
    Банит пользователя в группе.

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        user_id: ID пользователя
        duration_hours: Длительность бана в часах (0 = навсегда)
        reason: Причина бана (для логов)

    Returns:
        ActionResult с результатом операции
    """
    try:
        # ─────────────────────────────────────────────────────────
        # Вычисляем дату окончания бана
        # ─────────────────────────────────────────────────────────
        if duration_hours > 0:
            # Временный бан — вычисляем until_date
            until_date = datetime.now() + timedelta(hours=duration_hours)
            duration_text = f"{duration_hours}ч"
        else:
            # Постоянный бан — until_date=None (навсегда)
            until_date = None
            duration_text = "навсегда"

        # ─────────────────────────────────────────────────────────
        # Применяем бан
        # ─────────────────────────────────────────────────────────
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            until_date=until_date
        )

        # Логируем успешный бан
        logger.info(
            f"[ANTIRAID] БАН: user_id={user_id}, chat_id={chat_id}, "
            f"duration={duration_text}, reason='{reason}'"
        )

        return ActionResult(
            success=True,
            action_type='ban',
            duration_hours=duration_hours
        )

    except TelegramBadRequest as e:
        # ─────────────────────────────────────────────────────────
        # Ошибка Bad Request — возможные причины:
        # - Пользователь не в группе
        # - Бот не имеет прав
        # - Пользователь — владелец группы
        # ─────────────────────────────────────────────────────────
        error_msg = f"TelegramBadRequest при бане: {e}"
        logger.error(
            f"[ANTIRAID] ОШИБКА БАН: user_id={user_id}, chat_id={chat_id}, "
            f"error={error_msg}"
        )
        return ActionResult(
            success=False,
            action_type='ban',
            duration_hours=duration_hours,
            error_message=error_msg
        )

    except TelegramAPIError as e:
        # ─────────────────────────────────────────────────────────
        # Общая ошибка Telegram API
        # ─────────────────────────────────────────────────────────
        error_msg = f"TelegramAPIError при бане: {e}"
        logger.error(
            f"[ANTIRAID] ОШИБКА БАН: user_id={user_id}, chat_id={chat_id}, "
            f"error={error_msg}"
        )
        return ActionResult(
            success=False,
            action_type='ban',
            duration_hours=duration_hours,
            error_message=error_msg
        )


async def kick_user(
    bot: Bot,
    chat_id: int,
    user_id: int,
    reason: str = ""
) -> ActionResult:
    """
    Кикает пользователя из группы (может вернуться).

    Кик = бан + разбан (пользователь может вернуться по ссылке).

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        user_id: ID пользователя
        reason: Причина кика (для логов)

    Returns:
        ActionResult с результатом операции
    """
    try:
        # ─────────────────────────────────────────────────────────
        # Шаг 1: Баним пользователя
        # ─────────────────────────────────────────────────────────
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)

        # ─────────────────────────────────────────────────────────
        # Шаг 2: Сразу разбаниваем (это превращает бан в кик)
        # ─────────────────────────────────────────────────────────
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)

        # Логируем успешный кик
        logger.info(
            f"[ANTIRAID] КИК: user_id={user_id}, chat_id={chat_id}, "
            f"reason='{reason}'"
        )

        return ActionResult(
            success=True,
            action_type='kick',
            duration_hours=0
        )

    except TelegramAPIError as e:
        # Ошибка при кике
        error_msg = f"TelegramAPIError при кике: {e}"
        logger.error(
            f"[ANTIRAID] ОШИБКА КИК: user_id={user_id}, chat_id={chat_id}, "
            f"error={error_msg}"
        )
        return ActionResult(
            success=False,
            action_type='kick',
            error_message=error_msg
        )


async def mute_user(
    bot: Bot,
    chat_id: int,
    user_id: int,
    duration_minutes: int = 60,
    reason: str = ""
) -> ActionResult:
    """
    Мутит пользователя в группе (запрет отправки сообщений).

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        user_id: ID пользователя
        duration_minutes: Длительность мута в минутах (0 = навсегда)
        reason: Причина мута (для логов)

    Returns:
        ActionResult с результатом операции
    """
    try:
        # ─────────────────────────────────────────────────────────
        # Вычисляем дату окончания мута
        # ─────────────────────────────────────────────────────────
        if duration_minutes > 0:
            until_date = datetime.now() + timedelta(minutes=duration_minutes)
            duration_text = f"{duration_minutes}мин"
        else:
            until_date = None
            duration_text = "навсегда"

        # ─────────────────────────────────────────────────────────
        # Создаём permissions без права отправки сообщений
        # ─────────────────────────────────────────────────────────
        mute_permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )

        # ─────────────────────────────────────────────────────────
        # Применяем мут
        # ─────────────────────────────────────────────────────────
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=mute_permissions,
            until_date=until_date
        )

        # Логируем успешный мут
        logger.info(
            f"[ANTIRAID] МУТ: user_id={user_id}, chat_id={chat_id}, "
            f"duration={duration_text}, reason='{reason}'"
        )

        # Конвертируем минуты в часы для результата
        duration_hours = duration_minutes // 60 if duration_minutes > 0 else 0

        return ActionResult(
            success=True,
            action_type='mute',
            duration_hours=duration_hours
        )

    except TelegramAPIError as e:
        # Ошибка при муте
        error_msg = f"TelegramAPIError при муте: {e}"
        logger.error(
            f"[ANTIRAID] ОШИБКА МУТ: user_id={user_id}, chat_id={chat_id}, "
            f"error={error_msg}"
        )
        return ActionResult(
            success=False,
            action_type='mute',
            error_message=error_msg
        )


async def decline_join_request(
    bot: Bot,
    chat_id: int,
    user_id: int,
    reason: str = ""
) -> ActionResult:
    """
    Отклоняет заявку на вступление в группу.

    Используется для групп с включёнными Join Requests.

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        user_id: ID пользователя
        reason: Причина отклонения (для логов)

    Returns:
        ActionResult с результатом операции
    """
    try:
        # ─────────────────────────────────────────────────────────
        # Отклоняем заявку
        # ─────────────────────────────────────────────────────────
        await bot.decline_chat_join_request(
            chat_id=chat_id,
            user_id=user_id
        )

        # Логируем успешное отклонение
        logger.info(
            f"[ANTIRAID] ОТКЛОНЕНИЕ ЗАЯВКИ: user_id={user_id}, chat_id={chat_id}, "
            f"reason='{reason}'"
        )

        return ActionResult(
            success=True,
            action_type='decline',
            duration_hours=0
        )

    except TelegramAPIError as e:
        # Ошибка при отклонении
        error_msg = f"TelegramAPIError при отклонении заявки: {e}"
        logger.error(
            f"[ANTIRAID] ОШИБКА ОТКЛОНЕНИЯ: user_id={user_id}, chat_id={chat_id}, "
            f"error={error_msg}"
        )
        return ActionResult(
            success=False,
            action_type='decline',
            error_message=error_msg
        )


async def apply_name_pattern_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    is_join_request: bool = False
) -> ActionResult:
    """
    Применяет действие из настроек name_pattern.

    Читает настройки группы и применяет соответствующее действие.
    Это ГЛАВНАЯ функция для применения действий name_pattern.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя
        is_join_request: True если это событие chat_join_request
                         (нужно отклонить заявку перед баном)

    Returns:
        ActionResult с результатом операции
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — используем дефолты (бан навсегда)
    if settings is None:
        action = 'ban'
        duration = 0
    else:
        action = settings.name_pattern_action
        duration = settings.name_pattern_ban_duration

    # Причина для логов
    reason = "name_pattern_match"

    # ─────────────────────────────────────────────────────────
    # Если это join_request — сначала отклоняем заявку
    # ─────────────────────────────────────────────────────────
    if is_join_request:
        await decline_join_request(bot, chat_id, user_id, reason)

    # ─────────────────────────────────────────────────────────
    # Применяем действие в зависимости от настроек
    # ─────────────────────────────────────────────────────────
    if action == 'ban':
        return await ban_user(bot, chat_id, user_id, duration, reason)
    elif action == 'kick':
        return await kick_user(bot, chat_id, user_id, reason)
    else:
        # Неизвестное действие — логируем и баним (безопасный fallback)
        logger.warning(
            f"[ANTIRAID] Неизвестное действие name_pattern: '{action}', "
            f"применяем бан. chat_id={chat_id}"
        )
        return await ban_user(bot, chat_id, user_id, 0, reason)


async def apply_join_exit_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> ActionResult:
    """
    Применяет действие из настроек join_exit.

    Читает настройки группы и применяет соответствующее действие
    при злоупотреблении входами/выходами.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        ActionResult с результатом операции
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — используем дефолты (бан на 7 дней)
    if settings is None:
        action = 'ban'
        duration = 168  # 7 дней в часах
    else:
        action = settings.join_exit_action
        duration = settings.join_exit_ban_duration

    # Причина для логов
    reason = "join_exit_abuse"

    # ─────────────────────────────────────────────────────────
    # Применяем действие в зависимости от настроек
    # ─────────────────────────────────────────────────────────
    if action == 'ban':
        return await ban_user(bot, chat_id, user_id, duration, reason)
    elif action == 'kick':
        return await kick_user(bot, chat_id, user_id, reason)
    elif action == 'mute':
        # Для мута конвертируем часы в минуты
        duration_minutes = duration * 60 if duration > 0 else 0
        return await mute_user(bot, chat_id, user_id, duration_minutes, reason)
    else:
        # Неизвестное действие — логируем и баним (безопасный fallback)
        logger.warning(
            f"[ANTIRAID] Неизвестное действие join_exit: '{action}', "
            f"применяем бан. chat_id={chat_id}"
        )
        return await ban_user(bot, chat_id, user_id, 168, reason)


# ============================================================
# ДЕЙСТВИЯ ДЛЯ РЕЙД-ЗАЩИТЫ (MASS JOIN)
# ============================================================

async def set_slowmode(
    bot: Bot,
    chat_id: int,
    slow_mode_delay: int,
    reason: str = "raid_detected"
) -> ActionResult:
    """
    Устанавливает slowmode в группе.

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        slow_mode_delay: Задержка между сообщениями в секундах (0-3600)
        reason: Причина для логирования

    Returns:
        ActionResult с результатом операции
    """
    try:
        # Telegram ограничивает slowmode: 0, 10, 30, 60, 300, 900, 3600
        # Округляем до ближайшего допустимого значения
        valid_delays = [0, 10, 30, 60, 300, 900, 3600]
        closest_delay = min(valid_delays, key=lambda x: abs(x - slow_mode_delay))

        await bot.set_chat_slow_mode_delay(
            chat_id=chat_id,
            slow_mode_delay=closest_delay
        )

        logger.info(
            f"[ANTIRAID] Slowmode установлен: chat_id={chat_id}, "
            f"delay={closest_delay}s, reason={reason}"
        )

        return ActionResult(
            success=True,
            action="slowmode",
            details=f"delay={closest_delay}s"
        )

    except TelegramAPIError as e:
        logger.error(
            f"[ANTIRAID] Ошибка установки slowmode: {e}, "
            f"chat_id={chat_id}"
        )
        return ActionResult(
            success=False,
            action="slowmode",
            error=str(e)
        )


async def remove_slowmode(
    bot: Bot,
    chat_id: int,
    reason: str = "raid_cleared"
) -> ActionResult:
    """
    Снимает slowmode в группе.

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        reason: Причина для логирования

    Returns:
        ActionResult с результатом операции
    """
    return await set_slowmode(bot, chat_id, 0, reason)


async def lock_group(
    bot: Bot,
    chat_id: int,
    reason: str = "raid_detected"
) -> ActionResult:
    """
    Закрывает группу (запрещает отправку сообщений).

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        reason: Причина для логирования

    Returns:
        ActionResult с результатом операции
    """
    from aiogram.types import ChatPermissions

    try:
        # Полностью блокируем права на отправку
        locked_permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        await bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=locked_permissions
        )

        logger.info(
            f"[ANTIRAID] Группа закрыта: chat_id={chat_id}, reason={reason}"
        )

        return ActionResult(
            success=True,
            action="lock",
            details="group_locked"
        )

    except TelegramAPIError as e:
        logger.error(
            f"[ANTIRAID] Ошибка закрытия группы: {e}, chat_id={chat_id}"
        )
        return ActionResult(
            success=False,
            action="lock",
            error=str(e)
        )


async def unlock_group(
    bot: Bot,
    chat_id: int,
    reason: str = "raid_cleared"
) -> ActionResult:
    """
    Открывает группу (восстанавливает стандартные права).

    Args:
        bot: Экземпляр Bot
        chat_id: ID группы
        reason: Причина для логирования

    Returns:
        ActionResult с результатом операции
    """
    from aiogram.types import ChatPermissions

    try:
        # Стандартные права для обычных участников
        default_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,  # Обычно нельзя
            can_invite_users=True,
            can_pin_messages=False,  # Обычно нельзя
        )

        await bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=default_permissions
        )

        logger.info(
            f"[ANTIRAID] Группа открыта: chat_id={chat_id}, reason={reason}"
        )

        return ActionResult(
            success=True,
            action="unlock",
            details="group_unlocked"
        )

    except TelegramAPIError as e:
        logger.error(
            f"[ANTIRAID] Ошибка открытия группы: {e}, chat_id={chat_id}"
        )
        return ActionResult(
            success=False,
            action="unlock",
            error=str(e)
        )


async def apply_raid_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int
) -> ActionResult:
    """
    Применяет действие из настроек mass_join.

    Читает настройки группы и применяет соответствующее действие
    при обнаружении рейда.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы

    Returns:
        ActionResult с результатом операции
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — используем дефолты
    if settings is None:
        action = 'slowmode'
        slowmode_delay = 60
    else:
        action = settings.mass_join_action
        slowmode_delay = settings.mass_join_slowmode

    # Причина для логов
    reason = "raid_detected"

    # ─────────────────────────────────────────────────────────
    # Применяем действие в зависимости от настроек
    # ─────────────────────────────────────────────────────────
    if action == 'slowmode':
        return await set_slowmode(bot, chat_id, slowmode_delay, reason)
    elif action == 'lock':
        return await lock_group(bot, chat_id, reason)
    elif action == 'notify':
        # Только уведомление — не применяем ограничений
        logger.info(
            f"[ANTIRAID] Рейд обнаружен (notify only): chat_id={chat_id}"
        )
        return ActionResult(
            success=True,
            action="notify",
            details="notification_only"
        )
    else:
        # Неизвестное действие — логируем и ставим slowmode (безопасный fallback)
        logger.warning(
            f"[ANTIRAID] Неизвестное действие mass_join: '{action}', "
            f"применяем slowmode. chat_id={chat_id}"
        )
        return await set_slowmode(bot, chat_id, 60, reason)


# ============================================================
# ДЕЙСТВИЯ ДЛЯ МАССОВЫХ ИНВАЙТОВ (MASS INVITE)
# ============================================================

async def apply_mass_invite_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    inviter_id: int
) -> ActionResult:
    """
    Применяет действие из настроек mass_invite к инвайтеру.

    Читает настройки группы и применяет соответствующее действие
    когда один пользователь приглашает слишком много людей.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        inviter_id: ID пользователя-инвайтера

    Returns:
        ActionResult с результатом операции
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — используем дефолты (warn)
    if settings is None:
        action = 'warn'
        duration = 24  # 24 часа
    else:
        action = settings.mass_invite_action
        duration = settings.mass_invite_ban_duration

    # Причина для логов
    reason = "mass_invite_abuse"

    # ─────────────────────────────────────────────────────────
    # Применяем действие в зависимости от настроек
    # ─────────────────────────────────────────────────────────
    if action == 'warn':
        # Предупреждение — просто логируем, без ограничений
        logger.info(
            f"[ANTIRAID] WARN (mass_invite): inviter_id={inviter_id}, "
            f"chat_id={chat_id}"
        )
        return ActionResult(
            success=True,
            action_type='warn',
            duration_hours=0
        )
    elif action == 'kick':
        return await kick_user(bot, chat_id, inviter_id, reason)
    elif action == 'ban':
        return await ban_user(bot, chat_id, inviter_id, duration, reason)
    elif action == 'mute':
        # Для мута конвертируем часы в минуты
        duration_minutes = duration * 60 if duration > 0 else 0
        return await mute_user(bot, chat_id, inviter_id, duration_minutes, reason)
    else:
        # Неизвестное действие — логируем и предупреждаем (безопасный fallback)
        logger.warning(
            f"[ANTIRAID] Неизвестное действие mass_invite: '{action}', "
            f"применяем warn. chat_id={chat_id}"
        )
        return ActionResult(
            success=True,
            action_type='warn',
            duration_hours=0
        )


# ============================================================
# ДЕЙСТВИЯ ДЛЯ МАССОВЫХ РЕАКЦИЙ (MASS REACTION)
# ============================================================

async def apply_mass_reaction_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> ActionResult:
    """
    Применяет действие из настроек mass_reaction к пользователю.

    Читает настройки группы и применяет соответствующее действие
    когда пользователь спамит реакциями.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        ActionResult с результатом операции
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — используем дефолты (ban навсегда)
    if settings is None:
        action = 'ban'
        ban_duration = 0  # часы (0 = навсегда)
    else:
        action = settings.mass_reaction_action
        ban_duration = settings.mass_reaction_ban_duration

    # Причина для логов
    reason = "mass_reaction_abuse"

    # ─────────────────────────────────────────────────────────
    # Применяем действие в зависимости от настроек
    # ─────────────────────────────────────────────────────────
    if action == 'warn':
        # Предупреждение — просто логируем, без ограничений
        logger.info(
            f"[ANTIRAID] WARN (mass_reaction): user_id={user_id}, "
            f"chat_id={chat_id}"
        )
        return ActionResult(
            success=True,
            action_type='warn',
            duration_hours=0
        )
    elif action == 'mute':
        # Для mute используем ban_duration как часы, конвертируем в минуты
        mute_minutes = ban_duration * 60 if ban_duration > 0 else 60
        return await mute_user(bot, chat_id, user_id, mute_minutes, reason)
    elif action == 'kick':
        return await kick_user(bot, chat_id, user_id, reason)
    elif action == 'ban':
        # Бан с длительностью из настроек (0 = навсегда)
        return await ban_user(bot, chat_id, user_id, ban_duration, reason)
    else:
        # Неизвестное действие — логируем и баним (безопасный fallback)
        logger.warning(
            f"[ANTIRAID] Неизвестное действие mass_reaction: '{action}', "
            f"применяем ban. chat_id={chat_id}"
        )
        return await ban_user(bot, chat_id, user_id, 0, reason)
