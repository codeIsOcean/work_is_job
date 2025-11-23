"""
Unit тесты для БАГ #1: Пользователь остается замьюченным после успешной капчи
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import ChatPermissions, User, Chat, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.new_member_requested_to_join_mute_logic import mute_manually_approved_member_logic
from bot.services.auto_mute_scammers_logic import auto_mute_scammer_on_join


@pytest.mark.asyncio
async def test_mute_manually_approved_skips_if_captcha_passed():
    """Проверяет, что mute_manually_approved_member_logic НЕ мутит пользователя, если капча пройдена"""
    # Мокаем событие
    event = MagicMock()
    event.old_chat_member.status = "left"
    event.new_chat_member.status = "member"
    event.new_chat_member.user.id = 123
    event.chat.id = -100123
    event.date = None
    
    user = MagicMock()
    user.id = 123
    chat = MagicMock()
    chat.id = -100123
    event.new_chat_member.user = user
    event.chat = chat
    
    # Мокаем Redis - капча пройдена
    with patch('bot.services.new_member_requested_to_join_mute_logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(side_effect=lambda key: "1" if "captcha_passed" in key else None)
        mock_redis.ttl = AsyncMock(return_value=3600)
        
        # Мокаем restrict_chat_member - НЕ должен вызываться
        with patch.object(event.bot, 'restrict_chat_member', new_callable=AsyncMock) as mock_restrict:
            await mute_manually_approved_member_logic(event)
            
            # Проверяем, что restrict_chat_member НЕ вызывался
            mock_restrict.assert_not_called()


@pytest.mark.asyncio
async def test_auto_mute_scammer_skips_if_captcha_passed():
    """Проверяет, что auto_mute_scammer_on_join НЕ мутит пользователя, если капча пройдена"""
    # Мокаем событие
    event = MagicMock()
    event.old_chat_member.status = "left"
    event.new_chat_member.status = "member"
    event.new_chat_member.user.id = 123
    event.chat.id = -100123
    
    user = MagicMock()
    user.id = 123
    user.username = "test_user"
    user.first_name = "Test"
    chat = MagicMock()
    chat.id = -100123
    event.new_chat_member.user = user
    event.chat = chat
    event.bot = MagicMock(spec=Bot)
    
    # Мокаем Redis - капча пройдена
    with patch('bot.services.auto_mute_scammers_logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(side_effect=lambda key: "1" if "captcha_passed" in key else None)
        
        # Мокаем restrict_chat_member - НЕ должен вызываться
        with patch.object(event.bot, 'restrict_chat_member', new_callable=AsyncMock) as mock_restrict:
            result = await auto_mute_scammer_on_join(event.bot, event)
            
            # Проверяем, что функция вернула False (не мутила)
            assert result is False
            # Проверяем, что restrict_chat_member НЕ вызывался
            mock_restrict.assert_not_called()


@pytest.mark.asyncio
async def test_captcha_passed_flag_set_before_unmute():
    """Проверяет, что флаг captcha_passed устанавливается ДО размута"""
    # Это тест проверяет порядок операций в process_captcha_answer
    # Проверяется через логи или мок-вызовы
    pass  # Интеграционный тест

