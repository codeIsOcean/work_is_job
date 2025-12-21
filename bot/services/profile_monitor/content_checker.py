# ============================================================
# CONTENT CHECKER - ПРОВЕРКА ИМЕНИ/BIO НА ЗАПРЕЩЁННЫЙ КОНТЕНТ
# ============================================================
# Критерий 6 для Profile Monitor:
# Проверяет имя пользователя и bio на запрещённые слова из ContentFilter.
#
# Использует ТОЛЬКО WordFilter с категориями:
# - harmful: наркотики (кокс, шишки, экстази)
# - obfuscated: l33tspeak нормализация ("К о к с" → "кокс")
#
# НЕ использует:
# - simple: будут ложные муты
# - ScamDetector: не нужен для имён
#
# Мутит СРАЗУ при обнаружении, не ждёт сообщения.
# Действие берётся из ContentFilter (мут/бан/кик + длительность).
# ============================================================

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.content_filter.word_filter import WordFilter

logger = logging.getLogger(__name__)

# Категории которые проверяем (без simple - ложные муты)
ALLOWED_CATEGORIES = {"harmful", "obfuscated"}


@dataclass
class ContentCheckResult:
    """
    Результат проверки контента в имени/bio.

    Attributes:
        should_act: Нужно ли применять действие
        action: delete/warn/mute/kick/ban (из ContentFilter)
        action_duration: Длительность в минутах (None = навсегда)
        reason: Причина для лога
        matched_word: Какое слово сработало
        category: harmful/obfuscated
    """

    should_act: bool
    action: Optional[str] = None
    action_duration: Optional[int] = None
    reason: Optional[str] = None
    matched_word: Optional[str] = None
    category: Optional[str] = None


async def check_name_and_bio_content(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    full_name: str,
    bio: Optional[str] = None,
) -> ContentCheckResult:
    """
    Проверяет имя и bio на запрещённый контент.

    Использует ТОЛЬКО WordFilter (harmful + obfuscated).
    Действие берётся из WordFilter — если там настроено "мут навсегда" → мутим навсегда.

    Args:
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        full_name: Полное имя (first_name + last_name)
        bio: Bio пользователя (опционально)

    Returns:
        ContentCheckResult с информацией о необходимом действии
    """
    word_filter = WordFilter()

    # ─────────────────────────────────────────────────────────
    # 1. Проверка имени через WordFilter
    # ─────────────────────────────────────────────────────────
    if full_name and full_name.strip():
        name_result = await word_filter.check(
            text=full_name,
            chat_id=chat_id,
            session=session,
        )

        # Фильтруем только harmful и obfuscated категории
        if name_result.matched and name_result.category in ALLOWED_CATEGORIES:
            logger.warning(
                f"[CONTENT_CHECKER] Запрещённое слово в имени: "
                f"user={user_id} chat={chat_id} word={name_result.word} "
                f"category={name_result.category} action={name_result.action}"
            )
            return ContentCheckResult(
                should_act=True,
                action=name_result.action or "mute",  # Default: mute
                action_duration=name_result.action_duration,  # None = навсегда
                reason=f"Запрещённое слово в имени: {name_result.word}",
                matched_word=name_result.word,
                category=name_result.category,
            )

    # ─────────────────────────────────────────────────────────
    # 2. Проверка bio через WordFilter (если есть)
    # ─────────────────────────────────────────────────────────
    if bio and bio.strip():
        bio_result = await word_filter.check(
            text=bio,
            chat_id=chat_id,
            session=session,
        )

        if bio_result.matched and bio_result.category in ALLOWED_CATEGORIES:
            logger.warning(
                f"[CONTENT_CHECKER] Запрещённое слово в bio: "
                f"user={user_id} chat={chat_id} word={bio_result.word} "
                f"category={bio_result.category} action={bio_result.action}"
            )
            return ContentCheckResult(
                should_act=True,
                action=bio_result.action or "mute",
                action_duration=bio_result.action_duration,
                reason=f"Запрещённое слово в bio: {bio_result.word}",
                matched_word=bio_result.word,
                category=bio_result.category,
            )

    # Ничего не найдено
    return ContentCheckResult(should_act=False)


async def apply_content_filter_action(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action: str,
    duration: Optional[int],
    reason: str,
) -> bool:
    """
    Применяет действие из ContentFilter.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя
        action: mute/ban/kick/warn/delete
        duration: Длительность в минутах (None = навсегда)
        reason: Причина для лога

    Returns:
        True если действие выполнено успешно
    """
    try:
        if action == "mute":
            # Вычисляем until_date
            if duration is None or duration == 0:
                # Мут навсегда (используем далёкую дату)
                until_date = None
            else:
                until_date = datetime.now() + timedelta(minutes=duration)

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
            logger.warning(
                f"[CRITERION_6] MUTE: user={user_id} chat={chat_id} "
                f"duration={'forever' if duration is None else f'{duration}min'} "
                f"reason={reason}"
            )

        elif action == "ban":
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.warning(
                f"[CRITERION_6] BAN: user={user_id} chat={chat_id} reason={reason}"
            )

        elif action == "kick":
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.warning(
                f"[CRITERION_6] KICK: user={user_id} chat={chat_id} reason={reason}"
            )

        elif action == "warn":
            # Предупреждение - просто логируем, можно добавить отправку сообщения
            logger.warning(
                f"[CRITERION_6] WARN: user={user_id} chat={chat_id} reason={reason}"
            )

        elif action == "delete":
            # Удаление - в контексте имени/bio не применимо
            logger.info(
                f"[CRITERION_6] DELETE action ignored for name/bio: "
                f"user={user_id} chat={chat_id}"
            )
            return False

        else:
            logger.warning(
                f"[CRITERION_6] Unknown action '{action}': "
                f"user={user_id} chat={chat_id}"
            )
            return False

        return True

    except Exception as e:
        logger.error(
            f"[CRITERION_6] Failed to apply action '{action}': "
            f"user={user_id} chat={chat_id} error={e}"
        )
        return False
