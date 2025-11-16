from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, GroupUsers
from bot.services.enhanced_profile_analyzer import enhanced_profile_analyzer


logger = logging.getLogger(__name__)


async def _fetch_user_snapshot(
    *,
    session: AsyncSession,
    user_id: int,
    chat_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Возвращает данные о пользователе из базы для анализа риска."""
    try:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user_row: Optional[User] = result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("risk_gate: failed to fetch user %s: %s", user_id, exc)
        user_row = None

    snapshot: Dict[str, Any] = {
        "id": user_id,
        "user_id": user_id,
    }

    if user_row:
        snapshot.update(
            {
                "username": user_row.username,
                "first_name": user_row.first_name,
                "last_name": user_row.last_name,
                "full_name": user_row.full_name,
                "language_code": user_row.language_code,
                "is_bot": user_row.is_bot,
                "is_premium": user_row.is_premium,
            }
        )

    if chat_id is not None and "username" not in snapshot:
        try:
            membership = await session.execute(
                select(GroupUsers).where(
                    GroupUsers.user_id == user_id,
                    GroupUsers.chat_id == chat_id,
                )
            )
            member_row: Optional[GroupUsers] = membership.scalar_one_or_none()
            if member_row:
                snapshot.setdefault("username", member_row.username)
                snapshot.setdefault("first_name", member_row.first_name)
                snapshot.setdefault("last_name", member_row.last_name)
        except Exception as exc:
            logger.debug("risk_gate: failed to resolve membership info for %s/%s: %s", user_id, chat_id, exc)

    return snapshot


async def is_suspicious(
    *,
    user_id: int,
    chat_id: int,
    session: AsyncSession,
    bot: Optional[Bot] = None,
) -> bool:
    """Определяет, является ли пользователь подозрительным, используя существующую аналитику проекта."""
    snapshot = await _fetch_user_snapshot(session=session, user_id=user_id, chat_id=chat_id) or {
        "id": user_id,
    }

    try:
        analysis = await enhanced_profile_analyzer.analyze_user_profile_enhanced(snapshot, bot)
    except Exception as exc:
        logger.error("risk_gate: failed to analyze profile for %s: %s", user_id, exc)
        return False

    is_flagged = bool(analysis.get("is_suspicious"))
    logger.info(
        "risk_gate: user %s in chat %s suspicious=%s risk_score=%s",
        user_id,
        chat_id,
        is_flagged,
        analysis.get("risk_score"),
    )
    return is_flagged
