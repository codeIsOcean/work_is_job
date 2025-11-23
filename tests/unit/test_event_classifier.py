"""
Unit тесты для классификатора событий вступления в группу.
ФИКС №1: Проверка разделения self-join, invite, join_request.
"""
import pytest
from types import SimpleNamespace
from aiogram.types import ChatMemberUpdated, ChatMember, User, Chat

from bot.services.event_classifier import classify_join_event, JoinEventType


def _make_event(
    user_id: int,
    initiator_id: int = None,
    old_status: str = "left",
    new_status: str = "member",
) -> ChatMemberUpdated:
    """Создает мок ChatMemberUpdated события"""
    user = SimpleNamespace(id=user_id, username="user", first_name="User")
    old_member = SimpleNamespace(status=old_status, user=user)
    new_member = SimpleNamespace(status=new_status, user=user)
    chat = SimpleNamespace(id=-1001234567890, title="Test Group", type="supergroup")
    
    event = SimpleNamespace(
        old_chat_member=old_member,
        new_chat_member=new_member,
        chat=chat,
        from_user=SimpleNamespace(id=initiator_id) if initiator_id else None,
    )
    return event


def test_classify_invite():
    """Тест: Определение инвайта (initiator != user)"""
    event = _make_event(user_id=123, initiator_id=456)
    result = classify_join_event(
        event=event,
        user_id=123,
        initiator_id=456,
    )
    assert result == JoinEventType.INVITE


def test_classify_self_join():
    """Тест: Определение self-join (initiator == None или initiator == user)"""
    # Случай 1: нет инициатора
    event = _make_event(user_id=123, initiator_id=None)
    result = classify_join_event(
        event=event,
        user_id=123,
        initiator_id=None,
    )
    assert result == JoinEventType.SELF_JOIN
    
    # Случай 2: инициатор = пользователь
    event = _make_event(user_id=123, initiator_id=123)
    result = classify_join_event(
        event=event,
        user_id=123,
        initiator_id=123,
    )
    assert result == JoinEventType.SELF_JOIN


def test_classify_join_request():
    """Тест: Определение join_request (отдельный тип события)"""
    join_request = SimpleNamespace(from_user=SimpleNamespace(id=123))
    result = classify_join_event(
        join_request=join_request,
        user_id=123,
    )
    assert result == JoinEventType.JOIN_REQUEST


def test_classify_other():
    """Тест: Определение других событий (не вступление в группу)"""
    # Не переход на member
    event = _make_event(user_id=123, old_status="member", new_status="restricted")
    result = classify_join_event(
        event=event,
        user_id=123,
    )
    assert result == JoinEventType.OTHER
    
    # Нет события вообще
    result = classify_join_event(user_id=123)
    assert result == JoinEventType.OTHER


def test_join_request_priority():
    """Тест: JOIN_REQUEST имеет приоритет над другими типами"""
    join_request = SimpleNamespace(from_user=SimpleNamespace(id=123))
    event = _make_event(user_id=123, initiator_id=456)
    
    result = classify_join_event(
        event=event,
        join_request=join_request,
        user_id=123,
        initiator_id=456,
    )
    assert result == JoinEventType.JOIN_REQUEST

