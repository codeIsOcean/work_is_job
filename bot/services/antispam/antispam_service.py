"""
Сервис антиспам - бизнес-логика проверки сообщений и управления правилами.

Этот модуль содержит всю логику для:
- Проверки сообщений на спам (ссылки, пересылки, цитаты)
- Управления правилами антиспам (CRUD операции)
- Управления белым списком исключений
- Применения настроенных действий к нарушителям
"""

# Импорт типов для аннотаций
from typing import Optional, List, Dict, Any
# Импорт dataclass для создания класса данных
from dataclasses import dataclass
# Импорт регулярных выражений для поиска ссылок
import re
# Импорт логгера для отладки
import logging

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

    Проверяет есть ли хотя бы один паттерн из белого списка в check_string.

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

    # Получаем все паттерны белого списка для данного scope
    whitelist_patterns = await list_whitelist_patterns(session, chat_id, scope)

    # Проходим по каждому паттерну из белого списка
    for entry in whitelist_patterns:
        # Проверяем содержится ли паттерн в проверяемой строке
        if entry.pattern in normalized_string:
            # Логируем срабатывание белого списка
            logger.info(
                f"Whitelist match: chat_id={chat_id}, scope={scope}, "
                f"pattern='{entry.pattern}' found in '{check_string}'"
            )
            # Возвращаем True - строка в белом списке
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
            check_string = str(message.forward_origin.chat.id) if hasattr(message.forward_origin, 'chat') and message.forward_origin.chat else ""
            # Проверяем белый список для пересылок
            is_whitelisted = await check_whitelist(
                session,
                chat_id,
                WhitelistScope.FORWARD,
                check_string
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
            # Формируем строку для проверки (ID автора или источника)
            check_string = ""
            # Если есть пересылка в цитируемом сообщении
            if message.reply_to_message.forward_origin:
                # Используем ID чата источника
                if hasattr(message.reply_to_message.forward_origin, 'chat'):
                    check_string = str(message.reply_to_message.forward_origin.chat.id)
            # Иначе используем ID автора
            elif message.reply_to_message.from_user:
                check_string = str(message.reply_to_message.from_user.id)

            # Проверяем белый список для цитат
            is_whitelisted = await check_whitelist(
                session,
                chat_id,
                WhitelistScope.QUOTE,
                check_string
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
    # Извлекаем все ссылки из текста
    links = extract_links(message_text)

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
