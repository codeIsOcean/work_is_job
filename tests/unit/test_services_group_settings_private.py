import pytest

from bot.database.models import (
    CaptchaSettings,
    ChatSettings,
    Group,
    User,
    UserGroup,
)
from bot.services import groups_settings_in_private_logic as group_settings_logic


@pytest.mark.asyncio
async def test_get_admin_groups_without_bot(db_session):
    user = User(user_id=123, first_name="Admin")
    group = Group(chat_id=-3001, title="Team chat")
    link = UserGroup(user_id=user.user_id, group_id=group.chat_id)

    db_session.add_all([user, group, link])
    await db_session.commit()

    groups = await group_settings_logic.get_admin_groups(user.user_id, db_session)

    assert len(groups) == 1
    assert groups[0].chat_id == group.chat_id


@pytest.mark.asyncio
async def test_check_admin_rights(db_session):
    user = User(user_id=124, first_name="Admin2")
    group = Group(chat_id=-3002, title="Another chat")
    link = UserGroup(user_id=user.user_id, group_id=group.chat_id)

    db_session.add_all([user, group, link])
    await db_session.commit()

    assert await group_settings_logic.check_admin_rights(db_session, user.user_id, group.chat_id) is True
    assert await group_settings_logic.check_admin_rights(db_session, user.user_id, -999) is False


@pytest.mark.asyncio
async def test_get_mute_new_members_status_uses_db_and_caches(fake_redis, db_session):
    group = Group(chat_id=-3003, title="Mute group")
    settings = ChatSettings(chat_id=group.chat_id, mute_new_members=True)
    db_session.add_all([group, settings])
    await db_session.commit()

    result = await group_settings_logic.get_mute_new_members_status(db_session, group.chat_id)
    assert result is True
    assert await fake_redis.get(f"group:{group.chat_id}:mute_new_members") == "1"


@pytest.mark.asyncio
async def test_toggle_visual_captcha_creates_and_flips(fake_redis, db_session):
    group = Group(chat_id=-3004, title="Captcha group")
    db_session.add(group)
    await db_session.commit()

    enabled = await group_settings_logic.toggle_visual_captcha(db_session, group.chat_id)
    assert enabled is True

    second_state = await group_settings_logic.toggle_visual_captcha(db_session, group.chat_id)
    assert second_state is False

    record = await db_session.get(CaptchaSettings, group.chat_id)
    assert record.is_visual_enabled is False


@pytest.mark.asyncio
async def test_get_global_mute_status(fake_redis, db_session):
    global_group = Group(chat_id=0, title="Global")
    db_session.add(global_group)
    await db_session.commit()

    settings = ChatSettings(chat_id=0, global_mute_enabled=True)
    await db_session.merge(settings)
    await db_session.commit()

    result = await group_settings_logic.get_global_mute_status(db_session)
    assert result is True
    assert await fake_redis.get("global_mute_enabled") == "1"

