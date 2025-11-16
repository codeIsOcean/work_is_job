from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from bot.database.models import User, Group
from bot.config import DATABASE_URL

# тут файл для движка и сессии
print("DEBUG: DATABASE_URL =", DATABASE_URL)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


# функция добавления или проверки пользователя в бд при нажатий команды старт
async def get_or_create_user(session: AsyncSession, user_id: int, full_name: str, username: str):
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if not existing_user:
        user = User(user_id=user_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        return user

    return existing_user


# функция сохранения группы в бд
async def save_group(session: AsyncSession, chat_id, title, creator: User = None):
    # БАГ #13 ФИКС: Валидация chat_id перед сохранением
    if not chat_id or chat_id == 0:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"БАГ #13: Попытка сохранить группу с невалидным chat_id: {chat_id}")
        raise ValueError(f"Невалидный chat_id: {chat_id}. chat_id не может быть 0 или None")
    
    result = await session.execute(select(Group).where(Group.chat_id == chat_id))
    group = result.scalar_one_or_none()
    if group is None:
        group = Group(chat_id=chat_id, title=title, creator=creator)
        session.add(group)
        await session.commit()
    return group


# функция поиска группы по имени (username или title)
async def get_group_by_name(session: AsyncSession, group_name: str):
    """
    БАГ #10: Поиск группы по username (для публичных групп) или title.
    group_name может быть:
    - username группы (например, "toti_test" для @toti_test)
    - private_<chat_id> для приватных групп
    - числовой ID (например, "-1001234567890")
    """
    try:
        # Случай 1: Если group_name это username публичной группы
        # Проверяем по ChatSettings.username (там хранится username группы)
        from bot.database.models import ChatSettings
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.username == group_name)
        )
        chat_settings = result.scalar_one_or_none()
        if chat_settings:
            # Нашли через ChatSettings - возвращаем Group по chat_id
            result = await session.execute(
                select(Group).where(Group.chat_id == chat_settings.chat_id)
            )
            group = result.scalar_one_or_none()
            if group:
                return group
        
        # Случай 2: Если group_name начинается с "private_", извлекаем chat_id
        if group_name.startswith("private_"):
            try:
                chat_id = int(group_name.replace("private_", ""))
                result = await session.execute(
                    select(Group).where(Group.chat_id == chat_id)
                )
                return result.scalar_one_or_none()
            except ValueError:
                pass
        
        # Случай 3: Если group_name это числовой ID (начинается с "-")
        if group_name.startswith("-") and group_name[1:].isdigit():
            try:
                chat_id = int(group_name)
                result = await session.execute(
                    select(Group).where(Group.chat_id == chat_id)
                )
                return result.scalar_one_or_none()
            except ValueError:
                pass
        
        # Случай 4: Поиск по title (частичное совпадение)
        # Используем ilike для регистронезависимого поиска
        from sqlalchemy import func
        search_name = group_name.replace("_", " ").title()  # Преобразуем toti_test -> Toti Test
        result = await session.execute(
            select(Group).where(func.lower(Group.title).contains(func.lower(search_name)))
        )
        group = result.scalar_one_or_none()
        if group:
            return group
        
        # Не нашли
        return None
    except Exception as e:
        # Логируем ошибку, но не падаем
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при поиске группы по имени '{group_name}': {e}")
        return None