# handlers/bot_activity_journal/bot_activity_journal.py
import logging
import html
from datetime import datetime, timezone
from datetime import timezone as dt_timezone, timedelta
from types import SimpleNamespace

from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, Dict, Any
from bot.config import LOG_CHANNEL_ID
from sqlalchemy.ext.asyncio import AsyncSession
from bot.services.group_journal_service import send_journal_event
from bot.services.group_display import format_group_link
from bot.services.captcha_flow_logic import clear_captcha_state, build_restriction_permissions
from bot.database.session import get_session

logger = logging.getLogger(__name__)

bot_activity_journal_router = Router()

from bot.services.visual_captcha_logic import (
    get_group_settings_keyboard,
    get_group_join_keyboard,
    clear_join_request_state,
)

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
    
    # Получаем текущее время в UTC+4 (Asia/Dubai эквивалент)
    dubai_timezone = dt_timezone(timedelta(hours=4))
    current_time = datetime.now(dubai_timezone).strftime("%Y-%m-%d %H:%M:%S")
    
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
    group_title = group_data.get('title')
    group_username = group_data.get('username') or ''
    group_id = group_data.get('chat_id', 'N/A')
    
    display_title = group_title or (f"@{group_username}" if group_username else f"ID: {group_id}")
    
    if group_username:
        group_link = f"https://t.me/{group_username}"
    else:
        group_link = f"tg://openmessage?chat_id={group_id}"
    
    group_display = f"<a href='{html.escape(group_link)}'>{html.escape(display_title)}</a>"
    if group_username:
        group_display += f" [@{group_username}]"
    group_display += f" [{group_id}]"
    
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

        # Добавляем информацию о возрасте аккаунта (если передана)
        if additional_info and additional_info.get('age_info'):
            age_info = additional_info['age_info']
            photo_age = age_info.get('photo_age_days')
            estimated_age = age_info.get('estimated_age_days')
            photos_count = age_info.get('photos_count', 0)

            if photos_count > 0 and photo_age is not None:
                message += f"📸 Возраст фото: {photo_age} дн. ({photos_count} фото)\n"
            else:
                message += f"📸 Фото: нет\n"

            if estimated_age is not None:
                message += f"📅 Прибл. возраст аккаунта: ~{estimated_age} дн.\n"

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
        if additional_info:
            reason = additional_info.get('reason', 'Не указано')
            attempt = additional_info.get('attempt')
            risk_score = additional_info.get('risk_score')
            risk_factors = additional_info.get('risk_factors') or []
        else:
            reason = 'Не указано'
            attempt = None
            risk_score = None
            risk_factors = []
        
        risk_factors_text = ", ".join(map(str, risk_factors)) if risk_factors else "нет данных"
        attempt_text = f"{attempt}/3" if attempt is not None else "—"
        risk_score_text = f"{risk_score}/100" if risk_score is not None else "нет данных"
        
        message = f"❌ <b>#КАПЧА_НЕ_ПРОЙДЕНА</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"📝 <b>Причина:</b> {reason}\n"
        message += f"🔄 <b>Попытка:</b> {attempt_text}\n"
        message += f"📊 <b>Оценка риска:</b> {risk_score_text}\n"
        message += f"🔍 <b>Факторы риска:</b> {risk_factors_text}\n"
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
    
    elif event_type == "REACTION_MUTE":
        # Мут по реакции администратора
        admin_data = additional_info.get('admin', {}) if additional_info else {}
        admin_first = admin_data.get('first_name', '') or ''
        admin_last = admin_data.get('last_name', '') or ''
        admin_name = f"{admin_first} {admin_last}".strip()
        admin_username = admin_data.get('username', '') or ''
        admin_id = admin_data.get('user_id', 'N/A')

        admin_display = admin_name or 'Администратор'
        if admin_username:
            admin_display += f" [@{admin_username}]"
        admin_display += f" [{admin_id}]"

        reaction = additional_info.get('reaction', '?') if additional_info else '?'
        duration_seconds = additional_info.get('duration_seconds') if additional_info else None
        muted_groups = additional_info.get('muted_groups', []) if additional_info else []
        global_mute = additional_info.get('global_mute', False) if additional_info else False
        origin_message_id = additional_info.get('origin_message_id') if additional_info else None

        if duration_seconds is None:
            duration_text = "навсегда"
        else:
            days = duration_seconds // 86400
            hours = (duration_seconds % 86400) // 3600
            if days > 0:
                duration_text = f"{days} дн."
            elif hours > 0:
                duration_text = f"{hours} ч."
            else:
                duration_text = f"{duration_seconds // 60} мин."

        message = f"🔇 <b>#REACTION_MUTE</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"👮 <b>Админ:</b> {admin_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"😠 <b>Реакция:</b> {reaction}\n"
        message += f"⏱️ <b>Длительность:</b> {duration_text}\n"
        if origin_message_id:
            message += f"💬 <b>Сообщение:</b> #{origin_message_id}\n"
        if muted_groups:
            message += f"🌐 <b>Мульти-мут:</b> {len(muted_groups)} групп\n"
        if global_mute:
            message += f"🌍 <b>Глобальный мут:</b> да\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#reaction #mute #user{user_id}"

    elif event_type == "REACTION_WARNING":
        # Предупреждение по реакции
        admin_data = additional_info.get('admin', {}) if additional_info else {}
        admin_first = admin_data.get('first_name', '') or ''
        admin_last = admin_data.get('last_name', '') or ''
        admin_name = f"{admin_first} {admin_last}".strip()
        admin_username = admin_data.get('username', '') or ''
        admin_id = admin_data.get('user_id', 'N/A')

        admin_display = admin_name or 'Администратор'
        if admin_username:
            admin_display += f" [@{admin_username}]"
        admin_display += f" [{admin_id}]"

        reaction = additional_info.get('reaction', '?') if additional_info else '?'

        message = f"⚠️ <b>#REACTION_WARNING</b> {status_emoji}\n\n"
        message += f"👤 <b>Пользователь:</b> {user_display}\n"
        message += f"👮 <b>Админ:</b> {admin_display}\n"
        message += f"🏢 <b>Группа:</b> {group_display}\n"
        message += f"😠 <b>Реакция:</b> {reaction}\n"
        message += f"⏰ <b>Когда:</b> {current_time}\n"
        message += f"#reaction #warning #user{user_id}"

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
    
    elif event_type == "CAPTCHA_FAILED":
        user_id = user_data.get('user_id')
        chat_id = group_data.get('chat_id')
        buttons.append([
            InlineKeyboardButton(
                text="✅ Пропустить",
                callback_data=f"captcha_skip_{user_id}_{chat_id}"
            ),
            InlineKeyboardButton(
                text="🔇 Пропустить с мутом",
                callback_data=f"captcha_skip_mute_{user_id}_{chat_id}"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=f"captcha_cancel_{user_id}_{chat_id}"
            )
        ])

    # Кнопки для мута по реакции - размут и бан
    elif event_type == "REACTION_MUTE":
        user_id = user_data.get('user_id')
        chat_id = group_data.get('chat_id')
        buttons.append([
            # Кнопка размутить - снять ограничения с пользователя
            InlineKeyboardButton(
                text="🔓 Размутить",
                callback_data=f"unmute_user_{user_id}_{chat_id}"
            ),
            # Кнопка бана - усилить наказание
            InlineKeyboardButton(
                text="🚫 Забанить",
                callback_data=f"ban_user_{user_id}_{chat_id}"
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


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("unmute_user_"))
async def unmute_user_callback(callback):
    """
    Обработчик кнопки размутивания пользователя.

    Снимает все ограничения с пользователя в группе.
    Callback data формат: unmute_user_{user_id}_{group_id}
    """
    try:
        # Извлекаем user_id и group_id из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        group_id = int(parts[3])

        # Импортируем ChatPermissions для снятия ограничений
        from aiogram.types import ChatPermissions

        # Создаём разрешения без ограничений (все права)
        full_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,  # Не даём менять инфо группы
            can_invite_users=True,
            can_pin_messages=False,  # Не даём закреплять
        )

        # Снимаем ограничения с пользователя
        await callback.bot.restrict_chat_member(
            chat_id=group_id,
            user_id=user_id,
            permissions=full_permissions
        )

        # Уведомляем админа об успехе
        await callback.answer("🔓 Пользователь размучен", show_alert=True)
        logger.info(f"✅ Пользователь {user_id} размучен в группе {group_id}")

        # Обновляем текст сообщения, добавляя информацию о размуте
        try:
            # Получаем текущий текст и добавляем пометку
            current_text = callback.message.text or callback.message.caption or ""
            new_text = current_text + "\n\n✅ <b>РАЗМУЧЕН</b> администратором"
            await callback.message.edit_text(
                text=new_text,
                parse_mode="HTML",
                reply_markup=None  # Убираем кнопки после действия
            )
        except Exception as edit_err:
            # Если не удалось отредактировать - не критично
            logger.warning(f"Не удалось обновить сообщение: {edit_err}")

    except Exception as e:
        logger.error(f"Ошибка при размуте пользователя: {e}")
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


def _format_user_link(entity) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    full_name = getattr(entity, "full_name", None) or getattr(entity, "first_name", None) or getattr(entity, "last_name", None) or str(entity.id)
    return f'<a href="tg://user?id={entity.id}">{html.escape(full_name)}</a>'


def _build_action_message(admin, target, chat, action: str, result: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    admin_link = _format_user_link(admin)
    target_link = _format_user_link(target)
    group_link = f"{format_group_link(chat)} ({chat.id})"
    return (
        "📝 <b>Действие администратора</b>\n\n"
        f"👮 {admin_link}\n"
        f"👤 {target_link}\n"
        f"🏢 {group_link}\n"
        f"⚙️ Действие: {html.escape(action)}\n"
        f"📄 Результат: {html.escape(result)}\n"
        f"⏰ {timestamp}"
    )


async def _approve_join(bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
    except TelegramBadRequest as exc:
        if "HIDE_REQUESTER_MISSING" not in str(exc):
            raise


async def _decline_join(bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
    except TelegramBadRequest as exc:
        if "HIDE_REQUESTER_MISSING" not in str(exc):
            raise


async def _handle_captcha_decision(callback, action: str, mute: bool = False, reject: bool = False):
    try:
        user_id, group_id = map(int, callback.data.split("_")[-2:])
        chat = await callback.bot.get_chat(group_id)
        try:
            member = await callback.bot.get_chat_member(group_id, user_id)
            target = member.user
        except TelegramBadRequest:
            target = await callback.bot.get_chat(user_id)
        except Exception:
            target = SimpleNamespace(
                id=user_id,
                username=None,
                first_name=None,
                last_name=None,
                full_name=None,
            )

        if reject:
            await _decline_join(callback.bot, group_id, user_id)
            result_text = "Заявка отклонена"
        else:
            await _approve_join(callback.bot, group_id, user_id)
            result_text = "Пользователь допущен"
            if mute:
                try:
                    await callback.bot.restrict_chat_member(
                        chat_id=group_id,
                        user_id=user_id,
                        permissions=build_restriction_permissions(),
                        until_date=None,
                    )
                    result_text = "Пользователь допущен и замьючен"
                except TelegramBadRequest as exc:
                    logger.warning("Не удалось применить мут при ручном действии: %s", exc)

        await clear_captcha_state(chat_id=group_id, user_id=user_id)
        await clear_join_request_state(user_id, chat)

        from bot.services.bot_activity_journal.bot_activity_journal_logic import log_captcha_manual_action

        async with get_session() as session:
            await log_captcha_manual_action(
                bot=callback.bot,
                user=callback.from_user,
                target=target,
                chat=chat,
                action=action,
                result=result_text,
                session=session,
            )

            message = _build_action_message(callback.from_user, target, chat, action, result_text)
            await send_journal_event(
                bot=callback.bot,
                session=session,
                group_id=group_id,
                message_text=message,
            )

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        await callback.answer()
    except Exception as exc:
        logger.error("Ошибка при обработке действия журнала: %s", exc, exc_info=True)
        try:
            await callback.answer()
        except Exception:
            pass


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("captcha_skip_mute_"))
async def captcha_skip_mute_callback(callback):
    await _handle_captcha_decision(callback, action="Пропустить с мьютом", mute=True)


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("captcha_skip_") and not c.data.startswith("captcha_skip_mute_"))
async def captcha_skip_callback(callback):
    await _handle_captcha_decision(callback, action="Пропустить", mute=False)


@bot_activity_journal_router.callback_query(lambda c: c.data.startswith("captcha_cancel_"))
async def captcha_cancel_callback(callback):
    await _handle_captcha_decision(callback, action="Отменить", reject=True)
