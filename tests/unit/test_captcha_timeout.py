"""
Unit тесты для обработки таймаута капчи.
ФИКС №7: При таймауте капчи - reject для join_request, kick для обычного join.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from bot.services.visual_captcha_logic import handle_captcha_timeout_final


@pytest.mark.asyncio
async def test_timeout_with_join_request(fake_redis):
    """Тест: Таймаут капчи при наличии join_request → reject"""
    bot = MagicMock(spec=Bot)
    bot.decline_chat_join_request = AsyncMock()
    bot.get_chat = AsyncMock(return_value=MagicMock(title="Test Group"))
    # aiogram.TelegramBadRequest в актуальной версии требует method и message
    bot.get_chat_member = AsyncMock(
        side_effect=TelegramBadRequest(method="getChatMember", message="User not found")
    )
    
    user_id = 123
    group_name = "test_group"
    chat_id = -1001234567890
    
    # Сохраняем join_request
    from bot.services import redis_conn
    await redis_conn.redis.setex(f"join_request:{user_id}:{group_name}", 3600, str(chat_id))
    await redis_conn.redis.setex(f"captcha:{user_id}", 300, "answer:test_group:0")
    
    with patch('bot.services.visual_captcha_logic.get_captcha_data', return_value={"group_name": group_name}):
        with patch('asyncio.sleep', return_value=None):
            # Не ждем реальные 2 минуты в тесте
            await handle_captcha_timeout_final(bot, user_id, group_name)
    
    # Проверяем, что был вызван decline_chat_join_request
    bot.decline_chat_join_request.assert_called_once_with(chat_id=chat_id, user_id=user_id)
    
    # Очистка
    from bot.services import redis_conn as _redis_cleanup
    await _redis_cleanup.redis.delete(f"join_request:{user_id}:{group_name}")
    await _redis_cleanup.redis.delete(f"captcha:{user_id}")


@pytest.mark.asyncio
async def test_timeout_with_user_in_group(fake_redis):
    """Тест: Таймаут капчи при нахождении пользователя в группе → kick"""
    bot = MagicMock(spec=Bot)
    bot.ban_chat_member = AsyncMock()
    bot.unban_chat_member = AsyncMock()
    bot.get_chat = AsyncMock(return_value=MagicMock(title="Test Group"))
    
    user_id = 123
    chat_id = -1001234567890
    group_name = f"private_{chat_id}"
    
    # Мокаем, что пользователь в группе
    member = MagicMock(status="member", user=MagicMock(id=user_id))
    bot.get_chat_member = AsyncMock(return_value=member)
    
    # Сохраняем состояние капчи (группа кодируется как private_<id>, как в реальном deep-link)
    from bot.services import redis_conn
    await redis_conn.redis.setex(f"captcha:{user_id}", 300, "answer:test_group:0")
    
    with patch('bot.services.visual_captcha_logic.get_captcha_data', return_value={"group_name": group_name}):
        with patch('asyncio.sleep', return_value=None):
            await handle_captcha_timeout_final(bot, user_id, group_name)
    
    # Проверяем, что был вызван ban и unban
    bot.ban_chat_member.assert_called_once_with(chat_id=chat_id, user_id=user_id)
    bot.unban_chat_member.assert_called_once_with(chat_id=chat_id, user_id=user_id)
    
    # Очистка
    from bot.services import redis_conn as _redis_cleanup
    await _redis_cleanup.redis.delete(f"captcha:{user_id}")

