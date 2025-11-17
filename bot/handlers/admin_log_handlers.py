# handlers/admin_log_handlers.py
import logging
import os
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, ChatPermissions
from aiogram.filters import Command
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.redis_conn import redis
from bot.database.session import get_session
from bot.database.models import ScammerTracker
from bot.utils.logger import send_formatted_log

logger = logging.getLogger(__name__)

admin_log_router = Router()


async def check_admin_rights_in_channel(bot: Bot, user_id: int, chat_id: int) -> bool:
    """Проверяет права администратора в канале логов"""
    try:
        # Получаем информацию о канале логов
        log_channel_id = int(os.getenv("LOG_CHANNEL_ID", "0"))
        if log_channel_id == 0:
            return False
        
        # Проверяем, является ли пользователь администратором канала
        member = await bot.get_chat_member(log_channel_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора в канале: {e}")
        return False


@admin_log_router.callback_query(F.data.startswith("admin_allow:"))
async def handle_admin_allow(callback: CallbackQuery, session: AsyncSession):
    """Обработчик кнопки 'Разрешить доступ'"""
    try:
        # Проверяем права администратора в канале
        if not await check_admin_rights_in_channel(callback.bot, callback.from_user.id, 0):
            await callback.answer("❌ У вас нет прав администратора в канале логов", show_alert=True)
            return

        # Парсим данные
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("❌ Некорректные данные", show_alert=True)
            return

        target_user_id = int(parts[1])
        chat_id = int(parts[2])

        # Устанавливаем флаг разрешения доступа
        await redis.setex(f"admin_allow:{target_user_id}:{chat_id}", 300, "1")
        
        # Обновляем сообщение
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>Доступ разрешен администратором {callback.from_user.first_name}</b>",
            parse_mode="HTML"
        )
        
        await callback.answer("✅ Доступ разрешен", show_alert=True)
        
        # Логируем действие
        try:
            log_message = (
                f"✅ #АДМИН_РАЗРЕШИЛ_ДОСТУП 🟢\n"
                f"• Пользователь: <a href='tg://user?id={target_user_id}'>id{target_user_id}</a> [{target_user_id}]\n"
                f"• Группа: {chat_id}\n"
                f"• Администратор: <a href='tg://user?id={callback.from_user.id}'>{callback.from_user.first_name}</a> [{callback.from_user.id}]\n"
                f"#id{target_user_id} #админ_действие"
            )
            await send_formatted_log(log_message)
        except Exception as log_error:
            logger.error(f"Ошибка при логировании разрешения доступа: {log_error}")
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике admin_allow: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@admin_log_router.callback_query(F.data.startswith("admin_mute:"))
async def handle_admin_mute(callback: CallbackQuery, session: AsyncSession):
    """Обработчик кнопки 'Замутить навсегда'"""
    try:
        # Проверяем права администратора в канале
        if not await check_admin_rights_in_channel(callback.bot, callback.from_user.id, 0):
            await callback.answer("❌ У вас нет прав администратора в канале логов", show_alert=True)
            return

        # Парсим данные
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("❌ Некорректные данные", show_alert=True)
            return

        target_user_id = int(parts[1])
        chat_id = int(parts[2])

        # Мутим пользователя
        try:
            await callback.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=datetime.now() + timedelta(days=366 * 10)  # 10 лет
            )
            
            # Обновляем сообщение
            await callback.message.edit_text(
                callback.message.text + f"\n\n🔇 <b>Замучен администратором {callback.from_user.first_name}</b>",
                parse_mode="HTML"
            )
            
            await callback.answer("🔇 Пользователь замьючен", show_alert=True)
            
            # Обновляем запись в БД
            try:
                result = await session.execute(
                    select(ScammerTracker).where(
                        ScammerTracker.user_id == target_user_id,
                        ScammerTracker.chat_id == chat_id
                    )
                )
                record = result.scalar_one_or_none()
                
                if record:
                    record.scammer_level = 5  # Максимальный уровень
                    record.is_scammer = True
                    record.notes = f"Замучен администратором {callback.from_user.first_name} через канал логов"
                    record.updated_at = datetime.utcnow()
                    await session.commit()
                else:
                    # Создаем новую запись
                    new_record = ScammerTracker(
                        user_id=target_user_id,
                        chat_id=chat_id,
                        violation_type="admin_mute_via_logs",
                        violation_count=1,
                        is_scammer=True,
                        scammer_level=5,
                        first_violation_at=datetime.utcnow(),
                        last_violation_at=datetime.utcnow(),
                        notes=f"Замучен администратором {callback.from_user.first_name} через канал логов"
                    )
                    session.add(new_record)
                    await session.commit()
            except Exception as db_error:
                logger.error(f"Ошибка при обновлении БД: {db_error}")
                await session.rollback()
            
            # Логируем действие
            try:
                log_message = (
                    f"🔇 #АДМИН_ЗАМУТИЛ 🚫\n"
                    f"• Пользователь: <a href='tg://user?id={target_user_id}'>id{target_user_id}</a> [{target_user_id}]\n"
                    f"• Группа: {chat_id}\n"
                    f"• Администратор: <a href='tg://user?id={callback.from_user.id}'>{callback.from_user.first_name}</a> [{callback.from_user.id}]\n"
                    f"#id{target_user_id} #админ_действие #мут"
                )
                await send_formatted_log(log_message)
            except Exception as log_error:
                logger.error(f"Ошибка при логировании мута: {log_error}")
                
        except Exception as mute_error:
            logger.error(f"Ошибка при муте пользователя: {mute_error}")
            await callback.answer("❌ Не удалось замьютить пользователя", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике admin_mute: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Убираем обработчик бана - теперь только автомут


@admin_log_router.message(Command("log_admin_check"))
async def check_log_admin_rights(message, session: AsyncSession):
    """Команда для проверки прав администратора в канале логов"""
    try:
        user_id = message.from_user.id
        is_admin = await check_admin_rights_in_channel(message.bot, user_id, 0)
        
        if is_admin:
            await message.answer("✅ У вас есть права администратора в канале логов")
        else:
            await message.answer("❌ У вас нет прав администратора в канале логов")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        await message.answer("❌ Ошибка при проверке прав")
