"""
Unit тесты для автоматической синхронизации групп.

Проверяет, что:
1. Группа автоматически создаётся в БД при первом событии
2. Админы синхронизируются при создании группы
3. Кэш предотвращает слишком частую синхронизацию
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.enums import ChatType, ChatMemberStatus


class TestGroupAutoSync:
    """Тесты для автоматической синхронизации групп"""

    @pytest.mark.asyncio
    async def test_ensure_group_exists_creates_group(self, db_session, fake_redis):
        """
        Тест: ensure_group_exists создаёт группу если её нет в БД.
        """
        from bot.services.group_auto_sync import ensure_group_exists
        from bot.database.models import Group, User, UserGroup
        from sqlalchemy import select

        chat_id = -1002302638465

        # Мокаем chat
        chat = MagicMock()
        chat.id = chat_id
        chat.title = "Test Group"
        chat.type = ChatType.SUPERGROUP

        # Мокаем bot
        bot = AsyncMock(spec=Bot)
        bot.id = 999

        bot_info = MagicMock()
        bot_info.id = 999
        bot.me = AsyncMock(return_value=bot_info)

        # Мокаем get_chat_administrators
        admin = MagicMock()
        admin.user = MagicMock()
        admin.user.id = 619924982
        admin.user.username = "texas_dev"
        admin.user.first_name = "Texas"
        admin.user.last_name = "Dev"
        admin.user.is_bot = False
        admin.status = ChatMemberStatus.ADMINISTRATOR

        bot.get_chat_administrators = AsyncMock(return_value=[admin])

        # Вызываем ensure_group_exists
        result = await ensure_group_exists(db_session, chat, bot)

        # Проверяем, что группа создана
        assert result is not None
        assert result.chat_id == chat_id
        assert result.title == "Test Group"

        # Проверяем, что группа в БД
        group_result = await db_session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        assert group_result.scalar_one_or_none() is not None

        # Проверяем, что UserGroup связь создана
        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == 619924982,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_ensure_group_exists_updates_title(self, db_session, fake_redis):
        """
        Тест: ensure_group_exists обновляет название группы если изменилось.
        """
        from bot.services.group_auto_sync import ensure_group_exists
        from bot.database.models import Group, User
        from sqlalchemy import select

        chat_id = -1002302638466

        # Создаём группу с одним названием
        user = User(user_id=999, username="bot", full_name="Bot", is_bot=True)
        db_session.add(user)
        group = Group(chat_id=chat_id, title="Old Title", bot_id=999)
        db_session.add(group)
        await db_session.commit()

        # Мокаем chat с новым названием
        chat = MagicMock()
        chat.id = chat_id
        chat.title = "New Title"
        chat.type = ChatType.SUPERGROUP

        # Мокаем bot
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot_info = MagicMock()
        bot_info.id = 999
        bot.me = AsyncMock(return_value=bot_info)
        bot.get_chat_administrators = AsyncMock(return_value=[])

        # Вызываем ensure_group_exists
        result = await ensure_group_exists(db_session, chat, bot)

        # Проверяем, что название обновилось
        assert result.title == "New Title"

    @pytest.mark.asyncio
    async def test_sync_uses_cache(self, db_session, fake_redis):
        """
        Тест: После синхронизации группа кэшируется и не синхронизируется повторно.
        """
        from bot.services.group_auto_sync import ensure_group_exists, _is_recently_synced
        from bot.database.models import Group, User

        chat_id = -1002302638467

        # Мокаем chat
        chat = MagicMock()
        chat.id = chat_id
        chat.title = "Cached Group"
        chat.type = ChatType.SUPERGROUP

        # Мокаем bot
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot_info = MagicMock()
        bot_info.id = 999
        bot.me = AsyncMock(return_value=bot_info)
        bot.get_chat_administrators = AsyncMock(return_value=[])

        # Первый вызов - синхронизация
        await ensure_group_exists(db_session, chat, bot)

        # Проверяем, что группа в кэше
        assert await _is_recently_synced(chat_id)

        # get_chat_administrators вызван один раз
        assert bot.get_chat_administrators.call_count == 1

        # Второй вызов - из кэша
        await ensure_group_exists(db_session, chat, bot)

        # get_chat_administrators всё ещё вызван один раз (не было повторной синхронизации)
        assert bot.get_chat_administrators.call_count == 1

    @pytest.mark.asyncio
    async def test_ignores_private_chats(self, db_session, fake_redis):
        """
        Тест: Private чаты игнорируются.
        """
        from bot.services.group_auto_sync import ensure_group_exists

        # Мокаем private chat
        chat = MagicMock()
        chat.id = 619924982
        chat.title = None
        chat.type = ChatType.PRIVATE

        bot = AsyncMock(spec=Bot)

        result = await ensure_group_exists(db_session, chat, bot)

        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_user_admin_link_creates_link(self, db_session, fake_redis):
        """
        Тест: ensure_user_admin_link создаёт связь UserGroup для админа.
        """
        from bot.services.group_auto_sync import ensure_user_admin_link
        from bot.database.models import UserGroup, User, Group
        from sqlalchemy import select

        user_id = 619924982
        chat_id = -1002302638468

        # Создаём группу (FK constraint)
        bot_user = User(user_id=999, username="bot", full_name="Bot", is_bot=True)
        db_session.add(bot_user)
        group = Group(chat_id=chat_id, title="Test Group", bot_id=999)
        db_session.add(group)
        await db_session.commit()

        # Мокаем bot
        bot = AsyncMock(spec=Bot)

        # Мокаем member с user данными
        member = MagicMock()
        member.status = ChatMemberStatus.ADMINISTRATOR
        member.user = MagicMock()
        member.user.id = user_id
        member.user.username = "texas_dev"
        member.user.first_name = "Texas"
        member.user.last_name = "Dev"
        member.user.is_bot = False

        bot.get_chat_member = AsyncMock(return_value=member)

        # Вызываем ensure_user_admin_link
        result = await ensure_user_admin_link(db_session, user_id, chat_id, bot)

        assert result is True

        # Проверяем, что User создан
        user_result = await db_session.execute(
            select(User).where(User.user_id == user_id)
        )
        assert user_result.scalar_one_or_none() is not None

        # Проверяем, что связь создана
        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_ensure_user_admin_link_rejects_non_admin(self, db_session, fake_redis):
        """
        Тест: ensure_user_admin_link возвращает False для не-админа.
        """
        from bot.services.group_auto_sync import ensure_user_admin_link

        user_id = 123456
        chat_id = -1002302638469

        # Мокаем bot
        bot = AsyncMock(spec=Bot)
        member = MagicMock()
        member.status = ChatMemberStatus.MEMBER  # Не админ
        member.user = MagicMock()
        member.user.id = user_id
        bot.get_chat_member = AsyncMock(return_value=member)

        result = await ensure_user_admin_link(db_session, user_id, chat_id, bot)

        assert result is False
