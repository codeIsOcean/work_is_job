from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from sqlalchemy import select
from aiogram.types import MessageReactionUpdated
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from bot.database.models import ChatSettings, Group
from bot.middleware.db_session import DbSessionMiddleware
from bot.database import session as db_session_module
from bot.services.mute_by_reaction_service.logic import ReactionMuteResult


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__(api=TelegramAPIServer.from_base("https://api.test"))
        self.requests = []

    async def make_request(self, bot: Bot, method, timeout=None):
        method_name = getattr(method, "__api_method__", "")
        self.requests.append(method_name)
        if method_name == "sendMessage":
            return {"ok": True}
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args, **kwargs):
        return None

    async def stream_content(self, *args, **kwargs):
        return None


def build_update_payload(chat_id: int, admin_id: int, target_id: int, emoji: str):
    timestamp = int(datetime.now(timezone.utc).timestamp())
    return {
        "update_id": 1,
        "message_reaction": {
            "chat": {"id": chat_id, "type": "supergroup"},
            "message_id": 42,
            "user": {
                "id": admin_id,
                "is_bot": False,
                "first_name": "Admin",
                "username": "admin",
            },
            "date": timestamp,
            "old_reactions": [],
            "new_reactions": [{"type": "emoji", "emoji": emoji}],
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": emoji}],
            "message": {
                "message_id": 42,
                "date": timestamp,
                "chat": {"id": chat_id, "type": "supergroup"},
                "from": {
                    "id": target_id,
                    "is_bot": False,
                    "first_name": "Target",
                    "username": "target",
                },
                "text": "hello",
            },
        },
    }


@pytest.mark.asyncio
async def test_admin_reaction_triggers_mute(
    db_session,
    monkeypatch,
):
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

    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    test_router = Router()

    @test_router.message_reaction()
    async def test_handler(event: MessageReactionUpdated):
        await handle_mock(event=event, session=db_session)

    dispatcher.include_router(test_router)

    session = RecordingSession()
    bot = Bot(token="65000:TEST", session=session)

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == 111:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        return SimpleNamespace(status="member")

    bot.get_chat_member = AsyncMock(side_effect=fake_get_chat_member)
    bot.restrict_chat_member = AsyncMock()
    bot.send_message = AsyncMock()

    handle_mock = AsyncMock(
        return_value=ReactionMuteResult(success=True, should_announce=False, system_message=None)
    )

    monkeypatch.setattr("bot.handlers.mute_by_reaction.mute_by_reaction_handler.handle_reaction_mute", handle_mock)
    monkeypatch.setattr("bot.services.mute_by_reaction_service.logic.handle_reaction_mute", handle_mock)

    update_payload = build_update_payload(chat_id=chat_id, admin_id=111, target_id=999, emoji="🤢")
    update = Update.model_validate(update_payload)
    await dispatcher.feed_update(bot, update)

    assert handle_mock.await_count == 1


@pytest.mark.asyncio
async def test_anonymous_admin_reaction(db_session, monkeypatch):
    chat_id = -600
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=False,
        )
    )
    await db_session.commit()

    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    test_router = Router()

    @test_router.message_reaction()
    async def test_handler(event: MessageReactionUpdated):
        await handle_mock(event=event, session=db_session)

    dispatcher.include_router(test_router)

    session = RecordingSession()
    bot = Bot(token="65000:TEST", session=session)

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        return SimpleNamespace(status="administrator", can_restrict_members=True, is_anonymous=True, user=SimpleNamespace(id=777, username="anon"))

    monkeypatch.setattr(bot, "_me", SimpleNamespace(id=123))
    bot.get_chat_member = AsyncMock(side_effect=fake_get_chat_member)
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(is_anonymous=True, user=SimpleNamespace(id=777, username="anon"))]
    )
    bot.restrict_chat_member = AsyncMock()

    result_mock = ReactionMuteResult(success=True, should_announce=False, system_message=None, global_mute_state=False)
    handle_mock = AsyncMock(return_value=result_mock)

    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.handle_reaction_mute",
        handle_mock,
    )

    payload = build_update_payload(chat_id=chat_id, admin_id=777, target_id=999, emoji="👎")
    update = Update.model_validate(payload)
    await dispatcher.feed_update(bot, update)

    assert handle_mock.await_count == 1


@pytest.mark.asyncio
async def test_mute_forever_logs_multi_groups(db_session, monkeypatch):
    chat_id = -700
    db_session.add(Group(chat_id=chat_id, title="Test"))
    db_session.add(
        ChatSettings(
            chat_id=chat_id,
            reaction_mute_enabled=True,
            reaction_mute_announce_enabled=False,
        )
    )
    await db_session.commit()

    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    test_router = Router()

    @test_router.message_reaction()
    async def test_handler(event: MessageReactionUpdated):
        await handle_mock(event=event, session=db_session)

    dispatcher.include_router(test_router)

    session = RecordingSession()
    bot = Bot(token="65000:TEST", session=session)

    async def fake_get_chat_member(chat_id: int, user_id: int):
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        return SimpleNamespace(status="administrator", can_restrict_members=True)

    monkeypatch.setattr(bot, "_me", SimpleNamespace(id=321))
    bot.get_chat_member = AsyncMock(side_effect=fake_get_chat_member)
    bot.restrict_chat_member = AsyncMock()
    bot.send_message = AsyncMock()

    multi_result = [SimpleNamespace(chat_id=-1, success=True), SimpleNamespace(chat_id=-2, success=False)]
    handle_mock = AsyncMock(
        return_value=ReactionMuteResult(
            success=True,
            should_announce=False,
            system_message=None,
            global_mute_state=True,
            muted_groups=[res.chat_id for res in multi_result if res.success],
        )
    )

    monkeypatch.setattr(
        "bot.services.mute_by_reaction_service.logic.handle_reaction_mute",
        handle_mock,
    )

    payload = build_update_payload(chat_id=chat_id, admin_id=111, target_id=999, emoji="💩")
    update = Update.model_validate(payload)
    await dispatcher.feed_update(bot, update)

    assert handle_mock.await_count == 1