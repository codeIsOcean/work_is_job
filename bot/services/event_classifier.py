"""
Классификация событий вступления в группу.
Разделяет self-join, invite, join_request и другие события.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from aiogram.types import ChatMemberUpdated, ChatJoinRequest


class JoinEventType(Enum):
    """Тип события вступления в группу"""
    INVITE = "invite"  # Админ/участник пригласил пользователя
    SELF_JOIN = "self_join"  # Пользователь сам вступил (через ссылку/кнопку)
    JOIN_REQUEST = "join_request"  # Запрос на вступление (отдельный тип апдейта)
    OTHER = "other"  # Другое событие


def classify_join_event(
    *,
    event: Optional[ChatMemberUpdated] = None,
    join_request: Optional[ChatJoinRequest] = None,
    user_id: int,
    initiator_id: Optional[int] = None,
    had_pending_request: bool = False,
) -> JoinEventType:
    """
    Классифицирует событие вступления в группу.

    Args:
        event: ChatMemberUpdated событие (если есть)
        join_request: ChatJoinRequest событие (если есть)
        user_id: ID пользователя, который вступил/хочет вступить
        initiator_id: ID пользователя, который инициировал событие (from_user.id)
        had_pending_request: Был ли у пользователя pending join_request (проверяется через Redis)

    Returns:
        JoinEventType: Тип события
    """
    # JOIN_REQUEST - отдельный тип апдейта от Telegram
    if join_request is not None:
        return JoinEventType.JOIN_REQUEST
    
    # Если это не ChatMemberUpdated, не можем определить
    if event is None:
        return JoinEventType.OTHER
    
    # Проверяем статусы - должна быть смена на member
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    
    if old_status not in ("left", "kicked") or new_status != "member":
        return JoinEventType.OTHER
    
    # Определяем инициатора
    # initiator_id может быть из параметра или из event.from_user
    actual_initiator_id = initiator_id
    if actual_initiator_id is None:
        if hasattr(event, "from_user") and event.from_user:
            actual_initiator_id = event.from_user.id
        elif hasattr(event, "actor_chat") and event.actor_chat:
            actual_initiator_id = event.actor_chat.id

    # ФИКС БАГ 2: Если у пользователя был pending join_request, который одобрили - это НЕ invite!
    # Одобрение запроса на вступление != приглашение админом
    if had_pending_request:
        # Пользователь сам подал запрос, админ только одобрил - это SELF_JOIN
        return JoinEventType.SELF_JOIN

    # ФИКС 8: INVITE - есть инициатор и он не равен пользователю (истинный инвайт)
    if actual_initiator_id is not None and actual_initiator_id != user_id:
        return JoinEventType.INVITE

    # ФИКС 8: SELF_JOIN - нет инициатора или инициатор = пользователь
    # (пользователь сам нажал кнопку/перешел по ссылке) - антифлуд НЕ срабатывает
    return JoinEventType.SELF_JOIN

