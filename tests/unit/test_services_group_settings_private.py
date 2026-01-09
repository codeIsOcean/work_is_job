import pytest

from bot.database.models import (
    CaptchaSettings,
    ChatSettings,
    Group,
    GroupJournalChannel,
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


@pytest.mark.asyncio
async def test_get_admin_groups_filters_journals(db_session):
    """Тест что get_admin_groups() фильтрует журналы-каналы из списка групп"""
    # Создаём пользователя
    user = User(user_id=125, first_name="Admin3")

    # Создаём группу (обычная группа - должна быть в списке)
    group = Group(chat_id=-3005, title="Normal group")

    # Создаём журнал-канал (должен быть отфильтрован)
    journal = Group(chat_id=-1001234567890, title="Journal channel")

    # Связываем пользователя с обеими группами
    link_group = UserGroup(user_id=user.user_id, group_id=group.chat_id)
    link_journal = UserGroup(user_id=user.user_id, group_id=journal.chat_id)

    # Создаём запись о привязке журнала к группе
    journal_link = GroupJournalChannel(
        group_id=group.chat_id,
        journal_channel_id=journal.chat_id,
        journal_title="Journal channel",
        is_active=True
    )

    # Добавляем все объекты в базу
    db_session.add_all([user, group, journal, link_group, link_journal, journal_link])
    await db_session.commit()

    # Получаем список групп (без bot параметра для упрощения теста)
    groups = await group_settings_logic.get_admin_groups(user.user_id, db_session)

    # Проверяем что в списке только одна группа (журнал отфильтрован)
    assert len(groups) == 1
    assert groups[0].chat_id == group.chat_id
    assert groups[0].title == "Normal group"


@pytest.mark.asyncio
async def test_get_linked_journals_returns_empty_list(db_session):
    """Тест что get_linked_journals() возвращает пустой список когда журналов нет"""
    # Получаем список журналов (должен быть пустым)
    journals = await group_settings_logic.get_linked_journals(db_session)

    # Проверяем что список пустой
    assert journals == []


@pytest.mark.asyncio
async def test_get_linked_journals_returns_journals_list(db_session):
    """Тест что get_linked_journals() возвращает список привязанных журналов"""
    # Создаём группу
    group = Group(chat_id=-3006, title="Test group for journals")
    db_session.add(group)
    await db_session.commit()

    # Создаём запись о привязке журнала
    journal_link = GroupJournalChannel(
        group_id=group.chat_id,
        journal_channel_id=-1001234567891,
        journal_title="Test journal",
        is_active=True
    )
    db_session.add(journal_link)
    await db_session.commit()

    # Получаем список журналов
    journals = await group_settings_logic.get_linked_journals(db_session)

    # Проверяем что в списке один журнал
    assert len(journals) == 1
    assert journals[0]['group_id'] == group.chat_id
    assert journals[0]['group_title'] == "Test group for journals"
    # Ключ journal_id (не journal_channel_id) согласно get_linked_journals()
    assert journals[0]['journal_id'] == -1001234567891
    assert journals[0]['journal_title'] == "Test journal"
    assert journals[0]['is_active'] is True


@pytest.mark.asyncio
async def test_get_linked_journals_includes_inactive_journals(db_session):
    """Тест что get_linked_journals() возвращает неактивные журналы тоже"""
    # Создаём группу
    group = Group(chat_id=-3007, title="Inactive journal group")
    db_session.add(group)
    await db_session.commit()

    # Создаём запись о неактивном журнале
    journal_link = GroupJournalChannel(
        group_id=group.chat_id,
        journal_channel_id=-1001234567892,
        journal_title="Inactive journal",
        is_active=False
    )
    db_session.add(journal_link)
    await db_session.commit()

    # Получаем список журналов
    journals = await group_settings_logic.get_linked_journals(db_session)

    # Проверяем что неактивный журнал тоже в списке
    assert len(journals) == 1
    assert journals[0]['is_active'] is False

