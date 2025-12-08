# services/bot_activity_journal/bot_activity_journal_logic.py
import logging
from typing import Dict, Any, Optional, List
from aiogram import Bot
from aiogram.types import User, Chat
from sqlalchemy.ext.asyncio import AsyncSession
from bot.handlers.bot_activity_journal.bot_activity_journal import send_activity_log

logger = logging.getLogger(__name__)


async def log_join_request(
    bot: Bot,
    user: User,
    chat: Chat,
    captcha_status: str = "КАПЧА_НЕ_УДАЛАСЬ",
    saved_to_db: bool = False,
    session: Optional[AsyncSession] = None
):
    """Логирует запрос на вступление в группу"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "captcha_status": captcha_status,
            "saved_to_db": saved_to_db,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="ЗАПРОС_НА_ВСТУПЛЕНИЕ",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="failed" if captcha_status == "КАПЧА_НЕ_УДАЛАСЬ" else "success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании запроса на вступление: {e}")


async def log_new_member(
    bot: Bot,
    user: User,
    chat: Chat,
    invited_by: Optional[User] = None,
    session: Optional[AsyncSession] = None,
    age_info: Optional[Dict[str, Any]] = None
):
    """
    Логирует нового участника группы

    Args:
        age_info: Опциональный словарь с информацией о возрасте:
            - photo_age_days: возраст самого старого фото (если есть)
            - estimated_age_days: приблизительный возраст аккаунта (динамический расчёт)
            - photos_count: количество фото в профиле
    """
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }

        additional_info = {}
        if invited_by:
            additional_info["invited_by"] = {
                "user_id": invited_by.id,
                "username": invited_by.username,
                "first_name": invited_by.first_name,
                "last_name": invited_by.last_name,
            }

        # Добавляем информацию о возрасте аккаунта (если передана)
        if age_info:
            additional_info["age_info"] = age_info

        await send_activity_log(
            bot=bot,
            event_type="НовыйПользователь",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info if additional_info else None,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании нового участника: {e}")


async def log_user_left(
    bot: Bot,
    user: User,
    chat: Chat,
    session: Optional[AsyncSession] = None
):
    """Логирует выход пользователя из группы"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="пользовательвышел",
            user_data=user_data,
            group_data=group_data,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании выхода пользователя: {e}")


async def log_user_kicked(
    bot: Bot,
    user: User,
    chat: Chat,
    initiator: Optional[User] = None,
    session: Optional[AsyncSession] = None
):
    """Логирует удаление пользователя из группы"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {}
        if initiator:
            additional_info["initiator"] = {
                "user_id": initiator.id,
                "username": initiator.username,
                "first_name": initiator.first_name,
                "last_name": initiator.last_name,
            }
        
        await send_activity_log(
            bot=bot,
            event_type="пользовательудален",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании удаления пользователя: {e}")


async def log_visual_captcha_toggle(
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool,
    session: Optional[AsyncSession] = None
):
    """Логирует включение/выключение визуальной капчи"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        event_type = "Визуальная капча включена" if enabled else "Визуальная капча выключена"
        
        await send_activity_log(
            bot=bot,
            event_type=event_type,
            user_data=user_data,
            group_data=group_data,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании переключения визуальной капчи: {e}")


async def log_captcha_setting_change(
    *,
    bot: Bot,
    user: User,
    chat: Chat,
    setting: str,
    value: Any,
    session: Optional[AsyncSession] = None,
) -> None:
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }

        await send_activity_log(
            bot=bot,
            event_type="CAPTCHA_SETTING_UPDATE",
            user_data=user_data,
            group_data=group_data,
            additional_info={
                "setting": setting,
                "value": value,
            },
            status="success",
            session=session,
        )
    except Exception as exc:
        logger.error("❌ Ошибка при логировании изменения настроек капчи: %s", exc)


async def log_system_announcement_toggle(
    *,
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool,
    session: Optional[AsyncSession] = None,
) -> None:
    await log_captcha_setting_change(
        bot=bot,
        user=user,
        chat=chat,
        setting="system_mute_announcements_enabled",
        value="on" if enabled else "off",
        session=session,
    )


async def log_captcha_manual_action(
    *,
    bot: Bot,
    user: User,
    target: Chat,
    chat: Chat,
    action: str,
    result: str,
    session: Optional[AsyncSession] = None,
) -> None:
    await send_activity_log(
        bot=bot,
        event_type="CAPTCHA_MANUAL_ACTION",
        user_data={
            "user_id": target.id,
            "username": target.username,
            "first_name": getattr(target, "first_name", None),
            "last_name": getattr(target, "last_name", None),
        },
        group_data={
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        },
        additional_info={
            "action": action,
            "result": result,
            "admin": {
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
            },
        },
        status="success",
        session=session,
    )


async def log_mute_settings_toggle(
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool,
    session: Optional[AsyncSession] = None
):
    """Логирует включение/выключение настроек мута новых пользователей"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        event_type = "Настройка мута новых пользователей включена" if enabled else "Настройка мута новых пользователей выключена"
        
        await send_activity_log(
            bot=bot,
            event_type=event_type,
            user_data=user_data,
            group_data=group_data,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании переключения настроек мута: {e}")


async def log_bot_added_to_group(
    bot: Bot,
    chat: Chat,
    added_by: Optional[User] = None,
    session: Optional[AsyncSession] = None
):
    """Логирует добавление бота в группу"""
    try:
        # Получаем информацию о боте
        bot_info = await bot.me()
        
        # Используем данные бота как пользователя для логирования
        user_data = {
            "user_id": bot_info.id,
            "username": bot_info.username,
            "first_name": bot_info.first_name,
            "last_name": "",
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {}
        if added_by:
            additional_info["added_by"] = {
                "user_id": added_by.id,
                "username": added_by.username,
                "first_name": added_by.first_name,
                "last_name": added_by.last_name,
            }
        
        await send_activity_log(
            bot=bot,
            event_type="БОТ_ДОБАВЛЕН_В_ГРУППУ",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании добавления бота в группу: {e}")


# Новые функции логирования для недостающих событий

async def log_captcha_passed(
    bot: Bot,
    user: User,
    chat: Chat,
    scammer_level: int = 0,
    session: Optional[AsyncSession] = None
):
    """Логирует успешное прохождение капчи"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "scammer_level": scammer_level,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="CAPTCHA_PASSED",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании прохождения капчи: {e}")


async def log_captcha_failed(
    bot: Bot,
    user: User,
    chat: Chat,
    reason: str = "Неверный ответ",
    attempt: Optional[int] = None,
    risk_score: Optional[int] = None,
    risk_factors: Optional[List[str]] = None,
    session: Optional[AsyncSession] = None
):
    """Логирует неудачное прохождение капчи"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "reason": reason,
            "attempt": attempt,
            "risk_score": risk_score,
            "risk_factors": risk_factors or [],
        }
        
        await send_activity_log(
            bot=bot,
            event_type="CAPTCHA_FAILED",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="failed",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании неудачного прохождения капчи: {e}")


async def log_captcha_timeout(
    bot: Bot,
    user: User,
    chat: Chat,
    session: Optional[AsyncSession] = None
):
    """Логирует таймаут капчи"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="CAPTCHA_TIMEOUT",
            user_data=user_data,
            group_data=group_data,
            status="failed",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании таймаута капчи: {e}")


async def log_auto_mute_scammer(
    bot: Bot,
    user: User,
    chat: Chat,
    scammer_level: int = 0,
    reason: str = "Обнаружен как скаммер",
    session: Optional[AsyncSession] = None
):
    """Логирует автомута скаммера"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "scammer_level": scammer_level,
            "reason": reason,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="AUTO_MUTE_SCAMMER",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании автомута скаммера: {e}")


async def log_scammer_detected(
    bot: Bot,
    user: User,
    chat: Chat,
    scammer_level: int = 0,
    violation_type: str = "unknown",
    session: Optional[AsyncSession] = None
):
    """Логирует обнаружение скаммера"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "scammer_level": scammer_level,
            "violation_type": violation_type,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="SCAMMER_DETECTED",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="failed",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании обнаружения скаммера: {e}")


async def log_auto_mute_scammers_toggled(
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool,
    session: Optional[AsyncSession] = None
):
    """Логирует включение/выключение автомута скамеров"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "enabled": enabled,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="AUTO_MUTE_SCAMMERS_TOGGLED",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success",
            session=session
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании переключения автомута скамеров: {e}")
