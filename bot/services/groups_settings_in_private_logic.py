from typing import List, Optional
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from bot.database.models import Group, UserGroup, CaptchaSettings, ChatSettings
import logging
import inspect

logger = logging.getLogger(__name__)


async def _maybe_await(result):
    """Helper: supports both real AsyncSession and MagicMock in tests."""
    if inspect.isawaitable(result):
        return await result
    return result


async def _ensure_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    raw = session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    result = await _maybe_await(raw)
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        commit_call = session.commit()
        await _maybe_await(commit_call)
        result = await _maybe_await(
            session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
        )
        settings = result.scalar_one()
    return settings


async def _ensure_user_group_exists(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    user_info=None
) -> None:
    """Создаёт или обновляет запись UserGroup для админа.

    Решает проблему "исчезающих групп" - когда UserGroup был удалён,
    но пользователь снова стал админом.

    КРИТИЧЕСКИЙ ФИКС: Если user_info=None и пользователя нет в БД,
    создаём User с минимальными данными (только user_id).
    Это гарантирует что UserGroup ВСЕГДА создастся.

    Args:
        session: AsyncSession для БД
        user_id: ID пользователя Telegram
        chat_id: ID группы
        user_info: Объект aiogram User (опционально, для создания записи User)
    """
    from bot.database.models import User as DbUser

    try:
        # Проверяем, существует ли UserGroup
        result = await session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Связь уже есть, ничего не делаем
            return

        # Связи нет - нужно создать
        # Сначала проверяем, есть ли пользователь в таблице User (для FK constraint)
        user_result = await session.execute(
            select(DbUser).where(DbUser.user_id == user_id)
        )
        db_user = user_result.scalar_one_or_none()

        if not db_user:
            # КРИТИЧЕСКИЙ ФИКС: Создаём пользователя с минимальными данными
            # даже если user_info=None. Это гарантирует что UserGroup создастся!
            if user_info:
                full_name = f"{user_info.first_name or ''} {user_info.last_name or ''}".strip()
                username = getattr(user_info, 'username', None)
                is_bot = getattr(user_info, 'is_bot', False)
            else:
                # Минимальные данные - только user_id
                full_name = f"User_{user_id}"
                username = None
                is_bot = False

            db_user = DbUser(
                user_id=user_id,
                username=username,
                full_name=full_name,
                is_bot=is_bot
            )
            session.add(db_user)
            await session.flush()
            logger.info(f"✅ [AUTO_RESTORE] Создан пользователь {user_id} в БД (user_info={'есть' if user_info else 'нет'})")

        # Создаём UserGroup
        session.add(UserGroup(user_id=user_id, group_id=chat_id))
        await session.commit()
        logger.info(f"✅ [AUTO_RESTORE] Восстановлена связь админа {user_id} с группой {chat_id}")

    except Exception as e:
        logger.error(f"❌ [AUTO_RESTORE] Ошибка при восстановлении UserGroup для {user_id} в {chat_id}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def get_admin_groups(user_id: int, session: AsyncSession, bot: Bot = None) -> List[Group]:
    """Возвращает список групп, где пользователь сейчас является админом.
    Если bot не передан — возвращает группы по данным БД без онлайн-проверки.

    ВАЖНО: Функция проверяет ВСЕ группы где бот состоит (не только из UserGroup),
    чтобы восстановить связи если пользователь снова стал админом.
    """
    try:
        # ФИКС: Получаем ВСЕ группы из БД (где бот состоит), а не только из UserGroup
        # Это решает проблему "исчезающих групп" когда UserGroup был удалён,
        # но пользователь снова стал админом
        all_groups_query = select(Group).where(Group.chat_id != 0)  # исключаем глобальные настройки
        all_groups_result = await session.execute(all_groups_query)
        all_groups = all_groups_result.scalars().all()

        logger.info(f"Найдено {len(all_groups)} групп в БД для проверки")

        if not all_groups:
            return []

        if not bot:
            # Старое поведение: без онлайн-проверки, возвращаем только по UserGroup
            user_groups_query = select(UserGroup).where(UserGroup.user_id == user_id)
            user_groups_result = await session.execute(user_groups_query)
            user_groups = user_groups_result.scalars().all()
            group_ids = [ug.group_id for ug in user_groups]
            logger.warning("get_admin_groups: bot не передан, возврат групп без онлайн-проверки")
            return [g for g in all_groups if g.chat_id in group_ids]

        valid_groups: List[Group] = []

        # Итерируемся по ВСЕМ группам в БД (не только по UserGroup)
        for group in all_groups:
            try:
                # Проверяем, что бот в группе
                try:
                    bot_member = await bot.get_chat_member(group.chat_id, bot.id)
                    if bot_member.status not in ("member", "administrator", "creator"):
                        logger.info(f"Бот не состоит в группе {group.chat_id}, пропускаем")
                        continue
                except Exception as e:
                    error_str = str(e).lower()
                    # ФИКС: Удаляем связь ТОЛЬКО если группа/пользователь не найдены
                    # При других ошибках (таймаут, rate limit) - просто пропускаем
                    if "chat not found" in error_str or "user not found" in error_str or "kicked" in error_str:
                        logger.warning(f"Группа {group.chat_id} недоступна ({e}), чистим связь")
                        await session.execute(
                            delete(UserGroup).where(
                                UserGroup.user_id == user_id,
                                UserGroup.group_id == group.chat_id,
                            )
                        )
                        await session.commit()
                    else:
                        # При временных ошибках (таймаут, rate limit) - НЕ удаляем, но восстанавливаем UserGroup
                        logger.warning(f"Временная ошибка при проверке бота в группе {group.chat_id}: {e}")
                        # Доверяем данным из БД при временных ошибках
                        # ФИКС: Восстанавливаем UserGroup чтобы группа не пропала при следующем вызове
                        await _ensure_user_group_exists(session, user_id, group.chat_id, None)
                        valid_groups.append(group)
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
                    error_str = str(e).lower()
                    # ФИКС: Удаляем связь ТОЛЬКО если пользователь точно не в группе
                    if "user not found" in error_str or "kicked" in error_str:
                        logger.warning(f"Пользователь {user_id} не найден в группе {group.chat_id}, чистим связь")
                        await session.execute(
                            delete(UserGroup).where(
                                UserGroup.user_id == user_id,
                                UserGroup.group_id == group.chat_id,
                            )
                        )
                        await session.commit()
                    else:
                        # При временных ошибках - доверяем БД, но восстанавливаем UserGroup
                        logger.warning(f"Временная ошибка при проверке прав {user_id} в группе {group.chat_id}: {e}")
                        # ФИКС: Восстанавливаем UserGroup чтобы группа не пропала при следующем вызове
                        await _ensure_user_group_exists(session, user_id, group.chat_id, None)
                        valid_groups.append(group)
                    continue

                # ФИКС: Восстанавливаем UserGroup если пользователь снова админ
                # Это решает проблему "исчезающих групп"
                await _ensure_user_group_exists(session, user_id, group.chat_id, user_member.user)
                valid_groups.append(group)
            except Exception as e:
                # КРИТИЧЕСКИЙ ФИКС: При неожиданных ошибках - доверяем БД и добавляем группу!
                # Раньше группа просто терялась при любом exception
                logger.error(f"Ошибка обработки группы {group.chat_id}: {e}, но доверяем БД")
                try:
                    await _ensure_user_group_exists(session, user_id, group.chat_id, None)
                    valid_groups.append(group)
                except Exception:
                    pass
                continue

        return valid_groups

    except Exception as e:
        logger.error(f"Ошибка при получении групп пользователя {user_id}: {e}")
        # КРИТИЧЕСКИЙ ФИКС: При глобальной ошибке - возвращаем кэш из UserGroup
        # Раньше возвращался пустой список и все группы терялись
        try:
            user_groups_query = select(UserGroup).where(UserGroup.user_id == user_id)
            user_groups_result = await session.execute(user_groups_query)
            user_groups = user_groups_result.scalars().all()
            group_ids = [ug.group_id for ug in user_groups]

            all_groups_query = select(Group).where(Group.chat_id.in_(group_ids))
            all_groups_result = await session.execute(all_groups_query)
            cached_groups = all_groups_result.scalars().all()

            logger.warning(f"⚠️ Возвращаем {len(cached_groups)} групп из кэша (БД) после ошибки")
            return cached_groups
        except Exception as fallback_error:
            logger.error(f"❌ Даже fallback не сработал: {fallback_error}")
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
    """Переключает визуальную капчу и возвращает новый статус.

    В проде session — это AsyncSession, в тестах может приходить MagicMock.
    Поэтому аккуратно работаем как с awaitable, так и с синхронными заглушками.
    """
    try:
        raw_result = session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
        )
        if inspect.isawaitable(raw_result):
            raw_result = await raw_result
        settings = raw_result.scalar_one_or_none()

        if settings:
            # Обновляем существующую запись
            new_status = not settings.is_visual_enabled
            update_call = session.execute(
                update(CaptchaSettings)
                .where(CaptchaSettings.group_id == chat_id)
                .values(is_visual_enabled=new_status)
            )
            if inspect.isawaitable(update_call):
                await update_call
            logger.info(f"Обновлен статус визуальной капчи для группы {chat_id}: {new_status}")
        else:
            # Создаем новую запись
            new_settings = CaptchaSettings(group_id=chat_id, is_visual_enabled=True)
            session.add(new_settings)
            new_status = True
            logger.info(f"Создана новая запись визуальной капчи для группы {chat_id}: {new_status}")

        commit_call = session.commit()
        if inspect.isawaitable(commit_call):
            await commit_call
        
        # КРИТИЧЕСКИЙ ФИКС: Обновляем Redis после изменения в БД
        # Это гарантирует, что get_visual_captcha_status() вернет актуальное значение
        # БЕЗ этого фикса Redis кэш остается устаревшим и капча не отправляется при rejoin
        from bot.services.visual_captcha_logic import set_visual_captcha_status
        set_call = set_visual_captcha_status(chat_id, new_status)
        if inspect.isawaitable(set_call):
            await set_call
        logger.info(f"✅ Redis обновлен для группы {chat_id}: visual_captcha_enabled={new_status}")
        
        return new_status

    except Exception as e:
        logger.error(f"Ошибка при переключении капчи: {e}")
        rollback_call = getattr(session, "rollback", None)
        if rollback_call is not None:
            try:
                rc = rollback_call()
                if inspect.isawaitable(rc):
                    await rc
            except Exception:
                # В тестах не роняемся из-за mock rollback
                pass
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