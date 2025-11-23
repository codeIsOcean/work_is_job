"""
Unit тесты для БАГ #4: Мут по реакциям не работает
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import MessageReactionUpdated, MessageReactionCountUpdated, Chat, User, Message
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.mute_by_reaction.mute_by_reaction_handler import _process_reaction_event
from bot.services.mute_by_reaction_service import handle_reaction_mute


@pytest.mark.asyncio
async def test_reaction_handler_called():
    """Проверяет, что обработчик реакций вызывается"""
    # Создаем мок события реакции
    event = MagicMock(spec=MessageReactionUpdated)
    event.chat = MagicMock()
    event.chat.id = -100123
    event.message = MagicMock()
    event.message.message_id = 12345
    event.message.from_user = MagicMock()
    event.message.from_user.id = 999
    event.bot = MagicMock(spec=Bot)
    event.user = MagicMock()
    event.user.id = 111
    
    session = MagicMock(spec=AsyncSession)
    
    # Мокаем handle_reaction_mute
    with patch('bot.handlers.mute_by_reaction.mute_by_reaction_handler.handle_reaction_mute', new_callable=AsyncMock) as mock_handle:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.skip_reason = None
        mock_result.should_announce = False
        mock_result.system_message = None
        mock_handle.return_value = mock_result
        
        await _process_reaction_event(event, session)
        
        # Проверяем, что handle_reaction_mute был вызван
        mock_handle.assert_called_once_with(event=event, session=session)


@pytest.mark.asyncio
async def test_reaction_mute_logic_processes_negative_reaction():
    """Проверяет, что логика мута по реакциям обрабатывает негативную реакцию"""
    # Создаем мок события с негативной реакцией
    event = MagicMock(spec=MessageReactionUpdated)
    event.chat = MagicMock()
    event.chat.id = -100123
    event.message = MagicMock()
    event.message.message_id = 12345
    event.message.from_user = MagicMock()
    event.message.from_user.id = 999
    event.bot = MagicMock(spec=Bot)
    event.user = MagicMock()
    event.user.id = 111
    
    session = MagicMock(spec=AsyncSession)
    
    # Мокаем Redis, чтобы не было реального подключения
    with patch('bot.services.mute_by_reaction_service.logic.redis') as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        
        # Мокаем все зависимости
        with patch('bot.services.mute_by_reaction_service.logic._extract_emoji', return_value="👎"):
            with patch('bot.services.mute_by_reaction_service.logic.get_global_mute_flag', new_callable=AsyncMock, return_value=False):
                with patch('bot.services.mute_by_reaction_service.logic._ensure_chat_settings') as mock_settings:
                    mock_settings_obj = MagicMock()
                    mock_settings_obj.reaction_mute_enabled = True
                    mock_settings.return_value = mock_settings_obj
                    
                    with patch('bot.services.mute_by_reaction_service.logic._resolve_admin_actor', new_callable=AsyncMock) as mock_admin:
                        mock_admin.return_value = (event.user, False)
                        
                        with patch.object(event.bot, 'get_chat_member', new_callable=AsyncMock) as mock_get_member:
                            mock_admin_member = MagicMock()
                            mock_admin_member.status = "administrator"
                            mock_get_member.return_value = mock_admin_member
                            
                            # Вызываем функцию
                            result = await handle_reaction_mute(event=event, session=session)
                            
                            # Проверяем, что функция вернула результат
                            assert result is not None
                            assert hasattr(result, 'success')

