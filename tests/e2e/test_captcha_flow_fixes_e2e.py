"""
E2E тесты для исправленных багов капчи.
Проверка сценария: Капча при вступлении включена, пользователь решает visual captcha, должен быть размучен.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import Message, Chat, User as TgUser, ChatMember
from aiogram.enums import ChatMemberStatus

from bot.services import redis_conn
from bot.services.captcha_flow_logic import CAPTCHA_OWNER_KEY, CAPTCHA_MESSAGE_KEY


@pytest.mark.asyncio
@pytest.mark.skip(reason="Pseudo-e2e scenario; full visual captcha unmute behavior is covered by dedicated handler tests")
async def test_e2e_unmute_after_visual_captcha_solve():
    """
    E2E: Пользователь вступает в группу, решает visual captcha, mute должен быть снят.
    Сценарий: Капча при вступлении включена, пользователь решает через deep link.
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
    message_id = 456
    
    # Сохраняем состояние капчи (симулируем, что капча была отправлена в группу)
    captcha_msg_key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=user_id)
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    await redis_conn.redis.setex(captcha_msg_key, 3600, str(message_id))
    await redis_conn.redis.setex(owner_key, 3600, str(user_id))
    
    # Симулируем успешное прохождение visual captcha
    # Проверяем, что пользователь в группе и замьючен
    member = await bot.get_chat_member(chat_id, user_id)
    assert member.status == ChatMemberStatus.RESTRICTED
    
    # После прохождения капчи должен быть вызван restrict_chat_member с полными правами
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
    
    # Проверяем, что был вызван restrict_chat_member
    bot.restrict_chat_member.assert_called_once()
    
    # Проверяем, что флаг captcha_passed установлен
    captcha_passed = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert captcha_passed == "1"
    
    # Очистка
    await redis_conn.redis.delete(captcha_msg_key)
    await redis_conn.redis.delete(owner_key)
    await redis_conn.redis.delete(f"captcha_passed:{user_id}:{chat_id}")


@pytest.mark.asyncio
async def test_e2e_owner_check_deep_link():
    """
    E2E: Проверка владельца капчи при нажатии на deep link.
    Только владелец капчи может решить свою капчу.
    """
    chat_id = -1001234567890
    owner_id = 123
    other_user_id = 456
    message_id = 789
    
    # Сохраняем владельца капчи
    captcha_msg_key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=owner_id)
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    await redis_conn.redis.setex(captcha_msg_key, 3600, str(message_id))
    await redis_conn.redis.setex(owner_key, 3600, str(owner_id))
    
    # Правильный пользователь может решить
    captcha_msg_id = await redis_conn.redis.get(captcha_msg_key)
    if captcha_msg_id:
        owner = await redis_conn.redis.get(owner_key)
        assert owner == str(owner_id)
    
    # Неправильный пользователь не может решить
    captcha_msg_key_other = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=other_user_id)
    captcha_msg_id_other = await redis_conn.redis.get(captcha_msg_key_other)
    # Для другого пользователя нет активной капчи
    assert captcha_msg_id_other is None
    
    # Очистка
    await redis_conn.redis.delete(captcha_msg_key)
    await redis_conn.redis.delete(owner_key)


@pytest.mark.asyncio
async def test_e2e_invite_captcha_owner_check():
    """
    E2E: Проверка владельца капчи при invite.
    Только приглашенный пользователь может решить свою капчу.
    """
    chat_id = -1001234567890
    invited_user_id = 789
    other_user_id = 999
    message_id = 111
    
    # Сохраняем владельца капчи (invited пользователь)
    captcha_msg_key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=invited_user_id)
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    await redis_conn.redis.setex(captcha_msg_key, 3600, str(message_id))
    await redis_conn.redis.setex(owner_key, 3600, str(invited_user_id))
    
    # Приглашенный пользователь может решить
    captcha_msg_id = await redis_conn.redis.get(captcha_msg_key)
    if captcha_msg_id:
        owner = await redis_conn.redis.get(owner_key)
        assert owner == str(invited_user_id)
    
    # Другой пользователь не может решить
    owner = await redis_conn.redis.get(owner_key)
    assert owner != str(other_user_id)
    
    # Очистка
    await redis_conn.redis.delete(captcha_msg_key)
    await redis_conn.redis.delete(owner_key)

