from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.auto_mute_scammers_handlers import handle_auto_mute_settings


def _make_callback(data: str, user_id: int = 64):
    message = SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        bot=AsyncMock(),
        message=message,
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_auto_mute_settings_permission_denied(monkeypatch, db_session):
    callback = _make_callback("auto_mute_settings:disable:-500")

    monkeypatch.setattr(
        "bot.handlers.auto_mute_scammers_handlers.check_granular_permissions",
        AsyncMock(return_value=False),
    )

    await handle_auto_mute_settings(callback, db_session)

    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs.get("show_alert") is True

