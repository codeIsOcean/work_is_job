import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.settings_captcha_handler import (
    open_captcha_settings,
    toggle_captcha_setting,
    request_value_input,
    process_value_input,
    CaptchaSettingsStates,
    _refresh_view,
)
from bot.database.models import Group
from fakeredis.aioredis import FakeRedis


class DummySettings:
    def __init__(self):
        self.captcha_join_enabled = False
        self.captcha_invite_enabled = False
        self.captcha_timeout_seconds = 300
        self.captcha_message_ttl_seconds = 600
        self.captcha_flood_threshold = 5
        self.captcha_flood_window_seconds = 180
        self.captcha_flood_action = "warn"
        self.system_mute_announcements_enabled = True


async def _allow_permissions(*args, **kwargs):
    return True


@pytest.mark.asyncio
async def test_refresh_view_renders(monkeypatch, db_session):
    chat_id = -100
    db_session.add(Group(chat_id=chat_id, title="Test"))
    await db_session.commit()

    callback = SimpleNamespace(
        message=SimpleNamespace(
            chat=SimpleNamespace(id=999),
            edit_text=AsyncMock(),
        )
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_group_by_chat_id",
        AsyncMock(return_value=SimpleNamespace(title="Group", chat_id=chat_id, username=None, id=chat_id)),
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_captcha_settings",
        AsyncMock(return_value=DummySettings()),
    )
    fake_redis = FakeRedis()
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", fake_redis)
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_visual_captcha_status",
        AsyncMock(return_value=False),
    )
    await _refresh_view(callback, db_session, chat_id)

    callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_toggle_join_setting(monkeypatch, db_session):
    chat_id = -100
    db_session.add(Group(chat_id=chat_id, title="Test"))
    await db_session.commit()

    callback = SimpleNamespace(
        data=f"captcha_toggle:join:{chat_id}",
        from_user=SimpleNamespace(id=619924982, username="admin", first_name="Admin", last_name="Test"),
        message=SimpleNamespace(chat=SimpleNamespace(id=999, username=None), edit_text=AsyncMock()),
        bot=AsyncMock(),
        answer=AsyncMock(),
    )
    callback.bot.get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id, title="Group", username=None))
    callback.bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="administrator", can_change_info=True))

    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.check_granular_permissions",
        _allow_permissions,
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_captcha_settings",
        AsyncMock(return_value=DummySettings()),
    )
    set_join_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.set_captcha_join_enabled",
        set_join_mock,
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.log_captcha_setting_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.services.bot_activity_journal.bot_activity_journal_logic.log_captcha_setting_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.bot_activity_journal.bot_activity_journal.send_activity_log",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler._refresh_view",
        AsyncMock(),
    )
    fake_redis = FakeRedis()
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", fake_redis)

    await toggle_captcha_setting(callback, db_session)

    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_process_timeout_input(monkeypatch, db_session):
    chat_id = -100
    db_session.add(Group(chat_id=chat_id, title="Test"))
    await db_session.commit()

    storage = MemoryStorage()
    fsm_context = FSMContext(storage=storage, key=StorageKey(chat_id=999, user_id=1, bot_id=0))
    await fsm_context.set_state(CaptchaSettingsStates.waiting_for_value)
    await fsm_context.set_data({"chat_id": chat_id, "parameter": "timeout", "message_id": 555})

    message = SimpleNamespace(
        text="5m",
        chat=SimpleNamespace(id=999),
        from_user=SimpleNamespace(id=1, username="admin", first_name="Admin"),
        bot=AsyncMock(),
        reply=AsyncMock(),
    )
    message.bot.get_chat = AsyncMock(return_value=SimpleNamespace(id=-100, title="Group", username=None))
    message.bot.edit_message_text = AsyncMock()

    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.set_captcha_timeout",
        AsyncMock(return_value=300),
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.log_captcha_setting_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_group_by_chat_id",
        AsyncMock(return_value=SimpleNamespace(title="Group", chat_id=chat_id, username=None, id=chat_id)),
    )
    dummy_settings = DummySettings()
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_captcha_settings",
        AsyncMock(return_value=dummy_settings),
    )
    monkeypatch.setattr(
        "bot.handlers.settings_captcha_handler.get_visual_captcha_status",
        AsyncMock(return_value=False),
    )
    fake_redis = FakeRedis()
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", fake_redis)

    await process_value_input(message, fsm_context, db_session)

    message.bot.edit_message_text.assert_awaited_once()
