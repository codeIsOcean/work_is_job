import types

import pytest

from aiogram.enums import ChatMemberStatus


@pytest.mark.asyncio
async def test_rejoin_after_leave_triggers_captcha_again(monkeypatch):
    """Повторное вступление (LEFT -> MEMBER) должно снова запускать капчу.

    Этот тест эмулирует баг, когда раньше второе вступление считалось дубликатом
    и join-captcha не запускалась. Теперь `handle_member_join` должен вызывать
    send_captcha_prompt для каждого реального события вступления.
    """
    # Импортируем после monkeypatch-конфигурации окружения
    from bot.handlers.visual_captcha.visual_captcha_handler import (
        handle_member_join,
    )

    # --- Подготовка фейковых зависимостей ---

    send_calls = []

    class FakeRedis:
        async def get(self, key):  # type: ignore[override]
            # В данном тесте флаг captcha_passed всегда отсутствует
            return None

    fake_redis = FakeRedis()

    async def fake_send_captcha_prompt(*, bot, chat, user, settings, source, initiator):  # type: ignore[override]
        send_calls.append((chat.id, user.id, source))

    class Decision:
        def __init__(self, require_captcha: bool = True, fallback_mode: bool = False):
            self.require_captcha = require_captcha
            self.fallback_mode = fallback_mode

    async def fake_prepare_manual_approval_flow(*, session, chat_id):  # type: ignore[override]
        # Для self-join всегда требуется капча
        return Decision(require_captcha=True, fallback_mode=False)

    class Settings:
        def __init__(self, timeout_seconds: int = 60):
            self.timeout_seconds = timeout_seconds

    async def fake_load_captcha_settings(session, chat_id):  # type: ignore[override]
        return Settings(timeout_seconds=60)

    class Admission:
        def __init__(self, muted: bool = False, reason: str | None = None):
            self.muted = muted
            self.reason = reason

    async def fake_evaluate_admission(*, bot, session, chat, user, source):  # type: ignore[override]
        return Admission(muted=False, reason=None)

    async def fake_clear_captcha_state(chat_id, user_id):  # type: ignore[override]
        return None

    async def fake_log_new_member(*, bot, user, chat, invited_by, session):  # type: ignore[override]
        return None

    class DummyUser:
        def __init__(self, user_id: int):
            self.id = user_id

    class DummyChat:
        def __init__(self, chat_id: int):
            self.id = chat_id

    class DummyChatMember:
        def __init__(self, status, user):
            self.status = status
            self.user = user

    class DummyBot:
        async def restrict_chat_member(self, *args, **kwargs):  # type: ignore[override]
            # В этом тесте ограничение несущественно
            return None

    class DummyEvent:
        def __init__(self, chat_id: int, user_id: int):
            self.chat = DummyChat(chat_id)
            self.bot = DummyBot()
            self.from_user = None
            user = DummyUser(user_id)
            self.old_chat_member = DummyChatMember(ChatMemberStatus.LEFT, user)
            self.new_chat_member = DummyChatMember(ChatMemberStatus.MEMBER, user)

    # Подменяем зависимости непосредственно в модуле обработчика
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.redis",
        fake_redis,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt",
        fake_send_captcha_prompt,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow",
        fake_prepare_manual_approval_flow,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings",
        fake_load_captcha_settings,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.evaluate_admission",
        fake_evaluate_admission,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.clear_captcha_state",
        fake_clear_captcha_state,
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.visual_captcha.visual_captcha_handler.log_new_member",
        fake_log_new_member,
        raising=False,
    )

    # --- Эмуляция двух последовательных вступлений одного и того же пользователя ---

    event = DummyEvent(chat_id=-1002302638465, user_id=6250902394)

    # Первое вступление
    await handle_member_join(event, session=types.SimpleNamespace())
    # Пользователь выходит и тут же заходит снова — для обработчика это ещё одно
    # событие LEFT -> MEMBER, которое должно обрабатываться как новое
    await handle_member_join(event, session=types.SimpleNamespace())

    # Раньше второе событие ошибочно считалось дубликатом и игнорировалось.
    # Теперь мы ожидаем ДВЕ отправки капчи.
    assert len(send_calls) == 2, send_calls
