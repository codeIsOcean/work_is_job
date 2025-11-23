from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.visual_captcha.visual_captcha_handler import (
    drop_scam_command,
    start_command,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from bot.database import session as db_session_module
from bot.middleware.db_session import DbSessionMiddleware
from aiogram import Dispatcher


def _make_message(user_id: int, text: str = "/start"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="user"),
        text=text,
        bot=AsyncMock(),
        answer=AsyncMock(),
        chat=SimpleNamespace(id=999),
    )


@pytest.mark.asyncio
async def test_start_command_for_developer(db_session):
    storage = MemoryStorage()
    message = _make_message(619924982, "/start")
    fsm_context = FSMContext(storage=storage, key=StorageKey(chat_id=message.chat.id, user_id=message.from_user.id, bot_id=0))

    await start_command(message, fsm_context, db_session)

    message.answer.assert_awaited_once()
    sent_text = message.answer.await_args.kwargs.get("text") or message.answer.await_args.args[0]
    assert "Привет, разработчик" in sent_text


@pytest.mark.asyncio
async def test_start_command_for_user(db_session):
    storage = MemoryStorage()
    message = _make_message(42, "/start")
    fsm_context = FSMContext(storage=storage, key=StorageKey(chat_id=message.chat.id, user_id=message.from_user.id, bot_id=0))

    await start_command(message, fsm_context, db_session)

    message.answer.assert_awaited_once()
    sent_text = message.answer.await_args.kwargs.get("text") or message.answer.await_args.args[0]
    assert "Добро пожаловать" in sent_text


@pytest.mark.asyncio
async def test_drop_scam_command_requires_developer(db_session):
    message = _make_message(123, "/drop scam 999")

    await drop_scam_command(message, db_session)

    message.answer.assert_awaited()
    texts = [
        (call.kwargs.get("text") or call.args[0]).lower()
        for call in message.answer.await_args_list
    ]
    assert any("нет прав" in text for text in texts)

