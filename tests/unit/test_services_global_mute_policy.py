import pytest

from bot.services import global_mute_policy


@pytest.mark.asyncio
async def test_should_apply_manual_mute_when_global_off(db_session, monkeypatch):
    async def fake_risk_gate(**kwargs):
        return True

    monkeypatch.setattr(
        "bot.services.global_mute_policy.risk_gate_is_suspicious",
        fake_risk_gate,
    )

    decision = await global_mute_policy.should_apply_manual_mute(
        global_flag=False,
        user_id=123,
        chat_id=-100,
        session=db_session,
    )

    assert decision is False


@pytest.mark.asyncio
async def test_should_apply_manual_mute_when_suspicious(db_session, monkeypatch):
    async def fake_risk_gate(**kwargs):
        return True

    monkeypatch.setattr(
        "bot.services.global_mute_policy.risk_gate_is_suspicious",
        fake_risk_gate,
    )

    decision = await global_mute_policy.should_apply_manual_mute(
        global_flag=True,
        user_id=123,
        chat_id=-100,
        session=db_session,
    )

    assert decision is True


@pytest.mark.asyncio
async def test_should_apply_manual_mute_when_safe(db_session, monkeypatch):
    async def fake_risk_gate(**kwargs):
        return False

    monkeypatch.setattr(
        "bot.services.global_mute_policy.risk_gate_is_suspicious",
        fake_risk_gate,
    )

    decision = await global_mute_policy.should_apply_manual_mute(
        global_flag=True,
        user_id=123,
        chat_id=-100,
        session=db_session,
    )

    assert decision is False
