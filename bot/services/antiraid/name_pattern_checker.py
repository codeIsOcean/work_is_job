# bot/services/antiraid/name_pattern_checker.py
"""
Сервис проверки имени пользователя по паттернам при входе в группу.

Решает проблему ботов с обфусцированными именами типа:
- "Д.е́. t.С.k.ő.ē TKL98ВОТ" → после нормализации → "детское"

Логика:
1. Получаем first_name + last_name пользователя
2. Нормализуем имя (удаляем точки, спецсимволы, конвертируем leet-speak)
3. Проверяем по паттернам из БД
4. Если матч — применяем действие (бан/кик)
5. Отправляем уведомление в журнал

ВАЖНО: Использует существующий TextNormalizer для нормализации.
"""

# Импортируем логгер для записи событий
import logging
# Импортируем re для regex паттернов
import re
# Импортируем типы для аннотаций
from typing import Optional, List, NamedTuple
# Импортируем dataclass для результата проверки
from dataclasses import dataclass

# Импортируем AsyncSession для асинхронной работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем User из aiogram для получения данных пользователя
from aiogram.types import User

# Импортируем TextNormalizer для нормализации имён
# Используем существующий нормализатор из content_filter
from bot.services.content_filter.text_normalizer import TextNormalizer

# Импортируем модели и сервисы Anti-Raid
from bot.database.models_antiraid import AntiRaidNamePattern
from bot.services.antiraid.settings_service import (
    get_antiraid_settings,
    get_enabled_name_patterns,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём singleton экземпляр нормализатора
# Используем тот же что и content_filter для консистентности
_normalizer = TextNormalizer()


@dataclass
class NameCheckResult:
    """
    Результат проверки имени пользователя.

    Attributes:
        matched: True если имя матчит запрещённый паттерн
        pattern: Объект паттерна который сработал (или None)
        original_name: Оригинальное имя пользователя
        normalized_name: Нормализованное имя (для отладки/журнала)
    """
    matched: bool
    pattern: Optional[AntiRaidNamePattern] = None
    original_name: str = ""
    normalized_name: str = ""


def get_full_name(user: User) -> str:
    """
    Получает полное имя пользователя (first_name + last_name).

    Args:
        user: Объект пользователя Telegram

    Returns:
        Полное имя в формате "first_name last_name" или просто "first_name"
    """
    # Получаем first_name (всегда присутствует)
    first_name = user.first_name or ""

    # Получаем last_name (может быть None)
    last_name = user.last_name or ""

    # Объединяем с пробелом, убирая лишние пробелы
    full_name = f"{first_name} {last_name}".strip()

    return full_name


def normalize_name(name: str) -> str:
    """
    Нормализует имя для сравнения с паттернами.

    Этапы:
    1. Удаление точек и пробелов (разделители в обфускации)
    2. Применение TextNormalizer (leet-speak, unicode, etc.)

    Пример:
        "Д.е́. t.С.k.ő.ē TKL98ВОТ" → "детское"

    Args:
        name: Оригинальное имя пользователя

    Returns:
        Нормализованное имя (lowercase, без обфускации)
    """
    # Проверяем на пустое имя
    if not name:
        return ""

    # ─────────────────────────────────────────────────────────
    # ШАГ 1: Удаляем точки и пробелы (разделители обфускации)
    # ─────────────────────────────────────────────────────────
    # Спамеры вставляют точки между буквами: "Д.е.т.с.к.о.е"
    # Также удаляем пробелы чтобы "Д е т с к о е" стало "детское"
    # Удаляем: точки, пробелы, запятые, дефисы, подчёркивания
    no_separators = re.sub(r'[.\s,\-_]+', '', name)

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: Применяем TextNormalizer
    # ─────────────────────────────────────────────────────────
    # Это обработает:
    # - Leet-speak: 0→о, 1→и, 3→з, @→а
    # - Греческие буквы: κ→к, ρ→р, ο→о
    # - Small caps: ᴀ→а, ᴋ→к
    # - Combining marks (ударения, зачёркивания)
    # - Fullwidth и circled letters
    normalized = _normalizer.normalize(no_separators)

    # Логируем для отладки (debug уровень)
    logger.debug(
        f"Нормализация имени: '{name}' → (no_sep: '{no_separators}') → '{normalized}'"
    )

    return normalized


def check_pattern_match(
    normalized_name: str,
    pattern: AntiRaidNamePattern
) -> bool:
    """
    Проверяет совпадение нормализованного имени с паттерном.

    Поддерживает три типа паттернов:
    - 'contains': имя содержит паттерн как подстроку
    - 'regex': имя матчит регулярное выражение
    - 'exact': точное совпадение (редко используется)

    Args:
        normalized_name: Нормализованное имя пользователя
        pattern: Объект паттерна из БД

    Returns:
        True если имя матчит паттерн
    """
    # ВАЖНО: Нормализуем паттерн так же как имя!
    # Это позволяет добавлять паттерны в любом виде:
    # - "Д.е́. t.С.k.ő.ē" → нормализуется в "детское"
    # - "детское" → остаётся "детское"
    # - "detskoe" → нормализуется в "детское"
    pattern_text = normalize_name(pattern.pattern)

    # Проверяем в зависимости от типа паттерна
    if pattern.pattern_type == 'contains':
        # ─────────────────────────────────────────────────────────
        # ТИП: CONTAINS — имя содержит паттерн как подстроку
        # ─────────────────────────────────────────────────────────
        # Самый частый случай: паттерн "детск" найдёт "детское", "детский"
        return pattern_text in normalized_name

    elif pattern.pattern_type == 'regex':
        # ─────────────────────────────────────────────────────────
        # ТИП: REGEX — имя матчит регулярное выражение
        # ─────────────────────────────────────────────────────────
        # Для сложных случаев: паттерн "дет.*ое" найдёт "детское"
        try:
            # Компилируем regex с флагом IGNORECASE
            regex = re.compile(pattern_text, re.IGNORECASE)
            # Ищем совпадение
            return bool(regex.search(normalized_name))
        except re.error as e:
            # Если regex невалидный — логируем ошибку и пропускаем
            logger.error(
                f"Невалидный regex паттерн id={pattern.id}: '{pattern.pattern}' - {e}"
            )
            return False

    elif pattern.pattern_type == 'exact':
        # ─────────────────────────────────────────────────────────
        # ТИП: EXACT — точное совпадение
        # ─────────────────────────────────────────────────────────
        # Редко используется: паттерн "спамер" найдёт только "спамер"
        return normalized_name == pattern_text

    else:
        # Неизвестный тип — логируем предупреждение
        logger.warning(
            f"Неизвестный тип паттерна id={pattern.id}: '{pattern.pattern_type}'"
        )
        return False


async def check_name_against_patterns(
    session: AsyncSession,
    user: User,
    chat_id: int
) -> NameCheckResult:
    """
    Проверяет имя пользователя по паттернам группы.

    Это ОСНОВНАЯ функция модуля. Вызывается при:
    - chat_member событии (join)
    - chat_join_request событии

    Args:
        session: Асинхронная сессия SQLAlchemy
        user: Объект пользователя Telegram
        chat_id: ID группы

    Returns:
        NameCheckResult с результатом проверки
    """
    # Получаем полное имя пользователя
    original_name = get_full_name(user)

    # Если имя пустое — пропускаем проверку
    if not original_name:
        logger.debug(f"Пустое имя у user_id={user.id}, пропускаем проверку")
        return NameCheckResult(
            matched=False,
            original_name="",
            normalized_name=""
        )

    # Нормализуем имя
    normalized_name = normalize_name(original_name)

    # Если после нормализации имя пустое — пропускаем
    if not normalized_name:
        logger.debug(
            f"Имя стало пустым после нормализации: '{original_name}' → '', "
            f"user_id={user.id}"
        )
        return NameCheckResult(
            matched=False,
            original_name=original_name,
            normalized_name=""
        )

    # ─────────────────────────────────────────────────────────
    # Проверяем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или name_pattern выключен — пропускаем
    if settings is None or not settings.name_pattern_enabled:
        logger.debug(
            f"Name pattern проверка отключена для chat_id={chat_id}"
        )
        return NameCheckResult(
            matched=False,
            original_name=original_name,
            normalized_name=normalized_name
        )

    # ─────────────────────────────────────────────────────────
    # Получаем активные паттерны группы
    # ─────────────────────────────────────────────────────────
    patterns = await get_enabled_name_patterns(session, chat_id)

    # Если паттернов нет — пропускаем
    if not patterns:
        logger.debug(f"Нет активных паттернов для chat_id={chat_id}")
        return NameCheckResult(
            matched=False,
            original_name=original_name,
            normalized_name=normalized_name
        )

    # ─────────────────────────────────────────────────────────
    # Проверяем имя по каждому паттерну
    # ─────────────────────────────────────────────────────────
    for pattern in patterns:
        # Проверяем совпадение
        if check_pattern_match(normalized_name, pattern):
            # МАТЧ! Логируем с уровнем WARNING (важное событие)
            logger.warning(
                f"[ANTIRAID] Name pattern MATCH! "
                f"user_id={user.id}, "
                f"original='{original_name}', "
                f"normalized='{normalized_name}', "
                f"pattern_id={pattern.id}, "
                f"pattern='{pattern.pattern}', "
                f"chat_id={chat_id}"
            )

            # Возвращаем результат с информацией о совпадении
            return NameCheckResult(
                matched=True,
                pattern=pattern,
                original_name=original_name,
                normalized_name=normalized_name
            )

    # Ни один паттерн не сработал
    logger.debug(
        f"Name pattern проверка: OK, "
        f"user_id={user.id}, "
        f"normalized='{normalized_name}', "
        f"patterns_checked={len(patterns)}"
    )

    return NameCheckResult(
        matched=False,
        original_name=original_name,
        normalized_name=normalized_name
    )


async def is_name_banned(
    session: AsyncSession,
    user: User,
    chat_id: int
) -> bool:
    """
    Простая обёртка: проверяет должен ли пользователь быть забанен по имени.

    Это упрощённый интерфейс для использования в координаторе.

    Args:
        session: Асинхронная сессия SQLAlchemy
        user: Объект пользователя Telegram
        chat_id: ID группы

    Returns:
        True если пользователь должен быть забанен по имени
    """
    result = await check_name_against_patterns(session, user, chat_id)
    return result.matched
