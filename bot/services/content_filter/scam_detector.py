# ============================================================
# SCAM DETECTOR - ЭВРИСТИЧЕСКИЙ ДЕТЕКТОР СКАМА
# ============================================================
# Этот модуль определяет скам-сообщения на основе набора
# эвристических правил с подсчётом общего балла.
#
# Каждое правило имеет свой вес (score). Если сумма баллов
# превышает порог чувствительности — сообщение считается скамом.
#
# Пороги:
# - 40: высокая чувствительность (больше false positives)
# - 60: средняя чувствительность (рекомендуется)
# - 90: низкая чувствительность (только явный скам)
# ============================================================

# Импортируем модуль регулярных выражений
import re
# Импортируем типы для аннотаций
from typing import Optional, List, NamedTuple, Dict, Set, TYPE_CHECKING
# Импортируем логгер для записи событий
import logging
# Импортируем datetime для обновления времени срабатывания
from datetime import datetime
# Импортируем asyncio для async wrapper
import asyncio
# Импортируем ThreadPoolExecutor для выноса CPU-heavy операций из event loop
from concurrent.futures import ThreadPoolExecutor
# Импортируем functools для partial
from functools import partial
# Импортируем rapidfuzz для быстрого fuzzy matching (C-реализация, ~100x быстрее difflib)
from rapidfuzz import fuzz

# ============================================================
# ГЛОБАЛЬНЫЙ THREAD POOL ДЛЯ CPU-HEAVY ОПЕРАЦИЙ
# ============================================================
# Используем 2 потока - достаточно для fuzzy matching, не перегружает систему
_fuzzy_executor: Optional[ThreadPoolExecutor] = None


def _get_fuzzy_executor() -> ThreadPoolExecutor:
    """Lazy-инициализация ThreadPoolExecutor для fuzzy matching."""
    global _fuzzy_executor
    if _fuzzy_executor is None:
        _fuzzy_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fuzzy_match")
    return _fuzzy_executor

# Импортируем нормализатор текста
from bot.services.content_filter.text_normalizer import TextNormalizer, get_normalizer

# Type checking импорты (только для аннотаций)
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ
# ============================================================

class ScamCheckResult(NamedTuple):
    """
    Результат проверки на скам.

    Attributes:
        is_scam: True если сообщение определено как скам
        score: Набранный балл (0-100+)
        triggered_signals: Список сработавших сигналов
        threshold: Порог чувствительности который использовался
    """
    # Флаг: является ли сообщение скамом
    is_scam: bool
    # Набранный балл
    score: int
    # Список сработавших сигналов (для логирования)
    triggered_signals: List[str]
    # Порог который использовался
    threshold: int


# ============================================================
# СИГНАЛЫ СКАМА (эвристические правила)
# ============================================================

# Каждый сигнал содержит:
# - pattern: регулярное выражение для поиска
# - score: балл за срабатывание
# - description: описание для логов
SCAM_SIGNALS: Dict[str, Dict] = {
    # ─────────────────────────────────────────────────────────
    # ДЕНЬГИ И СУММЫ (25 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: число + валюта (доллары, рубли, символы валют)
    'money_amount': {
        'pattern': r'\d+\s*(доллар|рубл|бакс|\$|€|₽|usd|usdt|руб)',
        'score': 25,
        'description': 'Упоминание суммы денег'
    },

    # ─────────────────────────────────────────────────────────
    # ПЕРИОДИЧНОСТЬ ДОХОДА (20 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "в день", "в неделю", "ежедневно" и т.д.
    'income_period': {
        'pattern': r'(в\s*день|в\s*неделю|в\s*месяц|ежедневн|еженедельн|ежемесячн)',
        'score': 20,
        'description': 'Периодичность дохода'
    },

    # ─────────────────────────────────────────────────────────
    # ЛЁГКИЕ ДЕНЬГИ (15 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: обещания лёгкого заработка
    'easy_money': {
        'pattern': r'(легк\w*\s*(заработ|деньг|доход)|без\s*(вложен|напряг|опыт)|пассивн\w*\s*доход|гарантир\w*\s*(доход|заработ)|стабильн\w*\s*(доход|заработ))',
        'score': 15,
        'description': 'Обещание лёгкого заработка'
    },

    # ─────────────────────────────────────────────────────────
    # ПРИЗЫВ К ДЕЙСТВИЮ + КОНТАКТ (30 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "пишите" + @username в пределах 30 символов
    'call_to_action': {
        'pattern': r'(пиш\w*|обращай\w*|подробност\w*|свяж\w*|стуч\w*).{0,30}@\w+',
        'score': 30,
        'description': 'Призыв писать в личку'
    },

    # ─────────────────────────────────────────────────────────
    # КРИПТО (15 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: криптобиржи и крипто-термины
    'crypto': {
        'pattern': r'(bybit|binance|okx|huobi|crypto|крипт\w*|битко\w*|биток|эфир\w*|токен\w*|nft)',
        'score': 15,
        'description': 'Криптовалюта/биржи'
    },

    # ─────────────────────────────────────────────────────────
    # НАБОР В КОМАНДУ (20 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "набираю в команду", "требуются люди"
    'recruitment': {
        'pattern': r'(набира\w*|возьм\w*|требу\w*|ищ[уе]\w*).{0,20}(команд\w*|человек|людей|сотрудник\w*|партн[её]р\w*)',
        'score': 20,
        'description': 'Набор в команду'
    },

    # ─────────────────────────────────────────────────────────
    # УДАЛЁННАЯ РАБОТА (15 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "удалённая работа" в контексте заработка
    'remote_work': {
        'pattern': r'удал[её]нн\w*.{0,15}(работ\w*|деятельност\w*|заработ\w*|занятост\w*)',
        'score': 15,
        'description': 'Удалённая работа'
    },

    # ─────────────────────────────────────────────────────────
    # МНОГО ВОСКЛИЦАНИЙ (10 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: 3+ восклицательных знака подряд или много по тексту
    'exclamations': {
        'pattern': r'!{3,}',
        'score': 10,
        'description': 'Много восклицаний'
    },

    # ─────────────────────────────────────────────────────────
    # СРОЧНОСТЬ (15 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "срочно", "только сегодня", "последний шанс"
    'urgency': {
        'pattern': r'(срочн\w*|только\s*сегодн\w*|последн\w*\s*шанс|не\s*упусти\w*|торопи\w*)',
        'score': 15,
        'description': 'Срочность/давление'
    },

    # ─────────────────────────────────────────────────────────
    # СХЕМА/ПРОЕКТ (15 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: упоминание "схемы", "проекта" в контексте заработка
    'scheme': {
        'pattern': r'(схем\w*|проект\w*).{0,20}(заработ\w*|доход\w*|прибыл\w*)',
        'score': 15,
        'description': 'Схема заработка'
    },

    # ─────────────────────────────────────────────────────────
    # ОБУЧЕНИЕ ЗА ДЕНЬГИ (10 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "обучу", "научу", "курс"
    'training': {
        'pattern': r'(обуч\w*|науч\w*|курс\w*|менторств\w*).{0,20}(бесплатн\w*|платн\w*|недорог\w*)',
        'score': 10,
        'description': 'Обучение/курсы'
    },

    # ─────────────────────────────────────────────────────────
    # ИНВЕСТИЦИИ (20 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "инвестиции", "вложения", "вклад"
    'investments': {
        'pattern': r'(инвестиц\w*|вложен\w*|вклад\w*).{0,20}(доход\w*|прибыл\w*|процент\w*|\d+%)',
        'score': 20,
        'description': 'Инвестиции с доходом'
    },

    # ─────────────────────────────────────────────────────────
    # КАЗИНО/СТАВКИ (25 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: казино, ставки, слоты
    'gambling': {
        'pattern': r'(казино|ставк\w*|слот\w*|букмекер\w*|1xbet|1хбет|pin.?up|пин.?ап)',
        'score': 25,
        'description': 'Казино/ставки'
    },

    # ─────────────────────────────────────────────────────────
    # ВОЗРАСТНЫЕ ОГРАНИЧЕНИЯ (10 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "от 18 лет", "18+"
    'age_restriction': {
        'pattern': r'(от\s*18|18\+|совершеннолетн\w*)',
        'score': 10,
        'description': 'Возрастные ограничения'
    },

    # ─────────────────────────────────────────────────────────
    # УНИКАЛЬНОЕ ПРЕДЛОЖЕНИЕ (10 баллов)
    # ─────────────────────────────────────────────────────────
    # Паттерн: "уникальный", "эксклюзивный"
    'unique_offer': {
        'pattern': r'(уникальн\w*|эксклюзивн\w*|особ\w*\s*предложен\w*)',
        'score': 10,
        'description': 'Уникальное предложение'
    },
}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПРОДВИНУТОЙ ДЕТЕКЦИИ
# ============================================================

def fuzzy_match(text: str, pattern: str, threshold: float = 0.8) -> bool:
    """
    Проверяет нечёткое совпадение текста с паттерном.

    Использует rapidfuzz (C-реализация) для быстрого определения сходства строк.
    Полезно для обнаружения текста с опечатками или небольшими изменениями.

    ОПТИМИЗАЦИЯ: rapidfuzz в ~100x быстрее стандартного difflib.SequenceMatcher
    и уже реализует скользящее окно внутри partial_ratio.

    Args:
        text: Текст для проверки (нормализованный)
        pattern: Паттерн для поиска (нормализованный)
        threshold: Порог сходства (0.0-1.0), по умолчанию 0.8

    Returns:
        True если найдено совпадение >= threshold
    """
    pattern_lower = pattern.lower()
    text_lower = text.lower()
    pattern_len = len(pattern_lower)

    # Минимальная длина для проверки - для коротких паттернов точное совпадение
    if pattern_len < 3:
        return pattern_lower in text_lower

    # ─────────────────────────────────────────────────────────
    # ФИКС БАГА (2026-01-03): проверяем минимальную длину ТЕКСТА
    # ─────────────────────────────────────────────────────────
    # partial_ratio ищет короткую строку внутри длинной.
    # Когда text="Я" (1 символ), partial_ratio("обменяю usdt", "я") = 100%
    # потому что буква "я" есть в слове "обменЯю".
    # Это приводило к false positive: score=4870 для сообщения "Я".
    # Для коротких текстов fuzzy matching не имеет смысла — используем точное вхождение.
    if len(text_lower) < 4:
        return pattern_lower in text_lower

    # ─────────────────────────────────────────────────────────
    # ФИКС БАГА (2026-01-08): проверяем СООТНОШЕНИЕ длин текста и паттерна
    # ─────────────────────────────────────────────────────────
    # partial_ratio("есть зелёная белый", "есть") = 100%, потому что
    # "есть" полностью содержится в паттерне как подстрока.
    # Это приводило к false positive: текст "Есть" матчился с длинными
    # паттернами типа "есть зелёная белый", "меня есть зелёная" и т.д.
    # Если текст значительно короче паттерна (<60% длины) — это не fuzzy match,
    # а просто совпадение одного слова из паттерна. Используем точное вхождение.
    # Порог 0.6 выбран чтобы убрать граничные случаи типа "В лс"(4) vs "жду в лс"(8).
    if len(text_lower) < len(pattern_lower) * 0.6:
        return pattern_lower in text_lower

    # Конвертируем threshold из 0.0-1.0 в 0-100 (rapidfuzz использует 0-100)
    threshold_100 = threshold * 100

    # rapidfuzz.fuzz.partial_ratio уже реализует скользящее окно внутри
    # и работает в ~100x быстрее чем SequenceMatcher
    score = fuzz.partial_ratio(pattern_lower, text_lower)
    if score >= threshold_100:
        return True

    # Также проверяем слова целиком (для коротких паттернов = длине слова)
    # Используем fuzz.ratio для полного сравнения слов
    words = text_lower.split()
    for word in words:
        if len(word) >= 3:
            word_score = fuzz.ratio(pattern_lower, word)
            if word_score >= threshold_100:
                return True

    return False


def get_fuzzy_match_context(text: str, pattern: str, threshold: float = 0.8) -> tuple:
    """
    Находит какое слово/фраза из текста сработало на fuzzy match.

    ВАЖНО: Эта функция вызывается ПОСЛЕ детекции, только для логирования!
    Она НЕ влияет на логику детекции — только показывает контекст в журнале.

    Args:
        text: Нормализованный текст сообщения
        pattern: Нормализованный паттерн который сработал
        threshold: Порог совпадения (0.0-1.0)

    Returns:
        tuple[str, int]: (слово_из_текста, процент_совпадения)
        Если не удалось найти — возвращает (начало_текста, overall_score)
    """
    # Приводим к нижнему регистру для сравнения
    pattern_lower = pattern.lower()
    text_lower = text.lower()

    # Конвертируем threshold в проценты для rapidfuzz (0-100)
    threshold_100 = threshold * 100

    # Лучшее совпадение по умолчанию
    best_match = ""
    best_score = 0

    # ─────────────────────────────────────────────────────
    # МЕТОД 1: Проверяем отдельные слова
    # Ищем слово из текста которое максимально похоже на паттерн
    # ─────────────────────────────────────────────────────
    words = text_lower.split()
    for word in words:
        # Пропускаем слишком короткие слова
        if len(word) < 3:
            continue

        # Вычисляем схожесть слова с паттерном
        score = fuzz.ratio(pattern_lower, word)

        # Если это лучшее совпадение — запоминаем
        if score > best_score:
            best_score = score
            best_match = word

    # ─────────────────────────────────────────────────────
    # МЕТОД 2: Скользящее окно (если по словам не нашли хорошее)
    # Ищем подстроку текста размером ~длина паттерна
    # ─────────────────────────────────────────────────────
    if best_score < threshold_100:
        # Размер окна = длина паттерна +/- 20%
        window_size = len(pattern_lower)
        min_window = max(3, int(window_size * 0.8))
        max_window = int(window_size * 1.2)

        # Проходим по тексту скользящим окном
        for win_size in range(min_window, max_window + 1):
            for i in range(len(text_lower) - win_size + 1):
                # Извлекаем подстроку
                substring = text_lower[i:i + win_size]

                # Вычисляем схожесть
                score = fuzz.ratio(pattern_lower, substring)

                # Если это лучшее совпадение — запоминаем
                if score > best_score:
                    best_score = score
                    best_match = substring

    # ─────────────────────────────────────────────────────
    # МЕТОД 3: Если всё ещё не нашли — используем partial_ratio
    # Показываем начало текста как контекст
    # ─────────────────────────────────────────────────────
    if not best_match or best_score < 50:
        # Вычисляем общий partial_ratio для информации
        overall_score = fuzz.partial_ratio(pattern_lower, text_lower)

        # Возвращаем начало текста как контекст
        context_len = min(50, len(text))
        best_match = text[:context_len] + ("..." if len(text) > context_len else "")
        best_score = overall_score

    return (best_match, int(best_score))


async def fuzzy_match_async(text: str, pattern: str, threshold: float = 0.8) -> bool:
    """
    Асинхронная версия fuzzy_match с выполнением в отдельном потоке.

    Используется для очень длинных текстов (>5000 символов) чтобы не блокировать event loop.
    Для обычных текстов можно использовать синхронную версию fuzzy_match.

    Args:
        text: Текст для проверки (нормализованный)
        pattern: Паттерн для поиска (нормализованный)
        threshold: Порог сходства (0.0-1.0), по умолчанию 0.8

    Returns:
        True если найдено совпадение >= threshold
    """
    loop = asyncio.get_event_loop()
    executor = _get_fuzzy_executor()
    return await loop.run_in_executor(
        executor,
        partial(fuzzy_match, text, pattern, threshold)
    )


def fuzzy_match_batch(text: str, patterns: List[str], threshold: float = 0.8) -> List[bool]:
    """
    Пакетная проверка нескольких паттернов против одного текста.

    Оптимизирована для случаев когда нужно проверить много паттернов
    против одного текста - нормализация текста делается один раз.

    Args:
        text: Текст для проверки (нормализованный)
        patterns: Список паттернов для поиска
        threshold: Порог сходства (0.0-1.0), по умолчанию 0.8

    Returns:
        Список булевых значений - результат для каждого паттерна
    """
    text_lower = text.lower()
    threshold_100 = threshold * 100
    words = text_lower.split()
    results = []

    # ─────────────────────────────────────────────────────────
    # ФИКС БАГА (2026-01-03): проверяем минимальную длину ТЕКСТА
    # ─────────────────────────────────────────────────────────
    # Если текст слишком короткий — только точное вхождение для всех паттернов
    if len(text_lower) < 4:
        for pattern in patterns:
            pattern_lower = pattern.lower()
            results.append(pattern_lower in text_lower)
        return results

    # Длина текста — вычисляем один раз для всех паттернов
    text_len = len(text_lower)

    for pattern in patterns:
        pattern_lower = pattern.lower()
        pattern_len = len(pattern_lower)

        # Для коротких паттернов — только точное вхождение
        if pattern_len < 3:
            results.append(pattern_lower in text_lower)
            continue

        # ─────────────────────────────────────────────────────────
        # ФИКС БАГА (2026-01-08): проверяем СООТНОШЕНИЕ длин
        # ─────────────────────────────────────────────────────────
        # Если текст значительно короче паттерна (<60% длины) — только точное вхождение.
        # Защита от false positive: "Есть" → "есть зелёная белый", "В лс" → "жду в лс"
        if text_len < pattern_len * 0.6:
            results.append(pattern_lower in text_lower)
            continue

        # Проверяем partial_ratio
        score = fuzz.partial_ratio(pattern_lower, text_lower)
        if score >= threshold_100:
            results.append(True)
            continue

        # Проверяем слова
        found = False
        for word in words:
            if len(word) >= 3:
                word_score = fuzz.ratio(pattern_lower, word)
                if word_score >= threshold_100:
                    found = True
                    break
        results.append(found)

    return results


async def fuzzy_match_batch_async(
    text: str, patterns: List[str], threshold: float = 0.8
) -> List[bool]:
    """
    Асинхронная версия пакетной проверки паттернов.

    Выполняется в отдельном потоке чтобы не блокировать event loop
    при проверке большого количества паттернов.

    Args:
        text: Текст для проверки
        patterns: Список паттернов
        threshold: Порог сходства

    Returns:
        Список результатов для каждого паттерна
    """
    loop = asyncio.get_event_loop()
    executor = _get_fuzzy_executor()
    return await loop.run_in_executor(
        executor,
        partial(fuzzy_match_batch, text, patterns, threshold)
    )


def extract_ngrams(text: str, n: int = 2) -> Set[str]:
    """
    Извлекает n-граммы из текста.

    N-граммы полезны для обнаружения фраз даже при
    изменении порядка слов или частичном присутствии.

    Args:
        text: Текст для извлечения (должен быть нормализован)
        n: Размер n-граммы (по умолчанию 2 - биграммы)

    Returns:
        Множество n-грамм
    """
    # Разбиваем на слова
    words = text.lower().split()

    # Если слов меньше n, возвращаем пустое множество
    if len(words) < n:
        return set()

    # Генерируем n-граммы
    ngrams = set()
    for i in range(len(words) - n + 1):
        ngram = ' '.join(words[i:i + n])
        ngrams.add(ngram)

    return ngrams


def ngram_match(text_ngrams: Set[str], pattern_ngrams: Set[str], min_overlap: float = 0.5) -> bool:
    """
    Проверяет совпадение n-грамм текста и паттерна.

    Args:
        text_ngrams: N-граммы текста
        pattern_ngrams: N-граммы паттерна
        min_overlap: Минимальная доля совпадающих n-грамм (0.0-1.0)

    Returns:
        True если достаточное количество n-грамм совпадает
    """
    if not pattern_ngrams:
        return False

    # Считаем пересечение
    common = text_ngrams & pattern_ngrams
    overlap = len(common) / len(pattern_ngrams)

    return overlap >= min_overlap


# ============================================================
# КЛАСС ДЕТЕКТОРА СКАМА
# ============================================================

class ScamDetector:
    """
    Детектор скам-сообщений на основе эвристик.

    Алгоритм:
    1. Нормализует текст (l33tspeak, разделители)
    2. Проверяет каждый сигнал из SCAM_SIGNALS
    3. Суммирует баллы сработавших сигналов
    4. Сравнивает с порогом чувствительности
    5. Возвращает результат с деталями

    Пример использования:
        detector = ScamDetector()
        result = detector.check(
            text="Заработок 5000$ в день! Пиши @username",
            sensitivity=60  # Порог
        )
        if result.is_scam:
            print(f"Скам! Балл: {result.score}")
    """

    def __init__(self, normalizer: Optional[TextNormalizer] = None):
        """
        Инициализация детектора скама.

        Args:
            normalizer: Экземпляр TextNormalizer (если None — используется глобальный)
        """
        # Используем переданный нормализатор или глобальный
        self._normalizer = normalizer or get_normalizer()

        # Компилируем регулярные выражения заранее для производительности
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        # Проходим по всем сигналам и компилируем их паттерны
        for signal_name, signal_data in SCAM_SIGNALS.items():
            # Компилируем с флагами: игнорировать регистр, Unicode
            self._compiled_patterns[signal_name] = re.compile(
                signal_data['pattern'],
                re.IGNORECASE | re.UNICODE
            )

    def check(
        self,
        text: str,
        sensitivity: int = 60
    ) -> ScamCheckResult:
        """
        Проверяет текст на признаки скама.

        Args:
            text: Текст для проверки
            sensitivity: Порог чувствительности (40, 60, 90)
                - 40: высокая чувствительность (ловит больше)
                - 60: средняя (рекомендуется)
                - 90: низкая (только явный скам)

        Returns:
            ScamCheckResult с результатом проверки
        """
        # Проверка на пустой текст
        if not text or not text.strip():
            # Пустой текст не может быть скамом
            return ScamCheckResult(
                is_scam=False,
                score=0,
                triggered_signals=[],
                threshold=sensitivity
            )

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Нормализуем текст
        # ─────────────────────────────────────────────────────────
        # Приводим к единому виду (l33tspeak → кириллица)
        normalized_text = self._normalizer.normalize(text)

        # Также сохраняем оригинальный текст в нижнем регистре
        # (некоторые паттерны лучше работают с оригиналом)
        lower_text = text.lower()

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Проверяем каждый сигнал
        # ─────────────────────────────────────────────────────────
        # Общий балл
        total_score = 0
        # Список сработавших сигналов
        triggered: List[str] = []

        # Проходим по всем сигналам
        for signal_name, signal_data in SCAM_SIGNALS.items():
            # Получаем скомпилированный паттерн
            pattern = self._compiled_patterns[signal_name]

            # Проверяем и в нормализованном, и в оригинальном тексте
            # (некоторые паттерны могут работать лучше в одном из вариантов)
            match_normalized = pattern.search(normalized_text)
            match_original = pattern.search(lower_text)

            # Если сигнал сработал хотя бы в одном варианте
            if match_normalized or match_original:
                # Добавляем балл
                total_score += signal_data['score']
                # Добавляем в список сработавших
                triggered.append(f"{signal_name} (+{signal_data['score']})")

                # Логируем для отладки
                logger.debug(
                    f"[ScamDetector] Сигнал '{signal_name}' сработал: "
                    f"+{signal_data['score']} баллов"
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Сравниваем с порогом
        # ─────────────────────────────────────────────────────────
        is_scam = total_score >= sensitivity

        # Логируем результат
        if is_scam:
            logger.info(
                f"[ScamDetector] Обнаружен скам! "
                f"Score: {total_score} >= {sensitivity}. "
                f"Сигналы: {triggered}"
            )
        else:
            logger.debug(
                f"[ScamDetector] Не скам. "
                f"Score: {total_score} < {sensitivity}"
            )

        # Возвращаем результат
        return ScamCheckResult(
            is_scam=is_scam,
            score=total_score,
            triggered_signals=triggered,
            threshold=sensitivity
        )

    async def check_with_custom_patterns(
        self,
        text: str,
        chat_id: int,
        session: 'AsyncSession',
        sensitivity: int = 60
    ) -> ScamCheckResult:
        """
        Проверяет текст на скам с учётом кастомных паттернов группы.

        Алгоритм:
        1. Проверяет hardcoded SCAM_SIGNALS (base score)
        2. Загружает кастомные паттерны группы из БД
        3. Проверяет кастомные паттерны и добавляет их веса
        4. Обновляет счётчики срабатываний для сработавших паттернов
        5. Сравнивает итоговый скор с порогом

        Args:
            text: Текст для проверки
            chat_id: ID группы (для загрузки кастомных паттернов)
            session: Сессия БД
            sensitivity: Порог чувствительности (40, 60, 90)

        Returns:
            ScamCheckResult с результатом проверки
        """
        # Проверка на пустой текст
        if not text or not text.strip():
            return ScamCheckResult(
                is_scam=False,
                score=0,
                triggered_signals=[],
                threshold=sensitivity
            )

        # ─────────────────────────────────────────────────────────
        # ШАГ 1: Нормализуем текст
        # ─────────────────────────────────────────────────────────
        normalized_text = self._normalizer.normalize(text)
        lower_text = text.lower()

        # ─────────────────────────────────────────────────────────
        # ШАГ 2: Загружаем переопределения базовых сигналов
        # ─────────────────────────────────────────────────────────
        # Теперь базовые сигналы НАСТРАИВАЕМЫЕ вместо хардкода!
        from bot.database.models_content_filter import BaseSignalOverride
        from sqlalchemy import select

        overrides_map: Dict[str, Dict] = {}  # signal_name -> {enabled, weight}
        try:
            override_query = select(BaseSignalOverride).where(
                BaseSignalOverride.chat_id == chat_id
            )
            override_result = await session.execute(override_query)
            overrides = override_result.scalars().all()

            for override in overrides:
                overrides_map[override.signal_name] = {
                    'enabled': override.enabled,
                    'weight': override.weight_override
                }
        except Exception as e:
            logger.warning(f"[ScamDetector] Ошибка загрузки переопределений: {e}")

        # ─────────────────────────────────────────────────────────
        # ШАГ 3: Проверяем базовые сигналы (с учётом переопределений)
        # ─────────────────────────────────────────────────────────
        total_score = 0
        triggered: List[str] = []

        for signal_name, signal_data in SCAM_SIGNALS.items():
            # Проверяем переопределение для этого сигнала
            override = overrides_map.get(signal_name)

            # Если сигнал отключён для этой группы - пропускаем
            if override and not override['enabled']:
                logger.debug(
                    f"[ScamDetector] Базовый сигнал '{signal_name}' отключён для группы"
                )
                continue

            pattern = self._compiled_patterns[signal_name]
            match_normalized = pattern.search(normalized_text)
            match_original = pattern.search(lower_text)

            if match_normalized or match_original:
                # Используем переопределённый вес или стандартный
                if override and override['weight'] is not None:
                    score = override['weight']
                    triggered.append(f"{signal_name} (+{score} [custom])")
                else:
                    score = signal_data['score']
                    triggered.append(f"{signal_name} (+{score})")

                total_score += score
                logger.debug(
                    f"[ScamDetector] Базовый сигнал '{signal_name}' сработал: "
                    f"+{score} баллов"
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 4: Загружаем и проверяем кастомные паттерны
        # ─────────────────────────────────────────────────────────
        # Импортируем сервис паттернов (lazy import для избежания circular)
        from bot.services.content_filter.scam_pattern_service import get_pattern_service
        pattern_service = get_pattern_service()

        # Загружаем активные паттерны группы
        custom_patterns = await pattern_service.get_patterns(
            chat_id=chat_id,
            session=session,
            active_only=True
        )

        # Список ID паттернов которые сработали (для обновления счётчика)
        triggered_pattern_ids: List[int] = []

        # Предварительно извлекаем n-граммы из текста для n-gram matching
        text_bigrams = extract_ngrams(normalized_text, n=2)
        text_trigrams = extract_ngrams(normalized_text, n=3)

        # Проверяем каждый кастомный паттерн используя 4 метода
        for pattern in custom_patterns:
            matched = False
            match_method = None  # Для логирования какой метод сработал

            # ─────────────────────────────────────────────────────
            # МЕТОД 1: REGEX (точное совпадение по регулярке)
            # ─────────────────────────────────────────────────────
            if pattern.pattern_type == 'regex':
                try:
                    regex = re.compile(pattern.pattern, re.IGNORECASE | re.UNICODE)
                    if regex.search(normalized_text) or regex.search(lower_text):
                        matched = True
                        match_method = 'regex'
                except re.error:
                    logger.warning(
                        f"[ScamDetector] Некорректный regex паттерн #{pattern.id}: "
                        f"{pattern.pattern}"
                    )
                    continue

            # ─────────────────────────────────────────────────────
            # МЕТОД 2: KEYWORD (точное совпадение слова)
            # ─────────────────────────────────────────────────────
            elif pattern.pattern_type == 'word':
                # Сначала точное совпадение
                word_pattern = r'\b' + re.escape(pattern.normalized) + r'\b'
                try:
                    if re.search(word_pattern, normalized_text, re.IGNORECASE):
                        matched = True
                        match_method = 'keyword'
                except re.error:
                    pass

                # Если не нашли точное совпадение - пробуем fuzzy matching
                if not matched:
                    if fuzzy_match(normalized_text, pattern.normalized, threshold=0.85):
                        matched = True
                        match_method = 'fuzzy'

            # ─────────────────────────────────────────────────────
            # МЕТОД 3: PHRASE (подстрока + fuzzy + n-grams)
            # ─────────────────────────────────────────────────────
            else:
                # Сначала точное совпадение подстроки
                if pattern.normalized in normalized_text.lower():
                    matched = True
                    match_method = 'phrase'

                # Если не нашли - пробуем fuzzy matching
                if not matched:
                    if fuzzy_match(normalized_text, pattern.normalized, threshold=0.8):
                        matched = True
                        match_method = 'fuzzy'

                # Если не нашли - пробуем n-gram matching
                if not matched:
                    # Извлекаем n-граммы из паттерна
                    pattern_words = pattern.normalized.split()
                    if len(pattern_words) >= 2:
                        pattern_bigrams = extract_ngrams(pattern.normalized, n=2)
                        if ngram_match(text_bigrams, pattern_bigrams, min_overlap=0.6):
                            matched = True
                            match_method = 'ngram'

                    if not matched and len(pattern_words) >= 3:
                        pattern_trigrams = extract_ngrams(pattern.normalized, n=3)
                        if ngram_match(text_trigrams, pattern_trigrams, min_overlap=0.5):
                            matched = True
                            match_method = 'ngram'

            # Если паттерн сработал
            if matched:
                total_score += pattern.weight
                # Формируем описание для триггера с методом совпадения
                pattern_desc = pattern.pattern[:25]
                if len(pattern.pattern) > 25:
                    pattern_desc += '...'
                triggered.append(f"custom[{match_method}]:{pattern_desc} (+{pattern.weight})")
                triggered_pattern_ids.append(pattern.id)

                logger.debug(
                    f"[ScamDetector] Кастомный паттерн #{pattern.id} сработал "
                    f"методом '{match_method}': '{pattern.pattern}' +{pattern.weight} баллов"
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 5: Обновляем счётчики срабатываний
        # ─────────────────────────────────────────────────────────
        if triggered_pattern_ids:
            for pattern_id in triggered_pattern_ids:
                await pattern_service.increment_trigger_count(
                    pattern_id=pattern_id,
                    session=session
                )

        # ─────────────────────────────────────────────────────────
        # ШАГ 5.5: Загружаем и проверяем категории сигналов
        # ─────────────────────────────────────────────────────────
        # Категории позволяют админам создавать свои наборы ключевых слов
        # (например: "Наркотики", "Контакты для связи" и т.д.)
        from bot.database.models_content_filter import ScamSignalCategory
        from sqlalchemy import select

        try:
            # Загружаем активные категории для этой группы
            category_query = select(ScamSignalCategory).where(
                ScamSignalCategory.chat_id == chat_id,
                ScamSignalCategory.enabled == True
            )
            category_result = await session.execute(category_query)
            categories = category_result.scalars().all()

            # Проверяем каждую категорию
            for category in categories:
                if not category.keywords:
                    continue

                # Разбиваем keywords по запятым
                keywords = [kw.strip().lower() for kw in category.keywords.split(',') if kw.strip()]

                # Проверяем каждое ключевое слово
                category_matched = False
                matched_keyword = None

                for keyword in keywords:
                    # Пробуем точное совпадение
                    if keyword in normalized_text.lower():
                        category_matched = True
                        matched_keyword = keyword
                        break

                    # Пробуем fuzzy matching для длинных ключевых слов
                    if len(keyword) >= 4:
                        if fuzzy_match(normalized_text, keyword, threshold=0.85):
                            category_matched = True
                            matched_keyword = keyword
                            break

                # Если категория сработала
                if category_matched:
                    total_score += category.weight
                    triggered.append(
                        f"category[{category.category_name}]:{matched_keyword} (+{category.weight})"
                    )
                    logger.debug(
                        f"[ScamDetector] Категория '{category.category_name}' сработала "
                        f"на ключевом слове '{matched_keyword}': +{category.weight} баллов"
                    )

        except Exception as e:
            logger.warning(f"[ScamDetector] Ошибка проверки категорий: {e}")

        # ─────────────────────────────────────────────────────────
        # ШАГ 6: Сравниваем с порогом
        # ─────────────────────────────────────────────────────────
        is_scam = total_score >= sensitivity

        if is_scam:
            logger.info(
                f"[ScamDetector] Обнаружен скам (with custom)! "
                f"Score: {total_score} >= {sensitivity}. "
                f"Сигналы: {triggered}"
            )
        else:
            logger.debug(
                f"[ScamDetector] Не скам (with custom). "
                f"Score: {total_score} < {sensitivity}"
            )

        return ScamCheckResult(
            is_scam=is_scam,
            score=total_score,
            triggered_signals=triggered,
            threshold=sensitivity
        )

    def get_signals_info(self) -> Dict[str, Dict]:
        """
        Возвращает информацию о всех сигналах.

        Полезно для отладки и документации.

        Returns:
            Словарь с описанием всех сигналов
        """
        return SCAM_SIGNALS.copy()

    def get_max_possible_score(self) -> int:
        """
        Возвращает максимально возможный балл.

        Returns:
            Сумма баллов всех сигналов
        """
        return sum(signal['score'] for signal in SCAM_SIGNALS.values())


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР (СИНГЛТОН)
# ============================================================

# Глобальный экземпляр для переиспользования
_scam_detector: Optional[ScamDetector] = None


def get_scam_detector() -> ScamDetector:
    """
    Возвращает глобальный экземпляр ScamDetector (синглтон).

    Returns:
        Экземпляр ScamDetector
    """
    # Используем глобальную переменную
    global _scam_detector
    # Создаём экземпляр при первом обращении
    if _scam_detector is None:
        _scam_detector = ScamDetector()
    # Возвращаем существующий экземпляр
    return _scam_detector
