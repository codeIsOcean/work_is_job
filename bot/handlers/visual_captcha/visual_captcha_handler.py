# handlers/captcha/visual_captcha_handler.py
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from aiogram.enums import ChatMemberStatus

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
from bot.services.captcha_flow_logic import (
    load_captcha_settings,
    should_require_captcha,
    evaluate_admission,
    send_captcha_prompt,
    prepare_invite_flow,
    prepare_manual_approval_flow,
    build_restriction_permissions,
    clear_captcha_state,
    CaptchaDecision,
)
from bot.database.session import get_session
from bot.database.queries import get_group_by_name
from bot.services.bot_activity_journal.bot_activity_journal_logic import (
    log_join_request,
    log_captcha_passed,
    log_captcha_failed,
    log_captcha_timeout,
    log_new_member,
)
from bot.services.spammer_registry import mute_suspicious_user_across_groups

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

    async with get_session() as session:
        settings_snapshot = await load_captcha_settings(session, chat_id)
        decision = await should_require_captcha(settings=settings_snapshot, source="join_request")

        if decision.fallback_mode or not decision.require_captcha:
            admission = await evaluate_admission(
                bot=join_request.bot,
                session=session,
                chat=chat,
                user=user,
                source="join_request",
            )

            try:
                await approve_chat_join_request(join_request.bot, chat_id, user_id)
            except Exception as exc:
                logger.error(f"Не удалось одобрить join request без капчи: {exc}")
            else:
                status = "AUTO_ALLOW_FALLBACK" if decision.fallback_mode else "AUTO_ALLOW"
                try:
                    await log_join_request(
                        bot=join_request.bot,
                        user=user,
                        chat=chat,
                        captcha_status=status,
                        saved_to_db=False,
                        session=session,
                    )
                except Exception as log_error:
                    logger.error(f"Ошибка логирования автоодобрения: {log_error}")
            return

    # БАГ #2 ФИКС: Капча должна отправляться только если включена "Капча при вступлении"
    # Проверяем ОБА условия: decision.require_captcha И visual_captcha_enabled
    # Если "Капча при вступлении" отключена (decision.require_captcha == False),
    # капча НЕ должна отправляться, даже если visual_captcha_enabled == True
    if not decision.require_captcha:
        logger.info(
            f"⛔ [JOIN_REQUEST] Капча при вступлении отключена для chat={chat_id}, "
            f"decision.require_captcha={decision.require_captcha}. Капча НЕ будет отправлена."
        )
        return
    
    captcha_enabled = await get_visual_captcha_status(chat_id)
    if not captcha_enabled:
        logger.info(
            f"⛔ [JOIN_REQUEST] Визуальная капча не активирована в группе {chat_id}, выходим"
        )
        return
    
    logger.info(
        f"✅ [JOIN_REQUEST] Капча будет отправлена для chat={chat_id}, "
        f"decision.require_captcha={decision.require_captcha}, "
        f"visual_captcha_enabled={captcha_enabled}"
    )

    # Идентификатор группы в deep-link: username или private_<id>
    group_id = chat.username or f"private_{chat.id}"

    # Сохраняем запрос на вступление (для последующего approve)
    await save_join_request(user_id, chat_id, group_id)

    # Создаём start deep-link на /start для прохождения капчи
    deep_link = await create_deeplink_for_captcha(join_request.bot, group_id)

    # Кнопка «Пройти капчу»
    keyboard = await get_captcha_keyboard(deep_link)

    try:
        await send_captcha_prompt(
            bot=join_request.bot,
            chat=chat,
            user=user,
            settings=settings_snapshot,
            source="join_request",
        )

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
        
        # ВАЖНО: deep-link сам по себе не даёт вступить в группу. Безопасность обеспечивается тем,
        # кто получил кнопку в группе (handle_captcha_fallback) и самим join-flow.
        # Более жёсткая проверка владельца (CAPTCHA_OWNER_KEY/CAPTCHA_MESSAGE_KEY) приводила к тому,
        # что даже настоящий joiner иногда блокировался. Чтобы вернуть рабочий поток,
        # здесь больше НИЧЕГО не блокируем, а просто генерируем капчу.
        
        # Генерируем капчу
        captcha_answer, captcha_image = await generate_visual_captcha()
        logger.info(f"Сгенерирована капча, ответ: {captcha_answer}")

        # Начинаем отслеживание поведения пользователя
        await start_behavior_tracking(message.from_user.id)

        # Пишем в FSM + Redis
        await state.update_data(captcha_answer=captcha_answer, group_name=group_name, attempts=0, message_ids=[])
        await save_captcha_data(message.from_user.id, captcha_answer, group_name, 0)

        # ФИКС №12: Отменяем все напоминания при начале решения капчи
        reminder_key = f"captcha_reminder_msgs:{message.from_user.id}"
        await redis.delete(reminder_key)
        # Также отменяем запланированные таймауты (через флаг)
        await redis.setex(f"captcha_started:{message.from_user.id}:{group_name}", 600, "1")

        # Отправляем изображение-капчу с повторными попытками
        captcha_sent = False
        network_error = None  # Инициализируем переменную для логирования
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
                
                # Планируем напоминание через 2 минуты (если пользователь не начнет решать)
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
            error_msg = str(network_error) if network_error else "Неизвестная ошибка"
            logger.error(f"❌ Ошибка сети при отправке капчи: {error_msg}")
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
            
            # Определяем chat_id для approve ДО установки флага автомута
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

            # БАГ №1 и №3: КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ - Сначала собираем все возможные chat_id
            # ВАЖНО: Для self-join нет join_request в Redis, поэтому ищем по group_name ВСЕГДА
            chat_ids_to_check = []
            
            # Способ 1: Из chat_id (Redis/числовой ID)
            if chat_id:
                chat_ids_to_check.append(chat_id)
                logger.info(f"✅ [CAPTCHA] chat_id найден через Redis/числовой ID: {chat_id}")
            
            # Способ 2: Из chat_id_for_db (для сохранения в БД)
            if chat_id_for_db and chat_id_for_db != 0 and chat_id_for_db not in chat_ids_to_check:
                chat_ids_to_check.append(chat_id_for_db)
                logger.info(f"✅ [CAPTCHA] chat_id_for_db добавлен: {chat_id_for_db}")
            
            # Способ 3: КРИТИЧНО - По group_name (для self-join)
            # Это гарантирует, что мы найдем правильный chat_id для всех сценариев
            try:
                from bot.database.queries import get_group_by_name
                async with get_session() as db_session:
                    group_db = await get_group_by_name(db_session, group_name)
                    if group_db:
                        if group_db.chat_id not in chat_ids_to_check:
                            chat_ids_to_check.append(group_db.chat_id)
                            logger.info(f"✅ [CAPTCHA] Найден chat_id={group_db.chat_id} по group_name={group_name} (добавлен в список)")
                        else:
                            logger.info(f"✅ [CAPTCHA] chat_id={group_db.chat_id} уже есть в списке (найден по group_name={group_name})")
                    else:
                        logger.warning(f"⚠️ [CAPTCHA] Группа с group_name={group_name} не найдена в БД")
            except Exception as e:
                logger.error(f"❌ [CAPTCHA] КРИТИЧЕСКАЯ ОШИБКА при поиске chat_id по group_name={group_name}: {e}")
                # ФИКС: Используем глобальный импорт traceback из начала файла
                logger.error(traceback.format_exc())
            
            # Используем chat_id_for_db если chat_id не определен (для автомута)
            final_chat_id = chat_ids_to_check[0] if chat_ids_to_check else (chat_id if chat_id else chat_id_for_db)
            
            # Проверяем, нужно ли автоматически мутить скаммера
            if decision.get("should_auto_mute", False) and final_chat_id:
                # Устанавливаем флаг для автомута с увеличенным TTL (1 час вместо 5 минут)
                # Это гарантирует, что флаг будет доступен когда пользователь вступит в группу
                await redis.setex(f"auto_mute_scammer:{message.from_user.id}:{final_chat_id}", 3600, "1")
                logger.warning(f"🚨 Пользователь @{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] помечен для автомута как скаммер для группы {final_chat_id} (TTL: 3600s)")
            
            # Если все равно ничего не нашли - пытаемся определить chat_id напрямую через Telegram API
            if not chat_ids_to_check:
                is_public_username = not group_name.startswith("private_") and not (
                    group_name.startswith("-") and group_name[1:].isdigit()
                )
                if is_public_username:
                    try:
                        # Пытаемся получить чат по username, Telegram ожидает строку вида "@username"
                        username = group_name
                        if not username.startswith("@"):
                            username = f"@{username}"
                        chat_obj = await message.bot.get_chat(username)
                        api_chat_id = chat_obj.id
                        chat_ids_to_check.append(api_chat_id)
                        logger.info(
                            f"✅ [CAPTCHA] chat_id={api_chat_id} найден через message.bot.get_chat('{username}')"
                        )
                    except Exception as api_err:
                        logger.warning(
                            f"⚠️ [CAPTCHA] Не удалось получить chat_id через get_chat('{group_name}'): {api_err}"
                        )

            # Если всё равно ничего не нашли - это критическая ошибка
            if not chat_ids_to_check:
                logger.error(
                    f"❌ [CAPTCHA] КРИТИЧЕСКАЯ ОШИБКА: chat_id не найден ни одним способом! "
                    f"group_name={group_name}, chat_id={chat_id}, chat_id_for_db={chat_id_for_db}"
                )
                # БАГ #10 ФИКС: Попытка последней надежды - ищем в БД через get_group_by_name (исправленная функция)
                try:
                    from bot.database.queries import get_group_by_name
                    async with get_session() as db_session:
                        group = await get_group_by_name(db_session, group_name)
                        if group:
                            chat_ids_to_check.append(group.chat_id)
                            logger.info(
                                f"✅ [CAPTCHA] Последняя надежда: найден chat_id={group.chat_id} через get_group_by_name({group_name})"
                            )
                except Exception as e:
                    logger.error(f"❌ [CAPTCHA] Не удалось найти chat_id даже через прямой запрос: {e}")
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ БАГ #1: Сначала устанавливаем флаг captcha_passed, 
            # чтобы обработчики мута не мутили пользователя снова
            # Устанавливаем флаг для ВСЕХ найденных chat_id
            for current_chat_id in chat_ids_to_check:
                await redis.setex(f"captcha_passed:{message.from_user.id}:{current_chat_id}", 3600, "1")
                logger.info(f"✅ [CAPTCHA] Флаг captcha_passed установлен: user={message.from_user.id}, chat={current_chat_id}")
            
            # Если chat_ids_to_check пуст, но есть chat_id или chat_id_for_db, устанавливаем флаг для них
            if not chat_ids_to_check:
                if chat_id:
                    await redis.setex(f"captcha_passed:{message.from_user.id}:{chat_id}", 3600, "1")
                    logger.info(f"✅ [CAPTCHA] Флаг captcha_passed установлен: user={message.from_user.id}, chat={chat_id}")
                elif chat_id_for_db:
                    await redis.setex(f"captcha_passed:{message.from_user.id}:{chat_id_for_db}", 3600, "1")
                    logger.info(f"✅ [CAPTCHA] Флаг captcha_passed установлен: user={message.from_user.id}, chat={chat_id_for_db}")
            
            # Теперь размучиваем пользователя для всех найденных chat_id
            # БАГ №1: Размут должен происходить ПОСЛЕ установки флага
            all_chat_ids = chat_ids_to_check if chat_ids_to_check else []
            if not all_chat_ids and chat_id:
                all_chat_ids = [chat_id]
                logger.info(f"✅ [CAPTCHA] Использован chat_id из Redis/числового ID: {chat_id}")
            elif not all_chat_ids and chat_id_for_db and chat_id_for_db != 0:
                all_chat_ids = [chat_id_for_db]
                logger.info(f"✅ [CAPTCHA] Использован chat_id_for_db: {chat_id_for_db}")
            
            # КРИТИЧНО: Логируем количество найденных chat_id
            logger.info(f"🔍 [CAPTCHA] Количество chat_id для размута: {len(all_chat_ids)}, chat_ids={all_chat_ids}")
            
            if not all_chat_ids:
                logger.error(f"❌ [CAPTCHA] КРИТИЧЕСКАЯ ОШИБКА: all_chat_ids ПУСТ! chat_ids_to_check={chat_ids_to_check}, chat_id={chat_id}, chat_id_for_db={chat_id_for_db}, group_name={group_name}")
                # Попытка последней надежды - ищем chat_id по group_name ПРЯМО СЕЙЧАС
                try:
                    from bot.database.queries import get_group_by_name
                    async with get_session() as db_session:
                        group_db = await get_group_by_name(db_session, group_name)
                        if group_db:
                            all_chat_ids = [group_db.chat_id]
                            logger.info(f"✅ [CAPTCHA] Последняя надежда: найден chat_id={group_db.chat_id} по group_name={group_name}")
                except Exception as e:
                    logger.error(f"❌ [CAPTCHA] Не удалось найти chat_id даже в последней попытке: {e}")
            
            for current_chat_id in all_chat_ids:
                try:
                    # Проверяем, находится ли пользователь в группе
                    try:
                        member = await message.bot.get_chat_member(current_chat_id, message.from_user.id)
                        is_in_group = member.status in ("member", "restricted", "administrator", "creator")
                        logger.info(f"🔍 [CAPTCHA] Проверка пользователя в группе {current_chat_id}: status={member.status}, is_in_group={is_in_group}")
                    except Exception as e:
                        is_in_group = False
                        logger.warning(f"⚠️ [CAPTCHA] Не удалось проверить статус пользователя в группе {current_chat_id}: {e}")
                    
                    # ФИКС 1: Снимаем mute ВСЕГДА после успешной капчи, независимо от статуса пользователя
                    # УБРАНА проверка is_in_group - mute должен сниматься мгновенно
                    try:
                        from aiogram.types import ChatPermissions
                        await message.bot.restrict_chat_member(
                            chat_id=current_chat_id,
                            user_id=message.from_user.id,
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_polls=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True,
                                can_invite_users=True,
                                can_pin_messages=True,
                            ),
                        )
                        logger.info(f"✅ [CAPTCHA] Mute СНЯТ для пользователя {message.from_user.id} в группе {current_chat_id} (ФИКС 1: мгновенно, без проверки статуса)")
                    except Exception as e:
                        # Если пользователь не в группе - это не критично, просто логируем
                        error_str = str(e).lower()
                        if "chat not found" in error_str or "user not found" in error_str:
                            logger.info(f"ℹ️ [CAPTCHA] Пользователь {message.from_user.id} еще не в группе {current_chat_id}, mute будет снят при входе")
                        else:
                            logger.error(f"❌ [CAPTCHA] ОШИБКА при снятии mute для {current_chat_id}: {e}")
                            # ФИКС: Используем глобальный импорт traceback из начала файла
                            logger.error(traceback.format_exc())
                    
                    # Удаляем системное сообщение капчи в группе после прохождения
                    try:
                        from bot.services.captcha_flow_logic import pop_captcha_message_id
                        captcha_msg_id = await pop_captcha_message_id(current_chat_id, message.from_user.id)
                        if captcha_msg_id:
                            try:
                                await message.bot.delete_message(chat_id=current_chat_id, message_id=captcha_msg_id)
                                logger.info(f"✅ [CAPTCHA] Системное сообщение капчи удалено из группы {current_chat_id}")
                            except Exception as e:
                                if "message to delete not found" not in str(e).lower():
                                    logger.warning(f"⚠️ Не удалось удалить системное сообщение капчи: {e}")
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка при удалении системного сообщения капчи: {e}")
                except Exception as e:
                    logger.error(f"❌ [CAPTCHA] Ошибка при обработке группы {current_chat_id}: {e}")
                    # ФИКС: Используем глобальный импорт traceback из начала файла
                    logger.error(traceback.format_exc())
            
            if chat_id:
                # Пытаемся одобрить запрос (только для join_request)
                result = await approve_chat_join_request(message.bot, chat_id, message.from_user.id)

                if result["success"]:
                    pass  # Логика уже обработана выше
            
            # Убеждаемся, что флаг автомута установлен с правильным chat_id
            for current_chat_id in all_chat_ids:
                if decision.get("should_auto_mute", False):
                    await redis.setex(f"auto_mute_scammer:{message.from_user.id}:{current_chat_id}", 3600, "1")
                    logger.info(f"🔍 [AUTO_MUTE_SET] Флаг автомута установлен для пользователя {message.from_user.id} в группе {current_chat_id}")
            
            # Получаем реальное название группы для логирования
            final_chat_id_for_log = chat_ids_to_check[0] if chat_ids_to_check else (chat_id or chat_id_for_db)
            if final_chat_id_for_log:
                try:
                    chat = await message.bot.get_chat(final_chat_id_for_log)
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
            else:
                group_display_name = group_name.replace("_", " ").title()

            # Формируем сообщение об успехе с кнопкой для входа в группу
            group_link_for_keyboard = None
            if chat_id:
                # Пытаемся одобрить запрос (только для join_request)
                result = await approve_chat_join_request(message.bot, chat_id, message.from_user.id)
                
                if result.get("success"):
                    group_link_for_keyboard = result.get("group_link")
                    logger.info(f"Одобрен запрос на вступление user=@{message.from_user.username or message.from_user.first_name or message.from_user.id} [{message.from_user.id}] group={group_name}")
                else:
                    # Ошибка approve — показываем сообщение и (если есть) ссылку
                    await message.answer(result.get("message", "Произошла ошибка при одобрении запроса."), parse_mode="HTML")
                    if result.get("group_link"):
                        group_link_for_keyboard = result.get("group_link")
            else:
                # Запрос не найден — пытаемся получить ссылку из Redis или создать
                try:
                    # ФИКС: Используем глобальный импорт из начала файла, не создаем локальную переменную
                    group_link_for_keyboard = await get_group_link_from_redis_or_create(message.bot, group_name)
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось получить ссылку на группу: {e}")
            
            # Нормализуем group_link перед передачей
            if group_link_for_keyboard:
                if isinstance(group_link_for_keyboard, bytes):
                    group_link_for_keyboard = group_link_for_keyboard.decode('utf-8')
                elif not isinstance(group_link_for_keyboard, str):
                    group_link_for_keyboard = str(group_link_for_keyboard) if group_link_for_keyboard else None
            
            # Отправляем сообщение об успехе с кнопкой
            if group_link_for_keyboard:
                try:
                    keyboard = await get_group_join_keyboard(group_link_for_keyboard, group_display_name)
                    success_msg = await message.answer(
                        f"✅ Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{group_display_name}»:",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as keyboard_error:
                    error_msg = str(keyboard_error)
                    if "400" in error_msg and "inline keyboard button" in error_msg.lower():
                        logger.error(f"❌ Ошибка 400 при создании кнопки, отправляем ссылку текстом: {keyboard_error}")
                        success_msg = await message.answer(
                            f"✅ Капча пройдена успешно! Используйте ссылку ниже, чтобы войти в «{group_display_name}»:\n🔗 {group_link_for_keyboard}",
                            parse_mode="HTML"
                        )
                    else:
                        raise keyboard_error
                # Удаляем сообщение об успехе через 2-3 минуты
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))
            else:
                # Если ссылки нет, отправляем сообщение без кнопки
                success_msg = await message.answer(
                    f"✅ Капча пройдена успешно! Вы можете войти в группу «{group_display_name}».",
                    parse_mode="HTML"
                )
                # Удаляем сообщение об успехе через 2-3 минуты
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, success_msg.message_id, 150))
            
            # Очищаем состояние капчи
            if final_chat_id_for_log:
                await clear_captcha_state(final_chat_id_for_log, message.from_user.id)
            
            logger.info(f"✅ Обработка капчи завершена для пользователя {message.from_user.id}, группа {group_name}")
            
            # Очищаем состояние FSM
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
                        # ЛОГИРУЕМ ТАЙМАУТ (превышение попыток - 3/3)
                        await log_captcha_timeout(
                            bot=message.bot,
                            user=message.from_user,
                            chat=chat_for_timeout,
                            session=session
                        )
                        
                        # ЛОГИРУЕМ ФИНАЛЬНУЮ НЕУДАЧНУЮ ПОПЫТКУ КАПЧИ (3/3)
                        await log_captcha_failed(
                            bot=message.bot,
                            user=message.from_user,
                            chat=chat_for_timeout,
                            reason="Превышено количество попыток",
                            attempt=attempts,
                            risk_score=decision.get("total_risk_score"),
                            risk_factors=decision.get("risk_factors"),
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
async def start_command(message: Message, state: FSMContext, session: AsyncSession):
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
    # БАГ №2 и №3: Проверяем, что нажимает только владелец капчи
    from bot.services.captcha_flow_logic import CAPTCHA_OWNER_KEY, CAPTCHA_MESSAGE_KEY
    
    if not callback.message:
        await callback.answer("❌ Сообщение не найдено.", show_alert=True)
        return
    
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    user_id = callback.from_user.id
    
    logger.info(f"🔍 [CAPTCHA_FALLBACK] Пользователь {user_id} нажал на кнопку капчи в сообщении {message_id} в чате {chat_id}")
    
    # ФИКС 2: Проверяем владельца капчи - только он может нажать на кнопку
    owner_key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)
    expected_owner_id = await redis.get(owner_key)
    
    if expected_owner_id:
        try:
            expected_owner_id_int = int(expected_owner_id) if isinstance(expected_owner_id, (str, bytes)) else expected_owner_id
            if user_id != expected_owner_id_int:
                logger.warning(
                    f"⚠️ [CAPTCHA_FALLBACK] ФИКС 2: Пользователь {user_id} попытался нажать на капчу, "
                    f"предназначенную для {expected_owner_id_int} в сообщении {message_id}"
                )
                await callback.answer("❌ Эта капча предназначена не вам.", show_alert=True)
                return
            logger.info(f"✅ [CAPTCHA_FALLBACK] ФИКС 2: Проверка владельца пройдена: пользователь {user_id} является владельцем капчи")
        except (ValueError, TypeError) as e:
            logger.warning(f"⚠️ [CAPTCHA_FALLBACK] Ошибка при проверке владельца капчи: {e}")
            await callback.answer("❌ Эта капча недоступна. Обратитесь к администратору.", show_alert=True)
            return
    else:
        # ФИКС 2: Если owner_key не найден - блокируем для безопасности
        logger.warning(f"⚠️ [CAPTCHA_FALLBACK] ФИКС 2: Owner key не найден - блокируем нажатие для безопасности")
        await callback.answer("❌ Эта капча недоступна. Обратитесь к администратору.", show_alert=True)
        return
    
    # Deep link уже защищен, но для callback проверяем
    await callback.answer("❌ Ссылка недоступна. Пожалуйста, попробуйте позже.", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data == "group_link_fallback")
async def handle_group_link_fallback(callback: CallbackQuery):
    """Обработчик для fallback кнопки присоединения к группе"""
    await callback.answer("❌ Ссылка на группу недоступна. Обратитесь к администратору.", show_alert=True)


@visual_captcha_handler_router.chat_member()
async def handle_member_status_change(event: ChatMemberUpdated, session: AsyncSession):
    """Обработка изменения статуса участника группы.

    Обрабатывает два критичных сценария:
    1. Выход из группы (MEMBER/RESTRICTED -> LEFT/KICKED): очищает флаг captcha_passed
    2. Вступление в группу (LEFT/KICKED -> MEMBER): запускает капчу

    ВАЖНО: Эти сценарии обрабатываются в одном хендлере, чтобы гарантировать:
    - При выходе флаг captcha_passed всегда удаляется
    - При повторном вступлении капча всегда запрашивается
    - Нет конфликтов между несколькими обработчиками chat_member
    """
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
    except AttributeError:
        logger.warning("⚠️ [CHAT_MEMBER] AttributeError при получении статусов - пропускаем событие")
        return

    chat = event.chat
    user = event.new_chat_member.user

    # КРИТИЧЕСКОЕ ДИАГНОСТИЧЕСКОЕ ЛОГИРОВАНИЕ
    logger.info(
        f"🔍 [CHAT_MEMBER_HANDLER] ВЫЗВАН! user={user.id}, chat={chat.id}, "
        f"old_status={old_status} (type={type(old_status)}), "
        f"new_status={new_status} (type={type(new_status)})"
    )

    # ============================================================
    # СЦЕНАРИЙ 1: ВЫХОД ИЗ ГРУППЫ - Очищаем флаг captcha_passed
    # ============================================================
    # Проверяем как строки, так и enum значения для совместимости
    is_leaving = (
        str(new_status) in {"left", "kicked"} or
        new_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}
    )
    if is_leaving:
        key = f"captcha_passed:{user.id}:{chat.id}"
        try:
            # Проверяем TTL перед удалением для более подробного логирования
            ttl = await redis.ttl(key)
            deleted = await redis.delete(key)

            if deleted:
                logger.info(
                    f"✅ [CAPTCHA_LEAVE] Пользователь {user.id} покинул группу {chat.id}, "
                    f"флаг captcha_passed удалён (TTL был: {ttl}s, переход: {old_status} → {new_status})"
                )
            else:
                logger.debug(
                    f"🔍 [CAPTCHA_LEAVE] Пользователь {user.id} покинул группу {chat.id}, "
                    f"флаг captcha_passed отсутствовал (переход: {old_status} → {new_status})"
                )
        except Exception as exc:
            logger.warning(
                f"⚠️ [CAPTCHA_LEAVE] Не удалось удалить флаг captcha_passed для user={user.id}, "
                f"chat={chat.id}: {exc}"
            )

        # Для выхода из группы больше ничего не делаем
        return

    # ============================================================
    # СЦЕНАРИЙ 2: ВСТУПЛЕНИЕ В ГРУППУ - Запускаем капчу
    # ============================================================
    # Проверяем как строки, так и enum значения для совместимости
    was_not_member = (
        str(old_status) in {"left", "kicked"} or
        old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}
    )
    is_now_member = (
        str(new_status) == "member" or
        new_status == ChatMemberStatus.MEMBER
    )
    if not was_not_member or not is_now_member:
        # Это не вступление (может быть изменение прав администратора и т.д.)
        return

    # КРИТИЧНО: На момент вступления флаг captcha_passed должен быть удалён (если был выход ранее)
    # Если флаг всё ещё существует, это означает:
    # 1. Пользователь вступил впервые (флага не было)
    # 2. Пользователь вступил в течение 1 часа после прохождения капчи БЕЗ выхода
    # 3. БАГ: флаг не был удалён при выходе

    logger.info(
        f"👤 [MEMBER_JOIN] Пользователь {user.id} вступил в группу {chat.id} "
        f"(переход: {old_status} → {new_status})"
    )

    # РАНЕЕ здесь была попытка защиты от дублированных событий chat_member_updated
    # через хранение event_signature в Redis. Но у ChatMemberUpdated нет update_id,
    # поэтому разные реальные вступления пользователя (после выхода и повторного join)
    # получали одинаковую сигнатуру и второе вступление ошибочно игнорировалось.
    #
    # Это приводило к критичному багу безопасности: пользователь мог выйти из группы
    # и снова войти без повторной капчи, если делал это в пределах TTL ключа.
    #
    # Поэтому анти-дубликатная логика здесь отключена, чтобы каждое реальное
    # событие LEFT/KICKED -> MEMBER обрабатывалось полноценно.

    initiator = event.from_user if event.from_user and event.from_user.id != user.id else None

    # ФИКС №1 и №4: Явно разделяем три сценария: join_request, invite, self-join
    from bot.services.event_classifier import classify_join_event, JoinEventType

    event_type = classify_join_event(
        event=event,
        user_id=user.id,
        initiator_id=initiator.id if initiator else None,
    )

    logger.info(f"🔍 [MEMBER_JOIN] Классификация события: user={user.id}, type={event_type.value}")

    try:
        # ПРОВЕРКА БЕЗОПАСНОСТИ: Проверяем наличие флага captcha_passed
        # ВАЖНО: Флаг больше НЕ используется для пропуска капчи (это старая уязвимость)
        # Он используется только для логики мута/одобрения в других обработчиках
        # КРИТИЧНО: При rejoin (LEFT/KICKED → MEMBER) флаг ДОЛЖЕН быть удалён
        # Если флаг существует - это БАГ, но мы всё равно требуем капчу если она включена
        captcha_passed_key = f"captcha_passed:{user.id}:{chat.id}"
        captcha_passed = await redis.get(captcha_passed_key)
        captcha_ttl = await redis.ttl(captcha_passed_key) if captcha_passed else -2

        # КРИТИЧНО: Если флаг существует при rejoin - это ошибка, удаляем его
        # Пользователь покинул группу, флаг должен был быть удалён
        if captcha_passed:
            logger.warning(
                f"⚠️ [MEMBER_JOIN] БАГ: Флаг captcha_passed существует при rejoin для user={user.id}, "
                f"chat={chat.id}, TTL={captcha_ttl}s. Удаляем флаг для безопасности."
            )
            await redis.delete(captcha_passed_key)
            captcha_passed = None
            captcha_ttl = -2

        logger.info(
            f"🔒 [MEMBER_JOIN] Проверка флага captcha_passed для user={user.id}, chat={chat.id}: "
            f"value={captcha_passed}, TTL={captcha_ttl}s "
            f"(флаг НЕ используется для пропуска капчи, только для логики мута)"
        )

        if event_type == JoinEventType.INVITE:
            # ФИКС №1: Антифлуд срабатывает только для настоящих инвайтов
            # Это действительно invite от другого пользователя
            decision = await prepare_invite_flow(
                bot=event.bot,
                session=session,
                chat=chat,
                initiator=initiator,
            )
            source = "invite"
        elif event_type == JoinEventType.SELF_JOIN:
            # self-join (пользователь сам вступил) - антифлуд не работает
            decision = await prepare_manual_approval_flow(session=session, chat_id=chat.id)
            source = "manual"
        else:
            # OTHER - fallback
            decision = await prepare_manual_approval_flow(session=session, chat_id=chat.id)
            source = "manual"

        settings_snapshot = await load_captcha_settings(session, chat.id)
        
        # КРИТИЧЕСКИЙ ФИКС: Проверяем ОБА настройки капчи для rejoin
        # 1. ChatSettings.captcha_join_enabled (используется в decision)
        # 2. CaptchaSettings.is_visual_enabled (используется в handle_join_request)
        # Если ЛЮБАЯ из них включена - требуем капчу при rejoin
        # ВАЖНО: visual_captcha_enabled имеет ПРИОРИТЕТ - если включено, капча ОБЯЗАТЕЛЬНА
        
        # КРИТИЧНО: При rejoin ВСЕГДА проверяем БД напрямую для гарантии актуальности
        # Redis кэш может быть устаревшим, поэтому проверяем БД напрямую
        # ВАЖНО: При rejoin мы ДОЛЖНЫ проверить БД напрямую, так как Redis может быть устаревшим
        from bot.database.models import CaptchaSettings
        from sqlalchemy import select
        
        # СНАЧАЛА проверяем БД напрямую (источник истины)
        try:
            result = await session.execute(
                select(CaptchaSettings).where(CaptchaSettings.group_id == chat.id)
            )
            db_settings = result.scalar_one_or_none()
            db_visual_enabled = db_settings.is_visual_enabled if db_settings else False
        except Exception as db_error:
            logger.error(
                f"❌ [MEMBER_JOIN] Ошибка при проверке БД для chat={chat.id}: {db_error}. "
                f"Используем значение из Redis."
            )
            # Fallback на Redis если БД недоступна
            db_visual_enabled = await get_visual_captcha_status(chat.id)
        
        # Затем проверяем Redis для сравнения
        redis_visual_enabled = await get_visual_captcha_status(chat.id)
        
        logger.info(
            f"🔍 [MEMBER_JOIN] Проверка visual_captcha_enabled: БД={db_visual_enabled}, Redis={redis_visual_enabled} для chat={chat.id}"
        )
        
        # Используем значение из БД (источник истины), но обновляем Redis если не совпадает
        visual_captcha_enabled = db_visual_enabled
        
        if db_visual_enabled != redis_visual_enabled:
            # Несоответствие - обновляем Redis
            await redis.set(f"visual_captcha_enabled:{chat.id}", "1" if db_visual_enabled else "0")
            logger.warning(
                f"⚠️ [MEMBER_JOIN] КРИТИЧНО: Redis и БД не совпадают для chat={chat.id}. "
                f"БД: {db_visual_enabled}, Redis был: {redis_visual_enabled}. Обновлен Redis. "
                f"Используем значение из БД: {db_visual_enabled}"
            )
        
        # КРИТИЧНО: Если visual_captcha_enabled=True, капча ОБЯЗАТЕЛЬНА независимо от fallback_mode
        # Это гарантирует, что капча всегда отправляется при rejoin, если включена через UI
        if visual_captcha_enabled:
            captcha_should_be_required = True
            # Игнорируем fallback_mode если visual_captcha явно включен
            ignore_fallback = True
            logger.info(
                f"🔒 [MEMBER_JOIN] visual_captcha_enabled=True → капча ОБЯЗАТЕЛЬНА для user={user.id}, "
                f"chat={chat.id} (игнорируем fallback_mode)"
            )
        else:
            # Если visual_captcha выключен, используем decision
            captcha_should_be_required = decision.require_captcha
            ignore_fallback = False
        
        # Определяем источник требования капчи для лучшего логирования
        captcha_source = "unknown"
        if visual_captcha_enabled:
            captcha_source = "visual_captcha_enabled (UI)"
        elif decision.require_captcha:
            captcha_source = "captcha_join_enabled (ChatSettings)"
        else:
            captcha_source = "none"
        
        logger.info(
            f"🔍 [MEMBER_JOIN] Проверка капчи: decision.require_captcha={decision.require_captcha}, "
            f"visual_captcha_enabled={visual_captcha_enabled}, "
            f"decision.fallback_mode={decision.fallback_mode}, "
            f"captcha_should_be_required={captcha_should_be_required}, "
            f"ignore_fallback={ignore_fallback}, "
            f"captcha_source={captcha_source}"
        )

        # КРИТИЧНО: Отправляем капчу если:
        # 1. captcha_should_be_required=True И
        # 2. (ignore_fallback=True ИЛИ decision.fallback_mode=False)
        should_send_captcha = (
            captcha_should_be_required and 
            (ignore_fallback or not decision.fallback_mode)
        )
        
        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для отладки проблемы rejoin
        logger.info(
            f"🔍 [MEMBER_JOIN] ФИНАЛЬНАЯ ПРОВЕРКА: should_send_captcha={should_send_captcha}, "
            f"captcha_should_be_required={captcha_should_be_required}, "
            f"ignore_fallback={ignore_fallback}, "
            f"decision.fallback_mode={decision.fallback_mode}, "
            f"visual_captcha_enabled={visual_captcha_enabled}, "
            f"decision.require_captcha={decision.require_captcha}"
        )
        
        if should_send_captcha:
            logger.info(
                f"🎯 [MEMBER_JOIN] Капча требуется для user={user.id}, chat={chat.id}, source={source}, "
                f"visual_captcha_enabled={visual_captcha_enabled}, captcha_source={captcha_source}"
            )

            # КРИТИЧНО: Отправляем капчу с обработкой ошибок
            # Если отправка не удалась, всё равно ограничиваем пользователя
            captcha_sent = False
            try:
                await send_captcha_prompt(
                    bot=event.bot,
                    chat=chat,
                    user=user,
                    settings=settings_snapshot,
                    source=source,
                    initiator=initiator,
                )
                captcha_sent = True
                logger.info(
                    f"✅ [MEMBER_JOIN] Капча успешно отправлена для user={user.id}, chat={chat.id}"
                )
            except Exception as captcha_error:
                logger.error(
                    f"❌ [MEMBER_JOIN] КРИТИЧЕСКАЯ ОШИБКА: Не удалось отправить капчу для user={user.id}, "
                    f"chat={chat.id}: {captcha_error}. Продолжаем с ограничением пользователя."
                )
                # Продолжаем выполнение - ограничим пользователя даже если капча не отправлена

            try:
                await event.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=build_restriction_permissions(),
                    until_date=datetime.now(timezone.utc) + timedelta(seconds=settings_snapshot.timeout_seconds),
                )
                logger.info(
                    f"🔇 [MEMBER_JOIN] Пользователь {user.id} ограничен до прохождения капчи "
                    f"(timeout: {settings_snapshot.timeout_seconds}s, captcha_sent={captcha_sent})"
                )
            except Exception as exc:
                logger.error(
                    f"❌ [MEMBER_JOIN] Не удалось ограничить пользователя {user.id} до прохождения капчи: {exc}"
                )
            return
        else:
            # Капча НЕ требуется - логируем почему
            logger.warning(
                f"⚠️ [MEMBER_JOIN] Капча НЕ будет отправлена для user={user.id}, chat={chat.id}, "
                f"source={source}, visual_captcha_enabled={visual_captcha_enabled}, "
                f"decision.require_captcha={decision.require_captcha}, "
                f"captcha_should_be_required={captcha_should_be_required}, "
                f"ignore_fallback={ignore_fallback}, decision.fallback_mode={decision.fallback_mode}, "
                f"captcha_source={captcha_source}"
            )

        admission = await evaluate_admission(
            bot=event.bot,
            session=session,
            chat=chat,
            user=user,
            source=source,
        )

        if admission.muted:
            logger.info(
                "Пользователь %s замьючен при вступлении (%s)",
                user.id,
                admission.reason,
            )

            if admission.reason in {"risk_gate", "spammer_registry"}:
                await mute_suspicious_user_across_groups(
                    bot=event.bot,
                    session=session,
                    target_id=user.id,
                    admin_id=getattr(initiator, "id", None),
                    duration=None,
                    reason=admission.reason,
                )

        await clear_captcha_state(chat.id, user.id)

        try:
            await log_new_member(
                bot=event.bot,
                user=user,
                chat=chat,
                invited_by=initiator,
                session=session,
            )
        except Exception as log_error:
            logger.error("Ошибка при логировании нового участника: %s", log_error)

    except Exception as exc:
        logger.error("Ошибка обработки вступления: %s", exc)
        logger.error(traceback.format_exc())
