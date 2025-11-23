import asyncio
from types import SimpleNamespace

import pytest

from bot.utils import logger as logger_module


@pytest.mark.asyncio
async def test_send_formatted_log(monkeypatch):
    captured_payload = {}

    class DummyResponse:
        status = 200

        async def text(self):
            return ""

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def post(self, url, data):
            captured_payload["url"] = url
            captured_payload["data"] = data
            return DummyResponse()

    monkeypatch.setenv("BOT_TOKEN", "TEST_TOKEN")
    monkeypatch.setenv("LOG_CHANNEL_ID", "123")
    monkeypatch.setattr(logger_module, "BOT_TOKEN", "TEST_TOKEN", raising=False)
    monkeypatch.setattr(logger_module, "LOG_CHANNEL_ID", "123", raising=False)
    monkeypatch.setattr(logger_module, "aiohttp", SimpleNamespace(ClientSession=lambda: DummySession()))

    await logger_module.send_formatted_log("message")

    assert captured_payload["url"].endswith("/botTEST_TOKEN/sendMessage")
    assert captured_payload["data"]["text"] == "message"


@pytest.mark.asyncio
async def test_log_new_user_creates_task(monkeypatch):
    tasks = []

    async def dummy_send(message):
        tasks.append(message)

    monkeypatch.setenv("BOT_TOKEN", "TEST_TOKEN")
    monkeypatch.setenv("LOG_CHANNEL_ID", "123")
    monkeypatch.setattr(logger_module, "BOT_TOKEN", "TEST_TOKEN", raising=False)
    monkeypatch.setattr(logger_module, "LOG_CHANNEL_ID", "123", raising=False)
    monkeypatch.setattr(logger_module, "send_formatted_log", dummy_send)

    logger_module.log_new_user("user", 1, "group", -100)
    await asyncio.sleep(0)

    assert tasks

