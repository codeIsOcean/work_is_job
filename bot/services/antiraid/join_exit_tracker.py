# bot/services/antiraid/join_exit_tracker.py
"""
Трекер частых входов/выходов пользователя (Join/Exit Abuse).

Решает проблему ботов которые заходят-выходят чтобы засветить
своё имя в приветственном сообщении группы.

Алгоритм:
1. При входе/выходе записываем timestamp в Redis
2. Считаем количество событий в окне времени
3. Если превышен порог — применяем действие (бан/кик/мут)

Redis ключи:
- ar:je:{chat_id}:{user_id}:events — List timestamps событий
"""

# Импортируем логгер для записи событий
import logging
# Импортируем типы для аннотаций
from typing import NamedTuple, Optional
# Импортируем time для timestamps
import time

# Импортируем Redis клиент
from redis.asyncio import Redis

# Импортируем сессию для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис настроек
from bot.services.antiraid.settings_service import get_antiraid_settings


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ
# ============================================================

class JoinExitCheckResult(NamedTuple):
    """
    Результат проверки на злоупотребление входами/выходами.

    Attributes:
        is_abuse: True если обнаружено злоупотребление
        event_count: Количество событий в окне
        threshold: Порог срабатывания
        window_seconds: Временное окно в секундах
    """
    # Флаг: является ли это злоупотреблением
    is_abuse: bool
    # Количество событий в окне
    event_count: int
    # Порог срабатывания
    threshold: int
    # Временное окно
    window_seconds: int


# ============================================================
# КЛАСС ТРЕКЕРА
# ============================================================

class JoinExitTracker:
    """
    Трекер частых входов/выходов пользователя.

    Использует Redis для хранения истории событий.
    Определяет злоупотребление по количеству событий
    в заданном временном окне.

    Пример использования:
        tracker = JoinExitTracker(redis_client)
        result = await tracker.record_and_check(
            chat_id=-100123456,
            user_id=12345,
            event_type="join",
            threshold=3,
            window_seconds=60
        )
        if result.is_abuse:
            print(f"Злоупотребление! Событий: {result.event_count}")
    """

    # Префикс для Redis ключей
    REDIS_PREFIX = "ar:je"

    def __init__(self, redis: Redis):
        """
        Инициализация трекера.

        Args:
            redis: Клиент Redis для хранения истории событий
        """
        # Сохраняем ссылку на Redis клиент
        self._redis = redis

    def _get_events_key(self, chat_id: int, user_id: int) -> str:
        """
        Формирует Redis ключ для хранения событий.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Ключ Redis
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:events"

    async def record_event(
        self,
        chat_id: int,
        user_id: int,
        event_type: str,
        window_seconds: int = 60
    ) -> int:
        """
        Записывает событие входа/выхода.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            event_type: Тип события ('join' или 'exit')
            window_seconds: Временное окно для хранения (TTL)

        Returns:
            Текущее количество событий в окне
        """
        # Ключ Redis
        events_key = self._get_events_key(chat_id, user_id)

        # Текущий timestamp
        now = time.time()

        try:
            # ─────────────────────────────────────────────────────────
            # ШАГ 1: Добавляем timestamp события
            # ─────────────────────────────────────────────────────────
            # Формат: "type:timestamp" (например "join:1705498800.123")
            event_data = f"{event_type}:{now}"
            await self._redis.rpush(events_key, event_data)

            # ─────────────────────────────────────────────────────────
            # ШАГ 2: Устанавливаем/обновляем TTL
            # ─────────────────────────────────────────────────────────
            # TTL = window_seconds + небольшой запас
            await self._redis.expire(events_key, window_seconds + 10)

            # ─────────────────────────────────────────────────────────
            # ШАГ 3: Удаляем старые события за пределами окна
            # ─────────────────────────────────────────────────────────
            # Получаем все события
            all_events = await self._redis.lrange(events_key, 0, -1)

            # Фильтруем события в пределах окна
            cutoff = now - window_seconds
            valid_events = []

            for event in all_events:
                # Парсим timestamp
                try:
                    _, ts_str = event.rsplit(":", 1)
                    ts = float(ts_str)
                    if ts >= cutoff:
                        valid_events.append(event)
                except (ValueError, IndexError):
                    # Пропускаем невалидные записи
                    pass

            # Если есть старые события — перезаписываем список
            if len(valid_events) < len(all_events):
                # Удаляем старый список
                await self._redis.delete(events_key)
                # Записываем только валидные события
                if valid_events:
                    await self._redis.rpush(events_key, *valid_events)
                    await self._redis.expire(events_key, window_seconds + 10)

            # Возвращаем текущее количество событий
            return len(valid_events)

        except Exception as e:
            # Логируем ошибку Redis
            logger.error(
                f"[JoinExitTracker] Ошибка записи события: {e}, "
                f"chat_id={chat_id}, user_id={user_id}"
            )
            # При ошибке возвращаем 0 (не блокируем)
            return 0

    async def record_and_check(
        self,
        chat_id: int,
        user_id: int,
        event_type: str,
        threshold: int = 3,
        window_seconds: int = 60
    ) -> JoinExitCheckResult:
        """
        Записывает событие и проверяет на злоупотребление.

        Это ГЛАВНАЯ функция для использования.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            event_type: Тип события ('join' или 'exit')
            threshold: Порог срабатывания
            window_seconds: Временное окно в секундах

        Returns:
            JoinExitCheckResult с результатом проверки
        """
        # Записываем событие и получаем количество
        event_count = await self.record_event(
            chat_id=chat_id,
            user_id=user_id,
            event_type=event_type,
            window_seconds=window_seconds
        )

        # Проверяем превышение порога
        is_abuse = event_count >= threshold

        if is_abuse:
            logger.warning(
                f"[JoinExitTracker] Обнаружено злоупотребление! "
                f"chat_id={chat_id}, user_id={user_id}, "
                f"event_count={event_count} >= {threshold}, "
                f"window={window_seconds}s"
            )
        else:
            logger.debug(
                f"[JoinExitTracker] Событие записано: "
                f"type={event_type}, count={event_count}/{threshold}"
            )

        return JoinExitCheckResult(
            is_abuse=is_abuse,
            event_count=event_count,
            threshold=threshold,
            window_seconds=window_seconds
        )

    async def get_event_count(
        self,
        chat_id: int,
        user_id: int,
        window_seconds: int = 60
    ) -> int:
        """
        Получает текущее количество событий в окне.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            window_seconds: Временное окно

        Returns:
            Количество событий в окне
        """
        events_key = self._get_events_key(chat_id, user_id)
        now = time.time()
        cutoff = now - window_seconds

        try:
            # Получаем все события
            all_events = await self._redis.lrange(events_key, 0, -1)

            # Считаем события в пределах окна
            count = 0
            for event in all_events:
                try:
                    _, ts_str = event.rsplit(":", 1)
                    ts = float(ts_str)
                    if ts >= cutoff:
                        count += 1
                except (ValueError, IndexError):
                    pass

            return count

        except Exception as e:
            logger.error(f"[JoinExitTracker] Ошибка получения count: {e}")
            return 0

    async def reset_user_events(
        self,
        chat_id: int,
        user_id: int
    ) -> bool:
        """
        Сбрасывает историю событий для пользователя.

        Полезно при разбане или по команде админа.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            True если успешно
        """
        try:
            events_key = self._get_events_key(chat_id, user_id)
            await self._redis.delete(events_key)

            logger.info(
                f"[JoinExitTracker] Сброшены события: "
                f"chat_id={chat_id}, user_id={user_id}"
            )
            return True

        except Exception as e:
            logger.error(f"[JoinExitTracker] Ошибка сброса: {e}")
            return False


# ============================================================
# ФУНКЦИИ ДЛЯ ИСПОЛЬЗОВАНИЯ В КООРДИНАТОРЕ
# ============================================================

async def check_join_exit_abuse(
    redis: Redis,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    event_type: str
) -> Optional[JoinExitCheckResult]:
    """
    Проверяет злоупотребление входами/выходами с учётом настроек группы.

    Это ГЛАВНАЯ функция для вызова из координатора.
    Автоматически читает настройки группы из БД.

    Args:
        redis: Клиент Redis
        session: Сессия SQLAlchemy
        chat_id: ID чата
        user_id: ID пользователя
        event_type: Тип события ('join' или 'exit')

    Returns:
        JoinExitCheckResult если включено, None если выключено
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или join_exit выключен — пропускаем
    if settings is None or not settings.join_exit_enabled:
        logger.debug(
            f"[JoinExitTracker] Join/Exit отключён для chat_id={chat_id}"
        )
        return None

    # ─────────────────────────────────────────────────────────
    # Создаём трекер и проверяем
    # ─────────────────────────────────────────────────────────
    tracker = JoinExitTracker(redis)

    result = await tracker.record_and_check(
        chat_id=chat_id,
        user_id=user_id,
        event_type=event_type,
        threshold=settings.join_exit_threshold,
        window_seconds=settings.join_exit_window
    )

    return result


# ============================================================
# ФАБРИЧНАЯ ФУНКЦИЯ
# ============================================================

def create_join_exit_tracker(redis: Redis) -> JoinExitTracker:
    """
    Создаёт экземпляр JoinExitTracker.

    Args:
        redis: Клиент Redis

    Returns:
        Экземпляр JoinExitTracker
    """
    return JoinExitTracker(redis)
