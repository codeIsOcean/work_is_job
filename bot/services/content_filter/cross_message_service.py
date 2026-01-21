# ============================================================
# CROSS-MESSAGE DETECTOR — ДЕТЕКТОР НАКОПЛЕННОГО СКОРА
# ============================================================
# Этот модуль накапливает скор паттернов через несколько сообщений.
# Позволяет ловить спаммеров которые разбивают спам на части.
#
# Алгоритм:
# 1. Каждое сообщение проверяется через ContentFilter
# 2. Если score < threshold раздела — сообщение НЕ блокируется
# 3. Но score накапливается в Redis: cross_msg:{chat_id}:{user_id}
# 4. Когда накопленный score >= cross_message_threshold → применяется действие
#
# Redis ключи:
# - cross_msg:{chat_id}:{user_id}:score — накопленный скор (с TTL)
# - cross_msg:{chat_id}:{user_id}:history — история сообщений (для журнала)
#
# Пример использования:
#     service = CrossMessageService(redis)
#     # Добавляем скор после проверки ContentFilter
#     result = await service.add_score(
#         chat_id=-100123456,
#         user_id=12345,
#         score=35,
#         window_seconds=7200,  # 2 часа
#         threshold=100,
#         message_preview="Часть спама..."
#     )
#     if result.threshold_exceeded:
#         # Применить действие (mute/ban)
#         pass
# ============================================================

# Импортируем типы для аннотаций
from typing import Optional, NamedTuple, List
# Импортируем json для сериализации истории сообщений
import json
# Импортируем логгер
import logging
# Импортируем datetime для временных меток
from datetime import datetime
# Импортируем re для regex паттернов
import re

# Импортируем Redis клиент
from redis.asyncio import Redis

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модели паттернов и порогов
from bot.database.models_content_filter import CrossMessagePattern, CrossMessageThreshold

# Импортируем нормализатор текста (общий)
from bot.services.content_filter.text_normalizer import get_normalizer

# Импортируем функции fuzzy/ngram matching (общие из scam_detector)
from bot.services.content_filter.scam_detector import fuzzy_match, extract_ngrams, ngram_match

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ
# ============================================================

class CrossMessageResult(NamedTuple):
    """
    Результат добавления скора к накопленному.

    Attributes:
        threshold_exceeded: True если накопленный скор превысил порог
        total_score: Текущий накопленный скор
        threshold: Порог срабатывания
        messages_count: Количество сообщений в накоплении
        history: История сообщений (preview для журнала)
        message_ids: Список ID сообщений для удаления
    """
    # Флаг: превышен ли порог
    threshold_exceeded: bool
    # Текущий накопленный скор
    total_score: int
    # Порог который был проверен
    threshold: int
    # Количество сообщений в накоплении
    messages_count: int
    # История сообщений (для журнала): [{'score': int, 'preview': str, 'ts': str, 'msg_id': int}, ...]
    history: List[dict] = []
    # Список ID сообщений для удаления (NEW!)
    message_ids: List[int] = []


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ ПАТТЕРНОВ
# ============================================================

class CrossMessageCheckResult(NamedTuple):
    """
    Результат проверки текста по кросс-сообщение паттернам.

    Attributes:
        score: Скор текущего сообщения (сумма весов сработавших паттернов)
        matched_patterns: Список сработавших паттернов
        total_score: Общий накопленный скор (включая предыдущие сообщения)
        threshold_exceeded: True если накопленный скор превысил порог
        message_ids: Список ID сообщений для удаления (при срабатывании)
    """
    # Скор текущего сообщения (только от этого сообщения)
    score: int
    # Список сработавших паттернов: [{'pattern': str, 'weight': int, 'method': str}, ...]
    matched_patterns: List[dict] = []
    # Общий накопленный скор (включая предыдущие)
    total_score: int = 0
    # Флаг: превышен ли порог
    threshold_exceeded: bool = False
    # Список ID сообщений для удаления
    message_ids: List[int] = []


# ============================================================
# КЛАСС СЕРВИСА КРОСС-СООБЩЕНИЕ ДЕТЕКЦИИ
# ============================================================

class CrossMessageService:
    """
    Сервис накопления скора через несколько сообщений.

    Использует Redis для хранения накопленного скора с TTL.
    Когда скор превышает порог — сигнализирует о необходимости
    применить действие (mute/ban).

    Пример использования:
        service = CrossMessageService(redis)
        result = await service.add_score(
            chat_id=-100123456,
            user_id=12345,
            score=35,
            window_seconds=7200,
            threshold=100,
            message_preview="Спам сообщение..."
        )
        if result.threshold_exceeded:
            # Применить mute/ban
            pass
    """

    # Префикс для Redis ключей
    REDIS_PREFIX = "cross_msg"
    # Максимальное количество сообщений в истории
    MAX_HISTORY_SIZE = 20

    def __init__(self, redis: Redis):
        """
        Инициализация сервиса.

        Args:
            redis: Клиент Redis для хранения скора и истории
        """
        # Сохраняем ссылку на Redis клиент
        self._redis = redis

    def _get_score_key(self, chat_id: int, user_id: int) -> str:
        """
        Формирует Redis ключ для накопленного скора.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Ключ Redis в формате: cross_msg:{chat_id}:{user_id}:score
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:score"

    def _get_history_key(self, chat_id: int, user_id: int) -> str:
        """
        Формирует Redis ключ для истории сообщений.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Ключ Redis в формате: cross_msg:{chat_id}:{user_id}:history
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:history"

    def _get_messages_key(self, chat_id: int, user_id: int) -> str:
        """
        Формирует Redis ключ для списка ID сообщений (для удаления).

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Ключ Redis в формате: cross_msg:{chat_id}:{user_id}:messages
        """
        return f"{self.REDIS_PREFIX}:{chat_id}:{user_id}:messages"

    async def add_score(
        self,
        chat_id: int,
        user_id: int,
        score: int,
        window_seconds: int,
        threshold: int,
        message_preview: str = "",
        section_name: str = "",
        message_id: int = 0
    ) -> CrossMessageResult:
        """
        Добавляет скор к накопленному и проверяет порог.

        Если накопленный скор превышает threshold — возвращает
        threshold_exceeded=True для применения действия.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            score: Скор текущего сообщения (из ContentFilter)
            window_seconds: Временное окно накопления в секундах
            threshold: Порог срабатывания
            message_preview: Превью сообщения для истории (первые 100 символов)
            section_name: Название раздела где сработал паттерн
            message_id: ID сообщения (для последующего удаления)

        Returns:
            CrossMessageResult с информацией о накопленном скоре
        """
        # Если скор 0 или отрицательный — пропускаем
        if score <= 0:
            return CrossMessageResult(
                threshold_exceeded=False,
                total_score=0,
                threshold=threshold,
                messages_count=0,
                history=[],
                message_ids=[]
            )

        # Формируем ключи Redis
        score_key = self._get_score_key(chat_id, user_id)
        history_key = self._get_history_key(chat_id, user_id)
        messages_key = self._get_messages_key(chat_id, user_id)

        # Получаем текущий накопленный скор
        current_score_raw = await self._redis.get(score_key)
        current_score = int(current_score_raw) if current_score_raw else 0

        # Добавляем новый скор
        new_total = current_score + score

        # Сохраняем новый скор с TTL
        # ВАЖНО: setex устанавливает TTL при каждом обновлении
        # Это значит что окно "сдвигается" с каждым сообщением
        await self._redis.setex(score_key, window_seconds, str(new_total))

        # ─────────────────────────────────────────────────────────
        # Добавляем запись в историю сообщений
        # ─────────────────────────────────────────────────────────
        # Формируем запись истории (теперь включает message_id и полный текст)
        history_entry = {
            'score': score,
            # Полный текст сообщения (до 500 символов для журнала)
            'text': message_preview[:500] if message_preview else '',
            # Короткое превью для компактного отображения
            'preview': message_preview[:100] if message_preview else '',
            'section': section_name,
            'ts': datetime.utcnow().isoformat(),
            'msg_id': message_id  # ID сообщения для удаления
        }

        # Добавляем в список (RPUSH) и обрезаем до MAX_HISTORY_SIZE (LTRIM)
        await self._redis.rpush(history_key, json.dumps(history_entry))
        await self._redis.ltrim(history_key, -self.MAX_HISTORY_SIZE, -1)
        # Устанавливаем TTL для истории (такой же как для скора)
        await self._redis.expire(history_key, window_seconds)

        # ─────────────────────────────────────────────────────────
        # Сохраняем message_id для последующего удаления
        # ─────────────────────────────────────────────────────────
        # Храним ID сообщений отдельно для быстрого доступа при удалении
        if message_id > 0:
            # Добавляем ID сообщения в SET (уникальные значения)
            await self._redis.sadd(messages_key, str(message_id))
            # Устанавливаем TTL для списка сообщений
            await self._redis.expire(messages_key, window_seconds)

        # Получаем всю историю для возврата
        history_raw = await self._redis.lrange(history_key, 0, -1)
        history = []
        for entry in history_raw:
            try:
                history.append(json.loads(entry))
            except json.JSONDecodeError:
                pass

        # Получаем список ID сообщений для возврата
        message_ids_raw = await self._redis.smembers(messages_key)
        message_ids = [int(mid) for mid in message_ids_raw if mid.isdigit()]

        # Логируем добавление скора
        logger.info(
            f"[CrossMessageService] add_score: chat={chat_id}, user={user_id}, "
            f"+{score} баллов, total={new_total}/{threshold}, "
            f"messages={len(history)}, msg_id={message_id}"
        )

        # Проверяем превышение порога
        threshold_exceeded = new_total >= threshold

        if threshold_exceeded:
            logger.warning(
                f"[CrossMessageService] ПОРОГ ПРЕВЫШЕН: chat={chat_id}, user={user_id}, "
                f"total={new_total} >= threshold={threshold}, "
                f"сообщений в накоплении={len(history)}, "
                f"message_ids для удаления: {message_ids}"
            )

        return CrossMessageResult(
            threshold_exceeded=threshold_exceeded,
            total_score=new_total,
            threshold=threshold,
            messages_count=len(history),
            history=history,
            message_ids=message_ids
        )

    async def get_score(
        self,
        chat_id: int,
        user_id: int
    ) -> int:
        """
        Получает текущий накопленный скор пользователя.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Накопленный скор (0 если нет данных)
        """
        # Формируем ключ Redis
        score_key = self._get_score_key(chat_id, user_id)

        # Получаем значение
        score_raw = await self._redis.get(score_key)

        # Возвращаем int или 0
        return int(score_raw) if score_raw else 0

    async def get_history(
        self,
        chat_id: int,
        user_id: int
    ) -> List[dict]:
        """
        Получает историю сообщений пользователя.

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            Список записей: [{'score': int, 'preview': str, 'ts': str}, ...]
        """
        # Формируем ключ Redis
        history_key = self._get_history_key(chat_id, user_id)

        # Получаем все записи
        history_raw = await self._redis.lrange(history_key, 0, -1)

        # Парсим JSON
        history = []
        for entry in history_raw:
            try:
                history.append(json.loads(entry))
            except json.JSONDecodeError:
                pass

        return history

    async def reset_score(
        self,
        chat_id: int,
        user_id: int
    ) -> None:
        """
        Сбрасывает накопленный скор пользователя.

        Вызывается после применения действия (mute/ban)
        чтобы не срабатывать повторно.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
        """
        # Формируем ключи Redis
        score_key = self._get_score_key(chat_id, user_id)
        history_key = self._get_history_key(chat_id, user_id)
        messages_key = self._get_messages_key(chat_id, user_id)

        # Удаляем все ключи (score, history, messages)
        await self._redis.delete(score_key, history_key, messages_key)

        logger.info(
            f"[CrossMessageService] reset_score: chat={chat_id}, user={user_id}"
        )

    # ════════════════════════════════════════════════════════════════════════
    # МЕТОДЫ ДЛЯ РАБОТЫ С ПАТТЕРНАМИ (НОВОЕ!)
    # ════════════════════════════════════════════════════════════════════════
    # Эти методы работают с ОТДЕЛЬНОЙ таблицей cross_message_patterns
    # и НЕ используют паттерны разделов (CustomSectionPattern)
    # ════════════════════════════════════════════════════════════════════════

    async def get_patterns(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = True
    ) -> List[CrossMessagePattern]:
        """
        Получает паттерны кросс-сообщений для группы.

        Args:
            chat_id: ID чата
            session: Сессия БД
            active_only: True = только активные паттерны

        Returns:
            Список CrossMessagePattern
        """
        # Формируем базовый запрос
        query = select(CrossMessagePattern).where(
            CrossMessagePattern.chat_id == chat_id
        )

        # Фильтруем только активные если нужно
        if active_only:
            query = query.where(CrossMessagePattern.is_active == True)  # noqa: E712

        # Сортируем по весу (сначала самые "тяжёлые")
        query = query.order_by(CrossMessagePattern.weight.desc())

        # Выполняем запрос
        result = await session.execute(query)

        # Возвращаем список паттернов
        return list(result.scalars().all())

    async def check_patterns(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        text: str,
        session: AsyncSession,
        window_seconds: int,
        threshold: int
    ) -> CrossMessageCheckResult:
        """
        Проверяет текст по СВОИМ паттернам кросс-сообщений.

        НЕ использует паттерны разделов (CustomSectionPattern)!
        Использует общие функции: TextNormalizer, fuzzy_match, ngram_match.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            message_id: ID сообщения (для последующего удаления)
            text: Текст сообщения для проверки
            session: Сессия БД
            window_seconds: Временное окно накопления
            threshold: Порог срабатывания

        Returns:
            CrossMessageCheckResult с информацией о скоре и срабатывании
        """
        # Если текста нет — возвращаем пустой результат
        if not text or not text.strip():
            return CrossMessageCheckResult(score=0)

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Получаем паттерны из СВОЕЙ таблицы
        # ─────────────────────────────────────────────────────────
        patterns = await self.get_patterns(chat_id, session, active_only=True)

        # Если паттернов нет — возвращаем пустой результат
        if not patterns:
            logger.debug(
                f"[CrossMessageService] check_patterns: chat={chat_id}, "
                f"паттернов нет — пропуск"
            )
            return CrossMessageCheckResult(score=0)

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Нормализуем текст (общий TextNormalizer)
        # ─────────────────────────────────────────────────────────
        normalizer = get_normalizer()
        normalized = normalizer.normalize(text).lower()

        # Предварительно извлекаем n-граммы для ngram matching
        text_bigrams = extract_ngrams(normalized, n=2)
        text_trigrams = extract_ngrams(normalized, n=3)

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Проверяем каждый паттерн
        # ─────────────────────────────────────────────────────────
        score = 0
        matched_patterns = []

        for pattern in patterns:
            matched = False
            match_method = None

            # ─────────────────────────────────────────────────────
            # МЕТОД 1: REGEX
            # ─────────────────────────────────────────────────────
            if pattern.pattern_type == 'regex':
                try:
                    # Компилируем regex с флагами
                    regex = re.compile(pattern.pattern, re.IGNORECASE | re.UNICODE)
                    # Ищем в нормализованном тексте
                    if regex.search(normalized):
                        matched = True
                        match_method = 'regex'
                    # Если не нашли — пробуем в оригинальном тексте
                    elif regex.search(text.lower()):
                        matched = True
                        match_method = 'regex'
                except re.error as e:
                    # Некорректный regex — логируем и пропускаем
                    logger.warning(
                        f"[CrossMessageService] Некорректный regex #{pattern.id}: "
                        f"'{pattern.pattern}' — ошибка: {e}"
                    )
                    continue

            # ─────────────────────────────────────────────────────
            # МЕТОД 2: WORD (как отдельное слово)
            # ─────────────────────────────────────────────────────
            elif pattern.pattern_type == 'word':
                # Ищем как отдельное слово с границами \b
                word_regex = r'\b' + re.escape(pattern.normalized) + r'\b'
                if re.search(word_regex, normalized):
                    matched = True
                    match_method = 'word'
                # Пробуем оригинальный паттерн в оригинальном тексте
                elif re.search(r'\b' + re.escape(pattern.pattern.lower()) + r'\b', text.lower()):
                    matched = True
                    match_method = 'word'

            # ─────────────────────────────────────────────────────
            # МЕТОД 3: PHRASE (подстрока + fuzzy + ngram)
            # ─────────────────────────────────────────────────────
            else:  # pattern_type == 'phrase' или дефолт
                # Точное совпадение подстроки (нормализованный)
                if pattern.normalized in normalized:
                    matched = True
                    match_method = 'phrase'
                # Точное совпадение подстроки (оригинальный)
                elif pattern.pattern.lower() in text.lower():
                    matched = True
                    match_method = 'phrase'
                # Fuzzy matching (порог 0.8) — только для длинных паттернов
                elif len(pattern.normalized) >= 5:
                    if fuzzy_match(normalized, pattern.normalized, threshold=0.8):
                        matched = True
                        match_method = 'fuzzy'
                # N-gram matching — для фраз из нескольких слов
                if not matched:
                    pattern_words = pattern.normalized.split()
                    # Биграммы для паттернов из 2+ слов
                    if len(pattern_words) >= 2:
                        pattern_bigrams = extract_ngrams(pattern.normalized, n=2)
                        if ngram_match(text_bigrams, pattern_bigrams, min_overlap=0.6):
                            matched = True
                            match_method = 'ngram'
                    # Триграммы для паттернов из 3+ слов
                    if not matched and len(pattern_words) >= 3:
                        pattern_trigrams = extract_ngrams(pattern.normalized, n=3)
                        if ngram_match(text_trigrams, pattern_trigrams, min_overlap=0.5):
                            matched = True
                            match_method = 'ngram'

            # ─────────────────────────────────────────────────────
            # Если паттерн сработал — добавляем скор
            # ─────────────────────────────────────────────────────
            if matched:
                score += pattern.weight
                matched_patterns.append({
                    'pattern': pattern.pattern,
                    'weight': pattern.weight,
                    'method': match_method
                })

                # Увеличиваем счётчик срабатываний (асинхронно)
                pattern.triggers_count += 1
                pattern.last_triggered_at = datetime.utcnow()

                logger.info(
                    f"[CrossMessageService] MATCH: паттерн='{pattern.pattern}' "
                    f"[{match_method}] +{pattern.weight} баллов"
                )

        # Коммитим изменения счётчиков (если что-то сработало)
        if matched_patterns:
            try:
                await session.commit()
            except Exception as e:
                logger.warning(f"[CrossMessageService] Ошибка коммита счётчиков: {e}")
                await session.rollback()

        # ─────────────────────────────────────────────────────────
        # ШАГ 4: Если score > 0 — накапливаем в Redis
        # ─────────────────────────────────────────────────────────
        if score > 0:
            # Добавляем скор и получаем результат накопления
            # Передаём полный текст — обрезание происходит внутри add_score
            accumulation_result = await self.add_score(
                chat_id=chat_id,
                user_id=user_id,
                score=score,
                window_seconds=window_seconds,
                threshold=threshold,
                message_preview=text if text else '',  # Полный текст для журнала
                section_name='cross_message',  # Указываем что это от кросс-паттернов
                message_id=message_id
            )

            logger.info(
                f"[CrossMessageService] check_patterns: chat={chat_id}, user={user_id}, "
                f"score={score}, total={accumulation_result.total_score}/{threshold}, "
                f"matched={len(matched_patterns)}, exceeded={accumulation_result.threshold_exceeded}"
            )

            return CrossMessageCheckResult(
                score=score,
                matched_patterns=matched_patterns,
                total_score=accumulation_result.total_score,
                threshold_exceeded=accumulation_result.threshold_exceeded,
                message_ids=accumulation_result.message_ids
            )

        # Ничего не найдено
        return CrossMessageCheckResult(score=0)

    async def add_pattern(
        self,
        chat_id: int,
        pattern: str,
        weight: int,
        pattern_type: str,
        created_by: int,
        session: AsyncSession
    ) -> CrossMessagePattern:
        """
        Добавляет новый паттерн кросс-сообщений.

        Args:
            chat_id: ID чата
            pattern: Текст паттерна
            weight: Вес (баллы)
            pattern_type: Тип (word/phrase/regex)
            created_by: ID пользователя (админа)
            session: Сессия БД

        Returns:
            Созданный CrossMessagePattern
        """
        # Нормализуем паттерн
        normalizer = get_normalizer()
        normalized = normalizer.normalize(pattern).lower().strip()

        # Создаём объект паттерна
        new_pattern = CrossMessagePattern(
            chat_id=chat_id,
            pattern=pattern.strip(),
            normalized=normalized,
            pattern_type=pattern_type,
            weight=weight,
            is_active=True,
            created_by=created_by
        )

        # Добавляем в сессию
        session.add(new_pattern)

        # Коммитим
        await session.commit()

        # Обновляем из БД
        await session.refresh(new_pattern)

        logger.info(
            f"[CrossMessageService] add_pattern: chat={chat_id}, "
            f"pattern='{pattern}', weight={weight}, type={pattern_type}"
        )

        return new_pattern

    async def delete_pattern(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет паттерн по ID.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            True если удалён, False если не найден
        """
        # Ищем паттерн
        result = await session.execute(
            select(CrossMessagePattern).where(CrossMessagePattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        # Если не найден — возвращаем False
        if not pattern:
            return False

        # Удаляем
        await session.delete(pattern)
        await session.commit()

        logger.info(
            f"[CrossMessageService] delete_pattern: id={pattern_id}, "
            f"pattern='{pattern.pattern}'"
        )

        return True

    async def toggle_pattern(
        self,
        pattern_id: int,
        is_active: bool,
        session: AsyncSession
    ) -> Optional[CrossMessagePattern]:
        """
        Включает/выключает паттерн.

        Args:
            pattern_id: ID паттерна
            is_active: True = включить, False = выключить
            session: Сессия БД

        Returns:
            Обновлённый CrossMessagePattern или None если не найден
        """
        # Ищем паттерн
        result = await session.execute(
            select(CrossMessagePattern).where(CrossMessagePattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        # Если не найден — возвращаем None
        if not pattern:
            return None

        # Обновляем статус
        pattern.is_active = is_active
        await session.commit()

        logger.info(
            f"[CrossMessageService] toggle_pattern: id={pattern_id}, "
            f"is_active={is_active}"
        )

        return pattern

    async def get_pattern_by_id(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> Optional[CrossMessagePattern]:
        """
        Получает паттерн по ID.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            CrossMessagePattern или None если не найден
        """
        result = await session.execute(
            select(CrossMessagePattern).where(CrossMessagePattern.id == pattern_id)
        )
        return result.scalar_one_or_none()

    async def get_patterns_count(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = False
    ) -> int:
        """
        Возвращает количество паттернов для группы.

        Args:
            chat_id: ID чата
            session: Сессия БД
            active_only: True = считать только активные

        Returns:
            Количество паттернов
        """
        # Получаем все паттерны и считаем
        patterns = await self.get_patterns(chat_id, session, active_only=active_only)
        return len(patterns)

    async def get_ttl(
        self,
        chat_id: int,
        user_id: int
    ) -> int:
        """
        Получает оставшееся время жизни скора (TTL в секундах).

        Args:
            chat_id: ID чата
            user_id: ID пользователя

        Returns:
            TTL в секундах (-2 если ключ не существует, -1 если без TTL)
        """
        # Формируем ключ Redis
        score_key = self._get_score_key(chat_id, user_id)

        # Получаем TTL
        return await self._redis.ttl(score_key)

    # ════════════════════════════════════════════════════════════════════════
    # МЕТОДЫ ДЛЯ РАБОТЫ С ПОРОГАМИ (CrossMessageThreshold)
    # ════════════════════════════════════════════════════════════════════════

    async def get_threshold_for_score(
        self,
        chat_id: int,
        score: int,
        session: AsyncSession
    ) -> Optional[CrossMessageThreshold]:
        """
        Ищет порог который подходит для данного скора.

        Логика поиска:
        1. Получаем все активные пороги для группы
        2. Фильтруем: min_score <= score
        3. Фильтруем: max_score >= score (или max_score is NULL для бесконечности)
        4. Сортируем по priority (меньше = приоритетнее)
        5. Возвращаем первый подходящий или None

        Args:
            chat_id: ID чата
            score: Накопленный скор
            session: Сессия БД

        Returns:
            CrossMessageThreshold или None если порог не найден
        """
        # Формируем запрос для активных порогов группы
        # Условия: enabled=True, min_score <= score, (max_score >= score OR max_score IS NULL)
        query = (
            select(CrossMessageThreshold)
            .where(CrossMessageThreshold.chat_id == chat_id)
            .where(CrossMessageThreshold.enabled == True)  # noqa: E712
            .where(CrossMessageThreshold.min_score <= score)
            # max_score >= score ИЛИ max_score is NULL (бесконечность)
            .where(
                (CrossMessageThreshold.max_score >= score) |
                (CrossMessageThreshold.max_score.is_(None))
            )
            # Сортируем по приоритету (меньше = важнее)
            .order_by(CrossMessageThreshold.priority)
            # Берём только первый подходящий
            .limit(1)
        )

        # Выполняем запрос
        result = await session.execute(query)
        threshold = result.scalar_one_or_none()

        # Логируем результат поиска
        if threshold:
            logger.info(
                f"[CrossMessageService] get_threshold_for_score: "
                f"chat={chat_id}, score={score} → порог #{threshold.id} "
                f"({threshold.min_score}-{threshold.max_score or '∞'}) "
                f"action={threshold.action}, duration={threshold.mute_duration}"
            )
        else:
            logger.debug(
                f"[CrossMessageService] get_threshold_for_score: "
                f"chat={chat_id}, score={score} → порог не найден, "
                f"будет использован default из настроек"
            )

        return threshold

    async def get_thresholds(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = True
    ) -> List[CrossMessageThreshold]:
        """
        Получает все пороги для группы.

        Args:
            chat_id: ID чата
            session: Сессия БД
            active_only: True = только активные пороги

        Returns:
            Список CrossMessageThreshold отсортированный по min_score
        """
        # Формируем базовый запрос
        query = select(CrossMessageThreshold).where(
            CrossMessageThreshold.chat_id == chat_id
        )

        # Фильтруем только активные если нужно
        if active_only:
            query = query.where(CrossMessageThreshold.enabled == True)  # noqa: E712

        # Сортируем по min_score (для отображения в UI)
        query = query.order_by(CrossMessageThreshold.min_score)

        # Выполняем запрос
        result = await session.execute(query)

        # Возвращаем список порогов
        return list(result.scalars().all())

    async def add_threshold(
        self,
        chat_id: int,
        min_score: int,
        max_score: Optional[int],
        action: str,
        mute_duration: Optional[int],
        created_by: int,
        session: AsyncSession,
        description: str = None,
        priority: int = 0
    ) -> CrossMessageThreshold:
        """
        Добавляет новый порог.

        Args:
            chat_id: ID чата
            min_score: Минимальный скор диапазона
            max_score: Максимальный скор диапазона (None = бесконечность)
            action: Действие (mute/kick/ban)
            mute_duration: Длительность мута в минутах (только для action='mute')
            created_by: ID пользователя (админа)
            session: Сессия БД
            description: Описание порога (опционально)
            priority: Приоритет (0 = максимальный)

        Returns:
            Созданный CrossMessageThreshold
        """
        # Создаём объект порога
        new_threshold = CrossMessageThreshold(
            chat_id=chat_id,
            min_score=min_score,
            max_score=max_score,
            action=action,
            mute_duration=mute_duration,
            enabled=True,
            priority=priority,
            description=description,
            created_by=created_by
        )

        # Добавляем в сессию
        session.add(new_threshold)

        # Коммитим
        await session.commit()

        # Обновляем из БД
        await session.refresh(new_threshold)

        logger.info(
            f"[CrossMessageService] add_threshold: chat={chat_id}, "
            f"range={min_score}-{max_score or '∞'}, action={action}, "
            f"duration={mute_duration}"
        )

        return new_threshold

    async def delete_threshold(
        self,
        threshold_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет порог по ID.

        Args:
            threshold_id: ID порога
            session: Сессия БД

        Returns:
            True если удалён, False если не найден
        """
        # Ищем порог
        result = await session.execute(
            select(CrossMessageThreshold).where(CrossMessageThreshold.id == threshold_id)
        )
        threshold = result.scalar_one_or_none()

        # Если не найден — возвращаем False
        if not threshold:
            return False

        # Удаляем
        await session.delete(threshold)
        await session.commit()

        logger.info(
            f"[CrossMessageService] delete_threshold: id={threshold_id}, "
            f"range={threshold.min_score}-{threshold.max_score or '∞'}"
        )

        return True

    async def toggle_threshold(
        self,
        threshold_id: int,
        enabled: bool,
        session: AsyncSession
    ) -> Optional[CrossMessageThreshold]:
        """
        Включает/выключает порог.

        Args:
            threshold_id: ID порога
            enabled: True = включить, False = выключить
            session: Сессия БД

        Returns:
            Обновлённый CrossMessageThreshold или None если не найден
        """
        # Ищем порог
        result = await session.execute(
            select(CrossMessageThreshold).where(CrossMessageThreshold.id == threshold_id)
        )
        threshold = result.scalar_one_or_none()

        # Если не найден — возвращаем None
        if not threshold:
            return None

        # Обновляем статус
        threshold.enabled = enabled
        await session.commit()

        logger.info(
            f"[CrossMessageService] toggle_threshold: id={threshold_id}, "
            f"enabled={enabled}"
        )

        return threshold

    async def get_thresholds_count(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = False
    ) -> int:
        """
        Возвращает количество порогов для группы.

        Args:
            chat_id: ID чата
            session: Сессия БД
            active_only: True = считать только активные

        Returns:
            Количество порогов
        """
        thresholds = await self.get_thresholds(chat_id, session, active_only=active_only)
        return len(thresholds)


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР (для удобства)
# ============================================================
# Используется когда нужен сервис без инъекции зависимостей

_cross_message_service: Optional[CrossMessageService] = None


def create_cross_message_service(redis: Redis) -> CrossMessageService:
    """
    Создаёт и кэширует глобальный экземпляр сервиса.

    Args:
        redis: Клиент Redis

    Returns:
        CrossMessageService
    """
    global _cross_message_service
    _cross_message_service = CrossMessageService(redis)
    return _cross_message_service


def get_cross_message_service() -> Optional[CrossMessageService]:
    """
    Возвращает глобальный экземпляр сервиса.

    Returns:
        CrossMessageService или None если не инициализирован
    """
    return _cross_message_service