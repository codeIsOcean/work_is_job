from unittest.mock import AsyncMock

import pytest

from bot.middleware import access_control
from bot.middleware.access_control import AccessControlMiddleware


@pytest.mark.asyncio
async def test_access_control_allows(monkeypatch, message_factory):
    middleware = AccessControlMiddleware()

    message = message_factory(user_id=1234, chat_id=1234, chat_type="private")
    message = message.model_copy()

    allowed_ids = {1234}
    monkeypatch.setattr(access_control, "ALLOWED_USER_IDS", allowed_ids, raising=False)
    monkeypatch.setattr(access_control, "ALLOWED_USERNAMES", set(), raising=False)
    monkeypatch.setattr(access_control, "ACCESS_CONTROL_ENABLED", True, raising=False)

    called = False

    async def handler(event, data):
        nonlocal called
        called = True

    await middleware(handler, message, {})

    assert called is True


@pytest.mark.asyncio
async def test_access_control_denies(monkeypatch, message_factory):
    middleware = AccessControlMiddleware()

    message = message_factory(user_id=9999, chat_id=9999, chat_type="private")
    message = message.model_copy()

    answer_mock = AsyncMock()
    object.__setattr__(message, "answer", answer_mock)

    monkeypatch.setattr(access_control, "ALLOWED_USER_IDS", set(), raising=False)
    monkeypatch.setattr(access_control, "ALLOWED_USERNAMES", set(), raising=False)
    monkeypatch.setattr(access_control, "ACCESS_CONTROL_ENABLED", True, raising=False)

    async def handler(event, data):
        pytest.fail("Handler should not be called")

    await middleware(handler, message, {})

    answer_mock.assert_awaited_once()

