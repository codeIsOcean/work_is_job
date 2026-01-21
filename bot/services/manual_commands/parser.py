# ═══════════════════════════════════════════════════════════════════════════
# ПАРСЕР КОМАНД МОДЕРАЦИИ
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит функции для парсинга команд /amute, /aban, /akick.
# Парсер извлекает из текста команды: target (кого), duration (на сколько),
# reason (причина).
#
# Примеры использования:
#   /amute 1h                     → mute на 1 час (reply на сообщение)
#   /amute @username 7d спам      → mute @username на 7 дней с причиной
#   /amute 123456789 forever      → mute user_id навсегда
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

import re
import logging
from dataclasses import dataclass
from typing import Optional

# Настраиваем логгер для отслеживания работы парсера
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATACLASS ДЛЯ РЕЗУЛЬТАТА ПАРСИНГА
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class ParsedCommand:
    """
    Результат парсинга команды модерации.

    Attributes:
        target: Цель команды — @username или user_id (None если reply)
        target_type: Тип цели — 'reply', 'username', 'user_id'
        duration_minutes: Время в минутах (None = навсегда)
        is_forever: True если мут/бан навсегда
        reason: Причина (может быть None)
    """
    # Цель команды: @username или user_id (None если reply на сообщение)
    target: Optional[str] = None
    # Тип цели: 'reply', 'username', 'user_id'
    target_type: str = 'reply'
    # Длительность в минутах (None = навсегда)
    duration_minutes: Optional[int] = None
    # True если команда содержит "forever"/"навсегда"
    is_forever: bool = False
    # Причина действия (может быть пустой)
    reason: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ ДЛЯ ПАРСИНГА "НАВСЕГДА"
# ═══════════════════════════════════════════════════════════════════════════
# Слова которые означают "навсегда" — поддерживаем русский и английский
FOREVER_KEYWORDS = frozenset([
    'forever', 'навсегда', 'permanent', 'perm', 'inf', '∞',
    'бессрочно', 'всегда', 'вечно', 'permanently'
])


# ═══════════════════════════════════════════════════════════════════════════
# ПАРСИНГ ДЛИТЕЛЬНОСТИ
# ═══════════════════════════════════════════════════════════════════════════
def parse_duration_extended(duration_str: str) -> tuple[Optional[int], bool]:
    """
    Парсит строку длительности и возвращает (минуты, is_forever).

    Расширенная версия парсера с поддержкой:
    - forever/навсегда → (None, True)
    - 30s → (1, False) минимум 1 минута
    - 5m/5min → (5, False)
    - 1h → (60, False)
    - 1d → (1440, False)
    - 1w → (10080, False) неделя
    - 2h30m → (150, False) комбинированный формат

    Args:
        duration_str: Строка вида "30s", "5min", "1h", "forever", "навсегда"

    Returns:
        tuple[Optional[int], bool]: (минуты, is_forever)
        - Если forever: (None, True)
        - Если время: (минуты, False)
        - Если ошибка парсинга: (None, False)
    """
    # Проверка на пустой ввод
    if not duration_str or not duration_str.strip():
        return (None, False)

    # Приводим к нижнему регистру и убираем пробелы
    s = duration_str.lower().strip()

    # ─── Проверка на "навсегда" ───
    if s in FOREVER_KEYWORDS:
        return (None, True)

    # ─── Проверка на отрицательные числа ───
    if s.startswith('-'):
        return (None, False)

    # ─── Комбинированный формат: 2h30m, 1d12h ───
    # Паттерн для захвата всех частей: 2h, 30m, 1d, 12h
    combined_pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?(?:(\d+)s(?:ec)?)?'
    combined_match = re.fullmatch(combined_pattern, s)

    if combined_match and any(combined_match.groups()):
        # Извлекаем дни, часы, минуты, секунды
        days = int(combined_match.group(1) or 0)
        hours = int(combined_match.group(2) or 0)
        minutes = int(combined_match.group(3) or 0)
        seconds = int(combined_match.group(4) or 0)

        # Конвертируем всё в минуты
        total_minutes = (days * 1440) + (hours * 60) + minutes + (seconds // 60)

        # Минимум 1 минута если указаны только секунды
        if total_minutes == 0 and seconds > 0:
            total_minutes = 1

        if total_minutes > 0:
            return (total_minutes, False)

    # ─── Простой формат: 30s, 5min, 1h, 1d, 1w ───
    simple_pattern = r'^(\d+)\s*(s|sec|m|min|h|hour|d|day|w|week)$'
    simple_match = re.match(simple_pattern, s)

    if simple_match:
        # Извлекаем число и единицу измерения
        value = int(simple_match.group(1))
        unit = simple_match.group(2)

        # Конвертируем в минуты в зависимости от единицы
        if unit in ('s', 'sec'):
            # Секунды -> минуты (минимум 1 минута)
            return (max(1, value // 60), False)
        elif unit in ('m', 'min'):
            # Минуты
            return (value, False)
        elif unit in ('h', 'hour'):
            # Часы -> минуты
            return (value * 60, False)
        elif unit in ('d', 'day'):
            # Дни -> минуты
            return (value * 1440, False)
        elif unit in ('w', 'week'):
            # Недели -> минуты
            return (value * 10080, False)

    # ─── Просто число — интерпретируем как минуты ───
    if re.match(r'^\d+$', s):
        return (int(s), False)

    # ─── Не удалось распарсить ───
    return (None, False)


# ═══════════════════════════════════════════════════════════════════════════
# ПАРСИНГ КОМАНДЫ /amute
# ═══════════════════════════════════════════════════════════════════════════
def parse_mute_command(text: str, has_reply: bool = False) -> ParsedCommand:
    """
    Парсит текст команды /amute и извлекает target, duration, reason.

    Форматы команды:
    1. /amute                          → reply, время по умолчанию
    2. /amute 1h                       → reply, 1 час
    3. /amute forever                  → reply, навсегда
    4. /amute спам                     → reply, время по умолчанию, причина "спам"
    5. /amute 1h спам                  → reply, 1 час, причина "спам"
    6. /amute @username                → @username, время по умолчанию
    7. /amute @username 1h             → @username, 1 час
    8. /amute @username forever спам   → @username, навсегда, причина "спам"
    9. /amute 123456789 1h             → user_id, 1 час
    10. /amute 123456789 forever       → user_id, навсегда

    Args:
        text: Полный текст сообщения с командой
        has_reply: True если сообщение является ответом на другое

    Returns:
        ParsedCommand: Результат парсинга
    """
    # Создаём результат с дефолтными значениями
    result = ParsedCommand()

    # Убираем команду из начала текста
    # Поддерживаем /amute и /amute@botname
    text = re.sub(r'^/a?mute(@\w+)?\s*', '', text, flags=re.IGNORECASE).strip()

    # Если текст пустой — используем reply
    if not text:
        if has_reply:
            result.target_type = 'reply'
        return result

    # Разбиваем текст на части
    parts = text.split()

    # Индекс текущей позиции парсинга
    idx = 0

    # ─── Шаг 1: Пытаемся найти target (@username или user_id) ───
    first_part = parts[0]

    # Проверяем на @username
    if first_part.startswith('@'):
        result.target = first_part  # Сохраняем с @
        result.target_type = 'username'
        idx = 1
    # Проверяем на user_id (число больше 1000 — чтобы не путать с минутами)
    elif first_part.isdigit() and int(first_part) > 10000:
        result.target = first_part
        result.target_type = 'user_id'
        idx = 1
    # Если нет target — используем reply
    elif has_reply:
        result.target_type = 'reply'
    else:
        # Нет reply и нет target в тексте — попробуем интерпретировать как время
        result.target_type = 'reply'

    # ─── Шаг 2: Пытаемся найти duration ───
    if idx < len(parts):
        next_part = parts[idx]

        # Пробуем распарсить как время
        duration, is_forever = parse_duration_extended(next_part)

        # Если это время — сохраняем
        if is_forever:
            result.duration_minutes = None
            result.is_forever = True
            idx += 1
        elif duration is not None:
            result.duration_minutes = duration
            result.is_forever = False
            idx += 1
        # Иначе это не время — возможно это начало причины

    # ─── Шаг 3: Остаток — это причина ───
    if idx < len(parts):
        result.reason = ' '.join(parts[idx:])

    # Логируем результат для отладки
    logger.debug(
        f"[PARSER] Parsed command: target={result.target}, "
        f"type={result.target_type}, duration={result.duration_minutes}min, "
        f"forever={result.is_forever}, reason={result.reason}"
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ ВРЕМЕНИ ДЛЯ ОТОБРАЖЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════
def format_duration(minutes: Optional[int]) -> str:
    """
    Форматирует длительность в минутах в человекочитаемый вид.

    Args:
        minutes: Количество минут (None = навсегда)

    Returns:
        str: Строка вида "1 час", "7 дней", "навсегда"
    """
    # Если None — навсегда
    if minutes is None or minutes == 0:
        return "навсегда"

    # Вычисляем дни, часы, минуты
    days = minutes // 1440
    hours = (minutes % 1440) // 60
    mins = minutes % 60

    # Формируем строку
    parts = []

    # Добавляем дни
    if days > 0:
        if days == 1:
            parts.append("1 день")
        elif days < 5:
            parts.append(f"{days} дня")
        else:
            parts.append(f"{days} дней")

    # Добавляем часы
    if hours > 0:
        if hours == 1:
            parts.append("1 час")
        elif hours < 5:
            parts.append(f"{hours} часа")
        else:
            parts.append(f"{hours} часов")

    # Добавляем минуты (только если нет дней)
    if mins > 0 and days == 0:
        if mins == 1:
            parts.append("1 минута")
        elif mins < 5:
            parts.append(f"{mins} минуты")
        else:
            parts.append(f"{mins} минут")

    # Если всё по нулям — показываем минуты
    if not parts:
        return f"{minutes} минут"

    return ' '.join(parts)
