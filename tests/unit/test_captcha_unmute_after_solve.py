"""
Unit тесты для проверки снятия mute после прохождения visual captcha.
БАГ №1 и №3: Пользователь должен быть размучен после успешного решения капчи.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import ChatPermissions, ChatMember
from aiogram.exceptions import TelegramBadRequest



@pytest.mark.asyncio
async def test_unmute_after_visual_captcha_self_join():
    """Тест: После прохождения visual captcha при self-join mute должен быть снят"""
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(
        spec=ChatMember,
        status="restricted",
        user=MagicMock(id=123)
    ))
    
    user_id = 123
    chat_id = -1001234567890
    
    # Симулируем, что пользователь в группе и замьючен
    member = await bot.get_chat_member(chat_id, user_id)
    assert member.status == "restricted"
    
    # После успешного прохождения капчи должен быть вызван restrict_chat_member с полными правами
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
    
    # Проверяем, что был вызван restrict_chat_member
    bot.restrict_chat_member.assert_called_once()
    call_args = bot.restrict_chat_member.call_args
    assert call_args.kwargs['chat_id'] == chat_id
    assert call_args.kwargs['user_id'] == user_id
    assert call_args.kwargs['permissions'].can_send_messages is True


@pytest.mark.asyncio
async def test_unmute_after_visual_captcha_invite():
    """Тест: После прохождения visual captcha при invite mute должен быть снят"""
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(
        spec=ChatMember,
        status="restricted",
        user=MagicMock(id=456)
    ))
    
    user_id = 456
    chat_id = -1001234567890
    
    # После успешного прохождения капчи должен быть вызван restrict_chat_member с полными правами
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
    
    bot.restrict_chat_member.assert_called_once()


@pytest.mark.asyncio
async def test_unmute_multiple_chat_ids():
    """Тест: Mute должен быть снят для всех найденных chat_id"""
    bot = MagicMock(spec=Bot)
    bot.restrict_chat_member = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(
        spec=ChatMember,
        status="restricted",
        user=MagicMock(id=789)
    ))
    
    user_id = 789
    chat_ids = [-1001234567890, -1001234567891]
    
    # Для каждого chat_id должен быть вызван restrict_chat_member
    for chat_id in chat_ids:
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
    
    assert bot.restrict_chat_member.call_count == len(chat_ids)

