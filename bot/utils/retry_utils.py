# ============================================================
# RETRY UTILS - УТИЛИТЫ ДЛЯ RETRY ПРИ СЕТЕВЫХ ОШИБКАХ
# ============================================================
# Этот модуль содержит утилиты для повторных попыток при
# сетевых ошибках, особенно актуальных для Windows
# (WinError 121 "Превышен таймаут семафора")
# ============================================================

import asyncio
import logging
from typing import TypeVar, Callable, Awaitable, Optional
from functools import wraps

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

logger = logging.getLogger(__name__)

# Тип для возвращаемого значения
T = TypeVar('T')


async def retry_on_network_error(
    coro: Awaitable[T],
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0
) -> T:
    """
    Выполняет корутину с retry при сетевых ошибках.

    Полезно для Windows где может возникать WinError 121
    при webhook режиме.

    Args:
        coro: Корутина для выполнения
        max_retries: Максимальное количество повторных попыток
        delay: Начальная задержка между попытками (секунды)
        backoff: Множитель задержки для каждой следующей попытки

    Returns:
        Результат выполнения корутины

    Raises:
        Последнее исключение если все попытки неудачны

    Example:
        result = await retry_on_network_error(
            message.answer("Hello"),
            max_retries=3
        )
    """
    last_exception = None
    current_delay = delay

    for attempt in range(max_retries + 1):
        try:
            return await coro
        except TelegramNetworkError as e:
            last_exception = e

            if attempt < max_retries:
                logger.warning(
                    f"[Retry] Сетевая ошибка (попытка {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Повтор через {current_delay:.1f}с..."
                )
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(
                    f"[Retry] Все {max_retries + 1} попыток исчерпаны. "
                    f"Последняя ошибка: {e}"
                )
        except TelegramRetryAfter as e:
            # Telegram просит подождать
            wait_time = e.retry_after + 1
            logger.warning(
                f"[Retry] Telegram rate limit. Ожидание {wait_time}с..."
            )
            await asyncio.sleep(wait_time)
            # Не считаем как попытку
            continue
        except OSError as e:
            # Ловим WinError 121 и подобные
            if "121" in str(e) or "семафор" in str(e).lower():
                last_exception = e
                if attempt < max_retries:
                    logger.warning(
                        f"[Retry] Windows сетевая ошибка (попытка {attempt + 1}): {e}. "
                        f"Повтор через {current_delay:.1f}с..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
                else:
                    logger.error(f"[Retry] Windows ошибка, попытки исчерпаны: {e}")
            else:
                raise

    # Если все попытки неудачны - выбрасываем последнее исключение
    if last_exception:
        raise last_exception


def with_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0
) -> Callable:
    """
    Декоратор для автоматического retry при сетевых ошибках.

    Args:
        max_retries: Максимальное количество повторных попыток
        delay: Начальная задержка между попытками
        backoff: Множитель задержки

    Returns:
        Декоратор

    Example:
        @with_retry(max_retries=3)
        async def send_notification(message, text):
            await message.answer(text)
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (TelegramNetworkError, OSError) as e:
                    # Проверяем что это сетевая ошибка Windows
                    if isinstance(e, OSError) and "121" not in str(e):
                        raise

                    last_exception = e

                    if attempt < max_retries:
                        logger.warning(
                            f"[Retry] {func.__name__}: ошибка (попытка {attempt + 1}): {e}"
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"[Retry] {func.__name__}: все попытки исчерпаны"
                        )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    continue

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


async def safe_answer(
    message,
    text: str,
    max_retries: int = 2,
    **kwargs
) -> Optional[any]:
    """
    Безопасная отправка ответа с retry.

    Удобная обёртка для message.answer() с автоматическим retry.

    Args:
        message: Объект Message
        text: Текст ответа
        max_retries: Количество повторных попыток
        **kwargs: Дополнительные параметры для answer()

    Returns:
        Результат message.answer() или None при ошибке

    Example:
        await safe_answer(message, "Готово!", parse_mode="HTML")
    """
    try:
        return await retry_on_network_error(
            message.answer(text, **kwargs),
            max_retries=max_retries
        )
    except Exception as e:
        logger.error(f"[safe_answer] Не удалось отправить ответ: {e}")
        return None


async def safe_edit(
    message,
    text: str,
    max_retries: int = 2,
    **kwargs
) -> Optional[any]:
    """
    Безопасное редактирование сообщения с retry.

    Args:
        message: Объект Message для редактирования
        text: Новый текст
        max_retries: Количество повторных попыток
        **kwargs: Дополнительные параметры

    Returns:
        Результат или None при ошибке
    """
    try:
        return await retry_on_network_error(
            message.edit_text(text, **kwargs),
            max_retries=max_retries
        )
    except Exception as e:
        logger.error(f"[safe_edit] Не удалось отредактировать: {e}")
        return None
