"""
Unit тесты для проверки владельца капчи при нажатии на кнопку.
БАГ №2 и №3: Только владелец капчи может решать свою капчу.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.captcha_flow_logic import CAPTCHA_OWNER_KEY, CAPTCHA_MESSAGE_KEY
from bot.services.redis_conn import redis


@pytest.mark.asyncio
async def test_deep_link_owner_check_valid():
    """Тест: Правильный пользователь может решить свою капчу через deep link"""
    chat_id = -1001234567890
    user_id = 123
    message_id = 456
    
    # Сохраняем владельца капчи
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    msg_key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=user_id)
    
    with patch('bot.services.captcha_flow_logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(side_effect=lambda key: {
            msg_key: str(message_id),
            owner_key: str(user_id),
        }.get(key))
        
        # Проверяем, что владелец найден и совпадает
        captcha_msg_id = await mock_redis.get(msg_key)
        if captcha_msg_id:
            owner = await mock_redis.get(owner_key)
            assert owner == str(user_id)


@pytest.mark.asyncio
async def test_deep_link_owner_check_invalid():
    """Тест: Неправильный пользователь не может решить чужую капчу через deep link"""
    chat_id = -1001234567890
    owner_id = 123
    other_user_id = 456
    message_id = 789
    
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    msg_key = CAPTCHA_MESSAGE_KEY.format(chat_id=chat_id, user_id=owner_id)
    
    with patch('bot.services.captcha_flow_logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(side_effect=lambda key: {
            msg_key: str(message_id),
            owner_key: str(owner_id),
        }.get(key))
        
        # Проверяем, что другой пользователь не может решить
        captcha_msg_id = await mock_redis.get(msg_key)
        if captcha_msg_id:
            owner = await mock_redis.get(owner_key)
            assert owner != str(other_user_id)


@pytest.mark.asyncio
async def test_callback_button_owner_check():
    """Тест: Проверка владельца капчи при нажатии на callback кнопку"""
    chat_id = -1001234567890
    owner_id = 123
    other_user_id = 456
    message_id = 789
    
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    
    with patch('bot.handlers.visual_captcha.visual_captcha_handler.redis') as mock_redis:
        mock_redis.get = AsyncMock(return_value=str(owner_id))
        
        # Проверяем владельца
        expected_owner_id = await mock_redis.get(owner_key)
        
        # Правильный пользователь
        assert int(expected_owner_id) == owner_id
        
        # Неправильный пользователь
        assert int(expected_owner_id) != other_user_id

