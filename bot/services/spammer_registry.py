from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.mute_models import SpammerRecord
from bot.database.models import utcnow
from bot.services.mute_by_reaction_service import mute_across_groups, MultiGroupMuteResult


async def get_spammer_record(session: AsyncSession, user_id: int) -> Optional[SpammerRecord]:
    return await session.get(SpammerRecord, user_id)


async def record_spammer_incident(
    session: AsyncSession,
    user_id: int,
    risk_score: int,
    reason: str,
) -> None:
    record = await session.get(SpammerRecord, user_id)
    now = utcnow()
    if record:
        record.risk_score = max(record.risk_score or 0, risk_score)
        record.reason = reason
        record.incidents += 1
        record.last_incident_at = now
    else:
        session.add(
            SpammerRecord(
                user_id=user_id,
                risk_score=risk_score,
                reason=reason,
                incidents=1,
                last_incident_at=now,
            )
        )
    await session.flush()


async def mute_suspicious_user_across_groups(
    *,
    bot: Bot,
    session: AsyncSession,
    target_id: int,
    admin_id: Optional[int],
    duration=None,
    reason: str = "risk_gate",
) -> Sequence[MultiGroupMuteResult]:
    if admin_id is None:
        return []
    return await mute_across_groups(
        admin_id=admin_id,
        target_id=target_id,
        duration=duration,
        reason=reason,
        session=session,
        bot=bot,
    )

