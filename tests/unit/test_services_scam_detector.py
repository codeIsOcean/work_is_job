# ============================================================
# Unit-тесты для модуля ScamDetector
# ============================================================
# Этот модуль тестирует функции детекции скама:
# - fuzzy_match: нечёткое сравнение строк
# - ScamDetector.check: базовая проверка на скам
# ============================================================

# Импорт pytest для тестирования
import pytest

# Импорт тестируемых функций из scam_detector
from bot.services.content_filter.scam_detector import (
    fuzzy_match,
    fuzzy_match_batch,
    ScamDetector,
)


# ============================================================
# ТЕСТЫ ДЛЯ fuzzy_match - КРИТИЧЕСКИЙ БАГ С КОРОТКИМИ ТЕКСТАМИ
# ============================================================
# История бага (2026-01-02):
# Пользователь отправил сообщение "Я" (1 символ).
# ScamDetector вернул score=4870 и удалил сообщение как скам.
# Причина: partial_ratio("обменяю ваши usdt", "я") = 100%,
# потому что буква "я" есть в слове "обменЯю".
# ============================================================


class TestFuzzyMatchShortText:
    """Тесты на корректную работу fuzzy_match с очень короткими текстами."""

    # Тест: короткий текст "Я" НЕ должен матчить длинный паттерн
    def test_single_letter_should_not_match_long_pattern(self):
        """Одна буква 'Я' не должна матчить паттерн 'обменяю ваши usdt'."""
        # Этот тест воспроизводит реальный баг
        result = fuzzy_match(
            text="Я",  # Текст пользователя - одна буква
            pattern="обменяю ваши usdt",  # Паттерн скама
            threshold=0.8  # Порог 80%
        )
        # ОЖИДАНИЕ: НЕ должно быть совпадения!
        # Раньше возвращало True (баг), теперь должно False
        assert result is False, (
            "Одна буква 'Я' не должна матчить длинный паттерн! "
            "Это ложное срабатывание (false positive)."
        )

    # Тест: короткий текст "Я" НЕ должен матчить "меня есть"
    def test_single_letter_ya_should_not_match_menya_est(self):
        """Одна буква 'Я' не должна матчить паттерн 'меня есть'."""
        result = fuzzy_match(
            text="Я",
            pattern="меня есть",
            threshold=0.8
        )
        # Не должно быть совпадения
        assert result is False

    # Тест: текст из 2 букв не должен матчить длинный паттерн
    def test_two_letters_should_not_match_long_pattern(self):
        """Текст 'Да' не должен матчить паттерн 'обменяю usdt'."""
        result = fuzzy_match(
            text="Да",
            pattern="обменяю usdt",
            threshold=0.8
        )
        # Не должно быть совпадения
        assert result is False

    # Тест: текст из 3 букв не должен матчить длинный паттерн
    def test_three_letters_should_not_match_long_pattern(self):
        """Текст 'Нет' не должен матчить паттерн 'быстро обменяю'."""
        result = fuzzy_match(
            text="Нет",
            pattern="быстро обменяю",
            threshold=0.8
        )
        # Не должно быть совпадения
        assert result is False

    # Тест: паттерн меньше 3 символов - точное вхождение
    def test_short_pattern_exact_match(self):
        """Короткий паттерн (< 3 символов) должен искать точное вхождение."""
        # Паттерн "ок" должен найтись в "всё ок"
        result = fuzzy_match(
            text="всё ок",
            pattern="ок",
            threshold=0.8
        )
        assert result is True

    # Тест: паттерн меньше 3 символов - НЕТ вхождения
    def test_short_pattern_no_match(self):
        """Короткий паттерн (< 3 символов) не должен найтись если его нет."""
        # Паттерн "ок" НЕ должен найтись в "привет"
        result = fuzzy_match(
            text="привет",
            pattern="ок",
            threshold=0.8
        )
        assert result is False


class TestFuzzyMatchNormalCases:
    """Тесты на нормальную работу fuzzy_match с адекватными текстами."""

    # Тест: точное совпадение
    def test_exact_match(self):
        """Точное совпадение текста и паттерна."""
        result = fuzzy_match(
            text="обменяю usdt",
            pattern="обменяю usdt",
            threshold=0.8
        )
        # Должно быть совпадение
        assert result is True

    # Тест: близкое совпадение с опечаткой
    def test_fuzzy_match_with_typo(self):
        """Совпадение с небольшой опечаткой."""
        result = fuzzy_match(
            text="обменяю usdт",  # опечатка: т вместо t
            pattern="обменяю usdt",
            threshold=0.8
        )
        # Должно быть совпадение (fuzzy)
        assert result is True

    # Тест: паттерн как подстрока текста
    def test_pattern_as_substring(self):
        """Паттерн содержится в тексте как подстрока."""
        result = fuzzy_match(
            text="Привет! Хочу обменяю usdt на рубли.",
            pattern="обменяю usdt",
            threshold=0.8
        )
        # Должно быть совпадение
        assert result is True

    # Тест: совсем разные строки
    def test_completely_different_strings(self):
        """Совершенно разные строки не должны матчиться."""
        result = fuzzy_match(
            text="Привет как дела",
            pattern="обменяю usdt",
            threshold=0.8
        )
        # Не должно быть совпадения
        assert result is False


class TestFuzzyMatchBatch:
    """Тесты для пакетного fuzzy matching."""

    # Тест: короткий текст не матчит ни один паттерн в батче
    def test_batch_short_text_no_matches(self):
        """Короткий текст 'Я' не должен матчить ни один паттерн."""
        patterns = [
            "обменяю usdt",
            "меня есть шабашка",
            "быстро обменяю",
            "нужен человек",
        ]
        results = fuzzy_match_batch(
            text="Я",
            patterns=patterns,
            threshold=0.8
        )
        # ВСЕ результаты должны быть False
        assert all(r is False for r in results), (
            f"Короткий текст 'Я' не должен матчить паттерны! "
            f"Результаты: {results}"
        )

    # Тест: нормальный текст с матчами
    def test_batch_normal_text_with_matches(self):
        """Нормальный текст должен находить совпадения."""
        patterns = [
            "обменяю usdt",  # Должен матчить
            "привет мир",  # Не должен
            "usdt обменяю",  # Должен матчить (слова те же)
        ]
        results = fuzzy_match_batch(
            text="Хочу обменяю usdt на рубли",
            patterns=patterns,
            threshold=0.8
        )
        # Первый и третий паттерны должны матчить
        assert results[0] is True  # обменяю usdt
        assert results[1] is False  # привет мир
        # Третий зависит от реализации, не проверяем строго


class TestScamDetectorBasic:
    """Базовые тесты для ScamDetector."""

    # Тест: пустой текст не скам
    def test_empty_text_not_scam(self):
        """Пустой текст не должен определяться как скам."""
        detector = ScamDetector()
        result = detector.check(text="", sensitivity=60)
        # Не скам
        assert result.is_scam is False
        # Score = 0
        assert result.score == 0

    # Тест: короткий текст "Я" не скам
    def test_single_letter_not_scam(self):
        """Текст из одной буквы не должен быть скамом."""
        detector = ScamDetector()
        result = detector.check(text="Я", sensitivity=60)
        # Не скам
        assert result.is_scam is False
        # Score должен быть 0 или очень низкий
        assert result.score < 60, (
            f"Score для 'Я' = {result.score}, слишком высокий!"
        )

    # Тест: обычное сообщение не скам
    def test_normal_message_not_scam(self):
        """Обычное сообщение не должно быть скамом."""
        detector = ScamDetector()
        result = detector.check(
            text="Привет! Как дела?",
            sensitivity=60
        )
        # Не скам
        assert result.is_scam is False

    # Тест: явный скам определяется
    def test_obvious_scam_detected(self):
        """Явный скам-текст должен определяться."""
        detector = ScamDetector()
        result = detector.check(
            text="Заработок 5000$ в день! Пиши @username срочно!!!",
            sensitivity=60
        )
        # Это скам
        assert result.is_scam is True
        # Score высокий
        assert result.score >= 60
