import pytest

from bot.database.models import User
from bot.services import risk_gate


@pytest.mark.asyncio
async def test_risk_gate_uses_analyzer(db_session, monkeypatch):
    user = User(user_id=555, username="tester", first_name="Test", last_name="User")
    db_session.add(user)
    await db_session.commit()

    called = {}

    async def fake_analyze(snapshot, bot=None):
        called["snapshot"] = snapshot
        return {"is_suspicious": True, "risk_score": 90}

    monkeypatch.setattr(
        "bot.services.risk_gate.enhanced_profile_analyzer.analyze_user_profile_enhanced",
        fake_analyze,
    )

    result = await risk_gate.is_suspicious(user_id=555, chat_id=-100, session=db_session)

    assert result is True
    assert called["snapshot"]["username"] == "tester"


@pytest.mark.asyncio
async def test_risk_gate_handles_safe_result(db_session, monkeypatch):
    async def fake_analyze(snapshot, bot=None):
        return {"is_suspicious": False, "risk_score": 10}

    monkeypatch.setattr(
        "bot.services.risk_gate.enhanced_profile_analyzer.analyze_user_profile_enhanced",
        fake_analyze,
    )

    result = await risk_gate.is_suspicious(user_id=777, chat_id=-200, session=db_session)

    assert result is False
