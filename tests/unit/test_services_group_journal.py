from datetime import datetime

import pytest

from bot.database.models import Group, GroupJournalChannel
from bot.services import group_journal_service as journal_service


@pytest.mark.asyncio
async def test_link_and_get_journal_channel(db_session):
    group = Group(chat_id=-2001, title="Journal group")
    db_session.add(group)
    await db_session.commit()

    linked = await journal_service.link_journal_channel(
        session=db_session,
        group_id=group.chat_id,
        journal_channel_id=-4001,
        journal_title="Log channel",
        linked_by_user_id=42,
    )
    assert linked is True

    record = await journal_service.get_group_journal_channel(db_session, group.chat_id)
    assert record is not None
    assert record.journal_channel_id == -4001
    assert record.journal_title == "Log channel"


@pytest.mark.asyncio
async def test_link_journal_channel_updates_existing(db_session):
    group = Group(chat_id=-2002, title="Journal group 2")
    db_session.add(group)
    await db_session.commit()

    await journal_service.link_journal_channel(db_session, group.chat_id, -5001)

    updated = await journal_service.link_journal_channel(
        db_session,
        group.chat_id,
        journal_channel_id=-5002,
        journal_title="Updated channel",
    )
    assert updated is True

    record = await journal_service.get_group_journal_channel(db_session, group.chat_id)
    assert record.journal_channel_id == -5002
    assert record.journal_title == "Updated channel"


@pytest.mark.asyncio
async def test_send_journal_event_without_link(bot_mock, db_session):
    result = await journal_service.send_journal_event(
        bot=bot_mock,
        session=db_session,
        group_id=-999,
        message_text="Test",
    )
    assert result is False
    bot_mock.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_journal_event_success(bot_mock, db_session):
    group = Group(chat_id=-2003, title="Journal group 3")
    db_session.add(group)
    await db_session.commit()

    await journal_service.link_journal_channel(db_session, group.chat_id, -6001, journal_title="Channel")

    bot_mock.send_message.reset_mock()

    result = await journal_service.send_journal_event(
        bot=bot_mock,
        session=db_session,
        group_id=group.chat_id,
        message_text="Event happened",
    )

    assert result is True
    bot_mock.send_message.assert_awaited_once()

    record = await journal_service.get_group_journal_channel(db_session, group.chat_id)
    assert isinstance(record.last_event_at, datetime)


@pytest.mark.asyncio
async def test_unlink_journal_channel(db_session):
    group = Group(chat_id=-2004, title="Journal group 4")
    db_session.add(group)
    await db_session.commit()

    await journal_service.link_journal_channel(db_session, group.chat_id, -7001)

    result = await journal_service.unlink_journal_channel(db_session, group.chat_id)
    assert result is True

    record = await journal_service.get_group_journal_channel(db_session, group.chat_id)
    assert record is None

