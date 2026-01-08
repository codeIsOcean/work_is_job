# ============================================================
# WORD FILTER - ФИЛЬТР ЗАПРЕЩЁННЫХ СЛОВ
# ============================================================
# Этот модуль проверяет текст на наличие запрещённых слов.
# Использует TextNormalizer для обхода обфускации (l33tspeak).
#
# Функционал:
# - Загрузка списка запрещённых слов из БД
# - Кэширование в Redis для производительности
# - Проверка с учётом whitelist (исключений)
# - Поддержка разных типов совпадений (word, phrase, regex)
# ============================================================

# Импортируем модуль регулярных выражений
import re
# Импортируем типы для аннотаций
from typing import Optional, List, Set, NamedTuple
# Импортируем логгер для записи событий
import logging

# Импортируем SQLAlchemy компоненты для работы с БД
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модели БД
from bot.database.models_content_filter import FilterWord, FilterWhitelist
# Импортируем нормализатор текста
from bot.services.content_filter.text_normalizer import TextNormalizer, get_normalizer

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


class WordMatchResult(NamedTuple):
    """
    Результат проверки на запрещённое слово.

    Используем NamedTuple для иммутабельности и удобного доступа к полям.

    Attributes:
        matched: True если найдено запрещённое слово
        word: Найденное слово (из БД)
        word_id: ID слова в БД (для статистики)
        action: Действие для этого слова (или None если использовать default)
        action_duration: Длительность действия в минутах (или None)
        category: Категория слова (profanity, drugs, etc.)
    """
    # Флаг: найдено ли запрещённое слово
    matched: bool
    # Само слово которое нашли (оригинал из БД)
    word: Optional[str] = None
    # ID слова в БД
    word_id: Optional[int] = None
    # Индивидуальное действие для этого слова (None = использовать default)
    action: Optional[str] = None
    # Длительность действия в минутах
    action_duration: Optional[int] = None
    # Категория слова
    category: Optional[str] = None


class WordFilter:
    """
    Класс для проверки текста на запрещённые слова.

    Алгоритм работы:
    1. Загружает слова группы из БД (с кэшированием)
    2. Загружает whitelist (исключения)
    3. Нормализует входной текст
    4. Ищет совпадения с учётом типа (word/phrase/regex)
    5. Возвращает результат с информацией о слове

    Пример использования:
        filter = WordFilter()
        result = await filter.check(
            text="Продаю наркотики дёшево",
            chat_id=-100123456,
            session=db_session
        )
        if result.matched:
            print(f"Найдено слово: {result.word}")
    """

    def __init__(self, normalizer: Optional[TextNormalizer] = None):
        """
        Инициализация фильтра слов.

        Args:
            normalizer: Экземпляр TextNormalizer (если None - используется глобальный)
        """
        # Используем переданный нормализатор или глобальный
        self._normalizer = normalizer or get_normalizer()

    async def check(
        self,
        text: str,
        chat_id: int,
        session: AsyncSession,
        use_normalizer: bool = True
    ) -> WordMatchResult:
        """
        Проверяет текст на наличие запрещённых слов.

        ВАЖНО: Нормализация (l33tspeak) применяется ТОЛЬКО к категории 'obfuscated'.
        Для категорий 'simple' и 'harmful' используется простое сравнение (lowercase).

        Args:
            text: Текст для проверки
            chat_id: ID группы (для загрузки слов этой группы)
            session: Сессия БД
            use_normalizer: Deprecated, игнорируется. Нормализация теперь per-category.

        Returns:
            WordMatchResult с информацией о найденном слове (или matched=False)
        """
        # Проверяем на пустой текст
        if not text or not text.strip():
            # Пустой текст не может содержать запрещённых слов
            return WordMatchResult(matched=False)

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Загружаем запрещённые слова для этой группы
        # ─────────────────────────────────────────────────────────
        filter_words = await self._get_filter_words(chat_id, session)

        # Если список слов пуст - нечего проверять
        if not filter_words:
            return WordMatchResult(matched=False)

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Загружаем whitelist (исключения)
        # ─────────────────────────────────────────────────────────
        whitelist = await self._get_whitelist(chat_id, session)

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Готовим ОБЕ версии текста
        # ─────────────────────────────────────────────────────────
        # Версия для simple/harmful - простой lowercase
        text_lower = text.lower()
        text_words_lower = [w.lower() for w in re.split(r'\W+', text) if w.strip()]

        # Версия для obfuscated - полная нормализация (l33tspeak → кириллица)
        text_normalized = self._normalizer.normalize(text)
        text_words_normalized = self._normalizer.get_words_from_text(text)
        # Версия БЕЗ пробелов - для contains/phrase в obfuscated
        # Чтобы "Alice Demidova" → "алиседемидова" совпадало с паттерном
        text_normalized_no_spaces = text_normalized.replace(' ', '')

        # ─────────────────────────────────────────────────────────
        # ШАГ 4: Проверяем каждое запрещённое слово
        # ─────────────────────────────────────────────────────────
        logger.info(
            f"[WordFilter] Проверка: chat={chat_id}, words={len(filter_words)}, "
            f"text_lower='{text_lower[:80] if len(text_lower) > 80 else text_lower}'"
        )

        for fw in filter_words:
            # ─────────────────────────────────────────────────────
            # ВЫБОР ВЕРСИИ ТЕКСТА НА ОСНОВЕ КАТЕГОРИИ СЛОВА
            # ─────────────────────────────────────────────────────
            # obfuscated → используем нормализованный текст (l33tspeak)
            # simple/harmful → используем простой lowercase
            if fw.category == 'obfuscated':
                check_text = text_normalized
                check_words = text_words_normalized
                # Для obfuscated слово тоже должно быть нормализовано
                check_filter_word = fw.normalized
                # Текст без пробелов для contains/phrase
                check_text_no_spaces = text_normalized_no_spaces
            else:
                check_text = text_lower
                check_words = text_words_lower
                # Для simple/harmful сравниваем с оригиналом слова (lowercase)
                check_filter_word = fw.word.lower()
                # Для harmful/simple не убираем пробелы
                check_text_no_spaces = None

            logger.info(
                f"[WordFilter] Проверяем: '{fw.word}' (cat={fw.category}, "
                f"match={fw.match_type}, use_normalized={fw.category == 'obfuscated'})"
            )

            # Проверяем совпадение в зависимости от типа
            is_match = self._check_word_match(
                filter_word=fw,
                normalized_text=check_text,
                text_words=check_words,
                whitelist=whitelist,
                check_filter_word=check_filter_word,
                text_no_spaces=check_text_no_spaces,
            )

            # Если нашли совпадение - возвращаем результат
            if is_match:
                logger.info(
                    f"[WordFilter] ✅ Найдено: '{fw.word}' (cat={fw.category}) в чате {chat_id}"
                )
                return WordMatchResult(
                    matched=True,
                    word=fw.word,
                    word_id=fw.id,
                    action=fw.action,
                    action_duration=fw.action_duration,
                    category=fw.category
                )

        # Запрещённых слов не найдено
        return WordMatchResult(matched=False)

    def _check_word_match(
        self,
        filter_word: FilterWord,
        normalized_text: str,
        text_words: List[str],
        whitelist: Set[str],
        check_filter_word: Optional[str] = None,
        text_no_spaces: Optional[str] = None,
    ) -> bool:
        """
        Проверяет совпадение одного запрещённого слова с текстом.

        Args:
            filter_word: Объект FilterWord из БД
            normalized_text: Текст для проверки (нормализованный или lowercase)
            text_words: Список отдельных слов из текста
            whitelist: Множество слов-исключений
            check_filter_word: Слово для сравнения (normalized для obfuscated,
                               lowercase для simple/harmful). Если None - используется
                               filter_word.normalized (для обратной совместимости)
            text_no_spaces: Текст без пробелов (для obfuscated + contains/phrase)
                           Позволяет "Alice Demidova" матчить "alicedemidova"

        Returns:
            True если слово найдено в тексте
        """
        # Используем переданное слово или fallback на normalized
        normalized_filter_word = check_filter_word or filter_word.normalized

        # ─────────────────────────────────────────────────────────
        # Проверяем тип совпадения
        # ─────────────────────────────────────────────────────────

        if filter_word.match_type == 'regex':
            # ─────────────────────────────────────────────────────
            # REGEX: используем регулярное выражение
            # ─────────────────────────────────────────────────────
            try:
                # Компилируем regex (оригинальный word, не normalized)
                pattern = re.compile(filter_word.word, re.IGNORECASE | re.UNICODE)
                # Ищем в нормализованном тексте
                match = pattern.search(normalized_text)
                if match:
                    # Проверяем что найденное не в whitelist
                    matched_text = match.group()
                    if matched_text.lower() not in whitelist:
                        return True
            except re.error as e:
                # Логируем ошибку компиляции regex
                logger.warning(
                    f"[WordFilter] Ошибка regex '{filter_word.word}': {e}"
                )
            return False

        elif filter_word.match_type in ('phrase', 'contains'):
            # ─────────────────────────────────────────────────────
            # PHRASE / CONTAINS: ищем как подстроку
            # ─────────────────────────────────────────────────────
            # Для obfuscated + contains/phrase используем текст БЕЗ пробелов
            # чтобы "Alice Demidova" → "алиседемидова" совпадало с паттерном
            if text_no_spaces is not None:
                # obfuscated категория — проверяем в тексте без пробелов
                search_text = text_no_spaces
                # Паттерн тоже без пробелов для корректного сравнения
                search_pattern = normalized_filter_word.replace(' ', '')
            else:
                # harmful/simple — проверяем в обычном тексте
                search_text = normalized_text
                search_pattern = normalized_filter_word

            is_found = search_pattern in search_text
            logger.info(
                f"[WordFilter] {filter_word.match_type.upper()} check: "
                f"'{normalized_filter_word}' in text = {is_found}"
            )
            if is_found:
                # Для whitelist проверяем полный текст, не отдельные слова
                # Если искомая фраза есть в whitelist - пропускаем
                if normalized_filter_word in whitelist:
                    logger.info(
                        f"[WordFilter] {filter_word.match_type.upper()} "
                        f"'{normalized_filter_word}' в whitelist, пропускаем"
                    )
                    return False
                return True
            return False

        else:
            # ─────────────────────────────────────────────────────
            # WORD / EXACT (по умолчанию): ищем как отдельное слово
            # ─────────────────────────────────────────────────────
            # Проверяем есть ли слово среди слов текста
            for text_word in text_words:
                # Точное совпадение слова
                if text_word == normalized_filter_word:
                    # Проверяем что слово не в whitelist
                    if text_word not in whitelist:
                        return True

            return False

    async def _get_filter_words(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> List[FilterWord]:
        """
        Загружает список запрещённых слов для группы из БД.

        TODO: Добавить кэширование в Redis для производительности.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Список объектов FilterWord
        """
        # Формируем запрос: все слова для данной группы
        query = select(FilterWord).where(FilterWord.chat_id == chat_id)

        # Выполняем запрос
        result = await session.execute(query)

        # Возвращаем список объектов
        return list(result.scalars().all())

    async def _get_whitelist(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> Set[str]:
        """
        Загружает whitelist (исключения) для группы.

        Whitelist содержит слова которые НЕ нужно фильтровать,
        даже если они похожи на запрещённые.
        Пример: "анализ" не должен срабатывать на "анал".

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Множество нормализованных слов-исключений
        """
        # Формируем запрос
        query = select(FilterWhitelist.normalized).where(
            FilterWhitelist.chat_id == chat_id
        )

        # Выполняем запрос
        result = await session.execute(query)

        # Возвращаем как множество для быстрого поиска O(1)
        return set(result.scalars().all())

    async def add_word(
        self,
        chat_id: int,
        word: str,
        created_by: int,
        session: AsyncSession,
        action: Optional[str] = None,
        action_duration: Optional[int] = None,
        match_type: str = 'word',
        category: Optional[str] = None
    ) -> FilterWord:
        """
        Добавляет новое запрещённое слово в БД.

        Args:
            chat_id: ID группы
            word: Слово/фраза для добавления
            created_by: ID пользователя который добавляет
            session: Сессия БД
            action: Индивидуальное действие (None = использовать default)
            action_duration: Длительность действия в минутах
            match_type: Тип совпадения (word, phrase, regex)
            category: Категория слова

        Returns:
            Созданный объект FilterWord
        """
        # Нормализуем слово для хранения
        normalized = self._normalizer.normalize_word(word)

        # ─────────────────────────────────────────────────────────
        # Проверка на дубликаты
        # Ищем существующее слово с таким же normalized текстом
        # ─────────────────────────────────────────────────────────
        existing = await session.execute(
            select(FilterWord).where(
                FilterWord.chat_id == chat_id,
                FilterWord.normalized == normalized
            )
        )
        # Получаем первый результат (или None)
        existing_word = existing.scalar_one_or_none()

        # Если слово уже существует — выбрасываем исключение
        if existing_word:
            raise ValueError(f"Слово уже существует: '{existing_word.word}'")

        # Создаём объект модели
        filter_word = FilterWord(
            chat_id=chat_id,
            word=word,
            normalized=normalized,
            match_type=match_type,
            action=action,
            action_duration=action_duration,
            category=category,
            created_by=created_by
        )

        # Добавляем в сессию
        session.add(filter_word)

        # Коммитим изменения
        await session.commit()

        # Обновляем объект из БД (получаем id)
        await session.refresh(filter_word)

        logger.info(
            f"[WordFilter] Добавлено слово '{word}' в чат {chat_id} "
            f"пользователем {created_by}"
        )

        return filter_word

    async def remove_word(
        self,
        chat_id: int,
        word: str,
        session: AsyncSession
    ) -> bool:
        """
        Удаляет запрещённое слово из БД.

        Args:
            chat_id: ID группы
            word: Слово для удаления
            session: Сессия БД

        Returns:
            True если слово было удалено, False если не найдено
        """
        # Ищем слово в БД
        query = select(FilterWord).where(
            FilterWord.chat_id == chat_id,
            FilterWord.word == word
        )
        result = await session.execute(query)
        filter_word = result.scalar_one_or_none()

        # Если слово не найдено
        if not filter_word:
            return False

        # Удаляем
        await session.delete(filter_word)
        await session.commit()

        logger.info(f"[WordFilter] Удалено слово '{word}' из чата {chat_id}")

        return True

    async def get_words_list(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> List[FilterWord]:
        """
        Возвращает список всех запрещённых слов группы.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Список объектов FilterWord
        """
        return await self._get_filter_words(chat_id, session)

    async def get_words_by_category(
        self,
        chat_id: int,
        session: AsyncSession,
        category: str
    ) -> List[FilterWord]:
        """
        Возвращает список слов группы по категории.

        Args:
            chat_id: ID группы
            session: Сессия БД
            category: Категория (simple, harmful, obfuscated)

        Returns:
            Список объектов FilterWord с указанной категорией
        """
        words = await self._get_filter_words(chat_id, session)
        return [w for w in words if w.category == category]

    async def get_words_count(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> int:
        """
        Возвращает количество запрещённых слов в группе.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            Количество слов
        """
        words = await self._get_filter_words(chat_id, session)
        return len(words)
