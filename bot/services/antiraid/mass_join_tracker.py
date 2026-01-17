# bot/services/antiraid/mass_join_tracker.py
"""
Трекер массовых вступлений (Raid Detection) v2.

Обнаруживает координированные атаки когда много пользователей
вступают в группу одновременно.

v2 ИЗМЕНЕНИЯ:
- При детекции рейда включается "режим защиты" (protection mode)
- Все новые вступления во время protection mode = БАН
- Protection mode имеет TTL (protection_duration из настроек)
- После истечения TTL защита снимается автоматически

Алгоритм v2:
1. Проверяем активен ли protection mode
2. Если ДА → текущий юзер должен быть забанен (is_protection_mode=True)
3. Записываем вступление в Sorted Set (score=timestamp)
4. Считаем количество вступлений в окне
5. Если превышен порог И protection НЕ активен:
   - Включаем protection mode с TTL=protection_duration
   - Банятся все кто в Sorted Set + текущий юзер

Redis ключи:
- ar:mj:{chat_id}:joins — Sorted Set (member=user_id, score=timestamp)
- ar:mj:{chat_id}:protection — Flag с TTL что protection mode активен
"""

# Импортируем логгер для записи событий
import logging
# Импортируем типы для аннотаций
from typing import NamedTuple, Optional, List
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

class MassJoinCheckResult(NamedTuple):
    """
    Результат проверки на массовые вступления (рейд) v2.

    Attributes:
        is_raid_detected: True если рейд ТОЛЬКО ЧТО обнаружен (первый раз)
        is_protection_mode: True если protection mode активен (нужно банить юзера)
        join_count: Количество вступлений в окне
        threshold: Порог срабатывания
        window_seconds: Временное окно в секундах
        protection_remaining_seconds: Сколько секунд осталось protection mode (0 если не активен)
        recent_user_ids: Список user_id для бана (только при is_raid_detected=True)
    """
    # Флаг: рейд ТОЛЬКО ЧТО обнаружен (первый раз — нужно уведомить)
    is_raid_detected: bool
    # Флаг: protection mode активен (нужно банить текущего юзера)
    is_protection_mode: bool
    # Количество вступлений в окне
    join_count: int
    # Порог срабатывания
    threshold: int
    # Временное окно
    window_seconds: int
    # Сколько секунд осталось protection mode
    protection_remaining_seconds: int = 0
    # Список user_id для массового бана (только при is_raid_detected)
    recent_user_ids: List[int] = []


# ============================================================
# КЛАСС ТРЕКЕРА
# ============================================================

class MassJoinTracker:
    """
    Трекер массовых вступлений (рейд-детектор) v2.

    Использует Redis Sorted Set для хранения вступлений.
    При превышении порога включает protection mode.
    Во время protection mode ВСЕ новые вступления = бан.

    Пример использования:
        tracker = MassJoinTracker(redis_client)
        result = await tracker.record_and_check(
            chat_id=-100123456,
            user_id=12345,
            threshold=10,
            window_seconds=60,
            protection_duration=180
        )
        if result.is_protection_mode:
            # Банить юзера
            await ban_user(user_id)
        if result.is_raid_detected:
            # Уведомить в журнал + забанить recent_user_ids
            await send_raid_alert(result.recent_user_ids)
    """

    # Префикс для Redis ключей
    REDIS_PREFIX = "ar:mj"

    def __init__(self, redis: Redis):
        """
        Инициализация трекера.

        Args:
            redis: Клиент Redis для хранения данных
        """
        # Сохраняем ссылку на Redis клиент
        self._redis = redis

    def _get_joins_key(self, chat_id: int) -> str:
        """
        Формирует Redis ключ для Sorted Set вступлений.

        Args:
            chat_id: ID чата

        Returns:
            Ключ Redis для Sorted Set
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:joins"

    def _get_protection_key(self, chat_id: int) -> str:
        """
        Формирует Redis ключ для флага protection mode.

        Args:
            chat_id: ID чата

        Returns:
            Ключ Redis для protection flag
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:protection"

    def _get_banned_count_key(self, chat_id: int) -> str:
        """
        Формирует Redis ключ для счётчика забаненных.

        Args:
            chat_id: ID чата

        Returns:
            Ключ Redis для счётчика
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:banned"

    def _get_journal_msg_key(self, chat_id: int) -> str:
        """
        Формирует Redis ключ для ID сообщения в журнале.

        Нужен чтобы обновлять одно сообщение вместо отправки новых.

        Args:
            chat_id: ID чата

        Returns:
            Ключ Redis для message_id
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:journal_msg"

    async def is_protection_active(self, chat_id: int) -> bool:
        """
        Проверяет активен ли protection mode.

        Args:
            chat_id: ID чата

        Returns:
            True если protection mode активен
        """
        try:
            # Проверяем существует ли ключ protection
            protection_key = self._get_protection_key(chat_id)
            return await self._redis.exists(protection_key) > 0
        except Exception as e:
            # При ошибке Redis — считаем что protection НЕ активен
            # (безопаснее не банить чем банить по ошибке)
            logger.error(f"[MassJoinTracker] Ошибка проверки protection: {e}")
            return False

    async def get_protection_ttl(self, chat_id: int) -> int:
        """
        Получает оставшееся время protection mode в секундах.

        Args:
            chat_id: ID чата

        Returns:
            Оставшееся время в секундах (0 если не активен)
        """
        try:
            protection_key = self._get_protection_key(chat_id)
            ttl = await self._redis.ttl(protection_key)
            # TTL возвращает -2 если ключ не существует, -1 если без TTL
            return max(0, ttl)
        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка получения TTL: {e}")
            return 0

    async def activate_protection(
        self,
        chat_id: int,
        duration_seconds: int = 180
    ) -> None:
        """
        Активирует protection mode.

        Args:
            chat_id: ID чата
            duration_seconds: Длительность protection mode в секундах
        """
        try:
            protection_key = self._get_protection_key(chat_id)

            # Устанавливаем флаг с TTL
            await self._redis.setex(protection_key, duration_seconds, "1")

            logger.warning(
                f"[MassJoinTracker] 🛡️ PROTECTION MODE АКТИВИРОВАН: "
                f"chat_id={chat_id}, duration={duration_seconds}s"
            )

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка активации protection: {e}")

    async def deactivate_protection(self, chat_id: int) -> None:
        """
        Деактивирует protection mode вручную.

        Args:
            chat_id: ID чата
        """
        try:
            protection_key = self._get_protection_key(chat_id)
            joins_key = self._get_joins_key(chat_id)
            banned_key = self._get_banned_count_key(chat_id)
            journal_key = self._get_journal_msg_key(chat_id)

            # Удаляем все ключи
            await self._redis.delete(protection_key, joins_key, banned_key, journal_key)

            logger.info(f"[MassJoinTracker] Protection mode снят: chat_id={chat_id}")

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка деактивации protection: {e}")

    async def increment_banned_count(self, chat_id: int, count: int = 1) -> int:
        """
        Увеличивает счётчик забаненных при рейде.

        Args:
            chat_id: ID чата
            count: На сколько увеличить (по умолчанию 1)

        Returns:
            Новое значение счётчика
        """
        try:
            banned_key = self._get_banned_count_key(chat_id)

            # Инкрементируем счётчик
            new_count = await self._redis.incrby(banned_key, count)

            # TTL = 10 минут (достаточно для рейда)
            await self._redis.expire(banned_key, 600)

            return new_count

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка increment_banned_count: {e}")
            return 0

    async def get_banned_count(self, chat_id: int) -> int:
        """
        Получает текущий счётчик забаненных.

        Args:
            chat_id: ID чата

        Returns:
            Количество забаненных (0 если счётчик не существует)
        """
        try:
            banned_key = self._get_banned_count_key(chat_id)
            value = await self._redis.get(banned_key)
            return int(value) if value else 0

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка get_banned_count: {e}")
            return 0

    async def set_journal_message_id(self, chat_id: int, message_id: int) -> None:
        """
        Сохраняет ID сообщения в журнале для обновления.

        Args:
            chat_id: ID чата
            message_id: ID сообщения в журнале
        """
        try:
            journal_key = self._get_journal_msg_key(chat_id)
            await self._redis.setex(journal_key, 600, str(message_id))

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка set_journal_message_id: {e}")

    async def get_journal_message_id(self, chat_id: int) -> Optional[int]:
        """
        Получает ID сообщения в журнале.

        Args:
            chat_id: ID чата

        Returns:
            message_id или None если не сохранён
        """
        try:
            journal_key = self._get_journal_msg_key(chat_id)
            value = await self._redis.get(journal_key)
            return int(value) if value else None

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка get_journal_message_id: {e}")
            return None

    async def record_join(
        self,
        chat_id: int,
        user_id: int,
        window_seconds: int = 60
    ) -> int:
        """
        Записывает вступление пользователя в Sorted Set.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            window_seconds: Временное окно

        Returns:
            Текущее количество вступлений в окне
        """
        joins_key = self._get_joins_key(chat_id)
        now = time.time()

        try:
            # ─────────────────────────────────────────────────────────
            # ШАГ 1: Добавляем вступление в Sorted Set
            # member = user_id, score = timestamp
            # ─────────────────────────────────────────────────────────
            await self._redis.zadd(joins_key, {str(user_id): now})

            # ─────────────────────────────────────────────────────────
            # ШАГ 2: Удаляем старые записи (за пределами окна)
            # ─────────────────────────────────────────────────────────
            cutoff = now - window_seconds
            await self._redis.zremrangebyscore(joins_key, "-inf", cutoff)

            # ─────────────────────────────────────────────────────────
            # ШАГ 3: Устанавливаем TTL на ключ
            # ─────────────────────────────────────────────────────────
            await self._redis.expire(joins_key, window_seconds + 60)

            # ─────────────────────────────────────────────────────────
            # ШАГ 4: Считаем количество в окне
            # ─────────────────────────────────────────────────────────
            count = await self._redis.zcount(joins_key, cutoff, "+inf")

            return count

        except Exception as e:
            logger.error(
                f"[MassJoinTracker] Ошибка записи вступления: {e}, "
                f"chat_id={chat_id}, user_id={user_id}"
            )
            return 0

    async def get_recent_user_ids(
        self,
        chat_id: int,
        window_seconds: int = 60,
        limit: int = 100
    ) -> List[int]:
        """
        Получает список user_id недавно вступивших (для массового бана).

        Args:
            chat_id: ID чата
            window_seconds: Временное окно
            limit: Максимальное количество

        Returns:
            Список user_id
        """
        joins_key = self._get_joins_key(chat_id)
        now = time.time()
        cutoff = now - window_seconds

        try:
            # Получаем все записи в окне (от старых к новым)
            members = await self._redis.zrangebyscore(
                joins_key, cutoff, "+inf", start=0, num=limit
            )

            # Преобразуем в список int
            user_ids = []
            for member in members:
                try:
                    user_ids.append(int(member))
                except ValueError:
                    pass

            return user_ids

        except Exception as e:
            logger.error(f"[MassJoinTracker] Ошибка get_recent_user_ids: {e}")
            return []

    async def record_and_check(
        self,
        chat_id: int,
        user_id: int,
        threshold: int = 10,
        window_seconds: int = 60,
        protection_duration: int = 180
    ) -> MassJoinCheckResult:
        """
        Записывает вступление и проверяет на рейд.

        Это ГЛАВНАЯ функция для использования.

        ЛОГИКА v2:
        1. Проверяем активен ли protection mode
        2. Если ДА → is_protection_mode=True (нужно банить юзера)
        3. Записываем вступление
        4. Если count >= threshold И protection НЕ был активен:
           - is_raid_detected=True (первое обнаружение)
           - Активируем protection mode
           - Возвращаем recent_user_ids для массового бана

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            threshold: Порог срабатывания
            window_seconds: Временное окно в секундах
            protection_duration: Длительность protection mode в секундах

        Returns:
            MassJoinCheckResult с результатом проверки
        """
        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Проверяем активен ли protection mode
        # ─────────────────────────────────────────────────────────
        protection_was_active = await self.is_protection_active(chat_id)
        protection_ttl = await self.get_protection_ttl(chat_id) if protection_was_active else 0

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Записываем вступление и получаем count
        # ─────────────────────────────────────────────────────────
        join_count = await self.record_join(
            chat_id=chat_id,
            user_id=user_id,
            window_seconds=window_seconds
        )

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Определяем is_raid_detected
        # Рейд обнаружен ТОЛЬКО если:
        # - count >= threshold
        # - protection НЕ был активен до этого
        # ─────────────────────────────────────────────────────────
        is_raid_detected = join_count >= threshold and not protection_was_active

        # ─────────────────────────────────────────────────────────
        # ШАГ 4: Если рейд обнаружен — активируем protection
        # ─────────────────────────────────────────────────────────
        recent_user_ids: List[int] = []

        if is_raid_detected:
            # Активируем protection mode
            await self.activate_protection(chat_id, protection_duration)

            # Получаем список всех юзеров для бана
            recent_user_ids = await self.get_recent_user_ids(
                chat_id, window_seconds, limit=100
            )

            logger.warning(
                f"[MassJoinTracker] 🚨 РЕЙД ОБНАРУЖЕН! "
                f"chat_id={chat_id}, "
                f"joins={join_count} >= {threshold}, "
                f"window={window_seconds}s, "
                f"protection={protection_duration}s, "
                f"users_to_ban={len(recent_user_ids)}"
            )

        # ─────────────────────────────────────────────────────────
        # ШАГ 5: Определяем is_protection_mode
        # Protection mode активен ЕСЛИ:
        # - protection БЫЛ активен до вступления
        # - ИЛИ рейд только что обнаружен
        # ─────────────────────────────────────────────────────────
        is_protection_mode = protection_was_active or is_raid_detected

        # Логирование
        if is_protection_mode and not is_raid_detected:
            logger.debug(
                f"[MassJoinTracker] Protection mode активен, "
                f"user_id={user_id} будет забанен, "
                f"remaining={protection_ttl}s"
            )
        elif not is_protection_mode:
            logger.debug(
                f"[MassJoinTracker] Вступление записано: "
                f"count={join_count}/{threshold}"
            )

        return MassJoinCheckResult(
            is_raid_detected=is_raid_detected,
            is_protection_mode=is_protection_mode,
            join_count=join_count,
            threshold=threshold,
            window_seconds=window_seconds,
            protection_remaining_seconds=protection_ttl if protection_was_active else protection_duration if is_raid_detected else 0,
            recent_user_ids=recent_user_ids
        )


# ============================================================
# ФУНКЦИИ ДЛЯ ИСПОЛЬЗОВАНИЯ В КООРДИНАТОРЕ
# ============================================================

async def check_mass_join(
    redis: Redis,
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> Optional[MassJoinCheckResult]:
    """
    Проверяет массовые вступления с учётом настроек группы.

    Это ГЛАВНАЯ функция для вызова из координатора.
    Автоматически читает настройки группы из БД.

    Args:
        redis: Клиент Redis
        session: Сессия SQLAlchemy
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        MassJoinCheckResult если включено, None если выключено
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или mass_join выключен — пропускаем
    if settings is None or not settings.mass_join_enabled:
        logger.debug(
            f"[MassJoinTracker] Mass Join отключён для chat_id={chat_id}"
        )
        return None

    # ─────────────────────────────────────────────────────────
    # Создаём трекер и проверяем
    # ─────────────────────────────────────────────────────────
    tracker = MassJoinTracker(redis)

    result = await tracker.record_and_check(
        chat_id=chat_id,
        user_id=user_id,
        threshold=settings.mass_join_threshold,
        window_seconds=settings.mass_join_window,
        protection_duration=settings.mass_join_protection_duration
    )

    return result


async def is_protection_active(redis: Redis, chat_id: int) -> bool:
    """
    Проверяет активен ли protection mode для группы.

    Args:
        redis: Клиент Redis
        chat_id: ID чата

    Returns:
        True если protection mode активен
    """
    tracker = MassJoinTracker(redis)
    return await tracker.is_protection_active(chat_id)


async def deactivate_protection(redis: Redis, chat_id: int) -> None:
    """
    Деактивирует protection mode вручную.

    Args:
        redis: Клиент Redis
        chat_id: ID чата
    """
    tracker = MassJoinTracker(redis)
    await tracker.deactivate_protection(chat_id)


async def get_protection_ttl(redis: Redis, chat_id: int) -> int:
    """
    Получает оставшееся время protection mode.

    Args:
        redis: Клиент Redis
        chat_id: ID чата

    Returns:
        Оставшееся время в секундах
    """
    tracker = MassJoinTracker(redis)
    return await tracker.get_protection_ttl(chat_id)


async def activate_protection(
    redis: Redis,
    session: AsyncSession,
    chat_id: int
) -> int:
    """
    Активирует protection mode и возвращает auto_unlock_minutes из настроек.

    Это обёртка для использования в хендлерах.

    Args:
        redis: Клиент Redis
        session: Сессия SQLAlchemy
        chat_id: ID чата

    Returns:
        Значение auto_unlock из настроек (минуты)
    """
    # Получаем настройки
    settings = await get_antiraid_settings(session, chat_id)
    if settings is None:
        return 0

    # Активируем protection mode с длительностью из настроек
    tracker = MassJoinTracker(redis)
    await tracker.activate_protection(
        chat_id=chat_id,
        duration_seconds=settings.mass_join_protection_duration
    )

    # Возвращаем auto_unlock для журнала
    return settings.mass_join_auto_unlock


# Алиас для обратной совместимости
activate_raid_mode = activate_protection


# ============================================================
# ФАБРИЧНАЯ ФУНКЦИЯ
# ============================================================

def create_mass_join_tracker(redis: Redis) -> MassJoinTracker:
    """
    Создаёт экземпляр MassJoinTracker.

    Args:
        redis: Клиент Redis

    Returns:
        Экземпляр MassJoinTracker
    """
    return MassJoinTracker(redis)