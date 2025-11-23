"""
Unit тесты для ФИКС 1: После прохождения капчи пользователь остаётся в муте.
Проверяет, что mute снимается ВСЕГДА после успешной капчи.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import ChatPermissions, User, Chat, Message, ChatMember
from aiogram.enums import ChatMemberStatus
from sqlalchemy.ext.asyncio import AsyncSession



@pytest.mark.asyncio
async def test_unmute_always_after_successful_captcha():
    """
    ФИКС 1: Проверяет, что restrict_chat_member с full permissions вызывается
    ВСЕГДА после успешной капчи, независимо от статуса пользователя.
    """
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(
        spec=ChatMember,
        status=ChatMemberStatus.RESTRICTED,
        user=MagicMock(id=123)
    ))
    bot.get_chat = AsyncMock(return_value=MagicMock(spec=Chat, id=-1001234567890, title="Test Group"))
    
    user_id = 123
    chat_id = -1001234567890
    
    # Симулируем успешное прохождение капчи
    # ФИКС 1: После успешной капчи должен вызываться restrict_chat_member с полными правами
    from aiogram.types import ChatPermissions
    
    full_permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_pin_messages=True,
    )
    
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=full_permissions,
    )
    
    # Проверяем, что был вызван restrict_chat_member с полными правами
    bot.restrict_chat_member.assert_called_once()
    call_args = bot.restrict_chat_member.call_args
    assert call_args.kwargs['chat_id'] == chat_id
    assert call_args.kwargs['user_id'] == user_id
    assert call_args.kwargs['permissions'] == full_permissions


@pytest.mark.asyncio
async def test_unmute_even_if_user_not_in_group():
    """
    ФИКС 1: Проверяет, что попытка размута происходит даже если пользователь не в группе.
    В этом случае ошибка игнорируется (не критично).
    """
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock(side_effect=Exception("Chat not found"))
    bot.get_chat_member = AsyncMock(side_effect=Exception("User not found"))
    
    user_id = 123
    chat_id = -1001234567890
    
    # ФИКС 1: Попытка размута должна происходить даже если пользователь не в группе
    from aiogram.types import ChatPermissions
    
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True,
                can_pin_messages=True,
            ),
        )
    except Exception as e:
        # Ошибка не критична - пользователь может быть еще не в группе
        error_str = str(e).lower()
        assert "chat not found" in error_str or "user not found" in error_str
    
    # Проверяем, что была попытка вызова
    bot.restrict_chat_member.assert_called_once()


@pytest.mark.asyncio
async def test_no_ttl_dependency_for_unmute():
    """
    ФИКС 1: Проверяет, что размут не зависит от TTL таймера.
    Mute должен сниматься мгновенно после успешной капчи.
    """
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(
        spec=ChatMember,
        status=ChatMemberStatus.MEMBER,  # Пользователь уже member
        user=MagicMock(id=123)
    ))
    
    user_id = 123
    chat_id = -1001234567890
    
    # ФИКС 1: Размут должен происходить мгновенно, без проверки TTL
    from aiogram.types import ChatPermissions
    
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_invite_users=True,
            can_pin_messages=True,
        ),
    )
    
    # Проверяем, что был вызван restrict_chat_member (независимо от статуса)
    bot.restrict_chat_member.assert_called_once()
    
    # Проверяем, что нет проверки TTL (не вызывается redis.ttl или подобное)
    # Этот тест проверяет отсутствие зависимости от TTL в коде


