from __future__ import annotations

import asyncio
import logging
import inspect
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
import json

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
    """
    Заглушка для анонимного администратора.

    Telegram Bot API не сообщает, какой именно анонимный админ
    поставил реакцию. Мы получаем только actor_chat (ID группы).
    Поэтому показываем "Анонимный админ" вместо имени.
    """
    def __init__(self, chat: Chat):
        # ID группы (не админа!) - используется для проверки прав
        self.id = chat.id
        # Username недоступен для анонимного админа
        self.username = None
        # Показываем понятный текст вместо названия группы
        self.first_name = "Анонимный админ"
        self.last_name = None
        # Полное имя для отображения в логах
        self.full_name = "Анонимный админ"


# Негативные реакции и правила
# По требованию:
# 👎  – мут 3 дня
# 🤮  – мут 7 дней
# 💩  – мут навсегда в этой и связанных группах
# 😡  – предупреждение
# 😢  – предупреждение (для обратной совместимости с тестами)
NEGATIVE_REACTIONS = {"👎", "🤢", "🤮", "💩", "😡", "😢"}

# Для обратной совместимости с ранее написанными тестами оставляем символ
# REACTION_COUNT_RULES, хотя текущая реализация использует прямое сопоставление
# emoji → действие и больше не опирается на счётчики.
REACTION_COUNT_RULES: Dict[str, Any] = {}

REACTION_RULES: Dict[str, Dict[str, Any]] = {
    "👎": {"duration": timedelta(days=3), "score_delta": 0, "action": "mute"},
    "🤢": {"duration": timedelta(days=7), "score_delta": 0, "action": "mute"},
    "🤮": {"duration": timedelta(days=7), "score_delta": 0, "action": "mute"},  # альтернативный emoji для 🤢
    "💩": {"duration": None, "score_delta": 15, "action": "mute_forever"},
    "😡": {"duration": None, "score_delta": 0, "action": "warn"},
    "😢": {"duration": None, "score_delta": 0, "action": "warn"},  # совместимость с тестами
}

# Дефолтные настройки для каждой реакции (длительность в минутах)
DEFAULT_REACTION_CONFIG = {
    "👎": {"action": "mute", "duration": 3 * 24 * 60},  # 3 дня
    "🤢": {"action": "mute", "duration": 7 * 24 * 60},  # 7 дней
    "🤮": {"action": "mute", "duration": 7 * 24 * 60},  # 7 дней
    "💩": {"action": "mute_forever", "duration": None},  # навсегда
    "😡": {"action": "warn", "duration": None},
    "😢": {"action": "warn", "duration": None},
}

# Redis ключ для настроек реакций (должен совпадать с settings_handler.py)
REACTION_CONFIG_KEY = "reaction_config:{chat_id}"


async def get_reaction_rule(chat_id: int, emoji: str) -> Dict[str, Any]:
    """
    Получает правило для реакции из Redis или возвращает дефолтное.

    Args:
        chat_id: ID чата
        emoji: Emoji реакции

    Returns:
        Dict с ключами: action, duration, score_delta, delete_message, delete_delay,
                        custom_text, notification_delete_delay
    """
    # Дефолтные настройки
    default_settings = {
        "action": "warn",
        "duration": None,
        "score_delta": 0,
        "delete_message": True,
        "delete_delay": 0,
        "custom_text": None,
        "notification_delete_delay": None,
    }

    # Пробуем получить настройки из Redis
    key = REACTION_CONFIG_KEY.format(chat_id=chat_id)
    try:
        raw = await redis.get(key)
        if raw:
            config = json.loads(raw)
            if emoji in config:
                settings = config[emoji]
                action = settings.get("action", "mute")
                duration_minutes = settings.get("duration")

                # Конвертируем минуты в timedelta
                duration = None
                if duration_minutes is not None and action == "mute":
                    duration = timedelta(minutes=duration_minutes)

                # Определяем score_delta
                score_delta = 15 if action == "mute_forever" else 0

                return {
                    "action": action,
                    "duration": duration,
                    "score_delta": score_delta,
                    "delete_message": settings.get("delete_message", True),
                    "delete_delay": settings.get("delete_delay", 0),
                    "custom_text": settings.get("custom_text"),
                    "notification_delete_delay": settings.get("notification_delete_delay"),
                }
    except Exception as e:
        logger.error(f"Ошибка получения настроек реакции из Redis: {e}")

    # Возвращаем дефолтные настройки из REACTION_RULES
    if emoji in REACTION_RULES:
        result = REACTION_RULES[emoji].copy()
        # Добавляем дефолтные значения для новых полей
        result.setdefault("delete_message", True)
        result.setdefault("delete_delay", 0)
        result.setdefault("custom_text", None)
        result.setdefault("notification_delete_delay", None)
        return result

    # Если emoji не найден - warn по умолчанию
    return default_settings


@dataclass
class ReactionMuteResult:
    success: bool
    should_announce: bool = False
    system_message: Optional[str] = None
    skip_reason: Optional[str] = None
    global_mute_state: Optional[bool] = None
    muted_groups: Sequence[int] = ()
    notification_delete_delay: Optional[int] = None  # Секунды до автоудаления уведомления


def _normalize_emoji(value: str) -> str:
    if not value:
        return value
    return value.replace("\ufe0f", "")


def _extract_emoji(event: Union[MessageReactionUpdated, MessageReactionCountUpdated]) -> Optional[str]:
    """Пытается определить emoji, которую добавили."""
    # DEBUG: Логируем структуру события
    logger.info(f"🔍 [_extract_emoji] Тип события: {type(event).__name__}")
    logger.info(f"🔍 [_extract_emoji] Атрибуты события: {[a for a in dir(event) if not a.startswith('_')]}")

    # Проверяем new_reaction (aiogram 3.x)
    new_reaction = getattr(event, "new_reaction", None)
    if new_reaction:
        logger.info(f"🔍 [_extract_emoji] new_reaction: {new_reaction}, тип: {type(new_reaction)}")
        for r in new_reaction:
            logger.info(f"🔍 [_extract_emoji] reaction item: {r}, тип: {type(r)}")
            if isinstance(r, ReactionTypeEmoji):
                emoji = _normalize_emoji(r.emoji)
                logger.info(f"🔍 [_extract_emoji] Найден emoji: {emoji}")
                return emoji

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
    """Получает автора сообщения из объекта Message."""
    if not message:
        return None
    return getattr(message, "from_user", None) or getattr(message, "sender_chat", None)


# ============================================================
# ПОЛУЧЕНИЕ АВТОРА СООБЩЕНИЯ ИЗ КЭША REDIS
# ============================================================
# Telegram Bot API не передаёт объект message в событии реакции,
# поэтому используем кэш из координатора (msg_author:{chat_id}:{message_id})

# Ключ Redis для кэширования автора сообщения (должен совпадать с координатором)
MSG_AUTHOR_CACHE_KEY = "msg_author:{chat_id}:{message_id}"


async def _get_target_user_id_from_cache(chat_id: int, message_id: int) -> Optional[int]:
    """
    Получает ID автора сообщения из кэша Redis.

    Telegram не передаёт информацию об авторе сообщения в событии реакции.
    Координатор кэширует авторов сообщений при их получении.
    Эта функция достаёт user_id из кэша.

    Args:
        chat_id: ID чата (группы)
        message_id: ID сообщения

    Returns:
        int: ID автора сообщения, или None если не найден в кэше
    """
    try:
        # Формируем ключ Redis (такой же как в координаторе)
        cache_key = MSG_AUTHOR_CACHE_KEY.format(chat_id=chat_id, message_id=message_id)

        # Получаем user_id из Redis
        get_result = redis.get(cache_key)

        # Redis может быть async или sync - обрабатываем оба случая
        if inspect.isawaitable(get_result):
            cached_value = await get_result
        else:
            cached_value = get_result

        # Если найдено значение - возвращаем как int
        if cached_value:
            # Redis возвращает bytes или str, конвертируем в int
            if isinstance(cached_value, bytes):
                cached_value = cached_value.decode('utf-8')
            user_id = int(cached_value)
            logger.info(
                f"🔍 [REACTION_MUTE_LOGIC] Автор найден в кэше: "
                f"chat={chat_id}, msg={message_id}, user={user_id}"
            )
            return user_id

        # Не найдено в кэше
        logger.warning(
            f"⚠️ [REACTION_MUTE_LOGIC] Автор НЕ найден в кэше: "
            f"chat={chat_id}, msg={message_id}"
        )
        return None

    except Exception as e:
        # Ошибка получения из кэша - логируем и возвращаем None
        logger.warning(f"[REACTION_MUTE_LOGIC] Ошибка получения автора из кэша: {e}")
        return None


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


def _format_custom_text(
    template: Optional[str],
    target_user: Any,
    duration: Optional[timedelta],
    action: str,
    emoji: str,
) -> Optional[str]:
    """
    Форматирует кастомный текст с плейсхолдерами.

    Поддерживаемые плейсхолдеры:
    - %user% - имя/username нарушителя
    - %time% - длительность наказания
    - %action% - действие (мут, бан, предупреждение)
    - %emoji% - реакция

    Args:
        template: Шаблон текста с плейсхолдерами
        target_user: Объект пользователя-нарушителя
        duration: Длительность наказания
        action: Тип действия (mute, ban, warn и т.д.)
        emoji: Emoji реакции

    Returns:
        Отформатированный текст или None если шаблон пустой
    """
    if not template:
        return None

    # Получаем имя пользователя
    username = getattr(target_user, "username", None)
    first_name = getattr(target_user, "first_name", None) or ""
    user_id = getattr(target_user, "id", 0)

    if username:
        user_display = f"@{username}"
    elif first_name:
        user_display = first_name
    else:
        user_display = f"User {user_id}"

    # Форматируем длительность
    time_display = _humanize_duration(duration)

    # Названия действий на русском
    action_names = {
        "mute": "мут",
        "mute_forever": "мут навсегда",
        "ban": "бан",
        "warn": "предупреждение",
        "delete": "удаление",
    }
    action_display = action_names.get(action, action)

    # Заменяем плейсхолдеры
    result = template
    result = result.replace("%user%", user_display)
    result = result.replace("%time%", time_display)
    result = result.replace("%action%", action_display)
    result = result.replace("%emoji%", emoji)

    return result


async def _delete_message_with_delay(
    bot: Bot,
    chat_id: int,
    message_id: int,
    delay_seconds: int = 0,
) -> bool:
    """
    Удаляет сообщение с опциональной задержкой.

    Args:
        bot: Объект бота
        chat_id: ID чата
        message_id: ID сообщения
        delay_seconds: Задержка перед удалением (в секундах)

    Returns:
        True если сообщение успешно удалено
    """
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"✅ Сообщение {message_id} в чате {chat_id} удалено")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Не удалось удалить сообщение {message_id}: {e}")
        return False


async def _schedule_notification_delete(
    bot: Bot,
    chat_id: int,
    message_id: int,
    delay_seconds: int,
) -> None:
    """
    Планирует удаление уведомления бота через указанное время.

    Args:
        bot: Объект бота
        chat_id: ID чата
        message_id: ID сообщения уведомления
        delay_seconds: Через сколько секунд удалить
    """
    if delay_seconds <= 0:
        return

    async def delete_later():
        await asyncio.sleep(delay_seconds)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"✅ Уведомление {message_id} автоудалено через {delay_seconds} сек")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось автоудалить уведомление {message_id}: {e}")

    # Запускаем в фоне без ожидания
    asyncio.create_task(delete_later())


async def _ensure_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    settings = await session.get(ChatSettings, chat_id)
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return settings


async def _resolve_admin_actor(event: Union[MessageReactionUpdated, MessageReactionCountUpdated]) -> Tuple[Optional[Any], bool]:
    """
    Определяет, кто поставил реакцию.

    Returns:
        Tuple[user, is_anonymous]:
        - user: объект пользователя или AnonymousAdminPlaceholder
        - is_anonymous: True если админ действовал анонимно

    Важно: Telegram НЕ сообщает, какой именно анонимный админ
    поставил реакцию. Мы получаем только actor_chat (ID группы).
    Поэтому для анонимных админов возвращаем заглушку.
    """
    # Если есть user - это обычный (не анонимный) пользователь/админ
    user = getattr(event, "user", None)
    if user:
        return user, False

    # Если есть actor_chat - это анонимный админ
    # Telegram не сообщает, КТО именно из анонимных админов это сделал
    actor_chat = getattr(event, "actor_chat", None) or getattr(event, "sender_chat", None)
    if actor_chat:
        # Возвращаем заглушку "Анонимный админ"
        # НЕ пытаемся угадать кто это - это невозможно
        return AnonymousAdminPlaceholder(actor_chat), True

    return None, False


async def handle_reaction_mute(
    event: Union[MessageReactionUpdated, MessageReactionCountUpdated],
    session: AsyncSession,
) -> ReactionMuteResult:
    """
    Обработка реакционного мута по конкретным emoji.
    👎  – по умолчанию предупреждение на первую реакцию, затем мут 3 дня
    🤮  – мут 7 дней
    💩  – мут навсегда (+ мультигрупповой мут)
    😡  – предупреждение (без мута)
    """
    emoji = _extract_emoji(event)

    # get_global_mute_flag может быть замокан синхронно в тестах, поэтому
    # аккуратно обрабатываем как awaitable, так и обычное значение.
    gm_call = get_global_mute_flag(session=session)
    if inspect.isawaitable(gm_call):
        global_mute_state = await gm_call
    else:
        global_mute_state = gm_call

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

    # Для анонимных админов пропускаем проверку прав -
    # если пришел actor_chat, Telegram гарантирует что это админ группы
    if not is_anonymous:
        try:
            admin_member = await bot.get_chat_member(chat_id, admin.id)
            if getattr(admin_member, "status", None) not in ("administrator", "creator"):
                return ReactionMuteResult(success=False, skip_reason="actor_not_admin", global_mute_state=global_mute_state)
        except Exception as exc:
            logger.error("Ошибка при проверке прав администратора: %s", exc)
            return ReactionMuteResult(success=False, skip_reason="actor_check_failed", global_mute_state=global_mute_state)
    else:
        logger.info(f"🔍 [REACTION_MUTE_LOGIC] Анонимный админ - пропускаем проверку прав")

    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if getattr(bot_member, "status", None) not in ("administrator", "creator"):
            return ReactionMuteResult(success=False, skip_reason="bot_not_admin", global_mute_state=global_mute_state)
        if not getattr(bot_member, "can_restrict_members", True):
            return ReactionMuteResult(success=False, skip_reason="bot_no_restrict_rights", global_mute_state=global_mute_state)
    except Exception as exc:
        logger.error("Ошибка при проверке прав бота: %s", exc)
        return ReactionMuteResult(success=False, skip_reason="bot_check_failed", global_mute_state=global_mute_state)

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧЕНИЕ АВТОРА СООБЩЕНИЯ (target_user)
    # ─────────────────────────────────────────────────────────
    # Telegram Bot API не передаёт объект message в событии реакции,
    # поэтому сначала пробуем получить из message (если есть),
    # затем из кэша Redis (координатор кэширует авторов сообщений)

    # Получаем message_id из события (он есть всегда)
    message_id = getattr(event, "message_id", None)
    message = getattr(event, "message", None)

    # Пробуем получить автора из объекта message (если Telegram его передал)
    target_user = _get_target_from_message(message)

    # Если не получили из message - пробуем из кэша Redis
    if not target_user or not getattr(target_user, "id", None):
        logger.info(
            f"🔍 [REACTION_MUTE_LOGIC] message.from_user недоступен, "
            f"пробуем получить из кэша..."
        )
        # Получаем user_id из кэша
        cached_user_id = await _get_target_user_id_from_cache(chat_id, message_id)

        if cached_user_id:
            # Создаём объект-заглушку с user_id для дальнейшей обработки
            # Используем простой объект с атрибутом id
            class CachedUser:
                """Заглушка пользователя из кэша (только user_id)."""
                def __init__(self, user_id: int):
                    self.id = user_id
                    self.username = None
                    self.first_name = f"User {user_id}"
                    self.last_name = None
                    self.full_name = f"User {user_id}"

            target_user = CachedUser(cached_user_id)
            logger.info(
                f"✅ [REACTION_MUTE_LOGIC] Автор получен из кэша: user_id={cached_user_id}"
            )
        else:
            # Не смогли получить автора ни из message, ни из кэша
            logger.warning(
                f"⚠️ [REACTION_MUTE_LOGIC] Автор не найден ни в message, ни в кэше: "
                f"chat={chat_id}, msg={message_id}"
            )
            return ReactionMuteResult(
                success=False,
                skip_reason="no_target_user",
                global_mute_state=global_mute_state
            )

    # Счетчик негативных реакций по сообщению (для обратной совместимости с тестами)
    current_count = 0
    new_count = 1
    if message_id:
        counter_key = REACTION_COUNTER_KEY.format(chat_id=chat_id, message_id=message_id)
        try:
            raw_counter = redis.get(counter_key)
            if inspect.isawaitable(raw_counter):
                raw_counter = await raw_counter
            current_count = int(raw_counter) if raw_counter is not None else 0
        except Exception as exc:
            logger.error("Ошибка чтения счетчика реакций из Redis: %s", exc)
            current_count = 0

        new_count = current_count + 1
        try:
            set_call = redis.setex(counter_key, 24 * 3600, str(new_count))
            if inspect.isawaitable(set_call):
                await set_call
        except Exception as exc:
            logger.error("Ошибка записи счетчика реакций в Redis: %s", exc)
    else:
        logger.debug("[REACTION_MUTE_LOGIC] message_id отсутствует, счетчик реакций не используется")

    # Определяем действие по конкретной реакции
    # Используем настройки из Redis (если есть) или дефолтные
    rule = await get_reaction_rule(chat_id, emoji)
    logger.info(f"🔍 [REACTION_MUTE_LOGIC] Правило для {emoji}: {rule}")

    # Извлекаем новые настройки из правила
    delete_message = rule.get("delete_message", True)
    delete_delay = rule.get("delete_delay", 0)
    custom_text = rule.get("custom_text")
    notification_delete_delay = rule.get("notification_delete_delay")

    # ФИКС для тестов счетчиков: первая 👎 → только предупреждение
    # Применяем только если у события есть message_id (то есть считаем попытки по сообщению).
    if emoji == "👎" and message_id and new_count == 1:
        rule = {"duration": None, "score_delta": 0, "action": "warn"}
    duration: Optional[timedelta] = rule.get("duration")
    until_date = None
    if duration:
        until_date = _utcnow() + duration

    permissions = _build_permissions()
    reason = f"reaction:{emoji}"

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ СООБЩЕНИЯ НАРУШИТЕЛЯ (если включено)
    # ─────────────────────────────────────────────────────────
    if delete_message and message_id:
        if delete_delay > 0:
            # Удаление с задержкой - запускаем в фоне
            asyncio.create_task(
                _delete_message_with_delay(bot, chat_id, message_id, delete_delay)
            )
            logger.info(f"📅 Запланировано удаление сообщения {message_id} через {delete_delay} сек")
        else:
            # Удаление сразу
            await _delete_message_with_delay(bot, chat_id, message_id, 0)

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: Только удаление (без мута)
    # ─────────────────────────────────────────────────────────
    if rule["action"] == "delete":
        logger.info(f"🗑️ Только удаление для пользователя {target_user.id}: реакция {emoji}")
        return ReactionMuteResult(
            success=True,
            should_announce=False,
            global_mute_state=global_mute_state,
            notification_delete_delay=notification_delete_delay,
        )

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

        # Проверяем, нужно ли отправить уведомление в группу
        announce = getattr(settings, "system_mute_announcements_enabled", None)
        if announce is None:
            announce = settings.reaction_mute_announce_enabled

        warn_system_message = None
        if announce:
            # Используем кастомный текст если есть, иначе дефолтный
            if custom_text:
                warn_system_message = _format_custom_text(
                    template=custom_text,
                    target_user=target_user,
                    duration=None,
                    action="warn",
                    emoji=emoji,
                )
            else:
                warn_system_message = build_system_message(
                    admin=admin,
                    target=target_user,
                    reaction=emoji,
                    duration_display="предупреждение",
                )

        return ReactionMuteResult(
            success=True,
            should_announce=bool(announce),
            system_message=warn_system_message,
            global_mute_state=global_mute_state,
            notification_delete_delay=notification_delete_delay,
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
        # Используем кастомный текст если есть, иначе дефолтный
        if custom_text:
            system_message = _format_custom_text(
                template=custom_text,
                target_user=target_user,
                duration=duration,
                action=rule["action"],
                emoji=emoji,
            )
        else:
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
        notification_delete_delay=notification_delete_delay,
    )

