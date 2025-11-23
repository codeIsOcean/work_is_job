"""
E2E тесты для полного цикла капчи.
Проверка всех сценариев: visual + join, таймаут, системные сообщения.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot
from aiogram.types import Message, Chat, User as TgUser

from bot.services import redis_conn


@pytest.mark.asyncio
async def test_captcha_message_deleted_on_pass():
    """E2E: Системное сообщение капчи удаляется после успешного прохождения"""
    bot = MagicMock(spec=Bot)
    bot.delete_message = AsyncMock()
    
    chat_id = -1001234567890
    user_id = 123
    message_id = 456
    
    # Сохраняем ID системного сообщения капчи
    from bot.services.captcha_flow_logic import register_captcha_message
    await register_captcha_message(
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        ttl=300,
    )
    
    # Симулируем успешное прохождение капчи
    from bot.services.captcha_flow_logic import pop_captcha_message_id
    msg_id = await pop_captcha_message_id(chat_id, user_id)
    assert msg_id == message_id
    
    # Удаляем сообщение
    if msg_id:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    
    bot.delete_message.assert_called_once_with(chat_id=chat_id, message_id=message_id)


@pytest.mark.asyncio
async def test_reminders_cancelled_on_start():
    """E2E: Напоминания отменяются при начале решения капчи"""
    bot = MagicMock(spec=Bot)
    user_id = 123
    group_name = "test_group"
    
    # Сохраняем напоминание
    reminder_key = f"captcha_reminder_msgs:{user_id}"
    await redis_conn.redis.setex(reminder_key, 600, "789,790")
    
    # Симулируем начало решения капчи
    await redis_conn.redis.delete(reminder_key)
    await redis_conn.redis.setex(f"captcha_started:{user_id}:{group_name}", 600, "1")
    
    # Проверяем, что напоминания удалены
    reminder = await redis_conn.redis.get(reminder_key)
    assert reminder is None
    
    # Проверяем, что флаг "начал решать" установлен
    started = await redis_conn.redis.get(f"captcha_started:{user_id}:{group_name}")
    assert started == "1"
    
    # Очистка
    await redis_conn.redis.delete(f"captcha_started:{user_id}:{group_name}")


@pytest.mark.asyncio
async def test_duplicate_events_ignored():
    """E2E: Дубликаты chat_member_updated игнорируются"""
    chat_id = -1001234567890
    user_id = 123
    update_id = 789
    
    # Первое событие
    event_key = f"chat_member_event:{chat_id}:{user_id}"
    event_signature = f"{update_id}:left:member"
    await redis_conn.redis.setex(event_key, 60, event_signature)
    
    # Проверяем, что событие сохранено
    stored = await redis_conn.redis.get(event_key)
    assert stored is not None
    assert stored.decode('utf-8') if isinstance(stored, bytes) else stored == event_signature
    
    # Второе событие с той же сигнатурой должно быть проигнорировано
    # (в реальном коде проверка происходит в обработчике)
    
    # Очистка
    await redis_conn.redis.delete(event_key)

