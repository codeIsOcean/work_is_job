# ============================================================
# СЕРВИС CAS (COMBOT ANTI-SPAM)
# ============================================================
# Проверяет пользователя в глобальной базе забаненных спамеров.
#
# CAS (Combot Anti-Spam) — бесплатный сервис от Combot.
# Содержит миллионы заблокированных спамеров Telegram.
# API: https://api.cas.chat/check?user_id=XXX
#
# Документация: https://cas.chat/api
# ============================================================

# Импортируем aiohttp для асинхронных HTTP запросов
import aiohttp
# Импортируем asyncio для таймаутов
import asyncio
# Импортируем logging для логирования ошибок
import logging
# Импортируем типы для аннотаций
from typing import Optional, Dict, Any

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# КОНСТАНТЫ
# ============================================================
# URL API CAS для проверки пользователей
CAS_API_URL = "https://api.cas.chat/check"
# Таймаут запроса в секундах (чтобы не зависать если CAS недоступен)
CAS_TIMEOUT_SECONDS = 5


async def check_cas_ban(user_id: int) -> Dict[str, Any]:
    """
    Проверяет пользователя в базе CAS (Combot Anti-Spam).

    CAS — бесплатная глобальная база спамеров Telegram.
    Содержит миллионы заблокированных пользователей.

    Args:
        user_id: Telegram ID пользователя для проверки

    Returns:
        Словарь с результатом проверки:
        {
            "is_banned": True/False,  # Есть ли в базе CAS
            "offenses": int,          # Количество нарушений (если есть)
            "time_added": str,        # Когда добавлен в базу (если есть)
            "error": str              # Ошибка (если произошла)
        }

    Example:
        >>> result = await check_cas_ban(123456789)
        >>> if result["is_banned"]:
        ...     print(f"Спамер! Нарушений: {result['offenses']}")
    """
    # Результат по умолчанию — не в базе CAS
    result = {
        "is_banned": False,
        "offenses": 0,
        "time_added": None,
        "error": None
    }

    try:
        # Создаём таймаут для запроса (не зависаем если CAS недоступен)
        timeout = aiohttp.ClientTimeout(total=CAS_TIMEOUT_SECONDS)

        # Создаём HTTP сессию для запроса
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Формируем URL с параметром user_id
            url = f"{CAS_API_URL}?user_id={user_id}"

            # Отправляем GET запрос к API CAS
            async with session.get(url) as response:
                # Проверяем статус ответа (должен быть 200 OK)
                if response.status != 200:
                    # Логируем ошибку если статус не 200
                    logger.warning(
                        f"CAS API вернул статус {response.status} для user_id={user_id}"
                    )
                    # Возвращаем результат с ошибкой
                    result["error"] = f"HTTP {response.status}"
                    return result

                # Парсим JSON ответ от API
                data = await response.json()

                # ─────────────────────────────────────────────────
                # Структура ответа CAS API:
                # Если пользователь В базе:
                # {"ok": true, "result": {"offenses": 1, "time_added": "2024-01-15T..."}}
                #
                # Если пользователь НЕ в базе:
                # {"ok": false}
                # ─────────────────────────────────────────────────

                # Проверяем поле "ok" — если True, пользователь в базе CAS
                if data.get("ok"):
                    # Пользователь НАЙДЕН в базе CAS — он спамер!
                    result["is_banned"] = True

                    # Извлекаем детали из поля "result"
                    cas_result = data.get("result", {})
                    # Количество зафиксированных нарушений
                    result["offenses"] = cas_result.get("offenses", 0)
                    # Когда пользователь был добавлен в базу
                    result["time_added"] = cas_result.get("time_added")

                    # Логируем обнаружение спамера (для отладки)
                    logger.info(
                        f"CAS: user_id={user_id} НАЙДЕН в базе! "
                        f"Нарушений: {result['offenses']}, "
                        f"Добавлен: {result['time_added']}"
                    )
                else:
                    # Пользователь НЕ найден в базе CAS — он чист
                    result["is_banned"] = False

    except asyncio.TimeoutError:
        # Таймаут запроса — CAS не ответил вовремя
        logger.warning(f"CAS API таймаут для user_id={user_id}")
        result["error"] = "timeout"

    except aiohttp.ClientError as e:
        # Ошибка сети или подключения
        logger.error(f"CAS API ошибка сети для user_id={user_id}: {e}")
        result["error"] = f"network: {str(e)}"

    except Exception as e:
        # Неожиданная ошибка
        logger.exception(f"CAS API неожиданная ошибка для user_id={user_id}: {e}")
        result["error"] = f"unexpected: {str(e)}"

    # Возвращаем результат проверки
    return result


async def is_cas_banned(user_id: int) -> bool:
    """
    Упрощённая проверка: есть ли пользователь в базе CAS.

    Возвращает только True/False без деталей.
    При ошибках возвращает False (не блокируем если CAS недоступен).

    Args:
        user_id: Telegram ID пользователя

    Returns:
        True если пользователь в базе CAS, False иначе

    Example:
        >>> if await is_cas_banned(123456789):
        ...     await ban_user(123456789)
    """
    # Вызываем полную проверку
    result = await check_cas_ban(user_id)
    # Возвращаем только флаг is_banned
    return result.get("is_banned", False)
