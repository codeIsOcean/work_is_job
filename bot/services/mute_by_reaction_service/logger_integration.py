from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional, Sequence

from aiogram import Bot
from aiogram.types import User
from sqlalchemy.ext.asyncio import AsyncSession

async def log_reaction_mute(
    *,
    bot: Bot,
    session: AsyncSession,
    group_id: int,
    admin: User,
    target: User,
    reaction: str,
    duration: Optional[timedelta],
    muted_groups: Sequence[int],
    global_mute_state: bool,
    admin_anonymous: bool,
    message_id: Optional[int],
) -> None:
    additional_info: Dict[str, object] = {
        "reaction": reaction,
        "status": "mute",
        "duration_seconds": int(duration.total_seconds()) if duration else None,
        "muted_groups": list(muted_groups),
        "global_mute": global_mute_state,
        "admin_anonymous": admin_anonymous,
        "origin_message_id": message_id,
    }

    from bot.services.bot_activity_journal.bot_activity_journal_logic import (
        send_activity_log,
    )

    await send_activity_log(
        bot=bot,
        event_type="REACTION_MUTE",
        user_data={
            "user_id": target.id,
            "username": getattr(target, "username", None),
            "first_name": getattr(target, "first_name", None),
            "last_name": getattr(target, "last_name", None),
        },
        group_data={"chat_id": group_id, "title": "", "username": None},
        additional_info={
            **additional_info,
            "admin": {
                "user_id": admin.id,
                "username": getattr(admin, "username", None),
                "first_name": getattr(admin, "first_name", None),
                "last_name": getattr(admin, "last_name", None),
                "display": getattr(admin, "full_name", None),
            },
        },
        status="success",
        session=session,
    )


async def log_warning_reaction(
    *,
    bot: Bot,
    session: AsyncSession,
    group_id: int,
    admin: User,
    target: User,
    reaction: str,
    admin_anonymous: bool,
) -> None:
    from bot.services.bot_activity_journal.bot_activity_journal_logic import (
        send_activity_log,
    )

    await send_activity_log(
        bot=bot,
        event_type="REACTION_WARNING",
        user_data={
            "user_id": target.id,
            "username": getattr(target, "username", None),
            "first_name": getattr(target, "first_name", None),
            "last_name": getattr(target, "last_name", None),
        },
        group_data={"chat_id": group_id, "title": "", "username": None},
        additional_info={
            "reaction": reaction,
            "admin_anonymous": admin_anonymous,
            "admin": {
                "user_id": admin.id,
                "username": getattr(admin, "username", None),
                "first_name": getattr(admin, "first_name", None),
                "last_name": getattr(admin, "last_name", None),
                "display": getattr(admin, "full_name", None),
            },
        },
        status="warning",
        session=session,
    )


def build_system_message(
    *,
    admin: User,
    target: User,
    reaction: str,
    duration_display: str,
) -> str:
    admin_display = f"@{admin.username}" if getattr(admin, "username", None) else admin.id
    target_display = f"@{target.username}" if getattr(target, "username", None) else target.id
    if duration_display == "∞":
        duration_text = "навсегда"
    else:
        duration_text = f"на {duration_display}"
    return (
        f"Пользователь {target_display} получил мьют {duration_text} "
        f"за реакцию {reaction} (от {admin_display})."
    )

