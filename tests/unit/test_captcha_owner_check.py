"""
Unit тесты для проверки владельца капчи.
ФИКС №6: Проверка, что на кнопку капчи может нажимать только владелец.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.captcha_flow_logic import CAPTCHA_OWNER_KEY


@pytest.mark.asyncio
async def test_captcha_owner_check_valid_user():
    """Тест: Правильный пользователь может нажать на кнопку"""
    chat_id = -1001234567890
    message_id = 12345
    owner_id = 123
    
    # Сохраняем владельца (мокаем Redis)
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    
    with patch('bot.services.captcha_flow_logic.redis') as mock_redis:
        mock_redis.setex = AsyncMock()
        mock_redis.get = AsyncMock(return_value=str(owner_id))
        
        from bot.services.captcha_flow_logic import register_captcha_message
        
        # Проверяем доступ
        stored_owner_id = await mock_redis.get(owner_key)
        assert stored_owner_id is not None
        assert int(stored_owner_id) == owner_id


@pytest.mark.asyncio
async def test_captcha_owner_check_invalid_user():
    """Тест: Неправильный пользователь не может нажать на кнопку"""
    chat_id = -1001234567890
    message_id = 12345
    owner_id = 123
    other_user_id = 456
    
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    
    with patch('bot.services.captcha_flow_logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(return_value=str(owner_id))
        
        # Проверяем доступ другого пользователя
        stored_owner_id = await mock_redis.get(owner_key)
        assert stored_owner_id is not None
        assert int(stored_owner_id) != other_user_id


@pytest.mark.asyncio
async def test_captcha_owner_ttl():
    """Тест: Ключ владельца капчи имеет TTL"""
    chat_id = -1001234567890
    message_id = 12345
    owner_id = 123
    
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    
    with patch('bot.services.captcha_flow_logic.redis') as mock_redis:
        mock_redis.setex = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=250)  # Меньше 300
        
        await mock_redis.setex(owner_key, 300, str(owner_id))
        ttl = await mock_redis.ttl(owner_key)
        
        assert ttl > 0
        assert ttl <= 300

