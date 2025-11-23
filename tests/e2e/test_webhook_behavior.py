from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Update, User
from aiogram.methods import TelegramMethod

from bot.middleware.db_session import DbSessionMiddleware
from bot.database import session as db_session_module
from tests.e2e.utils import build_fresh_router


class WebhookSession(BaseSession):
    def __init__(self) -> None:
        super().__init__(api=TelegramAPIServer.from_base("https://api.test"))
        self.calls: list[tuple[str, Dict[str, Any]]] = []

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
        self.calls.append((method_name, payload))
        if method_name == "sendMessage":
            return {
                "message_id": 5000,
                "date": datetime.now(timezone.utc),
                "chat": {"id": payload["chat_id"], "type": "private"},
                "text": payload["text"],
                "from": {"id": bot.id or 5050, "is_bot": True, "first_name": "TestBot"},
            }
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


async def _setup_app(dp: Dispatcher, bot: Bot):
    app = web.Application()

    async def handle(request: web.Request):
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return web.Response(text="OK")

    app.router.add_post("/webhook", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8081)
    await site.start()
    return runner, site


@pytest.mark.asyncio
async def test_webhook_flow(redis_client_e2e, message_factory, monkeypatch):
    monkeypatch.setattr("bot.services.redis_conn.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", redis_client_e2e, raising=False)

    storage = RedisStorage(redis_client_e2e)
    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    dp.include_router(build_fresh_router())

    session = WebhookSession()
    bot = Bot(token="000000:TEST", session=session)
    bot._me = User(id=9090, is_bot=True, first_name="TestBot", username="test_bot")

    runner, site = await _setup_app(dp, bot)

    message = message_factory(text="/start", user_id=5656, chat_type="private", chat_id=5656)
    update_payload = {"update_id": 123456, "message": message.model_dump()}

    async with aiohttp.ClientSession() as client:
        resp = await client.post("http://127.0.0.1:8081/webhook", json=update_payload)
        assert resp.status == 200

    send_calls = [payload for method, payload in session.calls if method == "sendMessage"]
    assert send_calls, "Webhook should trigger bot response"

    await storage.close()
    await bot.session.close()
    await runner.cleanup()

