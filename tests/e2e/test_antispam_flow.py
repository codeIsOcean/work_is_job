"""
E2E-тесты для антиспам модуля.

Этот модуль тестирует полный поток работы антиспам системы:
- Фильтрация сообщений с Telegram ссылками
- Фильтрация пересылок из разных источников
- Работа белого списка
- Применение различных действий (WARN, KICK, RESTRICT, BAN)
"""

# Импорт стандартных библиотек
from __future__ import annotations
# Импорт datetime для работы со временем
from datetime import datetime, timezone
# Импорт types для создания SimpleNamespace
from types import SimpleNamespace
# Импорт unittest.mock для создания заглушек
from unittest.mock import AsyncMock, MagicMock

# Импорт pytest для тестирования
import pytest
# Импорт aiogram компонентов
from aiogram import Bot, Dispatcher, Router
# Импорт базовой сессии aiogram
from aiogram.client.session.base import BaseSession
# Импорт TelegramAPIServer для создания тестового бота
from aiogram.client.telegram import TelegramAPIServer
# Импорт типа Update
from aiogram.types import Update, Message
# Импорт FSM storage
from aiogram.fsm.storage.memory import MemoryStorage

# Импорт моделей БД
from bot.database.models import ChatSettings, Group
# Импорт моделей антиспам
from bot.database.models_antispam import (
    AntiSpamRule,
    AntiSpamWhitelist,
    RuleType,
    ActionType,
    WhitelistScope,
)
# Импорт middleware для сессий БД
from bot.middleware.db_session import DbSessionMiddleware
# Импорт модуля сессий БД
from bot.database import session as db_session_module
# Импорт сервисов антиспам
from bot.services.antispam import (
    check_message_for_spam,
    upsert_rule,
    add_whitelist_pattern,
    AntiSpamDecision,
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЙ КЛАСС ДЛЯ ЗАПИСИ ЗАПРОСОВ К API TELEGRAM
# ============================================================

class RecordingSession(BaseSession):
    """
    Сессия для записи запросов к Telegram API.

    Используется в E2E тестах для отслеживания
    каких методов вызывался бот.
    """

    # Конструктор класса
    def __init__(self) -> None:
        # Вызываем конструктор родительского класса
        super().__init__(api=TelegramAPIServer.from_base("https://api.test"))
        # Список для хранения запросов
        self.requests = []

    # Метод для выполнения запроса к API
    async def make_request(self, bot: Bot, method, timeout=None):
        # Получаем название метода API
        method_name = getattr(method, "__api_method__", "")
        # Сохраняем запрос
        self.requests.append(method_name)
        # Возвращаем успешный результат для sendMessage
        if method_name == "sendMessage":
            return {"ok": True}
        # Для остальных методов возвращаем True
        return True

    # Метод для закрытия сессии
    async def close(self) -> None:
        # Ничего не делаем
        pass

    # Метод для потоковой передачи ответа
    async def stream_response(self, *args, **kwargs):
        # Возвращаем None
        return None

    # Метод для потоковой передачи контента
    async def stream_content(self, *args, **kwargs):
        # Возвращаем None
        return None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СОЗДАНИЯ ТЕСТОВЫХ ДАННЫХ
# ============================================================

def build_message_update_payload(
    # ID чата
    chat_id: int,
    # ID пользователя отправителя
    user_id: int,
    # Текст сообщения
    text: str,
    # ID сообщения (по умолчанию 1)
    message_id: int = 1,
) -> dict:
    """
    Создать payload обычного текстового сообщения.

    Args:
        chat_id: ID чата
        user_id: ID пользователя отправителя
        text: Текст сообщения
        message_id: ID сообщения

    Returns:
        Словарь с данными Update
    """
    # Получаем текущую временную метку
    timestamp = int(datetime.now(timezone.utc).timestamp())
    # Формируем и возвращаем payload
    return {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "date": timestamp,
            "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "TestUser",
                "username": "testuser",
            },
            "text": text,
        },
    }


def build_forward_update_payload(
    # ID чата назначения
    chat_id: int,
    # ID пользователя отправителя
    user_id: int,
    # Текст пересланного сообщения
    text: str,
    # Тип источника пересылки ("channel", "supergroup", "user", "bot")
    source_type: str,
    # ID источника пересылки
    source_id: int,
) -> dict:
    """
    Создать payload пересланного сообщения.

    Args:
        chat_id: ID чата назначения
        user_id: ID пользователя который переслал
        text: Текст пересланного сообщения
        source_type: Тип источника пересылки
        source_id: ID источника пересылки

    Returns:
        Словарь с данными Update
    """
    # Получаем текущую временную метку
    timestamp = int(datetime.now(timezone.utc).timestamp())

    # Формируем forward_origin в зависимости от типа источника
    forward_origin = {}
    # Если источник - канал или группа
    if source_type in ("channel", "supergroup", "group"):
        # Формируем forward_origin для чата
        forward_origin = {
            "type": "chat",
            "date": timestamp,
            "chat": {
                "id": source_id,
                "type": source_type,
                "title": f"Source {source_type}",
            },
        }
    # Если источник - пользователь или бот
    else:
        # Формируем forward_origin для пользователя
        forward_origin = {
            "type": "user",
            "date": timestamp,
            "sender_user": {
                "id": source_id,
                "is_bot": source_type == "bot",
                "first_name": "SourceUser",
            },
        }

    # Формируем и возвращаем payload
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": timestamp,
            "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "TestUser",
                "username": "testuser",
            },
            "text": text,
            "forward_origin": forward_origin,
        },
    }


# ============================================================
# E2E ТЕСТЫ ДЛЯ АНТИСПАМ МОДУЛЯ
# ============================================================

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_telegram_link_detected_and_blocked(db_session):
    """
    E2E тест: Telegram ссылка обнаружена и заблокирована.

    Сценарий:
    1. Создаем группу с правилом блокировки Telegram ссылок (WARN + удаление)
    2. Отправляем сообщение с Telegram ссылкой
    3. Проверяем что сообщение определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567001
    # ID пользователя
    user_id = 111111111

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Test Group")
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
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с Telegram ссылкой
    message_mock.text = "Подписывайтесь на канал https://t.me/spam_channel_123"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None (не пересылка)
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None (не ответ)
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.WARN
    # Проверяем что сообщение нужно удалить
    assert decision.delete_message is True
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.TELEGRAM_LINK
    # Проверяем что причина содержит информацию о ссылке
    assert "t.me" in decision.reason.lower()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_telegram_link_whitelisted_allowed(db_session):
    """
    E2E тест: Telegram ссылка из белого списка разрешена.

    Сценарий:
    1. Создаем группу с правилом блокировки Telegram ссылок
    2. Добавляем ссылку в белый список
    3. Отправляем сообщение с этой ссылкой
    4. Проверяем что сообщение НЕ определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567002
    # ID пользователя
    user_id = 222222222

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Whitelist Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для Telegram ссылок (строгое - BAN)
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.BAN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Добавляем разрешенную ссылку в белый список
    await add_whitelist_pattern(
        db_session,
        chat_id,
        WhitelistScope.TELEGRAM_LINK,
        "t.me/official_channel",
        added_by=user_id,
    )
    # Сохраняем изменения
    await db_session.commit()

    # Создаем mock сообщения с разрешенной Telegram ссылкой
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с разрешенной ссылкой
    message_mock.text = "Наш канал: https://t.me/official_channel/news"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение НЕ определено как спам (в белом списке)
    assert decision.is_spam is False
    # Проверяем что действие OFF
    assert decision.action == ActionType.OFF


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_forward_from_channel_blocked(db_session):
    """
    E2E тест: Пересылка из канала заблокирована.

    Сценарий:
    1. Создаем группу с правилом блокировки пересылок из каналов
    2. Отправляем пересланное сообщение из канала
    3. Проверяем что сообщение определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567003
    # ID пользователя
    user_id = 333333333
    # ID канала-источника
    source_channel_id = -1001999999999

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Forward Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для пересылок из каналов (RESTRICT на 30 минут)
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
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст
    message_mock.text = "Пересланное сообщение из спам-канала"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Создаем mock forward_origin для канала
    forward_origin = MagicMock()
    # Создаем mock чата источника
    forward_origin.chat = MagicMock()
    # Устанавливаем тип чата
    forward_origin.chat.type = "channel"
    # Устанавливаем ID чата источника
    forward_origin.chat.id = source_channel_id
    # Устанавливаем forward_origin
    message_mock.forward_origin = forward_origin
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.RESTRICT
    # Проверяем что сообщение нужно удалить
    assert decision.delete_message is True
    # Проверяем длительность ограничения
    assert decision.restrict_minutes == 30
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.FORWARD_CHANNEL


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_any_link_blocked(db_session):
    """
    E2E тест: Любая ссылка заблокирована.

    Сценарий:
    1. Создаем группу с правилом блокировки всех ссылок
    2. Отправляем сообщение с обычной HTTP ссылкой
    3. Проверяем что сообщение определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567004
    # ID пользователя
    user_id = 444444444

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Any Link Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для любых ссылок (KICK)
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
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с обычной ссылкой
    message_mock.text = "Смотрите здесь: https://spam-site.com/malware"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.KICK
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.ANY_LINK


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_multiple_rules_telegram_priority(db_session):
    """
    E2E тест: При наличии нескольких правил Telegram ссылки имеют приоритет.

    Сценарий:
    1. Создаем группу с правилами для Telegram ссылок и любых ссылок
    2. Отправляем сообщение с Telegram ссылкой
    3. Проверяем что сработало правило для Telegram ссылок (не ANY_LINK)
    """
    # ID чата для теста
    chat_id = -1001234567005
    # ID пользователя
    user_id = 555555555

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Priority Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для любых ссылок (KICK - менее строгое)
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.ANY_LINK,
        ActionType.KICK,
        delete_message=False,
        restrict_minutes=None,
    )
    # Создаем правило для Telegram ссылок (BAN - более строгое)
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.BAN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()

    # Создаем mock сообщения с Telegram ссылкой
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с Telegram ссылкой
    message_mock.text = "Переходи на https://t.me/spam_channel"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем что сработало правило для Telegram ссылок (BAN, не KICK)
    assert decision.action == ActionType.BAN
    # Проверяем что тип правила - TELEGRAM_LINK (не ANY_LINK)
    assert decision.triggered_rule_type == RuleType.TELEGRAM_LINK
    # Проверяем что delete_message из правила TELEGRAM_LINK
    assert decision.delete_message is True


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_rule_off_allows_message(db_session):
    """
    E2E тест: Выключенное правило пропускает сообщение.

    Сценарий:
    1. Создаем группу с выключенным правилом для Telegram ссылок
    2. Отправляем сообщение с Telegram ссылкой
    3. Проверяем что сообщение НЕ определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567006
    # ID пользователя
    user_id = 666666666

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Rule Off Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для Telegram ссылок с действием OFF
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
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с Telegram ссылкой
    message_mock.text = "Наш канал https://t.me/some_channel"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение НЕ определено как спам (правило OFF)
    assert decision.is_spam is False
    # Проверяем что действие OFF
    assert decision.action == ActionType.OFF


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_clean_text_allowed(db_session):
    """
    E2E тест: Чистый текст без ссылок проходит проверку.

    Сценарий:
    1. Создаем группу со всеми активными правилами
    2. Отправляем обычное текстовое сообщение без ссылок
    3. Проверяем что сообщение НЕ определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567007
    # ID пользователя
    user_id = 777777777

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Clean Text Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем все активные правила
    await upsert_rule(
        db_session, chat_id, RuleType.TELEGRAM_LINK, ActionType.BAN, True, None
    )
    # Правило для любых ссылок
    await upsert_rule(
        db_session, chat_id, RuleType.ANY_LINK, ActionType.BAN, True, None
    )
    # Правило для пересылок из каналов
    await upsert_rule(
        db_session, chat_id, RuleType.FORWARD_CHANNEL, ActionType.BAN, True, None
    )
    # Сохраняем изменения
    await db_session.commit()

    # Создаем mock сообщения без ссылок
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем обычный текст без ссылок
    message_mock.text = "Привет! Как дела? Отличная погода сегодня!"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None (не пересылка)
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None (не ответ)
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение НЕ определено как спам
    assert decision.is_spam is False
    # Проверяем что действие OFF
    assert decision.action == ActionType.OFF
    # Проверяем что нет сработавшего правила
    assert decision.triggered_rule_type is None


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_forward_from_bot_blocked(db_session):
    """
    E2E тест: Пересылка от бота заблокирована.

    Сценарий:
    1. Создаем группу с правилом блокировки пересылок от ботов
    2. Отправляем пересланное сообщение от бота
    3. Проверяем что сообщение определено как спам
    """
    # ID чата для теста
    chat_id = -1001234567008
    # ID пользователя
    user_id = 888888888
    # ID бота-источника
    source_bot_id = 123456789

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Forward Bot Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило для пересылок от ботов
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.FORWARD_BOT,
        ActionType.WARN,
        delete_message=True,
        restrict_minutes=None,
    )
    # Сохраняем изменения
    await db_session.commit()

    # Создаем mock сообщения с пересылкой от бота
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст
    message_mock.text = "Сообщение от бота"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Создаем mock forward_origin для бота
    forward_origin = MagicMock()
    # Удаляем атрибут chat (это пересылка от пользователя/бота)
    del forward_origin.chat
    # Создаем mock sender_user
    forward_origin.sender_user = MagicMock()
    # Устанавливаем is_bot в True
    forward_origin.sender_user.is_bot = True
    # Устанавливаем ID бота
    forward_origin.sender_user.id = source_bot_id
    # Устанавливаем forward_origin
    message_mock.forward_origin = forward_origin
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.WARN
    # Проверяем тип сработавшего правила
    assert decision.triggered_rule_type == RuleType.FORWARD_BOT


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_restrict_with_duration(db_session):
    """
    E2E тест: RESTRICT с указанной длительностью.

    Сценарий:
    1. Создаем группу с правилом RESTRICT на 60 минут
    2. Отправляем запрещенное сообщение
    3. Проверяем что действие RESTRICT и длительность 60 минут
    """
    # ID чата для теста
    chat_id = -1001234567009
    # ID пользователя
    user_id = 999999999

    # Создаем группу в БД
    group = Group(chat_id=chat_id, title="E2E Restrict Duration Test Group")
    # Добавляем группу в сессию
    db_session.add(group)
    # Сохраняем изменения
    await db_session.commit()

    # Создаем правило с RESTRICT на 60 минут
    await upsert_rule(
        db_session,
        chat_id,
        RuleType.TELEGRAM_LINK,
        ActionType.RESTRICT,
        delete_message=True,
        restrict_minutes=60,
    )
    # Сохраняем изменения
    await db_session.commit()

    # Создаем mock сообщения с Telegram ссылкой
    message_mock = MagicMock(spec=Message)
    # Устанавливаем атрибуты
    message_mock.chat = MagicMock()
    # Устанавливаем ID чата
    message_mock.chat.id = chat_id
    # Устанавливаем текст с Telegram ссылкой
    message_mock.text = "Реклама https://t.me/ad_channel"
    # Устанавливаем caption в None
    message_mock.caption = None
    # Устанавливаем forward_origin в None
    message_mock.forward_origin = None
    # Устанавливаем reply_to_message в None
    message_mock.reply_to_message = None

    # Проверяем сообщение через антиспам сервис
    decision = await check_message_for_spam(message_mock, db_session)

    # Проверяем что сообщение определено как спам
    assert decision.is_spam is True
    # Проверяем действие
    assert decision.action == ActionType.RESTRICT
    # Проверяем длительность ограничения
    assert decision.restrict_minutes == 60
    # Проверяем что сообщение нужно удалить
    assert decision.delete_message is True
