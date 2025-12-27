# ============================================================
# SCAM PATTERN SERVICE - СЕРВИС УПРАВЛЕНИЯ ПАТТЕРНАМИ СКАМА
# ============================================================
# Этот модуль предоставляет CRUD операции для работы с кастомными
# паттернами скама, которые хранятся в БД (таблица scam_patterns).
#
# Каждая группа может иметь свои паттерны, которые используются
# детектором скама (scam_detector.py) для проверки сообщений.
#
# Основные функции:
# - add_pattern: добавить новый паттерн
# - get_patterns: получить все паттерны группы
# - delete_pattern: удалить паттерн
# - extract_patterns_from_text: анализ текста и извлечение фраз
# - increment_trigger_count: увеличить счётчик срабатываний
# ============================================================

# Импортируем типы для аннотаций
from typing import Optional, List, Tuple, Dict, Any
# Импортируем datetime для работы с временем
from datetime import datetime, timezone
# Импортируем логгер
import logging
# Импортируем регулярные выражения для извлечения фраз
import re

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func
from sqlalchemy.exc import IntegrityError

# Импортируем модели ScamPattern, ScamScoreThreshold и кастомные разделы
from bot.database.models_content_filter import (
    ScamPattern,
    ScamScoreThreshold,
    CustomSpamSection,
    CustomSectionPattern
)

# Импортируем нормализатор текста для единообразной нормализации
# паттернов и текста сообщений
from bot.services.content_filter.text_normalizer import get_normalizer

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _utcnow_naive() -> datetime:
    """
    Возвращает текущее UTC время без информации о часовом поясе.
    PostgreSQL хранит timestamp without timezone.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_pattern(text: str) -> str:
    """
    Нормализует паттерн для хранения и поиска.

    ВАЖНО: Используем тот же TextNormalizer что и для текста сообщений,
    чтобы нормализация паттернов и текста была совместимой.

    Операции (через TextNormalizer):
    - Приводит к нижнему регистру
    - Удаляет невидимые символы (zero-width)
    - Удаляет разделители между буквами (/, -, ., и т.д.)
    - Заменяет l33tspeak и латиницу на кириллицу

    Args:
        text: Исходный текст паттерна

    Returns:
        Нормализованный паттерн
    """
    # Используем TextNormalizer для совместимости с нормализацией текста
    normalizer = get_normalizer()
    normalized = normalizer.normalize(text)
    # Убираем множественные пробелы (на случай если остались)
    normalized = re.sub(r'\s+', ' ', normalized)
    # Убираем пробелы по краям
    normalized = normalized.strip()
    return normalized


def _determine_pattern_type(text: str) -> str:
    """
    Определяет тип паттерна по его содержимому.

    Args:
        text: Текст паттерна

    Returns:
        'word' если одно слово, 'phrase' если фраза
    """
    # Убираем пробелы по краям
    stripped = text.strip()
    # Если есть пробелы внутри — это фраза
    if ' ' in stripped:
        return 'phrase'
    # Иначе — слово
    return 'word'


def _calculate_weight(text: str) -> int:
    """
    Рассчитывает вес паттерна на основе его длины и типа.

    Логика:
    - Одно короткое слово (< 5 символов): 15 баллов
    - Одно длинное слово (>= 5 символов): 20 баллов
    - Фраза из 2 слов: 25 баллов
    - Фраза из 3+ слов: 30 баллов

    Args:
        text: Текст паттерна

    Returns:
        Вес паттерна (10-50)
    """
    # Разбиваем на слова
    words = text.strip().split()
    word_count = len(words)

    if word_count == 1:
        # Одно слово — вес зависит от длины
        if len(words[0]) < 5:
            return 15  # Короткое слово
        else:
            return 20  # Длинное слово
    elif word_count == 2:
        return 25  # Фраза из 2 слов
    else:
        return 30  # Фраза из 3+ слов


# ============================================================
# КЛАСС СЕРВИСА ПАТТЕРНОВ
# ============================================================

class ScamPatternService:
    """
    Сервис для управления паттернами скама в БД.

    Предоставляет:
    - CRUD операции для паттернов
    - Анализ текста и извлечение фраз
    - Статистику срабатываний
    - Экспорт/импорт паттернов

    Пример использования:
        service = ScamPatternService()

        # Добавить паттерн
        await service.add_pattern(
            chat_id=-1001234567890,
            pattern="гарантированный доход",
            created_by=123456789,
            session=session
        )

        # Получить все паттерны группы
        patterns = await service.get_patterns(chat_id, session)
    """

    # ─────────────────────────────────────────────────────────
    # ДОБАВЛЕНИЕ ПАТТЕРНА
    # ─────────────────────────────────────────────────────────

    async def add_pattern(
        self,
        chat_id: int,
        pattern: str,
        created_by: int,
        session: AsyncSession,
        weight: Optional[int] = None,
        category: Optional[str] = None,
        pattern_type: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Добавляет новый паттерн скама для группы.

        Args:
            chat_id: ID группы
            pattern: Текст паттерна (слово или фраза)
            created_by: ID пользователя который добавляет
            session: Сессия БД
            weight: Вес паттерна (если None — рассчитывается автоматически)
            category: Категория (money, crypto, gambling, drugs, adult, other)
            pattern_type: Тип (word, phrase, regex), если None — определяется автоматически

        Returns:
            Tuple[bool, str]: (успех, сообщение)
        """
        # Проверяем что паттерн не пустой
        if not pattern or not pattern.strip():
            return False, "Паттерн не может быть пустым"

        # Нормализуем паттерн
        normalized = _normalize_pattern(pattern)

        # Если паттерн слишком короткий (< 2 символов)
        if len(normalized) < 2:
            return False, "Паттерн слишком короткий (минимум 2 символа)"

        # ─────────────────────────────────────────────────────────
        # Проверка на дубликаты
        # Ищем существующий паттерн с таким же normalized текстом
        # ─────────────────────────────────────────────────────────
        existing = await session.execute(
            select(ScamPattern).where(
                ScamPattern.chat_id == chat_id,
                ScamPattern.normalized == normalized
            )
        )
        # Получаем первый результат (или None)
        existing_pattern = existing.scalar_one_or_none()

        # Если паттерн уже существует — возвращаем ошибку
        if existing_pattern:
            return False, f"Паттерн уже существует: '{existing_pattern.pattern}'"

        # Определяем тип если не задан
        if pattern_type is None:
            pattern_type = _determine_pattern_type(pattern)

        # Рассчитываем вес если не задан
        if weight is None:
            weight = _calculate_weight(pattern)

        try:
            # Создаём объект паттерна
            new_pattern = ScamPattern(
                chat_id=chat_id,
                pattern=pattern.strip(),
                normalized=normalized,
                pattern_type=pattern_type,
                weight=weight,
                category=category,
                is_active=True,
                triggers_count=0,
                created_by=created_by,
                created_at=_utcnow_naive()
            )

            # Добавляем в сессию
            session.add(new_pattern)
            # Фиксируем транзакцию
            await session.commit()

            # Логируем успех
            logger.info(
                f"[ScamPatternService] Добавлен паттерн '{pattern}' "
                f"в чат {chat_id} пользователем {created_by}"
            )

            return True, f"Паттерн добавлен (вес: {weight})"

        except IntegrityError:
            # Откатываем транзакцию при дубликате
            await session.rollback()
            logger.warning(
                f"[ScamPatternService] Паттерн '{pattern}' уже существует в чате {chat_id}"
            )
            return False, "Такой паттерн уже существует"

        except Exception as e:
            # Откатываем транзакцию при ошибке
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка при добавлении паттерна: {e}")
            return False, f"Ошибка: {str(e)}"

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧЕНИЕ ПАТТЕРНОВ
    # ─────────────────────────────────────────────────────────

    async def get_patterns(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = True
    ) -> List[ScamPattern]:
        """
        Получает все паттерны группы.

        Args:
            chat_id: ID группы
            session: Сессия БД
            active_only: Только активные паттерны (по умолчанию True)

        Returns:
            Список объектов ScamPattern
        """
        try:
            # Формируем запрос
            query = select(ScamPattern).where(ScamPattern.chat_id == chat_id)

            # Если нужны только активные
            if active_only:
                query = query.where(ScamPattern.is_active == True)

            # Сортируем по дате создания (новые сверху)
            query = query.order_by(ScamPattern.created_at.desc())

            # Выполняем запрос
            result = await session.execute(query)
            # Возвращаем список паттернов
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"[ScamPatternService] Ошибка при получении паттернов: {e}")
            return []

    async def get_patterns_count(
        self,
        chat_id: int,
        session: AsyncSession,
        active_only: bool = True
    ) -> int:
        """
        Возвращает количество паттернов в группе.

        Args:
            chat_id: ID группы
            session: Сессия БД
            active_only: Считать только активные

        Returns:
            Количество паттернов
        """
        try:
            # Формируем запрос подсчёта
            query = select(func.count(ScamPattern.id)).where(
                ScamPattern.chat_id == chat_id
            )

            if active_only:
                query = query.where(ScamPattern.is_active == True)

            # Выполняем
            result = await session.execute(query)
            return result.scalar() or 0

        except Exception as e:
            logger.error(f"[ScamPatternService] Ошибка подсчёта паттернов: {e}")
            return 0

    async def get_pattern_by_id(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> Optional[ScamPattern]:
        """
        Получает паттерн по его ID.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            ScamPattern или None
        """
        try:
            query = select(ScamPattern).where(ScamPattern.id == pattern_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"[ScamPatternService] Ошибка получения паттерна {pattern_id}: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ ПАТТЕРНА
    # ─────────────────────────────────────────────────────────

    async def delete_pattern(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет паттерн по ID.

        Args:
            pattern_id: ID паттерна для удаления
            session: Сессия БД

        Returns:
            True если удалено успешно
        """
        try:
            # Выполняем удаление
            query = delete(ScamPattern).where(ScamPattern.id == pattern_id)
            result = await session.execute(query)
            await session.commit()

            # Проверяем что что-то удалили
            if result.rowcount > 0:
                logger.info(f"[ScamPatternService] Удалён паттерн ID={pattern_id}")
                return True
            else:
                logger.warning(f"[ScamPatternService] Паттерн ID={pattern_id} не найден")
                return False

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка удаления паттерна: {e}")
            return False

    async def delete_all_patterns(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> int:
        """
        Удаляет все паттерны группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Количество удалённых паттернов
        """
        try:
            query = delete(ScamPattern).where(ScamPattern.chat_id == chat_id)
            result = await session.execute(query)
            await session.commit()

            deleted_count = result.rowcount
            logger.info(
                f"[ScamPatternService] Удалено {deleted_count} паттернов из чата {chat_id}"
            )
            return deleted_count

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка удаления паттернов: {e}")
            return 0

    # ─────────────────────────────────────────────────────────
    # ПЕРЕКЛЮЧЕНИЕ АКТИВНОСТИ
    # ─────────────────────────────────────────────────────────

    async def toggle_pattern(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Переключает активность паттерна (вкл/выкл).

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            True если переключено успешно
        """
        try:
            # Получаем текущий паттерн
            pattern = await self.get_pattern_by_id(pattern_id, session)
            if not pattern:
                return False

            # Инвертируем флаг активности
            new_status = not pattern.is_active

            # Обновляем
            query = update(ScamPattern).where(
                ScamPattern.id == pattern_id
            ).values(is_active=new_status)

            await session.execute(query)
            await session.commit()

            logger.info(
                f"[ScamPatternService] Паттерн ID={pattern_id} "
                f"{'включён' if new_status else 'выключен'}"
            )
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка переключения паттерна: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ СТАТИСТИКИ СРАБАТЫВАНИЙ
    # ─────────────────────────────────────────────────────────

    async def increment_trigger_count(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> None:
        """
        Увеличивает счётчик срабатываний паттерна.
        Вызывается когда паттерн сработал при проверке сообщения.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД
        """
        try:
            # Увеличиваем счётчик и обновляем время последнего срабатывания
            query = update(ScamPattern).where(
                ScamPattern.id == pattern_id
            ).values(
                triggers_count=ScamPattern.triggers_count + 1,
                last_triggered_at=_utcnow_naive()
            )

            await session.execute(query)
            await session.commit()

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка обновления счётчика: {e}")

    # ─────────────────────────────────────────────────────────
    # АНАЛИЗ ТЕКСТА И ИЗВЛЕЧЕНИЕ ФРАЗ
    # ─────────────────────────────────────────────────────────

    def extract_patterns_from_text(
        self,
        text: str,
        min_word_length: int = 3,
        min_phrase_words: int = 2,
        max_phrase_words: int = 5
    ) -> List[Tuple[str, int]]:
        """
        Извлекает потенциальные паттерны из скам-текста.

        Алгоритм (восстановлен из оригинала GitHub):
        1. Разбивает текст на строки
        2. Из каждой строки извлекает значимые слова (фильтрует стоп-слова)
        3. Генерирует комбинации разной длины (скользящее окно 2-5 слов)
        4. Фильтрует по длине и значимости
        5. Рассчитывает вес для каждой фразы

        Args:
            text: Текст для анализа (скам-сообщение)
            min_word_length: Минимальная длина слова
            min_phrase_words: Минимум слов в фразе (по умолчанию 2)
            max_phrase_words: Максимум слов в фразе (по умолчанию 5)

        Returns:
            Список кортежей (фраза, вес)
        """
        # Проверяем что текст не пустой
        if not text or not text.strip():
            return []

        # Результат — список (фраза, вес)
        extracted: List[Tuple[str, int]] = []

        # Множество для отслеживания дубликатов (по нормализованной форме)
        seen: set = set()

        # ─────────────────────────────────────────────────────
        # Стоп-слова которые не имеют смысла как паттерны
        # (восстановлено из оригинального кода GitHub)
        # ─────────────────────────────────────────────────────
        stop_words = {
            'и', 'в', 'на', 'с', 'по', 'из', 'за', 'к', 'от', 'до', 'у',
            'для', 'при', 'о', 'об', 'а', 'но', 'или', 'же', 'бы', 'не',
            'да', 'то', 'как', 'так', 'это', 'что', 'кто', 'где', 'когда',
            'если', 'уже', 'ещё', 'еще', 'все', 'всё', 'вы', 'мы', 'они'
        }

        # ─────────────────────────────────────────────────────
        # ШАГ 1: Разбиваем на строки (исходный текст)
        # ─────────────────────────────────────────────────────
        lines = text.strip().split('\n')

        for line in lines:
            # ─────────────────────────────────────────────────
            # ШАГ 2: Очищаем строку от спецсимволов
            # Убираем эмодзи, оставляем буквы, цифры, дефис, слэш
            # ─────────────────────────────────────────────────
            line_cleaned = re.sub(r'[^\w\s\-/]', ' ', line)
            # Убираем множественные пробелы
            line_cleaned = re.sub(r'\s+', ' ', line_cleaned).strip()

            # Пропускаем пустые строки
            if not line_cleaned:
                continue

            # Разбиваем на слова
            words = line_cleaned.split()

            # ─────────────────────────────────────────────────
            # ШАГ 3: Фильтруем слова по длине и стоп-словам
            # Оставляем только значимые слова
            # ─────────────────────────────────────────────────
            significant_words = [
                w for w in words
                if len(w) >= min_word_length and w.lower() not in stop_words
            ]

            # Если нет значимых слов — пропускаем строку
            if not significant_words:
                continue

            # ─────────────────────────────────────────────────
            # ШАГ 4: Генерируем фразы разной длины
            # Скользящее окно от min_phrase_words до max_phrase_words
            # Это ключевая логика из оригинального кода!
            # ─────────────────────────────────────────────────
            for phrase_len in range(min_phrase_words, min(max_phrase_words + 1, len(significant_words) + 1)):
                for i in range(len(significant_words) - phrase_len + 1):
                    # Формируем фразу из phrase_len подряд идущих слов
                    phrase_words = significant_words[i:i + phrase_len]
                    phrase = ' '.join(phrase_words)

                    # Нормализуем для проверки дубликатов
                    normalized = _normalize_pattern(phrase)

                    # Пропускаем если уже видели такую фразу
                    if normalized in seen:
                        continue

                    # Пропускаем слишком короткие (меньше 5 символов)
                    if len(normalized) < 5:
                        continue

                    # Добавляем в результат
                    seen.add(normalized)
                    weight = _calculate_weight(phrase)
                    extracted.append((phrase, weight))

        # ─────────────────────────────────────────────────────
        # ШАГ 5: Сортируем по весу (от большего к меньшему)
        # ─────────────────────────────────────────────────────
        extracted.sort(key=lambda x: x[1], reverse=True)

        # Ограничиваем количество (максимум 20 фраз как в оригинале)
        return extracted[:20]

    # ─────────────────────────────────────────────────────────
    # ЭКСПОРТ ПАТТЕРНОВ
    # ─────────────────────────────────────────────────────────

    async def export_patterns(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> str:
        """
        Экспортирует паттерны группы в текстовый формат.
        Каждый паттерн на новой строке.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Текст с паттернами (каждый на новой строке)
        """
        patterns = await self.get_patterns(chat_id, session, active_only=False)

        if not patterns:
            return ""

        # Формируем текст: каждый паттерн на новой строке
        lines = [p.pattern for p in patterns]
        return '\n'.join(lines)

    # ─────────────────────────────────────────────────────────
    # ИМПОРТ ПАТТЕРНОВ ИЗ ТЕКСТА
    # ─────────────────────────────────────────────────────────

    async def import_patterns_from_text(
        self,
        chat_id: int,
        text: str,
        created_by: int,
        session: AsyncSession
    ) -> Tuple[int, int]:
        """
        Импортирует паттерны из текста (каждая строка = паттерн).

        Args:
            chat_id: ID группы
            text: Текст с паттернами (каждый на новой строке)
            created_by: ID пользователя который импортирует
            session: Сессия БД

        Returns:
            Tuple[int, int]: (добавлено, пропущено)
        """
        if not text or not text.strip():
            return 0, 0

        # Разбиваем на строки
        lines = text.strip().split('\n')

        added = 0
        skipped = 0

        for line in lines:
            pattern = line.strip()
            if not pattern:
                continue

            # Пробуем добавить
            success, _ = await self.add_pattern(
                chat_id=chat_id,
                pattern=pattern,
                created_by=created_by,
                session=session
            )

            if success:
                added += 1
            else:
                skipped += 1

        logger.info(
            f"[ScamPatternService] Импорт в чат {chat_id}: "
            f"добавлено {added}, пропущено {skipped}"
        )

        return added, skipped

    # ─────────────────────────────────────────────────────────
    # ПЕРЕНОРМАЛИЗАЦИЯ ПАТТЕРНОВ
    # ─────────────────────────────────────────────────────────

    async def renormalize_all_patterns(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> int:
        """
        Перенормализует все паттерны группы с новой логикой нормализации.

        Используется после обновления функции _normalize_pattern().
        Обновляет поле normalized для всех паттернов группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Количество обновлённых паттернов
        """
        try:
            # Получаем все паттерны группы (включая неактивные)
            patterns = await self.get_patterns(chat_id, session, active_only=False)

            if not patterns:
                return 0

            updated_count = 0

            for pattern in patterns:
                # Вычисляем новую нормализованную версию
                new_normalized = _normalize_pattern(pattern.pattern)

                # Если изменилось - обновляем
                if new_normalized != pattern.normalized:
                    query = update(ScamPattern).where(
                        ScamPattern.id == pattern.id
                    ).values(normalized=new_normalized)

                    await session.execute(query)
                    updated_count += 1

                    logger.debug(
                        f"[ScamPatternService] Перенормализован паттерн #{pattern.id}: "
                        f"'{pattern.normalized}' -> '{new_normalized}'"
                    )

            # Коммитим все изменения
            await session.commit()

            logger.info(
                f"[ScamPatternService] Перенормализовано {updated_count} паттернов "
                f"из {len(patterns)} в чате {chat_id}"
            )

            return updated_count

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamPatternService] Ошибка перенормализации: {e}")
            return 0


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР (СИНГЛТОН)
# ============================================================

# Глобальный экземпляр для переиспользования
_pattern_service: Optional[ScamPatternService] = None


def get_pattern_service() -> ScamPatternService:
    """
    Возвращает глобальный экземпляр ScamPatternService (синглтон).

    Returns:
        Экземпляр ScamPatternService
    """
    global _pattern_service
    if _pattern_service is None:
        _pattern_service = ScamPatternService()
    return _pattern_service


# ============================================================
# СЕРВИС УПРАВЛЕНИЯ ПОРОГАМИ БАЛЛОВ СКАМА
# ============================================================
# Класс для CRUD операций с порогами баллов (ScamScoreThreshold).
# Позволяет задавать разные действия для разных диапазонов скора.

class ScamThresholdService:
    """
    Сервис для управления порогами баллов антискама.

    Пороги позволяют градировать действия по скору:
    - 100-299 баллов → delete (возможно ложное срабатывание)
    - 300-399 баллов → mute 1 час (подозрительно)
    - 400+ баллов → ban (явный скам)
    """

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧЕНИЕ ПОРОГОВ
    # ─────────────────────────────────────────────────────────

    async def get_thresholds(
        self,
        chat_id: int,
        session: AsyncSession,
        enabled_only: bool = True
    ) -> List[ScamScoreThreshold]:
        """
        Получает все пороги группы.

        Args:
            chat_id: ID группы
            session: Сессия БД
            enabled_only: Только активные пороги

        Returns:
            Список порогов отсортированный по приоритету
        """
        # Формируем запрос для получения порогов группы
        query = select(ScamScoreThreshold).where(
            ScamScoreThreshold.chat_id == chat_id
        )

        # Если нужны только активные - фильтруем
        if enabled_only:
            query = query.where(ScamScoreThreshold.enabled == True)

        # Сортируем по приоритету (меньше = раньше)
        query = query.order_by(ScamScoreThreshold.priority)

        # Выполняем запрос
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_threshold_by_id(
        self,
        threshold_id: int,
        session: AsyncSession
    ) -> Optional[ScamScoreThreshold]:
        """
        Получает порог по ID.

        Args:
            threshold_id: ID порога
            session: Сессия БД

        Returns:
            Порог или None если не найден
        """
        query = select(ScamScoreThreshold).where(
            ScamScoreThreshold.id == threshold_id
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────────────
    # ПОИСК ПОДХОДЯЩЕГО ПОРОГА ПО СКОРУ
    # ─────────────────────────────────────────────────────────

    async def get_action_for_score(
        self,
        chat_id: int,
        score: int,
        session: AsyncSession
    ) -> Optional[Tuple[str, Optional[int]]]:
        """
        Находит действие для указанного скора.

        Проходит по всем активным порогам группы и ищет
        порог где min_score <= score <= max_score.

        Args:
            chat_id: ID группы
            score: Скор сообщения
            session: Сессия БД

        Returns:
            Tuple[action, mute_duration] или None если подходящий порог не найден
        """
        # Получаем все активные пороги отсортированные по приоритету
        thresholds = await self.get_thresholds(chat_id, session, enabled_only=True)

        # Ищем подходящий порог
        for threshold in thresholds:
            # Проверяем нижнюю границу
            if score < threshold.min_score:
                continue

            # Проверяем верхнюю границу (если задана)
            if threshold.max_score is not None and score > threshold.max_score:
                continue

            # Нашли подходящий порог
            logger.debug(
                f"[ScamThresholdService] Скор {score} попал в порог "
                f"[{threshold.min_score}-{threshold.max_score or '∞'}]: {threshold.action}"
            )
            return (threshold.action, threshold.mute_duration)

        # Не нашли подходящий порог
        return None

    # ─────────────────────────────────────────────────────────
    # ДОБАВЛЕНИЕ ПОРОГА
    # ─────────────────────────────────────────────────────────

    async def add_threshold(
        self,
        chat_id: int,
        min_score: int,
        action: str,
        session: AsyncSession,
        max_score: Optional[int] = None,
        mute_duration: Optional[int] = None,
        description: Optional[str] = None,
        priority: int = 0,
        created_by: Optional[int] = None
    ) -> Tuple[bool, Optional[int]]:
        """
        Добавляет новый порог баллов.

        Args:
            chat_id: ID группы
            min_score: Минимальный скор (включительно)
            action: Действие (delete/mute/kick/ban)
            session: Сессия БД
            max_score: Максимальный скор (NULL = без ограничения)
            mute_duration: Длительность мута в минутах
            description: Описание порога
            priority: Приоритет (меньше = раньше)
            created_by: ID админа

        Returns:
            Tuple[bool, Optional[int]]: (успех, ID нового порога)
        """
        try:
            # Создаём новый порог
            threshold = ScamScoreThreshold(
                chat_id=chat_id,
                min_score=min_score,
                max_score=max_score,
                action=action,
                mute_duration=mute_duration,
                description=description,
                priority=priority,
                enabled=True,
                created_by=created_by,
                created_at=_utcnow_naive(),
                updated_at=_utcnow_naive()
            )

            # Добавляем в сессию
            session.add(threshold)
            await session.commit()
            await session.refresh(threshold)

            logger.info(
                f"[ScamThresholdService] Добавлен порог [{min_score}-{max_score or '∞'}] "
                f"→ {action} для чата {chat_id}"
            )

            return True, threshold.id

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamThresholdService] Ошибка добавления порога: {e}")
            return False, None

    # ─────────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ ПОРОГА
    # ─────────────────────────────────────────────────────────

    async def update_threshold(
        self,
        threshold_id: int,
        session: AsyncSession,
        min_score: Optional[int] = None,
        max_score: Optional[int] = None,
        action: Optional[str] = None,
        mute_duration: Optional[int] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        enabled: Optional[bool] = None
    ) -> bool:
        """
        Обновляет существующий порог.

        Args:
            threshold_id: ID порога
            session: Сессия БД
            (остальные параметры - новые значения, None = не менять)

        Returns:
            True если обновлено успешно
        """
        try:
            # Формируем словарь с новыми значениями
            values = {'updated_at': _utcnow_naive()}

            # Добавляем только указанные поля
            if min_score is not None:
                values['min_score'] = min_score
            if max_score is not None:
                values['max_score'] = max_score
            if action is not None:
                values['action'] = action
            if mute_duration is not None:
                values['mute_duration'] = mute_duration
            if description is not None:
                values['description'] = description
            if priority is not None:
                values['priority'] = priority
            if enabled is not None:
                values['enabled'] = enabled

            # Выполняем обновление
            query = update(ScamScoreThreshold).where(
                ScamScoreThreshold.id == threshold_id
            ).values(**values)

            result = await session.execute(query)
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"[ScamThresholdService] Порог ID={threshold_id} обновлён")
                return True

            return False

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamThresholdService] Ошибка обновления порога: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ ПОРОГА
    # ─────────────────────────────────────────────────────────

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
            True если удалено успешно
        """
        try:
            query = delete(ScamScoreThreshold).where(
                ScamScoreThreshold.id == threshold_id
            )
            result = await session.execute(query)
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"[ScamThresholdService] Удалён порог ID={threshold_id}")
                return True

            return False

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamThresholdService] Ошибка удаления порога: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # ПЕРЕКЛЮЧЕНИЕ АКТИВНОСТИ
    # ─────────────────────────────────────────────────────────

    async def toggle_threshold(
        self,
        threshold_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Переключает активность порога (вкл/выкл).

        Args:
            threshold_id: ID порога
            session: Сессия БД

        Returns:
            True если переключено успешно
        """
        try:
            # Получаем текущий порог
            threshold = await self.get_threshold_by_id(threshold_id, session)
            if not threshold:
                return False

            # Инвертируем флаг активности
            new_status = not threshold.enabled

            # Обновляем
            query = update(ScamScoreThreshold).where(
                ScamScoreThreshold.id == threshold_id
            ).values(enabled=new_status, updated_at=_utcnow_naive())

            await session.execute(query)
            await session.commit()

            logger.info(
                f"[ScamThresholdService] Порог ID={threshold_id} "
                f"{'включён' if new_status else 'выключен'}"
            )
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[ScamThresholdService] Ошибка переключения порога: {e}")
            return False


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР THRESHOLD SERVICE (СИНГЛТОН)
# ============================================================

# Глобальный экземпляр для переиспользования
_threshold_service: Optional[ScamThresholdService] = None


def get_threshold_service() -> ScamThresholdService:
    """
    Возвращает глобальный экземпляр ScamThresholdService (синглтон).

    Returns:
        Экземпляр ScamThresholdService
    """
    global _threshold_service
    if _threshold_service is None:
        _threshold_service = ScamThresholdService()
    return _threshold_service


# ============================================================
# СЕРВИС УПРАВЛЕНИЯ КАСТОМНЫМИ РАЗДЕЛАМИ СПАМА
# ============================================================
# Класс для CRUD операций с кастомными разделами (CustomSpamSection)
# и их паттернами (CustomSectionPattern).
#
# Кастомные разделы позволяют администраторам создавать отдельные
# категории спама (такси, жильё, наркотики и т.д.) со своими:
# - Наборами паттернов
# - Порогом чувствительности
# - Действием при срабатывании
# - Каналом для пересылки (forward + delete)

class CustomSectionService:
    """
    Сервис для управления кастомными разделами спама.

    Каждый раздел — это отдельная категория спама с:
    - Уникальным названием
    - Своими паттернами
    - Своим порогом чувствительности
    - Своим действием (delete/mute/ban/forward_delete)
    - Опционально каналом для пересылки
    """

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧЕНИЕ РАЗДЕЛОВ
    # ─────────────────────────────────────────────────────────

    async def get_sections(
        self,
        chat_id: int,
        session: AsyncSession,
        enabled_only: bool = True
    ) -> List[CustomSpamSection]:
        """
        Получает все разделы группы.

        Args:
            chat_id: ID группы
            session: Сессия БД
            enabled_only: Только активные разделы

        Returns:
            Список разделов отсортированный по названию
        """
        query = select(CustomSpamSection).where(
            CustomSpamSection.chat_id == chat_id
        )

        if enabled_only:
            query = query.where(CustomSpamSection.enabled == True)

        query = query.order_by(CustomSpamSection.name)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_section_by_id(
        self,
        section_id: int,
        session: AsyncSession
    ) -> Optional[CustomSpamSection]:
        """
        Получает раздел по ID.

        Args:
            section_id: ID раздела
            session: Сессия БД

        Returns:
            Раздел или None если не найден
        """
        query = select(CustomSpamSection).where(
            CustomSpamSection.id == section_id
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_section_by_name(
        self,
        chat_id: int,
        name: str,
        session: AsyncSession
    ) -> Optional[CustomSpamSection]:
        """
        Находит раздел по названию в группе.

        Args:
            chat_id: ID группы
            name: Название раздела
            session: Сессия БД

        Returns:
            Раздел или None если не найден
        """
        query = select(CustomSpamSection).where(
            CustomSpamSection.chat_id == chat_id,
            CustomSpamSection.name == name
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────────────
    # СОЗДАНИЕ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def create_section(
        self,
        chat_id: int,
        name: str,
        session: AsyncSession,
        description: Optional[str] = None,
        threshold: int = 60,
        action: str = 'delete',
        mute_duration: Optional[int] = None,
        forward_channel_id: Optional[int] = None,
        created_by: Optional[int] = None
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Создаёт новый раздел спама.

        Args:
            chat_id: ID группы
            name: Название раздела
            session: Сессия БД
            description: Описание
            threshold: Порог чувствительности (по умолчанию 60)
            action: Действие (delete/mute/ban/forward_delete)
            mute_duration: Длительность мута в минутах
            forward_channel_id: ID канала для пересылки
            created_by: ID создателя

        Returns:
            Tuple[bool, Optional[int], Optional[str]]:
            (успех, ID раздела или None, сообщение об ошибке или None)
        """
        try:
            # Проверяем что название не пустое
            name = name.strip()
            if not name:
                return False, None, "Название раздела не может быть пустым"

            # Проверяем длину названия
            if len(name) > 100:
                return False, None, "Название слишком длинное (макс. 100 символов)"

            # Создаём раздел
            section = CustomSpamSection(
                chat_id=chat_id,
                name=name,
                description=description,
                enabled=True,
                threshold=threshold,
                action=action,
                mute_duration=mute_duration,
                forward_channel_id=forward_channel_id,
                log_violations=True,
                created_by=created_by,
                created_at=_utcnow_naive(),
                updated_at=_utcnow_naive()
            )

            session.add(section)
            await session.commit()
            await session.refresh(section)

            logger.info(
                f"[CustomSectionService] Создан раздел '{name}' (ID={section.id}) "
                f"для чата {chat_id}"
            )

            return True, section.id, None

        except IntegrityError:
            await session.rollback()
            return False, None, f"Раздел с названием '{name}' уже существует"

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка создания раздела: {e}")
            return False, None, str(e)

    # ─────────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def update_section(
        self,
        section_id: int,
        session: AsyncSession,
        name: Optional[str] = None,
        description: Optional[str] = None,
        threshold: Optional[int] = None,
        action: Optional[str] = None,
        mute_duration: Optional[int] = None,
        forward_channel_id: Optional[int] = None,
        mute_text: Optional[str] = None,
        ban_text: Optional[str] = None,
        delete_delay: Optional[int] = None,
        notification_delete_delay: Optional[int] = None,
        log_violations: Optional[bool] = None,
        enabled: Optional[bool] = None,
        forward_on_delete: Optional[bool] = None,
        forward_on_mute: Optional[bool] = None,
        forward_on_ban: Optional[bool] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Обновляет существующий раздел.

        Args:
            section_id: ID раздела
            session: Сессия БД
            (остальные параметры - новые значения, None = не менять)

        Returns:
            Tuple[bool, Optional[str]]: (успех, сообщение об ошибке или None)
        """
        try:
            # Формируем словарь с новыми значениями
            values = {'updated_at': _utcnow_naive()}

            if name is not None:
                name = name.strip()
                if not name:
                    return False, "Название не может быть пустым"
                if len(name) > 100:
                    return False, "Название слишком длинное"
                values['name'] = name

            if description is not None:
                values['description'] = description
            if threshold is not None:
                values['threshold'] = threshold
            if action is not None:
                values['action'] = action
            if mute_duration is not None:
                values['mute_duration'] = mute_duration
            if forward_channel_id is not None:
                values['forward_channel_id'] = forward_channel_id
            if mute_text is not None:
                values['mute_text'] = mute_text
            if ban_text is not None:
                values['ban_text'] = ban_text
            if delete_delay is not None:
                values['delete_delay'] = delete_delay
            if notification_delete_delay is not None:
                values['notification_delete_delay'] = notification_delete_delay
            if log_violations is not None:
                values['log_violations'] = log_violations
            if enabled is not None:
                values['enabled'] = enabled
            if forward_on_delete is not None:
                values['forward_on_delete'] = forward_on_delete
            if forward_on_mute is not None:
                values['forward_on_mute'] = forward_on_mute
            if forward_on_ban is not None:
                values['forward_on_ban'] = forward_on_ban

            query = update(CustomSpamSection).where(
                CustomSpamSection.id == section_id
            ).values(**values)

            result = await session.execute(query)
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"[CustomSectionService] Раздел ID={section_id} обновлён")
                return True, None

            return False, "Раздел не найден"

        except IntegrityError:
            await session.rollback()
            return False, "Раздел с таким названием уже существует"

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка обновления раздела: {e}")
            return False, str(e)

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def delete_section(
        self,
        section_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет раздел и все его паттерны (CASCADE).

        Args:
            section_id: ID раздела
            session: Сессия БД

        Returns:
            True если удалено успешно
        """
        try:
            query = delete(CustomSpamSection).where(
                CustomSpamSection.id == section_id
            )
            result = await session.execute(query)
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"[CustomSectionService] Удалён раздел ID={section_id}")
                return True

            return False

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка удаления раздела: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # ПЕРЕКЛЮЧЕНИЕ АКТИВНОСТИ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def toggle_section(
        self,
        section_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Переключает активность раздела (вкл/выкл).

        Args:
            section_id: ID раздела
            session: Сессия БД

        Returns:
            True если переключено успешно
        """
        try:
            section = await self.get_section_by_id(section_id, session)
            if not section:
                return False

            new_status = not section.enabled

            query = update(CustomSpamSection).where(
                CustomSpamSection.id == section_id
            ).values(enabled=new_status, updated_at=_utcnow_naive())

            await session.execute(query)
            await session.commit()

            logger.info(
                f"[CustomSectionService] Раздел ID={section_id} "
                f"{'включён' if new_status else 'выключен'}"
            )
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка переключения раздела: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # ПАТТЕРНЫ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def get_section_patterns(
        self,
        section_id: int,
        session: AsyncSession,
        active_only: bool = True
    ) -> List[CustomSectionPattern]:
        """
        Получает все паттерны раздела.

        Args:
            section_id: ID раздела
            session: Сессия БД
            active_only: Только активные паттерны

        Returns:
            Список паттернов отсортированный по весу (по убыванию)
        """
        query = select(CustomSectionPattern).where(
            CustomSectionPattern.section_id == section_id
        )

        if active_only:
            query = query.where(CustomSectionPattern.is_active == True)

        query = query.order_by(CustomSectionPattern.weight.desc())

        result = await session.execute(query)
        return list(result.scalars().all())

    async def add_section_pattern(
        self,
        section_id: int,
        pattern: str,
        session: AsyncSession,
        pattern_type: str = 'phrase',
        weight: int = 25,
        created_by: Optional[int] = None
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Добавляет паттерн в раздел.

        Args:
            section_id: ID раздела
            pattern: Текст паттерна
            session: Сессия БД
            pattern_type: Тип (word/phrase/regex)
            weight: Вес паттерна
            created_by: ID создателя

        Returns:
            Tuple[bool, Optional[int], Optional[str]]:
            (успех, ID паттерна или None, сообщение об ошибке или None)
        """
        try:
            pattern = pattern.strip()
            if not pattern:
                return False, None, "Паттерн не может быть пустым"

            if len(pattern) > 500:
                return False, None, "Паттерн слишком длинный (макс. 500 символов)"

            # Нормализуем паттерн
            normalized = _normalize_pattern(pattern)

            # Проверяем на дубликат
            existing = await session.execute(
                select(CustomSectionPattern).where(
                    CustomSectionPattern.section_id == section_id,
                    CustomSectionPattern.normalized == normalized
                )
            )
            if existing.scalar_one_or_none():
                return False, None, f"Паттерн «{pattern[:30]}...» уже существует"

            section_pattern = CustomSectionPattern(
                section_id=section_id,
                pattern=pattern,
                normalized=normalized,
                pattern_type=pattern_type,
                weight=weight,
                is_active=True,
                triggers_count=0,
                created_by=created_by,
                created_at=_utcnow_naive()
            )

            session.add(section_pattern)
            await session.commit()
            await session.refresh(section_pattern)

            logger.info(
                f"[CustomSectionService] Добавлен паттерн '{pattern[:30]}...' "
                f"(ID={section_pattern.id}) в раздел {section_id}"
            )

            return True, section_pattern.id, None

        except IntegrityError:
            await session.rollback()
            return False, None, "Такой паттерн уже существует в разделе"

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка добавления паттерна: {e}")
            return False, None, str(e)

    async def delete_section_pattern(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет паттерн раздела по ID.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            True если удалено успешно
        """
        try:
            query = delete(CustomSectionPattern).where(
                CustomSectionPattern.id == pattern_id
            )
            result = await session.execute(query)
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"[CustomSectionService] Удалён паттерн ID={pattern_id}")
                return True

            return False

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка удаления паттерна: {e}")
            return False

    async def delete_all_section_patterns(
        self,
        section_id: int,
        session: AsyncSession
    ) -> int:
        """
        Удаляет все паттерны раздела.

        Args:
            section_id: ID раздела
            session: Сессия БД

        Returns:
            Количество удалённых паттернов
        """
        try:
            query = delete(CustomSectionPattern).where(
                CustomSectionPattern.section_id == section_id
            )
            result = await session.execute(query)
            await session.commit()

            deleted_count = result.rowcount
            if deleted_count > 0:
                logger.info(
                    f"[CustomSectionService] Удалено {deleted_count} паттернов "
                    f"из раздела ID={section_id}"
                )

            return deleted_count

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка удаления паттернов: {e}")
            return 0

    async def get_section_pattern_by_id(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> Optional[CustomSectionPattern]:
        """
        Получает паттерн раздела по ID.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            Паттерн или None
        """
        query = select(CustomSectionPattern).where(
            CustomSectionPattern.id == pattern_id
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def toggle_section_pattern(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Переключает активность паттерна раздела.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД

        Returns:
            True если переключено успешно
        """
        try:
            pattern = await self.get_section_pattern_by_id(pattern_id, session)
            if not pattern:
                return False

            new_status = not pattern.is_active

            query = update(CustomSectionPattern).where(
                CustomSectionPattern.id == pattern_id
            ).values(is_active=new_status)

            await session.execute(query)
            await session.commit()

            logger.info(
                f"[CustomSectionService] Паттерн ID={pattern_id} "
                f"{'включён' if new_status else 'выключен'}"
            )
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка переключения паттерна: {e}")
            return False

    async def get_patterns_count(
        self,
        section_id: int,
        session: AsyncSession
    ) -> int:
        """
        Возвращает количество паттернов в разделе.

        Args:
            section_id: ID раздела
            session: Сессия БД

        Returns:
            Количество паттернов
        """
        query = select(func.count()).select_from(CustomSectionPattern).where(
            CustomSectionPattern.section_id == section_id
        )
        result = await session.execute(query)
        return result.scalar() or 0

    async def increment_pattern_trigger(
        self,
        pattern_id: int,
        session: AsyncSession
    ) -> None:
        """
        Увеличивает счётчик срабатываний паттерна раздела.

        Args:
            pattern_id: ID паттерна
            session: Сессия БД
        """
        try:
            query = update(CustomSectionPattern).where(
                CustomSectionPattern.id == pattern_id
            ).values(
                triggers_count=CustomSectionPattern.triggers_count + 1,
                last_triggered_at=_utcnow_naive()
            )

            await session.execute(query)
            await session.commit()

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка обновления счётчика: {e}")

    # ─────────────────────────────────────────────────────────
    # ПОРОГИ БАЛЛОВ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def get_section_thresholds(
        self,
        section_id: int,
        session: AsyncSession,
        enabled_only: bool = True
    ) -> List:
        """
        Получает все пороги баллов раздела.

        Args:
            section_id: ID раздела
            session: Сессия БД
            enabled_only: Только активные пороги

        Returns:
            Список порогов
        """
        from bot.database.models_content_filter import CustomSectionThreshold

        query = select(CustomSectionThreshold).where(
            CustomSectionThreshold.section_id == section_id
        )

        if enabled_only:
            query = query.where(CustomSectionThreshold.enabled == True)

        query = query.order_by(CustomSectionThreshold.min_score)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def add_section_threshold(
        self,
        section_id: int,
        min_score: int,
        max_score: Optional[int],
        action: str,
        session: AsyncSession,
        mute_duration: Optional[int] = None,
        created_by: Optional[int] = None
    ) -> Tuple[bool, Optional[int]]:
        """
        Добавляет порог баллов для раздела.

        Args:
            section_id: ID раздела
            min_score: Минимальный балл (включительно)
            max_score: Максимальный балл (включительно, None = ∞)
            action: Действие (delete/mute/ban)
            session: Сессия БД
            mute_duration: Длительность мута в минутах
            created_by: ID создателя

        Returns:
            (успех, id_порога)
        """
        from bot.database.models_content_filter import CustomSectionThreshold

        try:
            threshold = CustomSectionThreshold(
                section_id=section_id,
                min_score=min_score,
                max_score=max_score,
                action=action,
                mute_duration=mute_duration,
                created_by=created_by
            )
            session.add(threshold)
            await session.commit()
            await session.refresh(threshold)

            logger.info(
                f"[CustomSectionService] Порог добавлен: section={section_id}, "
                f"range={min_score}-{max_score}, action={action}"
            )
            return True, threshold.id

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка добавления порога: {e}")
            return False, None

    async def delete_section_threshold(
        self,
        threshold_id: int,
        session: AsyncSession
    ) -> bool:
        """Удаляет порог баллов."""
        from bot.database.models_content_filter import CustomSectionThreshold

        try:
            result = await session.execute(
                delete(CustomSectionThreshold).where(
                    CustomSectionThreshold.id == threshold_id
                )
            )
            await session.commit()
            return result.rowcount > 0

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка удаления порога: {e}")
            return False

    async def toggle_section_threshold(
        self,
        threshold_id: int,
        session: AsyncSession
    ) -> bool:
        """Переключает активность порога."""
        from bot.database.models_content_filter import CustomSectionThreshold

        try:
            result = await session.execute(
                select(CustomSectionThreshold).where(
                    CustomSectionThreshold.id == threshold_id
                )
            )
            threshold = result.scalar_one_or_none()

            if not threshold:
                return False

            threshold.enabled = not threshold.enabled
            await session.commit()
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[CustomSectionService] Ошибка переключения порога: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # ПОИСК ПОДХОДЯЩЕГО ПОРОГА ПО СКОРУ РАЗДЕЛА
    # ─────────────────────────────────────────────────────────

    async def get_action_for_section_score(
        self,
        section_id: int,
        score: int,
        session: AsyncSession
    ) -> Optional[Tuple[str, Optional[int]]]:
        """
        Находит действие для указанного скора в порогах раздела.

        Проходит по всем активным порогам раздела и ищет
        порог где min_score <= score <= max_score.

        Логика:
        1. Если score попадает в диапазон порога — используем его action
        2. Если score ПРЕВЫШАЕТ все пороги — используем ПОСЛЕДНИЙ (самый строгий) порог
        3. Если score МЕНЬШЕ всех порогов — возвращаем None (action из раздела)

        Args:
            section_id: ID раздела
            score: Скор сообщения
            session: Сессия БД

        Returns:
            Tuple[action, mute_duration] или None если порог не найден
        """
        # Получаем все активные пороги раздела отсортированные по min_score
        thresholds = await self.get_section_thresholds(section_id, session, enabled_only=True)

        if not thresholds:
            return None

        # Сохраняем последний (самый строгий) порог для случая превышения
        last_threshold = thresholds[-1]

        # Ищем подходящий порог
        for threshold in thresholds:
            # Проверяем нижнюю границу
            if score < threshold.min_score:
                continue

            # Проверяем верхнюю границу (если задана)
            if threshold.max_score is not None and score > threshold.max_score:
                continue

            # Нашли подходящий порог
            logger.debug(
                f"[CustomSectionService] Скор {score} попал в порог раздела "
                f"[{threshold.min_score}-{threshold.max_score or '∞'}]: {threshold.action}"
            )
            return (threshold.action, threshold.mute_duration)

        # Не нашли подходящий порог
        # Проверяем: если score превышает последний порог — используем его
        if score >= last_threshold.min_score:
            logger.debug(
                f"[CustomSectionService] Скор {score} превышает все пороги, "
                f"используем последний порог [{last_threshold.min_score}-"
                f"{last_threshold.max_score or '∞'}]: {last_threshold.action}"
            )
            return (last_threshold.action, last_threshold.mute_duration)

        # Score меньше всех порогов — вернём None, чтобы использовался action из раздела
        return None


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР SECTION SERVICE (СИНГЛТОН)
# ============================================================

_section_service: Optional[CustomSectionService] = None


def get_section_service() -> CustomSectionService:
    """
    Возвращает глобальный экземпляр CustomSectionService (синглтон).

    Returns:
        Экземпляр CustomSectionService
    """
    global _section_service
    if _section_service is None:
        _section_service = CustomSectionService()
    return _section_service


# ============================================================
# СЕРВИС УПРАВЛЕНИЯ БАЗОВЫМИ СИГНАЛАМИ (УБИРАЕМ ХАРДКОД)
# ============================================================
# Позволяет группам настраивать базовые SCAM_SIGNALS:
# - Включать/выключать отдельные сигналы
# - Менять веса (scores) сигналов
#
# Базовые сигналы определены в scam_detector.py:
# money_amount, income_period, easy_money, call_to_action, crypto,
# recruitment, remote_work, exclamations, urgency, scheme,
# training, investments, gambling, age_restriction, unique_offer

class BaseSignalService:
    """
    Сервис для управления переопределениями базовых сигналов.

    Базовые сигналы (SCAM_SIGNALS) теперь настраиваемые!
    Каждая группа может:
    - Отключить ненужные сигналы
    - Изменить веса для более точной настройки
    """

    def get_available_signals(self) -> Dict[str, Dict]:
        """
        Возвращает список всех базовых сигналов с их стандартными значениями.

        Returns:
            Словарь {signal_name: {score, description, pattern}}
        """
        from bot.services.content_filter.scam_detector import SCAM_SIGNALS
        return SCAM_SIGNALS.copy()

    async def get_overrides(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> List:
        """
        Получает все переопределения базовых сигналов для группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Список BaseSignalOverride объектов
        """
        from bot.database.models_content_filter import BaseSignalOverride

        query = select(BaseSignalOverride).where(
            BaseSignalOverride.chat_id == chat_id
        ).order_by(BaseSignalOverride.signal_name)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_override(
        self,
        chat_id: int,
        signal_name: str,
        session: AsyncSession
    ) -> Optional[Any]:
        """
        Получает переопределение для конкретного сигнала.

        Args:
            chat_id: ID группы
            signal_name: Имя сигнала
            session: Сессия БД

        Returns:
            BaseSignalOverride или None
        """
        from bot.database.models_content_filter import BaseSignalOverride

        result = await session.execute(
            select(BaseSignalOverride).where(
                BaseSignalOverride.chat_id == chat_id,
                BaseSignalOverride.signal_name == signal_name
            )
        )
        return result.scalar_one_or_none()

    async def set_override(
        self,
        chat_id: int,
        signal_name: str,
        session: AsyncSession,
        enabled: Optional[bool] = None,
        weight_override: Optional[int] = None,
        updated_by: Optional[int] = None
    ) -> bool:
        """
        Устанавливает или обновляет переопределение для сигнала.

        Если переопределение не существует - создаёт новое.
        Если существует - обновляет.

        Args:
            chat_id: ID группы
            signal_name: Имя сигнала
            session: Сессия БД
            enabled: Включён ли сигнал (None = не менять)
            weight_override: Переопределённый вес (None = не менять)
            updated_by: ID пользователя который делает изменение

        Returns:
            True если успешно
        """
        from bot.database.models_content_filter import BaseSignalOverride

        try:
            # Проверяем что сигнал существует
            available = self.get_available_signals()
            if signal_name not in available:
                logger.warning(
                    f"[BaseSignalService] Неизвестный сигнал: {signal_name}"
                )
                return False

            # Ищем существующее переопределение
            existing = await self.get_override(chat_id, signal_name, session)

            if existing:
                # Обновляем существующее
                if enabled is not None:
                    existing.enabled = enabled
                if weight_override is not None:
                    existing.weight_override = weight_override
                existing.updated_at = _utcnow_naive()
                if updated_by:
                    existing.updated_by = updated_by
            else:
                # Создаём новое
                new_override = BaseSignalOverride(
                    chat_id=chat_id,
                    signal_name=signal_name,
                    enabled=enabled if enabled is not None else True,
                    weight_override=weight_override,
                    created_at=_utcnow_naive(),
                    updated_at=_utcnow_naive(),
                    updated_by=updated_by
                )
                session.add(new_override)

            await session.commit()
            return True

        except Exception as e:
            await session.rollback()
            logger.error(f"[BaseSignalService] Ошибка set_override: {e}")
            return False

    async def toggle_signal(
        self,
        chat_id: int,
        signal_name: str,
        session: AsyncSession,
        updated_by: Optional[int] = None
    ) -> Tuple[bool, bool]:
        """
        Переключает активность сигнала.

        Args:
            chat_id: ID группы
            signal_name: Имя сигнала
            session: Сессия БД
            updated_by: ID пользователя

        Returns:
            (success, new_enabled_state)
        """
        from bot.database.models_content_filter import BaseSignalOverride

        try:
            existing = await self.get_override(chat_id, signal_name, session)

            if existing:
                existing.enabled = not existing.enabled
                existing.updated_at = _utcnow_naive()
                if updated_by:
                    existing.updated_by = updated_by
                await session.commit()
                return True, existing.enabled
            else:
                # Создаём новое переопределение с enabled=False
                # (т.к. по умолчанию все сигналы включены)
                new_override = BaseSignalOverride(
                    chat_id=chat_id,
                    signal_name=signal_name,
                    enabled=False,  # Отключаем
                    weight_override=None,
                    created_at=_utcnow_naive(),
                    updated_at=_utcnow_naive(),
                    updated_by=updated_by
                )
                session.add(new_override)
                await session.commit()
                return True, False

        except Exception as e:
            await session.rollback()
            logger.error(f"[BaseSignalService] Ошибка toggle_signal: {e}")
            return False, True

    async def set_weight(
        self,
        chat_id: int,
        signal_name: str,
        weight: int,
        session: AsyncSession,
        updated_by: Optional[int] = None
    ) -> bool:
        """
        Устанавливает вес для сигнала.

        Args:
            chat_id: ID группы
            signal_name: Имя сигнала
            weight: Новый вес (1-100)
            session: Сессия БД
            updated_by: ID пользователя

        Returns:
            True если успешно
        """
        if weight < 1 or weight > 100:
            return False

        return await self.set_override(
            chat_id=chat_id,
            signal_name=signal_name,
            session=session,
            weight_override=weight,
            updated_by=updated_by
        )

    async def reset_signal(
        self,
        chat_id: int,
        signal_name: str,
        session: AsyncSession
    ) -> bool:
        """
        Сбрасывает переопределение сигнала к стандартным значениям.

        Args:
            chat_id: ID группы
            signal_name: Имя сигнала
            session: Сессия БД

        Returns:
            True если успешно
        """
        from bot.database.models_content_filter import BaseSignalOverride
        from sqlalchemy import delete

        try:
            result = await session.execute(
                delete(BaseSignalOverride).where(
                    BaseSignalOverride.chat_id == chat_id,
                    BaseSignalOverride.signal_name == signal_name
                )
            )
            await session.commit()
            return result.rowcount > 0

        except Exception as e:
            await session.rollback()
            logger.error(f"[BaseSignalService] Ошибка reset_signal: {e}")
            return False

    async def reset_all_signals(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> int:
        """
        Сбрасывает все переопределения сигналов для группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Количество удалённых переопределений
        """
        from bot.database.models_content_filter import BaseSignalOverride
        from sqlalchemy import delete

        try:
            result = await session.execute(
                delete(BaseSignalOverride).where(
                    BaseSignalOverride.chat_id == chat_id
                )
            )
            await session.commit()
            return result.rowcount

        except Exception as e:
            await session.rollback()
            logger.error(f"[BaseSignalService] Ошибка reset_all_signals: {e}")
            return 0

    async def get_effective_signals(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> Dict[str, Dict]:
        """
        Получает эффективные (с учётом переопределений) сигналы для группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Словарь {signal_name: {score, description, enabled}}
        """
        base_signals = self.get_available_signals()
        overrides = await self.get_overrides(chat_id, session)

        # Создаём словарь переопределений для быстрого доступа
        override_map = {o.signal_name: o for o in overrides}

        result = {}
        for signal_name, signal_data in base_signals.items():
            override = override_map.get(signal_name)

            result[signal_name] = {
                'score': override.weight_override if (override and override.weight_override is not None) else signal_data['score'],
                'description': signal_data['description'],
                'enabled': override.enabled if override else True,
                'is_custom': bool(override and (override.weight_override is not None or not override.enabled))
            }

        return result


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР BASE SIGNAL SERVICE (СИНГЛТОН)
# ============================================================

_base_signal_service: Optional[BaseSignalService] = None


def get_base_signal_service() -> BaseSignalService:
    """
    Возвращает глобальный экземпляр BaseSignalService (синглтон).

    Returns:
        Экземпляр BaseSignalService
    """
    global _base_signal_service
    if _base_signal_service is None:
        _base_signal_service = BaseSignalService()
    return _base_signal_service
