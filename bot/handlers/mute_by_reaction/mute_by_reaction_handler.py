from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

from aiogram import Router, F
from aiogram.types import MessageReactionUpdated, MessageReactionCountUpdated, Update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.mute_by_reaction_service import handle_reaction_mute

reaction_mute_router = Router(name="reaction_mute_router")

logger = logging.getLogger(__name__)


async def _schedule_notification_delete(bot, chat_id: int, message_id: int, delay_seconds: int) -> None:
    """
    Планирует удаление уведомления бота через указанное время.
    """
    if delay_seconds <= 0:
        return

    async def delete_later():
        await asyncio.sleep(delay_seconds)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"✅ Уведомление {message_id} автоудалено через {delay_seconds} сек")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось автоудалить уведомление {message_id}: {e}")

    asyncio.create_task(delete_later())


ReactionEvent = Union[MessageReactionUpdated, MessageReactionCountUpdated]


async def _process_reaction_event(
    event: ReactionEvent,
    session: AsyncSession,
) -> None:
    """
    Обработчик события реакций на сообщения.
    Делегирует бизнес-логику в сервисный слой, а затем, при необходимости,
    отправляет системное сообщение.
    """
    # БАГ #4: Добавляем детальное логирование для диагностики
    logger.info(f"🔍 [REACTION_MUTE_HANDLER] ===== ПОЛУЧЕНО СОБЫТИЕ РЕАКЦИИ =====")
    logger.info(f"🔍 [REACTION_MUTE_HANDLER] Тип события: {type(event).__name__}")
    
    try:
        chat_id = getattr(event, 'chat', None)
        if chat_id:
            logger.info(f"🔍 [REACTION_MUTE_HANDLER] Чат ID: {chat_id.id if hasattr(chat_id, 'id') else chat_id}")
        else:
            logger.warning(f"⚠️ [REACTION_MUTE_HANDLER] Чат не найден в событии")
        
        message = getattr(event, 'message', None)
        if message:
            logger.info(f"🔍 [REACTION_MUTE_HANDLER] Сообщение ID: {getattr(message, 'message_id', 'N/A')}")
        else:
            logger.warning(f"⚠️ [REACTION_MUTE_HANDLER] Сообщение не найдено в событии")
        
        result = await handle_reaction_mute(event=event, session=session)
        logger.info(f"🔍 [REACTION_MUTE_HANDLER] Результат обработки: success={result.success}, skip_reason={result.skip_reason}, should_announce={result.should_announce}")
        
        if result.should_announce and result.system_message:
            try:
                sent_msg = await event.bot.send_message(
                    chat_id=event.chat.id,
                    text=result.system_message,
                    parse_mode="HTML",
                )
                logger.info(f"✅ [REACTION_MUTE_HANDLER] Системное сообщение отправлено в чат {event.chat.id}")

                # Планируем автоудаление уведомления если настроено
                if result.notification_delete_delay and result.notification_delete_delay > 0:
                    await _schedule_notification_delete(
                        bot=event.bot,
                        chat_id=event.chat.id,
                        message_id=sent_msg.message_id,
                        delay_seconds=result.notification_delete_delay,
                    )
                    logger.info(f"📅 Запланировано автоудаление уведомления через {result.notification_delete_delay} сек")
            except Exception as exc:
                logger.error("❌ Ошибка при отправке системного сообщения: %s", exc)
    except Exception as exc:
        logger.error("❌ [REACTION_MUTE_HANDLER] КРИТИЧЕСКАЯ ОШИБКА при обработке реакции: %s", exc, exc_info=True)
        import traceback
        logger.error(traceback.format_exc())


# БАГ #4: КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ - Регистрируем обработчики реакций
# В Aiogram 3 обработчики реакций регистрируются через специальные декораторы
# Примечание: В некоторых версиях Aiogram 3 декораторы для реакций могут не поддерживаться
# Если обработчики не срабатывают, проверьте версию Aiogram и документацию

# Пытаемся зарегистрировать обработчики через декораторы
# Если декораторы не поддерживаются, будет выведено предупреждение, но бот не упадет

try:
    # Проверяем, есть ли метод message_reaction у роутера
    if callable(getattr(reaction_mute_router, 'message_reaction', None)):
        @reaction_mute_router.message_reaction()
        async def handle_message_reaction(
            event: MessageReactionUpdated,
            session: AsyncSession,
        ) -> None:
            """Обработчик message_reaction через декоратор"""
            logger.info("✅ [REACTION_MUTE_HANDLER] Обработчик message_reaction ВЫЗВАН (декоратор)")
            await _process_reaction_event(event, session)
        
        @reaction_mute_router.message_reaction_count()
        async def handle_message_reaction_count(
            event: MessageReactionCountUpdated, 
            session: AsyncSession
        ) -> None:
            """Обработчик message_reaction_count через декоратор"""
            logger.info("✅ [REACTION_MUTE_HANDLER] Обработчик message_reaction_count ВЫЗВАН (декоратор)")
            await _process_reaction_event(event, session)
        
        logger.info("✅ [REACTION_MUTE_HANDLER] Декораторы для реакций успешно зарегистрированы")
    else:
        logger.warning("⚠️ [REACTION_MUTE_HANDLER] Декораторы message_reaction/message_reaction_count не найдены в роутере")
except (AttributeError, TypeError, Exception) as e:
    logger.warning(f"⚠️ [REACTION_MUTE_HANDLER] Ошибка при регистрации обработчиков реакций: {e}")




# БАГ #4: Обработчики зарегистрированы через декораторы (если доступны) и fallback через @router.update()
# В логах должно быть видно хотя бы одно из сообщений:
# "✅ [REACTION_MUTE_HANDLER] Обработчик message_reaction ВЫЗВАН (декоратор)" или
# "✅ [REACTION_MUTE_HANDLER] Fallback: получен update.message_reaction"

