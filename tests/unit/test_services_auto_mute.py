from contextlib import asynccontextmanager
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import AsyncMock
import sys

import pytest
from aiogram.types import ChatMemberUpdated

from bot.database.models import ChatSettings, Group
from bot.services import auto_mute_scammers_logic as auto_mute_logic


@pytest.mark.asyncio
async def test_get_auto_mute_status_from_redis(fake_redis, db_session):
    await fake_redis.set("group:777:auto_mute_scammers", "0")

    result = await auto_mute_logic.get_auto_mute_scammers_status(777, session=db_session)

    assert result is False


@pytest.mark.asyncio
async def test_get_auto_mute_status_fallback_db(fake_redis, db_session):
    group = Group(chat_id=888, title="Test group")
    db_session.add(group)
    db_session.add(ChatSettings(chat_id=888, auto_mute_scammers=False))
    await db_session.commit()

    result = await auto_mute_logic.get_auto_mute_scammers_status(888, session=db_session)

    assert result is False
    assert await fake_redis.get("group:888:auto_mute_scammers") == "0"


@pytest.mark.asyncio
async def test_set_auto_mute_status_updates_storage(fake_redis, db_session):
    group = Group(chat_id=999, title="Another group")
    db_session.add(group)
    await db_session.commit()

    await auto_mute_logic.set_auto_mute_scammers_status(999, enabled=True, session=db_session)
    await db_session.commit()

    redis_value = await fake_redis.get("group:999:auto_mute_scammers")
    assert redis_value == "1"

    settings = await db_session.get(ChatSettings, 999)
    assert settings is not None
    assert settings.auto_mute_scammers is True


@pytest.mark.asyncio
async def test_auto_mute_scammer_on_join_applies_restriction(
    fake_redis,
    db_session,
    bot_mock,
    monkeypatch,
):
    chat_id = -100123
    user_id = 555

    group = Group(chat_id=chat_id, title="Secure group")
    db_session.add(group)
    await db_session.commit()

    await fake_redis.set(f"group:{chat_id}:auto_mute_scammers", "1")
    await fake_redis.set(f"auto_mute_scammer:{user_id}:{chat_id}", "1")

    @asynccontextmanager
    async def session_ctx():
        yield db_session

    monkeypatch.setattr(auto_mute_logic, "get_session", session_ctx)
    log_mock = AsyncMock()
    monkeypatch.setitem(
        sys.modules,
        "bot.services.bot_activity_journal.bot_activity_journal_logic",
        SimpleNamespace(log_auto_mute_scammer=log_mock),
    )
    monkeypatch.setattr(
        "bot.services.new_member_requested_to_join_mute_logic.get_mute_new_members_status",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bot.services.account_age_estimator.account_age_estimator.get_detailed_age_info",
        lambda _uid: {"age_days": 5, "risk_score": 70},
    )

    async def get_chat_member_side_effect(chat_id_arg, user_or_bot):
        if user_or_bot == bot_mock.id:
            return SimpleNamespace(status="administrator")
        return SimpleNamespace(status="administrator", can_restrict_members=True)

    bot_mock.get_chat_member.side_effect = get_chat_member_side_effect
    bot_mock.get_chat.return_value = SimpleNamespace(title="Secure group", username=None)

    event_payload = {
        "chat": {"id": chat_id, "type": "supergroup", "title": "Secure group"},
        "from": {"id": 1, "is_bot": False, "first_name": "Moderator"},
        "date": int(datetime.now().timestamp()),
        "old_chat_member": {"status": "left", "user": {"id": user_id, "is_bot": False, "first_name": "User"}},
        "new_chat_member": {"status": "member", "user": {"id": user_id, "is_bot": False, "first_name": "User"}},
    }
    event = ChatMemberUpdated.model_validate(event_payload)

    result = await auto_mute_logic.auto_mute_scammer_on_join(bot_mock, event)

    assert result is True
    bot_mock.restrict_chat_member.assert_awaited_once()
    assert await fake_redis.get(f"auto_mute_scammer:{user_id}:{chat_id}") is None

