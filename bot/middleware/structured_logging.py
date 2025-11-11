# middleware/structured_logging.py
"""
Middleware для структурированного логирования апдейтов от Telegram
"""
import logging
import json
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update, Message, CallbackQuery, ChatMemberUpdated, ChatJoinRequest
from datetime import datetime

logger = logging.getLogger(__name__)

# Отключаем встроенное логирование aiogram для апдейтов
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)


class StructuredLoggingMiddleware(BaseMiddleware):
    """Middleware для структурированного логирования апдейтов"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Логирует апдейт в структурированном виде"""
        
        # КРИТИЧНО: Отключаем старое логирование aiogram ПЕРЕД обработкой
        # Это должно быть первым действием в middleware
        # Сохраняем старые уровни для восстановления
        old_levels = {}
        for log_name in ["aiogram.dispatcher", "aiogram.event", "aiogram"]:
            lg = logging.getLogger(log_name)
            old_levels[log_name] = lg.level
            lg.setLevel(logging.ERROR)  # Только ошибки - отключаем INFO логи
        
        # Определяем тип апдейта
        update_type = None
        update_data = {}
        
        if event.message:
            update_type = "MESSAGE"
            msg = event.message
            update_data = {
                "update_id": event.update_id,
                "type": "message",
                "message_id": msg.message_id,
                "from": {
                    "id": msg.from_user.id if msg.from_user else None,
                    "username": msg.from_user.username if msg.from_user else None,
                    "first_name": msg.from_user.first_name if msg.from_user else None,
                    "last_name": msg.from_user.last_name if msg.from_user else None,
                },
                "chat": {
                    "id": msg.chat.id,
                    "type": msg.chat.type,
                    "title": msg.chat.title if hasattr(msg.chat, 'title') else None,
                    "username": msg.chat.username if hasattr(msg.chat, 'username') else None,
                },
                "text": msg.text[:100] if msg.text else None,
                "date": msg.date.isoformat() if msg.date else None,
            }
            
        elif event.callback_query:
            update_type = "CALLBACK_QUERY"
            cb = event.callback_query
            update_data = {
                "update_id": event.update_id,
                "type": "callback_query",
                "callback_id": cb.id,
                "from": {
                    "id": cb.from_user.id if cb.from_user else None,
                    "username": cb.from_user.username if cb.from_user else None,
                    "first_name": cb.from_user.first_name if cb.from_user else None,
                },
                "data": cb.data[:50] if cb.data else None,
                "message": {
                    "message_id": cb.message.message_id if cb.message else None,
                    "chat_id": cb.message.chat.id if cb.message else None,
                } if cb.message else None,
            }
            
        elif event.chat_member:
            update_type = "CHAT_MEMBER_UPDATED"
            cm = event.chat_member
            update_data = {
                "update_id": event.update_id,
                "type": "chat_member_updated",
                "chat": {
                    "id": cm.chat.id,
                    "type": cm.chat.type,
                    "title": cm.chat.title if hasattr(cm.chat, 'title') else None,
                    "username": cm.chat.username if hasattr(cm.chat, 'username') else None,
                },
                "from": {
                    "id": cm.from_user.id if cm.from_user else None,
                    "username": cm.from_user.username if cm.from_user else None,
                    "first_name": cm.from_user.first_name if cm.from_user else None,
                },
                "old_status": cm.old_chat_member.status if isinstance(cm.old_chat_member.status, str) else cm.old_chat_member.status.value if cm.old_chat_member else None,
                "new_status": cm.new_chat_member.status if isinstance(cm.new_chat_member.status, str) else cm.new_chat_member.status.value if cm.new_chat_member else None,
                "user": {
                    "id": cm.new_chat_member.user.id if cm.new_chat_member else None,
                    "username": cm.new_chat_member.user.username if cm.new_chat_member else None,
                    "first_name": cm.new_chat_member.user.first_name if cm.new_chat_member else None,
                } if cm.new_chat_member else None,
            }
            
        elif event.chat_join_request:
            update_type = "CHAT_JOIN_REQUEST"
            cjr = event.chat_join_request
            update_data = {
                "update_id": event.update_id,
                "type": "chat_join_request",
                "chat": {
                    "id": cjr.chat.id,
                    "type": cjr.chat.type,
                    "title": cjr.chat.title if hasattr(cjr.chat, 'title') else None,
                    "username": cjr.chat.username if hasattr(cjr.chat, 'username') else None,
                },
                "from": {
                    "id": cjr.from_user.id if cjr.from_user else None,
                    "username": cjr.from_user.username if cjr.from_user else None,
                    "first_name": cjr.from_user.first_name if cjr.from_user else None,
                    "last_name": cjr.from_user.last_name if cjr.from_user else None,
                },
                "date": cjr.date.isoformat() if cjr.date else None,
            }
        else:
            update_type = "UNKNOWN"
            update_data = {
                "update_id": event.update_id,
                "type": "unknown",
            }
        
        # Логируем в структурированном виде (ЗАМЕНЯЕМ старое логирование)
        # Отключаем все INFO логирование aiogram перед выводом нашего лога
        for log_name in ["aiogram.dispatcher", "aiogram.event", "aiogram"]:
            lg = logging.getLogger(log_name)
            lg.setLevel(logging.ERROR)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Формируем структурированное сообщение одной строкой для удобства
        log_parts = [f"📩 [{timestamp}] === {update_type} ===", f"   Update ID: {event.update_id}"]
        
        # Красиво форматируем данные
        if update_data:
            for key, value in update_data.items():
                if isinstance(value, dict):
                    log_parts.append(f"   {key}:")
                    for sub_key, sub_value in value.items():
                        if sub_value:
                            log_parts.append(f"      {sub_key}: {sub_value}")
                elif value:
                    log_parts.append(f"   {key}: {value}")
        
        # Выводим структурированный лог
        logger.info("\n".join(log_parts))
        
        # Вызываем обработчик
        try:
            result = await handler(event, data)
            
            # Логируем результат обработки
            if hasattr(event, 'update_id'):
                logger.info(f"✅ Update id={event.update_id} обработан успешно")
            
            # Восстанавливаем уровни логирования aiogram
            for log_name, old_level in old_levels.items():
                lg = logging.getLogger(log_name)
                lg.setLevel(old_level)
            
            return result
        except Exception as e:
            # Восстанавливаем уровни логирования даже при ошибке
            for log_name, old_level in old_levels.items():
                lg = logging.getLogger(log_name)
                lg.setLevel(old_level)
            logger.error(f"❌ Ошибка обработки update id={event.update_id}: {e}")
            raise

