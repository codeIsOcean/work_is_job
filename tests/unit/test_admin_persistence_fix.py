"""
Unit тесты для фикса: Админы не должны "слетать" при временных ошибках API.

Баг: При перезагрузке бота, get_admin_groups удалял записи UserGroup
при ЛЮБОЙ ошибке API (таймаут, rate limit), что приводило к потере прав админов.

Фикс: Записи удаляются ТОЛЬКО при постоянных ошибках ("chat not found", "user not found").
При временных ошибках - доверяем данным из БД.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError


async def _create_test_data(db_session, user_id: int, chat_id: int):
    """Создает тестовые данные: User, Group, UserGroup"""
    from bot.database.models import User, Group, UserGroup

    # Создаем пользователя
    user = User(user_id=user_id, username="test_user", full_name="Test User")
    db_session.add(user)

    # Создаем группу
    group = Group(chat_id=chat_id, title="Test Group", bot_id=999)
    db_session.add(group)

    # Создаем связь UserGroup
    user_group = UserGroup(user_id=user_id, group_id=chat_id)
    db_session.add(user_group)

    await db_session.commit()
    return group


class TestAdminPersistenceFix:
    """Тесты для проверки, что админы не теряются при временных ошибках"""

    @pytest.mark.asyncio
    async def test_temporary_error_does_not_delete_user_group(self, db_session):
        """
        Тест: При временной ошибке (таймаут) записи UserGroup НЕ удаляются.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 123456
        chat_id = -1001234567890

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота с таймаутом
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot.get_chat_member = AsyncMock(side_effect=TimeoutError("Connection timeout"))

        result = await get_admin_groups(user_id, db_session, bot=bot)

        # Группа должна быть в результате (доверяем БД)
        assert len(result) == 1
        assert result[0].chat_id == chat_id

        # Запись UserGroup НЕ удалена
        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_rate_limit_error_does_not_delete_user_group(self, db_session):
        """
        Тест: При rate limit ошибке записи UserGroup НЕ удаляются.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 234567
        chat_id = -1001234567891

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота с rate limit
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot.get_chat_member = AsyncMock(
            side_effect=TelegramAPIError(
                method=MagicMock(),
                message="Too Many Requests: retry after 30"
            )
        )

        result = await get_admin_groups(user_id, db_session, bot=bot)

        assert len(result) == 1

        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_chat_not_found_deletes_user_group(self, db_session):
        """
        Тест: При ошибке "chat not found" записи UserGroup УДАЛЯЮТСЯ.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 345678
        chat_id = -1001234567892

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота с ошибкой "chat not found"
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot.get_chat_member = AsyncMock(
            side_effect=TelegramAPIError(
                method=MagicMock(),
                message="Bad Request: chat not found"
            )
        )

        result = await get_admin_groups(user_id, db_session, bot=bot)

        # Группа НЕ в результате
        assert len(result) == 0

        # Запись UserGroup УДАЛЕНА
        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_user_kicked_deletes_user_group(self, db_session):
        """
        Тест: При ошибке "kicked" записи UserGroup УДАЛЯЮТСЯ.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 456789
        chat_id = -1001234567893

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота с ошибкой "kicked"
        bot = AsyncMock(spec=Bot)
        bot.id = 999
        bot.get_chat_member = AsyncMock(
            side_effect=TelegramAPIError(
                method=MagicMock(),
                message="Forbidden: bot was kicked from the supergroup chat"
            )
        )

        result = await get_admin_groups(user_id, db_session, bot=bot)

        assert len(result) == 0

        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_normal_flow_works(self, db_session):
        """
        Тест: Нормальный флоу (без ошибок) работает корректно.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 567890
        chat_id = -1001234567894

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота - всё ОК
        bot = AsyncMock(spec=Bot)
        bot.id = 999

        bot_member = MagicMock()
        bot_member.status = "administrator"

        user_member = MagicMock()
        user_member.status = "administrator"

        bot.get_chat_member = AsyncMock(side_effect=[bot_member, user_member])

        result = await get_admin_groups(user_id, db_session, bot=bot)

        assert len(result) == 1
        assert result[0].chat_id == chat_id

        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_user_demoted_deletes_user_group(self, db_session):
        """
        Тест: Если пользователь больше не админ, запись удаляется.
        """
        from bot.services.groups_settings_in_private_logic import get_admin_groups
        from bot.database.models import UserGroup
        from sqlalchemy import select

        user_id = 678901
        chat_id = -1001234567895

        await _create_test_data(db_session, user_id, chat_id)

        # Мокаем бота
        bot = AsyncMock(spec=Bot)
        bot.id = 999

        bot_member = MagicMock()
        bot_member.status = "administrator"

        user_member = MagicMock()
        user_member.status = "member"  # Не админ!

        bot.get_chat_member = AsyncMock(side_effect=[bot_member, user_member])

        result = await get_admin_groups(user_id, db_session, bot=bot)

        assert len(result) == 0

        ug_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        assert ug_result.scalar_one_or_none() is None
