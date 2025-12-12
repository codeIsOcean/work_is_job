# bot/services/restriction_service.py
"""
Сервис для управления ограничениями пользователей (муты/баны).
Обеспечивает сохранение в БД и восстановление после повторного входа.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import UserRestriction
from bot.database.session import get_session

logger = logging.getLogger(__name__)


async def save_restriction(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    restriction_type: str,
    reason: str,
    restricted_by: Optional[int] = None,
    until_date: Optional[datetime] = None,
) -> UserRestriction:
    """
    Сохраняет ограничение пользователя в БД.
    Если есть активное ограничение - обновляет его.

    Args:
        session: AsyncSession для работы с БД
        chat_id: ID чата/группы
        user_id: ID пользователя
        restriction_type: Тип ограничения (mute, ban, kick)
        reason: Причина (antispam, content_filter, reaction, manual, risk_gate)
        restricted_by: ID админа или бота, применившего ограничение
        until_date: Дата окончания (None = бессрочно)

    Returns:
        UserRestriction: Созданная или обновлённая запись
    """
    # Ищем существующее активное ограничение
    stmt = select(UserRestriction).where(
        and_(
            UserRestriction.chat_id == chat_id,
            UserRestriction.user_id == user_id,
            UserRestriction.is_active == True,
        )
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    # Используем naive datetime для совместимости с БД (PostgreSQL без timezone)
    now = datetime.utcnow()

    # Конвертируем until_date в naive если он aware
    until_date_naive = None
    if until_date is not None:
        if until_date.tzinfo is not None:
            until_date_naive = until_date.replace(tzinfo=None)
        else:
            until_date_naive = until_date

    if existing:
        # Обновляем существующее ограничение
        existing.restriction_type = restriction_type
        existing.reason = reason
        existing.restricted_by = restricted_by
        existing.until_date = until_date_naive
        existing.updated_at = now
        logger.info(
            f"[RESTRICTION] Updated: chat={chat_id} user={user_id} "
            f"type={restriction_type} reason={reason} until={until_date_naive}"
        )
        await session.commit()
        return existing

    # Создаём новое ограничение
    restriction = UserRestriction(
        chat_id=chat_id,
        user_id=user_id,
        restriction_type=restriction_type,
        reason=reason,
        restricted_by=restricted_by,
        until_date=until_date_naive,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(restriction)
    await session.commit()

    logger.info(
        f"[RESTRICTION] Created: chat={chat_id} user={user_id} "
        f"type={restriction_type} reason={reason} until={until_date}"
    )
    return restriction


async def get_active_restriction(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> Optional[UserRestriction]:
    """
    Получает активное ограничение пользователя в чате.

    Args:
        session: AsyncSession
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        UserRestriction или None если нет активного ограничения
    """
    stmt = select(UserRestriction).where(
        and_(
            UserRestriction.chat_id == chat_id,
            UserRestriction.user_id == user_id,
            UserRestriction.is_active == True,
        )
    )
    result = await session.execute(stmt)
    restriction = result.scalar_one_or_none()

    # Проверяем, не истёк ли срок
    if restriction and restriction.until_date:
        # Используем naive datetime для сравнения
        now = datetime.utcnow()
        until = restriction.until_date

        if until < now:
            # Срок истёк - деактивируем
            restriction.is_active = False
            restriction.updated_at = now
            await session.commit()
            logger.info(
                f"[RESTRICTION] Expired and deactivated: chat={chat_id} user={user_id}"
            )
            return None

    return restriction


async def deactivate_restriction(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> bool:
    """
    Деактивирует ограничение пользователя (при размуте).

    Args:
        session: AsyncSession
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        True если ограничение было деактивировано, False если не найдено
    """
    stmt = select(UserRestriction).where(
        and_(
            UserRestriction.chat_id == chat_id,
            UserRestriction.user_id == user_id,
            UserRestriction.is_active == True,
        )
    )
    result = await session.execute(stmt)
    restriction = result.scalar_one_or_none()

    if restriction:
        restriction.is_active = False
        restriction.updated_at = datetime.utcnow()
        await session.commit()
        logger.info(f"[RESTRICTION] Deactivated: chat={chat_id} user={user_id}")
        return True

    return False


async def restore_restriction(
    bot: Bot,
    chat_id: int,
    user_id: int,
    restriction: UserRestriction,
) -> bool:
    """
    Восстанавливает ограничение через Telegram API после одобрения join request.

    Args:
        bot: Bot instance
        chat_id: ID чата
        user_id: ID пользователя
        restriction: Запись об ограничении из БД

    Returns:
        True если успешно восстановлено, False при ошибке
    """
    try:
        if restriction.restriction_type == "mute":
            # Полный мут - запрещаем все действия
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False,
            )

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=restriction.until_date,
            )

            logger.info(
                f"[RESTRICTION] Restored mute: chat={chat_id} user={user_id} "
                f"reason={restriction.reason} until={restriction.until_date}"
            )
            return True

        elif restriction.restriction_type == "ban":
            # Бан - кикаем пользователя
            await bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=restriction.until_date,
            )
            logger.info(
                f"[RESTRICTION] Restored ban: chat={chat_id} user={user_id}"
            )
            return True

    except Exception as e:
        logger.error(
            f"[RESTRICTION] Failed to restore: chat={chat_id} user={user_id} "
            f"error={e}"
        )
        return False

    return False


async def check_and_restore_restriction(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> Optional[UserRestriction]:
    """
    Проверяет наличие активного ограничения и восстанавливает его.
    Вызывается после approve_chat_join_request.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        UserRestriction если было восстановлено, None если нет ограничения
    """
    restriction = await get_active_restriction(session, chat_id, user_id)

    if restriction:
        success = await restore_restriction(bot, chat_id, user_id, restriction)
        if success:
            return restriction

    return None
