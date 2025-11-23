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


class DummyAPISession(BaseSession):
    """Minimal session stub that records bot API requests."""

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
                "message_id": 999,
                "date": datetime.now(timezone.utc),
                "chat": {"id": payload["chat_id"], "type": "private"},
                "text": payload["text"],
                "from": {
                    "id": bot.id or 100500,
                    "is_bot": True,
                    "first_name": "TestBot",
                },
            }

        # Default response for methods that return boolean value
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Streaming responses are not supported in tests.")

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Streaming content is not supported in tests.")


@pytest.mark.asyncio
async def test_start_command_flow(
    redis_client_e2e,
    message_factory,
    update_factory,
    monkeypatch,
):
    monkeypatch.setattr("bot.services.redis_conn.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", redis_client_e2e, raising=False)

    storage = RedisStorage(redis_client_e2e)

    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    dp.include_router(build_fresh_router())

    session = DummyAPISession()
    bot = Bot(token="000000:TEST", session=session)
    bot._me = User(id=424242, is_bot=True, first_name="TestBot", username="test_bot")

    message = message_factory(text="/start", user_id=1234, chat_type="private", chat_id=1234)
    update = update_factory(message=message)

    await dp.feed_update(bot, update)

    send_calls = [data for method, data in session.requests if method == "sendMessage"]
    assert send_calls, "Bot should send a reply to /start"
    assert "Добро пожаловать" in send_calls[0]["text"]

    await storage.close()
    await bot.session.close()

