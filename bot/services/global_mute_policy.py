from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.risk_gate import is_suspicious as risk_gate_is_suspicious
from bot.services.redis_conn import redis


logger = logging.getLogger(__name__)


GLOBAL_MUTE_CACHE_KEY = "global_mute_enabled"


async def get_global_mute_flag(session: Optional[AsyncSession] = None) -> bool:
    """Возвращает значение глобального мута, используя Redis как источник истины."""
    cached = await redis.get(GLOBAL_MUTE_CACHE_KEY)
    if cached is not None:
        return cached == "1"

    if session is None:
        # lazy import to avoid circular deps
        from bot.database.session import get_session

        async with get_session() as new_session:
            return await get_global_mute_flag(session=new_session)

    from bot.database.models import ChatSettings

    result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == 0))
    settings = result.scalar_one_or_none()

    flag = bool(getattr(settings, "global_mute_enabled", False))
    await redis.set(GLOBAL_MUTE_CACHE_KEY, "1" if flag else "0")
    return flag


async def set_global_mute_flag(*, enabled: bool, session: AsyncSession) -> None:
    """Сохраняет глобальный мут в Redis и БД."""
    from sqlalchemy import update, insert
    from bot.database.models import ChatSettings

    await redis.set(GLOBAL_MUTE_CACHE_KEY, "1" if enabled else "0")

    result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == 0))
    settings = result.scalar_one_or_none()
    if settings:
        await session.execute(
            update(ChatSettings)
            .where(ChatSettings.chat_id == 0)
            .values(global_mute_enabled=enabled)
        )
    else:
        await session.execute(
            insert(ChatSettings).values(chat_id=0, global_mute_enabled=enabled)
        )


async def should_apply_manual_mute(
    *,
    global_flag: bool,
    user_id: int,
    chat_id: int,
    session: AsyncSession,
    bot: Optional[Bot] = None,
) -> bool:
    """
    Определяет, нужно ли применять ручной мут при одобрении заявки админом.

    ВАЖНО: Глобальный мут = ТОЛЬКО для ручного одобрения заявок!
    - global_flag=True + ручное одобрение → МУТИМ
    - global_flag=False + ручное одобрение → НЕ мутим
    - Капча пройдена → НЕ мутим (глобальный мут не влияет)

    БЕЗ проверки risk_gate - это отдельная функция автомута скаммеров.
    """
    if not global_flag:
        logger.debug(
            "global_mute_policy: global mute DISABLED, skip manual mute for user %s chat %s",
            user_id,
            chat_id,
        )
        return False

    # Глобальный мут включен - мутим ВСЕХ при ручном одобрении
    logger.info(
        "global_mute_policy: global mute ENABLED, will mute user=%s chat=%s",
        user_id,
        chat_id,
    )
    return True
