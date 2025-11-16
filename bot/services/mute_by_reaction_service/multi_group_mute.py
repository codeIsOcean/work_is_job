from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import UserGroup

logger = logging.getLogger(__name__)


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


def _calc_until(duration: Optional[timedelta]) -> Optional[datetime]:
    if duration is None:
        return None
    return datetime.now(timezone.utc).replace(tzinfo=None) + duration


@dataclass
class MultiGroupMuteResult:
    chat_id: int
    success: bool
    reason: Optional[str] = None


async def mute_across_groups(
    admin_id: int,
    target_id: int,
    duration: Optional[timedelta],
    reason: str,
    session: AsyncSession,
    bot: Bot,
) -> List[MultiGroupMuteResult]:
    """
    Применяет mute во всех группах, где администратор и бот обладают правами.
    Возвращает список chat_id, где удалось применить ограничение.
    """
    result = await session.execute(
        select(UserGroup.group_id).where(UserGroup.user_id == admin_id)
    )
    candidate_group_ids = {row[0] for row in result.fetchall()}

    results: List[MultiGroupMuteResult] = []
    until_date = _calc_until(duration)
    permissions = _build_permissions()

    for group_id in candidate_group_ids:
        try:
            bot_member = await bot.get_chat_member(group_id, bot.id)
            if getattr(bot_member, "status", None) not in ("administrator", "creator"):
                continue
            if not getattr(bot_member, "can_restrict_members", True):
                continue

            admin_member = await bot.get_chat_member(group_id, admin_id)
            if getattr(admin_member, "status", None) not in ("administrator", "creator"):
                continue

            await bot.restrict_chat_member(
                chat_id=group_id,
                user_id=target_id,
                permissions=permissions,
                until_date=until_date,
            )
            results.append(MultiGroupMuteResult(chat_id=group_id, success=True))
        except Exception as exc:
            logger.warning(
                "Не удалось замьютить пользователя %s в группе %s: %s",
                target_id,
                group_id,
                exc,
            )
            results.append(
                MultiGroupMuteResult(
                    chat_id=group_id,
                    success=False,
                    reason=str(exc),
                )
            )

    return results

