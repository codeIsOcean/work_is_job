"""
Сервис автоматической синхронизации групп и админов.

Решает проблему: бот добавлен в группу, но записей в БД нет.
При любой активности в группе - автоматически синхронизирует данные.
"""
import logging
from typing import Optional
from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import Chat, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Group, User as DbUser, UserGroup, GroupUsers
from bot.services.redis_conn import redis

logger = logging.getLogger(__name__)

# Кэш в Redis чтобы не синхронизировать слишком часто
SYNC_CACHE_TTL = 300  # 5 минут


async def _is_recently_synced(chat_id: int) -> bool:
    """Проверяет, была ли группа недавно синхронизирована"""
    key = f"group_synced:{chat_id}"
    return await redis.exists(key) == 1


async def _mark_as_synced(chat_id: int):
    """Отмечает группу как синхронизированную"""
    key = f"group_synced:{chat_id}"
    await redis.setex(key, SYNC_CACHE_TTL, "1")


async def ensure_group_exists(
    session: AsyncSession,
    chat: Chat,
    bot: Bot,
) -> Optional[Group]:
    """
    Проверяет, что группа есть в БД. Если нет - создаёт.

    Returns:
        Group объект или None при ошибке
    """
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return None

    chat_id = chat.id

    # Проверяем кэш
    if await _is_recently_synced(chat_id):
        # Группа недавно синхронизировалась, просто возвращаем из БД
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    try:
        # Проверяем есть ли группа в БД
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        group = result.scalar_one_or_none()

        bot_info = await bot.me()

        if group:
            # Группа есть, обновляем название если изменилось
            if group.title != chat.title:
                group.title = chat.title
                await session.flush()
                logger.info(f"✅ Обновлено название группы {chat_id}: {chat.title}")
        else:
            # Группы нет - создаём
            group = Group(
                chat_id=chat_id,
                title=chat.title or str(chat_id),
                bot_id=bot_info.id
            )
            session.add(group)
            await session.flush()
            logger.info(f"✅ [AUTO_SYNC] Создана группа в БД: {chat.title} ({chat_id})")

        # Синхронизируем админов
        await sync_group_admins(session, chat_id, bot)

        await session.commit()
        await _mark_as_synced(chat_id)

        return group

    except Exception as e:
        logger.error(f"❌ Ошибка автосинхронизации группы {chat_id}: {e}")
        await session.rollback()
        return None


async def sync_group_admins(
    session: AsyncSession,
    chat_id: int,
    bot: Bot,
) -> int:
    """
    Синхронизирует админов группы с БД.

    Returns:
        Количество синхронизированных админов
    """
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_count = 0

        for admin in admins:
            user = admin.user

            # Пропускаем ботов (кроме нашего)
            if user.is_bot and user.id != bot.id:
                continue

            # Создаём/обновляем пользователя в таблице User
            result = await session.execute(
                select(DbUser).where(DbUser.user_id == user.id)
            )
            db_user = result.scalar_one_or_none()

            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

            if db_user:
                db_user.username = user.username
                db_user.full_name = full_name
            else:
                db_user = DbUser(
                    user_id=user.id,
                    username=user.username,
                    full_name=full_name,
                    is_bot=user.is_bot
                )
                session.add(db_user)

            # Создаём связь UserGroup (для проверки прав в /settings)
            result = await session.execute(
                select(UserGroup).where(
                    UserGroup.user_id == user.id,
                    UserGroup.group_id == chat_id
                )
            )
            if not result.scalar_one_or_none():
                session.add(UserGroup(user_id=user.id, group_id=chat_id))
                logger.info(f"✅ [AUTO_SYNC] Добавлен админ {user.id} (@{user.username}) в группу {chat_id}")

            # Создаём/обновляем GroupUsers
            is_creator = admin.status == ChatMemberStatus.CREATOR
            result = await session.execute(
                select(GroupUsers).where(
                    GroupUsers.user_id == user.id,
                    GroupUsers.chat_id == chat_id
                )
            )
            group_user = result.scalar_one_or_none()

            if group_user:
                group_user.username = user.username
                group_user.is_admin = True
                group_user.is_creator = is_creator
            else:
                session.add(GroupUsers(
                    user_id=user.id,
                    chat_id=chat_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    is_admin=True,
                    is_creator=is_creator
                ))

            admin_count += 1

        await session.flush()
        logger.info(f"✅ [AUTO_SYNC] Синхронизировано {admin_count} админов для группы {chat_id}")
        return admin_count

    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации админов группы {chat_id}: {e}")
        return 0


async def ensure_user_admin_link(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    bot: Bot,
) -> bool:
    """
    Проверяет и создаёт связь UserGroup если пользователь - админ.
    Вызывается когда пользователь пытается управлять группой.

    Returns:
        True если пользователь админ и связь создана/существует
    """
    try:
        # Проверяем в Telegram, что пользователь - админ
        member = await bot.get_chat_member(chat_id, user_id)

        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            return False

        # Создаём/обновляем пользователя в таблице User (для FK constraint)
        result = await session.execute(
            select(DbUser).where(DbUser.user_id == user_id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            # Получаем информацию о пользователе из member
            user = member.user
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            db_user = DbUser(
                user_id=user_id,
                username=user.username,
                full_name=full_name,
                is_bot=user.is_bot
            )
            session.add(db_user)
            await session.flush()

        # Проверяем есть ли связь в БД
        result = await session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )

        if not result.scalar_one_or_none():
            # Создаём связь
            session.add(UserGroup(user_id=user_id, group_id=chat_id))
            await session.commit()
            logger.info(f"✅ [AUTO_SYNC] Создана связь админа {user_id} с группой {chat_id}")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка проверки админа {user_id} в группе {chat_id}: {e}")
        return False
