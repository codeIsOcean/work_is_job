from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import User
from aiogram.methods import TelegramMethod

from bot.middleware.db_session import DbSessionMiddleware
from bot.database import session as db_session_module
from tests.e2e.utils import build_fresh_router


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__(api=TelegramAPIServer.from_base("https://api.test"))
        self.requests: List[Tuple[str, Dict[str, Any]]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: Optional[int] = None,
    ) -> Any:
        method_name = method.__api_method__
        payload: Dict[str, Any] = {}
        if method_name == "sendMessage":
            payload = {"chat_id": method.chat_id, "text": method.text}
        self.requests.append((method_name, payload))
        if method_name == "sendMessage":
            return {
                "message_id": 1000,
                "date": datetime.now(timezone.utc),
                "chat": {"id": payload["chat_id"], "type": "private"},
                "text": payload["text"],
                "from": {
                    "id": bot.id or 9999,
                    "is_bot": True,
                    "first_name": "TestBot",
                },
            }
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


async def _setup_dispatcher(redis_client):
    storage = RedisStorage(redis_client)
    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    dp.include_router(build_fresh_router())
    return dp, storage


@pytest.mark.asyncio
async def test_full_command_chain(
    redis_client_e2e,
    message_factory,
    update_factory,
    monkeypatch,
):
    monkeypatch.setattr("bot.services.redis_conn.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.auto_mute_scammers_logic.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.groups_settings_in_private_logic.redis", redis_client_e2e, raising=False)

    dp, storage = await _setup_dispatcher(redis_client_e2e)

    session = RecordingSession()
    bot = Bot(token="000000:TEST", session=session)
    bot._me = User(id=1010, is_bot=True, first_name="TestBot", username="test_bot")

    async def feed(text: str, user_id: int = 1234, chat_id: int = 1234):
        message = message_factory(text=text, user_id=user_id, chat_type="private", chat_id=chat_id)
        update = update_factory(message=message)
        await dp.feed_update(bot, update)

    await feed("/start")
    await feed("/help")
    await feed("/settings")

    texts = [payload["text"] for method, payload in session.requests if method == "sendMessage"]

    assert any("/settings" in t for t in texts)
    assert any("Доступные команды" in t for t in texts)

    await storage.close()
    await bot.session.close()

