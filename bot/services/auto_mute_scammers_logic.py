# services/auto_mute_scammers_logic.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import ChatMemberUpdated, ChatPermissions
from aiogram.enums import ChatMemberStatus
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

from bot.services.redis_conn import redis
from bot.database.models import ChatSettings, ScammerTracker
from bot.database.session import get_session
from bot.utils.logger import send_formatted_log

logger = logging.getLogger(__name__)


async def get_auto_mute_scammers_status(chat_id: int, session: AsyncSession = None) -> bool:
    """
    Получает статус автомута скаммеров для группы
    Сначала проверяет Redis, затем БД
    """
    try:
        # Проверяем Redis
        auto_mute_enabled = await redis.get(f"group:{chat_id}:auto_mute_scammers")
        logger.info(f"🔍 [AUTO_MUTE_STATUS] Redis check для группы {chat_id}: {auto_mute_enabled}")
        
        if auto_mute_enabled is not None:
            result = auto_mute_enabled == "1"
            logger.info(f"🔍 [AUTO_MUTE_STATUS] Результат из Redis для группы {chat_id}: {result}")
            return result
        
        # Если в Redis нет данных, проверяем в БД
        if session:
            # Используем переданную сессию
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            )
            settings = result.scalar_one_or_none()
            
            if settings and hasattr(settings, 'auto_mute_scammers'):
                auto_mute_enabled = "1" if settings.auto_mute_scammers else "0"
                # Обновляем Redis
                await redis.set(f"group:{chat_id}:auto_mute_scammers", auto_mute_enabled)
                return settings.auto_mute_scammers
            else:
                # По умолчанию включено
                await redis.set(f"group:{chat_id}:auto_mute_scammers", "1")
                return True
        else:
            # Создаем новую сессию
            async with get_session() as new_session:
                result = await new_session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                settings = result.scalar_one_or_none()
                
                if settings and hasattr(settings, 'auto_mute_scammers'):
                    auto_mute_enabled = "1" if settings.auto_mute_scammers else "0"
                    # Обновляем Redis
                    await redis.set(f"group:{chat_id}:auto_mute_scammers", auto_mute_enabled)
                    return settings.auto_mute_scammers
                else:
                    # По умолчанию включено
                    await redis.set(f"group:{chat_id}:auto_mute_scammers", "1")
                    return True
                
    except Exception as e:
        logger.error(f"Ошибка при получении статуса автомута скаммеров для группы {chat_id}: {e}")
        return True  # По умолчанию включено


async def set_auto_mute_scammers_status(chat_id: int, enabled: bool, session: AsyncSession = None) -> bool:
    """
    Устанавливает статус автомута скаммеров для группы
    Сохраняет в Redis и БД
    """
    try:
        # Сохраняем в Redis
        redis_value = "1" if enabled else "0"
        await redis.set(f"group:{chat_id}:auto_mute_scammers", redis_value)
        logger.info(f"🔍 [AUTO_MUTE_SET] Сохранено в Redis для группы {chat_id}: {redis_value}")
        
        # Сохраняем в БД
        if session:
            # Используем переданную сессию
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            )
            settings = result.scalar_one_or_none()
            
            if settings:
                await session.execute(
                    update(ChatSettings)
                    .where(ChatSettings.chat_id == chat_id)
                    .values(auto_mute_scammers=enabled)
                )
            else:
                await session.execute(
                    insert(ChatSettings).values(
                        chat_id=chat_id,
                        auto_mute_scammers=enabled,
                        enable_photo_filter=False,
                        admins_bypass_photo_filter=False,
                        photo_filter_mute_minutes=60,
                        mute_new_members=False
                    )
                )
        else:
            # Создаем новую сессию
            async with get_session() as new_session:
                result = await new_session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                settings = result.scalar_one_or_none()
                
                if settings:
                    await new_session.execute(
                        update(ChatSettings)
                        .where(ChatSettings.chat_id == chat_id)
                        .values(auto_mute_scammers=enabled)
                    )
                else:
                    await new_session.execute(
                        insert(ChatSettings).values(
                            chat_id=chat_id,
                            auto_mute_scammers=enabled,
                            enable_photo_filter=False,
                            admins_bypass_photo_filter=False,
                            photo_filter_mute_minutes=60,
                            mute_new_members=False
                        )
                    )
                await new_session.commit()
        
        logger.info(f"✅ Статус автомута скаммеров для группы {chat_id}: {'включен' if enabled else 'выключен'}")
        return True
            
    except Exception as e:
        logger.error(f"Ошибка при установке статуса автомута скаммеров для группы {chat_id}: {e}")
        return False


async def auto_mute_scammer_on_join(bot: Bot, event: ChatMemberUpdated) -> bool:
    """
    Автоматически мутит скаммеров при вступлении в группу
    """
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        chat_id = event.chat.id
        user = event.new_chat_member.user
        
        logger.info(f"🔍 [AUTO_MUTE_DEBUG] Обработка chat_member: user=@{user.username or user.first_name or user.id} [{user.id}], chat={chat_id}, old={old_status} -> new={new_status}")
        
        # Проверяем, что пользователь стал участником
        if old_status in ("left", "kicked") and new_status == "member":
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Пользователь @{user.username or user.first_name or user.id} [{user.id}] стал участником из статуса {old_status}")
            
            # Проверяем, включен ли автомут скаммеров для этой группы
            auto_mute_enabled = await get_auto_mute_scammers_status(chat_id)
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Статус автомута скаммеров для группы {chat_id}: {auto_mute_enabled}")
            
            if not auto_mute_enabled:
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] Автомут скаммеров для группы {chat_id} отключен, пропускаем")
                return False
            
            # Проверяем, включен ли ручной мут для этой группы
            from bot.services.new_member_requested_to_join_mute_logic import get_mute_new_members_status
            manual_mute_enabled = await get_mute_new_members_status(chat_id)
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Статус ручного мута для группы {chat_id}: {manual_mute_enabled}")
            
            # Проверяем капчу для логирования
            captcha_passed = await redis.get(f"captcha_passed:{user.id}:{chat_id}")
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Проверка капчи для пользователя @{user.username or user.first_name or user.id} [{user.id}]: {captcha_passed}")
            
            # ИСПРАВЛЕНИЕ: Автомут работает независимо от ручного мута
            # Если это скаммер (свежий аккаунт/подозрительное поведение) - мутим автоматически
            # Ручной мут и автомут работают параллельно, не блокируя друг друга
            
            # ПРИОРИТЕТ 1: Проверяем флаг автомута из Redis (устанавливается при анализе капчи)
            auto_mute_flag = await redis.get(f"auto_mute_scammer:{user.id}:{chat_id}")
            auto_mute_ttl = await redis.ttl(f"auto_mute_scammer:{user.id}:{chat_id}")
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Флаг автомута из Redis для пользователя @{user.username or user.first_name or user.id} [{user.id}]: {auto_mute_flag} (TTL: {auto_mute_ttl}s)")
            
            # ПРИОРИТЕТ 2: Проверяем уровень скама в БД
            scam_level = None
            async with get_session() as session:
                result = await session.execute(
                    select(ScammerTracker.scammer_level).where(
                        ScammerTracker.user_id == user.id,
                        ScammerTracker.chat_id == chat_id
                    )
                )
                scam_level = result.scalar_one_or_none()
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Уровень скама из БД для пользователя @{user.username or user.first_name or user.id} [{user.id}]: {scam_level}")
            
            # ПРИОРИТЕТ 3: Проверяем возраст аккаунта - свежие аккаунты (≤30 дней) мутим автоматически
            from bot.services.account_age_estimator import account_age_estimator
            age_info = account_age_estimator.get_detailed_age_info(user.id)
            age_days = age_info["age_days"]
            age_risk_score = age_info["risk_score"]
            
            logger.info(f"🔍 [AUTO_MUTE_DEBUG] Возраст аккаунта @{user.username or user.first_name or user.id} [{user.id}]: {age_days} дней, риск: {age_risk_score}/100")
            
            # РЕШЕНИЕ: Мутим если выполнено ЛЮБОЕ из условий:
            # 1. Есть флаг автомута из Redis (самый приоритетный)
            # 2. Уровень скама >= 50 (второй приоритет)
            # 3. Возраст аккаунта <= 30 дней (включая отрицательные значения - новые аккаунты)
            mute_reason = ""
            should_mute = False
            
            if auto_mute_flag == "1":
                mute_reason = f"Флаг автомута из Redis (TTL: {auto_mute_ttl}s)"
                should_mute = True
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] ✅ Флаг автомута установлен - мутим пользователя @{user.username or user.first_name or user.id} [{user.id}]")
            elif scam_level is not None and scam_level >= 50:
                mute_reason = f"Уровень скама {scam_level}/100 из БД"
                should_mute = True
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] ✅ Уровень скама {scam_level} >= 50 - мутим пользователя @{user.username or user.first_name or user.id} [{user.id}]")
            elif age_days <= 30:
                mute_reason = f"Свежий аккаунт ({age_days} дней)"
                should_mute = True
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] ✅ Свежий аккаунт ({age_days} дней) - мутим пользователя @{user.username or user.first_name or user.id} [{user.id}]")
            
            if not should_mute:
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] ❌ Пользователь @{user.username or user.first_name or user.id} [{user.id}] не соответствует критериям автомута (флаг: {auto_mute_flag}, уровень скама: {scam_level}, возраст: {age_days} дней)")
                return False
            
            logger.info(f"🔇 [AUTO_MUTE_DEBUG] Мутим скаммера @{user.username or user.first_name or user.id} [{user.id}] автоматически (причина: {mute_reason})")
            
            # Применяем мут
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
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
            
            await asyncio.sleep(1)
            logger.info(f"🔇 Скаммер @{user.username or user.first_name or user.id} [{user.id}] был автоматически замьючен (причина: {mute_reason})")
            
            # Удаляем флаг автомута из Redis после применения мута
            if auto_mute_flag == "1":
                await redis.delete(f"auto_mute_scammer:{user.id}:{chat_id}")
                logger.info(f"🔍 [AUTO_MUTE_DEBUG] Удален флаг автомута из Redis для пользователя @{user.username or user.first_name or user.id} [{user.id}]")
            
            # ЛОГИРУЕМ АВТОМУТ СКАММЕРА через новую систему журнала
            try:
                from bot.services.bot_activity_journal.bot_activity_journal_logic import log_auto_mute_scammer
                from bot.database.session import get_session
                async with get_session() as db_session:
                    await log_auto_mute_scammer(
                        bot=bot,
                        user=user,
                        chat=event.chat,
                        scammer_level=scam_level or age_risk_score or 0,
                        reason=f"Автоматический мут: {mute_reason}",
                        session=db_session
                    )
                logger.info(f"📱 Отправлен лог об автомуте скаммера @{user.username or user.first_name or user.id} [{user.id}] в группе {chat_id}")
            except Exception as log_error:
                logger.error(f"Ошибка при отправке лога об автомуте: {log_error}")
            
            return True
        else:
            logger.debug(f"Не обработан: статус не соответствует. old={old_status}, new={new_status}")
            return False
            
    except Exception as e:
        logger.error(f"AUTO_MUTE_ERROR: {str(e)}")
        return False


async def create_auto_mute_settings_keyboard(chat_id: int, session: AsyncSession = None) -> dict:
    """
    Создает клавиатуру для настроек автомута скаммеров
    """
    auto_mute_enabled = await get_auto_mute_scammers_status(chat_id, session)
    
    # Создаем текст кнопок с галочкой перед выбранным состоянием
    enable_text = "✓ Включить" if auto_mute_enabled else "Включить"
    disable_text = "✓ Выключить" if not auto_mute_enabled else "Выключить"
    
    keyboard_data = {
        "buttons": [
            [
                {"text": enable_text, "callback_data": f"auto_mute_settings:enable:{chat_id}"},
                {"text": disable_text, "callback_data": f"auto_mute_settings:disable:{chat_id}"}
            ],
            [{"text": "« Назад", "callback_data": "back_to_groups"}]
        ],
        "status": auto_mute_enabled  # Возвращаем булево значение
    }
    
    return keyboard_data


def get_auto_mute_settings_text(status: bool = True) -> str:
    """
    Возвращает текст для настроек автомута скаммеров
    """
    status_text = "✅ Включено" if status else "❌ Выключено"
    return (
        f"🤖 Настройки автомута скаммеров:\n\n"
        f"• Скаммеры автоматически получают мут при вступлении\n"
        f"• Мут действует до 10 лет\n"
        f"• Скаммеры определяются по анализу профиля и поведения\n"
        f"• Текущее состояние: {status_text}\n\n"
        f"Эта функция защищает вашу группу от спамеров и ботов."
    )
