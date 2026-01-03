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
# Импортируем re для работы с регулярными выражениями (word boundaries)
import re
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
from bot.services.content_filter.scam_detector import (
    ScamDetector, get_scam_detector,
    # Функции для fuzzy и n-gram matching (используются в CustomSpamSection)
    fuzzy_match, extract_ngrams, ngram_match
)
from bot.services.content_filter.flood_detector import FloodDetector, create_flood_detector
# Импортируем CAS сервис для проверки в глобальной базе спамеров
from bot.services.cas_service import is_cas_banned
# Импортируем spammer_registry для добавления в БД спаммеров
from bot.services.spammer_registry import record_spammer_incident

# Создаём логгер
logger = logging.getLogger(__name__)


class FilterResult(NamedTuple):
    """
    Результат проверки сообщения всеми фильтрами.

    Attributes:
        should_act: True если нужно применить действие
        detector_type: Какой детектор сработал (word_filter, scam, flood, custom_section)
        trigger: Что именно сработало (слово, описание)
        action: Какое действие применить (delete, warn, mute, kick, ban)
        action_duration: Длительность действия в минутах
        scam_score: Скор для scam_detector (или None)
        flood_message_ids: Список ID сообщений для удаления (только для flood)
        word_category: Категория слова (simple, harmful, obfuscated) для word_filter
        forward_channel_id: ID канала для пересылки
        section_name: Название кастомного раздела
        forward_on_delete: Пересылать в канал при действии delete
        forward_on_mute: Пересылать в канал при действии mute
        forward_on_ban: Пересылать в канал при действии ban
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
    # ID канала для пересылки
    forward_channel_id: Optional[int] = None
    # Название кастомного раздела
    section_name: Optional[str] = None
    # Флаги пересылки по действиям (для custom_section)
    forward_on_delete: bool = False
    forward_on_mute: bool = False
    forward_on_ban: bool = False
    # Кастомные тексты и задержки (для custom_section)
    custom_mute_text: Optional[str] = None
    custom_ban_text: Optional[str] = None
    custom_delete_delay: Optional[int] = None
    custom_notification_delay: Optional[int] = None
    # CAS и БД спаммеров (для custom_section)
    cas_banned: bool = False
    added_to_spammer_db: bool = False


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
            logger.info(f"[FilterManager] ❌ Нет настроек для чата {chat_id}")
            return FilterResult(should_act=False)

        # Логируем состояние модуля
        logger.info(
            f"[FilterManager] 📊 Настройки чата {chat_id}: "
            f"enabled={settings.enabled}, word_filter={settings.word_filter_enabled}, "
            f"scam={settings.scam_detection_enabled}, flood={settings.flood_detection_enabled}"
        )

        # Если модуль выключен - пропускаем
        if not settings.enabled:
            logger.info(f"[FilterManager] ⏸️ Модуль выключен для чата {chat_id}")
            return FilterResult(should_act=False)

        # Получаем текст сообщения
        text = message.text or message.caption or ''

        # Получаем user_id для детекторов
        user_id = message.from_user.id if message.from_user else 0

        # Определяем тип медиа (для медиа-флуда)
        # Поддерживаются ВСЕ типы медиа из Telegram API
        media_type: Optional[str] = None
        if message.photo:
            media_type = 'photo'
        elif message.sticker:
            media_type = 'sticker'
        elif message.video:
            media_type = 'video'
        elif message.animation:
            # GIF в Telegram API
            media_type = 'animation'
        elif message.voice:
            media_type = 'voice'
        elif message.video_note:
            media_type = 'video_note'
        elif message.audio:
            # Аудиофайлы/музыка
            media_type = 'audio'
        elif message.document:
            # Документы/файлы (не фото/видео/аудио)
            media_type = 'document'
        elif message.contact:
            media_type = 'contact'
        elif message.location:
            media_type = 'location'
        elif message.poll:
            media_type = 'poll'
        elif message.dice:
            # Кубик, дартс, боулинг и др. игры
            media_type = 'dice'

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
        # ШАГ 2.1: Расширенный антифлуд - любые сообщения подряд
        # ─────────────────────────────────────────────────────────
        # ВАЖНО: Проверяем media_group_id для поддержки альбомов
        # Альбом (несколько фото/видео сразу) = одно действие пользователя
        # Telegram отправляет каждое фото альбома как отдельное сообщение
        # Но все они имеют одинаковый media_group_id - пропускаем их
        is_album = bool(message.media_group_id)

        # Проверяем флуд любых сообщений ТОЛЬКО если это НЕ альбом
        if settings.flood_detect_any_messages and self._flood_detector and not is_album:
            # Проверяем на флуд любых сообщений (не только одинаковых)
            any_msg_result = await self._flood_detector.check_any_messages(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message.message_id,
                max_messages=settings.flood_any_max_messages,
                time_window=settings.flood_any_time_window
            )

            # Если обнаружен флуд любых сообщений
            if any_msg_result.is_flood:
                flood_action = settings.flood_action or settings.default_action
                flood_duration = settings.flood_mute_duration or settings.default_mute_duration

                logger.info(
                    f"[FilterManager] AnyMessagesFlood сработал в чате {chat_id}: "
                    f"сообщений={any_msg_result.repeat_count}, action={flood_action}"
                )

                return FilterResult(
                    should_act=True,
                    detector_type='flood',
                    trigger=f"Сообщений подряд: {any_msg_result.repeat_count}",
                    action=flood_action,
                    action_duration=flood_duration,
                    flood_message_ids=any_msg_result.flood_message_ids
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 2.2: Расширенный антифлуд - медиа (фото, стикеры, видео, войсы)
        # ─────────────────────────────────────────────────────────
        # is_album уже определён выше в ШАГ 2.1
        # Проверяем медиа-флуд ТОЛЬКО если это НЕ альбом
        if settings.flood_detect_media and self._flood_detector and media_type and not is_album:
            # Проверяем на медиа-флуд
            media_result = await self._flood_detector.check_media(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message.message_id,
                media_type=media_type,
                max_repeats=settings.flood_max_repeats,
                time_window=settings.flood_time_window
            )

            # Если обнаружен медиа-флуд
            if media_result.is_flood:
                flood_action = settings.flood_action or settings.default_action
                flood_duration = settings.flood_mute_duration or settings.default_mute_duration

                media_names = {
                    'photo': 'фото',
                    'sticker': 'стикеров',
                    'video': 'видео',
                    'animation': 'GIF',
                    'voice': 'голосовых',
                    'video_note': 'кружков',
                    'audio': 'аудио',
                    'document': 'документов',
                    'contact': 'контактов',
                    'location': 'геолокаций',
                    'poll': 'опросов',
                    'dice': 'игр'
                }
                media_name = media_names.get(media_type, media_type)

                logger.info(
                    f"[FilterManager] MediaFlood сработал в чате {chat_id}: "
                    f"тип={media_type}, кол-во={media_result.repeat_count}, action={flood_action}"
                )

                return FilterResult(
                    should_act=True,
                    detector_type='flood',
                    trigger=f"Флуд {media_name}: {media_result.repeat_count}",
                    action=flood_action,
                    action_duration=flood_duration,
                    flood_message_ids=media_result.flood_message_ids
                )

        # Если текста нет - дальше проверять нечего (word_filter и scam_detector работают с текстом)
        if not text.strip():
            return FilterResult(should_act=False)

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Word Filter (запрещённые слова)
        # ─────────────────────────────────────────────────────────
        if settings.word_filter_enabled:
            # Проверяем текст на запрещённые слова
            # Нормализация (l33tspeak) теперь применяется ТОЛЬКО к категории 'obfuscated'
            # Для simple/harmful используется простой lowercase matching
            word_result = await self._word_filter.check(
                text=text,
                chat_id=chat_id,
                session=session
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
        # ШАГ 4: Custom Sections (кастомные разделы спама)
        # ПРИОРИТЕТ: Разделы проверяются ПЕРВЫМИ перед общим scam_detector
        # ─────────────────────────────────────────────────────────
        # Проверяем текст на паттерны кастомных разделов.
        # Каждый раздел имеет свой набор паттернов, порог и действие.
        if settings.scam_detection_enabled and getattr(settings, 'custom_sections_enabled', True):
            from bot.services.content_filter.scam_pattern_service import get_section_service
            section_service = get_section_service()

            # Получаем все активные разделы группы
            sections = await section_service.get_sections(chat_id, session, enabled_only=True)

            # Логируем для отладки сколько разделов найдено
            logger.info(
                f"[FilterManager] CustomSections: chat={chat_id}, "
                f"разделов={len(sections) if sections else 0}"
            )

            if sections:
                # Нормализуем текст один раз
                normalized_text = self._normalizer.normalize(text).lower()

                for section in sections:
                    # Получаем паттерны раздела
                    patterns = await section_service.get_section_patterns(section.id, session, active_only=True)

                    # Логируем раздел и количество паттернов
                    logger.info(
                        f"[FilterManager] Раздел '{section.name}' (ID={section.id}): "
                        f"паттернов={len(patterns) if patterns else 0}, порог={section.threshold}"
                    )

                    if not patterns:
                        continue

                    # Вычисляем общий скор по паттернам
                    total_score = 0
                    triggered_patterns = []

                    # Предварительно извлекаем n-граммы из текста для n-gram matching
                    text_bigrams = extract_ngrams(normalized_text, n=2)
                    text_trigrams = extract_ngrams(normalized_text, n=3)

                    for pattern in patterns:
                        matched = False
                        match_method = None
                        match_context = None  # Контекст где найдено совпадение

                        # ─────────────────────────────────────────────────────
                        # МЕТОД 0: REGEX (точное совпадение по регулярному выражению)
                        # Для паттернов с pattern_type='regex' — используем только regex
                        # и пропускаем phrase/fuzzy/ngram методы
                        # ─────────────────────────────────────────────────────
                        if pattern.pattern_type == 'regex':
                            try:
                                # Компилируем regex с флагами регистронезависимости и Unicode
                                regex = re.compile(pattern.pattern, re.IGNORECASE | re.UNICODE)
                                # Ищем в нормализованном тексте
                                match_obj = regex.search(normalized_text)
                                # Если не нашли — пробуем в оригинальном тексте (lowercase)
                                if not match_obj:
                                    match_obj = regex.search(text.lower())

                                if match_obj:
                                    matched = True
                                    match_method = 'regex'
                                    # Формируем контекст совпадения
                                    pos = match_obj.start()
                                    matched_text = match_obj.group()
                                    # Берём контекст: 20 символов до и после
                                    source_text = normalized_text if match_obj.string == normalized_text else text.lower()
                                    start = max(0, pos - 20)
                                    end = min(len(source_text), pos + len(matched_text) + 20)
                                    match_context = source_text[start:end]
                                    if start > 0:
                                        match_context = "..." + match_context
                                    if end < len(source_text):
                                        match_context = match_context + "..."
                            except re.error as e:
                                # Некорректный regex — логируем и пропускаем паттерн
                                logger.warning(
                                    f"[FilterManager] Некорректный regex паттерн #{pattern.id}: "
                                    f"'{pattern.pattern}' — ошибка: {e}"
                                )
                                continue

                            # Обрабатываем результат regex и переходим к следующему паттерну
                            # ВАЖНО: regex паттерны НЕ используют fuzzy/ngram
                            if matched:
                                total_score += pattern.weight
                                # Формируем строку с контекстом для отображения
                                trigger_info = f"{pattern.pattern} [{match_method}]"
                                if match_context:
                                    trigger_info += f" → найдено в: «{match_context}»"
                                triggered_patterns.append(trigger_info)

                                # Увеличиваем счётчик срабатываний
                                await section_service.increment_pattern_trigger(pattern.id, session)

                                # Детальный лог для отладки
                                logger.info(
                                    f"[FilterManager] 🔍 REGEX MATCH: паттерн='{pattern.pattern}' "
                                    f"[{match_method}] +{pattern.weight} баллов\n"
                                    f"    📍 Контекст: {match_context}\n"
                                    f"    📝 Норм.текст (первые 200 симв): {normalized_text[:200]}..."
                                )
                            # Переходим к следующему паттерну — пропускаем phrase/fuzzy/ngram
                            continue

                        # ─────────────────────────────────────────────────────
                        # МЕТОД 1: Точное совпадение подстроки
                        # Для КОРОТКИХ паттернов (< 5 символов) требуем границы слов
                        # чтобы избежать ложных срабатываний (weed→вед в "ведущая")
                        # ─────────────────────────────────────────────────────
                        pattern_norm_lower = pattern.normalized.lower()

                        # Для коротких паттернов используем word boundaries
                        if len(pattern_norm_lower) < 5:
                            # Ищем как отдельное слово с границами \b
                            word_boundary_regex = r'\b' + re.escape(pattern_norm_lower) + r'\b'
                            match_obj = re.search(word_boundary_regex, normalized_text)
                            if match_obj:
                                matched = True
                                match_method = 'phrase'
                                pos = match_obj.start()
                                # Берём контекст: 20 символов до и после
                                start = max(0, pos - 20)
                                end = min(len(normalized_text), pos + len(pattern_norm_lower) + 20)
                                match_context = normalized_text[start:end]
                                if start > 0:
                                    match_context = "..." + match_context
                                if end < len(normalized_text):
                                    match_context = match_context + "..."
                        else:
                            # Для длинных паттернов - обычный поиск подстроки
                            if pattern_norm_lower in normalized_text:
                                matched = True
                                match_method = 'phrase'
                                # Находим позицию совпадения для контекста
                                pos = normalized_text.find(pattern_norm_lower)
                                if pos >= 0:
                                    # Берём контекст: 20 символов до и после
                                    start = max(0, pos - 20)
                                    end = min(len(normalized_text), pos + len(pattern_norm_lower) + 20)
                                    match_context = normalized_text[start:end]
                                    # Добавляем маркер где именно совпадение
                                    if start > 0:
                                        match_context = "..." + match_context
                                    if end < len(normalized_text):
                                        match_context = match_context + "..."

                        # ─────────────────────────────────────────────────────
                        # МЕТОД 2: Fuzzy matching (порог 0.8)
                        # Ловит перестановки слов и небольшие изменения
                        # ─────────────────────────────────────────────────────
                        # ВАЖНО: Для длинных текстов (>400 символов) отключаем fuzzy
                        # для коротких паттернов (<8 символов), чтобы избежать
                        # ложных срабатываний типа "в руки" → "в руский" (83% similarity)
                        # Для коротких текстов (спам) fuzzy работает как раньше
                        # ─────────────────────────────────────────────────────
                        min_pattern_len_for_fuzzy = 8 if len(normalized_text) > 400 else 5
                        if not matched and len(pattern_norm_lower) >= min_pattern_len_for_fuzzy:
                            if fuzzy_match(normalized_text, pattern.normalized, threshold=0.8):
                                matched = True
                                match_method = 'fuzzy'
                                # Показываем нормализованную форму паттерна
                                match_context = f"fuzzy ~ '{pattern.normalized}'"

                        # ─────────────────────────────────────────────────────
                        # МЕТОД 3: N-gram matching (перекрытие 0.6)
                        # Ловит перестановки слов в длинных фразах
                        # ─────────────────────────────────────────────────────
                        if not matched:
                            pattern_words = pattern.normalized.split()
                            # Биграммы для паттернов из 2+ слов
                            if len(pattern_words) >= 2:
                                pattern_bigrams = extract_ngrams(pattern.normalized, n=2)
                                if ngram_match(text_bigrams, pattern_bigrams, min_overlap=0.6):
                                    matched = True
                                    match_method = 'ngram'
                                    # Показываем нормализованную форму паттерна
                                    match_context = f"ngram ~ '{pattern.normalized}'"
                            # Триграммы для паттернов из 3+ слов
                            if not matched and len(pattern_words) >= 3:
                                pattern_trigrams = extract_ngrams(pattern.normalized, n=3)
                                if ngram_match(text_trigrams, pattern_trigrams, min_overlap=0.5):
                                    matched = True
                                    match_method = 'ngram'
                                    # Показываем нормализованную форму паттерна
                                    match_context = f"ngram ~ '{pattern.normalized}'"

                        # Если паттерн сработал - добавляем скор
                        if matched:
                            total_score += pattern.weight
                            # Формируем строку с контекстом для отображения
                            trigger_info = f"{pattern.pattern} [{match_method}]"
                            if match_context:
                                trigger_info += f" → найдено в: «{match_context}»"
                            triggered_patterns.append(trigger_info)

                            # Увеличиваем счётчик срабатываний
                            await section_service.increment_pattern_trigger(pattern.id, session)

                            # ВАЖНО: Детальный лог для отладки
                            logger.info(
                                f"[FilterManager] 🔍 MATCH: паттерн='{pattern.pattern}' "
                                f"(norm='{pattern.normalized}') [{match_method}] +{pattern.weight} баллов\n"
                                f"    📍 Контекст: {match_context}\n"
                                f"    📝 Норм.текст (первые 200 симв): {normalized_text[:200]}..."
                            )

                    # Проверяем достижен ли порог
                    if total_score >= section.threshold:
                        # Раздел сработал!
                        trigger_str = ', '.join(triggered_patterns[:3])
                        if len(triggered_patterns) > 3:
                            trigger_str += f" (+{len(triggered_patterns) - 3})"

                        # ─────────────────────────────────────────────────────
                        # ПРОВЕРЯЕМ ПОРОГИ БАЛЛОВ РАЗДЕЛА (Баг 1 fix)
                        # Если есть подходящий порог — используем его action
                        # Если нет — используем action из самого раздела
                        # ─────────────────────────────────────────────────────
                        threshold_result = await section_service.get_action_for_section_score(
                            section_id=section.id,
                            score=total_score,
                            session=session
                        )

                        # Определяем финальное действие и длительность
                        if threshold_result:
                            # Нашли подходящий порог — используем его
                            final_action = threshold_result[0]
                            final_mute_duration = threshold_result[1] or section.mute_duration
                            logger.info(
                                f"[FilterManager] CustomSection '{section.name}': "
                                f"порог баллов {total_score} → {final_action}"
                            )
                        else:
                            # Порог не найден — используем action из раздела
                            final_action = section.action
                            final_mute_duration = section.mute_duration

                        logger.info(
                            f"[FilterManager] CustomSection '{section.name}' сработал в чате {chat_id}: "
                            f"score={total_score}, порог={section.threshold}, action={final_action}"
                        )

                        # ─────────────────────────────────────────────────────
                        # CAS (COMBOT ANTI-SPAM) ПРОВЕРКА
                        # ─────────────────────────────────────────────────────
                        cas_banned = False
                        if section.cas_enabled:
                            try:
                                cas_banned = await is_cas_banned(user_id)
                                if cas_banned:
                                    logger.info(
                                        f"[FilterManager] CAS: user_id={user_id} найден в базе CAS!"
                                    )
                            except Exception as e:
                                logger.warning(f"[FilterManager] CAS ошибка: {e}")

                        # ─────────────────────────────────────────────────────
                        # ДОБАВЛЕНИЕ В ГЛОБАЛЬНУЮ БД СПАММЕРОВ
                        # Добавляем только при срабатывании САМОГО ВЫСОКОГО порога
                        # чтобы избежать ложных попаданий в БД спамеров
                        # ─────────────────────────────────────────────────────
                        added_to_spammer_db = False
                        if section.add_to_spammer_db:
                            # Получаем все активные пороги раздела
                            all_thresholds = await section_service.get_section_thresholds(
                                section.id, session, enabled_only=True
                            )

                            # Определяем, попадает ли score в самый высокий порог
                            should_add_to_db = False
                            if all_thresholds:
                                # Находим порог с максимальным min_score (самый строгий)
                                highest_threshold = max(all_thresholds, key=lambda t: t.min_score)
                                # Добавляем в БД только если score >= min_score самого высокого порога
                                if total_score >= highest_threshold.min_score:
                                    should_add_to_db = True
                                    logger.info(
                                        f"[FilterManager] Score {total_score} >= {highest_threshold.min_score} "
                                        f"(самый высокий порог) → добавляем в БД спаммеров"
                                    )
                                else:
                                    logger.info(
                                        f"[FilterManager] Score {total_score} < {highest_threshold.min_score} "
                                        f"(самый высокий порог) → НЕ добавляем в БД спаммеров"
                                    )
                            else:
                                # Нет порогов — добавляем по старой логике (флаг раздела)
                                should_add_to_db = True
                                logger.info(
                                    f"[FilterManager] Нет порогов в разделе, добавляем в БД спаммеров по флагу"
                                )

                            if should_add_to_db:
                                try:
                                    await record_spammer_incident(
                                        session=session,
                                        user_id=user_id,
                                        risk_score=total_score,
                                        reason=f"custom_section:{section.name}"
                                    )
                                    added_to_spammer_db = True
                                    logger.info(
                                        f"[FilterManager] Спаммер добавлен в БД: "
                                        f"user_id={user_id}, section={section.name}"
                                    )
                                except Exception as e:
                                    logger.warning(f"[FilterManager] Ошибка добавления в БД спаммеров: {e}")

                        return FilterResult(
                            should_act=True,
                            detector_type='custom_section',
                            trigger=trigger_str,
                            action=final_action,
                            action_duration=final_mute_duration,
                            scam_score=total_score,
                            forward_channel_id=section.forward_channel_id,
                            section_name=section.name,
                            forward_on_delete=section.forward_on_delete,
                            forward_on_mute=section.forward_on_mute,
                            forward_on_ban=section.forward_on_ban,
                            # Передаём кастомные тексты и задержки из раздела
                            custom_mute_text=section.mute_text,
                            custom_ban_text=section.ban_text,
                            custom_delete_delay=section.delete_delay,
                            custom_notification_delay=section.notification_delete_delay,
                            # CAS и БД спаммеров
                            cas_banned=cas_banned,
                            added_to_spammer_db=added_to_spammer_db
                        )

        # ─────────────────────────────────────────────────────────
        # ШАГ 5: Scam Detector (эвристика + кастомные паттерны)
        # Проверяется ПОСЛЕ Custom Sections
        # ─────────────────────────────────────────────────────────
        if settings.scam_detection_enabled and getattr(settings, 'scam_detector_enabled', True):
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

                # ─────────────────────────────────────────────────────
                # ОПРЕДЕЛЯЕМ ДЕЙСТВИЕ ПО ПОРОГАМ БАЛЛОВ
                # ─────────────────────────────────────────────────────
                # Проверяем есть ли подходящий порог для данного скора
                # Если есть - используем его action/mute_duration
                # Если нет - используем scam_action из настроек (или default_action)
                from bot.services.content_filter.scam_pattern_service import get_threshold_service
                threshold_service = get_threshold_service()

                # Получаем действие на основе порогов баллов
                threshold_result = await threshold_service.get_action_for_score(
                    chat_id=chat_id,
                    score=scam_result.score,
                    session=session
                )

                # Определяем финальное действие и длительность мута
                if threshold_result:
                    # Нашли подходящий порог - используем его настройки
                    action = threshold_result[0]  # action из порога
                    mute_duration = threshold_result[1]  # mute_duration из порога
                    # Если mute_duration не задан в пороге - берём из настроек
                    if mute_duration is None:
                        mute_duration = settings.scam_mute_duration or settings.default_mute_duration
                    logger.info(
                        f"[FilterManager] Порог баллов: {scam_result.score} → {action}"
                    )
                else:
                    # Порог не найден - используем scam_action или default_action
                    action = settings.scam_action or settings.default_action
                    mute_duration = settings.scam_mute_duration or settings.default_mute_duration

                return FilterResult(
                    should_act=True,
                    detector_type='scam',
                    trigger=signals_str,
                    action=action,
                    action_duration=mute_duration,
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
