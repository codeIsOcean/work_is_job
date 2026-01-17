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
)


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
