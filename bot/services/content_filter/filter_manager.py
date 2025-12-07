# ============================================================
# FILTER MANAGER - КООРДИНАТОР ВСЕХ ПОДМОДУЛЕЙ
# ============================================================
# Этот модуль координирует работу всех подмодулей фильтрации:
# - WordFilter: проверка на запрещённые слова
# - ScamDetector: эвристика скама
# - FloodDetector: повторяющиеся сообщения
#
# Также загружает настройки группы и применяет действия.
# ============================================================

# Импортируем типы для аннотаций
from typing import Optional, NamedTuple, List
# Импортируем логгер
import logging
# Импортируем datetime для работы со временем
from datetime import datetime, timedelta

# Импортируем типы aiogram
from aiogram.types import Message

# Импортируем SQLAlchemy компоненты
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем Redis для детекторов
from redis.asyncio import Redis

# Импортируем модели БД
from bot.database.models_content_filter import (
    ContentFilterSettings,
    FilterViolation
)
# Импортируем подмодули
from bot.services.content_filter.word_filter import WordFilter, WordMatchResult
from bot.services.content_filter.text_normalizer import TextNormalizer, get_normalizer
# Импортируем детекторы Phase 2
from bot.services.content_filter.scam_detector import ScamDetector, get_scam_detector
from bot.services.content_filter.flood_detector import FloodDetector, create_flood_detector

# Создаём логгер
logger = logging.getLogger(__name__)


class FilterResult(NamedTuple):
    """
    Результат проверки сообщения всеми фильтрами.

    Attributes:
        should_act: True если нужно применить действие
        detector_type: Какой детектор сработал (word_filter, scam, flood, referral)
        trigger: Что именно сработало (слово, описание)
        action: Какое действие применить (delete, warn, mute, kick, ban)
        action_duration: Длительность действия в минутах
        scam_score: Скор для scam_detector (или None)
        flood_message_ids: Список ID сообщений для удаления (только для flood)
        word_category: Категория слова (simple, harmful, obfuscated) для word_filter
    """
    # Флаг: нужно ли применять действие
    should_act: bool
    # Тип детектора который сработал
    detector_type: Optional[str] = None
    # Что сработало (слово, паттерн, описание)
    trigger: Optional[str] = None
    # Действие для применения
    action: Optional[str] = None
    # Длительность в минутах
    action_duration: Optional[int] = None
    # Скор (только для scam_detector)
    scam_score: Optional[int] = None
    # ID сообщений для удаления при флуде
    flood_message_ids: Optional[List[int]] = None
    # Категория слова (simple, harmful, obfuscated) для word_filter
    word_category: Optional[str] = None


class FilterManager:
    """
    Координатор всех подмодулей фильтрации контента.

    Отвечает за:
    - Загрузку настроек группы
    - Координацию вызовов подмодулей
    - Логирование нарушений в БД
    - Определение итогового действия

    Пример использования:
        manager = FilterManager()
        result = await manager.check_message(message, session)
        if result.should_act:
            # Применить действие result.action
            pass
    """

    def __init__(self, redis: Optional[Redis] = None):
        """
        Инициализация координатора.

        Создаёт экземпляры всех подмодулей.

        Args:
            redis: Клиент Redis (нужен для FloodDetector)
        """
        # Сохраняем ссылку на Redis
        self._redis = redis

        # Создаём нормализатор текста (общий для всех)
        self._normalizer = get_normalizer()

        # Создаём фильтр слов
        self._word_filter = WordFilter(normalizer=self._normalizer)

        # Создаём детектор скама (не требует Redis)
        self._scam_detector = get_scam_detector()

        # Детекторы требующие Redis (создаём только если Redis доступен)
        self._flood_detector: Optional[FloodDetector] = None

        # Если Redis передан - инициализируем детекторы
        if redis:
            self._flood_detector = create_flood_detector(redis)

    async def check_message(
        self,
        message: Message,
        session: AsyncSession
    ) -> FilterResult:
        """
        Проверяет сообщение всеми включёнными фильтрами.

        Порядок проверки:
        1. Загрузка настроек группы
        2. Flood detector (самый быстрый)
        3. Word filter (запрещённые слова)
        4. Scam detector (эвристика)

        Args:
            message: Сообщение для проверки
            session: Сессия БД

        Returns:
            FilterResult с информацией о срабатывании
        """
        # Получаем ID чата
        chat_id = message.chat.id

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Загружаем настройки группы
        # ─────────────────────────────────────────────────────────
        settings = await self._get_settings(chat_id, session)

        # Если настроек нет - модуль не настроен для этой группы
        if not settings:
            return FilterResult(should_act=False)

        # Если модуль выключен - пропускаем
        if not settings.enabled:
            return FilterResult(should_act=False)

        # Получаем текст сообщения
        text = message.text or message.caption or ''

        # Если текста нет - нечего проверять
        if not text.strip():
            return FilterResult(should_act=False)

        # Получаем user_id для детекторов
        user_id = message.from_user.id if message.from_user else 0

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Flood Detector (самый быстрый)
        # ─────────────────────────────────────────────────────────
        if settings.flood_detection_enabled and self._flood_detector:
            # Проверяем на флуд
            flood_result = await self._flood_detector.check(
                text=text,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message.message_id,
                max_repeats=settings.flood_max_repeats,
                time_window=settings.flood_time_window
            )

            # Если обнаружен флуд
            if flood_result.is_flood:
                # Определяем действие: сначала flood_action, потом default_action
                flood_action = settings.flood_action or settings.default_action
                flood_duration = settings.flood_mute_duration or settings.default_mute_duration

                logger.info(
                    f"[FilterManager] FloodDetector сработал в чате {chat_id}: "
                    f"повторов={flood_result.repeat_count}, action={flood_action}, "
                    f"messages_to_delete={len(flood_result.flood_message_ids)}"
                )

                return FilterResult(
                    should_act=True,
                    detector_type='flood',
                    trigger=f"Повтор #{flood_result.repeat_count}",
                    action=flood_action,
                    action_duration=flood_duration,
                    flood_message_ids=flood_result.flood_message_ids
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Word Filter (запрещённые слова)
        # ─────────────────────────────────────────────────────────
        if settings.word_filter_enabled:
            # Проверяем текст на запрещённые слова
            # Используем настройку word_filter_normalize для включения/выключения нормализатора
            word_result = await self._word_filter.check(
                text=text,
                chat_id=chat_id,
                session=session,
                use_normalizer=settings.word_filter_normalize
            )

            # Если найдено запрещённое слово
            if word_result.matched:
                # Определяем действие по приоритету:
                # 1. Индивидуальное действие слова (word_result.action)
                # 2. Действие категории слова (simple/harmful/obfuscated)
                # 3. Настройка для word_filter (settings.word_filter_action)
                # 4. Общий default (settings.default_action)

                action = word_result.action
                duration = word_result.action_duration

                # Если нет индивидуального действия - смотрим категорию
                if not action and word_result.category:
                    # Маппинг категорий на поля настроек
                    category_action_map = {
                        'simple': ('simple_words_action', 'simple_words_mute_duration'),
                        'harmful': ('harmful_words_action', 'harmful_words_mute_duration'),
                        'obfuscated': ('obfuscated_words_action', 'obfuscated_words_mute_duration')
                    }

                    # Получаем поля для категории
                    category_fields = category_action_map.get(word_result.category)
                    if category_fields:
                        action_field, duration_field = category_fields
                        # Получаем действие и длительность категории
                        action = getattr(settings, action_field, None)
                        duration = getattr(settings, duration_field, None)

                # Если всё ещё нет действия - используем общие настройки
                if not action:
                    action = settings.word_filter_action or settings.default_action
                if not duration:
                    duration = settings.word_filter_mute_duration or settings.default_mute_duration

                logger.info(
                    f"[FilterManager] WordFilter сработал в чате {chat_id}: "
                    f"слово='{word_result.word}', категория={word_result.category}, действие={action}"
                )

                return FilterResult(
                    should_act=True,
                    detector_type='word_filter',
                    trigger=word_result.word,
                    action=action,
                    action_duration=duration,
                    word_category=word_result.category  # Передаём категорию для кастомных настроек
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 4: Scam Detector (эвристика + кастомные паттерны)
        # ─────────────────────────────────────────────────────────
        if settings.scam_detection_enabled:
            # Проверяем на скам с учётом кастомных паттернов группы
            scam_result = await self._scam_detector.check_with_custom_patterns(
                text=text,
                chat_id=chat_id,
                session=session,
                sensitivity=settings.scam_sensitivity
            )

            # Если обнаружен скам
            if scam_result.is_scam:
                # Формируем описание сработавших сигналов
                signals_str = ', '.join(scam_result.triggered_signals[:3])

                logger.info(
                    f"[FilterManager] ScamDetector сработал в чате {chat_id}: "
                    f"score={scam_result.score}, сигналы={signals_str}"
                )

                return FilterResult(
                    should_act=True,
                    detector_type='scam',
                    trigger=signals_str,
                    action=settings.default_action,
                    action_duration=settings.default_mute_duration,
                    scam_score=scam_result.score
                )

        # Ничего не найдено
        return FilterResult(should_act=False)

    async def log_violation(
        self,
        message: Message,
        result: FilterResult,
        session: AsyncSession
    ) -> FilterViolation:
        """
        Записывает нарушение в таблицу filter_violations.

        Вызывается после применения действия для аудита.

        Args:
            message: Сообщение-нарушитель
            result: Результат проверки
            session: Сессия БД

        Returns:
            Созданный объект FilterViolation
        """
        # Создаём запись о нарушении
        violation = FilterViolation(
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            detector_type=result.detector_type or 'unknown',
            trigger=result.trigger,
            scam_score=result.scam_score,
            # Сохраняем первые 1000 символов текста
            message_text=(message.text or message.caption or '')[:1000],
            message_id=message.message_id,
            action_taken=result.action or 'unknown'
        )

        # Добавляем в сессию
        session.add(violation)

        # Коммитим
        await session.commit()

        logger.info(
            f"[FilterManager] Записано нарушение: "
            f"user={violation.user_id}, chat={violation.chat_id}, "
            f"detector={violation.detector_type}, action={violation.action_taken}"
        )

        return violation

    async def _get_settings(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> Optional[ContentFilterSettings]:
        """
        Загружает настройки content_filter для группы.

        TODO: Добавить кэширование в Redis.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            ContentFilterSettings или None если не настроено
        """
        # Формируем запрос
        query = select(ContentFilterSettings).where(
            ContentFilterSettings.chat_id == chat_id
        )

        # Выполняем
        result = await session.execute(query)

        # Возвращаем или None
        return result.scalar_one_or_none()

    async def get_or_create_settings(
        self,
        chat_id: int,
        session: AsyncSession
    ) -> ContentFilterSettings:
        """
        Возвращает настройки группы, создавая их если не существуют.

        Args:
            chat_id: ID группы
            session: Сессия БД

        Returns:
            ContentFilterSettings (существующие или новые)
        """
        # Пробуем получить существующие
        settings = await self._get_settings(chat_id, session)

        # Если есть - возвращаем
        if settings:
            return settings

        # Создаём новые с дефолтными значениями
        settings = ContentFilterSettings(chat_id=chat_id)

        # Добавляем в сессию
        session.add(settings)

        # Коммитим
        await session.commit()

        # Обновляем из БД
        await session.refresh(settings)

        logger.info(f"[FilterManager] Созданы настройки для чата {chat_id}")

        return settings

    async def toggle_module(
        self,
        chat_id: int,
        enabled: bool,
        session: AsyncSession
    ) -> ContentFilterSettings:
        """
        Включает или выключает весь модуль content_filter.

        Args:
            chat_id: ID группы
            enabled: True для включения, False для выключения
            session: Сессия БД

        Returns:
            Обновлённые настройки
        """
        # Получаем или создаём настройки
        settings = await self.get_or_create_settings(chat_id, session)

        # Обновляем флаг
        settings.enabled = enabled

        # Коммитим
        await session.commit()

        logger.info(
            f"[FilterManager] Модуль {'включён' if enabled else 'выключен'} "
            f"для чата {chat_id}"
        )

        return settings

    async def update_settings(
        self,
        chat_id: int,
        session: AsyncSession,
        **kwargs
    ) -> ContentFilterSettings:
        """
        Обновляет настройки модуля.

        Args:
            chat_id: ID группы
            session: Сессия БД
            **kwargs: Поля для обновления (например: scam_sensitivity=50)

        Returns:
            Обновлённые настройки
        """
        # Получаем или создаём настройки
        settings = await self.get_or_create_settings(chat_id, session)

        # Обновляем переданные поля
        for key, value in kwargs.items():
            # Проверяем что атрибут существует
            if hasattr(settings, key):
                setattr(settings, key, value)
            else:
                logger.warning(
                    f"[FilterManager] Неизвестный параметр настроек: {key}"
                )

        # Коммитим
        await session.commit()

        return settings

    async def get_violation_stats(
        self,
        chat_id: int,
        session: AsyncSession,
        days: int = 7
    ) -> dict:
        """
        Возвращает статистику нарушений за период.

        Args:
            chat_id: ID группы
            session: Сессия БД
            days: За сколько дней (по умолчанию 7)

        Returns:
            Словарь со статистикой:
            {
                'total': int,
                'by_detector': {'word_filter': int, 'scam': int, ...},
                'by_action': {'delete': int, 'mute': int, ...}
            }
        """
        # Вычисляем дату начала периода
        since = datetime.utcnow() - timedelta(days=days)

        # Запрашиваем нарушения за период
        query = select(FilterViolation).where(
            FilterViolation.chat_id == chat_id,
            FilterViolation.created_at >= since
        )

        result = await session.execute(query)
        violations = list(result.scalars().all())

        # Считаем статистику
        stats = {
            'total': len(violations),
            'by_detector': {},
            'by_action': {}
        }

        # Группируем по детектору
        for v in violations:
            # По типу детектора
            detector = v.detector_type
            stats['by_detector'][detector] = stats['by_detector'].get(detector, 0) + 1

            # По действию
            action = v.action_taken
            stats['by_action'][action] = stats['by_action'].get(action, 0) + 1

        return stats

    # ─────────────────────────────────────────────────────────
    # ПРЯМОЙ ДОСТУП К ПОДМОДУЛЯМ
    # ─────────────────────────────────────────────────────────

    @property
    def word_filter(self) -> WordFilter:
        """Возвращает экземпляр WordFilter для прямого использования."""
        return self._word_filter

    @property
    def normalizer(self) -> TextNormalizer:
        """Возвращает экземпляр TextNormalizer для прямого использования."""
        return self._normalizer
