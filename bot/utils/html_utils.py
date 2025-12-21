# ============================================================
# HTML UTILS - УТИЛИТЫ ДЛЯ РАБОТЫ С HTML В TELEGRAM
# ============================================================
# Telegram поддерживает ограниченный набор HTML тегов.
# Этот модуль помогает валидировать и экранировать HTML.
# ============================================================

import re
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)

# Разрешённые теги в Telegram HTML
ALLOWED_TAGS = {
    'b', 'strong',           # жирный
    'i', 'em',               # курсив
    'u', 'ins',              # подчёркнутый
    's', 'strike', 'del',    # зачёркнутый
    'span',                  # spoiler (class="tg-spoiler")
    'tg-spoiler',            # spoiler
    'a',                     # ссылки
    'code', 'pre',           # код
    'blockquote',            # цитата
    'tg-emoji',              # кастомные эмодзи
}

# Паттерн для поиска HTML тегов
TAG_PATTERN = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9\-]*)[^>]*>')

# Паттерн для поиска некорректных "тегов" (число после <)
INVALID_TAG_PATTERN = re.compile(r'<(\d)')


def validate_telegram_html(text: str) -> Tuple[bool, List[str]]:
    """
    Проверяет HTML текст на корректность для Telegram.

    Args:
        text: HTML текст для проверки

    Returns:
        Tuple[bool, List[str]]: (is_valid, list_of_errors)

    Example:
        is_valid, errors = validate_telegram_html("<b>Hello</b>")
        # (True, [])

        is_valid, errors = validate_telegram_html("Value <5")
        # (False, ["Invalid tag-like pattern: '<5'"])
    """
    errors = []

    # Проверка на некорректные "теги" типа <1, <5 и т.д.
    invalid_matches = INVALID_TAG_PATTERN.findall(text)
    if invalid_matches:
        for match in invalid_matches:
            errors.append(f"Invalid tag-like pattern: '<{match}' - use '&lt;' instead")

    # Проверка на неразрешённые теги
    for match in TAG_PATTERN.finditer(text):
        tag_name = match.group(2).lower()
        if tag_name not in ALLOWED_TAGS:
            errors.append(f"Unknown tag: '<{match.group(2)}>' - not supported by Telegram")

    # Проверка на незакрытые < без >
    # Ищем < за которым нет закрывающего > до следующего < или конца строки
    i = 0
    while i < len(text):
        if text[i] == '<':
            # Ищем закрывающий >
            j = i + 1
            found_close = False
            while j < len(text):
                if text[j] == '>':
                    found_close = True
                    break
                if text[j] == '<':
                    # Нашли новый < до закрытия
                    break
                j += 1

            if not found_close and j < len(text):
                # Незакрытый тег
                snippet = text[i:min(i+10, len(text))]
                errors.append(f"Unclosed '<' at position {i}: '{snippet}...'")
            i = j
        else:
            i += 1

    return len(errors) == 0, errors


def escape_html(text: str) -> str:
    """
    Экранирует специальные HTML символы.

    Используй эту функцию для пользовательского ввода
    или динамических значений в HTML сообщениях.

    Args:
        text: Текст для экранирования

    Returns:
        Экранированный текст

    Example:
        escape_html("5 < 10")  # "5 &lt; 10"
        escape_html("A & B")   # "A &amp; B"
    """
    return (
        text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def safe_format_html(template: str, **kwargs) -> str:
    """
    Безопасно форматирует HTML шаблон с экранированием значений.

    Все переданные значения автоматически экранируются.

    Args:
        template: Шаблон с плейсхолдерами {name}
        **kwargs: Значения для подстановки

    Returns:
        Отформатированная строка с экранированными значениями

    Example:
        safe_format_html(
            "Порог: <b>{threshold}</b> дней",
            threshold="<5"
        )
        # "Порог: <b>&lt;5</b> дней"
    """
    escaped_kwargs = {
        key: escape_html(str(value))
        for key, value in kwargs.items()
    }
    return template.format(**escaped_kwargs)


def validate_and_log(text: str, context: str = "") -> bool:
    """
    Валидирует HTML и логирует ошибки.

    Удобно использовать для отладки.

    Args:
        text: HTML текст
        context: Контекст для лога (название функции и т.п.)

    Returns:
        True если валидно, False если есть ошибки
    """
    is_valid, errors = validate_telegram_html(text)

    if not is_valid:
        error_msg = "; ".join(errors)
        logger.error(f"[HTML Validation] {context}: {error_msg}")
        logger.debug(f"[HTML Validation] Full text: {text[:500]}")

    return is_valid
