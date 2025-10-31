from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated, CallbackQuery
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.enums import ChatMemberStatus
from bot.services.new_member_requested_to_join_mute_logic import (
    get_mute_settings_menu,
    enable_mute_for_group,
    disable_mute_for_group,
    mute_unapproved_member_logic,
    mute_manually_approved_member_logic
)
from bot.services.bot_activity_journal.bot_activity_journal_logic import (
    log_new_member,
    log_user_left,
    log_user_kicked
)
import logging

logger = logging.getLogger(__name__)
new_member_requested_handler = Router()


@new_member_requested_handler.callback_query(F.data.startswith("new_member_requested_handler_settings"))
async def new_member_requested_handler_settings(callback: CallbackQuery):
    """Обработчик настроек мута новых участников"""
    try:
        user_id = callback.from_user.id
        logger.info(f"🔍 [MUTE_HANDLER] Вызов настроек мута для пользователя {user_id}")
        logger.info(f"🔍 [MUTE_HANDLER] Callback data: {callback.data}")
        
        # Проверяем есть ли chat_id в callback_data
        if ":" in callback.data:
            chat_id = int(callback.data.split(":")[-1])
            logger.info(f"🔍 [MUTE_HANDLER] Chat ID из callback: {chat_id}")
            # Сохраняем привязку в Redis для совместимости
            from bot.services.redis_conn import redis
            await redis.hset(f"user:{user_id}", "group_id", str(chat_id))
            await redis.expire(f"user:{user_id}", 30 * 60)
            logger.info(f"✅ [MUTE_HANDLER] Сохранена привязка user:{user_id} -> group:{chat_id}")
        
        await get_mute_settings_menu(callback)
        await callback.answer()  # Просто убираем "загрузку" с кнопки
    except Exception as e:
        logger.error(f"Ошибка в new_member_requested_handler_settings: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


# ✅ Мут через RESTRICTED статус (когда одобрение идёт через join_request)
# ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ТЕСТИРОВАНИЯ РУЧНОГО МУТА
# @new_member_requested_handler.chat_member(
#     F.chat.type.in_({"group", "supergroup"}),
#     ChatMemberUpdatedFilter(
#         member_status_changed=(None, ChatMemberStatus.RESTRICTED)
#     )
# )
# async def mute_handler(event: ChatMemberUpdated):
#     """Мут участников, не прошедших одобрение"""
#     await mute_unapproved_member(event)


# Добавляем общий обработчик для всех событий chat_member
# ✅ Отслеживаем вручную обновление chat_member после одобрения
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"})
)
async def manually_mute_on_approval(event: ChatMemberUpdated):
    """Мут вручную одобренных участников, если Telegram прислал событие"""
    print(f"🔍 [MANUAL_MUTE_HANDLER] ===== ОБРАБОТЧИК ВЫЗВАН =====")
    print(f"🔍 [MANUAL_MUTE_HANDLER] Пользователь: @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id} [{event.new_chat_member.user.id}]")
    print(f"🔍 [MANUAL_MUTE_HANDLER] Чат: {event.chat.title} [{event.chat.id}]")
    
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    
    print(f"🔍 [MANUAL_MUTE_HANDLER] Статус: {old_status} -> {new_status}")
    
    # Проверяем условие вручную
    if old_status in ("left", "kicked") and new_status == "member":
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ===== ОБРАБОТЧИК РУЧНОГО МУТА СРАБОТАЛ =====")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Пользователь: @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id} [{event.new_chat_member.user.id}]")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Чат: {event.chat.title} [{event.chat.id}]")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Статус: {old_status} -> {new_status}")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Время события: {event.date}")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Инвайтер: {event.invite_link}")
        
        # ЛОГИРУЕМ ВСТУПЛЕНИЕ ПОЛЬЗОВАТЕЛЯ В ГРУППУ
        try:
            from bot.database.session import get_session
            async with get_session() as session:
                await log_new_member(
                    bot=event.bot,
                    user=event.new_chat_member.user,
                    chat=event.chat,
                    invited_by=event.from_user if event.from_user.id != event.new_chat_member.user.id else None,
                    session=session
                )
        except Exception as log_error:
            logger.error(f"Ошибка при логировании вступления пользователя: {log_error}")
        
        try:
            # Проверяем и глобальный мут, и локальный мут
            from bot.services.new_member_requested_to_join_mute_logic import get_mute_new_members_status
            from bot.services.groups_settings_in_private_logic import get_global_mute_status
            from bot.database.session import get_session
            
            chat_id = event.chat.id
            
            # Получаем статус глобального мута
            async with get_session() as session:
                global_mute_enabled = await get_global_mute_status(session)
            
            # Получаем статус локального мута
            local_mute_enabled = await get_mute_new_members_status(chat_id)
            
            # Мут работает если включен глобально ИЛИ локально
            should_mute = global_mute_enabled or local_mute_enabled
            
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Статусы: global_mute={global_mute_enabled}, local_mute={local_mute_enabled}, should_mute={should_mute}")
            
            if should_mute:
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ✅ Мут включен (глобально: {global_mute_enabled}, локально: {local_mute_enabled}) - мутим пользователя @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id}")
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] 🚀 Вызываем mute_manually_approved_member_logic...")
                await mute_manually_approved_member_logic(event)
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ✅ Функция mute_manually_approved_member_logic завершена")
            else:
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ❌ Мут отключен (глобально: {global_mute_enabled}, локально: {local_mute_enabled}) - не мутим")
                
        except Exception as e:
            logger.error(f"🔍 [MANUAL_MUTE_HANDLER] 💥 MUTE ERROR (variant 2 - manual chat_member): {str(e)}")
            import traceback
            logger.error(f"🔍 [MANUAL_MUTE_HANDLER] 💥 Traceback: {traceback.format_exc()}")
    # ЛОГИРУЕМ ВЫХОД/УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ
    elif old_status == "member" and new_status in ("left", "kicked"):
        try:
            from bot.database.session import get_session
            async with get_session() as session:
                if new_status == "kicked":
                    # Удалён админом
                    await log_user_kicked(
                        bot=event.bot,
                        user=event.new_chat_member.user,
                        chat=event.chat,
                        kicked_by=event.from_user if event.from_user.id != event.new_chat_member.user.id else None,
                        session=session
                    )
                elif new_status == "left":
                    # Вышел сам
                    await log_user_left(
                        bot=event.bot,
                        user=event.new_chat_member.user,
                        chat=event.chat,
                        session=session
                    )
        except Exception as log_error:
            logger.error(f"Ошибка при логировании выхода пользователя: {log_error}")
    else:
        print(f"🔍 [MANUAL_MUTE_HANDLER] ❌ Условие не выполнено: {old_status} -> {new_status}")

# Добавляем обработчик для kicked -> member (альтернативный путь)
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(ChatMemberStatus.KICKED, ChatMemberStatus.MEMBER)
    )
)
async def manually_mute_on_approval_kicked_handler(event: ChatMemberUpdated):
    """Мут вручную одобренных участников (kicked -> member)"""
    logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] ===== ОБРАБОТЧИК РУЧНОГО МУТА (KICKED->MEMBER) =====")
    logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] Пользователь: @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id} [{event.new_chat_member.user.id}]")
    logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] Чат: {event.chat.title} [{event.chat.id}]")
    logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] Статус: {event.old_chat_member.status} -> {event.new_chat_member.status}")
    
    try:
        from bot.services.new_member_requested_to_join_mute_logic import get_mute_new_members_status
        from bot.services.groups_settings_in_private_logic import get_global_mute_status
        from bot.database.session import get_session
        
        chat_id = event.chat.id
        
        # Получаем статус глобального мута
        async with get_session() as session:
            global_mute_enabled = await get_global_mute_status(session)
        
        # Получаем статус локального мута
        local_mute_enabled = await get_mute_new_members_status(chat_id)
        
        # Мут работает если включен глобально ИЛИ локально
        should_mute = global_mute_enabled or local_mute_enabled
        
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] Статусы: global_mute={global_mute_enabled}, local_mute={local_mute_enabled}, should_mute={should_mute}")
        
        if should_mute:
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] ✅ Мут включен (глобально: {global_mute_enabled}, локально: {local_mute_enabled}) - мутим пользователя")
            await mute_manually_approved_member_logic(event)
        else:
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] ❌ Мут отключен (глобально: {global_mute_enabled}, локально: {local_mute_enabled}) - не мутим")
            
    except Exception as e:
        logger.error(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] 💥 MUTE ERROR: {str(e)}")
        import traceback
        logger.error(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] 💥 Traceback: {traceback.format_exc()}")


# ✅ Повторная проверка при изменении прав
# ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ТЕСТИРОВАНИЯ РУЧНОГО МУТА
# @new_member_requested_handler.chat_member(
#     F.chat.type.in_({"group", "supergroup"}),
#     ChatMemberUpdatedFilter(
#         member_status_changed=(ChatMemberStatus.RESTRICTED, ChatMemberStatus.MEMBER)
#     )
# )
# async def recheck_approved_member(event: ChatMemberUpdated):
#     """Повторно мутим, если одобренный пользователь всё ещё не подтверждён"""
#     await mute_unapproved_member(event)


# Добавляем обработчик для отслеживания ручного одобрения
@new_member_requested_handler.chat_join_request()
async def track_manual_approval(join_request):
    """Отслеживаем ручное одобрение заявок на вступление"""
    logger.info(f"🔍 [APPROVAL_TRACKER] ===== ОБРАБОТЧИК РУЧНОГО ОДОБРЕНИЯ =====")
    logger.info(f"🔍 [APPROVAL_TRACKER] Пользователь: @{join_request.from_user.username or join_request.from_user.first_name or join_request.from_user.id} [{join_request.from_user.id}]")
    logger.info(f"🔍 [APPROVAL_TRACKER] Чат: {join_request.chat.title} [{join_request.chat.id}]")
    logger.info(f"🔍 [APPROVAL_TRACKER] Время заявки: {join_request.date}")
    logger.info(f"🔍 [APPROVAL_TRACKER] Bio: {join_request.bio}")
    logger.info(f"🔍 [APPROVAL_TRACKER] Invite link: {join_request.invite_link}")

@new_member_requested_handler.callback_query(F.data == "mute_new_members:enable")
async def enable_mute_new_members(callback: CallbackQuery):
    """Включение мута новых участников"""
    try:
        await enable_mute_for_group(callback)
        await callback.answer("✅ Функция включена")
    except Exception as e:
        logger.error(f"Ошибка при включении мута: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


@new_member_requested_handler.callback_query(F.data == "mute_new_members:disable")
async def disable_mute_new_members(callback: CallbackQuery):
    """Выключение мута новых участников"""
    try:
        await disable_mute_for_group(callback)
        await callback.answer("❌ Функция выключена")
    except Exception as e:
        logger.error(f"Ошибка при выключении мута: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


async def mute_unapproved_member(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    try:
        await mute_unapproved_member_logic(event)
    except Exception as e:
        logger.error(f"💥 MUTE ERROR: {str(e)}")