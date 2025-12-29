# bot/services/captcha/reminder_service.py
"""
Сервис напоминаний о капче.

Отвечает за:
- Планирование напоминаний перед таймаутом
- Отправку напоминаний пользователю
- Отмену напоминаний при завершении капчи

Использует asyncio.create_task для планирования.
"""

import asyncio
import logging
from typing import Optional, Dict, Any

from aiogram import Bot

from bot.services.redis_conn import redis
from bot.handlers.captcha.captcha_messages import send_reminder_message
from bot.services.captcha.dm_flow_service import save_captcha_message_id


# Логгер для отслеживания напоминаний
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ REDIS КЛЮЧЕЙ
# ═══════════════════════════════════════════════════════════════════════════════

# Ключ для хранения флага активной капчи
# Формат: captcha_active:{user_id}:{chat_id}
CAPTCHA_ACTIVE_KEY = "captcha_active:{user_id}:{chat_id}"

# Ключ для хранения ID напоминающего сообщения
# Формат: captcha_reminder_msg:{user_id}
REMINDER_MSG_KEY = "captcha_reminder_msg:{user_id}"

# Ключ для отслеживания взаимодействия пользователя с капчей
# Если установлен - пользователь начал решать, напоминания не нужны
# Формат: captcha_interacted:{user_id}:{chat_id}
CAPTCHA_INTERACTED_KEY = "captcha_interacted:{user_id}:{chat_id}"

# TTL для ключей (10 минут)
CAPTCHA_TTL = 600


# ═══════════════════════════════════════════════════════════════════════════════
# ФУНКЦИИ УПРАВЛЕНИЯ СОСТОЯНИЕМ
# ═══════════════════════════════════════════════════════════════════════════════

async def mark_captcha_active(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Отмечает капчу как активную для пользователя.

    Используется для проверки нужно ли отправлять напоминание.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    # Формируем ключ Redis
    key = CAPTCHA_ACTIVE_KEY.format(user_id=user_id, chat_id=chat_id)

    # Сохраняем с TTL
    await redis.setex(key, CAPTCHA_TTL, "1")

    # Логируем
    logger.debug(
        f"🔔 [REMINDER] Капча активна: user_id={user_id}, chat_id={chat_id}"
    )


async def is_captcha_active(
    user_id: int,
    chat_id: int,
) -> bool:
    """
    Проверяет активна ли капча для пользователя.

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        True если капча активна
    """
    # Формируем ключ Redis
    key = CAPTCHA_ACTIVE_KEY.format(user_id=user_id, chat_id=chat_id)

    # Проверяем существование ключа
    exists = await redis.exists(key)

    return bool(exists)


async def mark_captcha_inactive(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Отмечает капчу как неактивную (завершена или отменена).

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    # Формируем ключ Redis
    key = CAPTCHA_ACTIVE_KEY.format(user_id=user_id, chat_id=chat_id)

    # Удаляем ключ
    await redis.delete(key)

    # Логируем
    logger.debug(
        f"🔕 [REMINDER] Капча неактивна: user_id={user_id}, chat_id={chat_id}"
    )


async def mark_user_interacted(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Отмечает что пользователь начал решать капчу.

    После этого напоминания не отправляются.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    key = CAPTCHA_INTERACTED_KEY.format(user_id=user_id, chat_id=chat_id)
    await redis.setex(key, CAPTCHA_TTL, "1")
    logger.debug(
        f"👆 [REMINDER] Пользователь начал решать: user_id={user_id}"
    )


async def has_user_interacted(
    user_id: int,
    chat_id: int,
) -> bool:
    """
    Проверяет начал ли пользователь решать капчу.

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        True если пользователь взаимодействовал с капчей
    """
    key = CAPTCHA_INTERACTED_KEY.format(user_id=user_id, chat_id=chat_id)
    exists = await redis.exists(key)
    return bool(exists)


async def clear_user_interaction(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Очищает флаг взаимодействия пользователя.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    key = CAPTCHA_INTERACTED_KEY.format(user_id=user_id, chat_id=chat_id)
    await redis.delete(key)


# ═══════════════════════════════════════════════════════════════════════════════
# ПЛАНИРОВАНИЕ НАПОМИНАНИЙ
# ═══════════════════════════════════════════════════════════════════════════════

async def schedule_reminder(
    bot: Bot,
    user_id: int,
    chat_id: int,
    reminder_seconds: int,
    timeout_seconds: int,
    max_reminders: int = 3,
) -> None:
    """
    Планирует отправку напоминания о капче.

    Напоминание отправляется через reminder_seconds секунд,
    если капча всё ещё активна.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        reminder_seconds: Через сколько секунд напомнить
        timeout_seconds: Общий таймаут капчи (для расчёта оставшегося времени)
        max_reminders: Максимум напоминаний (0 = безлимит)
    """
    # Если напоминание выключено (0 секунд) - не планируем
    if reminder_seconds <= 0:
        logger.debug(
            f"🔕 [REMINDER] Напоминания выключены: user_id={user_id}"
        )
        return

    # Отмечаем капчу как активную
    await mark_captcha_active(user_id, chat_id)

    # Создаём задачу напоминания
    asyncio.create_task(
        _reminder_task(
            bot=bot,
            user_id=user_id,
            chat_id=chat_id,
            delay_seconds=reminder_seconds,
            timeout_seconds=timeout_seconds,
            max_reminders=max_reminders,
        )
    )

    # Логируем планирование
    logger.info(
        f"🔔 [REMINDER] Запланировано: user_id={user_id}, "
        f"через {reminder_seconds} сек, макс {max_reminders} напоминаний"
    )


async def _reminder_task(
    bot: Bot,
    user_id: int,
    chat_id: int,
    delay_seconds: int,
    timeout_seconds: int,
    max_reminders: int = 3,
) -> None:
    """
    Внутренняя задача отправки ПЕРИОДИЧЕСКИХ напоминаний.

    Отправляет напоминание каждые delay_seconds секунд,
    пока:
    - Капча активна
    - Пользователь НЕ начал решать
    - Осталось > 10 секунд до таймаута
    - Не превышено max_reminders (если > 0)

    Каждое предыдущее напоминание удаляется.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        delay_seconds: Интервал между напоминаниями (секунды)
        timeout_seconds: Общий таймаут капчи
        max_reminders: Максимум напоминаний (0 = безлимит)
    """
    elapsed = 0  # Сколько времени прошло с начала
    sent_count = 0  # Сколько напоминаний отправлено

    try:
        while True:
            # Ждём интервал напоминания
            await asyncio.sleep(delay_seconds)
            elapsed += delay_seconds

            # Проверяем активна ли ещё капча
            if not await is_captcha_active(user_id, chat_id):
                logger.debug(
                    f"🔕 [REMINDER] Капча неактивна: user_id={user_id}"
                )
                break

            # Проверяем начал ли пользователь решать
            if await has_user_interacted(user_id, chat_id):
                logger.debug(
                    f"🔕 [REMINDER] Пользователь решает: user_id={user_id}"
                )
                break

            # Проверяем лимит напоминаний (если задан)
            if max_reminders > 0 and sent_count >= max_reminders:
                logger.debug(
                    f"🔕 [REMINDER] Лимит достигнут: user_id={user_id}, "
                    f"sent={sent_count}/{max_reminders}"
                )
                break

            # Рассчитываем оставшееся время
            seconds_left = timeout_seconds - elapsed

            # Если осталось меньше 10 секунд - прекращаем
            if seconds_left < 10:
                logger.debug(
                    f"🔕 [REMINDER] Мало времени: user_id={user_id}"
                )
                break

            # Удаляем предыдущее напоминание перед отправкой нового
            await _delete_previous_reminder(bot, user_id)

            # Отправляем новое напоминание
            message = await send_reminder_message(
                bot=bot,
                user_id=user_id,
                seconds_left=seconds_left,
            )

            # Сохраняем ID для последующего удаления
            if message:
                await _save_reminder_message_id(user_id, message.message_id)
                # Также сохраняем в общий список для чистки диалога
                await save_captcha_message_id(user_id, message.message_id)
                sent_count += 1

            logger.info(
                f"🔔 [REMINDER] Отправлено: user_id={user_id}, "
                f"осталось {seconds_left} сек, напоминание {sent_count}"
                f"{'/' + str(max_reminders) if max_reminders > 0 else ''}"
            )

    except asyncio.CancelledError:
        logger.debug(f"🔕 [REMINDER] Задача отменена: user_id={user_id}")

    except Exception as e:
        logger.error(
            f"❌ [REMINDER] Ошибка: user_id={user_id}, error={e}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ПЛАНИРОВАНИЕ ТАЙМАУТА
# ═══════════════════════════════════════════════════════════════════════════════

async def schedule_timeout(
    bot: Bot,
    user_id: int,
    chat_id: int,
    timeout_seconds: int,
    on_timeout_callback: Optional[Any] = None,
) -> None:
    """
    Планирует таймаут капчи.

    После timeout_seconds секунд, если капча активна,
    вызывает callback для обработки провала.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        timeout_seconds: Таймаут в секундах
        on_timeout_callback: Функция для вызова при таймауте
    """
    # Создаём задачу таймаута
    asyncio.create_task(
        _timeout_task(
            bot=bot,
            user_id=user_id,
            chat_id=chat_id,
            timeout_seconds=timeout_seconds,
            on_timeout_callback=on_timeout_callback,
        )
    )

    # Логируем планирование
    logger.info(
        f"⏰ [TIMEOUT] Запланирован: user_id={user_id}, "
        f"через {timeout_seconds} сек"
    )


async def _timeout_task(
    bot: Bot,
    user_id: int,
    chat_id: int,
    timeout_seconds: int,
    on_timeout_callback: Optional[Any] = None,
) -> None:
    """
    Внутренняя задача таймаута.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        timeout_seconds: Таймаут в секундах
        on_timeout_callback: Callback при таймауте
    """
    try:
        # Ждём таймаут
        await asyncio.sleep(timeout_seconds)

        # Проверяем активна ли капча
        if not await is_captcha_active(user_id, chat_id):
            # Капча уже завершена
            logger.debug(
                f"⏰ [TIMEOUT] Капча уже завершена: user_id={user_id}"
            )
            return

        # Логируем таймаут
        logger.info(
            f"⏰ [TIMEOUT] Время вышло: user_id={user_id}, chat_id={chat_id}"
        )

        # Отмечаем капчу как неактивную
        await mark_captcha_inactive(user_id, chat_id)

        # Вызываем callback если передан
        if on_timeout_callback:
            try:
                await on_timeout_callback(bot, user_id, chat_id)
            except Exception as e:
                logger.error(
                    f"❌ [TIMEOUT] Ошибка callback: user_id={user_id}, error={e}"
                )

        # Удаляем последнее напоминание перед отправкой сообщения о таймауте
        await _delete_previous_reminder(bot, user_id)

        # Получаем настройки для определения failure_action и cleanup_delay
        # Используем дефолты если не получится получить из настроек
        failure_action = "keep"  # По умолчанию оставляем заявку висеть
        cleanup_delay = 120
        try:
            from bot.database.session import get_session
            from bot.services.captcha.settings_service import get_captcha_settings
            async with get_session() as session:
                settings = await get_captcha_settings(session, chat_id)
                failure_action = settings.failure_action
                cleanup_delay = settings.dialog_cleanup_seconds
        except Exception as e:
            logger.debug(f"Используем дефолты (failure_action=keep, cleanup_delay=120): {e}")

        # Получаем информацию о группе для сообщения о провале
        group_name = None
        group_link = None
        try:
            chat_info = await bot.get_chat(chat_id)
            group_name = chat_info.title
            if chat_info.username:
                group_link = f"https://t.me/{chat_info.username}"
        except Exception as e:
            logger.debug(f"Не удалось получить информацию о группе: {e}")

        # Отправляем сообщение о таймауте
        from bot.handlers.captcha.captcha_messages import send_failure_message
        # Сохраняем сообщение чтобы потом удалить при чистке диалога
        failure_msg = await send_failure_message(
            bot, user_id, reason="timeout",
            group_name=group_name, group_link=group_link
        )
        if failure_msg:
            # Сохраняем ID для чистки диалога
            await save_captcha_message_id(user_id, failure_msg.message_id)

        # Проверяем настройку failure_action
        # "decline" = отклонить заявку, "keep" = оставить висеть
        if failure_action == "decline":
            # Отклоняем join request
            try:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
                logger.info(
                    f"🚫 [TIMEOUT] Join request отклонён: "
                    f"user_id={user_id}, chat_id={chat_id}"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ [TIMEOUT] Не удалось отклонить: {e}"
                )
        else:
            # failure_action == "keep" - оставляем заявку висеть
            logger.info(
                f"📌 [TIMEOUT] Join request оставлен (failure_action=keep): "
                f"user_id={user_id}, chat_id={chat_id}"
            )

        # Планируем чистку если задержка > 0
        if cleanup_delay > 0:
            await schedule_dialog_cleanup(
                bot=bot,
                user_id=user_id,
                cleanup_seconds=cleanup_delay,
            )

    except asyncio.CancelledError:
        logger.debug(f"⏰ [TIMEOUT] Задача отменена: user_id={user_id}")

    except Exception as e:
        logger.error(
            f"❌ [TIMEOUT] Ошибка: user_id={user_id}, error={e}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════════

async def _save_reminder_message_id(
    user_id: int,
    message_id: int,
) -> None:
    """
    Сохраняет ID сообщения напоминания для последующего удаления.

    Args:
        user_id: ID пользователя
        message_id: ID сообщения
    """
    key = REMINDER_MSG_KEY.format(user_id=user_id)
    await redis.setex(key, CAPTCHA_TTL, str(message_id))


async def _delete_previous_reminder(
    bot: Bot,
    user_id: int,
) -> None:
    """
    Удаляет предыдущее сообщение напоминания.

    Вызывается перед отправкой нового напоминания.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
    """
    key = REMINDER_MSG_KEY.format(user_id=user_id)

    # Получаем ID предыдущего сообщения
    prev_msg_id = await redis.get(key)

    if prev_msg_id:
        try:
            await bot.delete_message(
                chat_id=user_id,
                message_id=int(prev_msg_id),
            )
            logger.debug(
                f"🗑️ [REMINDER] Удалено предыдущее: user_id={user_id}, "
                f"msg_id={prev_msg_id}"
            )
        except Exception:
            # Сообщение уже удалено - пропускаем
            pass

        # Удаляем ключ
        await redis.delete(key)


async def cancel_reminders(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Отменяет все напоминания для пользователя.

    Вызывается при успешном прохождении или отмене капчи.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    # Отмечаем капчу как неактивную (это остановит все задачи)
    await mark_captcha_inactive(user_id, chat_id)

    # Удаляем ключ напоминающего сообщения
    key = REMINDER_MSG_KEY.format(user_id=user_id)
    await redis.delete(key)

    # Логируем
    logger.debug(
        f"🔕 [REMINDER] Напоминания отменены: user_id={user_id}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ПЛАНИРОВАНИЕ ЧИСТКИ ДИАЛОГА
# ═══════════════════════════════════════════════════════════════════════════════

async def schedule_dialog_cleanup(
    bot: Bot,
    user_id: int,
    cleanup_seconds: int,
) -> None:
    """
    Планирует чистку диалога после завершения капчи.

    Удаляет все сообщения капчи через cleanup_seconds секунд.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя (это chat_id для ЛС)
        cleanup_seconds: Через сколько секунд чистить
    """
    # Создаём задачу чистки
    asyncio.create_task(
        _cleanup_task(
            bot=bot,
            user_id=user_id,
            delay_seconds=cleanup_seconds,
        )
    )

    # Логируем
    logger.info(
        f"🧹 [CLEANUP] Запланирована чистка: user_id={user_id}, "
        f"через {cleanup_seconds} сек"
    )


async def _cleanup_task(
    bot: Bot,
    user_id: int,
    delay_seconds: int,
) -> None:
    """
    Внутренняя задача чистки диалога.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        delay_seconds: Задержка в секундах
    """
    try:
        # Ждём указанное время
        await asyncio.sleep(delay_seconds)

        # Импортируем функцию получения ID сообщений
        from bot.services.captcha.dm_flow_service import (
            get_captcha_message_ids,
            delete_captcha_message_ids,
        )

        # Получаем ID сообщений для удаления
        message_ids = await get_captcha_message_ids(user_id)

        # Удаляем сообщения
        deleted_count = 0
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id=user_id, message_id=msg_id)
                deleted_count += 1
            except Exception:
                # Сообщение уже удалено - пропускаем
                pass

        # Удаляем список ID из Redis
        await delete_captcha_message_ids(user_id)

        # Логируем результат
        logger.info(
            f"🧹 [CLEANUP] Удалено сообщений: user_id={user_id}, "
            f"count={deleted_count}/{len(message_ids)}"
        )

    except asyncio.CancelledError:
        logger.debug(f"🧹 [CLEANUP] Задача отменена: user_id={user_id}")

    except Exception as e:
        logger.error(
            f"❌ [CLEANUP] Ошибка: user_id={user_id}, error={e}"
        )
