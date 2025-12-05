"""
Unit-тесты для антиспам сервиса.

Этот модуль тестирует все функции из bot.services.antispam:
- Извлечение и анализ ссылок (extract_links, is_telegram_link)
- Определение типов пересылок и цитат (detect_forward_source, detect_quote_source)
- CRUD операции с правилами (get_rules_for_chat, get_rule_by_type, upsert_rule)
- CRUD операции с белым списком (add_whitelist_pattern, remove_whitelist_pattern, etc.)
- Проверка сообщений на спам (check_message_for_spam)
"""

# Импорт pytest для тестирования
import pytest
# Импорт типов aiogram для создания mock-объектов
from aiogram import types
# Импорт datetime для работы с временем
from datetime import datetime, timezone
# Импорт unittest.mock для создания заглушек
from unittest.mock import MagicMock, AsyncMock

# Импорт модели Group для создания связанных записей
from bot.database.models import Group
# Импорт моделей антиспам
from bot.database.models_antispam import (
    AntiSpamRule,
    AntiSpamWhitelist,
    RuleType,
    ActionType,
    WhitelistScope,
)
# Импорт тестируемых функций
from bot.services.antispam import (
    extract_links,
    is_telegram_link,
    detect_forward_source,
    detect_quote_source,
    get_rules_for_chat,
    get_rule_by_type,
    upsert_rule,
    add_whitelist_pattern,
    remove_whitelist_pattern,
    list_whitelist_patterns,
    get_whitelist_by_id,
    check_whitelist,
    check_message_for_spam,
    AntiSpamDecision,
)


# ============================================================
# ТЕСТЫ ДЛЯ ФУНКЦИИ extract_links
# ============================================================

class TestExtractLinks:
    """Тесты для функции extract_links."""

    # Тест: извлечение одной HTTP ссылки
    def test_extract_single_http_link(self):
        # Создаем текст с одной HTTP ссылкой
        text = "Посмотри сюда http://example.com/page"
        # Вызываем функцию
        result = extract_links(text)
        # Проверяем что найдена одна ссылка
        assert len(result) == 1
        # Проверяем содержимое ссылки
        assert "http://example.com/page" in result

    # Тест: извлечение одной HTTPS ссылки
    def test_extract_single_https_link(self):
        # Создаем текст с одной HTTPS ссылкой
        text = "Безопасный сайт https://secure.example.com/test"
        # Вызываем функцию
        result = extract_links(text)
        # Проверяем что найдена одна ссылка
        assert len(result) == 1
        # Проверяем что это HTTPS ссылка
        assert "https://secure.example.com/test" in result

    # Тест: извлечение нескольких ссылок
    def test_extract_multiple_links(self):
        # Создаем текст с несколькими ссылками
        text = "Сайты: http://first.com и https://second.com/page"
        # Вызываем функцию
        result = extract_links(text)
        # Проверяем что найдены две ссылки
        assert len(result) == 2

    # Тест: текст без ссылок
    def test_extract_no_links(self):
        # Создаем текст без ссылок
        text = "Просто обычный текст без ссылок"
        # Вызываем функцию
        result = extract_links(text)
        # Проверяем что список пустой
        assert len(result) == 0

    # Тест: пустой текст
    def test_extract_empty_text(self):
        # Вызываем функцию с пустым текстом
        result = extract_links("")
        # Проверяем что список пустой
        assert len(result) == 0

    # Тест: None вместо текста
    def test_extract_none_text(self):
        # Вызываем функцию с None
        result = extract_links(None)
        # Проверяем что список пустой
        assert len(result) == 0

    # Тест: ссылка со сложным путем и параметрами
    def test_extract_complex_url(self):
        # Создаем текст со сложной ссылкой
        text = "Страница https://example.com/path/to/page?param=value&other=123"
        # Вызываем функцию
        result = extract_links(text)
        # Проверяем что найдена одна ссылка
        assert len(result) == 1
        # Проверяем что параметры включены
        assert "param=value" in result[0]


# ============================================================
# ТЕСТЫ ДЛЯ ФУНКЦИИ is_telegram_link
# ============================================================

class TestIsTelegramLink:
    """Тесты для функции is_telegram_link."""

    # Тест: ссылка t.me с HTTP
    def test_t_me_http_link(self):
        # Создаем Telegram ссылку с HTTP
        url = "http://t.me/channel_name"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это Telegram ссылка
        assert result is True

    # Тест: ссылка t.me с HTTPS
    def test_t_me_https_link(self):
        # Создаем Telegram ссылку с HTTPS
        url = "https://t.me/username"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это Telegram ссылка
        assert result is True

    # Тест: ссылка telegram.me
    def test_telegram_me_link(self):
        # Создаем ссылку telegram.me
        url = "https://telegram.me/group_name"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это Telegram ссылка
        assert result is True

    # Тест: ссылка tg://
    def test_tg_protocol_link(self):
        # Создаем ссылку с протоколом tg://
        url = "tg://resolve?domain=channel"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это Telegram ссылка
        assert result is True

    # Тест: обычная HTTP ссылка (не Telegram)
    def test_non_telegram_http_link(self):
        # Создаем обычную HTTP ссылку
        url = "http://example.com/path"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это НЕ Telegram ссылка
        assert result is False

    # Тест: обычная HTTPS ссылка (не Telegram)
    def test_non_telegram_https_link(self):
        # Создаем обычную HTTPS ссылку
        url = "https://google.com/search?q=test"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это НЕ Telegram ссылка
        assert result is False

    # Тест: ссылка без протокола t.me
    def test_t_me_without_protocol(self):
        # Создаем ссылку без протокола
        url = "t.me/channel"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это Telegram ссылка
        assert result is True

    # Тест: похожая на Telegram, но не Telegram ссылка
    def test_fake_telegram_link(self):
        # Создаем ссылку с похожим доменом
        url = "https://t-me.fake.com/scam"
        # Вызываем функцию
        result = is_telegram_link(url)
        # Проверяем что это НЕ Telegram ссылка
        assert result is False


# ============================================================
# ТЕСТЫ ДЛЯ ФУНКЦИИ detect_forward_source
# ============================================================

class TestDetectForwardSource:
    """Тесты для функции detect_forward_source."""

    # Тест: сообщение без пересылки
    def test_no_forward(self):
        # Создаем mock сообщения без forward_origin
        message = MagicMock(spec=types.Message)
        # Устанавливаем forward_origin в None
        message.forward_origin = None
        # Вызываем функцию
        result = detect_forward_source(message)
        # Проверяем что результат None
        assert result is None

    # Тест: пересылка из канала
    def test_forward_from_channel(self):
        # Создаем mock сообщения
        message = MagicMock(spec=types.Message)
        # Создаем mock forward_origin с чатом типа "channel"
        forward_origin = MagicMock()
        # Создаем mock чата
        forward_origin.chat = MagicMock()
        # Устанавливаем тип чата
        forward_origin.chat.type = "channel"
        # Устанавливаем forward_origin
        message.forward_origin = forward_origin
        # Вызываем функцию
        result = detect_forward_source(message)
        # Проверяем что определен тип FORWARD_CHANNEL
        assert result == RuleType.FORWARD_CHANNEL

    # Тест: пересылка из группы
    def test_forward_from_group(self):
        # Создаем mock сообщения
        message = MagicMock(spec=types.Message)
        # Создаем mock forward_origin с чатом типа "supergroup"
        forward_origin = MagicMock()
        # Создаем mock чата
        forward_origin.chat = MagicMock()
        # Устанавливаем тип чата
        forward_origin.chat.type = "supergroup"
        # Устанавливаем forward_origin
        message.forward_origin = forward_origin
        # Вызываем функцию
        result = detect_forward_source(message)
        # Проверяем что определен тип FORWARD_GROUP
        assert result == RuleType.FORWARD_GROUP

    # Тест: пересылка от пользователя
    def test_forward_from_user(self):
        # Создаем mock сообщения
        message = MagicMock(spec=types.Message)
        # Создаем mock forward_origin без чата
        forward_origin = MagicMock()
        # Удаляем атрибут chat
        del forward_origin.chat
        # Создаем mock пользователя
        forward_origin.sender_user = MagicMock()
        # Устанавливаем что это не бот
        forward_origin.sender_user.is_bot = False
        # Устанавливаем forward_origin
        message.forward_origin = forward_origin
        # Вызываем функцию
        result = detect_forward_source(message)
        # Проверяем что определен тип FORWARD_USER
        assert result == RuleType.FORWARD_USER

    # Тест: пересылка от бота
    def test_forward_from_bot(self):
        # Создаем mock сообщения
        message = MagicMock(spec=types.Message)
        # Создаем mock forward_origin без чата
        forward_origin = MagicMock()
        # Удаляем атрибут chat
        del forward_origin.chat
        # Создаем mock пользователя-бота
        forward_origin.sender_user = MagicMock()
        # Устанавливаем что это бот
        forward_origin.sender_user.is_bot = True
        # Устанавливаем forward_origin
        message.forward_origin = forward_origin
        # Вызываем функцию
        result = detect_forward_source(message)
        # Проверяем что определен тип FORWARD_BOT
        assert result == RuleType.FORWARD_BOT


# ============================================================
# ТЕСТЫ ДЛЯ CRUD ОПЕРАЦИЙ С ПРАВИЛАМИ (требуют db_session)
# ============================================================

@pytest.mark.asyncio
async def test_get_rules_for_chat_empty(db_session):
    """Тест получения правил для чата без правил."""
    # Создаем группу для теста
    group = Group(chat_id=-1001234567890, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Вызываем функцию получения правил
    rules = await get_rules_for_chat(db_session, -1001234567890)
    # Проверяем что список правил пустой
    assert len(rules) == 0


@pytest.mark.asyncio
async def test_upsert_rule_create_new(db_session):
    """Тест создания нового правила через upsert."""
    # ID чата для теста
    chat_id = -1001111111111
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем новое правило через upsert
    rule = await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.WARN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем что правило создано
    assert rule is not None
    # Проверяем chat_id
    assert rule.chat_id == chat_id
    # Проверяем тип правила
    assert rule.rule_type == RuleType.TELEGRAM_LINK
    # Проверяем действие
    assert rule.action == ActionType.WARN
    # Проверяем флаг удаления
    assert rule.delete_message is True


@pytest.mark.asyncio
async def test_upsert_rule_update_existing(db_session):
    """Тест обновления существующего правила через upsert."""
    # ID чата для теста
    chat_id = -1002222222222
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем первое правило
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.ANY_LINK,
        ActionType.KICK,
        delete_message=False,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Обновляем правило через upsert
    updated_rule = await upsert_rule(
        db_session,
        chat_id,
        RuleType.ANY_LINK,
        ActionType.BAN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем что действие обновлено
    assert updated_rule.action == ActionType.BAN
    # Проверяем что флаг удаления обновлен
    assert updated_rule.delete_message is True
    # Проверяем что есть только одно правило этого типа
    all_rules = await get_rules_for_chat(db_session, chat_id)
    # Фильтруем правила по типу
    any_link_rules = [r for r in all_rules if r.rule_type == RuleType.ANY_LINK]
    # Проверяем что правило одно
    assert len(any_link_rules) == 1


@pytest.mark.asyncio
async def test_get_rule_by_type_found(db_session):
    """Тест получения существующего правила по типу."""
    # ID чата для теста
    chat_id = -1003333333333
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.FORWARD_CHANNEL,
        ActionType.RESTRICT,
        delete_message=True,
        restrict_minutes=60,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Получаем правило по типу
    rule = await get_rule_by_type(db_session, chat_id, RuleType.FORWARD_CHANNEL)
    # Проверяем что правило найдено
    assert rule is not None
    # Проверяем тип
    assert rule.rule_type == RuleType.FORWARD_CHANNEL
    # Проверяем длительность ограничения
    assert rule.restrict_minutes == 60


@pytest.mark.asyncio
async def test_get_rule_by_type_not_found(db_session):
    """Тест получения несуществующего правила по типу."""
    # ID чата для теста
    chat_id = -1004444444444
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Пытаемся получить несуществующее правило
    rule = await get_rule_by_type(db_session, chat_id, RuleType.QUOTE_USER)
    # Проверяем что правило не найдено
    assert rule is None


# ============================================================
# ТЕСТЫ ДЛЯ CRUD ОПЕРАЦИЙ С БЕЛЫМ СПИСКОМ
# ============================================================

@pytest.mark.asyncio
async def test_add_whitelist_pattern(db_session):
    """Тест добавления паттерна в белый список."""
    # ID чата для теста
    chat_id = -1005555555555
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Добавляем паттерн в белый список
    entry = await add_whitelist_pattern(
        db_session,
        chat_id,
        WhitelistScope.TELEGRAM_LINK,
        "t.me/allowed_channel",
        added_by=123456789,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем что запись создана
    assert entry is not None
    # Проверяем ID
    assert entry.id is not None
    # Проверяем что паттерн нормализован (lowercase)
    assert entry.pattern == "t.me/allowed_channel"


@pytest.mark.asyncio
async def test_list_whitelist_patterns(db_session):
    """Тест получения списка паттернов белого списка."""
    # ID чата для теста
    chat_id = -1006666666666
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Добавляем несколько паттернов
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.ANY_LINK, "google.com", 111
    )
    # Добавляем второй паттерн
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.ANY_LINK, "youtube.com", 111
    )
    # Добавляем паттерн другого типа
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "t.me/official", 111
    )
    # Сохраняем изменения
    await db_session.commit()
    # Получаем все паттерны
    all_patterns = await list_whitelist_patterns(db_session, chat_id)
    # Проверяем что найдено 3 паттерна
    assert len(all_patterns) == 3
    # Получаем паттерны только для ANY_LINK
    any_link_patterns = await list_whitelist_patterns(
        db_session, chat_id, WhitelistScope.ANY_LINK
    )
    # Проверяем что найдено 2 паттерна
    assert len(any_link_patterns) == 2


@pytest.mark.asyncio
async def test_remove_whitelist_pattern_success(db_session):
    """Тест успешного удаления паттерна из белого списка."""
    # ID чата для теста
    chat_id = -1007777777777
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Добавляем паттерн
    entry = await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.FORWARD, "-1001234567890", 111
    )
    # Сохраняем изменения
    await db_session.commit()
    # Сохраняем ID записи
    entry_id = entry.id
    # Удаляем паттерн
    result = await remove_whitelist_pattern(db_session, chat_id, entry_id)
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем что удаление успешно
    assert result is True
    # Проверяем что запись удалена
    remaining = await list_whitelist_patterns(db_session, chat_id)
    # Проверяем что список пустой
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_remove_whitelist_pattern_not_found(db_session):
    """Тест удаления несуществующего паттерна."""
    # ID чата для теста
    chat_id = -1008888888888
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Пытаемся удалить несуществующий паттерн
    result = await remove_whitelist_pattern(db_session, chat_id, 99999)
    # Проверяем что удаление не удалось
    assert result is False


@pytest.mark.asyncio
async def test_check_whitelist_match(db_session):
    """Тест проверки белого списка - паттерн найден."""
    # ID чата для теста
    chat_id = -1009999999999
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Добавляем паттерн в белый список
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "t.me/official", 111
    )
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем ссылку на соответствие белому списку
    result = await check_whitelist(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "https://t.me/official/123"
    )
    # Проверяем что ссылка в белом списке
    assert result is True


@pytest.mark.asyncio
async def test_check_whitelist_no_match(db_session):
    """Тест проверки белого списка - паттерн не найден."""
    # ID чата для теста
    chat_id = -1010101010101
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Добавляем паттерн в белый список
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "t.me/official", 111
    )
    # Сохраняем изменения
    await db_session.commit()
    # Проверяем другую ссылку
    result = await check_whitelist(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "https://t.me/spam_channel"
    )
    # Проверяем что ссылка НЕ в белом списке
    assert result is False


# ============================================================
# ТЕСТЫ ДЛЯ ФУНКЦИИ check_message_for_spam
# ============================================================

@pytest.mark.asyncio
async def test_check_message_no_spam_no_rules(db_session):
    """Тест проверки сообщения без правил - не спам."""
    # ID чата для теста
    chat_id = -1011111111111
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с текстом и ссылкой
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Привет, смотри сайт https://t.me/spam_channel"
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None (не пересылка)
    message.forward_origin = None
    # Устанавливаем reply_to_message в None (не ответ)
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это не спам (нет правил)
    assert decision.is_spam is False
    # Проверяем действие
    assert decision.action == ActionType.OFF


@pytest.mark.asyncio
async def test_check_message_telegram_link_spam(db_session):
    """Тест проверки сообщения с Telegram ссылкой - спам."""
    # ID чата для теста
    chat_id = -1012121212121
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило для Telegram ссылок
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.WARN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с Telegram ссылкой
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Подписывайтесь https://t.me/spam_channel"
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None
    message.forward_origin = None
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.WARN
    # Проверяем флаг удаления
    assert decision.delete_message is True
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.TELEGRAM_LINK


@pytest.mark.asyncio
async def test_check_message_telegram_link_whitelisted(db_session):
    """Тест проверки сообщения с Telegram ссылкой из белого списка."""
    # ID чата для теста
    chat_id = -1013131313131
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило для Telegram ссылок
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.BAN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Добавляем ссылку в белый список
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK, "t.me/allowed", 111
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с разрешенной Telegram ссылкой
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Наш канал https://t.me/allowed/123"
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None
    message.forward_origin = None
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это НЕ спам (в белом списке)
    assert decision.is_spam is False


@pytest.mark.asyncio
async def test_check_message_any_link_spam(db_session):
    """Тест проверки сообщения с любой ссылкой - спам."""
    # ID чата для теста
    chat_id = -1014141414141
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило для любых ссылок
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.ANY_LINK,
        ActionType.KICK,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с обычной ссылкой
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Смотри сюда https://some-spam-site.com/page"
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None
    message.forward_origin = None
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.KICK
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.ANY_LINK


@pytest.mark.asyncio
async def test_check_message_forward_from_channel_spam(db_session):
    """Тест проверки пересылки из канала - спам."""
    # ID чата для теста
    chat_id = -1015151515151
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило для пересылок из канала
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.FORWARD_CHANNEL,
        ActionType.RESTRICT,
        delete_message=True,
        restrict_minutes=30,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с пересылкой из канала
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Пересланное сообщение из канала"
    # Устанавливаем caption в None
    message.caption = None
    # Создаем mock forward_origin с типом channel
    forward_origin = MagicMock()
    # Создаем mock чата источника
    forward_origin.chat = MagicMock()
    # Устанавливаем тип чата
    forward_origin.chat.type = "channel"
    # Устанавливаем ID чата источника
    forward_origin.chat.id = -1001234567890
    # Устанавливаем forward_origin
    message.forward_origin = forward_origin
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.RESTRICT
    # Проверяем длительность ограничения
    assert decision.restrict_minutes == 30
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.FORWARD_CHANNEL


@pytest.mark.asyncio
async def test_check_message_rule_off_no_spam(db_session):
    """Тест проверки с выключенным правилом - не спам."""
    # ID чата для теста
    chat_id = -1016161616161
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правило с действием OFF
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.OFF,
        delete_message=False,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения с Telegram ссылкой
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения
    message.text = "Ссылка https://t.me/some_channel"
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None
    message.forward_origin = None
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это НЕ спам (правило выключено)
    assert decision.is_spam is False


@pytest.mark.asyncio
async def test_check_message_plain_text_no_spam(db_session):
    """Тест проверки обычного текста без ссылок - не спам."""
    # ID чата для теста
    chat_id = -1017171717171
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()
    # Создаем правила для всех типов
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK, ActionType.BAN, True, None
    )
    # Создаем правило для любых ссылок
    await upsert_rule(
        db_session, chat_id, RuleType.ANY_LINK, ActionType.KICK, True, None
    )
    # Сохраняем изменения
    await db_session.commit()
    # Создаем mock сообщения без ссылок
    message = MagicMock(spec=types.Message)
    # Устанавливаем атрибуты сообщения
    message.chat = MagicMock()
    # Устанавливаем ID чата
    message.chat.id = chat_id
    # Устанавливаем текст сообщения без ссылок
    message.text = "Привет! Как дела? Это обычное сообщение без ссылок."
    # Устанавливаем caption в None
    message.caption = None
    # Устанавливаем forward_origin в None
    message.forward_origin = None
    # Устанавливаем reply_to_message в None
    message.reply_to_message = None
    # Проверяем сообщение
    decision = await check_message_for_spam(message, db_session)
    # Проверяем что это НЕ спам (нет ссылок и пересылок)
    assert decision.is_spam is False


# ============================================================
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ: ПОЛНЫЙ ЦИКЛ ВКЛЮЧЕНИЯ/ВЫКЛЮЧЕНИЯ
# ============================================================

@pytest.mark.asyncio
async def test_full_cycle_enable_disable_telegram_links(db_session):
    """
    Интеграционный тест: полный цикл включения и выключения блокировки Telegram ссылок.

    Этот тест проверяет реальный сценарий использования:
    1. Сначала правило выключено - ссылки не блокируются
    2. Включаем правило - ссылки начинают блокироваться
    3. Выключаем правило - ссылки снова не блокируются
    """
    # ID чата для теста
    chat_id = -1020202020202
    # Создаем группу для теста
    group = Group(chat_id=chat_id, title="Integration Test Group")
    db_session.add(group)
    await db_session.commit()

    # Создаем mock сообщения с Telegram ссылкой
    def create_message_with_tg_link():
        message = MagicMock(spec=types.Message)
        message.chat = MagicMock()
        message.chat.id = chat_id
        message.text = "Смотрите канал https://t.me/spam_channel"
        message.caption = None
        message.forward_origin = None
        message.reply_to_message = None
        return message

    # ШАГ 1: Без правил - сообщение НЕ должно быть спамом
    message1 = create_message_with_tg_link()
    decision1 = await check_message_for_spam(message1, db_session)
    assert decision1.is_spam is False, "Без правил сообщение не должно быть спамом"

    # ШАГ 2: Включаем правило WARN - сообщение ДОЛЖНО быть спамом
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK,
        ActionType.WARN, delete_message=True, restrict_minutes=None
    )
    await db_session.commit()

    message2 = create_message_with_tg_link()
    decision2 = await check_message_for_spam(message2, db_session)
    assert decision2.is_spam is True, "С правилом WARN сообщение должно быть спамом"
    assert decision2.action == ActionType.WARN
    assert decision2.delete_message is True

    # ШАГ 3: Меняем действие на BAN - сообщение все еще спам, но действие другое
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK,
        ActionType.BAN, delete_message=True, restrict_minutes=None
    )
    await db_session.commit()

    message3 = create_message_with_tg_link()
    decision3 = await check_message_for_spam(message3, db_session)
    assert decision3.is_spam is True, "С правилом BAN сообщение должно быть спамом"
    assert decision3.action == ActionType.BAN

    # ШАГ 4: Выключаем правило (OFF) - сообщение НЕ должно быть спамом
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK,
        ActionType.OFF, delete_message=False, restrict_minutes=None
    )
    await db_session.commit()

    message4 = create_message_with_tg_link()
    decision4 = await check_message_for_spam(message4, db_session)
    assert decision4.is_spam is False, "С правилом OFF сообщение не должно быть спамом"


@pytest.mark.asyncio
async def test_full_cycle_enable_disable_any_links(db_session):
    """
    Интеграционный тест: полный цикл блокировки ВСЕХ ссылок (не только Telegram).
    """
    chat_id = -1021212121212
    group = Group(chat_id=chat_id, title="Any Links Test Group")
    db_session.add(group)
    await db_session.commit()

    def create_message_with_regular_link():
        message = MagicMock(spec=types.Message)
        message.chat = MagicMock()
        message.chat.id = chat_id
        message.text = "Смотрите на этом сайте https://example.com/page"
        message.caption = None
        message.forward_origin = None
        message.reply_to_message = None
        return message

    # Без правил - не спам
    decision1 = await check_message_for_spam(create_message_with_regular_link(), db_session)
    assert decision1.is_spam is False

    # Включаем блокировку ВСЕХ ссылок
    await upsert_rule(
        db_session, chat_id, RuleType.ANY_LINK,
        ActionType.KICK, delete_message=True, restrict_minutes=None
    )
    await db_session.commit()

    # Теперь любая ссылка - спам
    decision2 = await check_message_for_spam(create_message_with_regular_link(), db_session)
    assert decision2.is_spam is True
    assert decision2.action == ActionType.KICK

    # Выключаем
    await upsert_rule(
        db_session, chat_id, RuleType.ANY_LINK,
        ActionType.OFF, delete_message=False, restrict_minutes=None
    )
    await db_session.commit()

    # Снова не спам
    decision3 = await check_message_for_spam(create_message_with_regular_link(), db_session)
    assert decision3.is_spam is False


@pytest.mark.asyncio
async def test_whitelist_actually_prevents_blocking(db_session):
    """
    Интеграционный тест: белый список реально предотвращает блокировку.

    Этот тест проверяет:
    1. Включаем строгую блокировку (BAN) для Telegram ссылок
    2. Добавляем паттерн в белый список
    3. Ссылка из белого списка НЕ блокируется
    4. Ссылка НЕ из белого списка блокируется
    """
    chat_id = -1022222222222
    group = Group(chat_id=chat_id, title="Whitelist Test Group")
    db_session.add(group)
    await db_session.commit()

    # Включаем блокировку Telegram ссылок (BAN)
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK,
        ActionType.BAN, delete_message=True, restrict_minutes=None
    )
    await db_session.commit()

    # Добавляем разрешенный канал в белый список
    await add_whitelist_pattern(
        db_session, chat_id, WhitelistScope.TELEGRAM_LINK,
        "t.me/allowed_channel", added_by=123
    )
    await db_session.commit()

    # Сообщение с РАЗРЕШЕННОЙ ссылкой - НЕ должно блокироваться
    allowed_message = MagicMock(spec=types.Message)
    allowed_message.chat = MagicMock()
    allowed_message.chat.id = chat_id
    allowed_message.text = "Наш официальный канал https://t.me/allowed_channel/123"
    allowed_message.caption = None
    allowed_message.forward_origin = None
    allowed_message.reply_to_message = None

    decision_allowed = await check_message_for_spam(allowed_message, db_session)
    assert decision_allowed.is_spam is False, "Ссылка из белого списка не должна блокироваться"

    # Сообщение с ЗАПРЕЩЕННОЙ ссылкой - ДОЛЖНО блокироваться
    blocked_message = MagicMock(spec=types.Message)
    blocked_message.chat = MagicMock()
    blocked_message.chat.id = chat_id
    blocked_message.text = "Смотрите спам канал https://t.me/spam_channel"
    blocked_message.caption = None
    blocked_message.forward_origin = None
    blocked_message.reply_to_message = None

    decision_blocked = await check_message_for_spam(blocked_message, db_session)
    assert decision_blocked.is_spam is True, "Ссылка не из белого списка должна блокироваться"
    assert decision_blocked.action == ActionType.BAN


@pytest.mark.asyncio
async def test_restrict_action_with_duration(db_session):
    """
    Интеграционный тест: действие RESTRICT с указанной длительностью.
    """
    chat_id = -1023232323232
    group = Group(chat_id=chat_id, title="Restrict Test Group")
    db_session.add(group)
    await db_session.commit()

    # Включаем RESTRICT на 60 минут для пересылок из каналов
    await upsert_rule(
        db_session, chat_id, RuleType.FORWARD_CHANNEL,
        ActionType.RESTRICT, delete_message=True, restrict_minutes=60
    )
    await db_session.commit()

    # Создаем сообщение с пересылкой из канала
    message = MagicMock(spec=types.Message)
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.text = "Пересланное сообщение"
    message.caption = None
    forward_origin = MagicMock()
    forward_origin.chat = MagicMock()
    forward_origin.chat.type = "channel"
    forward_origin.chat.id = -1001234567890
    message.forward_origin = forward_origin
    message.reply_to_message = None

    decision = await check_message_for_spam(message, db_session)

    assert decision.is_spam is True
    assert decision.action == ActionType.RESTRICT
    assert decision.restrict_minutes == 60
    assert decision.delete_message is True


# ============================================================
# ТЕСТЫ CALLBACK_DATA: ПРОВЕРКА ЛИМИТА 64 БАЙТА
# ============================================================

class TestCallbackDataLimit:
    """Тесты для проверки что callback_data укладывается в лимит 64 байта Telegram."""

    def test_main_menu_callback_within_limit(self):
        """Проверка что callback главного меню укладывается в 64 байта."""
        # Максимально длинный chat_id (14 цифр)
        chat_id = -10023026384650
        callback = f"as:m:{chat_id}"
        # Проверяем длину в байтах
        assert len(callback.encode('utf-8')) <= 64, f"Callback '{callback}' превышает 64 байта"

    def test_action_callback_within_limit(self):
        """Проверка что callback установки действия укладывается в 64 байта."""
        chat_id = -10023026384650
        short_code = "tl"
        action = "RESTRICT"
        callback = f"as:a:{short_code}:{action}:{chat_id}"
        assert len(callback.encode('utf-8')) <= 64, f"Callback '{callback}' превышает 64 байта"

    def test_duration_callback_within_limit(self):
        """Проверка что callback установки длительности укладывается в 64 байта."""
        chat_id = -10023026384650
        short_code = "fc"
        minutes = 10080  # максимум - 1 неделя
        callback = f"as:sd:{short_code}:{minutes}:{chat_id}"
        assert len(callback.encode('utf-8')) <= 64, f"Callback '{callback}' превышает 64 байта"

    def test_whitelist_delete_callback_within_limit(self):
        """Проверка что callback удаления из белого списка укладывается в 64 байта."""
        chat_id = -10023026384650
        short_code = "al"
        entry_id = 999999  # большой ID записи
        callback = f"as:wd:{short_code}:{entry_id}:{chat_id}"
        assert len(callback.encode('utf-8')) <= 64, f"Callback '{callback}' превышает 64 байта"

    def test_all_short_codes_callbacks_within_limit(self):
        """Проверка всех коротких кодов правил."""
        from bot.keyboards.antispam_keyboards import RULE_TYPE_TO_SHORT

        chat_id = -10023026384650

        for rule_type, short_code in RULE_TYPE_TO_SHORT.items():
            # Проверяем самый длинный callback для каждого типа
            callback = f"as:wdc:{short_code}:999999:{chat_id}"
            byte_length = len(callback.encode('utf-8'))
            assert byte_length <= 64, (
                f"Callback для {rule_type} '{callback}' = {byte_length} байт, "
                f"превышает лимит 64 байта"
            )

    def test_ttl_callback_within_limit(self):
        """Проверка что callback TTL укладывается в 64 байта."""
        chat_id = -10023026384650
        ttl_seconds = 2592000  # 1 месяц - максимальное значение
        callback = f"as:sttl:{ttl_seconds}:{chat_id}"
        byte_length = len(callback.encode('utf-8'))
        assert byte_length <= 64, f"Callback TTL '{callback}' = {byte_length} байт"

    def test_custom_duration_callback_within_limit(self):
        """Проверка что callback для ввода длительности укладывается в 64 байта."""
        chat_id = -10023026384650
        short_code = "tl"
        callback = f"as:sdc:{short_code}:{chat_id}"
        byte_length = len(callback.encode('utf-8'))
        assert byte_length <= 64, f"Callback '{callback}' = {byte_length} байт"

    def test_whitelist_delete_by_number_callback_within_limit(self):
        """Проверка что callback удаления по номеру укладывается в 64 байта."""
        chat_id = -10023026384650
        short_code = "al"
        callback = f"as:wdn:{short_code}:{chat_id}"
        byte_length = len(callback.encode('utf-8'))
        assert byte_length <= 64, f"Callback '{callback}' = {byte_length} байт"


# ============================================================
# ТЕСТЫ КЛАВИАТУР С НОВОЙ ФУНКЦИОНАЛЬНОСТЬЮ
# ============================================================

class TestAntispamKeyboardsNewFeatures:
    """Тесты для новых функций клавиатур."""

    def test_main_menu_with_ttl_display(self):
        """Проверка что главное меню корректно отображает TTL."""
        from bot.keyboards.antispam_keyboards import create_antispam_main_menu

        chat_id = -100123456789

        # TTL = 0 (не удалять)
        keyboard = create_antispam_main_menu(chat_id, 0)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("Не удалять" in text for text in buttons_text)

        # TTL = 30 сек
        keyboard = create_antispam_main_menu(chat_id, 30)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("30 сек" in text for text in buttons_text)

        # TTL = 300 сек (5 мин)
        keyboard = create_antispam_main_menu(chat_id, 300)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("5 мин" in text for text in buttons_text)

        # TTL = 3600 сек (1 час)
        keyboard = create_antispam_main_menu(chat_id, 3600)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("1 ч" in text for text in buttons_text)

        # TTL = 86400 сек (1 день)
        keyboard = create_antispam_main_menu(chat_id, 86400)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("1 дн" in text for text in buttons_text)

    def test_warning_ttl_keyboard(self):
        """Проверка клавиатуры выбора TTL."""
        from bot.keyboards.antispam_keyboards import create_warning_ttl_keyboard

        chat_id = -100123456789
        current_ttl = 300  # 5 минут

        keyboard = create_warning_ttl_keyboard(chat_id, current_ttl)

        # Должны быть все варианты TTL
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("Не удалять" in text for text in buttons_text)
        assert any("30 секунд" in text for text in buttons_text)
        assert any("1 минута" in text for text in buttons_text)
        assert any("5 минут" in text for text in buttons_text)
        assert any("1 час" in text for text in buttons_text)
        assert any("1 день" in text for text in buttons_text)
        assert any("1 месяц" in text for text in buttons_text)

        # Текущий выбор должен быть помечен галочкой
        assert any("✅ 5 минут" in text for text in buttons_text)

    def test_whitelist_menu_with_entries_count(self):
        """Проверка меню белого списка с количеством записей."""
        from bot.keyboards.antispam_keyboards import create_whitelist_menu

        chat_id = -100123456789
        short_code = "tl"

        # С записями - должна быть кнопка удаления по номеру
        keyboard = create_whitelist_menu(chat_id, short_code, entries_count=5)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("Удалить по номеру" in text for text in buttons_text)
        assert any("Добавить" in text for text in buttons_text)

        # Без записей - не должно быть кнопки удаления
        keyboard = create_whitelist_menu(chat_id, short_code, entries_count=0)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert not any("Удалить по номеру" in text for text in buttons_text)
        assert any("Добавить" in text for text in buttons_text)

    def test_duration_keyboard_has_custom_input(self):
        """Проверка что клавиатура длительности имеет кнопку ввода вручную."""
        from bot.keyboards.antispam_keyboards import create_duration_keyboard

        chat_id = -100123456789
        short_code = "tl"

        keyboard = create_duration_keyboard(chat_id, short_code, 30)
        buttons_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("Ввести вручную" in text for text in buttons_text)


# ============================================================
# ТЕСТЫ ФИЛЬТРА С АВТО-УДАЛЕНИЕМ
# ============================================================

class TestAntispamFilterAutoDelete:
    """Тесты для функций авто-удаления в фильтре."""

    def test_schedule_message_deletion_function_exists(self):
        """Проверка что функция schedule_message_deletion существует."""
        from bot.handlers.antispam_handlers.antispam_filter_handler import (
            schedule_message_deletion
        )
        assert callable(schedule_message_deletion)

    def test_get_warning_ttl_function_exists(self):
        """Проверка что функция get_warning_ttl существует."""
        from bot.handlers.antispam_handlers.antispam_filter_handler import (
            get_warning_ttl
        )
        assert callable(get_warning_ttl)


# ============================================================
# ТЕСТЫ МОДЕЛЕЙ
# ============================================================

class TestChatSettingsModel:
    """Тесты для модели ChatSettings."""

    def test_antispam_warning_ttl_field_exists(self):
        """Проверка что поле antispam_warning_ttl_seconds существует."""
        from bot.database.models import ChatSettings
        assert hasattr(ChatSettings, 'antispam_warning_ttl_seconds')


# ============================================================
# ТЕСТЫ ЖУРНАЛЬНОГО ЛОГИРОВАНИЯ АНТИСПАМА
# ============================================================

class TestAntispamJournalLogging:
    """Тесты для проверки импортов и наличия функций журнального логирования."""

    def test_send_journal_event_import_in_filter(self):
        """Проверка что send_journal_event импортирован в фильтре."""
        from bot.handlers.antispam_handlers import antispam_filter_handler
        # Проверяем что импорт присутствует через globals модуля
        assert 'send_journal_event' in dir(antispam_filter_handler)

    def test_group_journal_service_exists(self):
        """Проверка что сервис журнала группы существует."""
        from bot.services.group_journal_service import send_journal_event
        assert callable(send_journal_event)

    def test_filter_handler_uses_journal_service(self):
        """Проверка что фильтр импортирует сервис журнала."""
        import inspect
        from bot.handlers.antispam_handlers import antispam_filter_handler

        # Читаем исходный код модуля
        source = inspect.getsource(antispam_filter_handler)

        # Проверяем наличие импорта
        assert "from bot.services.group_journal_service import send_journal_event" in source

        # Проверяем использование для WARN
        assert "Антиспам: Предупреждение" in source

        # Проверяем использование для KICK
        assert "Антиспам: Исключение" in source

        # Проверяем использование для RESTRICT
        assert "Антиспам: Ограничение" in source

        # Проверяем использование для BAN
        assert "Антиспам: Бан" in source


# ============================================================
# ТЕСТЫ ИМПОРТОВ И ИНИЦИАЛИЗАЦИИ МОДУЛЕЙ
# ============================================================

class TestAntispamModuleImports:
    """Тесты для проверки что все модули антиспам корректно импортируются."""

    def test_antispam_settings_handler_imports(self):
        """Проверка что antispam_settings_handler корректно импортируется."""
        # Этот тест проверяет что все импорты в модуле корректны
        from bot.handlers.antispam_handlers import antispam_settings_handler

        # Проверяем наличие ключевых объектов
        assert hasattr(antispam_settings_handler, 'antispam_router')
        assert hasattr(antispam_settings_handler, 'antispam_main_menu_handler')
        assert hasattr(antispam_settings_handler, 'select')  # SQLAlchemy select

    def test_antispam_filter_handler_imports(self):
        """Проверка что antispam_filter_handler корректно импортируется."""
        from bot.handlers.antispam_handlers import antispam_filter_handler

        # Проверяем наличие ключевых объектов
        assert hasattr(antispam_filter_handler, 'antispam_filter_router')
        assert hasattr(antispam_filter_handler, 'filter_message_for_spam')
        assert hasattr(antispam_filter_handler, 'schedule_message_deletion')
        assert hasattr(antispam_filter_handler, 'get_warning_ttl')

    def test_antispam_keyboards_imports(self):
        """Проверка что antispam_keyboards корректно импортируется."""
        from bot.keyboards import antispam_keyboards

        # Проверяем наличие ключевых функций
        assert hasattr(antispam_keyboards, 'create_antispam_main_menu')
        assert hasattr(antispam_keyboards, 'create_action_settings_keyboard')
        assert hasattr(antispam_keyboards, 'create_duration_keyboard')
        assert hasattr(antispam_keyboards, 'create_warning_ttl_keyboard')
        assert hasattr(antispam_keyboards, 'create_whitelist_menu')

    def test_antispam_service_imports(self):
        """Проверка что antispam сервис корректно импортируется."""
        from bot.services import antispam

        # Проверяем наличие ключевых функций
        assert hasattr(antispam, 'check_message_for_spam')
        assert hasattr(antispam, 'get_rule_by_type')
        assert hasattr(antispam, 'upsert_rule')
        assert hasattr(antispam, 'list_whitelist_patterns')

    def test_antispam_models_imports(self):
        """Проверка что модели антиспам корректно импортируются."""
        from bot.database import models_antispam

        # Проверяем наличие моделей
        assert hasattr(models_antispam, 'AntiSpamRule')
        assert hasattr(models_antispam, 'AntiSpamWhitelist')
        assert hasattr(models_antispam, 'RuleType')
        assert hasattr(models_antispam, 'ActionType')
        assert hasattr(models_antispam, 'WhitelistScope')

    def test_chat_settings_has_ttl_field(self):
        """Проверка что ChatSettings имеет поле antispam_warning_ttl_seconds."""
        from bot.database.models import ChatSettings
        assert hasattr(ChatSettings, 'antispam_warning_ttl_seconds')

    def test_settings_handler_has_select_import(self):
        """Проверка что в settings_handler импортирован select из SQLAlchemy."""
        import inspect
        from bot.handlers.antispam_handlers import antispam_settings_handler

        source = inspect.getsource(antispam_settings_handler)
        assert "from sqlalchemy import select" in source
