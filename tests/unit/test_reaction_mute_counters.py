"""
Unit тесты для реакционного мута с счетчиками.
ФИКС №8: Проверка логики по количеству негативных реакций.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta
from aiogram.types import MessageReactionUpdated, Message, Chat, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.mute_by_reaction_service.logic import (
    handle_reaction_mute,
    REACTION_COUNT_RULES,
    NEGATIVE_REACTIONS,
)


def _make_reaction_event(emoji: str, chat_id: int, message_id: int, target_user_id: int) -> MessageReactionUpdated:
    """Создает мок MessageReactionUpdated события"""
    from aiogram.types import ReactionTypeEmoji
    
    target_user = MagicMock(spec=TgUser)
    target_user.id = target_user_id
    
    message = MagicMock(spec=Message)
    message.message_id = message_id
    message.from_user = target_user
    
    chat = MagicMock(spec=Chat)
    chat.id = chat_id
    
    reaction_type = MagicMock(spec=ReactionTypeEmoji)
    reaction_type.emoji = emoji
    
    event = MagicMock(spec=MessageReactionUpdated)
    event.bot = MagicMock()
    event.chat = chat
    event.message = message
    event.reaction = reaction_type
    event.new_reactions = [reaction_type]
    event.old_reactions = []
    event.user = MagicMock(id=123)  # Админ
    
    return event


@pytest.mark.asyncio
async def test_reaction_counter_first_warn():
    """Тест: 1 негативная реакция → предупреждение"""
    event = _make_reaction_event("👎", chat_id=-100123, message_id=456, target_user_id=789)
    session = MagicMock(spec=AsyncSession)
    
    # Мокаем проверки
    with patch('bot.services.mute_by_reaction_service.logic._ensure_chat_settings') as mock_settings, \
         patch('bot.services.mute_by_reaction_service.logic._resolve_admin_actor') as mock_admin, \
         patch('bot.services.mute_by_reaction_service.logic.get_global_mute_flag', return_value=False), \
         patch('bot.services.redis_conn.redis.get', return_value=None), \
         patch('bot.services.redis_conn.redis.setex', return_value=None), \
         patch('bot.services.mute_by_reaction_service.logic.log_warning_reaction', new_callable=AsyncMock) as mock_warn:
        
        mock_settings.return_value = MagicMock(reaction_mute_enabled=True)
        mock_admin.return_value = (MagicMock(id=123), False)
        
        event.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))
        
        result = await handle_reaction_mute(event, session)
        
        # Проверяем, что было предупреждение (не мут)
        assert result.success
        assert not result.should_announce
        mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_reaction_counter_second_mute():
    """Тест: 2 негативные реакции → мут 7 дней"""
    event = _make_reaction_event("🤢", chat_id=-100123, message_id=456, target_user_id=789)
    session = MagicMock(spec=AsyncSession)
    
    with patch('bot.services.mute_by_reaction_service.logic._ensure_chat_settings') as mock_settings, \
         patch('bot.services.mute_by_reaction_service.logic._resolve_admin_actor') as mock_admin, \
         patch('bot.services.mute_by_reaction_service.logic.get_global_mute_flag', return_value=False), \
         patch('bot.services.redis_conn.redis.get', return_value="1"), \
         patch('bot.services.redis_conn.redis.setex', return_value=None), \
         patch.object(event.bot, 'restrict_chat_member', new_callable=AsyncMock) as mock_restrict:
        
        mock_settings.return_value = MagicMock(reaction_mute_enabled=True)
        mock_admin.return_value = (MagicMock(id=123), False)
        event.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator", can_restrict_members=True))
        event.bot.id = 999
        
        result = await handle_reaction_mute(event, session)
        
        # Проверяем, что был мут
        assert result.success
        mock_restrict.assert_called_once()


@pytest.mark.asyncio
async def test_reaction_counter_third_forever():
    """Тест: 3+ негативные реакции → мут навсегда +15 баллов"""
    event = _make_reaction_event("💩", chat_id=-100123, message_id=456, target_user_id=789)
    session = MagicMock(spec=AsyncSession)
    
    with patch('bot.services.mute_by_reaction_service.logic._ensure_chat_settings') as mock_settings, \
         patch('bot.services.mute_by_reaction_service.logic._resolve_admin_actor') as mock_admin, \
         patch('bot.services.mute_by_reaction_service.logic.get_global_mute_flag', return_value=False), \
         patch('bot.services.redis_conn.redis.get', return_value="2"), \
         patch('bot.services.redis_conn.redis.setex', return_value=None), \
         patch('bot.services.mute_by_reaction_service.logic.mute_across_groups', new_callable=AsyncMock) as mock_multi, \
         patch.object(event.bot, 'restrict_chat_member', new_callable=AsyncMock):
        
        mock_settings.return_value = MagicMock(reaction_mute_enabled=True)
        mock_admin.return_value = (MagicMock(id=123), False)
        event.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator", can_restrict_members=True))
        event.bot.id = 999
        mock_multi.return_value = []
        
        session.get = AsyncMock(return_value=None)  # Нет UserScore
        
        result = await handle_reaction_mute(event, session)
        
        # Проверяем, что был мультигрупповой мут
        assert result.success
        mock_multi.assert_called_once()

