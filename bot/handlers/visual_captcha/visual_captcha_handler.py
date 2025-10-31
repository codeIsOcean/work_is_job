# handlers/captcha/visual_captcha_handler.py
import asyncio
import logging
import traceback
from typing import Dict, Optional, Any

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ChatJoinRequest

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.redis_conn import redis
from bot.services.visual_captcha_logic import (
    generate_visual_captcha,
    delete_message_after_delay,
    save_join_request,
    create_deeplink_for_captcha,
    get_captcha_keyboard,
    get_group_settings_keyboard,
    get_group_join_keyboard,
    save_captcha_data,
    get_captcha_data,
    set_rate_limit,
    check_rate_limit,
    get_rate_limit_time_left,
    check_admin_rights,
    set_visual_captcha_status,
    get_visual_captcha_status,
    approve_chat_join_request,
    get_group_display_name,
    save_user_to_db,
    get_group_link_from_redis_or_create,
    schedule_captcha_reminder,
    start_behavior_tracking,
    track_captcha_input,
    increment_captcha_attempts,
    get_enhanced_captcha_decision,
    save_scam_level_to_db,
    get_user_scam_level,
    reset_user_scam_level,
)
# from bot.services.scammer_tracker_logic import track_captcha_failure  # Убираем старую логику
from bot.database.queries import get_group_by_name
from bot.services.bot_activity_journal.bot_activity_journal_logic import (
    log_join_request,
    log_captcha_passed,
    log_captcha_failed,
    log_captcha_timeout
)

logger = logging.getLogger(__name__)

visual_captcha_handler_router = Router()


class CaptchaStates(StatesGroup):
    waiting_for_captcha = State()


@visual_captcha_handler_router.chat_join_request()
async def handle_join_request(join_request: ChatJoinRequest):
    """
    Обрабатывает запрос на вступление в группу:
    - Если включена визуальная капча, отправляет пользователю deep-link на прохождение капчи.
    - Не даём «битую» ссылку для приватных групп до прохождения капчи.
    """
    user = join_request.from_user
    chat = join_request.chat
    user_id = user.id
    chat_id = chat.id

    # Проверяем, активна ли визуальная капча
    captcha_enabled = await get_visual_captcha_status(chat_id)
    if not captcha_enabled:
        logger.info(f"⛔ Визуальная капча не активирована в группе {chat_id}, выходим")
        return

    # Идентификатор группы в deep-link: username или private_<id>
    group_id = chat.username or f"private_{chat.id}"

    # Сохраняем запрос на вступление (для последующего approve)
    await save_join_request(user_id, chat_id, group_id)

    # Создаём start deep-link на /start для прохождения капчи
    deep_link = await create_deeplink_for_captcha(join_request.bot, group_id)

    # Кнопка «Пройти капчу»
    keyboard = await get_captcha_keyboard(deep_link)

    try:
        # Удаляем прошлые сообщения бота пользователю (если есть)
        user_messages = await redis.get(f"user_messages:{user_id}")
        if user_messages:
            message_ids = user_messages.split(",")
            for msg_id in message_ids:
                try:
                    await join_request.bot.delete_message(chat_id=user_id, message_id=int(msg_id))
                except Exception as e:
                    if "message to delete not found" not in str(e).lower():
                        logger.error(f"Ошибка при удалении сообщения {msg_id}: {str(e)}")

        # Формируем текст с кликабельным названием группы
        group_title = (
            chat.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if chat.title else "группа"
        )
        logger.info(f"📝 Название группы для сообщения: '{group_title}' (исходное: '{chat.title}')")

        # Создаем ссылку на группу
        group_link = None
        if chat.username:
            # Публичная группа - используем username
            group_link = f"https://t.me/{chat.username}"
        else:
            # Приватная группа - создаем инвайт-ссылку
            try:
                invite = await join_request.bot.create_chat_invite_link(
                    chat_id=chat_id,
                    name=f"Captcha invite for user {user_id}",
                    creates_join_request=False,
                )
                # Преобразуем invite.invite_link в строку явно
                group_link = str(invite.invite_link) if invite.invite_link else None
                logger.info(f"Создана инвайт-ссылка для приватной группы {chat_id}: {group_link}")
            except Exception as e:
                logger.error(f"Ошибка при создании инвайт-ссылки для группы {chat_id}: {e}")
                # Fallback - используем tg:// ссылку
                group_link = f"tg://resolve?domain={chat_id}"

        # Формируем сообщение с кликабельным названием группы
        if group_link:
            message_text = (
                f"🔒 Для вступления в группу <a href='{group_link}'>{group_title}</a> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )
        else:
            # Fallback если не удалось создать ссылку
            message_text = (
                f"🔒 Для вступления в группу <b>{group_title}</b> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )

        # Отправляем сообщение пользователю
        msg = await join_request.bot.send_message(
            user_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"✅ Отправлено сообщение пользователю {user_id} о прохождении капчи")

        # Логируем запрос на вступление в журнал действий
        try:
            from bot.database.session import get_session
            async with get_session() as session:
                await log_join_request(
                    bot=join_request.bot,
                    user=user,
                    chat=chat,
                    captcha_status="КАПЧА_ОТПРАВЛЕНА",
                    saved_to_db=False,
                    session=session
                )
        except Exception as log_error:
            logger.error(f"Ошибка при логировании запроса на вступление: {log_error}")

        # Удаляем сообщение через 2-3 минуты (150 секунд = 2.5 минуты)
        asyncio.create_task(delete_message_after_delay(join_request.bot, user_id, msg.message_id, 150))

        # Сохраняем ID сообщения на час (для последующего удаления)
        await redis.setex(f"user_messages:{user_id}", 3600, str(msg.message_id))

    except Exception as e:
        error_msg = str(e)
        if "bot can't initiate conversation with a user" in error_msg:
            logger.warning(f"⚠️ Пользователь {user_id} не начал диалог с ботом. Запрос на вступление будет отклонен.")
            # Логируем неудачную попытку отправки капчи
            await log_join_request(
                bot=join_request.bot,
                user=user,
                chat=chat,
                captcha_status="КАПЧА_НЕ_УДАЛАСЬ_НЕТ_ДИАЛОГА",
                saved_to_db=False
            )
        elif "bot was blocked by the user" in error_msg:
            logger.warning(f"⚠️ Пользователь {user_id} заблокировал бота. Запрос на вступление будет отклонен.")
            # Логируем неудачную попытку отправки капчи
            await log_join_request(
                bot=join_request.bot,
                user=user,
                chat=chat,
                captcha_status="КАПЧА_НЕ_УДАЛАСЬ_БОТ_ЗАБЛОКИРОВАН",
                saved_to_db=False
            )
        else:
            logger.error(f"❌ Ошибка при обработке запроса на вступление: {e}")
            logger.debug(traceback.format_exc())


@visual_captcha_handler_router.message(CommandStart(deep_link=True))
async def process_visual_captcha_deep_link(message: Message, bot: Bot, state: FSMContext, session: AsyncSession):
    """
    Обработка /start с deep_link вида deep_link_<group_id_or_username>.
    Генерация и показ визуальной капчи.
    """
    try:
        # Сохраняем/обновляем пользователя в БД
        user_data = {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
            "is_bot": message.from_user.is_bot,
            "is_premium": message.from_user.is_premium,
            "added_to_attachment_menu": message.from_user.added_to_attachment_menu,
            "can_join_groups": message.from_user.can_join_groups,
            "can_read_all_group_messages": message.from_user.can_read_all_group_messages,
            "supports_inline_queries": message.from_user.supports_inline_queries,
            "can_connect_to_business": message.from_user.can_connect_to_business,
            "has_main_web_app": message.from_user.has_main_web_app,
        }
        await save_user_to_db(session, user_data)

        # Извлекаем deep_link параметры
        deep_link_args = message.text.split()[1] if len(message.text.split()) > 1 else None
        logger.info(f"Активирован deep link с параметрами: {deep_link_args}")

        if not deep_link_args or not deep_link_args.startswith("deep_link_"):
            await message.answer("Неверная ссылка. Пожалуйста, используйте корректную ссылку для вступления в группу.")
            logger.warning(f"Неверный deep link: {deep_link_args}")
            return

        # Чистим предыдущие сообщения капчи
        stored = await state.get_data()
        prev_ids = stored.get("message_ids", [])
        for mid in prev_ids:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=mid)
            except Exception as e:
                if "message to delete not found" not in str(e).lower():
                    logger.error(f"Ошибка удаления сообщения {mid}: {e}")

        # Также чистим, если ID были записаны в Redis
        user_messages = await redis.get(f"user_messages:{message.from_user.id}")
        if user_messages:
            try:
                for mid in user_messages.split(","):
                    try:
                        await bot.delete_message(chat_id=message.chat.id, message_id=int(mid))
                    except Exception as e:
                        if "message to delete not found" not in str(e).lower():
                            logger.error(f"Ошибка при удалении сообщения {mid}: {e}")
                await redis.delete(f"user_messages:{message.from_user.id}")
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщений из Redis: {e}")

        # Имя/ID группы из deep-link
        group_name = deep_link_args.replace("deep_link_", "")
        logger.info(f"Extracted group name from deep-link: {group_name}")

        # Генерируем капчу
        captcha_answer, captcha_image = await generate_visual_captcha()
        logger.info(f"Сгенерирована капча, ответ: {captcha_answer}")

        # Начинаем отслеживание поведения пользователя
        await start_behavior_tracking(message.from_user.id)

        # Пишем в FSM + Redis
        await state.update_data(captcha_answer=captcha_answer, group_name=group_name, attempts=0, message_ids=[])
        await save_captcha_data(message.from_user.id, captcha_answer, group_name, 0)

        # Отправляем изображение-капчу с повторными попытками
        captcha_sent = False
        for attempt in range(3):  # 3 попытки
            try:
                captcha_msg = await message.answer_photo(
                    photo=captcha_image,
                    caption=(
                        "Пожалуйста, введите символы, которые вы видите на изображении, "
                        "или решите математическое выражение, чтобы продолжить."
                    ),
                )
                message_ids = [captcha_msg.message_id]
                await state.update_data(message_ids=message_ids)

                # Удалим капчу через 5 минут (чтобы дать время на напоминание)
                asyncio.create_task(delete_message_after_delay(bot, message.chat.id, captcha_msg.message_id, 300))
                
                # Планируем напоминание через 2 минуты
                asyncio.create_task(schedule_captcha_reminder(bot, message.from_user.id, group_name, 2))
                
                await state.set_state(CaptchaStates.waiting_for_captcha)
                captcha_sent = True
                break
                
            except Exception as network_error:
                logger.warning(f"⚠️ Попытка {attempt + 1}/3 отправки капчи не удалась: {network_error}")
                if attempt < 2:  # Не последняя попытка
                    await asyncio.sleep(1)  # Ждем 1 секунду перед повторной попыткой
                    continue

        if not captcha_sent:
            logger.error(f"❌ Ошибка сети при отправке капчи: {network_error}")
            # Фолбэк — текстовый код
            try:
                fallback_msg = await message.answer(
                    "⚠️ Не удалось отправить изображение капчи.\n\n"
                    f"🔑 Ваш код для входа в группу: **{captcha_answer}**\n"
                    "Введите этот код для подтверждения:",
                    parse_mode="Markdown",
                )
                await state.update_data(message_ids=[fallback_msg.message_id])
                await state.set_state(CaptchaStates.waiting_for_captcha)
                asyncio.create_task(delete_message_after_delay(bot, message.chat.id, fallback_msg.message_id, 300))
                
                # Планируем напоминание через 2 минуты
                asyncio.create_task(schedule_captcha_reminder(bot, message.from_user.id, group_name, 2))
            except Exception as fallback_error:
                logger.error(f"❌ Критическая ошибка при отправке fallback-сообщения: {fallback_error}")
                await message.answer("Произошла критическая ошибка. Попробуйте позже.")
                await state.clear()

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в process_visual_captcha_deep_link: {e}")
        logger.debug(traceback.format_exc())
        try:
            await message.answer("Произошла ошибка при обработке запроса. Попробуйте позже.")
        except Exception:
            pass
        await state.clear()


@visual_captcha_handler_router.message(CaptchaStates.waiting_for_captcha)
async def process_captcha_answer(message: Message, state: FSMContext, session: AsyncSession):
    """
    Проверяет ответ на капчу. При успехе:
    - approve join request (если был),
    - отдаёт кнопку для открытия группы (с приоритетом tg:// ссылок),
    - показывает реальное название группы на кнопке.
    """
    user_id = message.from_user.id

    try:
        # Обновим юзера в БД (для рассылок и т.п.)
        await save_user_to_db(
            session,
            {
                "user_id": message.from_user.id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "last_name": message.from_user.last_name,
                "language_code": message.from_user.language_code,
                "is_bot": message.from_user.is_bot,
                "is_premium": message.from_user.is_premium,
            },
        )

        # Рейтлимит
        if await check_rate_limit(user_id):
            time_left = await get_rate_limit_time_left(user_id)
            limit_msg = await message.answer(f"Пожалуйста, подождите {time_left} секунд перед следующей попыткой.")
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, limit_msg.message_id, 5))
            return

        # Достаём данные из FSM (или Redis)
        data = await state.get_data()
        captcha_answer = data.get("captcha_answer")
        group_name = data.get("group_name")
        attempts = data.get("attempts", 0)
        message_ids = data.get("message_ids", [])
        moderate_risk_check = data.get("moderate_risk_check", False)
        additional_answer = data.get("additional_answer")

        # Добавим текущее сообщение в список на удаление
        message_ids.append(message.message_id)
        await state.update_data(message_ids=message_ids)

        # Проверяем, если это ответ на дополнительный вопрос при умеренном риске
        if moderate_risk_check and additional_answer:
            user_answer = (message.text or "").strip().lower()
            if user_answer == additional_answer.lower():
                # Дополнительный вопрос решен правильно - разрешаем доступ
                success_msg = await message.answer(
                    "✅ <b>Дополнительная проверка пройдена!</b>\n\n"
                    "🎉 <b>Доступ разрешен</b>\n"
                    "🔗 <b>Сейчас вы будете добавлены в группу</b>",
                    parse_mode="HTML"
                )
                message_ids.append(success_msg.message_id)
                await state.update_data(message_ids=message_ids)
                
                # Удаляем все сообщения через 5 секунд
                for mid in message_ids:
                    asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 5))
                
                # Одобряем запрос на вступление
                await approve_user_join_request(message, group_name, message_ids)
                await state.clear()
                return
            else:
                # Неверный ответ на дополнительный вопрос - блокируем
                wrong_additional_msg = await message.answer(
                    f"❌ <b>Неверный ответ на дополнительный вопрос</b>\n\n"
                    f"✅ <b>Правильный ответ был:</b> <code>{additional_answer}</code>\n"
                    f"🚫 <b>Доступ заблокирован из-за подозрительной активности</b>",
                    parse_mode="HTML"
                )
                message_ids.append(wrong_additional_msg.message_id)
                await state.update_data(message_ids=message_ids)
                
                # Удаляем все сообщения через 10 секунд
                for mid in message_ids:
                    asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 10))
                
                await redis.delete(f"captcha:{message.from_user.id}")
                await state.clear()
                return

        if not captcha_answer or not group_name:
            captcha_data = await get_captcha_data(message.from_user.id)
            if captcha_data:
                captcha_answer = captcha_data["captcha_answer"]
                group_name = captcha_data["group_name"]
                attempts = captcha_data["attempts"]
            else:
                no_captcha_msg = await message.answer("Время сессии истекло. Пожалуйста, начните процесс заново.")
                message_ids.append(no_captcha_msg.message_id)
                await state.update_data(message_ids=message_ids)
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, no_captcha_msg.message_id, 5))
                await state.clear()
                return

        # Проверка количества попыток
        if attempts >= 3:
            too_many = await message.answer("Превышено количество попыток. Повторите через 60 секунд.")
            message_ids.append(too_many.message_id)
            await state.update_data(message_ids=message_ids)
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, too_many.message_id, 5))

            await redis.delete(f"captcha:{message.from_user.id}")
            await set_rate_limit(message.from_user.id, 60)
            time_left = await get_rate_limit_time_left(message.from_user.id)
            await message.answer(f"Пожалуйста, подождите {time_left} секунд и начните заново.")
            await state.clear()
            return

        # Отслеживаем ввод пользователя
        user_answer = (message.text or "").strip()
        await track_captcha_input(message.from_user.id, user_answer)
        
        # Увеличиваем счетчик попыток
        current_attempts = await increment_captcha_attempts(message.from_user.id)
        
        # Подготавливаем данные пользователя для анализа
        user_data = {
            "id": message.from_user.id,  # Исправлено: используем "id" вместо "user_id"
            "user_id": message.from_user.id,  # Оставляем для совместимости
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
            "is_bot": message.from_user.is_bot,
            "is_premium": message.from_user.is_premium,
        }
        
        # Используем улучшенную систему проверки
        # Получаем решение на основе всех проверок
        logger.info(f"🔍 Начинаем анализ пользователя @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}]")
        
        # Определяем chat_id для анализа сообщений
        chat_id_for_analysis = 0
        if group_name.startswith("private_"):
            chat_id_for_analysis = int(group_name.replace("private_", ""))
        elif group_name.startswith("-") and group_name[1:].isdigit():
            chat_id_for_analysis = int(group_name)
        else:
            # Для публичных групп пытаемся получить chat_id из Redis
            chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
            if chat_id_from_redis:
                chat_id_for_analysis = int(chat_id_from_redis)
        
        decision = await get_enhanced_captcha_decision(
            message.from_user.id, 
            user_data, 
            str(captcha_answer), 
            user_answer,
            message.bot,
            chat_id_for_analysis if chat_id_for_analysis != 0 else None
        )
        logger.info(f"🔍 Анализ завершен для пользователя @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}]")
        
        # Сохраняем уровень скама в БД (всегда, независимо от результата)
        try:
            # Определяем chat_id для сохранения
            chat_id_for_db = 0
            if group_name.startswith("private_"):
                chat_id_for_db = int(group_name.replace("private_", ""))
            elif group_name.startswith("-") and group_name[1:].isdigit():
                chat_id_for_db = int(group_name)
            else:
                # Для публичных групп пытаемся получить chat_id из Redis
                chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                if chat_id_from_redis:
                    chat_id_for_db = int(chat_id_from_redis)
            
            if chat_id_for_db != 0:
                await save_scam_level_to_db(
                    session, 
                    message.from_user.id, 
                    chat_id_for_db, 
                    decision["total_risk_score"], 
                    decision["risk_factors"], 
                    user_data,
                    message.bot
                )
                
                # Логируем попытку капчи с кнопками управления
                try:
                    from bot.utils.logger import log_captcha_attempt_with_buttons
                    chat_info = await message.bot.get_chat(chat_id_for_db)
                    log_captcha_attempt_with_buttons(
                        username=message.from_user.username,
                        user_id=message.from_user.id,
                        chat_name=chat_info.title,
                        chat_id=chat_id_for_db,
                        risk_score=decision["total_risk_score"],
                        risk_factors=decision["risk_factors"],
                        method="Визуальная капча"
                    )
                except Exception as log_error:
                    logger.error(f"Ошибка при логировании попытки капчи: {log_error}")
                    
        except Exception as e:
            logger.error(f"Ошибка при сохранении уровня скама в БД: {e}")

        if decision["approved"]:
            # Капча решена
            await redis.delete(f"captcha:{message.from_user.id}")
            
            # Удаляем все напоминания сразу
            reminder_key = f"captcha_reminder_msgs:{message.from_user.id}"
            reminder_msgs = await redis.get(reminder_key)
            if reminder_msgs:
                # Преобразуем из bytes в строку если нужно
                reminder_str = reminder_msgs.decode('utf-8') if isinstance(reminder_msgs, bytes) else str(reminder_msgs)
                for reminder_id in reminder_str.split(","):
                    try:
                        await message.bot.delete_message(chat_id=message.from_user.id, message_id=int(reminder_id))
                    except Exception as e:
                        if "message to delete not found" not in str(e).lower():
                            logger.warning(f"Не удалось удалить напоминание {reminder_id}: {e}")
                await redis.delete(reminder_key)

            # Удалим все сообщения через 5 секунд
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 5))
            
            # Проверяем, нужно ли автоматически мутить скаммера
            if decision.get("should_auto_mute", False):
                # Устанавливаем флаг для автомута после одобрения
                await redis.setex(f"auto_mute_scammer:{message.from_user.id}:{chat_id_for_analysis}", 300, "1")
                logger.warning(f"🚨 Пользователь @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] помечен для автомута как скаммер")

            # Определяем chat_id для approve
            chat_id: Optional[int] = None
            if group_name.startswith("private_"):
                chat_id = int(group_name.replace("private_", ""))
            else:
                # Проверяем, является ли group_name числовым ID группы
                try:
                    # Если group_name это числовой ID группы (начинается с -)
                    if group_name.startswith("-") and group_name[1:].isdigit():
                        chat_id = int(group_name)
                        logger.info(f"Определен chat_id из числового ID: {chat_id}")
                    else:
                        # Пытаемся найти в Redis по оригинальному group_name
                        if await redis.exists(f"join_request:{message.from_user.id}:{group_name}"):
                            val = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                            chat_id = int(val)
                            logger.info(f"Найден chat_id в Redis: {chat_id}")
                except ValueError:
                    logger.error(f"Не удалось преобразовать group_name в chat_id: {group_name}")

            if chat_id:
                # Пытаемся одобрить запрос
                result = await approve_chat_join_request(message.bot, chat_id, message.from_user.id)

                if result["success"]:
                    # Устанавливаем флаг, что пользователь прошел капчу
                    await redis.setex(f"captcha_passed:{message.from_user.id}:{chat_id}", 3600, "1")
                    logger.info(f"✅ Пользователь @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] прошел капчу для группы {chat_id}")
                    
                    # Получаем реальное название группы
                    try:
                        chat = await message.bot.get_chat(chat_id)
                        group_display_name = chat.title
                        logger.info(f"Получено название группы: {group_display_name}")
                        
                        # ЛОГИРУЕМ УСПЕШНОЕ ПРОХОЖДЕНИЕ КАПЧИ
                        scammer_level = decision.get("total_risk_score", 0)
                        await log_captcha_passed(
                            bot=message.bot,
                            user=message.from_user,
                            chat=chat,
                            scammer_level=scammer_level,
                            session=session
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы: {e}")
                        group_display_name = group_name.replace("_", " ").title()

                    # Проверяем и нормализуем group_link перед передачей
                    group_link_for_keyboard = result.get("group_link")
                    if group_link_for_keyboard:
                        if isinstance(group_link_for_keyboard, bytes):
                            group_link_for_keyboard = group_link_for_keyboard.decode('utf-8')
                        elif not isinstance(group_link_for_keyboard, str):
                            group_link_for_keyboard = str(group_link_for_keyboard) if group_link_for_keyboard else None
                    logger.info(f"🔗 Создаем кнопку (approve_user): group_link='{group_link_for_keyboard}' (тип: {type(group_link_for_keyboard)})")
                    
                    try:
                        keyboard = await get_group_join_keyboard(group_link_for_keyboard, group_display_name)
                        success_msg = await message.answer(result["message"], reply_markup=keyboard, parse_mode="HTML")
                    except Exception as keyboard_error:
                        error_msg = str(keyboard_error)
                        if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                            logger.error(f"❌ Ошибка 400 при создании кнопки (process_captcha_answer), отправляем сообщение без кнопки: {keyboard_error}")
                            success_msg = await message.answer(result["message"], parse_mode="HTML")
                            if group_link_for_keyboard:
                                try:
                                    await message.answer(f"🔗 Ссылка для присоединения:\n{group_link_for_keyboard}")
                                except Exception:
                                    pass
                        else:
                            raise keyboard_error
                    # Удаляем сообщение об успехе через 2-3 минуты (150 секунд = 2.5 минуты)
                    asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))
                else:
                    # Ошибка approve — показываем сообщение и (если есть) ссылку
                    await message.answer(result["message"], parse_mode="HTML")

                    if result["group_link"]:
                        try:
                            chat = await message.bot.get_chat(chat_id)
                            group_display_name = chat.title
                            logger.info(f"Получено название группы для fallback: {group_display_name}")
                        except Exception as e:
                            logger.error(f"Ошибка при получении названия группы для fallback: {e}")
                            group_display_name = group_name.replace("_", " ").title()

                        # Проверяем и нормализуем group_link перед передачей
                        group_link_for_keyboard = result.get("group_link")
                        if group_link_for_keyboard:
                            if isinstance(group_link_for_keyboard, bytes):
                                group_link_for_keyboard = group_link_for_keyboard.decode('utf-8')
                            elif not isinstance(group_link_for_keyboard, str):
                                group_link_for_keyboard = str(group_link_for_keyboard) if group_link_for_keyboard else None
                        logger.info(f"🔗 Создаем кнопку (fallback): group_link='{group_link_for_keyboard}' (тип: {type(group_link_for_keyboard)})")
                        
                        try:
                            keyboard = await get_group_join_keyboard(group_link_for_keyboard, group_display_name)
                            await message.answer("Используйте эту кнопку для присоединения:", reply_markup=keyboard)
                        except Exception as keyboard_error:
                            error_msg = str(keyboard_error)
                            if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                                logger.error(f"❌ Ошибка 400 при создании кнопки (process_captcha_answer fallback), отправляем ссылку текстом: {keyboard_error}")
                                if group_link_for_keyboard:
                                    await message.answer(f"Используйте эту ссылку для присоединения:\n🔗 {group_link_for_keyboard}")
                                else:
                                    await message.answer("Используйте ссылку для присоединения к группе.")
                            else:
                                raise keyboard_error

                logger.info(f"Одобрен/обработан запрос на вступление user=@{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] group={group_name}")
            else:
                # Запрос не найден — отдаём прямую ссылку
                if group_name.startswith("private_"):
                    # Для приватной группы без активного join_request — просим переотправить заявку
                    warn = await message.answer(
                        "Ваш запрос на вступление истёк. Пожалуйста, отправьте новый запрос на вступление в группу."
                    )
                    message_ids.append(warn.message_id)
                    await state.update_data(message_ids=message_ids)
                else:
                    group_info = await get_group_by_name(session, group_name)
                    if group_info:
                        group_link = f"https://t.me/{group_name}"
                        try:
                            keyboard = await get_group_join_keyboard(group_link, group_info.title)
                            success_msg = await message.answer(
                                f"Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{group_info.title}»:",
                                reply_markup=keyboard,
                            )
                        except Exception as keyboard_error:
                            error_msg = str(keyboard_error)
                            if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                                logger.error(f"❌ Ошибка 400 при создании кнопки (get_group_by_name), отправляем сообщение без кнопки: {keyboard_error}")
                                success_msg = await message.answer(
                                    f"Капча пройдена успешно! Используйте ссылку ниже, чтобы войти в «{group_info.title}»:\n🔗 {group_link}"
                                )
                            else:
                                raise keyboard_error
                        # Удаляем сообщение об успехе через 2-3 минуты (150 секунд = 2.5 минуты)
                        asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))
                    else:
                        group_link = await get_group_link_from_redis_or_create(message.bot, group_name)
                        if not group_link:
                            await message.answer(
                                "Капча пройдена, но не удалось сгенерировать ссылку на группу. "
                                "Пожалуйста, отправьте запрос на вступление повторно."
                            )
                        else:
                            # Получаем реальное название группы
                            try:
                                if group_name.startswith("private_"):
                                    chat_id_for_name = int(group_name.replace("private_", ""))
                                    chat = await message.bot.get_chat(chat_id_for_name)
                                    display_name = chat.title
                                elif group_name.startswith("-") and group_name[1:].isdigit():
                                    # Если group_name это числовой ID группы
                                    chat = await message.bot.get_chat(int(group_name))
                                    display_name = chat.title
                                else:
                                    # Для публичных групп пытаемся получить chat_id из Redis
                                    chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                                    if chat_id_from_redis:
                                        chat = await message.bot.get_chat(int(chat_id_from_redis))
                                        display_name = chat.title
                                    else:
                                        # Fallback - используем group_name как есть
                                        display_name = group_name.replace("_", " ").title()
                                logger.info(f"Получено название группы: {display_name}")
                            except Exception as e:
                                logger.error(f"Ошибка при получении названия группы: {e}")
                                display_name = group_name.replace("_", " ").title()
                            
                            # Нормализуем group_link перед передачей (может быть bytes из Redis)
                            if isinstance(group_link, bytes):
                                group_link = group_link.decode('utf-8')
                            elif not isinstance(group_link, str):
                                group_link = str(group_link) if group_link else None
                            
                            try:
                                keyboard = await get_group_join_keyboard(group_link, display_name)
                                await message.answer(
                                    f"Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{display_name}»:",
                                    reply_markup=keyboard,
                                )
                            except Exception as keyboard_error:
                                error_msg = str(keyboard_error)
                                if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                                    logger.error(f"❌ Ошибка 400 при создании кнопки (get_group_link_from_redis), отправляем ссылку текстом: {keyboard_error}")
                                    await message.answer(
                                        f"Капча пройдена успешно! Используйте ссылку ниже, чтобы войти в «{display_name}»:\n🔗 {group_link}"
                                    )
                                else:
                                    raise keyboard_error

            await state.clear()
            return

        # Обработка умеренного риска (30-49 баллов)
        elif not decision["approved"] and 30 <= decision["total_risk_score"] < 50:
            # Для умеренного риска требуем дополнительную проверку
            factors_text = ", ".join(decision['risk_factors'][:2]) if decision['risk_factors'] else "неизвестно"
            moderate_risk_msg = await message.answer(
                f"⚠️ <b>Обнаружен умеренный риск</b>\n\n"
                f"📊 <b>Оценка:</b> {decision['total_risk_score']}/100\n"
                f"🔍 <b>Факторы риска:</b> {factors_text}\n\n"
                f"🛡️ <b>Для безопасности требуется дополнительная проверка</b>\n"
                f"❓ <b>Пожалуйста, ответьте на дополнительный вопрос:</b>",
                parse_mode="HTML"
            )
            message_ids.append(moderate_risk_msg.message_id)
            await state.update_data(message_ids=message_ids)
            
            # Добавляем дополнительный вопрос для проверки
            additional_questions = [
                ("да", "✅ <b>Дополнительная проверка</b>\n\n❓ <b>Напишите слово:</b> <code>да</code>"),
                ("нет", "✅ <b>Дополнительная проверка</b>\n\n❓ <b>Напишите слово:</b> <code>нет</code>"),
                ("привет", "✅ <b>Дополнительная проверка</b>\n\n❓ <b>Напишите слово:</b> <code>привет</code>"),
                ("спасибо", "✅ <b>Дополнительная проверка</b>\n\n❓ <b>Напишите слово:</b> <code>спасибо</code>"),
                ("пожалуйста", "✅ <b>Дополнительная проверка</b>\n\n❓ <b>Напишите слово:</b> <code>пожалуйста</code>")
            ]
            
            import random
            additional_answer, additional_question = random.choice(additional_questions)
            
            # Сохраняем дополнительный вопрос в состоянии
            await state.update_data(
                additional_question=additional_question,
                additional_answer=additional_answer,
                moderate_risk_check=True
            )
            
            # Отправляем дополнительный вопрос
            additional_msg = await message.answer(additional_question, parse_mode="HTML")
            message_ids.append(additional_msg.message_id)
            await state.update_data(message_ids=message_ids)
            
            # Удаляем сообщения через 2 минуты
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 120))
            
            return

        # Неверный ответ или подозрительное поведение
        attempts += 1
        await state.update_data(attempts=attempts)
        
        # ЛОГИРУЕМ НЕУДАЧНУЮ ПОПЫТКУ КАПЧИ
        try:
            chat_id_for_log_failed = 0
            if group_name.startswith("private_"):
                chat_id_for_log_failed = int(group_name.replace("private_", ""))
            elif group_name.startswith("-") and group_name[1:].isdigit():
                chat_id_for_log_failed = int(group_name)
            else:
                chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                if chat_id_from_redis:
                    chat_id_for_log_failed = int(chat_id_from_redis)
            
            if chat_id_for_log_failed != 0:
                try:
                    chat_for_log = await message.bot.get_chat(chat_id_for_log_failed)
                    await log_captcha_failed(
                        bot=message.bot,
                        user=message.from_user,
                        chat=chat_for_log,
                        attempt=attempts,
                        reason=decision.get("reason", "Неверный ответ"),
                        session=session
                    )
                except Exception as log_fail_error:
                    logger.error(f"Ошибка при логировании неудачной капчи: {log_fail_error}")
        except Exception as e:
            logger.error(f"Ошибка при получении chat_id для логирования неудачи: {e}")
        
        # Если пользователь заблокирован как подозрительный (только для очень высокого риска)
        if not decision["approved"] and decision["total_risk_score"] >= 100:
            blocked_msg = await message.answer(
                f"❌ Доступ заблокирован: {decision['reason']}\n"
                f"Причины: {', '.join(decision['risk_factors'])}"
            )
            message_ids.append(blocked_msg.message_id)
            await state.update_data(message_ids=message_ids)
            
            # Удаляем все сообщения через 10 секунд
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 10))
            
            await redis.delete(f"captcha:{message.from_user.id}")
            
            # Удаляем все напоминания сразу
            reminder_key = f"captcha_reminder_msgs:{message.from_user.id}"
            reminder_msgs = await redis.get(reminder_key)
            if reminder_msgs:
                reminder_str = reminder_msgs.decode('utf-8') if isinstance(reminder_msgs, bytes) else str(reminder_msgs)
                for reminder_id in reminder_str.split(","):
                    try:
                        await message.bot.delete_message(chat_id=message.from_user.id, message_id=int(reminder_id))
                    except Exception as e:
                        if "message to delete not found" not in str(e).lower():
                            logger.warning(f"Не удалось удалить напоминание {reminder_id}: {e}")
                await redis.delete(reminder_key)
            
            await state.clear()
            return

        # Логируем неуспех (если есть chat_id)
        try:
            chat_id_for_log = 0
            if group_name.startswith("private_"):
                chat_id_for_log = int(group_name.replace("private_", ""))
            elif group_name.startswith("-") and group_name[1:].isdigit():
                # Если group_name это числовой ID группы
                chat_id_for_log = int(group_name)
            else:
                # Для публичных групп пытаемся получить chat_id из Redis
                chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                if chat_id_from_redis:
                    chat_id_for_log = int(chat_id_from_redis)
            
            # Только если у нас есть валидный chat_id
            if chat_id_for_log != 0:
                # Используем новую систему оценки риска вместо старой логики скаммера
                logger.info(f"📊 Неверный ответ на капчу от пользователя @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] в группе {chat_id_for_log}")
        except Exception as e:
            logger.error(f"Ошибка при отслеживании неудачной капчи: {e}")

        # Превышение попыток
        if attempts >= 3:
            if group_name.startswith("private_"):
                too_many_msg = await message.answer(
                    "Превышено количество попыток. Пожалуйста, начните процесс заново."
                )
            else:
                group_link = await get_group_link_from_redis_or_create(message.bot, group_name)
                if group_link:
                    # Получаем реальное название группы
                    try:
                        if group_name.startswith("private_"):
                            chat_id_for_name = int(group_name.replace("private_", ""))
                            chat = await message.bot.get_chat(chat_id_for_name)
                            group_title = chat.title
                        elif group_name.startswith("-") and group_name[1:].isdigit():
                            chat = await message.bot.get_chat(int(group_name))
                            group_title = chat.title
                        else:
                            group_title = group_name.replace("_", " ").title()
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы для too_many: {e}")
                        group_title = group_name.replace("_", " ").title()
                    
                    too_many_msg = await message.answer(
                        "Превышено количество попыток. Пожалуйста, начните процесс заново.\n"
                        f"Отправьте запрос в группу: <a href='{group_link}'>{group_title}</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                else:
                    too_many_msg = await message.answer(
                        "Превышено количество попыток. Пожалуйста, начните процесс заново и отправьте запрос в группу."
                    )

            message_ids.append(too_many_msg.message_id)
            await state.update_data(message_ids=message_ids)

            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 90))

            await redis.delete(f"captcha:{message.from_user.id}")
            await set_rate_limit(message.from_user.id, 60)
            
            # ЛОГИРУЕМ ТАЙМАУТ КАПЧИ (превышение попыток)
            try:
                chat_id_for_timeout = 0
                if group_name.startswith("private_"):
                    chat_id_for_timeout = int(group_name.replace("private_", ""))
                elif group_name.startswith("-") and group_name[1:].isdigit():
                    chat_id_for_timeout = int(group_name)
                else:
                    chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                    if chat_id_from_redis:
                        chat_id_for_timeout = int(chat_id_from_redis)
                
                if chat_id_for_timeout != 0:
                    try:
                        chat_for_timeout = await message.bot.get_chat(chat_id_for_timeout)
                        await log_captcha_timeout(
                            bot=message.bot,
                            user=message.from_user,
                            chat=chat_for_timeout,
                            attempts=attempts,
                            session=session
                        )
                    except Exception as timeout_log_error:
                        logger.error(f"Ошибка при логировании таймаута капчи: {timeout_log_error}")
            except Exception as e:
                logger.error(f"Ошибка при получении chat_id для логирования таймаута: {e}")
            
            await state.clear()
            return

        # Генерируем новую капчу
        try:
            new_answer, new_image = await generate_visual_captcha()
            await state.update_data(captcha_answer=new_answer)
            await save_captcha_data(message.from_user.id, new_answer, group_name, attempts)
            
            # Начинаем новое отслеживание поведения для новой капчи
            await start_behavior_tracking(message.from_user.id)

            # Удаляем предыдущие сообщения через 5 секунд
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 5))

            # Формируем сообщение об ошибке с учетом анализа
            if decision["total_risk_score"] > 0:
                factors_text = ", ".join(decision['risk_factors'][:2]) if decision['risk_factors'] else "неизвестно"
                error_msg = (
                    f"❌ <b>{decision['reason']}</b>\n\n"
                    f"⚠️ <b>Факторы риска:</b> {factors_text}\n"
                    f"🔄 <b>Осталось попыток:</b> {3 - attempts}"
                )
            else:
                error_msg = (
                    f"❌ <b>Неверный ответ</b>\n\n"
                    f"🔄 <b>Осталось попыток:</b> {3 - attempts}"
                )
            
            wrong_msg = await message.answer(error_msg, parse_mode="HTML")

            try:
                captcha_msg = await message.answer_photo(
                    photo=new_image,
                    caption="🧩 <b>Пожалуйста, введите символы или решите выражение:</b>",
                    parse_mode="HTML"
                )
                message_ids = [wrong_msg.message_id, captcha_msg.message_id]
            except Exception as network_error:
                logger.error(f"❌ Ошибка сети при отправке новой капчи: {network_error}")
                fallback_msg = await message.answer(
                    f"⚠️ Не удалось отправить изображение капчи.\n"
                    f"🔑 Ваш код: **{new_answer}**\n"
                    f"Введите этот код:",
                    parse_mode="Markdown",
                )
                message_ids = [wrong_msg.message_id, fallback_msg.message_id]

            await state.update_data(message_ids=message_ids)

            # Удалим через 5 минут
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 300))
            
            # Планируем напоминание через 2 минуты для новой капчи
            asyncio.create_task(schedule_captcha_reminder(message.bot, message.from_user.id, group_name, 2))

        except Exception as captcha_error:
            logger.error(f"❌ Ошибка при генерации новой капчи: {captcha_error}")
            await message.answer("Произошла ошибка при генерации новой капчи. Попробуйте позже.")
            await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке ответа на капчу: {e}")
        logger.debug(traceback.format_exc())
        try:
            err_msg = await message.answer("Пожалуйста, введите корректный ответ, соответствующий изображению.")
            data = await state.get_data()
            mids = data.get("message_ids", [])
            mids.append(err_msg.message_id)
            await state.update_data(message_ids=mids)
        except Exception:
            pass


@visual_captcha_handler_router.message(Command("check"))
async def cmd_check(message: Message, session: AsyncSession):
    """Простой тест отправки сообщения пользователю."""
    await save_user_to_db(
        session,
        {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
        },
    )
    try:
        await message.bot.send_message(message.from_user.id, "Проверка связи ✅")
        await message.answer("Сообщение успешно отправлено")
    except Exception as e:
        await message.answer(f"❌ Не могу отправить сообщение: {e}")


@visual_captcha_handler_router.message(Command("checkuser"))
async def cmd_check_user(message: Message, session: AsyncSession):
    """Проверка возможности отправки сообщения указанному пользователю (ID или @username)."""
    await save_user_to_db(
        session,
        {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
        },
    )

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите ID или @username пользователя: /checkuser <id или @username>")
        return

    target = args[1]
    try:
        if target.isdigit():
            target_id = int(target)
        elif target.startswith("@"):
            username = target[1:]
            chat = await message.bot.get_chat(username)
            target_id = chat.id
        else:
            await message.answer("Неверный формат. Укажите ID (число) или @username")
            return

        await message.bot.send_message(target_id, "Проверка связи от администратора ✅")
        await message.answer(f"✅ Сообщение успешно отправлено (ID: {target_id})")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}")


@visual_captcha_handler_router.callback_query(F.data == "visual_captcha_settings")
async def visual_captcha_settings(callback_query: CallbackQuery, state: FSMContext):
    """Отображает настройки визуальной капчи для группы."""
    user_id = callback_query.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback_query.answer("❌ Не удалось определить группу. Попробуйте снова.", show_alert=True)
        return

    try:
        is_admin = await check_admin_rights(callback_query.bot, int(group_id), user_id)
        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        captcha_enabled = await redis.get(f"visual_captcha_enabled:{group_id}") or "0"
        keyboard = await get_group_settings_keyboard(group_id, captcha_enabled)

        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard,
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка при настройке визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при загрузке настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data.startswith("set_visual_captcha:"))
async def set_visual_captcha(callback_query: CallbackQuery, state: FSMContext):
    """Устанавливает состояние визуальной капчи (вкл/выкл)."""
    parts = callback_query.data.split(":")
    if len(parts) < 3:
        await callback_query.answer("Некорректные данные", show_alert=True)
        return

    chat_id = parts[1]
    enabled = parts[2]

    try:
        user_id = callback_query.from_user.id
        is_admin = await check_admin_rights(callback_query.bot, int(chat_id), user_id)
        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        await set_visual_captcha_status(int(chat_id), enabled == "1")
        status_message = "Визуальная капча включена" if enabled == "1" else "Визуальная капча отключена"
        await callback_query.answer(status_message, show_alert=True)

        keyboard = await get_group_settings_keyboard(chat_id, enabled)
        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Ошибка при установке настроек визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при сохранении настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data == "captcha_settings")
async def back_to_main_captcha_settings(callback: CallbackQuery, state: FSMContext):
    """Возврат к основным настройкам капчи в ЛС."""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось определить группу", show_alert=True)
        return

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Обработка настроек перенесена в group_settings_handler
    await callback.answer("Настройки доступны через команду /settings", show_alert=True)


@visual_captcha_handler_router.message(Command("start"))
async def start_command(message: Message):
    """Обработчик обычной команды /start"""
    user_id = message.from_user.id
    
    if user_id == 619924982:
        # Приветствие для разработчика
        text = (
            "👋 <b>Привет, разработчик!</b>\n\n"
            "🤖 Бот готов к работе.\n\n"
            "📋 <b>Доступные команды:</b>\n"
            "• /settings - Настройки групп\n"
            "• /bot_access - Настройки доступа к боту\n"
            "• /drop scam - Сброс уровня скама\n"
            "• /help - Полный список команд\n\n"
            "🔧 Используйте /bot_access для переключения режима доступа."
        )
    else:
        # Обычное приветствие для пользователей
        text = (
            "👋 <b>Привет!</b>\n\n"
            "🤖 Добро пожаловать!\n\n"
            "Этот бот помогает управлять группами с функциями:\n"
            "• Визуальная капча для новых участников\n"
            "• Антиспам защита\n"
            "• Настройки мута\n\n"
            "Для получения помощи используйте /help"
        )
    
    await message.answer(text, parse_mode="HTML")


@visual_captcha_handler_router.message(Command("drop"))
async def drop_scam_command(message: Message, session: AsyncSession):
    """Команда для сброса уровня скама пользователя."""
    user_id = message.from_user.id
    
    # Проверяем, что это разработчик
    if user_id != 619924982:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Парсим аргументы команды
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "📝 <b>Использование команды:</b>\n\n"
            "<code>/drop scam &lt;user_id&gt;</code> - сбросить уровень скама для пользователя\n"
            "<code>/drop scam &lt;user_id&gt; &lt;chat_id&gt;</code> - сбросить для конкретной группы\n\n"
            "<b>Примеры:</b>\n"
            "<code>/drop scam 123456789</code>\n"
            "<code>/drop scam 123456789 -1001234567890</code>",
            parse_mode="HTML"
        )
        return
    
    if args[1].lower() != "scam":
        await message.answer("❌ Неверный тип сброса. Используйте: <code>/drop scam &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    
    try:
        target_user_id = int(args[2])
        target_chat_id = int(args[3]) if len(args) > 3 else None
        
        # Сбрасываем уровень скама
        success = await reset_user_scam_level(session, target_user_id, target_chat_id)
        
        if success:
            if target_chat_id:
                await message.answer(f"✅ Уровень скама сброшен для пользователя {target_user_id} в группе {target_chat_id}")
            else:
                await message.answer(f"✅ Уровень скама сброшен для пользователя {target_user_id} во всех группах")
        else:
            await message.answer(f"❌ Не удалось сбросить уровень скама для пользователя {target_user_id}")
            
    except ValueError:
        await message.answer("❌ Неверный формат ID. Используйте числовые ID.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /drop scam: {e}")
        await message.answer("❌ Произошла ошибка при выполнении команды.")


async def approve_user_join_request(message: Message, group_name: str, message_ids: list):
    """Одобряет запрос на вступление пользователя в группу."""
    try:
        # Определяем chat_id для approve
        chat_id: Optional[int] = None
        if group_name.startswith("private_"):
            chat_id = int(group_name.replace("private_", ""))
        else:
            # Проверяем, является ли group_name числовым ID группы
            try:
                # Если group_name это числовой ID группы (начинается с -)
                if group_name.startswith("-") and group_name[1:].isdigit():
                    chat_id = int(group_name)
                    logger.info(f"Определен chat_id из числового ID: {chat_id}")
                else:
                    # Пытаемся найти в Redis по оригинальному group_name
                    if await redis.exists(f"join_request:{message.from_user.id}:{group_name}"):
                        val = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                        chat_id = int(val)
                        logger.info(f"Найден chat_id в Redis: {chat_id}")
            except ValueError:
                logger.error(f"Не удалось преобразовать group_name в chat_id: {group_name}")

        if chat_id:
            # Пытаемся одобрить запрос
            result = await approve_chat_join_request(message.bot, chat_id, message.from_user.id)

            if result["success"]:
                # Устанавливаем флаг, что пользователь прошел капчу
                await redis.setex(f"captcha_passed:{message.from_user.id}:{chat_id}", 3600, "1")
                logger.info(f"✅ Пользователь {message.from_user.id} прошел капчу для группы {chat_id}")
                
                # Получаем реальное название группы
                try:
                    chat = await message.bot.get_chat(chat_id)
                    group_display_name = chat.title
                    logger.info(f"Получено название группы: {group_display_name}")
                except Exception as e:
                    logger.error(f"Ошибка при получении названия группы: {e}")
                    group_display_name = group_name.replace("_", " ").title()

                # Проверяем и нормализуем group_link перед передачей
                group_link_for_keyboard = result.get("group_link")
                if group_link_for_keyboard:
                    # Преобразуем в строку если нужно (может быть bytes из Redis или объект)
                    if isinstance(group_link_for_keyboard, bytes):
                        group_link_for_keyboard = group_link_for_keyboard.decode('utf-8')
                    elif not isinstance(group_link_for_keyboard, str):
                        group_link_for_keyboard = str(group_link_for_keyboard) if group_link_for_keyboard else None
                logger.info(f"🔗 Создаем кнопку: group_link='{group_link_for_keyboard}' (тип: {type(group_link_for_keyboard)})")
                
                try:
                    keyboard = await get_group_join_keyboard(group_link_for_keyboard, group_display_name)
                    success_msg = await message.answer(result["message"], reply_markup=keyboard, parse_mode="HTML")
                except Exception as keyboard_error:
                    error_msg = str(keyboard_error)
                    if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                        logger.error(f"❌ Ошибка 400 при создании кнопки, отправляем сообщение без кнопки: {keyboard_error}")
                        success_msg = await message.answer(result["message"], parse_mode="HTML")
                        # Пытаемся отправить ссылку отдельным сообщением
                        if group_link_for_keyboard:
                            try:
                                await message.answer(f"🔗 Ссылка для присоединения:\n{group_link_for_keyboard}")
                            except Exception:
                                pass
                    else:
                        raise keyboard_error
                
                # Удаляем сообщение об успехе через 2-3 минуты (150 секунд = 2.5 минуты)
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))
            else:
                # Ошибка approve — показываем сообщение и (если есть) ссылку
                await message.answer(result["message"], parse_mode="HTML")

                if result["group_link"]:
                    try:
                        chat = await message.bot.get_chat(chat_id)
                        group_display_name = chat.title
                        logger.info(f"Получено название группы для fallback: {group_display_name}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы для fallback: {e}")
                        group_display_name = group_name.replace("_", " ").title()

                    # Проверяем и нормализуем group_link перед передачей
                    group_link_for_keyboard = result.get("group_link")
                    if group_link_for_keyboard:
                        if isinstance(group_link_for_keyboard, bytes):
                            group_link_for_keyboard = group_link_for_keyboard.decode('utf-8')
                        elif not isinstance(group_link_for_keyboard, str):
                            group_link_for_keyboard = str(group_link_for_keyboard) if group_link_for_keyboard else None
                    logger.info(f"🔗 Создаем кнопку (approve_user fallback): group_link='{group_link_for_keyboard}' (тип: {type(group_link_for_keyboard)})")
                    
                    try:
                        keyboard = await get_group_join_keyboard(group_link_for_keyboard, group_display_name)
                        await message.answer("Используйте эту кнопку для присоединения:", reply_markup=keyboard)
                    except Exception as keyboard_error:
                        error_msg = str(keyboard_error)
                        if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                            logger.error(f"❌ Ошибка 400 при создании кнопки (fallback), отправляем ссылку текстом: {keyboard_error}")
                            if group_link_for_keyboard:
                                await message.answer(f"Используйте эту ссылку для присоединения:\n🔗 {group_link_for_keyboard}")
                            else:
                                await message.answer("Используйте ссылку для присоединения к группе.")
                        else:
                            raise keyboard_error

            logger.info(f"Одобрен/обработан запрос на вступление user={message.from_user.id} group={group_name}")
        else:
            # Запрос не найден — отдаём прямую ссылку
            if group_name.startswith("private_"):
                # Для приватной группы без активного join_request — просим переотправить заявку
                warn = await message.answer(
                    "Ваш запрос на вступление истёк. Пожалуйста, отправьте новый запрос на вступление в группу."
                )
                message_ids.append(warn.message_id)
            else:
                group_link = await get_group_link_from_redis_or_create(message.bot, group_name)
                if not group_link:
                    await message.answer(
                        "Капча пройдена, но не удалось сгенерировать ссылку на группу. "
                        "Пожалуйста, отправьте запрос на вступление повторно."
                    )
                else:
                    # Получаем реальное название группы
                    try:
                        if group_name.startswith("private_"):
                            chat_id_for_name = int(group_name.replace("private_", ""))
                            chat = await message.bot.get_chat(chat_id_for_name)
                            display_name = chat.title
                        elif group_name.startswith("-") and group_name[1:].isdigit():
                            # Если group_name это числовой ID группы
                            chat = await message.bot.get_chat(int(group_name))
                            display_name = chat.title
                        else:
                            # Для публичных групп пытаемся получить chat_id из Redis
                            chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                            if chat_id_from_redis:
                                chat = await message.bot.get_chat(int(chat_id_from_redis))
                                display_name = chat.title
                            else:
                                # Fallback - используем group_name как есть
                                display_name = group_name.replace("_", " ").title()
                        logger.info(f"Получено название группы: {display_name}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы: {e}")
                        display_name = group_name.replace("_", " ").title()
                    
                    # Нормализуем group_link перед передачей (может быть bytes из Redis)
                    if isinstance(group_link, bytes):
                        group_link = group_link.decode('utf-8')
                    elif not isinstance(group_link, str):
                        group_link = str(group_link) if group_link else None
                    
                    try:
                        keyboard = await get_group_join_keyboard(group_link, display_name)
                        success_msg = await message.answer(
                            f"Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{display_name}»:",
                            reply_markup=keyboard,
                        )
                    except Exception as keyboard_error:
                        error_msg = str(keyboard_error)
                        if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                            logger.error(f"❌ Ошибка 400 при создании кнопки, отправляем сообщение без кнопки: {keyboard_error}")
                            success_msg = await message.answer(
                                f"Капча пройдена успешно! Используйте ссылку ниже, чтобы войти в «{display_name}»:\n🔗 {group_link}"
                            )
                        else:
                            raise keyboard_error
                    # Удаляем сообщение об успехе через 2-3 минуты (150 секунд = 2.5 минуты)
                    asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))

    except Exception as e:
        logger.error(f"Ошибка при одобрении запроса на вступление: {e}")
        await message.answer("Произошла ошибка при обработке запроса. Попробуйте позже.")


# Обработчики для fallback callback-запросов
@visual_captcha_handler_router.callback_query(F.data == "captcha_fallback")
async def handle_captcha_fallback(callback: CallbackQuery):
    """Обработчик для fallback кнопки капчи"""
    await callback.answer("❌ Ссылка недоступна. Пожалуйста, попробуйте позже.", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data == "group_link_fallback")
async def handle_group_link_fallback(callback: CallbackQuery):
    """Обработчик для fallback кнопки присоединения к группе"""
    await callback.answer("❌ Ссылка на группу недоступна. Обратитесь к администратору.", show_alert=True)
