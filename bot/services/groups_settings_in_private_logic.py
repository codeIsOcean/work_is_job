from typing import List
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from bot.database.models import Group, UserGroup, CaptchaSettings, ChatSettings
import logging

logger = logging.getLogger(__name__)


async def get_admin_groups(user_id: int, session: AsyncSession, bot: Bot = None) -> List[Group]:
    """Возвращает список групп, где пользователь сейчас является админом.
    Если bot не передан — возвращает группы по данным БД без онлайн-проверки.
    """
    try:
        # Все связи пользователь-группа из БД
        user_groups_query = select(UserGroup).where(UserGroup.user_id == user_id)
        user_groups_result = await session.execute(user_groups_query)
        user_groups = user_groups_result.scalars().all()

        logger.info(f"Найдено {len(user_groups)} записей с правами админа (по БД)")

        if not user_groups:
            return []

        group_ids = [ug.group_id for ug in user_groups]
        groups_query = select(Group).where(Group.chat_id.in_(group_ids))
        groups_result = await session.execute(groups_query)
        groups = groups_result.scalars().all()

        if not bot:
            # Старое поведение: без онлайн-проверки
            logger.warning("get_admin_groups: bot не передан, возврат групп без онлайн-проверки")
            return groups

        valid_groups: List[Group] = []

        for group in groups:
            try:
                # Проверяем, что бот в группе
                try:
                    bot_member = await bot.get_chat_member(group.chat_id, bot.id)
                    if bot_member.status not in ("member", "administrator", "creator"):
                        logger.info(f"Бот не состоит в группе {group.chat_id}, пропускаем")
                        continue
                except Exception as e:
                    logger.warning(f"Не удалось получить статус бота в группе {group.chat_id}: {e}")
                    # Чистим устаревшую связь
                    await session.execute(
                        delete(UserGroup).where(
                            UserGroup.user_id == user_id,
                            UserGroup.group_id == group.chat_id,
                        )
                    )
                    await session.commit()
                    continue

                # Проверяем, что пользователь сейчас админ
                try:
                    user_member = await bot.get_chat_member(group.chat_id, user_id)
                    if user_member.status not in ("administrator", "creator"):
                        logger.info(f"Пользователь {user_id} больше не админ в группе {group.chat_id}, чистим связь")
                        await session.execute(
                            delete(UserGroup).where(
                                UserGroup.user_id == user_id,
                                UserGroup.group_id == group.chat_id,
                            )
                        )
                        await session.commit()
                        continue
                except Exception as e:
                    logger.warning(f"Не удалось проверить права пользователя {user_id} в группе {group.chat_id}: {e}")
                    continue

                valid_groups.append(group)
            except Exception as e:
                logger.error(f"Ошибка обработки группы {group.chat_id}: {e}")
                continue

        return valid_groups

    except Exception as e:
        logger.error(f"Ошибка при получении групп пользователя {user_id}: {e}")
        return []


async def check_admin_rights(session: AsyncSession, user_id: int, chat_id: int) -> bool:
    """Проверяет права администратора пользователя в группе (базовая проверка из БД)"""
    try:
        result = await session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        return result.scalar_one_or_none() is not None
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def check_granular_permissions(
    bot: Bot,
    user_id: int,
    chat_id: int,
    required_permission: str,
    session: AsyncSession = None
) -> bool:
    """
    Проверяет гранулярные права администратора на основе флагов Telegram API.
    Как в крупных ботах (grouphelp, роза и т.д.)
    
    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        required_permission: Требуемое разрешение:
            - 'restrict_members' - для мута новых участников, автомута скамеров
            - 'change_info' - для изменения настроек бота, капчи
            - 'delete_messages' - для удаления сообщений, модерации
            - 'post_messages' - для рассылок
            - 'invite_users' - для управления приглашениями
            - 'pin_messages' - для закрепления сообщений
        session: Опциональная сессия БД для проверки суперадминов
    
    Returns:
        True если у пользователя есть требуемое право или он creator/superadmin
    """
    try:
        # 1. Проверяем, является ли пользователь суперадмином
        if session:
            from bot.config import ADMIN_IDS
            if user_id in ADMIN_IDS:
                logger.info(f"✅ Пользователь {user_id} - суперадмин, разрешаем доступ")
                return True
        
        # 2. Получаем информацию о члене группы через Telegram API
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception as e:
            logger.error(f"Ошибка при получении информации о члене группы {chat_id}: {e}")
            return False
        
        # 3. Если пользователь - creator, разрешаем всё
        if member.status == "creator":
            logger.info(f"✅ Пользователь {user_id} - creator группы {chat_id}, разрешаем доступ")
            return True
        
        # 4. Если пользователь не админ, отказываем
        if member.status != "administrator":
            logger.warning(f"❌ Пользователь {user_id} не является администратором в группе {chat_id}")
            return False
        
        # 5. Маппинг требуемых разрешений на флаги Telegram API
        permission_flags = {
            'restrict_members': getattr(member, 'can_restrict_members', False),
            'change_info': getattr(member, 'can_change_info', False),
            'delete_messages': getattr(member, 'can_delete_messages', False),
            'post_messages': getattr(member, 'can_post_messages', False),
            'invite_users': getattr(member, 'can_invite_users', False),
            'pin_messages': getattr(member, 'can_pin_messages', False),
        }
        
        # 6. Проверяем требуемое разрешение
        if required_permission not in permission_flags:
            logger.warning(f"⚠️ Неизвестное разрешение: {required_permission}")
            return False
        
        has_permission = permission_flags[required_permission]
        
        if has_permission:
            logger.info(f"✅ Пользователь {user_id} имеет право '{required_permission}' в группе {chat_id}")
        else:
            logger.warning(f"❌ Пользователь {user_id} НЕ имеет права '{required_permission}' в группе {chat_id}")
        
        return has_permission
        
    except Exception as e:
        logger.error(f"Ошибка при проверке гранулярных прав: {e}")
        return False


async def get_group_by_chat_id(session: AsyncSession, chat_id: int):
    """Получает группу по chat_id"""
    try:
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Ошибка при получении группы: {e}")
        return None


async def get_visual_captcha_status(session: AsyncSession, chat_id: int) -> bool:
    """Получает статус визуальной капчи для группы"""
    try:
        result = await session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
        )
        settings = result.scalar_one_or_none()

        is_enabled = settings.is_visual_enabled if settings else False
        logger.info(f"Статус визуальной капчи для группы {chat_id}: {'включена' if is_enabled else 'выключена'}")

        return is_enabled
    except Exception as e:
        logger.error(f"Ошибка при получении статуса капчи: {e}")
        return False


async def get_mute_new_members_status(session: AsyncSession, chat_id: int) -> bool:
    """Получает статус мута новых участников для группы"""
    try:
        from bot.services.redis_conn import redis
        
        # Проверяем Redis
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")
        
        if mute_enabled is not None:
            return mute_enabled == "1"
        
        # Если в Redis нет данных, проверяем в БД
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == chat_id)
        )
        settings = result.scalar_one_or_none()
        
        if settings and hasattr(settings, 'mute_new_members'):
            mute_enabled = "1" if settings.mute_new_members else "0"
            # Обновляем Redis
            await redis.set(f"group:{chat_id}:mute_new_members", mute_enabled)
            return settings.mute_new_members
        else:
            # По умолчанию выключено
            await redis.set(f"group:{chat_id}:mute_new_members", "0")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при получении статуса мута для группы {chat_id}: {e}")
        return False


async def toggle_visual_captcha(session: AsyncSession, chat_id: int) -> bool:
    """Переключает визуальную капчу и возвращает новый статус"""
    try:
        result = await session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            # Обновляем существующую запись
            new_status = not settings.is_visual_enabled
            await session.execute(
                update(CaptchaSettings)
                .where(CaptchaSettings.group_id == chat_id)
                .values(is_visual_enabled=new_status)
            )
            logger.info(f"Обновлен статус визуальной капчи для группы {chat_id}: {new_status}")
        else:
            # Создаем новую запись
            new_settings = CaptchaSettings(group_id=chat_id, is_visual_enabled=True)
            session.add(new_settings)
            new_status = True
            logger.info(f"Создана новая запись визуальной капчи для группы {chat_id}: {new_status}")

        await session.commit()
        return new_status

    except Exception as e:
        logger.error(f"Ошибка при переключении капчи: {e}")
        await session.rollback()
        return False


async def get_global_mute_status(session: AsyncSession) -> bool:
    """Получает статус глобального мута"""
    try:
        from bot.services.redis_conn import redis
        
        # Проверяем Redis
        global_mute_enabled = await redis.get("global_mute_enabled")
        
        if global_mute_enabled is not None:
            return global_mute_enabled == "1"
        
        # Если в Redis нет данных, проверяем в БД
        # Глобальная настройка хранится в первой записи ChatSettings с chat_id = 0
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == 0)
        )
        settings = result.scalar_one_or_none()
        
        if settings and hasattr(settings, 'global_mute_enabled'):
            global_mute_enabled = "1" if settings.global_mute_enabled else "0"
            # Обновляем Redis
            await redis.set("global_mute_enabled", global_mute_enabled)
            return settings.global_mute_enabled
        else:
            # По умолчанию выключено
            await redis.set("global_mute_enabled", "0")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при получении статуса глобального мута: {e}")
        return False


async def set_global_mute_status(session: AsyncSession, enabled: bool) -> bool:
    """Устанавливает статус глобального мута"""
    try:
        from bot.services.redis_conn import redis
        from sqlalchemy import insert
        from bot.database.models import Group
        
        # Сохраняем в Redis
        redis_value = "1" if enabled else "0"
        await redis.set("global_mute_enabled", redis_value)
        logger.info(f"🔍 [GLOBAL_MUTE_SET] Сохранено в Redis: {redis_value}")
        
        # Сначала создаем запись в таблице groups для глобальных настроек (если не существует)
        group_result = await session.execute(
            select(Group).where(Group.chat_id == 0)
        )
        global_group = group_result.scalar_one_or_none()
        
        if not global_group:
            await session.execute(
                insert(Group).values(
                    chat_id=0,
                    title="Global Settings"
                )
            )
            logger.info("✅ Создана запись глобальных настроек в таблице groups")
        
        # Теперь работаем с ChatSettings
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == 0)
        )
        settings = result.scalar_one_or_none()
        
        if settings:
            await session.execute(
                update(ChatSettings)
                .where(ChatSettings.chat_id == 0)
                .values(global_mute_enabled=enabled)
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=0,  # Специальный ID для глобальных настроек
                    global_mute_enabled=enabled,
                    enable_photo_filter=False,
                    admins_bypass_photo_filter=False,
                    photo_filter_mute_minutes=60,
                    mute_new_members=False,
                    auto_mute_scammers=True
                )
            )
        
        await session.commit()
        logger.info(f"✅ Глобальный мут {'включен' if enabled else 'выключен'}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при установке статуса глобального мута: {e}")
        await session.rollback()
        return False


async def toggle_global_mute(session: AsyncSession) -> bool:
    """Переключает статус глобального мута"""
    try:
        current_status = await get_global_mute_status(session)
        new_status = not current_status
        success = await set_global_mute_status(session, new_status)
        return new_status if success else current_status
    except Exception as e:
        logger.error(f"Ошибка при переключении глобального мута: {e}")
        return False