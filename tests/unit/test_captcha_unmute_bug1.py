import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bot.database.models import Base, Group, ChatSettings
from bot.database.queries import get_group_by_name


@pytest.fixture
async def sqlite_session() -> AsyncSession:
    """Создаёт in-memory SQLite БД c полным schema из Base.metadata.

    ВАЖНО: этот unit-тест НЕ использует PostgreSQL, Docker, Redis или async_session проекта.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_group_found_by_username_after_fix_sqlite(sqlite_session: AsyncSession):
    """БАГ #1: группа должна находиться по username через get_group_by_name (unit-тест на SQLite).

    Сценарий:
    1. Создаём запись Group и ChatSettings в in-memory SQLite.
    2. Вызываем get_group_by_name(session, username).
    3. Убеждаемся, что вернулась именно эта группа и нет исключений AttributeError.
    """
    test_chat_id = -1009990001234
    test_username = "toti_test_bug1"

    # Чистим возможные старые данные с тем же chat_id/username (на случай повторных запусков в одной БД)
    await sqlite_session.execute(delete(ChatSettings).where(ChatSettings.chat_id == test_chat_id))
    await sqlite_session.execute(delete(Group).where(Group.chat_id == test_chat_id))
    await sqlite_session.commit()

    # 1. Создаём группу
    group = Group(chat_id=test_chat_id, title="Bug1 Test Group")
    sqlite_session.add(group)
    await sqlite_session.flush()

    # 2. Создаём настройки чата с username
    chat_settings = ChatSettings(chat_id=test_chat_id, username=test_username)
    sqlite_session.add(chat_settings)
    await sqlite_session.commit()

    # 3. Вызываем целевую функцию
    result_group = await get_group_by_name(sqlite_session, test_username)

    # 4. Проверяем, что группа найдена и chat_id совпадает
    assert result_group is not None, "Группа по username не найдена"
    assert result_group.chat_id == test_chat_id

    # 5. Убираем за собой данные
    await sqlite_session.execute(delete(ChatSettings).where(ChatSettings.chat_id == test_chat_id))
    await sqlite_session.execute(delete(Group).where(Group.chat_id == test_chat_id))
    await sqlite_session.commit()
