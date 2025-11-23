import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy import delete

from bot.database.models import Base, Group, UserGroup
from bot.handlers.group_settings_handler.groups_settings_in_private_handler import (
    manage_group_callback,
)


@pytest.fixture
async def sqlite_session_bug2() -> AsyncSession:
    """In-memory SQLite БД для unit-теста бага #2.

    НЕ использует PostgreSQL, Docker, Redis-подключения проекта и глобальный async_session.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        # На всякий случай чистим таблицы перед тестом
        await session.execute(delete(UserGroup))
        await session.execute(delete(Group))
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_binding_saves_correct_user_not_bot(
    sqlite_session_bug2: AsyncSession,
    fake_redis,
    message_factory,
    callback_query_factory,
    bot_mock,
):
    """БАГ #2: при нажатии на manage_group_{chat_id} должен сохраняться ID АДМИНА, а не бота.

    Сценарий:
    1. В БД есть группа и запись UserGroup, что пользователь 123 — админ группы -100123.
    2. Сообщение с кнопкой manage_group_ отправлено ОТ БОТА (message.from_user.id = bot.id).
    3. Callback приходит ОТ АДМИНА (callback.from_user.id = 123).
    4. После вызова manage_group_callback в Redis должен быть ключ "user:123" -> group_id,
       и НЕ должно быть записи для user:{bot.id}.
    """
    chat_id = -100123
    admin_id = 123
    bot_id = 424242  # см. bot_mock.id

    # 1. Готовим БД: группа + связь UserGroup (админ в этой группе)
    group = Group(chat_id=chat_id, title="Bug2 Test Group")
    sqlite_session_bug2.add(group)
    sqlite_session_bug2.add(UserGroup(user_id=admin_id, group_id=chat_id))
    await sqlite_session_bug2.commit()

    # 2. Создаём сообщение от бота (message.from_user.id = bot_id)
    message = message_factory(chat_id=chat_id, user_id=bot_id)

    # 3. Создаём callback от админа (from_user.id = admin_id)
    callback = callback_query_factory(
        data=f"manage_group_{chat_id}",
        from_user_id=admin_id,
        chat_id=chat_id,
    )

    # Заменяем message внутри callback на наше сообщение от бота
    # Подвешиваем мокнутый bot к message и callback, учитывая что объекты заморожены
    # Создаем новую версию message с прикрепленным bot_mock
    message_with_bot = message.model_copy(update={"bot": bot_mock})
    # Создаем новую версию callback с прикрепленными message_with_bot и bot_mock
    callback = callback.model_copy(update={"message": message_with_bot, "bot": bot_mock})

    # Настраиваем get_me так, чтобы возвращал объект с id = bot_id
    class _Me:
        def __init__(self, id_: int):
            self.id = id_

    bot_mock.get_me.return_value = _Me(bot_id)

    # 4. Вызываем целевой хендлер
    await manage_group_callback(callback, sqlite_session_bug2)

    # 5. Проверяем, что в Redis сохранилась привязка ДЛЯ АДМИНА
    saved_group_for_admin = await fake_redis.hget(f"user:{admin_id}", "group_id")
    assert saved_group_for_admin == str(chat_id), "Должен сохраняться group_id для admin.id, а не для bot.id"

    # 6. И что НЕТ записи для бота
    saved_group_for_bot = await fake_redis.hget(f"user:{bot_id}", "group_id")
    assert saved_group_for_bot is None, "Не должно быть привязки для bot.id в Redis"
