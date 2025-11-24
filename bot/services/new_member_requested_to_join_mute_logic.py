# services/new_member_requested_to_join_mute_logic.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import ChatMemberUpdated, ChatPermissions
from aiogram.enums import ChatMemberStatus
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

from bot.services.redis_conn import redis
from bot.database.models import ChatSettings
from bot.database.session import get_session
from bot.services.scammer_tracker_logic import track_captcha_failure

logger = logging.getLogger(__name__)


async def get_mute_new_members_status(chat_id: int, session: AsyncSession = None) -> bool:
    """
    Получает статус мута новых участников для группы
    Сначала проверяет Redis, затем БД
    """
    try:
        # Проверяем Redis
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")
        logger.info(f"🔍 [MUTE_STATUS] Redis check для группы {chat_id}: {mute_enabled}")
        
        if mute_enabled is not None:
            result = mute_enabled == "1"
            logger.info(f"🔍 [MUTE_STATUS] Результат из Redis для группы {chat_id}: {result}")
            return result
        
        # Если в Redis нет данных, проверяем в БД
        if session:
            # Используем переданную сессию
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
        else:
            # Создаем новую сессию
            async with get_session() as new_session:
                result = await new_session.execute(
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


async def set_mute_new_members_status(chat_id: int, enabled: bool, session: AsyncSession = None) -> bool:
    """
    Устанавливает статус мута новых участников для группы
    Сохраняет в Redis и БД
    """
    try:
        # Сохраняем в Redis
        redis_value = "1" if enabled else "0"
        await redis.set(f"group:{chat_id}:mute_new_members", redis_value)
        logger.info(f"🔍 [MUTE_SET] Сохранено в Redis для группы {chat_id}: {redis_value}")
        
        # Сохраняем в БД
        if session:
            # Используем переданную сессию
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            )
            settings = result.scalar_one_or_none()
            
            if settings:
                await session.execute(
                    update(ChatSettings)
                    .where(ChatSettings.chat_id == chat_id)
                    .values(mute_new_members=enabled)
                )
            else:
                await session.execute(
                    insert(ChatSettings).values(
                        chat_id=chat_id,
                        mute_new_members=enabled,
                        enable_photo_filter=False,
                        admins_bypass_photo_filter=False,
                        photo_filter_mute_minutes=60
                    )
                )
        else:
            # Создаем новую сессию
            async with get_session() as new_session:
                result = await new_session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                settings = result.scalar_one_or_none()
                
                if settings:
                    await new_session.execute(
                        update(ChatSettings)
                        .where(ChatSettings.chat_id == chat_id)
                        .values(mute_new_members=enabled)
                    )
                else:
                    await new_session.execute(
                        insert(ChatSettings).values(
                            chat_id=chat_id,
                            mute_new_members=enabled,
                            enable_photo_filter=False,
                            admins_bypass_photo_filter=False,
                            photo_filter_mute_minutes=60
                        )
                    )
                await new_session.commit()
        
        logger.info(f"✅ Статус мута новых участников для группы {chat_id}: {'включен' if enabled else 'выключен'}")
        return True
            
    except Exception as e:
        logger.error(f"Ошибка при установке статуса мута для группы {chat_id}: {e}")
        return False


async def mute_unapproved_member(bot: Bot, event: ChatMemberUpdated) -> bool:
    """
    НЕ мутит участников автоматически - только логирует для отладки.
    Мут происходит только через manually_mute_on_approval когда админ вручную одобряет.
    """
    try:
        chat_id = event.chat.id
        user = event.new_chat_member.user
        
        # Проверяем, включен ли мут для этой группы
        mute_enabled = await get_mute_new_members_status(chat_id)
        
        if not mute_enabled:
            logger.debug(f"Мут для группы {chat_id} отключен, пропускаем")
            return False
        
        # Проверяем статусы для логирования
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        is_approved = getattr(event.new_chat_member, 'is_approved', True)
        
        logger.info(f"🔍 Chat member update: user={user.id}, old={old_status}, new={new_status}, approved={is_approved}")
        
        # НЕ мутим автоматически - только логируем
        logger.debug(f"Пользователь {user.id} не мутится автоматически - мут только через ручное одобрение админом")
        
        return False
        
    except Exception as e:
        logger.error(f"💥 Ошибка при обработке chat member update: {str(e)}")
        return False


# Удалена дублирующая функция - используется mute_manually_approved_member_logic ниже


async def create_mute_settings_keyboard(chat_id: int, session: AsyncSession = None) -> dict:
    """
    Создает клавиатуру для настроек мута новых участников
    """
    mute_enabled = await get_mute_new_members_status(chat_id, session)
    
    # Получаем статус глобального мута
    from bot.services.groups_settings_in_private_logic import get_global_mute_status
    global_mute_status = await get_global_mute_status(session)
    
    # Определяем общий статус мута (глобальный ИЛИ локальный)
    overall_mute_status = global_mute_status or mute_enabled
    
    # Создаем текст кнопок с учетом глобального мута
    if global_mute_status:
        enable_text = "✓ Включен 🌍 (глобально)"
        disable_text = "Отключить локально"
    else:
        enable_text = "✓ Включить" if mute_enabled else "Включить"
        disable_text = "✓ Выключить" if not mute_enabled else "Выключить"
    
    keyboard_data = {
        "buttons": [
            [
                {"text": enable_text, "callback_data": f"mute_settings:enable:{chat_id}"},
                {"text": disable_text, "callback_data": f"mute_settings:disable:{chat_id}"}
            ],
            [{"text": "« Назад", "callback_data": "back_to_groups"}]
        ],
        "status": overall_mute_status  # Возвращаем общий статус
    }
    
    return keyboard_data


async def get_mute_settings_text(status: bool = False, global_mute: bool = False) -> str:
    """
    Возвращает текст для настроек мута новых участников
    """
    if global_mute:
        status_text = "✅ Включено 🌍 (глобально)"
        description = "Мут включен глобально для всех групп. Локальные настройки не влияют."
    else:
        status_text = "✅ Включено" if status else "❌ Выключено"
        description = "Эта функция защищает вашу группу от спамеров."
    
    return (
        f"⚙️ Настройки мута для новых участников при ручном добавлении:\n\n"
        f"• Новые участники автоматически получают мут\n"
        f"• Мут действует до 10 лет\n"
        f"• Текущее состояние: {status_text}\n\n"
        f"{description}"
    )


async def get_mute_settings_menu(callback):
    """Получение меню настроек мута"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    user_id = callback.from_user.id
    logger.info(f"🔍 [MUTE_SERVICE] Получение настроек мута для пользователя {user_id}")
    
    # Проверяем все ключи в Redis для этого пользователя
    user_keys = await redis.hgetall(f"user:{user_id}")
    logger.info(f"🔍 [MUTE_SERVICE] Все ключи пользователя {user_id} в Redis: {user_keys}")
    
    group_id = await redis.hget(f"user:{user_id}", "group_id")
    logger.info(f"🔍 [MUTE_SERVICE] Group ID из Redis для пользователя {user_id}: {group_id}")

    if not group_id:
        logger.error(f"❌ [MUTE_SERVICE] НЕ НАЙДЕН group_id для пользователя {user_id}")
        logger.error(f"❌ [MUTE_SERVICE] Все ключи пользователя: {user_keys}")
        await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    # Проверяем текущее состояние мута для этой группы в Redis
    mute_enabled = await redis.get(f"group:{group_id}:mute_new_members")

    # Если в Redis нет данных, проверяем в БД
    if mute_enabled is None:
        async with get_session() as session:
            result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
            settings = result.scalar_one_or_none()

            if settings and hasattr(settings, 'mute_new_members'):
                mute_enabled = "1" if settings.mute_new_members else "0"
                # Обновляем Redis
                await redis.set(f"group:{group_id}:mute_new_members", mute_enabled)
            else:
                mute_enabled = "0"  # По умолчанию выключено

    status = "✅ Включено" if mute_enabled == "1" else "❌ Выключено"

    # Создаем клавиатуру с галочкой перед выбранным состоянием
    enable_text = "✓ Включить" if mute_enabled == "1" else "Включить"
    disable_text = "✓ Выключить" if mute_enabled != "1" else "Выключить"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=enable_text, callback_data="mute_new_members:enable"),
            InlineKeyboardButton(text=disable_text, callback_data="mute_new_members:disable")
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="back_to_groups")]
    ])

    # Используем edit_text вместо answer для редактирования текущего сообщения
    message_text = (
        f"⚙️ Настройки мута для новых участников при ручном добавлении:\n\n"
        f"• Новые участники автоматически получают мут\n"
        f"• Мут действует до 10 лет\n"
        f"• Текущее состояние: {status}\n\n"
        f"Эта функция защищает вашу группу от спамеров."
    )

    try:
        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении сообщения: {str(e)}")
        # Не вызываем callback.answer() здесь - это сделает handler


async def enable_mute_for_group(callback):
    """Включение мута для группы"""
    user_id = callback.from_user.id
    logger.info(f"🔍 [MUTE_SERVICE] Включение мута для пользователя {user_id}")
    
    # Проверяем все ключи в Redis для этого пользователя
    user_keys = await redis.hgetall(f"user:{user_id}")
    logger.info(f"🔍 [MUTE_SERVICE] Все ключи пользователя {user_id} в Redis: {user_keys}")
    
    group_id = await redis.hget(f"user:{user_id}", "group_id")
    logger.info(f"🔍 [MUTE_SERVICE] Group ID из Redis для пользователя {user_id}: {group_id}")

    if not group_id:
        logger.error(f"❌ [MUTE_SERVICE] НЕ НАЙДЕН group_id для пользователя {user_id} при включении мута")
        logger.error(f"❌ [MUTE_SERVICE] Все ключи пользователя: {user_keys}")
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    await redis.set(f"group:{group_id}:mute_new_members", "1")

    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    mute_new_members=True
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    mute_new_members=True,
                    enable_photo_filter=False,
                    admins_bypass_photo_filter=False,
                    photo_filter_mute_minutes=60
                )
            )

        await session.commit()
        logger.info(f"✅ Включен мут новых участников для группы {group_id}")

    # Не вызываем callback.answer() здесь - это сделает handler
    await get_mute_settings_menu(callback)


async def disable_mute_for_group(callback):
    """Выключение мута для группы"""
    user_id = callback.from_user.id
    logger.info(f"🔍 [MUTE_SERVICE] Выключение мута для пользователя {user_id}")
    
    # Проверяем все ключи в Redis для этого пользователя
    user_keys = await redis.hgetall(f"user:{user_id}")
    logger.info(f"🔍 [MUTE_SERVICE] Все ключи пользователя {user_id} в Redis: {user_keys}")
    
    group_id = await redis.hget(f"user:{user_id}", "group_id")
    logger.info(f"🔍 [MUTE_SERVICE] Group ID из Redis для пользователя {user_id}: {group_id}")

    if not group_id:
        logger.error(f"❌ [MUTE_SERVICE] НЕ НАЙДЕН group_id для пользователя {user_id} при выключении мута")
        logger.error(f"❌ [MUTE_SERVICE] Все ключи пользователя: {user_keys}")
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    # Выключаем функцию мута для группы в Redis
    await redis.set(f"group:{group_id}:mute_new_members", "0")

    # Сохраняем настройки в БД
    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    mute_new_members=False
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    mute_new_members=False,
                    enable_photo_filter=False,
                    admins_bypass_photo_filter=False,
                    photo_filter_mute_minutes=60
                )
            )

        await session.commit()
        logger.info(f"❌ Выключен мут новых участников для группы {group_id}")

    # Не вызываем callback.answer() здесь - это сделает handler
    await get_mute_settings_menu(callback)


async def mute_unapproved_member_logic(event):
    """Логика мута участников, не прошедших одобрение"""
    from aiogram.types import ChatPermissions
    from datetime import datetime, timedelta
    import asyncio
    
    try:
        if getattr(event.new_chat_member, 'is_approved', True):
            return

        # Проверяем, включен ли мут для этой группы
        chat_id = event.chat.id
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")

        # Если в Redis нет данных, проверяем в БД
        if mute_enabled is None:
            async with get_session() as session:
                result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
                settings = result.scalar_one_or_none()

                if settings and hasattr(settings, 'mute_new_members'):
                    mute_enabled = "1" if settings.mute_new_members else "0"
                    await redis.set(f"group:{chat_id}:mute_new_members", mute_enabled)
                else:
                    mute_enabled = "0"  # по умолчанию отключено

        if mute_enabled != "1":
            logger.debug(f"Мут для группы {chat_id} отключен, пропускаем")
            return

        user = event.new_chat_member.user

        await event.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=datetime.now() + timedelta(days=366 * 10)  # 10 лет
        )

        await asyncio.sleep(1)

        try:
            # Проверяем настройку системных сообщений перед отправкой
            should_announce = True
            try:
                async with get_session() as announce_session:
                    result = await announce_session.execute(
                        select(ChatSettings).where(ChatSettings.chat_id == event.chat.id)
                    )
                    settings = result.scalar_one_or_none()
                    if settings:
                        should_announce = settings.system_mute_announcements_enabled
            except Exception as settings_error:
                logger.error(f"Ошибка при проверке настроек системных сообщений: {settings_error}")

            if should_announce:
                await event.bot.send_message(
                    chat_id=event.chat.id,
                    text=f"🚫 Спамер @{user.username or user.id} был автоматически замьючен."
                )
            logger.info(f"Пользователь @{user.username or user.id} (ID: {user.id}) замьючен в группе {event.chat.id}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение в чат {event.chat.id}: {str(e)}")

    except Exception as e:
        logger.error(f"💥 MUTE ERROR: {str(e)}")


async def mute_manually_approved_member_logic(event):
    """Логика мута вручную одобренных участников"""
    from aiogram.types import ChatPermissions
    from datetime import datetime, timedelta
    import asyncio
    
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        user = event.new_chat_member.user
        chat = event.chat

        logger.info(f"🔍 [MUTE_LOGIC] ===== НАЧАЛО ФУНКЦИИ mute_manually_approved_member_logic =====")
        logger.info(f"🔍 [MUTE_LOGIC] Пользователь: @{user.username or user.first_name or user.id} [{user.id}]")
        logger.info(f"🔍 [MUTE_LOGIC] Чат: {chat.title} [{chat.id}]")
        logger.info(f"🔍 [MUTE_LOGIC] Статус: {old_status} -> {new_status}")
        logger.info(f"🔍 [MUTE_LOGIC] Время события: {event.date}")

        # Проверяем: это ручное одобрение?
        # Сценарий 1: left/kicked -> member (классический)
        # Сценарий 2: restricted -> restricted, но права изменились
        # Сценарий 3: restricted -> member
        is_manual_approval = False

        if old_status in ("left", "kicked") and new_status == "member":
            is_manual_approval = True
            logger.info(f"🔍 [MUTE_LOGIC] ✅ Сценарий 1: {old_status} -> member")
        elif old_status == "restricted" and new_status == "restricted":
            old_can_send = getattr(event.old_chat_member, 'can_send_messages', False)
            new_can_send = getattr(event.new_chat_member, 'can_send_messages', False)
            if not old_can_send and new_can_send:
                is_manual_approval = True
                logger.info(f"🔍 [MUTE_LOGIC] ✅ Сценарий 2: restricted -> restricted, can_send: {old_can_send} -> {new_can_send}")
        elif old_status == "restricted" and new_status == "member":
            is_manual_approval = True
            logger.info(f"🔍 [MUTE_LOGIC] ✅ Сценарий 3: restricted -> member")

        if is_manual_approval:
            logger.info(f"🔍 [MUTE_LOGIC] ✅ Условие выполнено: ручное одобрение")

            # Проверяем глобальную настройку мута (мастер-переключатель)
            global_mute_enabled = await redis.get("global_mute_enabled")
            logger.info(f"🔍 [MUTE_LOGIC] Глобальный мут: {global_mute_enabled}")

            # Глобальный мут — мастер-переключатель для ручного мута
            # Включен = мутим при ручном одобрении, Выключен = не мутим
            # Локальные настройки НЕ учитываются
            should_mute = (global_mute_enabled == "1")

            if not should_mute:
                logger.info(f"🔍 [MUTE_LOGIC] ❌ Глобальный мут выключен ({global_mute_enabled}), пропускаем")
                return

            # БАГ #1 и #3: Проверяем, что это именно ручное одобрение админом, а не автоматическое через капчу
            # Если пользователь прошел капчу - это автоматическое одобрение, не мутим (независимо от TTL)
            captcha_passed = await redis.get(f"captcha_passed:{user.id}:{chat.id}")
            captcha_ttl = await redis.ttl(f"captcha_passed:{user.id}:{chat.id}")
            
            logger.info(f"🔍 [MUTE_LOGIC] Проверка капчи: passed={captcha_passed}, ttl={captcha_ttl}")
            
            # БАГ #1: Если капча пройдена, не мутим вообще (независимо от давности)
            if captcha_passed:
                logger.info(f"🔍 [MUTE_LOGIC] ✅ Пользователь {user.id} прошел капчу - это автоматическое одобрение, ручной мут не применяется")
                return
            
            logger.info(f"🔍 [MUTE_LOGIC] 🌍 Глобальный мут включен - мутим пользователя {user.id} (ручное одобрение админом)")
            logger.info(f"🔍 [MUTE_LOGIC] 🚀 Все проверки пройдены, начинаем мут пользователя @{user.username or user.id}")
            logger.info(f"🔍 [MUTE_LOGIC] 📋 Дополнительная диагностика:")
            logger.info(f"🔍 [MUTE_LOGIC]    - user.id: {user.id}")
            logger.info(f"🔍 [MUTE_LOGIC]    - chat.id: {chat.id}")
            logger.info(f"🔍 [MUTE_LOGIC]    - old_status: {old_status}")
            logger.info(f"🔍 [MUTE_LOGIC]    - new_status: {new_status}")
            logger.info(f"🔍 [MUTE_LOGIC]    - event.date: {event.date}")

            try:
                await event.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    ),
                    until_date=datetime.now() + timedelta(days=366 * 10)
                )
                logger.info(f"🔍 [MUTE_LOGIC] ✅ API вызов restrict_chat_member выполнен успешно")

                await asyncio.sleep(1)
                logger.info(f"🔍 [MUTE_LOGIC] ✅ Пользователь @{user.username or user.id} был замьючен после ручного одобрения")
                
            except Exception as api_error:
                logger.error(f"🔍 [MUTE_LOGIC] 💥 Ошибка API при муте: {api_error}")
                raise
                
        else:
            logger.info(f"🔍 [MUTE_LOGIC] ❌ Условие не выполнено: old={old_status}, new={new_status}")

    except Exception as e:
        logger.error(f"🔍 [MUTE_LOGIC] 💥 MUTE ERROR: {str(e)}")
        import traceback
        logger.error(f"🔍 [MUTE_LOGIC] 💥 Traceback: {traceback.format_exc()}")
