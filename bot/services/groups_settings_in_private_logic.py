from typing import List, Optional
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from bot.database.models import Group, UserGroup, CaptchaSettings, ChatSettings
import logging

logger = logging.getLogger(__name__)


async def _ensure_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.commit()
        result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == chat_id)
        )
        settings = result.scalar_one()
    return settings


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


PERMISSION_ATTRIBUTE_MAP = {
    'restrict_members': 'can_restrict_members',
    'change_info': 'can_change_info',
    'delete_messages': 'can_delete_messages',
    'post_messages': 'can_post_messages',
    'invite_users': 'can_invite_users',
    'pin_messages': 'can_pin_messages',
}


async def _check_permissions_via_admin_list(
    bot: Bot,
    chat_id: int,
    required_permission: str,
) -> Optional[bool]:
    """
    Проверяет право у анонимных админов через get_chat_administrators.
    Возвращает True/False если удалось определить, None если нет доступа.
    """
    attr_name = PERMISSION_ATTRIBUTE_MAP.get(required_permission)
    if not attr_name:
        logger.warning(f"⚠️ Неизвестное разрешение: {required_permission}")
        return False

    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramAPIError as e:
        logger.error(f"Ошибка получения администраторов чата {chat_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка получения администраторов чата {chat_id}: {e}")
        return None

    for admin in admins:
        status = getattr(admin, 'status', '')
        if status == 'creator':
            logger.info(f"✅ Создатель найден в get_chat_administrators для {chat_id}")
            return True
        if status != 'administrator':
            continue

        has_perm = getattr(admin, attr_name, False)
        if not has_perm:
            continue

        if getattr(admin, 'is_anonymous', False):
            logger.info(f"✅ Найден анонимный админ с правом '{required_permission}' в чате {chat_id}")
            return True

    logger.warning(f"❌ Не найден анонимный админ с правом '{required_permission}' в чате {chat_id}")
    return False


async def check_granular_permissions(
    bot: Bot,
    user_id: int,
    chat_id: int,
    required_permission: str,
    session: AsyncSession = None,
    sender_chat_id: int = None
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
        
        # 2. Обработка анонимных админов (sender_chat_id — канал/группа)
        if sender_chat_id:
            try:
                member = await bot.get_chat_member(chat_id, sender_chat_id)

                if member.status == "creator":
                    logger.info(f"✅ Анонимный админ (канал {sender_chat_id}) — creator группы {chat_id}")
                    return True

                if member.status == "administrator":
                    attr = PERMISSION_ATTRIBUTE_MAP.get(required_permission)
                    if not attr:
                        logger.warning(f"⚠️ Неизвестное разрешение: {required_permission}")
                        return False
                    allowed = getattr(member, attr, False)
                    if allowed:
                        logger.info(f"✅ Анонимный админ (канал {sender_chat_id}) имеет право '{required_permission}'")
                    else:
                        logger.warning(f"❌ Анонимный админ (канал {sender_chat_id}) НЕ имеет права '{required_permission}'")
                    return allowed

                logger.warning(f"❌ Sender_chat_id={sender_chat_id} не является администратором в чате {chat_id}")
            except TelegramAPIError as e:
                # Если Telegram не даёт проверять sender_chat_id напрямую — пробуем через список админов
                if "invalid user_id" in str(e).lower():
                    logger.info(f"⚠️ Telegram не позволяет проверить sender_chat_id={sender_chat_id}, fallback на список админов")
                    fallback = await _check_permissions_via_admin_list(bot, chat_id, required_permission)
                    if fallback is not None:
                        return fallback
                logger.error(f"Ошибка при проверке прав анонимного админа (sender_chat_id={sender_chat_id}): {e}")
                return False
            except Exception as e:
                logger.error(f"Ошибка при проверке sender_chat_id={sender_chat_id}: {e}")
                fallback = await _check_permissions_via_admin_list(bot, chat_id, required_permission)
                if fallback is not None:
                    return fallback
                return False

        # 3. Если user_id не задан и нет sender_chat_id — нет данных для проверки
        if not user_id:
            logger.warning(f"❌ Нет user_id/sender_chat_id для проверки прав в группе {chat_id}")
            return False

        # 4. Получаем информацию о члене группы через Telegram API
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except TelegramAPIError as e:
            logger.error(f"Ошибка при получении члена группы {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неизвестная ошибка при получении члена группы {chat_id}: {e}")
            return False
        
        # 5. Если пользователь - creator, разрешаем всё
        if member.status == "creator":
            logger.info(f"✅ Пользователь {user_id} - creator группы {chat_id}, разрешаем доступ")
            return True
        
        # 6. Если пользователь не админ, отказываем
        if member.status != "administrator":
            logger.warning(f"❌ Пользователь {user_id} не является администратором в группе {chat_id}")
            return False
        
        attr = PERMISSION_ATTRIBUTE_MAP.get(required_permission)
        if not attr:
            logger.warning(f"⚠️ Неизвестное разрешение: {required_permission}")
            return False
        
        has_permission = getattr(member, attr, False)
        
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


async def get_reaction_mute_settings(session: AsyncSession, chat_id: int) -> tuple[bool, bool]:
    settings = await _ensure_chat_settings(session, chat_id)
    return settings.reaction_mute_enabled, settings.reaction_mute_announce_enabled


async def set_reaction_mute_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.reaction_mute_enabled = enabled
    await session.commit()
    return settings.reaction_mute_enabled


async def set_reaction_mute_announce_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.reaction_mute_announce_enabled = enabled
    await session.commit()
    return settings.reaction_mute_announce_enabled


async def get_captcha_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    return await _ensure_chat_settings(session, chat_id)


async def set_visual_captcha_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    from bot.services.visual_captcha_logic import set_visual_captcha_status, get_visual_captcha_status

    await set_visual_captcha_status(chat_id, enabled)
    await session.commit()
    return await get_visual_captcha_status(chat_id)


async def set_captcha_join_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_join_enabled = enabled
    await session.commit()
    return settings.captcha_join_enabled


async def set_captcha_invite_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_invite_enabled = enabled
    await session.commit()
    return settings.captcha_invite_enabled


async def set_captcha_timeout(session: AsyncSession, chat_id: int, seconds: int) -> int:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_timeout_seconds = seconds
    await session.commit()
    return settings.captcha_timeout_seconds


async def set_captcha_message_ttl(session: AsyncSession, chat_id: int, seconds: int) -> int:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_message_ttl_seconds = seconds
    await session.commit()
    return settings.captcha_message_ttl_seconds


async def set_captcha_flood_threshold(session: AsyncSession, chat_id: int, threshold: int) -> int:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_flood_threshold = threshold
    await session.commit()
    return settings.captcha_flood_threshold


async def set_captcha_flood_window(session: AsyncSession, chat_id: int, seconds: int) -> int:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_flood_window_seconds = seconds
    await session.commit()
    return settings.captcha_flood_window_seconds


async def set_captcha_flood_action(session: AsyncSession, chat_id: int, action: str) -> str:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.captcha_flood_action = action
    await session.commit()
    return settings.captcha_flood_action


async def set_system_mute_announcements_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    settings = await _ensure_chat_settings(session, chat_id)
    settings.system_mute_announcements_enabled = enabled
    await session.commit()
    return settings.system_mute_announcements_enabled


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
        
        # КРИТИЧЕСКИЙ ФИКС: Обновляем Redis после изменения в БД
        # Это гарантирует, что get_visual_captcha_status() вернет актуальное значение
        # БЕЗ этого фикса Redis кэш остается устаревшим и капча не отправляется при rejoin
        from bot.services.visual_captcha_logic import set_visual_captcha_status
        await set_visual_captcha_status(chat_id, new_status)
        logger.info(f"✅ Redis обновлен для группы {chat_id}: visual_captcha_enabled={new_status}")
        
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