import asyncio
from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock

from bot.database.models import User
from bot.services import broadcast_logic


@pytest.mark.asyncio
async def test_get_all_users_count(db_session):
    db_session.add_all(
        [
            User(user_id=1, username="one"),
            User(user_id=2, username="two"),
        ]
    )
    await db_session.commit()

    count = await broadcast_logic.get_all_users_count(db_session)
    assert count == 2


@pytest.mark.asyncio
async def test_get_users_for_broadcast(db_session):
    db_session.add_all(
        [
            User(user_id=10, username="user10", first_name="Ten"),
            User(user_id=11, username="user11", first_name="Eleven"),
        ]
    )
    await db_session.commit()

    users = await broadcast_logic.get_users_for_broadcast(db_session, limit=1)

    assert len(users) == 1
    assert users[0]["user_id"] in {10, 11}


@pytest.mark.asyncio
async def test_send_broadcast_message_success(bot_mock):
    result = await broadcast_logic.send_broadcast_message(bot_mock, 42, "Hello", username="tester")

    assert result["success"] is True
    bot_mock.send_message.assert_awaited_once_with(chat_id=42, text="Hello")


@pytest.mark.asyncio
async def test_send_broadcast_message_handles_exception(bot_mock):
    bot_mock.send_message.side_effect = RuntimeError("fail")

    result = await broadcast_logic.send_broadcast_message(bot_mock, 13, "Oops")

    assert result["success"] is False
    assert "fail" in result["error"]


@pytest.mark.asyncio
async def test_broadcast_to_all_users(bot_mock, db_session, monkeypatch):
    db_session.add_all(
        [
            User(user_id=100, username="user100"),
            User(user_id=101, username="user101"),
        ]
    )
    await db_session.commit()

    @asynccontextmanager
    async def session_provider():
        yield db_session

    monkeypatch.setattr(broadcast_logic, "get_session", session_provider)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await broadcast_logic.broadcast_to_all_users(bot_mock, "Broadcast", max_users=5)

    assert result["success"] is True
    assert result["total_users"] == 2
    assert result["success_count"] == 2

