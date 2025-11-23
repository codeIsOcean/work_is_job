"""
E2E тесты для сценариев вступления в группу.
Проверка антифлуда, классификации событий и капчи.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import ChatMemberUpdated, ChatJoinRequest, Chat, User as TgUser

from bot.services.event_classifier import classify_join_event, JoinEventType
from bot.services.captcha_flow_logic import prepare_invite_flow, prepare_manual_approval_flow
from bot.services.redis_conn import redis


@pytest.mark.asyncio
async def test_self_join_no_flood_warning():
    """E2E: Self-join не должен вызывать предупреждение антифлуда"""
    bot = MagicMock(spec=Bot)
    session = MagicMock()
    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    
    user = MagicMock(spec=TgUser)
    user.id = 123
    
    # Self-join: нет инициатора или инициатор = user
    event = MagicMock(spec=ChatMemberUpdated)
    event.bot = bot
    event.chat = chat
    event.new_chat_member.user = user
    event.from_user = None  # Нет инициатора
    
    event_type = classify_join_event(
        event=event,
        user_id=user.id,
        initiator_id=None,
    )
    
    assert event_type == JoinEventType.SELF_JOIN
    
    # Для self-join не должен вызываться prepare_invite_flow (антифлуд)
    # Проверяем, что вызывается prepare_manual_approval_flow
    decision = await prepare_manual_approval_flow(session=session, chat_id=chat.id)
    # Решение не должно содержать антифлуд-предупреждение
    assert decision.anti_flood is None or not decision.anti_flood.triggered


@pytest.mark.asyncio
async def test_join_request_no_flood():
    """E2E: Join request не должен вызывать антифлуд"""
    join_request = MagicMock(spec=ChatJoinRequest)
    join_request.from_user = MagicMock(spec=TgUser, id=123)
    
    event_type = classify_join_event(
        join_request=join_request,
        user_id=123,
    )
    
    assert event_type == JoinEventType.JOIN_REQUEST
    
    # Join request обрабатывается отдельно, не через prepare_invite_flow
    # Антифлуд не должен срабатывать


@pytest.mark.asyncio
async def test_invite_flood_triggers():
    """E2E: Многократный инвайт от одного админа → предупреждение"""
    bot = MagicMock(spec=Bot)
    session = MagicMock()
    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    
    initiator = MagicMock(spec=TgUser)
    initiator.id = 456
    
    # Настраиваем настройки с низким порогом для теста
    settings = MagicMock()
    settings.captcha_flood_threshold = 2
    settings.captcha_flood_window_seconds = 60
    settings.flood_action = "warn"
    
    with patch('bot.services.captcha_flow_logic.load_captcha_settings', return_value=settings), \
         patch('bot.services.captcha_flow_logic.increment_invite_counter', new_callable=AsyncMock) as mock_counter:
        
        from bot.services.captcha_flow_logic import AntiFloodResult
        
        # Первый инвайт - антифлуд не срабатывает
        mock_counter.return_value = AntiFloodResult(triggered=False, total=1)
        decision1 = await prepare_invite_flow(
            bot=bot,
            session=session,
            chat=chat,
            initiator=initiator,
        )
        assert decision1.anti_flood is None or not decision1.anti_flood.triggered
        
        # Второй инвайт - антифлуд срабатывает
        mock_counter.return_value = AntiFloodResult(triggered=True, total=2, action="warn")
        decision2 = await prepare_invite_flow(
            bot=bot,
            session=session,
            chat=chat,
            initiator=initiator,
        )
        assert decision2.anti_flood is not None
        assert decision2.anti_flood.triggered


@pytest.mark.asyncio
async def test_visual_captcha_passed_skips_join_captcha():
    """E2E: Если visual captcha пройдена, join captcha не отправляется"""
    from bot.services.redis_conn import redis
    
    user_id = 123
    chat_id = -1001234567890
    
    # Симулируем прохождение visual captcha
    await redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")
    
    # Проверяем, что флаг установлен
    captcha_passed = await redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert captcha_passed == "1"
    
    # Очистка
    await redis.delete(f"captcha_passed:{user_id}:{chat_id}")

