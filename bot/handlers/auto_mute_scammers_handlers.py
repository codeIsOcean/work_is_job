# handlers/auto_mute_scammers_handlers.py
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter
from aiogram.enums import ChatMemberStatus

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.auto_mute_scammers_logic import (
    get_auto_mute_scammers_status,
    set_auto_mute_scammers_status,
    auto_mute_scammer_on_join,
    create_auto_mute_settings_keyboard,
    get_auto_mute_settings_text
)
from bot.services.groups_settings_in_private_logic import check_granular_permissions
from bot.services.redis_conn import redis
from bot.database.session import get_session

logger = logging.getLogger(__name__)

auto_mute_scammers_router = Router()


@auto_mute_scammers_router.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(ChatMemberStatus.LEFT, ChatMemberStatus.MEMBER)
    )
)
async def handle_chat_member_update(event: ChatMemberUpdated):
    """
    Обрабатывает обновления статуса участников для автомута скаммеров
    """
    logger.info(f"🔍 [AUTO_MUTE_HANDLER] ===== ОБРАБОТЧИК АВТОМУТА СРАБОТАЛ =====")
    logger.info(f"🔍 [AUTO_MUTE_HANDLER] Пользователь: @{event.new_chat_member.user.username or event.new_chat_member.user.first_name or event.new_chat_member.user.id} [{event.new_chat_member.user.id}]")
    logger.info(f"🔍 [AUTO_MUTE_HANDLER] Чат: {event.chat.title} [{event.chat.id}]")
    logger.info(f"🔍 [AUTO_MUTE_HANDLER] Статус: {event.old_chat_member.status} -> {event.new_chat_member.status}")
    
    try:
        logger.info(f"🔍 [AUTO_MUTE_HANDLER] Начинаем проверку логики автомута...")
        
        # ИСПРАВЛЕНИЕ: Автомут и ручной мут работают независимо
        # Автомут проверяет скаммеров по возрасту аккаунта и уровню скама
        # Ручной мут работает для тех, кто не прошел капчу
        # Они не блокируют друг друга
        
        chat_id = event.chat.id
        user_id = event.new_chat_member.user.id
        
        # Логируем для диагностики
        captcha_key = f"captcha_passed:{user_id}:{chat_id}"
        captcha_passed = await redis.get(captcha_key)
        logger.info(f"🔍 [AUTO_MUTE_HANDLER] Проверка капчи для диагностики: {captcha_passed}")
        
        await auto_mute_scammer_on_join(event.bot, event)
    except Exception as e:
        logger.error(f"Ошибка в обработчике chat_member для автомута: {e}")


@auto_mute_scammers_router.callback_query(F.data.startswith("auto_mute_settings:"))
async def handle_auto_mute_settings(callback: CallbackQuery, session: AsyncSession):
    """Обработчик настроек автомута скаммеров"""
    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        action = parts[1]  # enable или disable
        chat_id = int(parts[2])

        # Проверяем гранулярные права: автомута скамеров требует can_restrict_members
        user_id = callback.from_user.id
        if not await check_granular_permissions(callback.bot, user_id, chat_id, 'restrict_members', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Ограничивать участников'", show_alert=True)
            return

        # Устанавливаем настройку
        enabled = action == "enable"
        success = await set_auto_mute_scammers_status(chat_id, enabled, session)
        
        if success:
            status_message = "Автомут скаммеров включен" if enabled else "Автомут скаммеров отключен"
            await callback.answer(status_message, show_alert=True)
            
            # Обновляем меню
            keyboard_data = await create_auto_mute_settings_keyboard(chat_id, session)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                    for btn in row
                ]
                for row in keyboard_data["buttons"]
            ])
            
            text = get_auto_mute_settings_text(keyboard_data["status"])
            await callback.message.edit_text(text, reply_markup=keyboard)
        else:
            await callback.answer("Ошибка при сохранении настроек", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике настроек автомута: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@auto_mute_scammers_router.callback_query(F.data.startswith("auto_mute_scammers_settings:"))
async def show_auto_mute_settings(callback: CallbackQuery, session: AsyncSession):
    """Показывает настройки автомута скаммеров"""
    try:
        user_id = callback.from_user.id
        
        # Получаем group_id из callback_data
        if callback.data.startswith("auto_mute_scammers_settings:"):
            group_id = int(callback.data.split(":")[-1])
        else:
            # Fallback - получаем из Redis
            group_id = await redis.hget(f"user:{user_id}", "group_id")
            if not group_id:
                group_id = await redis.get(f"current_group_for_user:{user_id}")
                if not group_id:
                    await callback.answer("❌ Не удалось найти привязку к группе. Попробуйте заново выбрать группу в настройках.", show_alert=True)
                    return
            group_id = int(group_id)
        
        # Проверяем гранулярные права: просмотр/изменение настроек автомута требует can_restrict_members
        if not await check_granular_permissions(callback.bot, user_id, group_id, 'restrict_members', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Ограничивать участников'", show_alert=True)
            return

        # Получаем текущий статус
        auto_mute_enabled = await get_auto_mute_scammers_status(group_id, session)
        
        # Создаем клавиатуру
        keyboard_data = await create_auto_mute_settings_keyboard(group_id, session)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in keyboard_data["buttons"]
        ])
        
        text = get_auto_mute_settings_text(auto_mute_enabled)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при показе настроек автомута: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@auto_mute_scammers_router.message(Command("auto_mute_status"))
async def check_auto_mute_status(message, session: AsyncSession):
    """Команда для проверки статуса автомута скаммеров"""
    try:
        if message.chat.type not in ("group", "supergroup"):
            await message.answer("Эта команда работает только в группах")
            return

        chat_id = message.chat.id
        auto_mute_enabled = await get_auto_mute_scammers_status(chat_id, session)
        
        status_text = "включен" if auto_mute_enabled else "выключен"
        await message.answer(f"🤖 Автомут скаммеров: {status_text}")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса автомута: {e}")
        await message.answer("Ошибка при проверке статуса")
