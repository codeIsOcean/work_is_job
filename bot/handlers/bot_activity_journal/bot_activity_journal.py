# handlers/bot_activity_journal/bot_activity_journal.py
import logging
from aiogram import Router, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, Dict, Any
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

bot_activity_journal_router = Router()

from bot.config import LOG_CHANNEL_ID
from sqlalchemy.ext.asyncio import AsyncSession
from bot.services.group_journal_service import send_journal_event

async def send_activity_log(
    bot: Bot,
    event_type: str,
    user_data: Dict[str, Any],
    group_data: Dict[str, Any],
    additional_info: Optional[Dict[str, Any]] = None,
    status: str = "success",
    session: Optional[AsyncSession] = None
):
    """
    Отправляет лог активности в журнал группы (multi-tenant).
    Если журнал не привязан - пытается отправить в глобальный LOG_CHANNEL_ID (fallback).
    
    Args:
        bot: Экземпляр бота
        event_type: Тип события (ЗАПРОС_НА_ВСТУПЛЕНИЕ, НовыйПользователь, etc.)
        user_data: Данные пользователя
        group_data: Данные группы
        additional_info: Дополнительная информация
        status: Статус (success, failed, etc.)
        session: Сессия БД для multi-tenant (опционально)
    """
    try:
        group_id = group_data.get('chat_id')
        logger.info(f"📝 Попытка отправить лог активности: {event_type} для пользователя {user_data.get('first_name', '')} {user_data.get('last_name', '')} [@{user_data.get('username', '')}] [{user_data.get('user_id')}] в группе {group_data.get('title', '')} [{group_id}]")
        
        # Формируем сообщение в зависимости от типа события
        message_text = await format_activity_message(
            event_type, user_data, group_data, additional_info, status
        )
        
        logger.info(f"📝 Сформированное сообщение: {message_text[:100]}...")
        
        # Создаем клавиатуру с кнопками действий
        keyboard = await create_activity_keyboard(event_type, user_data, group_data)
        
        # Пытаемся отправить в журнал группы (multi-tenant)
        sent_to_group_journal = False
        if session and group_id:
            try:
                sent_to_group_journal = await send_journal_event(
                    bot=bot,
                    session=session,
                    group_id=group_id,
                    message_text=message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                
                if sent_to_group_journal:
                    logger.info(f"📝 Отправлен лог активности в журнал группы {group_id}: {event_type}")
                else:
                    logger.info(f"📝 Журнал группы {group_id} не привязан, отправляем в fallback: {event_type}")
            except Exception as journal_error:
                logger.error(f"❌ Ошибка при отправке в журнал группы {group_id}: {journal_error}")
                sent_to_group_journal = False
        
        # Fallback: отправляем в глобальный канал если не отправлено в журнал группы
        if not sent_to_group_journal and LOG_CHANNEL_ID:
            try:
                await bot.send_message(
                    chat_id=LOG_CHANNEL_ID,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info(f"📝 Отправлен лог активности в глобальный канал: {event_type}")
            except Exception as fallback_error:
                logger.error(f"❌ Ошибка при отправке в глобальный канал: {fallback_error}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке лога активности: {e}")
        logger.error(f"❌ Детали ошибки: {type(e).__name__}: {str(e)}")


async def format_activity_message(
    event_type: str,
    user_data: Dict[str, Any],
    group_data: Dict[str, Any],
    additional_info: Optional[Dict[str, Any]] = None,
    status: str = "success"
) -> str:
    """Форматирует сообщение для журнала активности"""
    
    # Получаем текущее время в GST
    gst_tz = pytz.timezone('Asia/Dubai')
    current_time = datetime.now(gst_tz).strftime("%d %B %Y г. %H:%M:%S GST")
    
    # Формируем информацию о пользователе
    user_id = user_data.get('user_id', 'N/A')
    username = user_data.get('username', '') or ''
    first_name = user_data.get('first_name', '') or ''
    last_name = user_data.get('last_name', '') or ''
    
    user_display = f"{first_name} {last_name}".strip()
    if username:
        user_display += f" [@{username}]"
    user_display += f" [{user_id}]"
    
    # Формируем информацию о группе
    group_title = group_data.get('title', 'N/A')
    group_username = group_data.get('username', '')
    group_id = group_data.get('chat_id', 'N/A')
    
    # Создаем кликабельную ссылку на группу
    if group_username:
        group_display = f"<a href='https://t.me/{group_username}'>{group_title}</a> (https://t.me/{group_username}) [@{group_username}][{group_id}]"
    else:
        group_display = f"<b>{group_title}</b> [{group_id}]"
    
    # Определяем цвет статуса
    status_emoji = "🟢" if status == "success" else "🔴"
    
    # Формируем сообщение в зависимости от типа события
    if event_type == "ЗАПРОС_НА_ВСТУПЛЕНИЕ":
        message = f"📬 #{event_type} {status_emoji}\n\n"
        message += f"• Кто: {user_display}\n"
        message += f"• Группа: {group_display}\n"
        
        if additional_info:
            captcha_status = additional_info.get('captcha_status', 'неизвестно')
            saved_to_db = additional_info.get('saved_to_db', False)
            message += f"#id{user_id} #{captcha_status} #RECAPTCHA\n"
            message += f"сохранен в бд? {'да' if saved_to_db else 'нет'}\n"
        
        message += f"👋Время: {current_time}"
        
    elif event_type == "НовыйПользователь":
        message = f"🆔 #{event_type} вступление не по приглашению\n\n"
        message += f"Группа: {group_display} #c{group_id}\n"
        message += f"Пользователь: {user_display} #user{user_id}\n"
        message += f"👋Время: {current_time}"
        
    elif event_type == "пользовательудален":
        initiator_data = additional_info.get('initiator', {}) if additional_info else {}
        first_name = initiator_data.get('first_name', '') or ''
        last_name = initiator_data.get('last_name', '') or ''
        initiator_name = f"{first_name} {last_name}".strip()
        initiator_username = initiator_data.get('username', '') or ''
        initiator_id = initiator_data.get('user_id', 'N/A')
        
        initiator_display = initiator_name
        if initiator_username:
            initiator_display += f" [@{initiator_username}]"
        initiator_display += f"[{initiator_id}]"
        
        message = f"⚠️Пользователь удален из чата #{event_type}\n\n"
        message += f"Группа: {group_display} #c{group_id}\n"
        message += f"Инициатор: {initiator_display} #user{initiator_id}\n"
        message += f"Пользователь: {user_display} #user{user_id}\n"
        message += f"Действие: Удаление из группы #kicked\n"
        message += f"✉️Время: {current_time}"
        
    elif event_type == "пользовательвышел":
        message = f"⚠️Пользователь покинул чат #{event_type}\n\n"
        message += f"Группа: {group_display} #c{group_id}\n"
        message += f"Пользователь: {user_display} #user{user_id}\n"
        message += f"👋Время: {current_time}"
        
    elif event_type == "Визуальная капча включена":
        message = f"🔐 <b>#Визуальная_капча_включена</b>\n\n"
        message += f"👤 <b>Кто:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}"
        
    elif event_type == "Визуальная капча выключена":
        message = f"🔓 <b>#Визуальная_капча_выключена</b>\n\n"
        message += f"👤 <b>Кто:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}"
        
    elif event_type == "Настройка мута новых пользователей включена":
        message = f"🔇 <b>#Настройка_мута_включена</b>\n\n"
        message += f"👤 <b>Кто:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}"
        
    elif event_type == "Настройка мута новых пользователей выключена":
        message = f"🔊 <b>#Настройка_мута_выключена</b>\n\n"
        message += f"👤 <b>Кто:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}"
        
    elif event_type == "БОТ_ДОБАВЛЕН_В_ГРУППУ":
        added_by_data = additional_info.get('added_by', {}) if additional_info else {}
        first_name = added_by_data.get('first_name', '') or ''
        last_name = added_by_data.get('last_name', '') or ''
        added_by_name = f"{first_name} {last_name}".strip()
        added_by_username = added_by_data.get('username', '') or ''
        added_by_id = added_by_data.get('user_id', 'N/A')
        
        added_by_display = added_by_name
        if added_by_username:
            added_by_display += f" [@{added_by_username}]"
        added_by_display += f" [{added_by_id}]"
        
        message = f"🤖 <b>#БОТ_ДОБАВЛЕН_В_ГРУППУ</b>\n\n"
        message += f"👤 <b>Кто добавил:</b> {added_by_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}"
    
    # Новые события для полноты журнала
    elif event_type == "CAPTCHA_PASSED":
        scammer_level = additional_info.get('scammer_level', 0) if additional_info else 0
        message = f"✅ <b>#КАПЧА_ПРОЙДЕНА</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📊 <b>Уровень риска:</b> {scammer_level}/100\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#captcha #passed #user{user_id}"
    
    elif event_type == "CAPTCHA_FAILED":
        reason = additional_info.get('reason', 'Не указано') if additional_info else 'Не указано'
        message = f"❌ <b>#КАПЧА_НЕ_ПРОЙДЕНА</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📝 <b>Причина:</b> {reason}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#captcha #failed #user{user_id}"
    
    elif event_type == "CAPTCHA_TIMEOUT":
        message = f"⏱️ <b>#КАПЧА_ТАЙМАУТ</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#captcha #timeout #user{user_id}"
    
    elif event_type == "AUTO_MUTE_SCAMMER":
        scammer_level = additional_info.get('scammer_level', 0) if additional_info else 0
        scammer_reason = additional_info.get('reason', 'Обнаружен как скаммер') if additional_info else 'Обнаружен как скаммер'
        message = f"🤖 <b>#АВТОМУТ_СКАММЕРА</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📊 <b>Уровень скама:</b> {scammer_level}/100\n"
        message += f"📝 <b>Причина:</b> {scammer_reason}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#automute #scammer #user{user_id}"
    
    elif event_type == "SCAMMER_DETECTED":
        scammer_level = additional_info.get('scammer_level', 0) if additional_info else 0
        violation_type = additional_info.get('violation_type', 'unknown') if additional_info else 'unknown'
        message = f"🚨 <b>#СКАММЕР_ОБНАРУЖЕН</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📊 <b>Уровень:</b> {scammer_level}/100\n"
        message += f"🔍 <b>Тип нарушения:</b> {violation_type}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#scammer #detected #user{user_id}"
    
    elif event_type == "AUTO_MUTE_SCAMMERS_TOGGLED":
        enabled = additional_info.get('enabled', False) if additional_info else False
        status_text = "включен" if enabled else "выключен"
        emoji = "🟢" if enabled else "🔴"
        message = f"{emoji} <b>#Автомут_скамеров_{status_text}</b>\n\n"
        message += f"👤 <b>Кто:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#settings #automute"
    
    elif event_type == "USER_BANNED":
        initiator_data = additional_info.get('initiator', {}) if additional_info else {}
        reason = additional_info.get('reason', 'Не указано') if additional_info else 'Не указано'
        
        initiator_name = f"{initiator_data.get('first_name', '')} {initiator_data.get('last_name', '')}".strip()
        initiator_username = initiator_data.get('username', '') or ''
        initiator_id = initiator_data.get('user_id', 'N/A')
        
        initiator_display = initiator_name or 'Система'
        if initiator_username:
            initiator_display += f" [@{initiator_username}]"
        if initiator_id != 'N/A':
            initiator_display += f" [{initiator_id}]"
        
        message = f"🚫 <b>#ПОЛЬЗОВАТЕЛЬ_ЗАБАНЕН</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"👮 <b>Инициатор:</b> {initiator_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📝 <b>Причина:</b> {reason}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#ban #user{user_id}"
    
    elif event_type == "USER_UNBANNED":
        initiator_data = additional_info.get('initiator', {}) if additional_info else {}
        initiator_name = f"{initiator_data.get('first_name', '')} {initiator_data.get('last_name', '')}".strip()
        initiator_username = initiator_data.get('username', '') or ''
        initiator_id = initiator_data.get('user_id', 'N/A')
        
        initiator_display = initiator_name or 'Система'
        if initiator_username:
            initiator_display += f" [@{initiator_username}]"
        if initiator_id != 'N/A':
            initiator_display += f" [{initiator_id}]"
        
        message = f"✅ <b>#ПОЛЬЗОВАТЕЛЬ_РАЗБАНЕН</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"👮 <b>Инициатор:</b> {initiator_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#unban #user{user_id}"
    
    else:
        # Общий формат для неизвестных событий
        message = f"📝 <b>#{event_type}</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"⏰ <b>Время:</b> {current_time}"
    
    return message


async def create_activity_keyboard(
    event_type: str,
    user_data: Dict[str, Any],
    group_data: Dict[str, Any]
) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру с кнопками действий для журнала"""
    
    buttons = []
    
    if event_type == "ЗАПРОС_НА_ВСТУПЛЕНИЕ":
        # Кнопки для запроса на вступление
        buttons.append([
            InlineKeyboardButton(
                text="✅ Впустить в группу",
                callback_data=f"approve_user_{user_data.get('user_id')}_{group_data.get('chat_id')}"
            ),
            InlineKeyboardButton(
                text="🔇 Мут навсегда",
                callback_data=f"mute_user_{user_data.get('user_id')}_{group_data.get('chat_id')}"
            )
        ])
        
    elif event_type == "НовыйПользователь":
        # Кнопки для нового пользователя
        buttons.append([
            InlineKeyboardButton(
                text="🔇 Мут",
                callback_data=f"mute_user_{user_data.get('user_id')}_{group_data.get('chat_id')}"
            ),
            InlineKeyboardButton(
                text="🚫 Бан",
                callback_data=f"ban_user_{user_data.get('user_id')}_{group_data.get('chat_id')}"
            )
        ])
    
    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    return None


# Обработчики callback кнопок
@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("approve_user_"))
async def approve_user_callback(callback):
    """Обработчик кнопки одобрения пользователя"""
    try:
        # Извлекаем данные из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        group_id = int(parts[3])
        
        # Здесь можно добавить логику одобрения пользователя
        await callback.answer("✅ Пользователь одобрен", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при одобрении пользователя: {e}")
        await callback.answer("❌ Ошибка при одобрении", show_alert=True)


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("mute_user_"))
async def mute_user_callback(callback):
    """Обработчик кнопки мута пользователя"""
    try:
        # Извлекаем данные из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        group_id = int(parts[3])
        
        # Здесь можно добавить логику мута пользователя
        await callback.answer("🔇 Пользователь заглушен", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при муте пользователя: {e}")
        await callback.answer("❌ Ошибка при муте", show_alert=True)


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("ban_user_"))
async def ban_user_callback(callback):
    """Обработчик кнопки бана пользователя"""
    try:
        # Извлекаем данные из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        group_id = int(parts[3])
        
        # Здесь можно добавить логику бана пользователя
        await callback.answer("🚫 Пользователь забанен", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при бане пользователя: {e}")
        await callback.answer("❌ Ошибка при бане", show_alert=True)
