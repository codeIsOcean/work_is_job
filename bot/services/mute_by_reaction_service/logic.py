from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Dict, Any, Tuple

from aiogram import Bot
from aiogram.types import (
    ChatPermissions,
    Message,
    MessageReactionUpdated,
    MessageReactionCountUpdated,
    ReactionTypeEmoji,
    ReactionTypeCustomEmoji,
    Chat,
)
from typing import Union
import unicodedata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ChatSettings
from bot.database.mute_models import GroupMute, UserScore
from bot.database.models import UserGroup
from bot.services.redis_conn import redis
from bot.services.global_mute_policy import get_global_mute_flag

# ФИКС №8: Ключ для счетчика негативных реакций по сообщению
REACTION_COUNTER_KEY = "reaction:count:{chat_id}:{message_id}"
from .multi_group_mute import mute_across_groups
from .logger_integration import (
    build_system_message,
    log_reaction_mute,
    log_warning_reaction,
)

logger = logging.getLogger(__name__)


class AnonymousAdminPlaceholder:
    def __init__(self, chat: Chat):
        self.id = chat.id
        self.username = None
        self.first_name = chat.title
        self.last_name = None
        self.full_name = chat.title


# Негативные реакции и правила
# По требованию:
# 👎  – мут 3 дня
# 🤮  – мут 7 дней
# 💩  – мут навсегда в этой и связанных группах
# 😡  – предупреждение
NEGATIVE_REACTIONS = {"👎", "🤢", "💩", "😡"}

# Для обратной совместимости с ранее написанными тестами оставляем символ
# REACTION_COUNT_RULES, хотя текущая реализация использует прямое сопоставление
# emoji → действие и больше не опирается на счётчики.
REACTION_COUNT_RULES: Dict[str, Any] = {}

REACTION_RULES: Dict[str, Dict[str, Any]] = {
    "👎": {"duration": timedelta(days=3), "score_delta": 0, "action": "mute"},
    "🤢": {"duration": timedelta(days=7), "score_delta": 0, "action": "mute"},
    "💩": {"duration": None, "score_delta": 15, "action": "mute_forever"},
    "😡": {"duration": None, "score_delta": 0, "action": "warn"},
}


@dataclass
class ReactionMuteResult:
    success: bool
    should_announce: bool = False
    system_message: Optional[str] = None
    skip_reason: Optional[str] = None
    global_mute_state: Optional[bool] = None
    muted_groups: Sequence[int] = ()


def _normalize_emoji(value: str) -> str:
    if not value:
        return value
    return value.replace("\ufe0f", "")


def _extract_emoji(event: Union[MessageReactionUpdated, MessageReactionCountUpdated]) -> Optional[str]:
    """Пытается определить emoji, которую добавили."""
    # БАГ №8: Обработка MessageReactionCountUpdated
    if isinstance(event, MessageReactionCountUpdated):
        # MessageReactionCountUpdated имеет другую структуру
        reactions = getattr(event, "reactions", None) or ()
        for reaction in reactions:
            reaction_type = getattr(reaction, "type", None)
            if isinstance(reaction_type, ReactionTypeEmoji):
                emoji = _normalize_emoji(reaction_type.emoji)
                if emoji in NEGATIVE_REACTIONS:  # ФИКС №8: Используем NEGATIVE_REACTIONS
                    return emoji
            elif isinstance(reaction_type, ReactionTypeCustomEmoji):
                # Для кастомных emoji не обрабатываем
                pass
        return None
    
    # MessageReactionUpdated
    try:
        new_reactions: Sequence = getattr(event, "new_reactions", None) or getattr(event, "reactions", None) or ()
        old_reactions: Sequence = getattr(event, "old_reactions", None) or ()

        def _key(item):
            if isinstance(item, ReactionTypeEmoji):
                return _normalize_emoji(item.emoji)
            if isinstance(item, ReactionTypeCustomEmoji):
                return item.custom_emoji_id
            return getattr(item, "emoji", None)

        old_set = {_key(item) for item in old_reactions if _key(item)}
        for reaction in new_reactions:
            emoji = _key(reaction)
            if emoji and emoji not in old_set:
                return emoji
    except Exception as exc:
        logger.error("Ошибка при разборе реакций: %s", exc)

    # Fallback — кастомное поле new_reaction или single reaction.
    if hasattr(event, "reaction"):
        raw = getattr(event, "reaction", None)
        if isinstance(raw, ReactionTypeEmoji):
            return _normalize_emoji(raw.emoji)
        if isinstance(raw, ReactionTypeCustomEmoji):
            return raw.custom_emoji_id
        return raw
    return None


def _get_target_from_message(message: Optional[Message]) -> Optional[Any]:
    if not message:
        return None
    return getattr(message, "from_user", None) or getattr(message, "sender_chat", None)


def _build_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=False,
        can_pin_messages=False,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _humanize_duration(duration: Optional[timedelta]) -> str:
    if duration is None:
        return "∞"
    total_seconds = int(duration.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    return " ".join(parts) if parts else "0 мин"


async def _ensure_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    settings = await session.get(ChatSettings, chat_id)
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return settings


async def _resolve_admin_actor(event: Union[MessageReactionUpdated, MessageReactionCountUpdated]) -> Tuple[Optional[Any], bool]:
    user = getattr(event, "user", None)
    if user:
        return user, False

    actor_chat = getattr(event, "actor_chat", None) or getattr(event, "sender_chat", None)
    if actor_chat:
        try:
            admins = await event.bot.get_chat_administrators(event.chat.id)
            for admin_member in admins:
                if getattr(admin_member, "is_anonymous", False) and getattr(admin_member, "user", None):
                    return admin_member.user, True
        except Exception as exc:
            logger.warning("Не удалось получить список администраторов для определения анонимного: %s", exc)
        return AnonymousAdminPlaceholder(actor_chat), True

    return None, False


async def handle_reaction_mute(
    event: Union[MessageReactionUpdated, MessageReactionCountUpdated],
    session: AsyncSession,
) -> ReactionMuteResult:
    """
    Обработка реакционного мута по конкретным emoji.
    👎  – мут 3 дня
    🤮  – мут 7 дней
    💩  – мут навсегда (+ мультигрупповой мут)
    😡  – предупреждение (без мута)
    """
    emoji = _extract_emoji(event)
    global_mute_state = await get_global_mute_flag(session=session)

    # БАГ #4: Добавляем логирование для диагностики
    logger.info(f"🔍 [REACTION_MUTE_LOGIC] ===== НАЧАЛО ОБРАБОТКИ РЕАКЦИИ =====")
    logger.info(f"🔍 [REACTION_MUTE_LOGIC] Emoji: {emoji}")
    logger.info(f"🔍 [REACTION_MUTE_LOGIC] Global mute state: {global_mute_state}")
    
    # Проверяем, что это поддерживаемая негативная реакция
    if not emoji or emoji not in REACTION_RULES:
        logger.info(f"🔍 [REACTION_MUTE_LOGIC] Реакция {emoji} не обрабатывается, пропускаем")
        return ReactionMuteResult(success=False, skip_reason="unknown_reaction", global_mute_state=global_mute_state)

    logger.info(f"✅ [REACTION_MUTE_LOGIC] Реакция {emoji} поддерживается, продолжаем обработку")

    chat = getattr(event, "chat", None)
    if chat is None:
        return ReactionMuteResult(success=False, skip_reason="no_chat", global_mute_state=global_mute_state)
    chat_id = chat.id
    logger.info(f"🔍 [REACTION_MUTE_LOGIC] Чат ID: {chat_id}")

    settings = await _ensure_chat_settings(session, chat_id)
    if not settings.reaction_mute_enabled:
        return ReactionMuteResult(success=False, skip_reason="feature_disabled", global_mute_state=global_mute_state)

    admin, is_anonymous = await _resolve_admin_actor(event)
    if admin is None:
        return ReactionMuteResult(success=False, skip_reason="no_actor", global_mute_state=global_mute_state)

    bot: Bot = event.bot
    try:
        admin_member = await bot.get_chat_member(chat_id, admin.id)
        if getattr(admin_member, "status", None) not in ("administrator", "creator"):
            return ReactionMuteResult(success=False, skip_reason="actor_not_admin", global_mute_state=global_mute_state)
    except Exception as exc:
        logger.error("Ошибка при проверке прав администратора: %s", exc)
        return ReactionMuteResult(success=False, skip_reason="actor_check_failed", global_mute_state=global_mute_state)

    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if getattr(bot_member, "status", None) not in ("administrator", "creator"):
            return ReactionMuteResult(success=False, skip_reason="bot_not_admin", global_mute_state=global_mute_state)
        if not getattr(bot_member, "can_restrict_members", True):
            return ReactionMuteResult(success=False, skip_reason="bot_no_restrict_rights", global_mute_state=global_mute_state)
    except Exception as exc:
        logger.error("Ошибка при проверке прав бота: %s", exc)
        return ReactionMuteResult(success=False, skip_reason="bot_check_failed", global_mute_state=global_mute_state)

    target_user = _get_target_from_message(getattr(event, "message", None))
    if not target_user or not getattr(target_user, "id", None):
        return ReactionMuteResult(success=False, skip_reason="no_target_user", global_mute_state=global_mute_state)
    
    message = getattr(event, "message", None)
    if not message:
        return ReactionMuteResult(success=False, skip_reason="no_message", global_mute_state=global_mute_state)
    message_id = getattr(message, "message_id", None)
    if not message_id:
        return ReactionMuteResult(success=False, skip_reason="no_message_id", global_mute_state=global_mute_state)

    # Определяем действие по конкретной реакции
    rule = REACTION_RULES[emoji]
    duration: Optional[timedelta] = rule.get("duration")
    until_date = None
    if duration:
        until_date = _utcnow() + duration

    permissions = _build_permissions()
    reason = f"reaction:{emoji}"

    # Предупреждение без мута
    if rule["action"] == "warn":
        # Логирование не должно ломать основную логику (особенно в unit-тестах)
        try:
            await log_warning_reaction(
                bot=bot,
                session=session,
                group_id=chat_id,
                admin=admin,
                target=target_user,
                reaction=emoji,
                admin_anonymous=is_anonymous,
            )
        except Exception as exc:
            logger.error("Ошибка при логировании предупреждения по реакции: %s", exc)
        logger.info(
            f"⚠️ Предупреждение для пользователя {target_user.id}: негативная реакция {emoji}"
        )
        return ReactionMuteResult(
            success=True,
            should_announce=False,
            global_mute_state=global_mute_state,
        )

    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=permissions,
            until_date=until_date,
        )
    except Exception as exc:
        logger.error("Ошибка при применении mute: %s", exc)
        return ReactionMuteResult(success=False, skip_reason="restrict_failed", global_mute_state=global_mute_state)

    session.add(
        GroupMute(
            group_id=chat_id,
            target_user_id=target_user.id,
            admin_user_id=admin.id,
            reaction=emoji,
            mute_until=until_date,
            reason=reason,
        )
    )

    # Добавляем баллы только для 💩 (mute_forever)
    score_delta = rule.get("score_delta", 0)
    if score_delta:
        user_score = await session.get(UserScore, target_user.id)
        if user_score is None:
            session.add(UserScore(user_id=target_user.id, score=score_delta))
        else:
            user_score.score += score_delta

    await session.commit()
    
    logger.info(f"✅ Мут применен: пользователь {target_user.id}, реакция: {emoji}, действие: {rule['action']}")

    ttl = int(duration.total_seconds()) if duration else None
    redis_key = f"mute:{chat_id}:{target_user.id}"
    try:
        if ttl:
            # Временный мут — TTL равен длительности мута
            setex_obj = redis.setex(redis_key, ttl, "1")
        else:
            # Перманентный мут — используем большой TTL (например, 365 дней)
            setex_obj = redis.setex(redis_key, 365 * 24 * 3600, "1")
        import inspect
        if inspect.isawaitable(setex_obj):
            await setex_obj
    except Exception as exc:
        logger.error("Ошибка при записи в Redis: %s", exc)

    # Мультигрупповой мут только для действия mute_forever (💩)
    multi_results = []
    if rule["action"] == "mute_forever":
        try:
            multi_results = await mute_across_groups(
                admin_id=admin.id,
                target_id=target_user.id,
                duration=None,
                reason=reason,
                session=session,
                bot=bot,
            )
            logger.info(f"✅ Мультигрупповой мут применен для пользователя {target_user.id} в {len(multi_results)} группах")
        except Exception as exc:
            logger.error("Ошибка при мультигрупповом мьюте: %s", exc)
            multi_results = []

    # Логирование мута не должно ломать применение самого мута
    try:
        await log_reaction_mute(
            bot=bot,
            session=session,
            group_id=chat_id,
            admin=admin,
            target=target_user,
            reaction=emoji,
            duration=duration,
            muted_groups=[result.chat_id for result in multi_results if result.success],
            global_mute_state=global_mute_state,
            admin_anonymous=is_anonymous,
            message_id=message_id,
        )
    except Exception as exc:
        logger.error("Ошибка при логировании реакционного мута: %s", exc)

    announce = getattr(settings, "system_mute_announcements_enabled", None)
    if announce is None:
        announce = settings.reaction_mute_announce_enabled
    system_message = None
    if announce:
        system_message = build_system_message(
            admin=admin,
            target=target_user,
            reaction=emoji,
            duration_display=_humanize_duration(duration),
        )

    return ReactionMuteResult(
        success=True,
        should_announce=bool(announce),
        system_message=system_message,
        global_mute_state=global_mute_state,
        muted_groups=[result.chat_id for result in multi_results if result.success],
        skip_reason=None,
    )

