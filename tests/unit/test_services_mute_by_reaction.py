from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bot.database.models import ChatSettings, Group
from bot.database.mute_models import GroupMute, UserScore
from bot.services.mute_by_reaction_service.logic import handle_reaction_mute


def build_event(
    *,
    chat_id: int,
    emoji: str,
    admin_id: int = 111,
    admin_username: str = "admin",
    target_id: int = 999,
    target_username: str = "target",
):
    message = SimpleNamespace(
        from_user=SimpleNamespace(
            id=target_id,
            username=target_username,
            first_name="Target",
            last_name=None,
        )
    )
    chat = SimpleNamespace(id=chat_id, title="Test chat")
    admin = SimpleNamespace(id=admin_id, username=admin_username, first_name="Admin")
    event = SimpleNamespace(
        chat=chat,
        message=message,
        user=admin,
        new_reactions=[SimpleNamespace(emoji=emoji)],
        old_reactions=[],
    )
    return event


@pytest.mark.asyncio
async def test_unknown_reaction_skipped(db_session, fake_redis, monkeypatch):
    event = build_event(chat_id=-100, emoji="👍")
    event.bot = AsyncMock()

    monkeypatch.setattr("bot.services.mute_by_reaction_service.logic.redis", fake_redis)
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.get_global_mute_flag",
        AsyncMock(return_value=False),
    )

    result = await handle_reaction_mute(event=event, session=db_session)

    assert result.success is False
    assert result.skip_reason == "unknown_reaction"


@pytest.mark.asyncio
async def test_reaction_mute_applies(db_session, fake_redis, monkeypatch):
    chat_id = -200
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=True,
        )
    )
    await db_session.commit()

    event = build_event(chat_id=chat_id, emoji="🤢")
    bot = AsyncMock()

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == event.user.id:
            return SimpleNamespace(status="administrator")
        return SimpleNamespace(status="member")

    bot.id = 555
    bot.get_chat_member.side_effect = fake_get_chat_member
    bot.restrict_chat_member = AsyncMock()
    event.bot = bot

    log_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_reaction_mute",
        log_mock,
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_warning_reaction",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.mute_across_groups",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("bot.services.mute_by_reaction_service.logic.redis", fake_redis)
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.get_global_mute_flag",
        AsyncMock(return_value=False),
    )

    result = await handle_reaction_mute(event=event, session=db_session)

    assert result.success is True
    assert result.should_announce is True
    assert result.global_mute_state is False
    bot.restrict_chat_member.assert_awaited_once()

    stored = await db_session.execute(select(GroupMute))
    group_mute = stored.scalars().first()
    assert group_mute is not None
    assert group_mute.reaction == "🤢"

    score_entry = await db_session.get(UserScore, event.message.from_user.id)
    assert score_entry is None

    redis_value = await fake_redis.get(f"mute:{chat_id}:{event.message.from_user.id}")
    assert redis_value == "1"

    log_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_warning_reaction_only_logs(db_session, fake_redis, monkeypatch):
    chat_id = -300
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=True,
        )
    )
    await db_session.commit()

    event = build_event(chat_id=chat_id, emoji="😢")
    bot = AsyncMock()

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == event.user.id:
            return SimpleNamespace(status="administrator")
        return SimpleNamespace(status="member")

    bot.id = 777
    bot.get_chat_member.side_effect = fake_get_chat_member
    bot.restrict_chat_member = AsyncMock()
    event.bot = bot

    log_warning = AsyncMock()
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_warning_reaction",
        log_warning,
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_reaction_mute",
        AsyncMock(),
    )
    monkeypatch.setattr("bot.services.mute_by_reaction_service.logic.redis", fake_redis)
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.get_global_mute_flag",
        AsyncMock(return_value=False),
    )

    result = await handle_reaction_mute(event=event, session=db_session)

    assert result.success is True
    assert result.should_announce is False
    assert result.global_mute_state is False
    bot.restrict_chat_member.assert_not_awaited()
    log_warning.assert_awaited_once()


@pytest.mark.asyncio
async def test_mute_forever_multi_group_results(db_session, fake_redis, monkeypatch):
    chat_id = -400
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=False,
        )
    )
    await db_session.commit()

    event = build_event(chat_id=chat_id, emoji="💩")
    bot = AsyncMock()

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == event.user.id:
            return SimpleNamespace(status="administrator")
        return SimpleNamespace(status="member")

    bot.id = 999
    bot.get_chat_member.side_effect = fake_get_chat_member
    bot.restrict_chat_member = AsyncMock()
    event.bot = bot

    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_reaction_mute",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.mute_across_groups",
        AsyncMock(
            return_value=[
                SimpleNamespace(chat_id=-1, success=True),
                SimpleNamespace(chat_id=-2, success=False, reason="no rights"),
            ]
        ),
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.redis",
        fake_redis,
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.get_global_mute_flag",
        AsyncMock(return_value=True),
    )

    result = await handle_reaction_mute(event=event, session=db_session)

    assert result.global_mute_state is True
    assert -1 in result.muted_groups
    assert -2 not in result.muted_groups


@pytest.mark.asyncio
async def test_anonymous_admin_handled(db_session, fake_redis, monkeypatch):
    chat_id = -500
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=True,
        )
    )
    await db_session.commit()

    event = build_event(chat_id=chat_id, emoji="👎")
    event.user = None  # simulate missing direct user
    event.actor_chat = SimpleNamespace(id=-999, title="Admins", type="supergroup")

    bot = AsyncMock()

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == event.message.from_user.id:
            return SimpleNamespace(status="member")
        return SimpleNamespace(status="administrator", can_restrict_members=True, is_anonymous=True, user=SimpleNamespace(id=777, username="anon"))

    bot.id = 888
    bot.get_chat_member.side_effect = fake_get_chat_member
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(is_anonymous=True, user=SimpleNamespace(id=777, username="anon"))]
    )
    bot.restrict_chat_member = AsyncMock()
    event.bot = bot

    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.log_reaction_mute",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.redis",
        fake_redis,
    )
    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.get_global_mute_flag",
        AsyncMock(return_value=False),
    )

    result = await handle_reaction_mute(event=event, session=db_session)

    assert result.success is True
    bot.restrict_chat_member.assert_awaited_once()

