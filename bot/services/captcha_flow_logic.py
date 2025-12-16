from __future__ import annotations

import asyncio
import json
import logging
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import ChatPermissions, Chat
from aiogram.utils.markdown import hlink
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ChatSettings
from bot.services.redis_conn import redis
from bot.services import risk_gate
from bot.services import global_mute_policy
from bot.services.spammer_registry import (
    get_spammer_record,
    record_spammer_incident,
    mute_suspicious_user_across_groups,
)


logger = logging.getLogger(__name__)


async def _maybe_await(result):
    """Helper to support both real AsyncSession and MagicMock in tests.

    In production, SQLAlchemy methods return awaitables; in unit tests they
    might be plain values or MagicMocks. This keeps the implementation
    compatible with both without changing the public API.
    """
    if inspect.isawaitable(result):
        return await result
    return result


CAPTCHA_STATE_KEY = "captcha:state:{chat_id}:{user_id}"
CAPTCHA_MESSAGE_KEY = "captcha:message:{chat_id}:{user_id}"
CAPTCHA_OWNER_KEY = "captcha:owner:{chat_id}:{message_id}"  # ФИКС №6: Владелец капчи для кнопки
INVITE_COUNTER_KEY = "captcha:invite_counter:{chat_id}:{initiator_id}"
INVITE_FALLBACK_KEY = "captcha:invite_fallback:{chat_id}:{initiator_id}"


@dataclass
class CaptchaFlowSettings:
    join_enabled: bool
    invite_enabled: bool
    timeout_seconds: int
    message_ttl_seconds: int
    flood_threshold: int
    flood_window_seconds: int
    flood_action: str
    visual_enabled: bool
    system_announcements: bool


@dataclass
class AntiFloodResult:
    triggered: bool
    total: int
    action: Optional[str] = None


@dataclass
class CaptchaDecision:
    require_captcha: bool
    fallback_mode: bool
    anti_flood: Optional[AntiFloodResult]
    # reason делаем необязательным, чтобы старые тесты могли создавать
    # CaptchaDecision без этого поля
    reason: str = ""


@dataclass
class AdmissionDecision:
    allow: bool
    muted: bool
    reason: str


def build_restriction_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=False,
        can_pin_messages=False,
    )


async def _ensure_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    settings = await _maybe_await(session.get(ChatSettings, chat_id))
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await _maybe_await(session.flush())
    return settings


async def load_captcha_settings(session: AsyncSession, chat_id: int) -> CaptchaFlowSettings:
    settings = await _ensure_settings(session, chat_id)
    return CaptchaFlowSettings(
        join_enabled=settings.captcha_join_enabled,
        invite_enabled=settings.captcha_invite_enabled,
        timeout_seconds=settings.captcha_timeout_seconds,
        message_ttl_seconds=settings.captcha_message_ttl_seconds,
        flood_threshold=settings.captcha_flood_threshold,
        flood_window_seconds=settings.captcha_flood_window_seconds,
        flood_action=settings.captcha_flood_action,
        visual_enabled=settings.reaction_mute_enabled,
        system_announcements=settings.system_mute_announcements_enabled,
    )


async def should_require_captcha(
    *,
    settings: CaptchaFlowSettings,
    source: str,
    anti_flood: Optional[AntiFloodResult] = None,
) -> CaptchaDecision:
    if anti_flood and anti_flood.triggered:
        return CaptchaDecision(
            require_captcha=False,
            fallback_mode=True,
            anti_flood=anti_flood,
            reason="antiflood_triggered",
        )

    source_map = {
        "join_request": settings.join_enabled,
        "invite": settings.invite_enabled,
        "manual": settings.join_enabled,
    }
    require = source_map.get(source, False)
    return CaptchaDecision(
        require_captcha=require,
        fallback_mode=False,
        anti_flood=anti_flood,
        reason="captcha_required" if require else "captcha_not_required",
    )


async def prepare_join_flow(
    *,
    session: AsyncSession,
    chat_id: int,
) -> CaptchaDecision:
    settings = await load_captcha_settings(session, chat_id)
    return await should_require_captcha(settings=settings, source="join_request")


async def prepare_manual_approval_flow(
    *,
    session: AsyncSession,
    chat_id: int,
) -> CaptchaDecision:
    settings = await load_captcha_settings(session, chat_id)
    return await should_require_captcha(settings=settings, source="manual")


async def prepare_invite_flow(
    *,
    bot: Bot,
    session: AsyncSession,
    chat: Chat,
    initiator,
) -> CaptchaDecision:
    settings = await load_captcha_settings(session, chat.id)

    anti_flood: Optional[AntiFloodResult] = None
    if initiator:
        fallback_active = await is_fallback_active(chat_id=chat.id, initiator_id=initiator.id)
        if fallback_active:
            anti_flood = AntiFloodResult(triggered=True, total=0, action=settings.flood_action)
            # ОТКЛЮЧЕНО: Ложные срабатывания при одобрении join requests
            # await log_mass_invite_event(
            #     bot=bot,
            #     session=session,
            #     chat=chat,
            #     initiator=initiator,
            #     invited_total=0,
            #     settings=settings,
            # )
        else:
            anti_flood = await increment_invite_counter(
                initiator_id=initiator.id,
                chat_id=chat.id,
                settings=settings,
            )
            # ОТКЛЮЧЕНО: Ложные срабатывания при одобрении join requests
            # Система неправильно классифицирует одобрение запросов как INVITE
            # if anti_flood.triggered:
            #     await log_mass_invite_event(
            #         bot=bot,
            #         session=session,
            #         chat=chat,
            #         initiator=initiator,
            #         invited_total=anti_flood.total,
            #         settings=settings,
            #     )
            #     await apply_flood_action(
            #         bot=bot,
            #         chat=chat,
            #         initiator=initiator,
            #         flood_result=anti_flood,
            #     )

    return await should_require_captcha(
        settings=settings,
        source="invite",
        anti_flood=anti_flood,
    )


async def increment_invite_counter(
    *,
    initiator_id: int,
    chat_id: int,
    settings: CaptchaFlowSettings,
) -> AntiFloodResult:
    key = INVITE_COUNTER_KEY.format(chat_id=chat_id, initiator_id=initiator_id)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.flood_window_seconds)

    triggered = count >= settings.flood_threshold > 0
    action = settings.flood_action if triggered else None

    if triggered:
        fallback_key = INVITE_FALLBACK_KEY.format(chat_id=chat_id, initiator_id=initiator_id)
        await redis.setex(fallback_key, settings.flood_window_seconds, "1")

    return AntiFloodResult(triggered=triggered, total=count, action=action)


async def is_fallback_active(*, chat_id: int, initiator_id: int) -> bool:
    key = INVITE_FALLBACK_KEY.format(chat_id=chat_id, initiator_id=initiator_id)
    value = await redis.get(key)
    return value == "1"


async def store_captcha_state(
    *,
    chat_id: int,
    user_id: int,
    state: Dict[str, Any],
    ttl: int,
) -> None:
    key = CAPTCHA_STATE_KEY.format(chat_id=chat_id, user_id=user_id)
    await redis.setex(key, ttl, json.dumps(state))
    
    # БАГ №7: При таймауте капчи пользователь остается в муте
    # Состояние капчи удаляется через TTL, пользователь остается в муте до явного снятия


async def clear_captcha_state(chat_id: int, user_id: int) -> None:
    key = CAPTCHA_STATE_KEY.format(chat_id=chat_id, user_id=user_id)
    await redis.delete(key)


async def register_captcha_message(
    *,
    chat_id: int,
    user_id: int,
    message_id: int,
    ttl: int,
) -> None:
    key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=user_id)
    await redis.setex(key, ttl, str(message_id))


async def pop_captcha_message_id(chat_id: int, user_id: int) -> Optional[int]:
    key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=user_id)
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def schedule_message_deletion(bot: Bot, chat_id: int, user_id: int, ttl: int) -> None:
    message_id = await pop_captcha_message_id(chat_id, user_id)
    if message_id is None:
        return

    async def _delete_later():
        try:
            await asyncio.sleep(ttl)
            await bot.delete_message(chat_id=user_id, message_id=message_id)
        except Exception as exc:  # noqa: BLE001
            if "message to delete not found" not in str(exc).lower():
                logger.debug("Failed to remove captcha message %s: %s", message_id, exc)

    asyncio.create_task(_delete_later())


async def evaluate_admission(
    *,
    bot: Bot,
    session: AsyncSession,
    chat: Chat,
    user,
    source: str,
) -> AdmissionDecision:
    global_flag = await global_mute_policy.get_global_mute_flag(session)
    record = await get_spammer_record(session, user.id)
    suspicious = record is not None
    reason = "spammer_registry" if suspicious else "allowed"

    if not suspicious:
        is_suspicious = await risk_gate.is_suspicious(
            user_id=user.id,
            chat_id=chat.id,
            session=session,
            bot=bot,
        )
        if is_suspicious:
            suspicious = True
            reason = "risk_gate"

    should_mute = False
    if suspicious:
        should_mute = True
    else:
        should_mute = await global_mute_policy.should_apply_manual_mute(
            global_flag=global_flag,
            user_id=user.id,
            chat_id=chat.id,
            session=session,
            bot=bot,
        )
        if should_mute:
            reason = "global_mute"

    if should_mute:
        try:
            await bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=build_restriction_permissions(),
                until_date=None,
            )
        except Exception as exc:
            logger.error("Failed to restrict user %s in chat %s: %s", user.id, chat.id, exc)

        if reason in {"risk_gate", "spammer_registry"}:
            try:
                await record_spammer_incident(
                    session=session,
                    user_id=user.id,
                    risk_score=100,
                    reason=reason,
                )
            except Exception as exc:
                logger.error("Failed to record spammer incident: %s", exc)

        return AdmissionDecision(allow=True, muted=True, reason=reason)

    return AdmissionDecision(allow=True, muted=False, reason="allowed")


async def log_mass_invite_event(
    *,
    bot: Bot,
    session: AsyncSession,
    chat: Chat,
    initiator,
    invited_total: int,
    settings: CaptchaFlowSettings,
) -> None:
    from bot.services.bot_activity_journal.bot_activity_journal_logic import send_activity_log

    try:
        await send_activity_log(
            bot=bot,
            event_type="CAPTCHA_MASS_INVITE",
            user_data={
                "user_id": initiator.id,
                "username": getattr(initiator, "username", None),
                "first_name": getattr(initiator, "first_name", None),
                "last_name": getattr(initiator, "last_name", None),
            },
            group_data={
                "chat_id": chat.id,
                "title": chat.title,
                "username": getattr(chat, "username", None),
            },
            additional_info={
                "invited_total": invited_total,
                "flood_action": settings.flood_action,
                "threshold": settings.flood_threshold,
                "window_seconds": settings.flood_window_seconds,
            },
            status="warning",
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to log mass invite event: %s", exc)


async def apply_flood_action(
    *,
    bot: Bot,
    chat: Chat,
    initiator,
    flood_result: AntiFloodResult,
) -> None:
    if not flood_result.action:
        return

    try:
        display_name = getattr(initiator, "username", None)
        if display_name:
            display = f"@{display_name}"
        else:
            first = getattr(initiator, "first_name", "Администратор")
            display = f"<a href=\"tg://user?id={initiator.id}\">{first}</a>"

        if flood_result.action == "warn":
            await bot.send_message(
                chat.id,
                f"⚠️ Администратор {display} приглашает слишком много пользователей. Включён режим защиты.",
                parse_mode="HTML",
            )
        elif flood_result.action == "mute":
            await bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=initiator.id,
                permissions=build_restriction_permissions(),
                until_date=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        elif flood_result.action == "ban":
            await bot.ban_chat_member(chat_id=chat.id, user_id=initiator.id)
    except Exception as exc:
        logger.error("Failed to apply flood action %s to initiator %s: %s", flood_result.action, initiator.id, exc)


async def send_captcha_prompt(
    *,
    bot: Bot,
    chat: Chat,
    user,
    settings: CaptchaFlowSettings,
    source: str,
    initiator=None,
) -> None:
    from bot.services.visual_captcha_logic import (
        create_deeplink_for_captcha,
        get_captcha_keyboard,
        delete_message_after_delay,
    )
    from bot.services.bot_activity_journal.bot_activity_journal_logic import log_join_request
    from bot.database.session import get_session

    group_identifier = chat.username or f"private_{chat.id}"
    deep_link = await create_deeplink_for_captcha(bot, group_identifier)
    keyboard = await get_captcha_keyboard(deep_link)

    target_chat_id = chat.id if source in {"join_request", "invite", "manual"} else user.id
    mention = hlink(user.first_name or user.username or str(user.id), f"tg://user?id={user.id}")
    if source in {"join_request", "invite", "manual"}:
        if chat.username:
            group_link = f"https://t.me/{chat.username}"
            group_display = f"<a href='{group_link}'>{chat.title}</a>"
        else:
            group_display = f"<b>{chat.title}</b>"
        message_text = (
            f"🔒 {mention}, для вступления в {group_display} необходимо пройти капчу.\n"
            "Используйте кнопку ниже."
        )
    else:
        message_text = (
            f"🔒 Для вступления в {chat.title} необходимо пройти проверку.\n"
            "Нажмите на кнопку ниже."
        )

    # DEBUG: Логируем перед отправкой
    logger.info(f"📤 [SEND_CAPTCHA] Отправляем капчу: target_chat_id={target_chat_id}, user_id={user.id}, source={source}")

    try:
        msg = await bot.send_message(
            chat_id=target_chat_id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"✅ [SEND_CAPTCHA] Сообщение отправлено: message_id={msg.message_id}")
    except Exception as send_err:
        logger.error(f"❌ [SEND_CAPTCHA] Ошибка отправки: {send_err}")
        raise

    await register_captcha_message(
        chat_id=chat.id,
        user_id=user.id,
        message_id=msg.message_id,
        ttl=settings.message_ttl_seconds,
    )
    
    # БАГ #2 и #3: Регистрируем владельца капчи для проверки кнопок
    if source in {"join_request", "invite", "manual"}:
        owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat.id, message_id=msg.message_id)
        await redis.setex(owner_key, settings.message_ttl_seconds, str(user.id))
        logger.info(f"✅ [CAPTCHA_FLOW] Зарегистрирован владелец капчи: user_id={user.id}, chat_id={chat.id}, message_id={msg.message_id}")

    await store_captcha_state(
        chat_id=chat.id,
        user_id=user.id,
        state={
            "source": source,
            "chat_id": chat.id,
            "initiator_id": getattr(initiator, "id", None),
        },
        ttl=settings.timeout_seconds,
    )

    asyncio.create_task(
        delete_message_after_delay(
            bot,
            target_chat_id,
            msg.message_id,
            settings.message_ttl_seconds,
        )
    )

    try:
        async with get_session() as session:
            await log_join_request(
                bot=bot,
                user=user,
                chat=chat,
                captcha_status="CAPTCHA_SENT",
                saved_to_db=False,
                session=session,
            )
    except Exception as exc:
        logger.error("Failed to log captcha prompt: %s", exc)
