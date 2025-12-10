# ============================================================
# FLOOD DETECTOR - ДЕТЕКТОР ФЛУДА (ПОВТОРЯЮЩИХСЯ СООБЩЕНИЙ)
# ============================================================
# Этот модуль определяет флуд — повторяющиеся одинаковые
# или похожие сообщения от одного пользователя.
#
# Алгоритм:
# 1. Вычисляем хэш текста сообщения
# 2. Сохраняем хэш в Redis с TTL
# 3. Сравниваем с предыдущими хэшами пользователя
# 4. Если повторов >= порога — это флуд
#
# Redis ключи:
# - cf:flood:{chat_id}:{user_id}:messages — List последних хэшей
# - cf:flood:{chat_id}:{user_id}:count:{hash} — Счётчик повторов
# ============================================================

# Импортируем hashlib для хэширования
import hashlib
# Импортируем типы для аннотаций
from typing import Optional, NamedTuple, List
# Импортируем логгер
import logging
# Импортируем json для сериализации
import json

# Импортируем Redis клиент
from redis.asyncio import Redis

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ
# ============================================================

class FloodCheckResult(NamedTuple):
    """
    Результат проверки на флуд.

    Attributes:
        is_flood: True если обнаружен флуд
        repeat_count: Количество повторов этого сообщения
        max_allowed: Максимально допустимое количество повторов
        message_hash: Хэш проверенного сообщения
        flood_message_ids: Список ID всех сообщений для удаления (при флуде)
    """
    # Флаг: является ли это флудом
    is_flood: bool
    # Количество повторов
    repeat_count: int
    # Максимально допустимое
    max_allowed: int
    # Хэш сообщения (для логирования)
    message_hash: str
    # ID сообщений для удаления при флуде (включая текущее)
    flood_message_ids: List[int] = []


# ============================================================
# КЛАСС ДЕТЕКТОРА ФЛУДА
# ============================================================

class FloodDetector:
    """
    Детектор флуда (повторяющихся сообщений).

    Использует Redis для хранения истории сообщений пользователя.
    Определяет флуд по количеству повторений одинакового текста
    в заданном временном окне.

    Пример использования:
        detector = FloodDetector(redis_client)
        result = await detector.check(
            text="Спам спам спам",
            chat_id=-100123456,
            user_id=12345,
            max_repeats=2,
            time_window=60
        )
        if result.is_flood:
            print(f"Флуд! Повторов: {result.repeat_count}")
    """

    # Префикс для Redis ключей
    REDIS_PREFIX = "cf:flood"
    # Максимальное количество хэшей для хранения на пользователя
    MAX_HISTORY_SIZE = 10

    def __init__(self, redis: Redis):
        """
        Инициализация детектора флуда.

        Args:
            redis: Клиент Redis для хранения истории сообщений
        """
        # Сохраняем ссылку на Redis клиент
        self._redis = redis

    def _compute_hash(self, text: str) -> str:
        """
        Вычисляет хэш текста сообщения.

        Используем MD5 — он достаточно быстрый для нашей задачи,
        криптографическая стойкость здесь не нужна.

        Args:
            text: Текст сообщения

        Returns:
            Хэш в виде строки (первые 16 символов)
        """
        # Нормализуем текст: убираем пробелы по краям, приводим к нижнему регистру
        normalized = text.strip().lower()
        # Вычисляем MD5 хэш
        hash_obj = hashlib.md5(normalized.encode('utf-8'))
        # Возвращаем первые 16 символов (достаточно для идентификации)
        return hash_obj.hexdigest()[:16]

    def _get_count_key(self, chat_id: int, user_id: int, msg_hash: str) -> str:
        """
        Формирует Redis ключ для счётчика повторов.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            msg_hash: Хэш сообщения

        Returns:
            Ключ Redis
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:count:{msg_hash}"

    def _get_history_key(self, chat_id: int, user_id: int) -> str:
        """
        Формирует Redis ключ для истории сообщений.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Ключ Redis
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:history"

    def _get_messages_key(self, chat_id: int, user_id: int, msg_hash: str) -> str:
        """
        Формирует Redis ключ для хранения ID сообщений с данным хэшем.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            msg_hash: Хэш сообщения

        Returns:
            Ключ Redis
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:msgs:{msg_hash}"

    async def check(
        self,
        text: str,
        chat_id: int,
        user_id: int,
        message_id: int,
        max_repeats: int = 2,
        time_window: int = 60
    ) -> FloodCheckResult:
        """
        Проверяет сообщение на флуд.

        Args:
            text: Текст сообщения
            chat_id: ID чата
            user_id: ID пользователя
            message_id: ID сообщения (для удаления всех при флуде)
            max_repeats: Максимальное количество повторов (по умолчанию 2)
            time_window: Временное окно в секундах (по умолчанию 60)

        Returns:
            FloodCheckResult с результатом проверки и списком ID сообщений
        """
        # Проверяем на пустой текст
        if not text or not text.strip():
            # Пустой текст не считается флудом
            return FloodCheckResult(
                is_flood=False,
                repeat_count=0,
                max_allowed=max_repeats,
                message_hash="",
                flood_message_ids=[]
            )

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Вычисляем хэш сообщения
        # ─────────────────────────────────────────────────────────
        msg_hash = self._compute_hash(text)

        # Ключи Redis
        count_key = self._get_count_key(chat_id, user_id, msg_hash)
        messages_key = self._get_messages_key(chat_id, user_id, msg_hash)

        try:
            # ─────────────────────────────────────────────────────────
            # ШАГ 2: Инкрементируем счётчик и сохраняем message_id
            # ─────────────────────────────────────────────────────────
            # Инкрементируем счётчик
            current_count = await self._redis.incr(count_key)

            # Добавляем message_id в список сообщений с этим хэшем
            await self._redis.rpush(messages_key, str(message_id))

            # Устанавливаем TTL при первом создании ключей
            if current_count == 1:
                await self._redis.expire(count_key, time_window)
                await self._redis.expire(messages_key, time_window)

            # ─────────────────────────────────────────────────────────
            # ШАГ 3: Проверяем превышение порога
            # ─────────────────────────────────────────────────────────
            is_flood = current_count > max_repeats
            flood_message_ids = []

            if is_flood:
                # Получаем ВСЕ ID сообщений для удаления
                all_msg_ids = await self._redis.lrange(messages_key, 0, -1)
                flood_message_ids = [int(mid) for mid in all_msg_ids if mid]

                # Очищаем список сообщений после получения (чтобы не удалять повторно)
                await self._redis.delete(messages_key)
                # Сбрасываем счётчик
                await self._redis.delete(count_key)

                logger.info(
                    f"[FloodDetector] Обнаружен флуд! "
                    f"chat={chat_id}, user={user_id}, "
                    f"count={current_count} > {max_repeats}, "
                    f"hash={msg_hash}, messages_to_delete={len(flood_message_ids)}"
                )
            else:
                logger.debug(
                    f"[FloodDetector] Не флуд. "
                    f"count={current_count} <= {max_repeats}"
                )

            # Возвращаем результат
            return FloodCheckResult(
                is_flood=is_flood,
                repeat_count=current_count,
                max_allowed=max_repeats,
                message_hash=msg_hash,
                flood_message_ids=flood_message_ids
            )

        except Exception as e:
            # Логируем ошибку Redis
            logger.error(
                f"[FloodDetector] Ошибка Redis: {e}, "
                f"chat={chat_id}, user={user_id}"
            )
            # При ошибке Redis не блокируем сообщение
            return FloodCheckResult(
                is_flood=False,
                repeat_count=0,
                max_allowed=max_repeats,
                message_hash=msg_hash,
                flood_message_ids=[]
            )

    async def check_any_messages(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        max_messages: int = 5,
        time_window: int = 10
    ) -> FloodCheckResult:
        """
        Проверяет флуд по количеству любых сообщений (не только одинаковых).

        Считает количество сообщений от пользователя за временное окно,
        независимо от их содержимого.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            message_id: ID сообщения
            max_messages: Максимум сообщений за время (по умолчанию 5)
            time_window: Временное окно в секундах (по умолчанию 10)

        Returns:
            FloodCheckResult с результатом проверки
        """
        # Ключ для счётчика любых сообщений
        any_count_key = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:any:count"
        any_messages_key = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:any:msgs"

        try:
            # Инкрементируем счётчик
            current_count = await self._redis.incr(any_count_key)

            # Добавляем message_id в список
            await self._redis.rpush(any_messages_key, str(message_id))

            # Устанавливаем TTL при первом создании
            if current_count == 1:
                await self._redis.expire(any_count_key, time_window)
                await self._redis.expire(any_messages_key, time_window)

            # Проверяем превышение порога
            is_flood = current_count > max_messages
            flood_message_ids = []

            if is_flood:
                # Получаем все ID сообщений для удаления
                all_msg_ids = await self._redis.lrange(any_messages_key, 0, -1)
                flood_message_ids = [int(mid) for mid in all_msg_ids if mid]

                # Очищаем после получения
                await self._redis.delete(any_messages_key)
                await self._redis.delete(any_count_key)

                logger.info(
                    f"[FloodDetector] Обнаружен флуд (любые сообщения)! "
                    f"chat={chat_id}, user={user_id}, "
                    f"count={current_count} > {max_messages}, "
                    f"messages_to_delete={len(flood_message_ids)}"
                )
            else:
                logger.debug(
                    f"[FloodDetector] Не флуд (любые). "
                    f"count={current_count} <= {max_messages}"
                )

            return FloodCheckResult(
                is_flood=is_flood,
                repeat_count=current_count,
                max_allowed=max_messages,
                message_hash="any",
                flood_message_ids=flood_message_ids
            )

        except Exception as e:
            logger.error(f"[FloodDetector] Ошибка Redis (any): {e}")
            return FloodCheckResult(
                is_flood=False,
                repeat_count=0,
                max_allowed=max_messages,
                message_hash="any",
                flood_message_ids=[]
            )

    async def check_media(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        media_type: str,
        max_repeats: int = 2,
        time_window: int = 60
    ) -> FloodCheckResult:
        """
        Проверяет медиа-флуд (фото, стикеры, видео, войсы).

        Считает количество медиа одного типа от пользователя.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            message_id: ID сообщения
            media_type: Тип медиа (photo, sticker, video, voice, video_note)
            max_repeats: Максимум медиа одного типа (по умолчанию 2)
            time_window: Временное окно в секундах (по умолчанию 60)

        Returns:
            FloodCheckResult с результатом проверки
        """
        # Ключ для счётчика медиа определённого типа
        media_count_key = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:media:{media_type}:count"
        media_messages_key = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:media:{media_type}:msgs"

        try:
            # Инкрементируем счётчик
            current_count = await self._redis.incr(media_count_key)

            # Добавляем message_id в список
            await self._redis.rpush(media_messages_key, str(message_id))

            # Устанавливаем TTL при первом создании
            if current_count == 1:
                await self._redis.expire(media_count_key, time_window)
                await self._redis.expire(media_messages_key, time_window)

            # Проверяем превышение порога
            is_flood = current_count > max_repeats
            flood_message_ids = []

            if is_flood:
                # Получаем все ID сообщений для удаления
                all_msg_ids = await self._redis.lrange(media_messages_key, 0, -1)
                flood_message_ids = [int(mid) for mid in all_msg_ids if mid]

                # Очищаем после получения
                await self._redis.delete(media_messages_key)
                await self._redis.delete(media_count_key)

                logger.info(
                    f"[FloodDetector] Обнаружен медиа-флуд ({media_type})! "
                    f"chat={chat_id}, user={user_id}, "
                    f"count={current_count} > {max_repeats}, "
                    f"messages_to_delete={len(flood_message_ids)}"
                )
            else:
                logger.debug(
                    f"[FloodDetector] Не медиа-флуд ({media_type}). "
                    f"count={current_count} <= {max_repeats}"
                )

            return FloodCheckResult(
                is_flood=is_flood,
                repeat_count=current_count,
                max_allowed=max_repeats,
                message_hash=f"media:{media_type}",
                flood_message_ids=flood_message_ids
            )

        except Exception as e:
            logger.error(f"[FloodDetector] Ошибка Redis (media): {e}")
            return FloodCheckResult(
                is_flood=False,
                repeat_count=0,
                max_allowed=max_repeats,
                message_hash=f"media:{media_type}",
                flood_message_ids=[]
            )

    async def reset_user_history(
        self,
        chat_id: int,
        user_id: int
    ) -> bool:
        """
        Сбрасывает историю флуда для пользователя.

        Полезно при размуте или по команде админа.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            True если успешно
        """
        try:
            # Формируем паттерн для поиска всех ключей пользователя
            pattern = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:*"

            # Получаем все ключи по паттерну
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            # Удаляем все найденные ключи
            if keys:
                await self._redis.delete(*keys)
                logger.info(
                    f"[FloodDetector] Сброшена история: "
                    f"chat={chat_id}, user={user_id}, keys={len(keys)}"
                )

            return True

        except Exception as e:
            logger.error(f"[FloodDetector] Ошибка сброса истории: {e}")
            return False

    async def get_user_stats(
        self,
        chat_id: int,
        user_id: int
    ) -> dict:
        """
        Получает статистику флуда пользователя.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Словарь со статистикой
        """
        try:
            # Формируем паттерн для поиска
            pattern = f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:count:*"

            # Собираем статистику
            stats = {
                'unique_messages': 0,
                'total_repeats': 0,
                'hashes': []
            }

            # Получаем все ключи счётчиков
            async for key in self._redis.scan_iter(match=pattern):
                # Получаем значение счётчика
                count = await self._redis.get(key)
                if count:
                    # Увеличиваем статистику
                    stats['unique_messages'] += 1
                    stats['total_repeats'] += int(count)
                    # Извлекаем хэш из ключа
                    hash_part = key.decode() if isinstance(key, bytes) else key
                    stats['hashes'].append(hash_part.split(':')[-1])

            return stats

        except Exception as e:
            logger.error(f"[FloodDetector] Ошибка получения статистики: {e}")
            return {'error': str(e)}


# ============================================================
# ФАБРИЧНАЯ ФУНКЦИЯ
# ============================================================

def create_flood_detector(redis: Redis) -> FloodDetector:
    """
    Создаёт экземпляр FloodDetector.

    Args:
        redis: Клиент Redis

    Returns:
        Экземпляр FloodDetector
    """
    return FloodDetector(redis)
