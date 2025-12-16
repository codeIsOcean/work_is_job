# bot/services/captcha/verification_service.py
"""
Сервис верификации капчи - проверка ответов и владельца.

Отвечает за:
- Проверку правильности ответа на капчу
- Проверку что кнопку нажимает владелец капчи
- Хэширование ответов для безопасного сравнения
"""

import hashlib
import logging
from typing import Optional

from bot.services.captcha.cleanup_service import (
    get_captcha_data,
    get_captcha_owner,
)


# Логгер для отслеживания верификации
logger = logging.getLogger(__name__)


def hash_answer(answer: str) -> str:
    """
    Создаёт хэш ответа для безопасного хранения и сравнения.

    Используется короткий хэш (8 символов) для callback_data,
    так как Telegram ограничивает длину callback_data до 64 байт.

    Args:
        answer: Ответ на капчу (текст или число)

    Returns:
        8-символьный MD5 хэш ответа
    """
    # Нормализуем ответ: lowercase и strip
    normalized = str(answer).lower().strip()

    # Вычисляем MD5 хэш
    full_hash = hashlib.md5(normalized.encode()).hexdigest()

    # Возвращаем первые 8 символов (достаточно для уникальности)
    return full_hash[:8]


def verify_answer_hash(
    provided_hash: str,
    correct_hash: str,
) -> bool:
    """
    Сравнивает хэш предоставленного ответа с правильным.

    Args:
        provided_hash: Хэш ответа пользователя (из callback_data)
        correct_hash: Хэш правильного ответа (из Redis)

    Returns:
        True если хэши совпадают
    """
    # Простое сравнение хэшей
    # Оба должны быть в lowercase
    result = provided_hash.lower() == correct_hash.lower()

    logger.debug(
        f"🔐 [VERIFY_HASH] provided={provided_hash}, "
        f"correct={correct_hash}, match={result}"
    )

    return result


async def verify_captcha_answer(
    user_id: int,
    chat_id: int,
    answer_hash: str,
) -> bool:
    """
    Проверяет ответ пользователя на капчу.

    Получает правильный хэш из Redis и сравнивает.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
        answer_hash: Хэш ответа из callback_data

    Returns:
        True если ответ правильный
    """
    # Получаем данные капчи из Redis
    captcha_data = await get_captcha_data(user_id, chat_id)

    # Если капча не найдена (истекла)
    if not captcha_data:
        logger.warning(
            f"⚠️ [VERIFY_ANSWER] Капча не найдена: "
            f"user_id={user_id}, chat_id={chat_id}"
        )
        return False

    # Получаем правильный хэш
    correct_hash = captcha_data.get("correct_hash")

    if not correct_hash:
        logger.error(
            f"❌ [VERIFY_ANSWER] Нет correct_hash в данных капчи: "
            f"user_id={user_id}, chat_id={chat_id}, data={captcha_data}"
        )
        return False

    # Логируем сравнение для отладки
    logger.info(
        f"🔐 [VERIFY_ANSWER] Сравнение хэшей: "
        f"user_id={user_id}, provided={answer_hash}, correct={correct_hash}"
    )

    # Сравниваем хэши
    return verify_answer_hash(answer_hash, correct_hash)


async def check_captcha_ownership(
    clicker_user_id: int,
    chat_id: int,
    message_id: int,
) -> tuple[bool, Optional[int]]:
    """
    Проверяет что кнопку капчи нажимает её владелец.

    Критически важная функция безопасности - предотвращает
    нажатие чужих капч другими пользователями.

    Args:
        clicker_user_id: ID пользователя который нажал кнопку
        chat_id: ID чата где находится сообщение с капчей
        message_id: ID сообщения с капчей

    Returns:
        Кортеж (is_owner, owner_user_id)
        - is_owner: True если clicker_user_id == owner_user_id
        - owner_user_id: ID реального владельца (или None если не найден)
    """
    # Получаем владельца капчи
    owner_user_id = await get_captcha_owner(chat_id, message_id)

    # Если владелец не найден (капча истекла или удалена)
    if owner_user_id is None:
        logger.warning(
            f"⚠️ [OWNERSHIP_CHECK] Владелец не найден: "
            f"chat_id={chat_id}, message_id={message_id}"
        )
        return False, None

    # Проверяем совпадение
    is_owner = clicker_user_id == owner_user_id

    if not is_owner:
        # Логируем попытку нажать чужую капчу
        logger.warning(
            f"🚫 [OWNERSHIP_CHECK] Попытка нажать чужую капчу: "
            f"clicker={clicker_user_id}, owner={owner_user_id}, "
            f"chat_id={chat_id}, message_id={message_id}"
        )

    return is_owner, owner_user_id


def check_captcha_ownership_by_callback_data(
    clicker_user_id: int,
    owner_from_callback: int,
    chat_id: int,
) -> bool:
    """
    Альтернативная проверка владельца через callback_data.

    Используется когда owner_user_id закодирован в callback_data.
    Это более надёжный способ, так как не зависит от Redis TTL.

    Args:
        clicker_user_id: ID пользователя который нажал кнопку
        owner_from_callback: ID владельца из callback_data
        chat_id: ID группы (для логирования)

    Returns:
        True если clicker_user_id == owner_from_callback
    """
    # Простое сравнение
    is_owner = clicker_user_id == owner_from_callback

    if not is_owner:
        logger.warning(
            f"🚫 [OWNERSHIP_CALLBACK] Попытка нажать чужую капчу: "
            f"clicker={clicker_user_id}, owner={owner_from_callback}, "
            f"chat_id={chat_id}"
        )

    return is_owner


def generate_captcha_options(
    correct_answer: str,
    count: int = 4,
) -> list[dict]:
    """
    Генерирует варианты ответов для капчи.

    Создаёт список вариантов включая правильный ответ
    и несколько неправильных (decoy).

    Args:
        correct_answer: Правильный ответ
        count: Общее количество вариантов (включая правильный)

    Returns:
        Список словарей с ключами 'text' и 'hash'
    """
    import random

    # Результат
    options = []

    # Добавляем правильный ответ
    correct_hash = hash_answer(correct_answer)
    options.append({
        "text": str(correct_answer),
        "hash": correct_hash,
        "is_correct": True,
    })

    # Определяем тип ответа для генерации decoy
    try:
        # Если ответ - число
        num = int(correct_answer)

        # Генерируем похожие числа
        decoys = set()
        while len(decoys) < count - 1:
            # Случайное отклонение от -10 до +10
            offset = random.randint(-10, 10)
            if offset == 0:
                continue
            decoy = num + offset
            # Не допускаем отрицательных
            if decoy < 0:
                continue
            decoys.add(decoy)

        # Добавляем decoy
        for decoy in decoys:
            decoy_hash = hash_answer(str(decoy))
            options.append({
                "text": str(decoy),
                "hash": decoy_hash,
                "is_correct": False,
            })

    except ValueError:
        # Если ответ - текст, генерируем случайные варианты
        # Для текстовой капчи нужна другая логика
        # Пока просто добавляем похожие строки
        for i in range(count - 1):
            decoy = correct_answer[::-1] if i % 2 == 0 else correct_answer.upper()
            if decoy == correct_answer:
                decoy = f"X{correct_answer}"
            decoy_hash = hash_answer(decoy)
            options.append({
                "text": decoy,
                "hash": decoy_hash,
                "is_correct": False,
            })

    # Перемешиваем варианты
    random.shuffle(options)

    return options
