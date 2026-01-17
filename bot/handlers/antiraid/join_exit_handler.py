# bot/handlers/antiraid/join_exit_handler.py
"""
Обработчик событий входа/выхода для модуля Anti-Raid.

Отслеживает:
- Выход из группы (chat_member с LEFT_TRANSITION)
- Запись событий в Redis трекер
- Применение действий при злоупотреблении

Примечание: входы обрабатываются в captcha_coordinator.py
"""

# Импортируем логгер для записи событий
import logging

# Импортируем aiogram
from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, LEAVE_TRANSITION

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем Redis клиент
from bot.services.redis_conn import redis

# Импортируем сервисы Anti-Raid
from bot.services.antiraid import (
    check_join_exit_abuse,
    apply_join_exit_action,
    send_join_exit_journal,
    get_antiraid_settings,
    # Mass Join
    check_mass_join,
    apply_raid_action,
    ban_user,
)
# Импортируем функции журнала
from bot.services.antiraid.journal_service import (
    send_raid_detected_journal,
    update_raid_journal,
)
# Импортируем трекер для работы со счётчиками
from bot.services.antiraid.mass_join_tracker import MassJoinTracker


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для событий выхода
join_exit_router = Router(name="antiraid_join_exit")


@join_exit_router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def handle_member_left(
    event: ChatMemberUpdated,
    session: AsyncSession,
) -> None:
    """
    Обработчик выхода участника из группы.

    Срабатывает при:
    - Пользователь сам вышел из группы
    - Пользователь был кикнут (но не забанен)

    НЕ срабатывает если пользователь забанен (это другой переход).

    Args:
        event: Событие изменения статуса участника
        session: Асинхронная сессия SQLAlchemy
    """
    # Извлекаем данные
    user = event.new_chat_member.user
    chat = event.chat
    bot = event.bot

    # Пропускаем ботов
    if user.is_bot:
        return

    # Логируем событие
    logger.debug(
        f"[ANTIRAID] Member left: user_id={user.id}, chat_id={chat.id}, "
        f"username=@{user.username or 'none'}"
    )

    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat.id)

    # Если настроек нет или join_exit выключен — пропускаем
    if settings is None or not settings.join_exit_enabled:
        return

    # ─────────────────────────────────────────────────────────
    # Проверяем на злоупотребление
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку")
        return

    result = await check_join_exit_abuse(
        redis=redis,
        session=session,
        chat_id=chat.id,
        user_id=user.id,
        event_type="exit"
    )

    # Если проверка не выполнена (модуль выключен) — выходим
    if result is None:
        return

    # ─────────────────────────────────────────────────────────
    # Если обнаружено злоупотребление — применяем действие
    # ─────────────────────────────────────────────────────────
    if result.is_abuse:
        logger.warning(
            f"[ANTIRAID] JOIN/EXIT ABUSE detected on EXIT! "
            f"user_id={user.id}, chat_id={chat.id}, "
            f"events={result.event_count}/{result.threshold}"
        )

        # Применяем действие из настроек
        action_result = await apply_join_exit_action(
            bot=bot,
            session=session,
            chat_id=chat.id,
            user_id=user.id
        )

        # Отправляем уведомление в журнал группы
        await send_join_exit_journal(
            bot=bot,
            session=session,
            chat_id=chat.id,
            user_id=user.id,
            user_name=user.full_name or str(user.id),
            event_count=result.event_count,
            window_seconds=result.window_seconds,
            action_result=action_result
        )


async def track_join_event(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    user_name: str
) -> bool:
    """
    Записывает событие входа и проверяет на злоупотребление.

    Эту функцию следует вызывать из captcha_coordinator.py
    при обработке событий входа (join_request, new_chat_member).

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID чата
        user_id: ID пользователя
        user_name: Имя пользователя (для журнала)

    Returns:
        True если обнаружено злоупотребление и применено действие
    """
    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или join_exit выключен — пропускаем
    if settings is None or not settings.join_exit_enabled:
        return False

    # ─────────────────────────────────────────────────────────
    # Проверяем на злоупотребление
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку")
        return False

    result = await check_join_exit_abuse(
        redis=redis,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        event_type="join"
    )

    # Если проверка не выполнена — выходим
    if result is None:
        return False

    # ─────────────────────────────────────────────────────────
    # Если обнаружено злоупотребление — применяем действие
    # ─────────────────────────────────────────────────────────
    if result.is_abuse:
        logger.warning(
            f"[ANTIRAID] JOIN/EXIT ABUSE detected on JOIN! "
            f"user_id={user_id}, chat_id={chat_id}, "
            f"events={result.event_count}/{result.threshold}"
        )

        # Применяем действие из настроек
        action_result = await apply_join_exit_action(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id
        )

        # Отправляем уведомление в журнал группы
        await send_join_exit_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            event_count=result.event_count,
            window_seconds=result.window_seconds,
            action_result=action_result
        )

        return True

    return False


async def track_mass_join(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> bool:
    """
    Записывает вступление и проверяет на массовые вступления (рейд).

    v2 ЛОГИКА:
    - При детекции рейда включается protection mode
    - ВСЕ вступления в protection mode = бан
    - Одно агрегированное уведомление обновляется со счётчиком

    Эту функцию следует вызывать из captcha_coordinator.py
    при обработке событий входа.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        True если protection mode активен и юзер забанен
    """
    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или mass_join выключен — пропускаем
    if settings is None or not settings.mass_join_enabled:
        return False

    # ─────────────────────────────────────────────────────────
    # Проверяем на массовые вступления
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку mass_join")
        return False

    result = await check_mass_join(
        redis=redis,
        session=session,
        chat_id=chat_id,
        user_id=user_id
    )

    # Если проверка не выполнена — выходим
    if result is None:
        return False

    # ─────────────────────────────────────────────────────────
    # Если protection mode НЕ активен — ничего не делаем
    # ─────────────────────────────────────────────────────────
    if not result.is_protection_mode:
        return False

    # ─────────────────────────────────────────────────────────
    # Protection mode АКТИВЕН — банить юзера!
    # ─────────────────────────────────────────────────────────
    tracker = MassJoinTracker(redis)

    # Получаем длительность бана из настроек
    ban_duration_hours = settings.mass_join_ban_duration  # 0 = навсегда

    # Применяем бан
    action_result = await ban_user(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        duration_hours=ban_duration_hours
    )

    if not action_result.success:
        logger.error(
            f"[ANTIRAID] Ошибка бана рейдера: user_id={user_id}, "
            f"error={action_result.error_message}"
        )
        return False

    # ─────────────────────────────────────────────────────────
    # Инкрементируем счётчик забаненных
    # ─────────────────────────────────────────────────────────
    banned_count = await tracker.increment_banned_count(chat_id)

    logger.warning(
        f"[ANTIRAID] 🚫 Рейдер забанен: user_id={user_id}, "
        f"chat_id={chat_id}, total_banned={banned_count}"
    )

    # ─────────────────────────────────────────────────────────
    # Обновляем агрегированное уведомление в журнале
    # ─────────────────────────────────────────────────────────
    if result.is_raid_detected:
        # Первое обнаружение — создаём новое уведомление
        message_id = await send_raid_detected_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            join_count=result.join_count,
            window_seconds=result.window_seconds,
            banned_count=banned_count,
            protection_seconds=result.protection_remaining_seconds,
            action_taken=settings.mass_join_action,
            slowmode_seconds=settings.mass_join_slowmode
        )

        # Сохраняем message_id для последующих обновлений
        if message_id:
            await tracker.set_journal_message_id(chat_id, message_id)

    else:
        # Protection mode был уже активен — обновляем существующее сообщение
        journal_message_id = await tracker.get_journal_message_id(chat_id)

        if journal_message_id:
            await update_raid_journal(
                bot=bot,
                session=session,
                chat_id=chat_id,
                journal_message_id=journal_message_id,
                join_count=result.join_count,
                window_seconds=result.window_seconds,
                banned_count=banned_count,
                protection_seconds=result.protection_remaining_seconds,
                action_taken=settings.mass_join_action,
                slowmode_seconds=settings.mass_join_slowmode,
                is_active=True
            )

    return True


async def track_mass_invite(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    inviter_id: int,
    inviter_name: str,
    invited_user_id: int
) -> bool:
    """
    Записывает инвайт и проверяет на массовые инвайты.

    Эту функцию следует вызывать из captcha_coordinator.py
    при обработке событий INVITE (когда один юзер приглашает другого).

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID чата
        inviter_id: ID пользователя-инвайтера
        inviter_name: Имя инвайтера (для журнала)
        invited_user_id: ID приглашённого пользователя

    Returns:
        True если обнаружено злоупотребление и применено действие
    """
    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или mass_invite выключен — пропускаем
    if settings is None or not settings.mass_invite_enabled:
        return False

    # ─────────────────────────────────────────────────────────
    # Проверяем на злоупотребление
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку mass_invite")
        return False

    # Импортируем функции трекера и действий
    from bot.services.antiraid import (
        check_mass_invite,
        apply_mass_invite_action,
        send_mass_invite_journal,
    )

    result = await check_mass_invite(
        redis=redis,
        session=session,
        chat_id=chat_id,
        inviter_id=inviter_id,
        invited_user_id=invited_user_id
    )

    # Если проверка не выполнена — выходим
    if result is None:
        return False

    # ─────────────────────────────────────────────────────────
    # Если обнаружено злоупотребление — применяем действие
    # ─────────────────────────────────────────────────────────
    if result.is_abuse:
        logger.warning(
            f"[ANTIRAID] MASS INVITE ABUSE detected! "
            f"inviter_id={inviter_id}, chat_id={chat_id}, "
            f"invites={result.invite_count}/{result.threshold}"
        )

        # Применяем действие из настроек
        action_result = await apply_mass_invite_action(
            bot=bot,
            session=session,
            chat_id=chat_id,
            inviter_id=inviter_id
        )

        # Отправляем уведомление в журнал группы
        await send_mass_invite_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            inviter_id=inviter_id,
            inviter_name=inviter_name,
            invite_count=result.invite_count,
            window_seconds=result.window_seconds,
            action_result=action_result
        )

        return True

    return False
