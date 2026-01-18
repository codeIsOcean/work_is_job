# bot/handlers/antiraid/reaction_handler.py
"""
Обработчик событий реакций для модуля Anti-Raid v2.

v2 ИЗМЕНЕНИЯ:
- Теперь считаем на сколько РАЗНЫХ сообщений юзер поставил реакции
- emoji больше не важен — важен только факт реакции на разные message_id
- Паттерн спаммера: идёт вниз по чату, ставит по 1 реакции на разные сообщения

Отслеживает:
- Добавление реакций на сообщения (message_reaction)
- Проверяет на спам реакциями (unique messages pattern)
- Применяет действия при злоупотреблении (бан/кик/мут)

Примечание: В aiogram 3.x событие реакции это MessageReactionUpdated.
"""

# Импортируем логгер для записи событий
import logging

# Импортируем aiogram
from aiogram import Router, Bot
from aiogram.types import MessageReactionUpdated

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем Redis клиент
from bot.services.redis_conn import redis

# Импортируем сервисы Anti-Raid
from bot.services.antiraid import (
    get_antiraid_settings,
    check_mass_reaction,
    apply_mass_reaction_action,
    send_mass_reaction_journal,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для событий реакций
reaction_router = Router(name="antiraid_reaction")


@reaction_router.message_reaction()
async def handle_message_reaction(
    event: MessageReactionUpdated,
    session: AsyncSession,
) -> None:
    """
    Обработчик добавления реакции на сообщение.

    Срабатывает при:
    - Пользователь поставил реакцию на сообщение

    Args:
        event: Событие изменения реакции
        session: Асинхронная сессия SQLAlchemy
    """
    # Извлекаем данные
    user = event.user
    chat = event.chat
    bot: Bot = event.bot
    message_id = event.message_id

    # Пропускаем если нет пользователя (анонимные реакции)
    if user is None:
        return

    # Пропускаем ботов
    if user.is_bot:
        return

    # Получаем добавленные реакции (new_reaction - это список)
    new_reactions = event.new_reaction or []

    # Если нет новых реакций — это удаление, пропускаем
    if not new_reactions:
        return

    # Логируем событие
    logger.debug(
        f"[ANTIRAID] Reaction added: user_id={user.id}, chat_id={chat.id}, "
        f"message_id={message_id}, reactions_count={len(new_reactions)}"
    )

    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat.id)

    # Если настроек нет или mass_reaction выключен — пропускаем
    if settings is None or not settings.mass_reaction_enabled:
        return

    # ─────────────────────────────────────────────────────────
    # Проверяем является ли юзер админом/модератором
    # Админы могут ставить реакции без ограничений
    # ─────────────────────────────────────────────────────────
    try:
        member = await bot.get_chat_member(chat.id, user.id)
        if member.status in ('creator', 'administrator'):
            logger.debug(
                f"[ANTIRAID] Mass reaction skip: user_id={user.id} is admin/creator"
            )
            return
    except Exception as e:
        # Если не удалось проверить статус — продолжаем проверку
        logger.warning(f"[ANTIRAID] Failed to check admin status for reaction: {e}")

    # ─────────────────────────────────────────────────────────
    # Проверяем на злоупотребление
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку mass_reaction")
        return

    # v2: проверяем один раз на message_id (emoji больше не важен)
    # Раньше проверяли каждую реакцию отдельно, теперь — один message_id
    result = await check_mass_reaction(
        redis=redis,
        session=session,
        chat_id=chat.id,
        user_id=user.id,
        message_id=message_id
    )

    # Если проверка не выполнена — выходим
    if result is None:
        return

    # ─────────────────────────────────────────────────────────
    # Если обнаружено злоупотребление — применяем действие
    # ─────────────────────────────────────────────────────────
    if result.is_abuse:
        logger.warning(
            f"[ANTIRAID] MASS REACTION ABUSE detected! "
            f"user_id={user.id}, chat_id={chat.id}, "
            f"unique_messages={result.unique_messages_count}/{result.threshold}"
        )

        # Применяем действие из настроек
        action_result = await apply_mass_reaction_action(
            bot=bot,
            session=session,
            chat_id=chat.id,
            user_id=user.id
        )

        # Отправляем уведомление в журнал группы
        # abuse_type='user' (всегда) — теперь только один тип детекции
        # reaction_count = unique_messages_count (количество разных сообщений)
        await send_mass_reaction_journal(
            bot=bot,
            session=session,
            chat_id=chat.id,
            user_id=user.id,
            user_name=user.full_name or str(user.id),
            abuse_type='user',
            reaction_count=result.unique_messages_count,
            window_seconds=result.window_seconds,
            action_result=action_result,
            message_id=None  # v2: не привязываем к конкретному сообщению
        )


async def track_reaction(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    user_name: str,
    message_id: int
) -> bool:
    """
    Записывает реакцию и проверяет на злоупотребление.

    Эту функцию можно вызывать из других мест если нужно.

    v2: emoji больше не нужен — считаем только разные message_id.

    Args:
        bot: Экземпляр Bot
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID чата
        user_id: ID пользователя
        user_name: Имя пользователя (для журнала)
        message_id: ID сообщения

    Returns:
        True если обнаружено злоупотребление и применено действие
    """
    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или mass_reaction выключен — пропускаем
    if settings is None or not settings.mass_reaction_enabled:
        return False

    # ─────────────────────────────────────────────────────────
    # Проверяем является ли юзер админом/модератором
    # Админы могут ставить реакции без ограничений
    # ─────────────────────────────────────────────────────────
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ('creator', 'administrator'):
            logger.debug(
                f"[ANTIRAID] Mass reaction skip: user_id={user_id} is admin/creator"
            )
            return False
    except Exception as e:
        # Если не удалось проверить статус — продолжаем проверку
        logger.warning(f"[ANTIRAID] Failed to check admin status for reaction: {e}")

    # ─────────────────────────────────────────────────────────
    # Проверяем на злоупотребление
    # ─────────────────────────────────────────────────────────
    if redis is None:
        logger.warning("[ANTIRAID] Redis недоступен, пропускаем проверку mass_reaction")
        return False

    result = await check_mass_reaction(
        redis=redis,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id
    )

    # Если проверка не выполнена — выходим
    if result is None:
        return False

    # ─────────────────────────────────────────────────────────
    # Если обнаружено злоупотребление — применяем действие
    # ─────────────────────────────────────────────────────────
    if result.is_abuse:
        logger.warning(
            f"[ANTIRAID] MASS REACTION ABUSE detected! "
            f"user_id={user_id}, chat_id={chat_id}, "
            f"unique_messages={result.unique_messages_count}/{result.threshold}"
        )

        # Применяем действие из настроек
        action_result = await apply_mass_reaction_action(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id
        )

        # Отправляем уведомление в журнал группы
        await send_mass_reaction_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            abuse_type='user',
            reaction_count=result.unique_messages_count,
            window_seconds=result.window_seconds,
            action_result=action_result,
            message_id=None
        )

        return True

    return False