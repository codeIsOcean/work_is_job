# bot/services/captcha/cleanup_service.py
"""
Сервис очистки капчи - удаление сообщений, Redis ключей, контроль лимитов.

Отвечает за:
- Удаление капчи конкретного пользователя
- Очистку устаревших капч
- Контроль лимита одновременных капч в группе
- Удаление сообщений с капчей после таймаута
"""

import json
import logging
import time
from typing import Optional, List, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.redis_conn import redis
from bot.services.captcha.settings_service import (
    get_captcha_settings,
    CaptchaSettings,
)


# Логгер для отслеживания операций очистки
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# REDIS КЛЮЧИ ДЛЯ КАПЧИ
# Централизованное определение всех ключей для консистентности
# ═══════════════════════════════════════════════════════════════════════════

# Данные активной капчи (JSON с correct_hash, mode, created_at и т.д.)
CAPTCHA_DATA_KEY = "captcha:data:{user_id}:{chat_id}"

# ID сообщения с капчей (для удаления)
CAPTCHA_MESSAGE_KEY = "captcha:msg:{user_id}:{chat_id}"

# Счётчик попыток (сколько раз пользователь ошибся)
CAPTCHA_ATTEMPTS_KEY = "captcha:attempts:{user_id}:{chat_id}"

# Владелец капчи - для проверки что кнопку нажал правильный пользователь
CAPTCHA_OWNER_KEY = "captcha:owner:{chat_id}:{message_id}"


class CaptchaOverflowError(Exception):
    """
    Исключение при превышении лимита капч в группе.

    Выбрасывается когда overflow_action = "auto_decline"
    и новую капчу создать нельзя.
    """
    pass


async def cleanup_user_captcha(
    bot: Bot,
    chat_id: int,
    user_id: int,
    delete_message: bool = True,
) -> bool:
    """
    Полностью очищает капчу пользователя.

    Удаляет:
    - Сообщение с капчей (если delete_message=True)
    - Данные капчи из Redis
    - Счётчик попыток
    - Ключ владельца

    Args:
        bot: Экземпляр бота для удаления сообщений
        chat_id: ID группы
        user_id: ID пользователя
        delete_message: Удалять ли сообщение с капчей

    Returns:
        True если была активная капча и она очищена
    """
    # Формируем ключи Redis
    data_key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)
    msg_key = CAPTCHA_MESSAGE_KEY.format(user_id=user_id, chat_id=chat_id)
    attempts_key = CAPTCHA_ATTEMPTS_KEY.format(user_id=user_id, chat_id=chat_id)

    # Проверяем есть ли активная капча
    captcha_data_raw = await redis.get(data_key)

    # Если капчи нет - нечего очищать
    if not captcha_data_raw:
        logger.debug(
            f"🔍 [CAPTCHA_CLEANUP] Нет активной капчи: "
            f"user_id={user_id}, chat_id={chat_id}"
        )
        return False

    # Парсим данные капчи
    try:
        captcha_data = json.loads(captcha_data_raw)
    except json.JSONDecodeError:
        captcha_data = {}

    # Удаляем сообщение если нужно
    if delete_message:
        # Получаем ID сообщения
        msg_id_raw = await redis.get(msg_key)

        if msg_id_raw:
            # Декодируем ID сообщения
            msg_id = int(msg_id_raw)

            # Определяем куда было отправлено сообщение
            # target_chat_id может быть chat_id (группа) или user_id (ЛС)
            target_chat_id = captcha_data.get("target_chat_id", chat_id)

            try:
                # Пытаемся удалить сообщение
                await bot.delete_message(
                    chat_id=target_chat_id,
                    message_id=msg_id,
                )
                logger.debug(
                    f"🗑️ [CAPTCHA_CLEANUP] Сообщение удалено: "
                    f"chat={target_chat_id}, msg_id={msg_id}"
                )
            except TelegramAPIError as e:
                # Сообщение могло быть уже удалено - это нормально
                logger.debug(
                    f"⚠️ [CAPTCHA_CLEANUP] Не удалось удалить сообщение: {e}"
                )

            # Удаляем ключ владельца для этого сообщения
            owner_key = CAPTCHA_OWNER_KEY.format(
                chat_id=target_chat_id,
                message_id=msg_id,
            )
            await redis.delete(owner_key)

    # Удаляем все Redis ключи капчи
    await redis.delete(data_key, msg_key, attempts_key)

    # Логируем успешную очистку
    logger.info(
        f"✅ [CAPTCHA_CLEANUP] Капча очищена: "
        f"user_id={user_id}, chat_id={chat_id}"
    )

    return True


async def get_pending_captchas(
    chat_id: int,
) -> List[Tuple[int, float, str]]:
    """
    Получает список активных капч в группе.

    Сканирует Redis по паттерну и возвращает данные капч.

    Args:
        chat_id: ID группы

    Returns:
        Список кортежей (user_id, created_at, data_key)
        отсортированный по времени создания (старые первыми)
    """
    # Паттерн для поиска капч этой группы
    # Формат ключа: captcha:data:{user_id}:{chat_id}
    pattern = f"captcha:data:*:{chat_id}"

    # Сканируем Redis
    captchas = []

    # Используем scan для эффективного поиска
    cursor = 0
    while True:
        # SCAN возвращает курсор и список ключей
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)

        # Обрабатываем найденные ключи
        for key in keys:
            # Декодируем ключ если это bytes
            key_str = key.decode() if isinstance(key, bytes) else key

            # Извлекаем user_id из ключа
            # Формат: captcha:data:{user_id}:{chat_id}
            parts = key_str.split(":")
            if len(parts) >= 3:
                try:
                    user_id = int(parts[2])
                except ValueError:
                    continue

                # Получаем данные капчи
                data_raw = await redis.get(key_str)
                if data_raw:
                    try:
                        data = json.loads(data_raw)
                        created_at = data.get("created_at", 0)
                        captchas.append((user_id, created_at, key_str))
                    except json.JSONDecodeError:
                        continue

        # Если курсор вернулся к 0 - сканирование завершено
        if cursor == 0:
            break

    # Сортируем по времени создания (старые первыми)
    captchas.sort(key=lambda x: x[1])

    return captchas


async def enforce_captcha_limit(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    new_user_id: int,
) -> None:
    """
    Контролирует количество активных капч в группе.

    Если лимит превышен - выполняет действие согласно настройкам:
    - remove_oldest: удаляет самые старые капчи
    - auto_decline: отклоняет новый запрос (выбрасывает CaptchaOverflowError)
    - queue: пока не реализовано, действует как remove_oldest

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        new_user_id: ID нового пользователя для которого создаётся капча

    Raises:
        CaptchaOverflowError: если overflow_action="auto_decline"
    """
    # Получаем настройки группы
    settings = await get_captcha_settings(session, chat_id)

    # Если лимит не настроен - пропускаем проверку
    if settings.max_pending is None or settings.max_pending <= 0:
        logger.debug(
            f"🔍 [CAPTCHA_LIMIT] Лимит не настроен для chat_id={chat_id}"
        )
        return

    # Получаем текущие активные капчи
    pending = await get_pending_captchas(chat_id)

    # Если лимит не превышен - всё ок
    if len(pending) < settings.max_pending:
        logger.debug(
            f"✅ [CAPTCHA_LIMIT] В пределах лимита: "
            f"{len(pending)}/{settings.max_pending} в chat_id={chat_id}"
        )
        return

    # Лимит превышен - определяем действие
    action = settings.overflow_action or "remove_oldest"

    logger.warning(
        f"⚠️ [CAPTCHA_LIMIT] Превышен лимит капч: "
        f"{len(pending)}/{settings.max_pending} в chat_id={chat_id}, "
        f"action={action}"
    )

    if action == "auto_decline":
        # Отклоняем новый запрос
        try:
            await bot.decline_chat_join_request(chat_id, new_user_id)
            logger.info(
                f"❌ [CAPTCHA_LIMIT] Запрос отклонён: "
                f"user_id={new_user_id}, chat_id={chat_id}"
            )
        except TelegramAPIError as e:
            logger.debug(f"Не удалось отклонить запрос: {e}")

        # Выбрасываем исключение чтобы прервать создание капчи
        raise CaptchaOverflowError(
            f"Превышен лимит капч ({settings.max_pending}) в группе {chat_id}"
        )

    elif action in ("remove_oldest", "queue"):
        # Удаляем старые капчи чтобы освободить место
        # queue пока работает так же - позже можно добавить очередь

        # Сколько нужно удалить (оставляем место для новой)
        to_remove_count = len(pending) - settings.max_pending + 1

        # Берём самые старые капчи
        to_remove = pending[:to_remove_count]

        for user_id, created_at, data_key in to_remove:
            # Очищаем капчу
            await cleanup_user_captcha(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                delete_message=True,
            )

            # Пытаемся отклонить join request
            try:
                await bot.decline_chat_join_request(chat_id, user_id)
            except TelegramAPIError:
                pass  # Запрос мог уже не существовать

            logger.info(
                f"🧹 [CAPTCHA_LIMIT] Удалена старая капча: "
                f"user_id={user_id}, chat_id={chat_id}, "
                f"age={time.time() - created_at:.0f}s"
            )


async def cleanup_expired_captchas(
    bot: Bot,
    chat_id: int,
    timeout_seconds: int,
) -> int:
    """
    Очищает истёкшие капчи в группе.

    Может вызываться периодически для очистки забытых капч.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        timeout_seconds: Через сколько секунд капча считается истёкшей

    Returns:
        Количество очищенных капч
    """
    # Получаем все активные капчи
    pending = await get_pending_captchas(chat_id)

    # Текущее время
    now = time.time()

    # Счётчик очищенных
    cleaned = 0

    for user_id, created_at, data_key in pending:
        # Вычисляем возраст капчи
        age = now - created_at

        # Если капча истекла
        if age > timeout_seconds:
            # Очищаем
            await cleanup_user_captcha(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                delete_message=True,
            )

            # Пытаемся отклонить join request
            try:
                await bot.decline_chat_join_request(chat_id, user_id)
            except TelegramAPIError:
                pass

            cleaned += 1

            logger.info(
                f"⏰ [CAPTCHA_EXPIRED] Капча истекла: "
                f"user_id={user_id}, chat_id={chat_id}, age={age:.0f}s"
            )

    return cleaned


async def save_captcha_data(
    user_id: int,
    chat_id: int,
    data: dict,
    ttl: int,
) -> None:
    """
    Сохраняет данные капчи в Redis.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
        data: Словарь с данными капчи (correct_hash, mode, created_at и т.д.)
        ttl: Время жизни в секундах
    """
    # Формируем ключ
    key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)

    # Добавляем created_at если не задано
    if "created_at" not in data:
        data["created_at"] = time.time()

    # Сохраняем с TTL
    await redis.setex(key, ttl, json.dumps(data))

    logger.debug(
        f"💾 [CAPTCHA_DATA] Сохранено: "
        f"user_id={user_id}, chat_id={chat_id}, ttl={ttl}s"
    )


async def get_captcha_data(
    user_id: int,
    chat_id: int,
) -> Optional[dict]:
    """
    Получает данные активной капчи пользователя.

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        Словарь с данными капчи или None если капча не найдена
    """
    # Формируем ключ
    key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)

    # Получаем данные
    data_raw = await redis.get(key)

    # Если данных нет
    if not data_raw:
        return None

    # Парсим JSON
    try:
        return json.loads(data_raw)
    except json.JSONDecodeError:
        logger.error(f"❌ [CAPTCHA_DATA] Ошибка парсинга: key={key}")
        return None


async def save_captcha_message(
    user_id: int,
    chat_id: int,
    target_chat_id: int,
    message_id: int,
    ttl: int,
) -> None:
    """
    Сохраняет информацию о сообщении с капчей.

    Args:
        user_id: ID пользователя (владельца капчи)
        chat_id: ID группы для которой капча
        target_chat_id: ID чата куда отправлено сообщение (группа или ЛС)
        message_id: ID сообщения
        ttl: Время жизни в секундах
    """
    # Ключ для ID сообщения
    msg_key = CAPTCHA_MESSAGE_KEY.format(user_id=user_id, chat_id=chat_id)

    # Ключ владельца (для проверки кто нажимает кнопки)
    owner_key = CAPTCHA_OWNER_KEY.format(
        chat_id=target_chat_id,
        message_id=message_id,
    )

    # Сохраняем оба ключа
    await redis.setex(msg_key, ttl, str(message_id))
    await redis.setex(owner_key, ttl, str(user_id))

    logger.debug(
        f"💾 [CAPTCHA_MSG] Сохранено: "
        f"user_id={user_id}, chat_id={chat_id}, "
        f"target={target_chat_id}, msg_id={message_id}"
    )


async def get_captcha_owner(
    chat_id: int,
    message_id: int,
) -> Optional[int]:
    """
    Получает ID владельца капчи по сообщению.

    Используется для проверки что кнопку нажимает правильный пользователь.

    Args:
        chat_id: ID чата где находится сообщение
        message_id: ID сообщения с капчей

    Returns:
        user_id владельца или None если не найден
    """
    # Формируем ключ
    key = CAPTCHA_OWNER_KEY.format(chat_id=chat_id, message_id=message_id)

    # Получаем значение
    owner_raw = await redis.get(key)

    if not owner_raw:
        return None

    try:
        return int(owner_raw)
    except ValueError:
        return None


async def increment_attempts(
    user_id: int,
    chat_id: int,
    max_attempts: int = 3,
) -> Tuple[int, bool]:
    """
    Увеличивает счётчик попыток и проверяет лимит.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
        max_attempts: Максимум попыток

    Returns:
        Кортеж (текущее_количество_попыток, превышен_лимит)
    """
    # Формируем ключ
    key = CAPTCHA_ATTEMPTS_KEY.format(user_id=user_id, chat_id=chat_id)

    # Инкрементируем счётчик
    attempts = await redis.incr(key)

    # Устанавливаем TTL если это первая попытка
    if attempts == 1:
        # TTL 10 минут - достаточно для любой капчи
        await redis.expire(key, 600)

    # Проверяем лимит
    exceeded = attempts >= max_attempts

    logger.debug(
        f"📊 [CAPTCHA_ATTEMPTS] user_id={user_id}, chat_id={chat_id}, "
        f"attempts={attempts}/{max_attempts}, exceeded={exceeded}"
    )

    return attempts, exceeded
