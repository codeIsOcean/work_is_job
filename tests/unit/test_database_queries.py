import pytest

from bot.database.models import Group, User
from bot.database import queries


@pytest.mark.asyncio
async def test_get_or_create_user_creates(db_session):
    user = await queries.get_or_create_user(db_session, 5000, "Test User", "tester")
    assert user.user_id == 5000

    stored = await db_session.get(User, user.id)
    assert stored.username == "tester"


@pytest.mark.asyncio
async def test_get_or_create_user_returns_existing(db_session):
    existing = User(user_id=6000, full_name="Existing", username="exist")
    db_session.add(existing)
    await db_session.commit()

    user = await queries.get_or_create_user(db_session, 6000, "New Name", "new_username")
    assert user.id == existing.id


@pytest.mark.asyncio
async def test_save_group_creates_once(db_session):
    group = await queries.save_group(db_session, -9000, "Saved group")
    assert group.chat_id == -9000

    again = await queries.save_group(db_session, -9000, "Saved group")
    assert again.id == group.id

