import pytest

from bot.services import global_mute_policy


@pytest.mark.asyncio
async def test_should_apply_manual_mute_when_global_off(db_session, monkeypatch):
    """Когда глобальный мут выключен - НЕ мутим (даже если risk_gate = True)"""
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
async def test_should_apply_manual_mute_when_global_on(db_session, monkeypatch):
    """Когда глобальный мут включен - МУТИМ всех при ручном одобрении

    ВАЖНО: Глобальный мут = ТОЛЬКО для ручного одобрения заявок!
    - global_flag=True + ручное одобрение → МУТИМ (всех, без проверки risk_gate)
    - global_flag=False + ручное одобрение → НЕ мутим
    - Капча пройдена → НЕ мутим (проверяется в другом месте)

    risk_gate - это отдельная функция автомута скаммеров, работает независимо.
    """
    # risk_gate не влияет на глобальный мут - мутим всех
    decision = await global_mute_policy.should_apply_manual_mute(
        global_flag=True,
        user_id=123,
        chat_id=-100,
        session=db_session,
    )

    assert decision is True
