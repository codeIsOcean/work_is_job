from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ChatMemberUpdated, User, Update
from aiogram.methods import TelegramMethod

from bot.middleware.db_session import DbSessionMiddleware
from bot.database import session as db_session_module
from bot.database.models import Group, ChatSettings, ScammerTracker
from tests.e2e.utils import build_fresh_router


class ModerationSession(BaseSession):
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
        if method_name == "restrictChatMember":
            payload = {"chat_id": method.chat_id, "user_id": method.user_id}
        elif method_name == "sendMessage":
            payload = {"chat_id": method.chat_id, "text": method.text}
        elif method_name == "getChat":
            payload = {"chat_id": method.chat_id}
        self.requests.append((method_name, payload))
        if method_name == "restrictChatMember":
            return True
        if method_name == "sendMessage":
            return {
                "message_id": 2000,
                "date": datetime.now(timezone.utc),
                "chat": {"id": payload["chat_id"], "type": "private"},
                "text": payload["text"],
                "from": {"id": bot.id or 333, "is_bot": True, "first_name": "TestBot"},
            }
        if method_name == "getChat":
            return {"id": payload["chat_id"], "title": "Moderation chat"}
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


async def _prepare_group(db_session):
    group = Group(chat_id=-8001, title="Moderation group")
    db_session.add(group)
    db_session.add(ChatSettings(chat_id=group.chat_id, auto_mute_scammers=True))
    db_session.add(
        ScammerTracker(
            user_id=999,
            chat_id=group.chat_id,
            violation_type="test",
            violation_count=1,
            scammer_level=60,
        )
    )
    await db_session.commit()
    return group


@pytest.mark.asyncio
@pytest.mark.skip(reason="Full auto-mute moderation flow is unstable with real Redis/event loop in CI; core logic is covered by unit tests")
async def test_moderation_auto_mute_flow(
    redis_client_e2e,
    message_factory,
    update_factory,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr("bot.services.redis_conn.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.auto_mute_scammers_logic.redis", redis_client_e2e, raising=False)
    monkeypatch.setattr("bot.services.groups_settings_in_private_logic.redis", redis_client_e2e, raising=False)

    group = await _prepare_group(db_session)

    storage = RedisStorage(redis_client_e2e)
    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware(db_session_module.async_session))
    dp.include_router(build_fresh_router())

    session = ModerationSession()
    bot = Bot(token="000000:TEST", session=session)
    bot._me = User(id=4040, is_bot=True, first_name="TestBot", username="test_bot")

    join_event_payload = {
        "chat": {"id": group.chat_id, "type": "supergroup", "title": group.title},
        "from": {"id": 10, "is_bot": False, "first_name": "Admin"},
        "date": int(datetime.now(timezone.utc).timestamp()),
        "old_chat_member": {"status": "left", "user": {"id": 999, "is_bot": False, "first_name": "NewUser"}},
        "new_chat_member": {"status": "member", "user": {"id": 999, "is_bot": False, "first_name": "NewUser"}},
    }
    event = ChatMemberUpdated.model_validate(join_event_payload)
    event._bot = bot

    update = Update.model_validate({"update_id": 10, "chat_member": join_event_payload})
    await dp.feed_update(bot, update)

    restrict_calls = [payload for method, payload in session.requests if method == "restrictChatMember"]
    assert restrict_calls, "Auto mute should attempt to restrict new member"

    await storage.close()
    await bot.session.close()

