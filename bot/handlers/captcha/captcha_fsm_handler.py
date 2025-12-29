# bot/handlers/captcha/captcha_fsm_handler.py
"""
FSM хендлер для ручного ввода ответа на капчу.

Отвечает за:
- Обработку текстовых сообщений в состоянии waiting_for_answer
- Проверку введённого ответа
- Одобрение/отклонение join request

Перенесено из visual_captcha_handler.py
"""

import asyncio
import logging
from typing import Optional

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.filters import CommandStart, BaseFilter

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.session import get_session
from bot.services.captcha.dm_flow_service import (
    get_captcha_data,
    update_captcha_attempts,
    delete_captcha_data,
    save_captcha_message_id,
    get_captcha_message_ids,
    delete_captcha_message_ids,
    clear_captcha_state,
    get_group_link,
    generate_visual_captcha,
    save_captcha_data,
    save_join_request,
    delete_join_request,
    create_captcha_deep_link,
)
from bot.handlers.captcha.captcha_messages import (
    CAPTCHA_DM_TITLE,
    send_success_message,
    send_failure_message,
    send_wrong_answer_message,
    format_captcha_instruction,
)
from bot.handlers.captcha.captcha_keyboards import build_captcha_verify_keyboard


# Логгер для отслеживания FSM
logger = logging.getLogger(__name__)

# Роутер для FSM хендлеров
fsm_router = Router(name="captcha_fsm")


# ═══════════════════════════════════════════════════════════════════════════════
# FSM СОСТОЯНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

class CaptchaStates(StatesGroup):
    """
    Состояния FSM для прохождения капчи.

    waiting_for_answer - ожидаем ввод ответа от пользователя.
    Данные в FSM storage:
    - chat_id: ID группы
    - correct_answer: Правильный ответ
    - group_id: Идентификатор группы (username или private_{id})
    - attempts_left: Оставшиеся попытки
    """
    # Состояние ожидания ответа на капчу
    waiting_for_answer = State()


class NoFSMStateFilter(BaseFilter):
    """
    Фильтр который матчит только если у пользователя НЕТ активного FSM состояния.

    Нужен для handle_captcha_text_input_redis чтобы не перехватывать числа
    когда пользователь находится в другом FSM (например, ввод порогов).

    ВАЖНО: Наследуется от BaseFilter для корректной работы в aiogram 3.x
    """

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        """Возвращает True только если FSM состояние не установлено."""
        current_state = await state.get_state()
        if current_state is None:
            return True
        # Разрешаем только для состояния капчи
        if current_state == CaptchaStates.waiting_for_answer.state:
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════════

async def _delete_message_later(bot: Bot, message: Message, delay: int) -> None:
    """
    Удаляет сообщение через указанное время.

    Args:
        bot: Экземпляр бота
        message: Сообщение для удаления
        delay: Задержка в секундах
    """
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
        logger.debug(f"🗑️ [AUTO_DELETE] Удалено сообщение: msg_id={message.message_id}")
    except Exception as e:
        logger.debug(f"⚠️ [AUTO_DELETE] Не удалось удалить сообщение: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК DEEP LINK
# ═══════════════════════════════════════════════════════════════════════════════

@fsm_router.message(CommandStart(deep_link=True))
async def handle_captcha_deep_link(
    message: Message,
    bot: Bot,
    state: FSMContext,
) -> None:
    """
    Обработка /start с deep_link вида captcha_{owner_id}_{chat_id}.

    ВАЖНО: Проверяет что message.from_user.id == owner_id из deep link!
    Это защищает от того, чтобы чужой пользователь проходил чужую капчу.

    Генерирует капчу и отправляет пользователю.

    Args:
        message: Входящее сообщение /start
        bot: Экземпляр бота
        state: FSM контекст
    """
    # Получаем user_id для логирования
    user_id = message.from_user.id

    try:
        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 1: Извлекаем параметры deep link
        # Формат: captcha_{owner_id}_{chat_id}
        # ═══════════════════════════════════════════════════════════════════════

        # Парсим текст команды для получения payload
        parts = message.text.split()
        # Если есть второй элемент - это payload
        deep_link_payload = parts[1] if len(parts) > 1 else None

        # Логируем входящий deep link
        logger.info(
            f"📥 [FSM] Deep link: user_id={user_id}, payload={deep_link_payload}"
        )

        # Проверяем формат payload - новый формат captcha_{owner_id}_{chat_id}
        if not deep_link_payload or not deep_link_payload.startswith("captcha_"):
            # Неверный формат - отправляем сообщение об ошибке
            await message.answer(
                "❌ Неверная ссылка.\n\n"
                "Пожалуйста, используйте ссылку из группы для прохождения капчи."
            )
            return

        # Извлекаем owner_id и chat_id из payload
        # Формат: captcha_{owner_id}_{chat_id}
        payload_parts = deep_link_payload.replace("captcha_", "").split("_")

        if len(payload_parts) != 2:
            error_msg = await message.answer(
                "❌ Неверный формат ссылки.\n\n"
                "Пожалуйста, используйте актуальную ссылку из группы."
            )
            asyncio.create_task(_delete_message_later(bot, error_msg, 30))
            return

        try:
            owner_id = int(payload_parts[0])
            chat_id = int(payload_parts[1])
        except ValueError:
            error_msg = await message.answer("❌ Неверный формат ссылки.")
            asyncio.create_task(_delete_message_later(bot, error_msg, 30))
            return

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 2: Проверяем что это владелец капчи
        # КРИТИЧНО: защита от прохождения чужой капчи!
        # ═══════════════════════════════════════════════════════════════════════
        if user_id != owner_id:
            logger.warning(
                f"⚠️ [FSM] Попытка пройти чужую капчу! "
                f"from_user={user_id}, owner={owner_id}, chat_id={chat_id}"
            )
            # Отправляем сообщение об ошибке и планируем его удаление
            error_msg = await message.answer(
                "❌ Эта капча предназначена для другого пользователя.\n\n"
                "Используйте свою ссылку из группы."
            )
            # Удаляем сообщение через 30 секунд
            asyncio.create_task(_delete_message_later(bot, error_msg, 30))
            return

        # group_id для совместимости с Redis
        group_id = f"private_{chat_id}"
        chat_username = None

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 2.5: Получаем реальное название группы
        # ═══════════════════════════════════════════════════════════════════════
        try:
            chat_info = await bot.get_chat(chat_id)
            group_title = chat_info.title or f"группу {chat_id}"
            # Если есть username - сохраняем для ссылки
            if chat_info.username:
                chat_username = chat_info.username
        except Exception as e:
            logger.warning(f"⚠️ [FSM] Не удалось получить название группы: {e}")
            group_title = f"группу {chat_id}"

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 3: Получаем настройки капчи для группы
        # chat_id теперь всегда известен благодаря новому формату deep link
        # ═══════════════════════════════════════════════════════════════════════

        async with get_session() as session:
            from bot.services.captcha.settings_service import get_captcha_settings
            settings = await get_captcha_settings(session, chat_id)

        # Логируем загруженные настройки для отладки
        logger.info(
            f"⚙️ [FSM] Настройки загружены: chat_id={chat_id}, "
            f"button_count={settings.button_count}, "
            f"max_attempts={settings.max_attempts}, "
            f"dialog_cleanup={settings.dialog_cleanup_seconds}, "
            f"reminder_sec={settings.reminder_seconds}, "
            f"reminder_count={settings.reminder_count}"
        )

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 3.5: Получаем режим капчи из существующих данных Redis
        # ВАЖНО: Нужно сохранить режим ДО генерации новой капчи!
        # ═══════════════════════════════════════════════════════════════════════
        from bot.services.captcha.cleanup_service import get_captcha_data as get_redis_captcha_data

        original_mode = "visual_dm"  # По умолчанию
        existing_data = await get_redis_captcha_data(user_id, chat_id)
        if existing_data and existing_data.get("mode"):
            original_mode = existing_data["mode"]
            logger.debug(f"📋 [FSM] Оригинальный режим: {original_mode}")

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 4: Очищаем предыдущие сообщения капчи
        # Включая deep link invitation которое было сохранено в Redis
        # ═══════════════════════════════════════════════════════════════════════

        # Получаем ID предыдущих сообщений из FSM
        fsm_data = await state.get_data()
        prev_message_ids = fsm_data.get("message_ids", [])

        # Также получаем ID сообщений из Redis (deep link invitation)
        redis_message_ids = await get_captcha_message_ids(user_id)

        # Объединяем все ID для удаления
        all_message_ids = set(prev_message_ids) | set(redis_message_ids)

        # Логируем для отладки
        logger.debug(
            f"🧹 [FSM] Очистка сообщений: user_id={user_id}, "
            f"fsm_ids={prev_message_ids}, redis_ids={redis_message_ids}"
        )

        # Удаляем предыдущие сообщения
        deleted_count = 0
        for msg_id in all_message_ids:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
                deleted_count += 1
                logger.debug(f"🗑️ [FSM] Удалено сообщение: msg_id={msg_id}")
            except Exception as e:
                # Сообщение уже удалено - пропускаем
                logger.debug(f"⚠️ [FSM] Не удалось удалить сообщение {msg_id}: {e}")

        if deleted_count > 0:
            logger.info(f"🧹 [FSM] Удалено {deleted_count} предыдущих сообщений")

        # Очищаем список сообщений в Redis
        await delete_captcha_message_ids(user_id)

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 5: Генерируем капчу
        # ═══════════════════════════════════════════════════════════════════════

        # Генерируем капчу с количеством кнопок из настроек
        correct_answer, captcha_image, options = await generate_visual_captcha(
            button_count=settings.button_count,
        )

        # Логируем генерацию (без ответа!)
        logger.info(
            f"🎨 [FSM] Капча сгенерирована: user_id={user_id}, "
            f"buttons={settings.button_count}"
        )

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 6: Сохраняем данные капчи
        # ═══════════════════════════════════════════════════════════════════════

        # Сохраняем в FSM
        await state.update_data(
            # Правильный ответ для проверки
            correct_answer=correct_answer,
            # Идентификатор группы
            group_id=group_id,
            # Числовой ID группы (если известен)
            chat_id=chat_id,
            # Название группы для отображения пользователю
            group_title=group_title,
            # Оставшиеся попытки из настроек
            attempts_left=settings.max_attempts,
            # Список ID сообщений для последующего удаления
            message_ids=[],
            # Хэши опций для проверки callback
            options=options,
        )

        # Сохраняем в Redis для персистентности
        # chat_id всегда известен благодаря новому формату deep link
        # ВАЖНО: передаём options чтобы correct_hash соответствовал кнопкам!
        # ВАЖНО: сохраняем original_mode чтобы не потерять режим join_group/invite_group!
        await save_captcha_data(
            user_id=user_id,
            correct_answer=correct_answer,
            group_id=group_id,
            chat_id=chat_id,
            attempts_left=settings.max_attempts,
            options=options,
            mode=original_mode,
        )

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 7: Отправляем капчу
        # ═══════════════════════════════════════════════════════════════════════

        # Формируем текст с инструкцией
        # ВАЖНО: Время и попытки берутся из "настроек диалогов" (dialog_cleanup_seconds, max_attempts)
        # dialog_cleanup_seconds = таймаут капчи (сколько времени на решение)
        instruction = format_captcha_instruction(
            timeout=settings.dialog_cleanup_seconds,
            attempts=settings.max_attempts,
            manual_input_enabled=settings.manual_input_enabled,
        )

        # Создаём клавиатуру с кнопками (2 в ряд)
        # chat_id всегда известен благодаря новому формату deep link
        keyboard = build_captcha_verify_keyboard(
            owner_id=user_id,
            chat_id=chat_id,
            options=options,
            buttons_per_row=2,
        )

        # Отправляем изображение капчи
        captcha_msg = await message.answer_photo(
            photo=captcha_image,
            caption=instruction,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        # Сохраняем ID сообщения
        message_ids = [captcha_msg.message_id]
        await state.update_data(message_ids=message_ids)

        # Сохраняем ID в Redis для чистки
        await save_captcha_message_id(user_id, captcha_msg.message_id)

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 8: Устанавливаем FSM состояние
        # ═══════════════════════════════════════════════════════════════════════

        # Переводим в состояние ожидания ответа
        await state.set_state(CaptchaStates.waiting_for_answer)

        # Логируем успех
        logger.info(
            f"✅ [FSM] Капча отправлена: user_id={user_id}, group={group_id}"
        )

        # ═══════════════════════════════════════════════════════════════════════
        # ШАГ 9: Планируем напоминание и таймаут
        # ═══════════════════════════════════════════════════════════════════════

        # Импортируем сервисы для планирования
        from bot.services.captcha.reminder_service import (
            schedule_reminder,
            schedule_timeout,
            mark_captcha_active,
        )

        # Таймаут капчи = время чистки диалога
        # Капча висит до момента чистки, после чего удаляется и join request отклоняется
        # Приоритет: visual_captcha_timeout → dialog_cleanup_seconds
        timeout_seconds = settings.visual_captcha_timeout or settings.dialog_cleanup_seconds

        # Отмечаем капчу как активную в Redis (нужно для работы напоминаний)
        if chat_id:
            await mark_captcha_active(user_id, chat_id)

        # ПРИМЕЧАНИЕ: Напоминания и таймаут уже запланированы в flow_service.py
        # при отправке deep link invite. Здесь НЕ планируем повторно,
        # чтобы избежать дублирования.
        #
        # VISUAL_DM_TIMEOUT (flow_service.py) обрабатывает:
        # - Таймаут (decline/keep в зависимости от настроек)
        # - Отправку сообщения о провале
        # - Планирование чистки диалога

    except Exception as e:
        # Логируем ошибку
        logger.error(
            f"❌ [FSM] Ошибка обработки deep link: user_id={user_id}, error={e}"
        )

        # Отправляем сообщение об ошибке пользователю
        try:
            await message.answer(
                "❌ Произошла ошибка при обработке запроса.\n"
                "Пожалуйста, попробуйте позже."
            )
        except Exception:
            pass

        # Очищаем FSM
        await state.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК ТЕКСТОВОГО ВВОДА
# ═══════════════════════════════════════════════════════════════════════════════

@fsm_router.message(CaptchaStates.waiting_for_answer, F.text)
async def handle_captcha_text_answer(
    message: Message,
    bot: Bot,
    state: FSMContext,
) -> None:
    """
    Обработка текстового ввода ответа на капчу.

    Проверяет введённый текст и одобряет/отклоняет запрос.

    Args:
        message: Сообщение с ответом
        bot: Экземпляр бота
        state: FSM контекст
    """
    # Получаем user_id
    user_id = message.from_user.id

    # Получаем введённый текст (очищаем от пробелов)
    user_answer = (message.text or "").strip()

    # Логируем попытку
    logger.info(
        f"📝 [FSM] Текстовый ввод: user_id={user_id}, answer={user_answer}"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 1: Получаем данные капчи из FSM
    # ═══════════════════════════════════════════════════════════════════════════

    fsm_data = await state.get_data()
    correct_answer = fsm_data.get("correct_answer")
    group_id = fsm_data.get("group_id")
    chat_id = fsm_data.get("chat_id")
    group_title = fsm_data.get("group_title")  # Название группы
    attempts_left = fsm_data.get("attempts_left", 0)
    message_ids = fsm_data.get("message_ids", [])

    # Добавляем текущее сообщение в список на удаление
    message_ids.append(message.message_id)
    await state.update_data(message_ids=message_ids)

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 2: Проверяем наличие данных капчи
    # ═══════════════════════════════════════════════════════════════════════════

    if not correct_answer or not group_id:
        # Данные капчи не найдены - возможно сессия истекла
        # Пробуем получить из Redis (нужен chat_id для ключа)
        if chat_id:
            redis_data = await get_captcha_data(user_id, chat_id)
        else:
            # Без chat_id не можем получить данные из Redis
            redis_data = None

        if redis_data:
            # Восстанавливаем данные из Redis
            correct_answer = redis_data.get("correct_answer")
            group_id = redis_data.get("group_id")
            chat_id = redis_data.get("chat_id")
            attempts_left = redis_data.get("attempts_left", 0)
        else:
            # Сессия истекла - сообщаем пользователю
            expired_msg = await message.answer(
                "⏰ Время сессии истекло.\n\n"
                "Пожалуйста, начните процесс заново."
            )
            message_ids.append(expired_msg.message_id)

            # Очищаем состояние
            await state.clear()
            return

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 3: Проверяем количество попыток
    # ═══════════════════════════════════════════════════════════════════════════

    if attempts_left <= 0:
        # Попытки закончились
        await send_failure_message(bot, user_id, reason="no_attempts")

        # Очищаем состояние
        if chat_id:
            await clear_captcha_state(bot, user_id, chat_id, state)
        else:
            await state.clear()
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 4: Отмечаем что пользователь начал решать (останавливает напоминания)
    # ═══════════════════════════════════════════════════════════════════════════
    if chat_id:
        from bot.services.captcha.reminder_service import mark_user_interacted
        await mark_user_interacted(user_id, chat_id)

    # ═══════════════════════════════════════════════════════════════════════════
    # ШАГ 5: Проверяем ответ
    # ═══════════════════════════════════════════════════════════════════════════

    # Сравниваем ответы (без учёта регистра)
    is_correct = user_answer.lower() == correct_answer.lower()

    if is_correct:
        # ═══════════════════════════════════════════════════════════════════════
        # УСПЕХ! Капча пройдена
        # ═══════════════════════════════════════════════════════════════════════

        logger.info(
            f"✅ [FSM] Капча пройдена: user_id={user_id}, group={group_id}"
        )

        # Получаем режим капчи из сохранённых данных
        from bot.services.captcha.cleanup_service import get_captcha_data as get_redis_captcha_data
        from bot.services.captcha.settings_service import CaptchaMode
        from bot.services.captcha.flow_service import process_captcha_success

        captcha_mode = CaptchaMode.VISUAL_DM  # По умолчанию
        if chat_id:
            redis_data = await get_redis_captcha_data(user_id, chat_id)
            if redis_data and redis_data.get("mode"):
                try:
                    captcha_mode = CaptchaMode(redis_data["mode"])
                except ValueError:
                    pass

        # Используем process_captcha_success для корректной обработки:
        # - Отменяет напоминания
        # - Проверяет ограничения перед снятием мута
        # - Очищает капчу
        # - Отправляет сообщение успеха
        async with get_session() as session:
            await process_captcha_success(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user_id=user_id,
                mode=captcha_mode,
            )

        # Очищаем FSM состояние
        await state.clear()

    else:
        # ═══════════════════════════════════════════════════════════════════════
        # НЕВЕРНЫЙ ОТВЕТ
        # ═══════════════════════════════════════════════════════════════════════

        # Уменьшаем количество попыток
        attempts_left -= 1

        # Обновляем FSM
        await state.update_data(attempts_left=attempts_left)

        # Обновляем Redis (нужен chat_id для ключа)
        if chat_id:
            await update_captcha_attempts(user_id, chat_id, attempts_left)

        # Логируем
        logger.info(
            f"❌ [FSM] Неверный ответ: user_id={user_id}, "
            f"attempts_left={attempts_left}"
        )

        if attempts_left > 0:
            # Есть ещё попытки - сообщаем
            wrong_msg = await send_wrong_answer_message(
                bot=bot,
                user_id=user_id,
                attempts_left=attempts_left,
            )

            if wrong_msg:
                message_ids.append(wrong_msg.message_id)
                await state.update_data(message_ids=message_ids)
        else:
            # Попытки закончились
            await send_failure_message(bot, user_id, reason="no_attempts")

            # Получаем режим капчи из сохранённых данных
            from bot.services.captcha.cleanup_service import get_captcha_data as get_redis_captcha_data
            from bot.services.captcha.settings_service import CaptchaMode

            captcha_mode = CaptchaMode.VISUAL_DM  # По умолчанию
            if chat_id:
                redis_data = await get_redis_captcha_data(user_id, chat_id)
                if redis_data and redis_data.get("mode"):
                    try:
                        captcha_mode = CaptchaMode(redis_data["mode"])
                    except ValueError:
                        pass

            # Обрабатываем провал в зависимости от режима
            if captcha_mode == CaptchaMode.VISUAL_DM:
                # Для VISUAL_DM - отклоняем join request
                if chat_id:
                    try:
                        await bot.decline_chat_join_request(
                            chat_id=chat_id,
                            user_id=user_id,
                        )
                        logger.info(
                            f"🚫 [FSM] Join request отклонён: "
                            f"user_id={user_id}, chat_id={chat_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ [FSM] Не удалось отклонить join request: {e}"
                        )
            else:
                # Для JOIN_GROUP/INVITE_GROUP - оставляем в муте (не кикаем!)
                logger.info(
                    f"🔇 [FSM] Мут сохранён (провал капчи): "
                    f"user_id={user_id}, chat_id={chat_id}"
                )

            # Очищаем состояние
            if chat_id:
                await clear_captcha_state(bot, user_id, chat_id, state)
            else:
                await state.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК ТЕКСТОВОГО ВВОДА БЕЗ FSM (через Redis)
# ═══════════════════════════════════════════════════════════════════════════════

@fsm_router.message(F.chat.type == "private", F.text.regexp(r"^\d+$"), NoFSMStateFilter())
async def handle_captcha_text_input_redis(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обработка текстового ввода числа в ЛС - проверяет капчу через Redis.

    Этот handler ловит числа в ЛС бота и проверяет есть ли активная капча.
    Работает БЕЗ FSM состояния - использует только Redis.

    ВАЖНО: NoFSMStateFilter() гарантирует что этот handler НЕ будет
    перехватывать числа когда пользователь находится в другом FSM состоянии
    (например, ввод порогов баллов в настройках).

    Args:
        message: Сообщение с числом
        bot: Экземпляр бота
        session: Сессия БД
        state: FSM контекст для фильтра
    """
    user_id = message.from_user.id
    user_answer = message.text.strip()

    # Импортируем функции для работы с Redis капчей
    from bot.services.captcha.cleanup_service import get_captcha_data, CAPTCHA_DATA_KEY
    from bot.services.redis_conn import redis

    # Ищем активную капчу для пользователя
    # Формат ключа: captcha:data:{user_id}:{chat_id}
    # Но мы не знаем chat_id, поэтому ищем по паттерну
    pattern = f"captcha:data:{user_id}:*"
    keys = await redis.keys(pattern)

    if not keys:
        # Нет активной капчи - игнорируем сообщение
        # Не отвечаем чтобы не спамить
        return

    # Берём первый найденный ключ
    key = keys[0]

    # Парсим chat_id из ключа
    # Формат: captcha:data:{user_id}:{chat_id} - 4 части
    parts = key.split(":")
    if len(parts) < 4:
        return

    try:
        chat_id = int(parts[3])  # chat_id это 4-я часть (индекс 3)
    except ValueError:
        return

    # Получаем данные капчи
    captcha_data = await get_captcha_data(user_id, chat_id)
    if not captcha_data:
        return

    correct_answer = captcha_data.get("correct_answer")
    mode_str = captcha_data.get("mode", "visual_dm")

    if not correct_answer:
        return

    # Логируем попытку
    logger.info(
        f"📝 [REDIS_INPUT] Текстовый ввод: user_id={user_id}, "
        f"answer={user_answer}, chat_id={chat_id}"
    )

    # Отмечаем что пользователь начал решать - останавливает напоминания
    from bot.services.captcha.reminder_service import mark_user_interacted
    await mark_user_interacted(user_id, chat_id)

    # Проверяем ответ
    is_correct = user_answer == correct_answer

    # Определяем режим
    from bot.services.captcha.settings_service import CaptchaMode
    mode = CaptchaMode(mode_str)

    if is_correct:
        # ✅ ПРАВИЛЬНЫЙ ОТВЕТ
        logger.info(
            f"✅ [REDIS_INPUT] Капча пройдена: user_id={user_id}, chat_id={chat_id}"
        )

        # Обрабатываем успех
        from bot.services.captcha.flow_service import process_captcha_success
        await process_captcha_success(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            mode=mode,
        )

    else:
        # ❌ НЕПРАВИЛЬНЫЙ ОТВЕТ
        # Увеличиваем счётчик попыток
        from bot.services.captcha import increment_attempts, get_captcha_settings
        from bot.services.captcha.flow_service import process_captcha_failure

        # Получаем настройки для max_attempts
        settings = await get_captcha_settings(session, chat_id)
        max_attempts = settings.max_attempts

        attempts, exceeded = await increment_attempts(
            user_id=user_id,
            chat_id=chat_id,
            max_attempts=max_attempts,
        )

        if exceeded:
            # Исчерпаны попытки
            logger.info(
                f"❌ [REDIS_INPUT] Исчерпаны попытки: user_id={user_id}"
            )

            await process_captcha_failure(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user_id=user_id,
                mode=mode,
                reason="max_attempts",
            )

            # Отправляем сообщение
            await message.answer("❌ Вы исчерпали все попытки")

        else:
            # Ещё есть попытки
            remaining = max_attempts - attempts
            logger.info(
                f"⚠️ [REDIS_INPUT] Неверный ответ: user_id={user_id}, "
                f"attempts={attempts}/{max_attempts}"
            )

            await message.answer(
                f"❌ Неверно! Осталось попыток: {remaining}"
            )
