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

# ═══════════════════════════════════════════════════════════════════════
# ANTI-RAID: Импорты для проверки имени по паттернам и трекинга входов
# Вызываем здесь как fallback, т.к. не все группы получают new_chat_members
# ═══════════════════════════════════════════════════════════════════════
from bot.services.antiraid import (
    check_name_against_patterns,  # Проверка имени по паттернам
    apply_name_pattern_action,    # Применение действия (бан/кик/мут)
    send_name_pattern_journal,    # Отправка в журнал
)
from bot.handlers.antiraid import (
    track_join_event,   # Трекинг входа/выхода (join_exit abuse)
    track_mass_join,    # Детекция рейда (mass join)
    track_mass_invite,  # Детекция массовых инвайтов
)

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

    # Проверяем: это ручное одобрение админом?
    # Сценарий 1: left/kicked -> member (классический)
    # Сценарий 2: restricted -> restricted НО права изменились (админ снял ограничения)
    # Сценарий 3: restricted -> member (админ снял все ограничения)

    is_manual_approval = False

    # Сценарий 1: классическое вступление
    if old_status in ("left", "kicked") and new_status == "member":
        is_manual_approval = True
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Сценарий 1: {old_status} -> member")

    # Сценарий 2: restricted -> restricted, но права изменились (админ вручную одобрил)
    elif old_status == "restricted" and new_status == "restricted":
        old_can_send = getattr(event.old_chat_member, 'can_send_messages', False)
        new_can_send = getattr(event.new_chat_member, 'can_send_messages', False)

        # Если раньше не мог писать, а теперь может - это одобрение
        if not old_can_send and new_can_send:
            is_manual_approval = True
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Сценарий 2: restricted -> restricted, но can_send_messages: {old_can_send} -> {new_can_send}")

    # Сценарий 3: restricted -> member (полное снятие ограничений)
    elif old_status == "restricted" and new_status == "member":
        is_manual_approval = True
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Сценарий 3: restricted -> member")

    if is_manual_approval:
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ===== ОБРАБОТЧИК РУЧНОГО МУТА СРАБОТАЛ =====")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Пользователь: @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id} [{event.new_chat_member.user.id}]")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Чат: {event.chat.title} [{event.chat.id}]")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Статус: {old_status} -> {new_status}")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Время события: {event.date}")
        logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Инвайтер: {event.invite_link}")
        
        # ЛОГИРУЕМ ВСТУПЛЕНИЕ ПОЛЬЗОВАТЕЛЯ В ГРУППУ (с информацией о возрасте)
        try:
            from bot.database.session import get_session
            from bot.services.enhanced_profile_analyzer import enhanced_profile_analyzer

            user = event.new_chat_member.user
            user_data = {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }

            # Получаем информацию о возрасте аккаунта
            age_info = None
            try:
                analysis = await enhanced_profile_analyzer.analyze_user_profile_enhanced(user_data, event.bot)
                photos_analysis = analysis.get('photos_analysis', {})
                age_analysis = analysis.get('age_analysis', {})

                age_info = {
                    'photo_age_days': photos_analysis.get('oldest_photo_days'),
                    'photos_count': photos_analysis.get('photos_count', 0),
                    'estimated_age_days': age_analysis.get('age_days'),
                }
                logger.info(f"📊 [AGE_INFO] Пользователь {user.id}: фото={age_info['photo_age_days']} дн., прибл.={age_info['estimated_age_days']} дн.")
            except Exception as age_error:
                logger.warning(f"Не удалось получить информацию о возрасте для {user.id}: {age_error}")

            async with get_session() as session:
                await log_new_member(
                    bot=event.bot,
                    user=event.new_chat_member.user,
                    chat=event.chat,
                    invited_by=event.from_user if event.from_user.id != event.new_chat_member.user.id else None,
                    session=session,
                    age_info=age_info
                )
        except Exception as log_error:
            logger.error(f"Ошибка при логировании вступления пользователя: {log_error}")

        # ═══════════════════════════════════════════════════════════════════════
        # PROFILE MONITOR: Создаём snapshot профиля при JOIN (left/kicked -> member)
        # ═══════════════════════════════════════════════════════════════════════
        if old_status in ("left", "kicked") and new_status == "member":
            try:
                from bot.services.profile_monitor import (
                    get_profile_monitor_settings,
                    create_snapshot_on_join,
                )
                user = event.new_chat_member.user
                if not user.is_bot:
                    async with get_session() as pm_session:
                        settings = await get_profile_monitor_settings(pm_session, event.chat.id)
                        if settings and settings.enabled:
                            logger.info(
                                f"[PROFILE_MONITOR] Creating snapshot on JOIN: "
                                f"chat={event.chat.id} user={user.id} name='{user.first_name}'"
                            )
                            snapshot = await create_snapshot_on_join(
                                session=pm_session,
                                chat_id=event.chat.id,
                                user_id=user.id,
                                first_name=user.first_name,
                                last_name=user.last_name,
                                username=user.username,
                                is_premium=user.is_premium or False,
                            )
                            if snapshot:
                                logger.info(
                                    f"[PROFILE_MONITOR] Snapshot created: "
                                    f"chat={event.chat.id} user={user.id} has_photo={snapshot.has_photo}"
                                )
                        else:
                            logger.debug(
                                f"[PROFILE_MONITOR] Skip snapshot: chat={event.chat.id} "
                                f"user={user.id} (module disabled)"
                            )
            except Exception as pm_error:
                logger.error(f"[PROFILE_MONITOR] Error creating snapshot: {pm_error}")

        # ═══════════════════════════════════════════════════════════════════════
        # ANTI-RAID: Проверка имени по паттернам и трекинг входов
        # Вызываем здесь как fallback, т.к. не все группы получают new_chat_members
        # ═══════════════════════════════════════════════════════════════════════
        if old_status in ("left", "kicked") and new_status == "member":
            # Получаем пользователя для проверки
            user = event.new_chat_member.user
            # Пропускаем ботов — они не подлежат Anti-Raid проверке
            if not user.is_bot:
                try:
                    # Импортируем get_session если ещё не импортирован
                    from bot.database.session import get_session
                    async with get_session() as ar_session:
                        # ─────────────────────────────────────────────────────────
                        # 1. Проверка имени по паттернам (Name Pattern Check)
                        # ─────────────────────────────────────────────────────────
                        logger.info(
                            f"[ANTIRAID] Checking name patterns: "
                            f"chat={event.chat.id} user={user.id} name='{user.full_name}'"
                        )
                        # Вызываем проверку имени по паттернам
                        antiraid_check = await check_name_against_patterns(
                            ar_session, user, event.chat.id
                        )
                        # Если паттерн совпал — применяем действие
                        if antiraid_check.matched:
                            logger.warning(
                                f"[ANTIRAID] Name pattern MATCHED: "
                                f"user={user.id} pattern='{antiraid_check.pattern}'"
                            )
                            # Применяем действие (бан/кик/мут) по настройкам группы
                            action_result = await apply_name_pattern_action(
                                bot=event.bot,
                                session=ar_session,
                                chat_id=event.chat.id,
                                user_id=user.id,
                                is_join_request=False,  # Это chat_member_updated, не join_request
                            )
                            # Отправляем уведомление в журнал группы
                            await send_name_pattern_journal(
                                bot=event.bot,
                                session=ar_session,
                                chat_id=event.chat.id,
                                user_id=user.id,
                                check_result=antiraid_check,
                                action_result=action_result,
                            )
                        else:
                            logger.debug(
                                f"[ANTIRAID] Name pattern NOT matched: "
                                f"user={user.id} name='{user.full_name}'"
                            )

                        # ─────────────────────────────────────────────────────────
                        # 2. Трекинг входа/выхода (Join/Exit Abuse Detection)
                        # ─────────────────────────────────────────────────────────
                        # Записываем событие входа для детекции join/exit abuse
                        await track_join_event(
                            bot=event.bot,
                            session=ar_session,
                            chat_id=event.chat.id,
                            user_id=user.id,
                            user_name=user.full_name or str(user.id)
                        )

                        # ─────────────────────────────────────────────────────────
                        # 3. Детекция рейда (Mass Join Detection)
                        # ─────────────────────────────────────────────────────────
                        # Проверяем на массовые вступления (рейд)
                        await track_mass_join(
                            bot=event.bot,
                            session=ar_session,
                            chat_id=event.chat.id,
                            user_id=user.id
                        )

                        # ─────────────────────────────────────────────────────────
                        # 4. Детекция массовых инвайтов (если есть инвайтер)
                        # ─────────────────────────────────────────────────────────
                        # Проверяем был ли пользователь приглашён другим участником
                        inviter = event.from_user
                        # Если inviter != user — это инвайт (кто-то пригласил)
                        if inviter and inviter.id != user.id:
                            logger.info(
                                f"[ANTIRAID] Detected invite: "
                                f"inviter={inviter.id} invited={user.id}"
                            )
                            # Вызываем трекинг массовых инвайтов
                            await track_mass_invite(
                                bot=event.bot,
                                session=ar_session,
                                chat_id=event.chat.id,
                                inviter_id=inviter.id,
                                inviter_name=inviter.full_name or str(inviter.id),
                                invited_user_id=user.id
                            )

                except Exception as ar_error:
                    # Логируем ошибку, но не прерываем обработку
                    logger.error(f"[ANTIRAID] Error in chat_member handler: {ar_error}")
                    import traceback
                    logger.error(f"[ANTIRAID] Traceback: {traceback.format_exc()}")

        try:
            # Проверяем глобальный мут (мастер-переключатель)
            from bot.services.groups_settings_in_private_logic import get_global_mute_status
            from bot.database.session import get_session

            # Получаем статус глобального мута
            async with get_session() as session:
                global_mute_enabled = await get_global_mute_status(session)

            # Глобальный мут — мастер-переключатель
            # Включен = мутим, Выключен = не мутим
            # Локальные настройки НЕ учитываются
            should_mute = global_mute_enabled

            logger.info(f"🔍 [MANUAL_MUTE_HANDLER] Глобальный мут: {global_mute_enabled}, should_mute={should_mute}")
            
            if should_mute:
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ✅ Глобальный мут включен - мутим пользователя @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id}")
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] 🚀 Вызываем mute_manually_approved_member_logic...")
                await mute_manually_approved_member_logic(event)
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ✅ Функция mute_manually_approved_member_logic завершена")
            else:
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] ❌ Глобальный мут выключен - не мутим")
            
            # ВАЖНО: Проверяем автомут скаммеров ПОСЛЕ ручного мута (они работают независимо)
            try:
                from bot.services.auto_mute_scammers_logic import auto_mute_scammer_on_join
                logger.info(f"🔍 [MANUAL_MUTE_HANDLER] 🔍 Проверяем автомут скаммеров для пользователя @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id}")
                await auto_mute_scammer_on_join(event.bot, event)
            except Exception as auto_mute_error:
                logger.error(f"🔍 [MANUAL_MUTE_HANDLER] 💥 AUTO_MUTE ERROR: {str(auto_mute_error)}")
                import traceback
                logger.error(f"🔍 [MANUAL_MUTE_HANDLER] 💥 Traceback: {traceback.format_exc()}")
                
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
                        initiator=event.from_user if event.from_user.id != event.new_chat_member.user.id else None,
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
        from bot.services.groups_settings_in_private_logic import get_global_mute_status
        from bot.database.session import get_session

        # Получаем статус глобального мута (мастер-переключатель)
        async with get_session() as session:
            global_mute_enabled = await get_global_mute_status(session)

        # Глобальный мут — мастер-переключатель
        # Локальные настройки НЕ учитываются
        should_mute = global_mute_enabled

        logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] Глобальный мут: {global_mute_enabled}, should_mute={should_mute}")

        if should_mute:
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] ✅ Глобальный мут включен - мутим пользователя")
            await mute_manually_approved_member_logic(event)
        else:
            logger.info(f"🔍 [MANUAL_MUTE_HANDLER_KICKED] ❌ Глобальный мут выключен - не мутим")
            
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