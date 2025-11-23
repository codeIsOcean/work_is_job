from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.group_settings_handler.groups_settings_in_private_handler import (
    manage_group_callback,
    settings_command,
)


def _make_message(user_id: int, text: str = "/settings"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="user"),
        text=text,
        bot=AsyncMock(),
        answer=AsyncMock(),
    )


def _make_callback(data: str, user_id: int):
    message = SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="user"),
        bot=AsyncMock(),
        message=message,
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_settings_command_denied(db_session):
    message = _make_message(123456, text="/settings")

    await settings_command(message, db_session)

    message.answer.assert_awaited_once()
    sent_text = message.answer.await_args.kwargs.get("text") or message.answer.await_args.args[0]
    assert "Доступ запрещен" in sent_text


@pytest.mark.asyncio
async def test_manage_group_callback_requires_admin(monkeypatch, db_session):
    callback = _make_callback("manage_group_-100", user_id=619924982)
    monkeypatch.setattr(
        "bot.handlers.group_settings_handler.groups_settings_in_private_handler.check_admin_rights",
        AsyncMock(return_value=False),
    )

    await manage_group_callback(callback, db_session)

    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs.get("show_alert") is True

