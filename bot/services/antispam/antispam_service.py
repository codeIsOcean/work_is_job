"""
Сервис антиспам - бизнес-логика проверки сообщений и управления правилами.

Этот модуль содержит всю логику для:
- Проверки сообщений на спам (ссылки, пересылки, цитаты)
- Управления правилами антиспам (CRUD операции)
- Управления белым списком исключений
- Применения настроенных действий к нарушителям
"""

# Импорт типов для аннотаций
from typing import Optional, List, Dict, Any, Tuple
# Импорт dataclass для создания класса данных
from dataclasses import dataclass
# Импорт регулярных выражений для поиска ссылок
import re
# Импорт логгера для отладки
import logging
# Импорт urllib.parse для извлечения домена из URL
from urllib.parse import urlparse

# Импорт типов aiogram для работы с сообщениями
from aiogram import types
# Импорт асинхронной сессии SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession
# Импорт функций SQLAlchemy для запросов
from sqlalchemy import select, delete, and_, or_
# Импорт функции для создания времени UTC
from sqlalchemy.sql import func

# Импорт моделей антиспам
from bot.database.models_antispam import (
    AntiSpamRule,
    AntiSpamWhitelist,
    RuleType,
    ActionType,
    WhitelistScope,
)

# Создание логгера для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# DATACLASS ДЛЯ РЕЗУЛЬТАТА ПРОВЕРКИ НА СПАМ
# ============================================================

# Декоратор dataclass для автоматической генерации __init__, __repr__ и других методов
@dataclass
class AntiSpamDecision:
    """
    Результат проверки сообщения на спам.

    Содержит всю информацию о том, является ли сообщение спамом
    и какие действия нужно предпринять.
    """
    # Является ли сообщение спамом (нарушает ли правила)
    is_spam: bool
    # Нужно ли удалить сообщение
    delete_message: bool
    # Действие которое нужно применить (OFF, WARN, KICK, RESTRICT, BAN)
    action: ActionType
    # Длительность ограничения в минутах (только для action=RESTRICT)
    restrict_minutes: Optional[int]
    # Тип правила которое сработало (для логирования)
    triggered_rule_type: Optional[RuleType]
    # Причина срабатывания (текст для администратора)
    reason: Optional[str]


# ============================================================
# РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ ДЛЯ ПОИСКА ССЫЛОК
# ============================================================

# Паттерн для поиска HTTP/HTTPS ссылок в тексте
# Ищет последовательности типа http://... или https://...
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    # Флаг IGNORECASE для поиска независимо от регистра
    re.IGNORECASE
)

# Паттерн для поиска Telegram ссылок
# Ищет: t.me/..., telegram.me/..., tg://...
TELEGRAM_LINK_PATTERN = re.compile(
    r'(https?://)?(t\.me|telegram\.me)/[a-zA-Z0-9_]+|tg://[^\s]+',
    # Флаг IGNORECASE для поиска независимо от регистра
    re.IGNORECASE
)


# ============================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С URL И ДОМЕНАМИ
# ============================================================

def normalize_url_for_comparison(url: str) -> str:
    """
    Нормализует URL для сравнения в whitelist.

    Убирает:
    - http:// и https://
    - www.
    - trailing slash
    - приводит к нижнему регистру

    Примеры:
        https://www.youtube.com/watch?v=123 → youtube.com/watch?v=123
        https://t.me/beauty_indubai/ → t.me/beauty_indubai
        t.me/channel → t.me/channel

    Args:
        url: URL для нормализации

    Returns:
        Нормализованный URL
    """
    normalized = url.strip().lower()
    # Убираем протокол
    if normalized.startswith('https://'):
        normalized = normalized[8:]
    elif normalized.startswith('http://'):
        normalized = normalized[7:]
    # Убираем www.
    if normalized.startswith('www.'):
        normalized = normalized[4:]
    # Убираем trailing slash
    normalized = normalized.rstrip('/')
    return normalized


def extract_path_from_url(url: str) -> Optional[str]:
    """
    Извлечь путь из URL (без домена).

    Примеры:
        https://t.me/beauty_indubai → /beauty_indubai
        https://youtube.com/watch?v=123 → /watch?v=123
        https://youtube.com/ → None (пустой путь)
        https://youtube.com → None

    Args:
        url: URL для извлечения пути

    Returns:
        Путь или None если путь пустой
    """
    # Нормализуем URL
    if not url.startswith(('http://', 'https://')):
        if '.' in url and ' ' not in url:
            url = 'https://' + url
        else:
            return None

    try:
        parsed = urlparse(url)
        path = parsed.path
        # Пустой путь или только /
        if not path or path == '/':
            return None
        # Добавляем query string если есть
        if parsed.query:
            path = path + '?' + parsed.query
        return path
    except Exception:
        return None


def is_domain_only_pattern(pattern: str) -> bool:
    """
    Проверить является ли паттерн только доменом (без пути).

    Примеры:
        youtube.com → True
        youtube.com/ → True
        t.me → True
        t.me/channel → False
        youtube.com/watch?v=123 → False

    Args:
        pattern: Паттерн для проверки

    Returns:
        True если паттерн - только домен
    """
    # Нормализуем паттерн
    normalized = normalize_url_for_comparison(pattern)

    # Если нет слеша - это домен
    if '/' not in normalized:
        return True

    # Если единственный слеш в конце - это домен
    if normalized.endswith('/') and normalized.count('/') == 1:
        return True

    return False


def extract_domain_from_url(url: str) -> Optional[str]:
    """
    Извлечь домен из URL.

    Примеры:
        https://maps.app.goo.gl/WazdAuvRaY2JV38j9 → maps.app.goo.gl
        https://www.youtube.com/watch?v=xyz → youtube.com (без www)
        https://t.me/mygroup → t.me
        простой_текст → None

    Args:
        url: URL для извлечения домена

    Returns:
        Домен в нижнем регистре или None если не удалось извлечь
    """
    # Если URL не начинается с http:// или https://, пробуем добавить
    if not url.startswith(('http://', 'https://')):
        # Проверяем есть ли похожая структура домена (содержит точку)
        if '.' in url and ' ' not in url:
            # Добавляем https:// для парсинга
            url = 'https://' + url
        else:
            # Это не URL - возвращаем None
            return None

    try:
        # Парсим URL с помощью urlparse
        parsed = urlparse(url)
        # Получаем netloc (домен с портом)
        domain = parsed.netloc
        # Если домен пустой - возвращаем None
        if not domain:
            return None
        # Убираем www. в начале для унификации
        if domain.startswith('www.'):
            domain = domain[4:]
        # Убираем порт если есть (например :8080)
        if ':' in domain:
            domain = domain.split(':')[0]
        # Приводим к нижнему регистру
        return domain.lower()
    except Exception:
        # При ошибке парсинга возвращаем None
        return None


def is_url(text: str) -> bool:
    """
    Проверить является ли текст URL (начинается с http:// или https://).

    Args:
        text: Текст для проверки

    Returns:
        True если это URL, False иначе
    """
    # Нормализуем текст - убираем пробелы
    text = text.strip().lower()
    # Проверяем начинается ли с http:// или https://
    return text.startswith(('http://', 'https://'))


def extract_username_from_telegram_link(text: str) -> Optional[str]:
    """
    Извлечь username из Telegram ссылки.

    Поддерживаемые форматы:
        https://t.me/channel_name → @channel_name
        t.me/channel_name → @channel_name
        @channel_name → @channel_name
        channel_name → None (не ссылка и не username)

    Args:
        text: Текст для извлечения (ссылка или username)

    Returns:
        Username в формате @channel_name или None
    """
    if not text:
        return None

    # Убираем пробелы
    text = text.strip().lower()

    # Если уже в формате @username - возвращаем как есть
    if text.startswith('@'):
        return text

    # Паттерн для извлечения username из t.me ссылки
    # Поддерживает: https://t.me/name, http://t.me/name, t.me/name, telegram.me/name
    tg_pattern = re.compile(
        r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z][a-zA-Z0-9_]{3,30})(?:/.*)?$',
        re.IGNORECASE
    )

    match = tg_pattern.match(text)
    if match:
        username = match.group(1)
        return f"@{username.lower()}"

    return None


# ============================================================
# ФУНКЦИИ РАБОТЫ С ПРАВИЛАМИ АНТИСПАМ
# ============================================================

async def get_rules_for_chat(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата для которого получаем правила
    chat_id: int,
) -> List[AntiSpamRule]:
    """
    Получить все правила антиспам для конкретного чата.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)

    Returns:
        Список всех правил антиспам для чата
    """
    # Создаем SQL запрос для выборки правил по chat_id
    stmt = select(AntiSpamRule).where(AntiSpamRule.chat_id == chat_id)
    # Выполняем запрос асинхронно
    result = await session.execute(stmt)
    # Получаем все записи из результата
    rules = result.scalars().all()
    # Возвращаем список правил
    return list(rules)


async def get_rule_by_type(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # Тип правила (TELEGRAM_LINK, FORWARD_CHANNEL и т.д.)
    rule_type: RuleType,
) -> Optional[AntiSpamRule]:
    """
    Получить правило антиспам по типу для конкретного чата.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        rule_type: Тип правила

    Returns:
        Правило если найдено, иначе None
    """
    # Создаем SQL запрос с фильтрацией по chat_id и rule_type
    stmt = select(AntiSpamRule).where(
        # Условие: chat_id совпадает
        and_(
            AntiSpamRule.chat_id == chat_id,
            # И rule_type совпадает
            AntiSpamRule.rule_type == rule_type
        )
    )
    # Выполняем запрос асинхронно
    result = await session.execute(stmt)
    # Получаем первую запись или None
    rule = result.scalar_one_or_none()
    # Возвращаем правило
    return rule


async def upsert_rule(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # Тип правила
    rule_type: RuleType,
    # Действие при срабатывании
    action: ActionType,
    # Флаг удаления сообщения
    delete_message: bool,
    # Длительность ограничения (опционально)
    restrict_minutes: Optional[int] = None,
) -> AntiSpamRule:
    """
    Создать или обновить правило антиспам (upsert).

    Если правило с таким chat_id и rule_type уже существует - обновляем его.
    Если не существует - создаем новое.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        rule_type: Тип правила
        action: Действие при срабатывании
        delete_message: Удалять ли сообщение
        restrict_minutes: Длительность ограничения в минутах

    Returns:
        Созданное или обновленное правило
    """
    # Пытаемся найти существующее правило
    existing_rule = await get_rule_by_type(session, chat_id, rule_type)

    # Если правило существует - обновляем его
    if existing_rule:
        # Обновляем действие
        existing_rule.action = action
        # Обновляем флаг удаления сообщения
        existing_rule.delete_message = delete_message
        # Обновляем длительность ограничения
        existing_rule.restrict_minutes = restrict_minutes
        # Обновляем время последнего изменения (автоматически через onupdate)
        # session.add не нужен, т.к. объект уже в сессии
        # Логируем обновление правила
        logger.info(
            f"Updated antispam rule: chat_id={chat_id}, "
            f"rule_type={rule_type}, action={action}"
        )
        # Возвращаем обновленное правило
        return existing_rule

    # Если правило не существует - создаем новое
    else:
        # Создаем новый экземпляр правила
        new_rule = AntiSpamRule(
            # ID чата
            chat_id=chat_id,
            # Тип правила
            rule_type=rule_type,
            # Действие
            action=action,
            # Флаг удаления сообщения
            delete_message=delete_message,
            # Длительность ограничения
            restrict_minutes=restrict_minutes,
        )
        # Добавляем новое правило в сессию
        session.add(new_rule)
        # Сбрасываем изменения в БД для получения ID
        await session.flush()
        # Логируем создание правила
        logger.info(
            f"Created new antispam rule: chat_id={chat_id}, "
            f"rule_type={rule_type}, action={action}"
        )
        # Возвращаем новое правило
        return new_rule


# ============================================================
# ФУНКЦИИ РАБОТЫ С БЕЛЫМ СПИСКОМ
# ============================================================

async def add_whitelist_pattern(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # Область применения (TELEGRAM_LINK, ANY_LINK, FORWARD, QUOTE)
    scope: WhitelistScope,
    # Паттерн для проверки (часть URL, домен или ID)
    pattern: str,
    # ID пользователя который добавляет
    added_by: int,
) -> AntiSpamWhitelist:
    """
    Добавить паттерн в белый список для чата.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        scope: Область применения белого списка
        pattern: Паттерн (часть URL, домен или ID канала/группы)
        added_by: ID пользователя (администратора) который добавляет

    Returns:
        Созданная запись белого списка
    """
    # Нормализуем паттерн: убираем пробелы в начале и конце
    normalized_pattern = pattern.strip()
    # Приводим паттерн к нижнему регистру для унифицированного поиска
    normalized_pattern = normalized_pattern.lower()

    # Создаем новую запись белого списка
    whitelist_entry = AntiSpamWhitelist(
        # ID чата
        chat_id=chat_id,
        # Область применения
        scope=scope,
        # Нормализованный паттерн
        pattern=normalized_pattern,
        # Кто добавил
        added_by=added_by,
    )
    # Добавляем запись в сессию
    session.add(whitelist_entry)
    # Сбрасываем изменения в БД для получения ID
    await session.flush()
    # Логируем добавление в белый список
    logger.info(
        f"Added whitelist pattern: chat_id={chat_id}, "
        f"scope={scope}, pattern={normalized_pattern}"
    )
    # Возвращаем созданную запись
    return whitelist_entry


async def remove_whitelist_pattern(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # ID записи белого списка для удаления
    whitelist_id: int,
) -> bool:
    """
    Удалить паттерн из белого списка по ID.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы) для проверки прав
        whitelist_id: ID записи белого списка

    Returns:
        True если удалено успешно, False если запись не найдена
    """
    # Создаем SQL запрос для удаления с проверкой chat_id
    stmt = delete(AntiSpamWhitelist).where(
        # Условие: ID записи совпадает
        and_(
            AntiSpamWhitelist.id == whitelist_id,
            # И chat_id совпадает (для безопасности)
            AntiSpamWhitelist.chat_id == chat_id
        )
    )
    # Выполняем запрос асинхронно
    result = await session.execute(stmt)
    # Проверяем количество удаленных записей
    deleted_count = result.rowcount

    # Если запись была удалена
    if deleted_count > 0:
        # Логируем удаление
        logger.info(
            f"Removed whitelist pattern: chat_id={chat_id}, "
            f"whitelist_id={whitelist_id}"
        )
        # Возвращаем True
        return True
    # Если запись не найдена
    else:
        # Логируем что запись не найдена
        logger.warning(
            f"Whitelist pattern not found: chat_id={chat_id}, "
            f"whitelist_id={whitelist_id}"
        )
        # Возвращаем False
        return False


async def list_whitelist_patterns(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # Область применения (опционально, для фильтрации)
    scope: Optional[WhitelistScope] = None,
) -> List[AntiSpamWhitelist]:
    """
    Получить список всех паттернов белого списка для чата.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        scope: Область применения для фильтрации (опционально)

    Returns:
        Список записей белого списка
    """
    # Создаем базовый SQL запрос
    stmt = select(AntiSpamWhitelist).where(AntiSpamWhitelist.chat_id == chat_id)

    # Если указана область применения - добавляем фильтр
    if scope is not None:
        # Добавляем условие фильтрации по scope
        stmt = stmt.where(AntiSpamWhitelist.scope == scope)

    # Сортируем по дате добавления (сначала новые)
    stmt = stmt.order_by(AntiSpamWhitelist.added_at.desc())

    # Выполняем запрос асинхронно
    result = await session.execute(stmt)
    # Получаем все записи
    patterns = result.scalars().all()
    # Возвращаем список
    return list(patterns)


async def get_whitelist_by_id(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID записи белого списка
    whitelist_id: int,
) -> Optional[AntiSpamWhitelist]:
    """
    Получить запись белого списка по ID.

    Args:
        session: Асинхронная сессия БД
        whitelist_id: ID записи белого списка

    Returns:
        Запись белого списка если найдена, иначе None
    """
    # Создаем SQL запрос для поиска по ID
    stmt = select(AntiSpamWhitelist).where(AntiSpamWhitelist.id == whitelist_id)
    # Выполняем запрос асинхронно
    result = await session.execute(stmt)
    # Получаем первую запись или None
    entry = result.scalar_one_or_none()
    # Возвращаем запись
    return entry


async def check_whitelist(
    # Асинхронная сессия БД
    session: AsyncSession,
    # ID чата
    chat_id: int,
    # Область применения
    scope: WhitelistScope,
    # Строка для проверки (URL, ID канала и т.д.)
    check_string: str,
) -> bool:
    """
    Проверить находится ли строка в белом списке.

    УМНАЯ ЛОГИКА:
    1. Если паттерн - только домен (youtube.com) → разрешает весь домен
    2. Если паттерн содержит путь (t.me/channel) → разрешает только этот путь и подпути

    Примеры:
        Паттерн "youtube.com" → разрешает youtube.com/anything
        Паттерн "t.me/beauty_indubai" → разрешает только t.me/beauty_indubai и t.me/beauty_indubai/123
        Паттерн "t.me" → НЕ РЕКОМЕНДУЕТСЯ (слишком широко)

    Args:
        session: Асинхронная сессия БД
        chat_id: ID чата (группы)
        scope: Область применения
        check_string: Строка для проверки

    Returns:
        True если строка в белом списке, False иначе
    """
    # Нормализуем проверяемую строку к нижнему регистру
    normalized_string = check_string.lower()

    # Извлекаем домен из проверяемой строки (если это URL)
    check_domain = extract_domain_from_url(check_string)

    # Нормализуем URL для сравнения (без протокола, без www, без trailing slash)
    normalized_check_url = normalize_url_for_comparison(check_string)

    # Получаем все паттерны белого списка для данного scope
    whitelist_patterns = await list_whitelist_patterns(session, chat_id, scope)

    # Извлекаем username из проверяемой строки (если это @username)
    # Для проверки forwards/quotes по username
    check_username = None
    if normalized_string.startswith('@'):
        check_username = normalized_string

    # Проходим по каждому паттерну из белого списка
    for entry in whitelist_patterns:
        # Нормализуем паттерн
        normalized_pattern = normalize_url_for_comparison(entry.pattern)
        pattern_domain = extract_domain_from_url(entry.pattern)

        # ============================================================
        # ПРОВЕРКА 1: Паттерн - только домен (без пути)
        # Пример: "youtube.com" или "youtube.com/" → разрешает весь домен
        # ============================================================
        if is_domain_only_pattern(entry.pattern):
            if check_domain and pattern_domain and check_domain == pattern_domain:
                logger.info(
                    f"Whitelist match (domain): chat_id={chat_id}, scope={scope}, "
                    f"pattern='{entry.pattern}' (domain={pattern_domain}) matches '{check_string}'"
                )
                return True
            # Также проверяем если паттерн - это просто домен (без http://)
            if check_domain and entry.pattern.lower() == check_domain:
                logger.info(
                    f"Whitelist match (domain direct): chat_id={chat_id}, scope={scope}, "
                    f"pattern='{entry.pattern}' equals domain='{check_domain}'"
                )
                return True

        # ============================================================
        # ПРОВЕРКА 2: Паттерн содержит путь
        # Пример: "t.me/channel" → разрешает только t.me/channel и t.me/channel/123
        # ============================================================
        else:
            # Проверяем что нормализованный URL начинается с нормализованного паттерна
            # Это позволяет: t.me/channel матчит t.me/channel и t.me/channel/123
            if normalized_check_url.startswith(normalized_pattern):
                # Дополнительная проверка: после паттерна должен быть конец, / или ?
                # Это предотвращает: t.me/chan НЕ матчит t.me/channel
                rest = normalized_check_url[len(normalized_pattern):]
                if not rest or rest.startswith('/') or rest.startswith('?'):
                    logger.info(
                        f"Whitelist match (path prefix): chat_id={chat_id}, scope={scope}, "
                        f"pattern='{entry.pattern}' is prefix of '{check_string}'"
                    )
                    return True

        # ============================================================
        # ПРОВЕРКА 3: Совпадение username (для forwards/quotes)
        # Пример: паттерн "https://t.me/channel" или "t.me/channel" или "@channel"
        # должен матчить проверку по "@channel"
        # ============================================================
        if check_username:
            # Извлекаем username из паттерна (если это t.me ссылка или @username)
            pattern_username = extract_username_from_telegram_link(entry.pattern)
            if pattern_username and check_username == pattern_username:
                logger.info(
                    f"Whitelist match (username from link): chat_id={chat_id}, scope={scope}, "
                    f"pattern='{entry.pattern}' → username='{pattern_username}' matches '{check_username}'"
                )
                return True

    # Если ни один паттерн не подошел - возвращаем False
    return False


# ============================================================
# ФУНКЦИИ АНАЛИЗА КОНТЕНТА СООБЩЕНИЙ
# ============================================================

def extract_links(
    # Текст сообщения
    text: str
) -> List[str]:
    """
    Извлечь все HTTP/HTTPS ссылки из текста.

    Args:
        text: Текст сообщения

    Returns:
        Список найденных ссылок
    """
    # Если текст пустой или None - возвращаем пустой список
    if not text:
        # Возвращаем пустой список
        return []

    # Ищем все совпадения с паттерном URL
    links = URL_PATTERN.findall(text)
    # Возвращаем список ссылок
    return links


def extract_links_from_entities(
    # Объект сообщения aiogram
    message: types.Message
) -> List[str]:
    """
    Извлечь все URL из entities сообщения.

    Telegram хранит ссылки в entities двух типов:
    - url: видимая ссылка (https://example.com в тексте)
    - text_link: скрытая ссылка (текст "нажми сюда" со скрытым URL)

    НЕ извлекаем:
    - mention: обычные @username (не являются ссылками)
    - text_mention: упоминания по user_id

    Args:
        message: Объект сообщения aiogram

    Returns:
        Список найденных URL из entities
    """
    # Инициализируем список для найденных URL
    urls = []

    # Получаем entities из сообщения (или caption_entities для медиа)
    entities = message.entities or message.caption_entities or []

    # Получаем текст сообщения для извлечения URL из entity типа 'url'
    text = message.text or message.caption or ""

    # Перебираем все entities
    for entity in entities:
        # Проверяем тип entity - text_link (скрытая ссылка)
        if entity.type == "text_link":
            # URL хранится в атрибуте url у text_link entity
            if entity.url:
                # Добавляем URL в список
                urls.append(entity.url)
                # Логируем найденную скрытую ссылку
                logger.debug(f"[ANTISPAM] Найден text_link URL: {entity.url}")

        # Проверяем тип entity - url (видимая ссылка в тексте)
        elif entity.type == "url":
            # Извлекаем URL из текста по offset и length
            url_text = text[entity.offset:entity.offset + entity.length]
            # Добавляем URL в список
            urls.append(url_text)
            # Логируем найденную видимую ссылку
            logger.debug(f"[ANTISPAM] Найден url entity: {url_text}")

        # ИГНОРИРУЕМ mention (@username) и text_mention (упоминание по user_id)
        # Это НЕ ссылки, это упоминания пользователей

    # Возвращаем список найденных URL
    return urls


def is_telegram_link(
    # Ссылка для проверки
    url: str
) -> bool:
    """
    Проверить является ли ссылка Telegram ссылкой.

    Проверяет паттерны: t.me/..., telegram.me/..., tg://...

    Args:
        url: URL для проверки

    Returns:
        True если это Telegram ссылка, False иначе
    """
    # Проверяем совпадение с паттерном Telegram ссылки
    match = TELEGRAM_LINK_PATTERN.search(url)
    # Возвращаем True если есть совпадение, иначе False
    return match is not None


def detect_forward_source(
    # Объект сообщения aiogram
    message: types.Message
) -> Optional[RuleType]:
    """
    Определить тип источника пересылки.

    Args:
        message: Объект сообщения aiogram

    Returns:
        Тип правила (FORWARD_CHANNEL, FORWARD_GROUP, FORWARD_USER, FORWARD_BOT)
        или None если сообщение не является пересылкой
    """
    # Проверяем есть ли информация о пересылке
    if not message.forward_origin:
        # Это не пересылка - возвращаем None
        return None

    # Получаем объект пересылки
    forward_origin = message.forward_origin

    # Проверяем тип пересылки по типу forward_origin
    # Пересылка из канала (forward_origin имеет тип MessageOriginChannel)
    if hasattr(forward_origin, 'chat') and forward_origin.chat:
        # Получаем объект чата источника
        source_chat = forward_origin.chat
        # Проверяем тип чата - канал
        if source_chat.type == "channel":
            # Возвращаем тип правила для канала
            return RuleType.FORWARD_CHANNEL
        # Проверяем тип чата - группа или супергруппа
        elif source_chat.type in ("group", "supergroup"):
            # Возвращаем тип правила для группы
            return RuleType.FORWARD_GROUP

    # Пересылка от пользователя (forward_origin имеет тип MessageOriginUser)
    if hasattr(forward_origin, 'sender_user') and forward_origin.sender_user:
        # Получаем объект пользователя-источника
        source_user = forward_origin.sender_user
        # Проверяем является ли источник ботом
        if source_user.is_bot:
            # Возвращаем тип правила для бота
            return RuleType.FORWARD_BOT
        # Иначе это обычный пользователь
        else:
            # Возвращаем тип правила для пользователя
            return RuleType.FORWARD_USER

    # Если не удалось определить тип - возвращаем None
    return None


def detect_quote_source(
    # Объект сообщения aiogram
    message: types.Message
) -> Optional[RuleType]:
    """
    Определить тип источника цитаты.

    Цитата - это когда пользователь отвечает на сообщение с выбранным текстом.
    В aiogram это определяется через reply_to_message и quote.

    Args:
        message: Объект сообщения aiogram

    Returns:
        Тип правила (QUOTE_CHANNEL, QUOTE_GROUP, QUOTE_USER, QUOTE_BOT)
        или None если сообщение не содержит цитату
    """
    # Проверяем есть ли ответ на сообщение
    if not message.reply_to_message:
        # Это не ответ/цитата - возвращаем None
        return None

    # Проверяем есть ли объект quote (цитата)
    if not hasattr(message, 'quote') or not message.quote:
        # Это простой ответ без цитаты - возвращаем None
        return None

    # Получаем исходное сообщение на которое отвечают
    replied_message = message.reply_to_message

    # Проверяем откуда цитата - из какого чата
    if replied_message.forward_origin:
        # Цитата из пересланного сообщения - определяем источник пересылки
        forward_origin = replied_message.forward_origin

        # Цитата из канала
        if hasattr(forward_origin, 'chat') and forward_origin.chat:
            # Получаем объект чата
            source_chat = forward_origin.chat
            # Проверяем тип чата - канал
            if source_chat.type == "channel":
                # Возвращаем тип правила для цитаты из канала
                return RuleType.QUOTE_CHANNEL
            # Проверяем тип чата - группа
            elif source_chat.type in ("group", "supergroup"):
                # Возвращаем тип правила для цитаты из группы
                return RuleType.QUOTE_GROUP

        # Цитата от пользователя/бота
        if hasattr(forward_origin, 'sender_user') and forward_origin.sender_user:
            # Получаем пользователя
            source_user = forward_origin.sender_user
            # Проверяем является ли бот
            if source_user.is_bot:
                # Возвращаем тип правила для цитаты от бота
                return RuleType.QUOTE_BOT
            # Обычный пользователь
            else:
                # Возвращаем тип правила для цитаты от пользователя
                return RuleType.QUOTE_USER

    # Если цитата из текущего чата (не из пересылки)
    # Проверяем автора исходного сообщения
    if replied_message.from_user:
        # Получаем пользователя
        author = replied_message.from_user
        # Проверяем является ли бот
        if author.is_bot:
            # Возвращаем тип правила для цитаты от бота
            return RuleType.QUOTE_BOT
        # Обычный пользователь
        else:
            # Возвращаем тип правила для цитаты от пользователя
            return RuleType.QUOTE_USER

    # Если не удалось определить тип - возвращаем None
    return None


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ ПРОВЕРКИ СООБЩЕНИЯ НА СПАМ
# ============================================================

async def check_message_for_spam(
    # Объект сообщения aiogram
    message: types.Message,
    # Асинхронная сессия БД
    session: AsyncSession,
) -> AntiSpamDecision:
    """
    Проверить сообщение на спам согласно настроенным правилам.

    Эта функция:
    1. Анализирует сообщение (ссылки, пересылки, цитаты)
    2. Определяет какие правила применимы
    3. Проверяет белые списки
    4. Возвращает решение о том, что делать с сообщением

    Args:
        message: Объект сообщения aiogram
        session: Асинхронная сессия БД

    Returns:
        AntiSpamDecision с информацией о том, является ли сообщение спамом
    """
    # Получаем ID чата
    chat_id = message.chat.id

    # ============================================================
    # ИСКЛЮЧЕНИЕ: Telegram (user_id 777000)
    # ============================================================
    # User ID 777000 — это официальный аккаунт Telegram, который
    # пересылает сообщения из СВЯЗАННОГО канала в группу.
    # Это НЕ спам — это легитимная функция Telegram!
    # Пропускаем такие сообщения без проверки.
    if message.from_user and message.from_user.id == 777000:
        logger.debug(
            f"[Antispam] Пропускаем сообщение от Telegram (777000) — "
            f"это пересылка из связанного канала"
        )
        return AntiSpamDecision(
            is_spam=False,
            delete_message=False,
            action=ActionType.OFF,
            restrict_minutes=None,
            triggered_rule_type=None,
            reason=None,
        )

    # Инициализируем переменные для результата
    # По умолчанию - не спам
    is_spam = False
    # По умолчанию - не удаляем сообщение
    delete_message = False
    # По умолчанию - действие OFF (ничего не делать)
    action = ActionType.OFF
    # По умолчанию - нет длительности ограничения
    restrict_minutes = None
    # По умолчанию - правило не сработало
    triggered_rule_type = None
    # По умолчанию - нет причины
    reason = None

    # ============================================================
    # ШАГ 1: ПРОВЕРКА ПЕРЕСЫЛОК
    # ============================================================

    # Определяем является ли сообщение пересылкой
    forward_source = detect_forward_source(message)
    # Если это пересылка
    if forward_source:
        # Получаем правило для этого типа пересылки
        rule = await get_rule_by_type(session, chat_id, forward_source)
        # Если правило существует и активно (не OFF)
        if rule and rule.action != ActionType.OFF:
            # Формируем строку для проверки белого списка (ID чата источника)
            # Для пересылок проверяем по ID чата источника
            is_whitelisted = False
            source_chat = None

            if hasattr(message.forward_origin, 'chat') and message.forward_origin.chat:
                source_chat = message.forward_origin.chat
                # Проверяем по ID чата
                check_string = str(source_chat.id)
                is_whitelisted = await check_whitelist(
                    session,
                    chat_id,
                    WhitelistScope.FORWARD,
                    check_string
                )
                # Если не в whitelist по ID, проверяем по username
                if not is_whitelisted and source_chat.username:
                    username_check = f"@{source_chat.username}"
                    is_whitelisted = await check_whitelist(
                        session,
                        chat_id,
                        WhitelistScope.FORWARD,
                        username_check
                    )
                    if is_whitelisted:
                        logger.info(f"Whitelist match by username: {username_check}")

            # Если НЕ в белом списке - применяем правило
            if not is_whitelisted:
                # Это спам
                is_spam = True
                # Флаг удаления из правила
                delete_message = rule.delete_message
                # Действие из правила
                action = rule.action
                # Длительность из правила
                restrict_minutes = rule.restrict_minutes
                # Сохраняем тип сработавшего правила
                triggered_rule_type = forward_source
                # Формируем причину
                reason = f"Пересылка из {forward_source.value}"
                # Логируем срабатывание правила
                logger.info(
                    f"Spam detected: chat_id={chat_id}, "
                    f"rule_type={forward_source}, action={action}"
                )
                # Возвращаем результат (пересылки имеют приоритет)
                return AntiSpamDecision(
                    is_spam=is_spam,
                    delete_message=delete_message,
                    action=action,
                    restrict_minutes=restrict_minutes,
                    triggered_rule_type=triggered_rule_type,
                    reason=reason,
                )

    # ============================================================
    # ШАГ 2: ПРОВЕРКА ЦИТАТ
    # ============================================================

    # Определяем является ли сообщение цитатой
    quote_source = detect_quote_source(message)
    # Если это цитата
    if quote_source:
        # Получаем правило для этого типа цитаты
        rule = await get_rule_by_type(session, chat_id, quote_source)
        # Если правило существует и активно
        if rule and rule.action != ActionType.OFF:
            # Для цитат также проверяем белый список
            is_whitelisted = False
            source_chat = None
            source_user = None

            # Если есть пересылка в цитируемом сообщении
            if message.reply_to_message.forward_origin:
                # Получаем объект forward_origin
                fwd_origin = message.reply_to_message.forward_origin
                # Проверяем наличие chat (для каналов/групп)
                if hasattr(fwd_origin, 'chat') and fwd_origin.chat:
                    source_chat = fwd_origin.chat
                    # Проверяем по ID чата
                    check_string = str(source_chat.id)
                    is_whitelisted = await check_whitelist(
                        session,
                        chat_id,
                        WhitelistScope.QUOTE,
                        check_string
                    )
                    # Если не в whitelist по ID, проверяем по username
                    if not is_whitelisted and source_chat.username:
                        username_check = f"@{source_chat.username}"
                        is_whitelisted = await check_whitelist(
                            session,
                            chat_id,
                            WhitelistScope.QUOTE,
                            username_check
                        )
                        if is_whitelisted:
                            logger.info(f"Quote whitelist match by username: {username_check}")
                # Проверяем наличие sender_user (для пользователей/ботов)
                elif hasattr(fwd_origin, 'sender_user') and fwd_origin.sender_user:
                    source_user = fwd_origin.sender_user
                    check_string = str(source_user.id)
                    is_whitelisted = await check_whitelist(
                        session,
                        chat_id,
                        WhitelistScope.QUOTE,
                        check_string
                    )
                    # Если не в whitelist по ID, проверяем по username
                    if not is_whitelisted and source_user.username:
                        username_check = f"@{source_user.username}"
                        is_whitelisted = await check_whitelist(
                            session,
                            chat_id,
                            WhitelistScope.QUOTE,
                            username_check
                        )
                        if is_whitelisted:
                            logger.info(f"Quote whitelist match by username: {username_check}")
            # Иначе используем автора сообщения
            elif message.reply_to_message.from_user:
                source_user = message.reply_to_message.from_user
                check_string = str(source_user.id)
                is_whitelisted = await check_whitelist(
                    session,
                    chat_id,
                    WhitelistScope.QUOTE,
                    check_string
                )
                # Если не в whitelist по ID, проверяем по username
                if not is_whitelisted and source_user.username:
                    username_check = f"@{source_user.username}"
                    is_whitelisted = await check_whitelist(
                        session,
                        chat_id,
                        WhitelistScope.QUOTE,
                        username_check
                    )
                    if is_whitelisted:
                        logger.info(f"Quote whitelist match by username: {username_check}")

            # Если НЕ в белом списке - применяем правило
            if not is_whitelisted:
                # Это спам
                is_spam = True
                # Флаг удаления из правила
                delete_message = rule.delete_message
                # Действие из правила
                action = rule.action
                # Длительность из правила
                restrict_minutes = rule.restrict_minutes
                # Сохраняем тип сработавшего правила
                triggered_rule_type = quote_source
                # Формируем причину
                reason = f"Цитата из {quote_source.value}"
                # Логируем срабатывание правила
                logger.info(
                    f"Spam detected: chat_id={chat_id}, "
                    f"rule_type={quote_source}, action={action}"
                )
                # Возвращаем результат
                return AntiSpamDecision(
                    is_spam=is_spam,
                    delete_message=delete_message,
                    action=action,
                    restrict_minutes=restrict_minutes,
                    triggered_rule_type=triggered_rule_type,
                    reason=reason,
                )

    # ============================================================
    # ШАГ 3: ПРОВЕРКА ССЫЛОК
    # ============================================================

    # Получаем текст сообщения (включая caption для медиа)
    message_text = message.text or message.caption or ""
    # Извлекаем ссылки из текста (regex поиск)
    links_from_text = extract_links(message_text)
    # Извлекаем ссылки из entities (text_link и url)
    # Это ловит скрытые ссылки типа "нажми сюда" → https://spam.com
    links_from_entities = extract_links_from_entities(message)
    # Объединяем ссылки и убираем дубликаты
    # Используем dict.fromkeys для сохранения порядка
    links = list(dict.fromkeys(links_from_text + links_from_entities))

    # Если есть ссылки в сообщении
    if links:
        # Перебираем каждую ссылку
        for link in links:
            # Проверяем является ли ссылка Telegram ссылкой
            if is_telegram_link(link):
                # Получаем правило для Telegram ссылок
                rule = await get_rule_by_type(session, chat_id, RuleType.TELEGRAM_LINK)
                # Если правило существует и активно
                if rule and rule.action != ActionType.OFF:
                    # Проверяем белый список для Telegram ссылок
                    is_whitelisted = await check_whitelist(
                        session,
                        chat_id,
                        WhitelistScope.TELEGRAM_LINK,
                        link
                    )
                    # Если НЕ в белом списке - применяем правило
                    if not is_whitelisted:
                        # Это спам
                        is_spam = True
                        # Флаг удаления из правила
                        delete_message = rule.delete_message
                        # Действие из правила
                        action = rule.action
                        # Длительность из правила
                        restrict_minutes = rule.restrict_minutes
                        # Сохраняем тип сработавшего правила
                        triggered_rule_type = RuleType.TELEGRAM_LINK
                        # Формируем причину
                        reason = f"Telegram ссылка: {link}"
                        # Логируем срабатывание правила
                        logger.info(
                            f"Spam detected: chat_id={chat_id}, "
                            f"rule_type=TELEGRAM_LINK, action={action}, link={link}"
                        )
                        # Возвращаем результат (Telegram ссылки имеют приоритет над обычными)
                        return AntiSpamDecision(
                            is_spam=is_spam,
                            delete_message=delete_message,
                            action=action,
                            restrict_minutes=restrict_minutes,
                            triggered_rule_type=triggered_rule_type,
                            reason=reason,
                        )

        # Если дошли сюда - проверяем правило для любых ссылок
        # Получаем правило для любых ссылок
        any_link_rule = await get_rule_by_type(session, chat_id, RuleType.ANY_LINK)
        # Если правило существует и активно
        if any_link_rule and any_link_rule.action != ActionType.OFF:
            # Проверяем каждую ссылку по белому списку
            has_whitelisted = False
            # Перебираем ссылки
            for link in links:
                # Проверяем белый список для любых ссылок
                if await check_whitelist(session, chat_id, WhitelistScope.ANY_LINK, link):
                    # Найдена разрешенная ссылка
                    has_whitelisted = True
                    # Прерываем цикл
                    break
                # Также проверяем белый список TELEGRAM_LINK для telegram ссылок
                # Это нужно чтобы ссылки из TELEGRAM_LINK whitelist не ловились правилом ANY_LINK
                if is_telegram_link(link) and await check_whitelist(session, chat_id, WhitelistScope.TELEGRAM_LINK, link):
                    # Найдена разрешенная telegram ссылка
                    has_whitelisted = True
                    # Прерываем цикл
                    break

            # Если ни одна ссылка не в белом списке
            if not has_whitelisted:
                # Это спам
                is_spam = True
                # Флаг удаления из правила
                delete_message = any_link_rule.delete_message
                # Действие из правила
                action = any_link_rule.action
                # Длительность из правила
                restrict_minutes = any_link_rule.restrict_minutes
                # Сохраняем тип сработавшего правила
                triggered_rule_type = RuleType.ANY_LINK
                # Формируем причину с первой ссылкой
                reason = f"Запрещенная ссылка: {links[0]}"
                # Логируем срабатывание правила
                logger.info(
                    f"Spam detected: chat_id={chat_id}, "
                    f"rule_type=ANY_LINK, action={action}"
                )
                # Возвращаем результат
                return AntiSpamDecision(
                    is_spam=is_spam,
                    delete_message=delete_message,
                    action=action,
                    restrict_minutes=restrict_minutes,
                    triggered_rule_type=triggered_rule_type,
                    reason=reason,
                )

    # ============================================================
    # ЕСЛИ ДОШЛИ СЮДА - СООБЩЕНИЕ НЕ ЯВЛЯЕТСЯ СПАМОМ
    # ============================================================

    # Возвращаем решение: не спам
    return AntiSpamDecision(
        is_spam=False,
        delete_message=False,
        action=ActionType.OFF,
        restrict_minutes=None,
        triggered_rule_type=None,
        reason=None,
    )
