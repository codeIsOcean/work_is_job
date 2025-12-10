# group_events.py
import logging
from aiogram import Router, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatJoinRequest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from bot.database.models import Group, User, GroupUsers, UserGroup, ChatSettings
from bot.services.visual_captcha_logic import (
    get_visual_captcha_status,
    generate_visual_captcha,
    save_captcha_data,
    create_deeplink_for_captcha,
    get_captcha_keyboard,
    is_visual_captcha_enabled
)

logger = logging.getLogger(__name__)

group_events_router = Router()
bot_activity_handlers_router = group_events_router  # Алиас для роутера группы


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

@bot_activity_handlers_router.chat_join_request()
async def handle_join_request(chat_join_request: ChatJoinRequest, session: AsyncSession):
    """Обработчик запроса на вступление в группу"""
    chat_id = chat_join_request.chat.id
    user = chat_join_request.from_user

    logger.info(f"📨 Получен запрос на вступление от пользователя {user.id} в группу {chat_id}")

    try:
        # Проверяем активна ли визуальная капча
        if not await is_visual_captcha_enabled(session, chat_id):
            logger.info(f"⛔ Визуальная капча не активирована в группе {chat_id}, выходим из handle_join_request")
            return

        logger.info(f"✅ Визуальная капча активирована в группе {chat_id}, отправляем капчу пользователю")

        # НЕ ГЕНЕРИРУЕМ КАПЧУ СРАЗУ - только создаем кнопку
        group_name = str(chat_id)

        # Создаем deep link
        deep_link = await create_deeplink_for_captcha(chat_join_request.bot, group_name)

        # Создаем клавиатуру
        keyboard = await get_captcha_keyboard(deep_link)

        # Формируем текст с кликабельным названием группы
        chat = chat_join_request.chat
        group_title = (
            chat.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if chat.title else "группа"
        )
        logger.info(f"📝 Название группы для сообщения: '{group_title}' (исходное: '{chat.title}')")

        # Создаем ссылку на группу
        group_link = None
        if chat.username:
            # Публичная группа - используем username
            group_link = f"https://t.me/{chat.username}"
        else:
            # Приватная группа - создаем invite link
            try:
                invite_link = await chat_join_request.bot.create_chat_invite_link(
                    chat_id=chat.id,
                    creates_join_request=False
                )
                # Преобразуем invite_link.invite_link в строку явно
                group_link = str(invite_link.invite_link) if invite_link.invite_link else None
            except Exception as e:
                logger.warning(f"Не удалось создать invite link для группы {chat.id}: {e}")

        # Формируем сообщение с кликабельным названием группы
        if group_link:
            message_text = (
                f"🔒 Для вступления в группу <a href='{group_link}'>{group_title}</a> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )
        else:
            # Fallback если не удалось создать ссылку
            message_text = (
                f"🔒 Для вступления в группу <b>{group_title}</b> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )

        # Отправляем ТОЛЬКО текст с кнопкой (БЕЗ ФОТО)
        try:
            msg = await chat_join_request.bot.send_message(
                chat_id=user.id,
                text=message_text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"📤 Капча отправлена пользователю {user.id}")
            
            # Удаляем сообщение через 2-3 минуты (150 секунд = 2.5 минуты)
            import asyncio
            from bot.services.visual_captcha_logic import delete_message_after_delay
            asyncio.create_task(delete_message_after_delay(chat_join_request.bot, user.id, msg.message_id, 150))
        except Exception as send_error:
            error_msg = str(send_error)
            if "bot can't initiate conversation with a user" in error_msg:
                logger.warning(f"⚠️ Пользователь {user.id} не начал диалог с ботом. Запрос на вступление будет отклонен.")
            elif "bot was blocked by the user" in error_msg:
                logger.warning(f"⚠️ Пользователь {user.id} заблокировал бота. Запрос на вступление будет отклонен.")
            else:
                logger.warning(f"⚠️ Не удалось отправить капчу пользователю {user.id}: {send_error}")
            # Пользователь заблокировал бота или не начал диалог
            return
        
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса на вступление: {e}")
        await session.rollback()
        raise
