# tests/unit/test_html_utils.py
"""
Тесты для HTML утилит.

Эти тесты проверяют валидацию и экранирование HTML
для Telegram сообщений.
"""

import pytest
from bot.utils.html_utils import (
    validate_telegram_html,
    escape_html,
    safe_format_html,
    validate_and_log,
)


class TestValidateTelegramHtml:
    """Тесты валидации Telegram HTML."""

    def test_valid_simple_tags(self):
        """Базовые теги валидны."""
        valid_texts = [
            "<b>bold</b>",
            "<i>italic</i>",
            "<u>underline</u>",
            "<s>strike</s>",
            "<code>code</code>",
            "<pre>preformatted</pre>",
            "<a href='https://t.me'>link</a>",
        ]
        for text in valid_texts:
            is_valid, errors = validate_telegram_html(text)
            assert is_valid, f"Should be valid: {text}, errors: {errors}"

    def test_valid_nested_tags(self):
        """Вложенные теги валидны."""
        text = "<b>bold and <i>italic</i></b>"
        is_valid, errors = validate_telegram_html(text)
        assert is_valid

    def test_invalid_number_after_lt(self):
        """Число после < невалидно (типичная ошибка)."""
        invalid_texts = [
            "Value <1",
            "Threshold (<5 days)",
            "Range: <10 to <20",
        ]
        for text in invalid_texts:
            is_valid, errors = validate_telegram_html(text)
            assert not is_valid, f"Should be invalid: {text}"
            assert any("&lt;" in e for e in errors)

    def test_real_bug_photo_freshness(self):
        """Реальный баг: (<1 дн) интерпретируется как тег."""
        # Это вызывало TelegramBadRequest: Unsupported start tag "1"
        buggy_text = "<b>Критерий 4:</b> Свежее фото (<1 дн)"
        is_valid, errors = validate_telegram_html(buggy_text)
        assert not is_valid
        assert len(errors) >= 1

    def test_fixed_version_valid(self):
        """Исправленная версия с &lt; валидна."""
        fixed_text = "<b>Критерий 4:</b> Свежее фото (&lt;1 дн)"
        is_valid, errors = validate_telegram_html(fixed_text)
        assert is_valid, f"Should be valid, errors: {errors}"

    def test_unknown_tag_detected(self):
        """Неизвестные теги обнаруживаются."""
        text = "<div>not allowed</div>"
        is_valid, errors = validate_telegram_html(text)
        assert not is_valid
        assert any("div" in e.lower() for e in errors)

    def test_plain_text_valid(self):
        """Обычный текст без тегов валиден."""
        text = "Just plain text without any HTML"
        is_valid, errors = validate_telegram_html(text)
        assert is_valid

    def test_escaped_lt_gt_valid(self):
        """Экранированные < и > валидны."""
        text = "5 &lt; 10 &gt; 3"
        is_valid, errors = validate_telegram_html(text)
        assert is_valid


class TestEscapeHtml:
    """Тесты экранирования HTML."""

    def test_escape_lt(self):
        """Экранирование <."""
        assert escape_html("<") == "&lt;"
        assert escape_html("5 < 10") == "5 &lt; 10"

    def test_escape_gt(self):
        """Экранирование >."""
        assert escape_html(">") == "&gt;"
        assert escape_html("10 > 5") == "10 &gt; 5"

    def test_escape_amp(self):
        """Экранирование &."""
        assert escape_html("&") == "&amp;"
        assert escape_html("A & B") == "A &amp; B"

    def test_escape_combined(self):
        """Комбинированное экранирование."""
        assert escape_html("<5 & >3") == "&lt;5 &amp; &gt;3"

    def test_no_escape_needed(self):
        """Текст без спецсимволов не меняется."""
        text = "Hello World 123"
        assert escape_html(text) == text


class TestSafeFormatHtml:
    """Тесты безопасного форматирования."""

    def test_escapes_values(self):
        """Значения экранируются."""
        result = safe_format_html(
            "Threshold: {value}",
            value="<5"
        )
        assert result == "Threshold: &lt;5"

    def test_preserves_template_html(self):
        """HTML в шаблоне сохраняется."""
        result = safe_format_html(
            "<b>Value:</b> {value}",
            value="10"
        )
        assert result == "<b>Value:</b> 10"

    def test_multiple_values(self):
        """Несколько значений экранируются."""
        result = safe_format_html(
            "{a} < {b} & {c} > {d}",
            a="1", b="2", c="3", d="4"
        )
        # Template < and > are literal, values are escaped
        assert "&lt;" not in result  # < in template stays as is
        assert "1 < 2 & 3 > 4" == result

    def test_real_use_case(self):
        """Реальный пример использования."""
        result = safe_format_html(
            "<b>Критерий:</b> Фото (&lt;{days} дн)",
            days=1
        )
        # days=1 doesn't need escaping, &lt; is already in template
        assert result == "<b>Критерий:</b> Фото (&lt;1 дн)"


class TestValidateAndLog:
    """Тесты валидации с логированием."""

    def test_returns_true_for_valid(self):
        """Возвращает True для валидного HTML."""
        assert validate_and_log("<b>test</b>") is True

    def test_returns_false_for_invalid(self):
        """Возвращает False для невалидного HTML."""
        assert validate_and_log("<1 invalid") is False

    def test_with_context(self):
        """Работает с контекстом."""
        result = validate_and_log("<b>ok</b>", context="test_function")
        assert result is True
