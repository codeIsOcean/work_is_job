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
from typing import Optional, List, Tuple
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

# Импортируем модель ScamPattern из моделей content_filter
from bot.database.models_content_filter import ScamPattern

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

        Алгоритм:
        1. Разбивает текст на строки
        2. Из каждой строки извлекает значимые фразы
        3. Фильтрует по длине и значимости
        4. Рассчитывает вес для каждой фразы

        Args:
            text: Текст для анализа (скам-сообщение)
            min_word_length: Минимальная длина слова
            min_phrase_words: Минимум слов в фразе
            max_phrase_words: Максимум слов в фразе

        Returns:
            Список кортежей (фраза, вес)
        """
        if not text or not text.strip():
            return []

        # Результат — список (фраза, вес)
        extracted: List[Tuple[str, int]] = []

        # Множество для отслеживания дубликатов
        seen: set = set()

        # Стоп-слова которые не имеют смысла как паттерны
        stop_words = {
            'и', 'в', 'на', 'с', 'по', 'из', 'за', 'к', 'от', 'до', 'у',
            'для', 'при', 'о', 'об', 'а', 'но', 'или', 'же', 'бы', 'не',
            'да', 'то', 'как', 'так', 'это', 'что', 'кто', 'где', 'когда',
            'если', 'уже', 'ещё', 'еще', 'все', 'всё', 'вы', 'мы', 'они'
        }

        # ─────────────────────────────────────────────────────
        # ШАГ 1: Очистка текста
        # ─────────────────────────────────────────────────────
        # Убираем эмодзи и спецсимволы, оставляем буквы и цифры
        # Заменяем символы переноса на пробелы
        cleaned = re.sub(r'[^\w\s\-/]', ' ', text)
        # Убираем множественные пробелы
        cleaned = re.sub(r'\s+', ' ', cleaned)

        # ─────────────────────────────────────────────────────
        # ШАГ 2: Разбиваем на строки (исходный текст)
        # ─────────────────────────────────────────────────────
        lines = text.strip().split('\n')

        for line in lines:
            # Очищаем строку
            line_cleaned = re.sub(r'[^\w\s\-/]', ' ', line)
            line_cleaned = re.sub(r'\s+', ' ', line_cleaned).strip()

            if not line_cleaned:
                continue

            # Разбиваем на слова
            words = line_cleaned.split()

            # Фильтруем слова по длине и стоп-словам
            significant_words = [
                w for w in words
                if len(w) >= min_word_length and w.lower() not in stop_words
            ]

            if not significant_words:
                continue

            # ─────────────────────────────────────────────────
            # ШАГ 3: Генерируем фразы разной длины
            # ─────────────────────────────────────────────────
            # Берём фразы от min_phrase_words до max_phrase_words слов
            for phrase_len in range(min_phrase_words, min(max_phrase_words + 1, len(significant_words) + 1)):
                for i in range(len(significant_words) - phrase_len + 1):
                    # Формируем фразу
                    phrase_words = significant_words[i:i + phrase_len]
                    phrase = ' '.join(phrase_words)

                    # Нормализуем для проверки дубликатов
                    normalized = _normalize_pattern(phrase)

                    # Пропускаем если уже видели
                    if normalized in seen:
                        continue

                    # Пропускаем слишком короткие
                    if len(normalized) < 5:
                        continue

                    # Добавляем в результат
                    seen.add(normalized)
                    weight = _calculate_weight(phrase)
                    extracted.append((phrase, weight))

        # ─────────────────────────────────────────────────────
        # ШАГ 4: Сортируем по весу (от большего к меньшему)
        # ─────────────────────────────────────────────────────
        extracted.sort(key=lambda x: x[1], reverse=True)

        # Ограничиваем количество (максимум 20 фраз)
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
