# bot/handlers/captcha/captcha_coordinator.py
"""
Координатор капчи - ЕДИНАЯ ТОЧКА ВХОДА для всех событий капчи.

Решает проблему конфликта хендлеров в aiogram 3.x:
- Перехватывает chat_join_request
- Перехватывает new_chat_members
- Определяет режим капчи и вызывает соответствующую логику

Все остальные хендлеры капчи должны вызываться ТОЛЬКО через координатор!
"""

import logging
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import ChatJoinRequest, Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.session import get_session
from bot.services.captcha import (
    CaptchaMode,
    determine_captcha_mode,
    send_captcha,
    get_captcha_settings,
    check_and_restore_restriction,
)
from bot.services.event_classifier import JoinEventType
from bot.services.profile_monitor.profile_monitor_service import (
    get_profile_monitor_settings,
)
from bot.services.profile_monitor.content_checker import (
    check_name_and_bio_content,
)


# Логгер для отслеживания работы координатора
logger = logging.getLogger(__name__)

# Роутер координатора
coordinator_router = Router(name="captcha_coordinator")


@coordinator_router.chat_join_request()
async def handle_join_request(
    event: ChatJoinRequest,
    session: AsyncSession,
) -> None:
    """
    Единая точка входа для chat_join_request.

    Обрабатывает запросы на вступление в группы с включённым
    режимом "Join Requests". Отправляет Visual Captcha в ЛС.

    Args:
        event: Событие запроса на вступление
        session: Сессия БД (инжектится middleware)
    """
    # Извлекаем данные из события
    user = event.from_user
    chat = event.chat
    bot = event.bot

    # Логируем входящее событие
    logger.info(
        f"📥 [COORDINATOR] chat_join_request: "
        f"user_id={user.id}, chat_id={chat.id}, "
        f"username=@{user.username or 'none'}"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Проверяем активные ограничения пользователя
    # Замученные пользователи МОГУТ войти через капчу, мут восстановится после входа
    # Эта проверка только для логирования - НЕ блокируем вход
    # ═══════════════════════════════════════════════════════════════════════
    from bot.database.models import UserRestriction
    from sqlalchemy import select, or_
    from datetime import datetime

    # Проверяем есть ли активное ограничение (для логирования)
    result = await session.execute(
        select(UserRestriction)
        .where(
            UserRestriction.user_id == user.id,
            UserRestriction.chat_id == chat.id,
            UserRestriction.is_active == True,
            or_(
                UserRestriction.until_date.is_(None),
                UserRestriction.until_date > datetime.utcnow(),
            ),
        )
    )
    existing_restriction = result.scalar_one_or_none()

    if existing_restriction:
        # Есть активное ограничение - логируем, но НЕ блокируем
        # Мут будет восстановлен автоматически после успешного входа
        logger.info(
            f"ℹ️ [COORDINATOR] Пользователь с активным мутом пытается войти: "
            f"user_id={user.id}, reason={existing_restriction.reason}. "
            f"Капча будет отправлена, мут восстановится после входа."
        )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1.5: КРИТЕРИЙ 6 - Проверка имени/bio на запрещённый контент
    # Проверяем ДО капчи, чтобы сразу отклонить спаммеров
    # ═══════════════════════════════════════════════════════════════════════
    pm_settings = await get_profile_monitor_settings(session, chat.id)
    if pm_settings and pm_settings.enabled and pm_settings.auto_mute_forbidden_content:
        # Формируем полное имя
        full_name = user.full_name or user.first_name or ""
        # Bio доступен в ChatJoinRequest!
        bio = getattr(event, "bio", None)

        content_result = await check_name_and_bio_content(
            session=session,
            chat_id=chat.id,
            user_id=user.id,
            full_name=full_name,
            bio=bio,
        )

        if content_result.should_act:
            # Запрещённый контент найден - отклоняем заявку
            logger.warning(
                f"🚫 [COORDINATOR] CRITERION_6 - Отклонение join_request: "
                f"user_id={user.id} chat_id={chat.id} "
                f"reason={content_result.reason}"
            )
            try:
                await bot.decline_chat_join_request(chat.id, user.id)
            except Exception as e:
                logger.error(f"❌ Ошибка отклонения join_request: {e}")
            return  # Прерываем обработку

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Определяем нужна ли капча и какой режим
    # ═══════════════════════════════════════════════════════════════════════
    mode = await determine_captcha_mode(
        session=session,
        chat_id=chat.id,
        event_type="join_request",
    )

    # Если капча не нужна - автоматически одобряем
    if mode is None:
        logger.info(
            f"✅ [COORDINATOR] Капча не требуется, автоодобрение: "
            f"user_id={user.id}, chat_id={chat.id}"
        )
        try:
            await bot.approve_chat_join_request(chat.id, user.id)
        except Exception as e:
            logger.error(f"❌ Ошибка автоодобрения: {e}")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Получаем настройки и отправляем капчу
    # ═══════════════════════════════════════════════════════════════════════
    settings = await get_captcha_settings(session, chat.id)

    # Отправляем капчу
    success = await send_captcha(
        bot=bot,
        session=session,
        chat=chat,
        user=user,
        mode=mode,
        settings=settings,
    )

    if success:
        logger.info(
            f"📤 [COORDINATOR] Капча отправлена: "
            f"user_id={user.id}, chat_id={chat.id}, mode={mode.value}"
        )
    else:
        # ═══════════════════════════════════════════════════════════════════════
        # КРИТИЧЕСКИЙ ФИКС: НЕ одобрять заявку при ошибке отправки капчи!
        # Раньше здесь было автоодобрение — это позволяло скаммерам обходить капчу,
        # просто заблокировав бота. Теперь заявка остаётся "висеть" без изменений.
        # Причина ошибки может быть: бот заблокирован, ошибка API, и т.д.
        # ═══════════════════════════════════════════════════════════════════════
        logger.warning(
            f"⚠️ [COORDINATOR] Не удалось отправить капчу, заявка оставлена без изменений: "
            f"user_id={user.id}, chat_id={chat.id}. Возможная причина: бот заблокирован."
        )

        # Отправляем уведомление в журнал для ручного решения админом
        try:
            # Импортируем функцию отправки в журнал
            from bot.handlers.bot_activity_journal.bot_activity_journal import send_activity_log

            # Формируем данные для журнала
            user_data = {
                'user_id': user.id,
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'username': user.username or '',
            }
            group_data = {
                'chat_id': chat.id,
                'title': chat.title or f'Chat {chat.id}',
            }
            additional_info = {
                'reason': 'Не удалось отправить капчу (возможно, бот заблокирован)',
                'action_required': 'Требуется ручное одобрение или отклонение заявки',
            }

            # Отправляем событие в журнал
            await send_activity_log(
                bot=bot,
                event_type="CAPTCHA_SEND_FAILED",
                user_data=user_data,
                group_data=group_data,
                additional_info=additional_info,
                status="pending",
                session=session,
            )
            logger.info(
                f"📝 [COORDINATOR] Уведомление отправлено в журнал: "
                f"user_id={user.id}, chat_id={chat.id}"
            )
        except Exception as journal_err:
            # Ошибка отправки в журнал не должна ломать основную логику
            logger.error(f"❌ [COORDINATOR] Ошибка отправки в журнал: {journal_err}")


@coordinator_router.message(F.new_chat_members)
async def handle_new_members(
    message: Message,
    session: AsyncSession,
) -> None:
    """
    Единая точка входа для new_chat_members.

    Обрабатывает появление новых участников в группе:
    - Самостоятельный вход → Join Captcha
    - Приглашение → Invite Captcha

    Args:
        message: Сообщение с информацией о новых участниках
        session: Сессия БД (инжектится middleware)
    """
    # Проверяем что есть новые участники
    if not message.new_chat_members:
        return

    # Извлекаем данные
    chat = message.chat
    bot = message.bot

    # Обрабатываем каждого нового участника
    for new_member in message.new_chat_members:
        # Пропускаем ботов
        if new_member.is_bot:
            continue

        # Логируем событие
        logger.info(
            f"📥 [COORDINATOR] new_chat_member: "
            f"user_id={new_member.id}, chat_id={chat.id}"
        )

        # ═══════════════════════════════════════════════════════════════════
        # ШАГ 1: Классифицируем событие (самовход или инвайт)
        # ═══════════════════════════════════════════════════════════════════
        # Для new_chat_members определяем по from_user:
        # - Если from_user == new_member - самовход (SELF_JOIN)
        # - Если from_user != new_member - инвайт (INVITE)
        initiator_id = message.from_user.id if message.from_user else None

        if initiator_id == new_member.id:
            event_type = JoinEventType.SELF_JOIN
            event_str = "self_join"
        elif initiator_id is not None:
            event_type = JoinEventType.INVITE
            event_str = "invite"
        else:
            # Неизвестный тип - пропускаем
            logger.debug(
                f"🔍 [COORDINATOR] Не удалось определить тип события: "
                f"user_id={new_member.id}, initiator_id={initiator_id}"
            )
            continue

        # ═══════════════════════════════════════════════════════════════════
        # ШАГ 2: Проверяем активные ограничения
        # ═══════════════════════════════════════════════════════════════════
        restriction = await check_and_restore_restriction(
            bot=bot,
            session=session,
            chat_id=chat.id,
            user_id=new_member.id,
        )

        if restriction:
            logger.info(
                f"🔒 [COORDINATOR] Ограничение восстановлено: "
                f"user_id={new_member.id}, reason={restriction.reason}"
            )
            # Продолжаем - мут уже восстановлен, капча не нужна
            continue

        # ═══════════════════════════════════════════════════════════════════
        # ШАГ 3: Определяем нужна ли капча
        # ═══════════════════════════════════════════════════════════════════
        mode = await determine_captcha_mode(
            session=session,
            chat_id=chat.id,
            event_type=event_str,
        )

        # Если капча не нужна - пропускаем
        if mode is None:
            logger.debug(
                f"🔍 [COORDINATOR] Капча не требуется: "
                f"user_id={new_member.id}, event={event_str}"
            )
            continue

        # ═══════════════════════════════════════════════════════════════════
        # ШАГ 4: Получаем настройки и отправляем капчу
        # ═══════════════════════════════════════════════════════════════════
        settings = await get_captcha_settings(session, chat.id)

        # Создаём псевдо-User объект для передачи в send_captcha
        # (new_member это User объект из Telegram)
        success = await send_captcha(
            bot=bot,
            session=session,
            chat=chat,
            user=new_member,
            mode=mode,
            settings=settings,
        )

        if success:
            logger.info(
                f"📤 [COORDINATOR] Групповая капча отправлена: "
                f"user_id={new_member.id}, chat_id={chat.id}, mode={mode.value}"
            )
        else:
            logger.warning(
                f"⚠️ [COORDINATOR] Не удалось отправить групповую капчу: "
                f"user_id={new_member.id}"
            )
