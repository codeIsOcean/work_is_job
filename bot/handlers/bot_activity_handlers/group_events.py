# group_events.py
# Обработка событий добавления/удаления бота из группы
import logging
from aiogram import Router, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from bot.database.models import Group, User, GroupUsers, UserGroup, ChatSettings

logger = logging.getLogger(__name__)

group_events_router = Router()


@group_events_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def bot_added_to_group(event: types.ChatMemberUpdated, session: AsyncSession):
    chat = event.chat
    user = event.from_user

    logger.info(f"Бот добавлен в группу {chat.title} (ID: {chat.id}) пользователем {user.full_name} (ID: {user.id})")

    try:
        # 1. Создание или обновление пользователя
        result = await session.execute(select(User).where(User.user_id == user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            db_user = User(user_id=user.id, username=user.username, full_name=user.full_name)
            session.add(db_user)
            await session.flush()
            logger.info(f"Создан новый пользователь: {user.full_name}")

        # 2. Проверка или создание группы
        result = await session.execute(select(Group).where(Group.chat_id == chat.id))
        group = result.scalar_one_or_none()

        if not group:
            # Получение администраторов
            creator_id = None
            admins = await event.bot.get_chat_administrators(chat.id)

            for admin in admins:
                # Создание пользователя, если не существует
                result = await session.execute(select(User).where(User.user_id == admin.user.id))
                db_admin = result.scalar_one_or_none()
                if not db_admin:
                    db_admin = User(
                        user_id=admin.user.id,
                        username=admin.user.username,
                        full_name=admin.user.full_name
                    )
                    session.add(db_admin)

            await session.flush()

            # Создание группы
            for admin in admins:
                if admin.status == "creator":
                    creator_id = admin.user.id
                    break

            # БАГ #13 ФИКС: Валидация chat_id перед созданием группы
            if not chat.id or chat.id == 0:
                logger.error(f"БАГ #13: Попытка создать группу с невалидным chat_id: {chat.id}")
                raise ValueError(f"Невалидный chat_id: {chat.id}. chat_id не может быть 0 или None")
            
            group = Group(
                chat_id=chat.id,
                title=chat.title,
                creator_user_id=creator_id,
                added_by_user_id=user.id
            )
            session.add(group)
            await session.flush()
            logger.info(f"Создана новая группа: {chat.title}")

            # Создаём/обновляем настройки чата и сохраняем username (для поиска по deep link)
            chat_settings = ChatSettings(chat_id=chat.id, username=chat.username)
            session.add(chat_settings)

            # Добавление всех админов в GroupUsers и UserGroup
            for admin in admins:
                session.add(GroupUsers(
                    user_id=admin.user.id,
                    chat_id=chat.id,
                    username=admin.user.username,
                    first_name=admin.user.first_name,
                    last_name=admin.user.last_name,
                    is_admin=True
                ))
                # Добавляем в UserGroup для проверки прав
                session.add(UserGroup(
                    user_id=admin.user.id,
                    group_id=chat.id
                ))
                logger.info(f"Добавлен администратор: {admin.user.full_name} (ID: {admin.user.id})")

        else:
            # Обновление названия
            group.title = chat.title
            logger.info(f"Обновлена информация о группе: {chat.title}")

            # Обновляем username в настройках, если группа уже существует
            result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat.id))
            chat_settings = result.scalar_one_or_none()
            if not chat_settings:
                chat_settings = ChatSettings(chat_id=chat.id, username=chat.username)
                session.add(chat_settings)
            else:
                chat_settings.username = chat.username

        # 3. Добавление пользователя, добавившего бота, как админа
        # Сначала убеждаемся, что пользователь существует в таблице User
        result = await session.execute(select(User).where(User.user_id == user.id))
        db_user_who_added = result.scalar_one_or_none()
        if not db_user_who_added:
            db_user_who_added = User(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                first_name=user.first_name,
                last_name=user.last_name
            )
            session.add(db_user_who_added)
            await session.flush()
        
        # Теперь добавляем в GroupUsers
        result = await session.execute(select(GroupUsers).where(
            GroupUsers.chat_id == chat.id,
            GroupUsers.user_id == user.id
        ))
        if not result.scalar_one_or_none():
            session.add(GroupUsers(
                chat_id=chat.id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_admin=True
            ))
            logger.info(f"Добавлен пользователь, добавивший бота: {user.full_name}")

        # Добавляем в UserGroup для проверки прав
        result = await session.execute(select(UserGroup).where(
            UserGroup.user_id == user.id,
            UserGroup.group_id == chat.id
        ))
        if not result.scalar_one_or_none():
            session.add(UserGroup(
                user_id=user.id,
                group_id=chat.id
            ))
            logger.info(f"Добавлен пользователь в UserGroup для проверки прав: {user.full_name}")

        await session.commit()
        logger.info(f"Информация о группе {chat.title} успешно сохранена")

    except Exception as e:
        logger.error(f"Ошибка при добавлении группы: {e}")
        await session.rollback()
        raise


@group_events_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER >> IS_NOT_MEMBER))
async def bot_removed_from_group(event: types.ChatMemberUpdated, session: AsyncSession):
    """
    Обработка удаления бота из группы.

    ВАЖНО: НЕ удаляем группу из БД! Только очищаем связи UserGroup.

    Причина: событие IS_MEMBER >> IS_NOT_MEMBER может срабатывать ложно
    при глитчах Telegram API или изменении прав бота. Если удалить группу,
    она исчезнет из /settings и пользователю придётся заново настраивать бота.

    При реальном удалении бота:
    - AUTO_SYNC не сможет синхронизировать группу (бота нет)
    - При восстановлении бота группа уже будет в БД с сохранёнными настройками
    """
    chat = event.chat
    user = event.from_user

    logger.info(
        f"🗑️ Бот удалён из группы {chat.title} (ID: {chat.id}) пользователем {user.full_name} (ID: {user.id})"
    )

    try:
        # Удаляем только связи UserGroup (права админов)
        # Группа остаётся в БД с сохранёнными настройками
        result = await session.execute(
            delete(UserGroup).where(UserGroup.group_id == chat.id)
        )
        deleted_count = result.rowcount

        # Помечаем группу как неактивную (опционально, для отладки)
        group_result = await session.execute(select(Group).where(Group.chat_id == chat.id))
        group = group_result.scalar_one_or_none()
        if group:
            # НЕ удаляем группу! Настройки сохраняются.
            logger.info(f"📝 Группа {chat.id} ({chat.title}) сохранена в БД, удалено {deleted_count} связей UserGroup")

        await session.commit()

        # Чистим кэш синхронизации в Redis (группа может быть ресинхронизирована позже)
        try:
            from bot.services.redis_conn import redis
            await redis.delete(f"group_synced:{chat.id}")
            # Остальные ключи НЕ удаляем - настройки сохраняются
        except Exception as re:
            logger.warning(f"Не удалось очистить Redis кэш для группы {chat.id}: {re}")

        logger.info(f"✅ Обработано удаление бота из группы {chat.id}. Группа и настройки СОХРАНЕНЫ в БД.")
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке удаления бота из группы {chat.id}: {e}")
        await session.rollback()

# УДАЛЕНО: Дублирующий хендлер handle_join_request
# Основная логика капчи находится в visual_captcha_handler.py
# Этот хендлер перехватывал события и блокировал работу основного хендлера
# Удалено 2025-12-14 для решения бага с неработающей капчей
