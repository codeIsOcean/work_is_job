import pytest

from bot.database.models import (
    Base,
    User,
    Group,
    UserGroup,
    GroupJournalChannel,
    ChatSettings,
)


@pytest.mark.asyncio
async def test_user_group_relationship(db_session):
    user = User(user_id=1000, first_name="Tester")
    group = Group(chat_id=-7000, title="Test Group", creator_user_id=None)
    db_session.add_all([user, group])
    await db_session.commit()

    link = UserGroup(user_id=user.user_id, group_id=group.chat_id)
    db_session.add(link)
    await db_session.commit()

    result = await db_session.get(UserGroup, link.id)
    assert result.user_id == user.user_id
    assert result.group_id == group.chat_id


@pytest.mark.asyncio
async def test_group_journal_channel_crud(db_session):
    group = Group(chat_id=-7100, title="Journalled")
    db_session.add(group)
    await db_session.commit()

    journal = GroupJournalChannel(
        group_id=group.chat_id,
        journal_channel_id=-12345,
        journal_type="channel",
        journal_title="Logs",
        linked_by_user_id=1,
    )
    db_session.add(journal)
    await db_session.commit()

    fetched = await db_session.get(GroupJournalChannel, journal.id)
    assert fetched.journal_channel_id == -12345
    assert fetched.group_id == group.chat_id


@pytest.mark.asyncio
async def test_chat_settings_defaults(db_session):
    group = Group(chat_id=-7200, title="Settings group")
    db_session.add(group)
    await db_session.commit()

    settings = ChatSettings(chat_id=group.chat_id)
    db_session.add(settings)
    await db_session.commit()

    stored = await db_session.get(ChatSettings, group.chat_id)
    assert stored.auto_mute_scammers is True
    assert stored.global_mute_enabled is False

