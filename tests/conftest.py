import asyncio
import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock
import sys
import pytest

import pytest

# КРИТИЧНО: Устанавливаем DATABASE_URL ДО импорта bot.config
# чтобы избежать ошибки "DATABASE_URL не установлен!"
# ВАЖНО: Используем postgres_unit_tests (порт 5434), НЕ postgres_test (порт 5433)!
#
# Проблема: bot/config.py загружает .env файл при импорте и перезаписывает DATABASE_URL
# Решение: Устанавливаем TEST_DATABASE_URL который имеет приоритет в _build_database_url()
#
# Настройки для postgres_unit_tests из docker-compose.test.yml
_test_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
_test_port = "5434"  # Порт 5434 - postgres_unit_tests (НЕ 5433!)
_test_db = "unit_tests"  # БД unit_tests
_test_user = "test_runner"
_test_pass = "test_runner_pass"
_test_database_url = f"postgresql+asyncpg://{_test_user}:{_test_pass}@{_test_host}:{_test_port}/{_test_db}"

# Устанавливаем TEST_DATABASE_URL который используется в _build_database_url()
os.environ["TEST_DATABASE_URL"] = _test_database_url

# Также устанавливаем DATABASE_URL для bot.config (чтобы не было ошибки при импорте)
# Но реальное подключение будет к TEST_DATABASE_URL
os.environ["DATABASE_URL"] = _test_database_url

# Гарантируем, что пакет bot доступен для импортов из тестов
# (добавляем корень проекта в sys.path независимо от того, откуда запущен pytest).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from aiogram import Bot
from aiogram.types import CallbackQuery, Message, Update
from fakeredis import aioredis as fakeredis_aioredis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from redis.asyncio import Redis as AsyncRedis

from bot.database.models import Base
from bot.database import session as db_session_module
from bot.services import redis_conn as redis_module

# Импортируем все модели чтобы они зарегистрировались в Base.metadata
# Это необходимо для корректного создания таблиц в тестах
import bot.database.models_content_filter  # noqa: F401
import bot.database.models_antispam  # noqa: F401
import bot.database.mute_models  # noqa: F401
import bot.database.models_scam_media  # noqa: F401


def _build_database_url() -> str:
    """
    Строит URL для подключения к тестовой БД.

    ВАЖНО: По умолчанию использует postgres_unit_tests на порту 5434!
    Это ОТДЕЛЬНАЯ БД только для pytest, не связанная с bot_test.

    Запуск БД: docker-compose -f docker-compose.test.yml up -d postgres_unit_tests
    """
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit

    # Настройки для postgres_unit_tests из docker-compose.test.yml
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5434")  # Порт 5434 - postgres_unit_tests
    db_name = os.getenv("POSTGRES_DB", "unit_tests")  # БД unit_tests
    user = os.getenv("POSTGRES_USER", "test_runner")
    password = os.getenv("POSTGRES_PASSWORD", "test_runner_pass")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"


# ========== ЗАЩИТА ОТ ПОДКЛЮЧЕНИЯ К БОЕВОЙ БД ==========
# Список запрещённых имён БД (боевые базы данных)
FORBIDDEN_DB_NAMES = [
    "jobs_inDubai_testBot",  # Тестовый бот (локальный)
    "bot_prod",              # Продакшн бот
    "kvd_moder_bot",         # Любые вариации имени бота
]

def _validate_database_url(database_url: str) -> None:
    """
    Проверяет что тесты НЕ подключаются к боевой БД.
    Вызывает RuntimeError если обнаружена попытка подключения к запрещённой БД.
    """
    # Извлекаем имя БД из URL
    # Формат: postgresql+asyncpg://user:pass@host:port/db_name
    if "/" in database_url:
        db_name = database_url.rsplit("/", 1)[-1]
        # Убираем query параметры если есть
        if "?" in db_name:
            db_name = db_name.split("?")[0]

        # Проверяем на запрещённые имена
        for forbidden in FORBIDDEN_DB_NAMES:
            if forbidden.lower() in db_name.lower():
                raise RuntimeError(
                    f"\n\n"
                    f"╔══════════════════════════════════════════════════════════════╗\n"
                    f"║  ⛔ КРИТИЧЕСКАЯ ОШИБКА: ПОПЫТКА ПОДКЛЮЧЕНИЯ К БОЕВОЙ БД!    ║\n"
                    f"╠══════════════════════════════════════════════════════════════╣\n"
                    f"║  БД: {db_name:<54} ║\n"
                    f"║  Запрещено: {forbidden:<47} ║\n"
                    f"╠══════════════════════════════════════════════════════════════╣\n"
                    f"║  Тесты удаляют ВСЕ данные из БД!                            ║\n"
                    f"║  Используйте отдельную тестовую БД.                         ║\n"
                    f"║                                                              ║\n"
                    f"║  Решение: установите TEST_DATABASE_URL или используйте      ║\n"
                    f"║  БД с именем 'testdb' на порту 5433                         ║\n"
                    f"╚══════════════════════════════════════════════════════════════╝\n"
                )

    # Дополнительная проверка: имя БД должно содержать "test"
    # (кроме явно разрешённых случаев)
    if "/" in database_url:
        db_name = database_url.rsplit("/", 1)[-1].split("?")[0]
        if "test" not in db_name.lower() and db_name != "testdb":
            raise RuntimeError(
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════╗\n"
                f"║  ⚠️ ПРЕДУПРЕЖДЕНИЕ: Имя БД не содержит 'test'               ║\n"
                f"╠══════════════════════════════════════════════════════════════╣\n"
                f"║  БД: {db_name:<54} ║\n"
                f"╠══════════════════════════════════════════════════════════════╣\n"
                f"║  Для безопасности имя тестовой БД должно содержать 'test'   ║\n"
                f"║  Установите TEST_DATABASE_URL с правильным именем БД        ║\n"
                f"╚══════════════════════════════════════════════════════════════╝\n"
            )


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def _reset_redis_client():
    """Переинициализирует глобальный Redis-клиент для каждого async-теста.

    Это устраняет ошибки вида "Future attached to a different loop" и
    "Event loop is closed", которые возникают, когда один и тот же
    Redis-клиент используется в разных event loop.
    """
    # Закрываем старый клиент, если он был
    old_client = getattr(redis_module, "redis", None)
    if old_client is not None and hasattr(old_client, "aclose"):
        try:
            await old_client.aclose()
        except Exception:
            # В тестах игнорируем ошибки закрытия
            pass

    redis_module.redis = AsyncRedis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )

    yield

    # После теста пробуем аккуратно закрыть клиент
    new_client = getattr(redis_module, "redis", None)
    if new_client is not None and hasattr(new_client, "aclose"):
        try:
            await new_client.aclose()
        except Exception:
            pass


@pytest.fixture(scope="session")
async def _setup_test_database():
    """Create database schema and patch global session factory to use test database."""
    from sqlalchemy import text

    async def init_engine(url: str):
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        async with engine.begin() as conn:
            # Удаляем все таблицы с CASCADE для PostgreSQL
            if "postgresql" in url:
                await conn.execute(text("""
                    DO $$ DECLARE
                        r RECORD;
                    BEGIN
                        FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                            EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                        END LOOP;
                    END $$;
                """))
            else:
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        return engine

    database_url = _build_database_url()

    # КРИТИЧНО: Проверяем что не подключаемся к боевой БД!
    _validate_database_url(database_url)

    engine = None
    try:
        engine = await init_engine(database_url)
    except Exception as exc:
        print(f"⚠️ Unable to initialise Postgres database at {database_url}: {exc}")
        fallback_path = Path("tests/temp_test.db").resolve()
        fallback_url = f"sqlite+aiosqlite:///{fallback_path}"
        engine = await init_engine(fallback_url)
        database_url = fallback_url
        os.environ["DATABASE_URL"] = database_url

    os.environ["DATABASE_URL"] = database_url

    TestingSessionMaker = async_sessionmaker(engine, expire_on_commit=False)
    original_engine = db_session_module.engine
    original_sessionmaker = db_session_module.async_session
    db_session_module.engine = engine
    db_session_module.async_session = TestingSessionMaker

    try:
        yield TestingSessionMaker
    finally:
        db_session_module.engine = original_engine
        db_session_module.async_session = original_sessionmaker
        await engine.dispose()


@pytest.fixture
async def db_session(_setup_test_database):
    """Provide an isolated database session for a test."""
    from sqlalchemy import text

    engine = db_session_module.engine
    async with engine.begin() as conn:
        # Удаляем все таблицы с CASCADE для PostgreSQL
        # Это решает проблему зависимых foreign keys
        await conn.execute(text("""
            DO $$ DECLARE
                r RECORD;
            BEGIN
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                END LOOP;
            END $$;
        """))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = _setup_test_database
    session = session_factory()

    try:
        yield session
    finally:
        try:
            await session.rollback()
        finally:
            await session.close()


@pytest.fixture
async def fake_redis(monkeypatch):
    """Patch project-wide redis client with fakeredis for unit tests."""
    client = fakeredis_aioredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr("bot.services.redis_conn.redis", client)
    monkeypatch.setattr("bot.services.visual_captcha_logic.redis", client)
    monkeypatch.setattr("bot.services.auto_mute_scammers_logic.redis", client, raising=False)
    monkeypatch.setattr("bot.services.groups_settings_in_private_logic.redis", client, raising=False)

    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest.fixture
async def redis_client_e2e():
    """Real redis client for end-to-end tests."""
    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6380"))
    db_index = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD")

    client = AsyncRedis(
        host=host,
        port=port,
        db=db_index,
        password=password,
        decode_responses=True,
    )

    try:
        await client.ping()
    except Exception as exc:
        await client.close()
        pytest.skip(f"Redis ({host}:{port}) is not available: {exc}")

    yield client

    await client.flushall()
    await client.aclose()


@pytest.fixture
def bot_mock():
    """Async mock for aiogram Bot."""
    bot = AsyncMock(spec=Bot)
    bot.__call__ = AsyncMock()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.get_chat = AsyncMock()
    bot.create_chat_invite_link = AsyncMock()
    bot.approve_chat_join_request = AsyncMock()
    bot.get_chat_member = AsyncMock()
    bot.get_user_profile_photos = AsyncMock()
    bot.get_updates = AsyncMock()
    bot.get_me = AsyncMock()
    bot.restrict_chat_member = AsyncMock()
    bot.session = AsyncMock()
    bot.id = 424242
    return bot


@pytest.fixture
def message_factory() -> Callable[..., Message]:
    """Factory for aiogram Message instances."""

    def _factory(
        *,
        message_id: int = 1,
        user_id: int = 100,
        chat_id: int = -1000,
        text: str = "/start",
        chat_type: str = "supergroup",
        first_name: str = "Test",
    ) -> Message:
        payload = {
            "message_id": message_id,
            "date": datetime.now(timezone.utc),
            "chat": {"id": chat_id, "type": chat_type, "title": "Test chat"},
            "from": {"id": user_id, "is_bot": False, "first_name": first_name},
            "text": text,
        }
        return Message.model_validate(payload)

    return _factory


@pytest.fixture
def callback_query_factory(message_factory) -> Callable[..., CallbackQuery]:
    """Factory for aiogram CallbackQuery instances."""

    def _factory(
        *,
        data: str = "test",
        from_user_id: int = 100,
        chat_id: int = -1000,
    ) -> CallbackQuery:
        message = message_factory(chat_id=chat_id)
        payload = {
            "id": "test-callback",
            "data": data,
            "chat_instance": "test-instance",
            "message": message.model_dump(),
            "from": {
                "id": from_user_id,
                "is_bot": False,
                "first_name": "Tester",
            },
        }
        return CallbackQuery.model_validate(payload)

    return _factory


@pytest.fixture
def update_factory(message_factory) -> Callable[..., Update]:
    """Factory for aiogram Update objects."""

    def _factory(message: Message = None) -> Update:
        if message is None:
            message = message_factory()
        payload = {"update_id": 1, "message": message.model_dump()}
        return Update.model_validate(payload)

    return _factory


def pytest_collection_modifyitems(config, items):
    """Skip e2e tests on Windows (real Redis/DB + Windows event loop = нестабильно).

    В проде (Linux) эти тесты должны запускаться без skip.

    ИСКЛЮЧЕНИЯ:
    - test_userbot_flows.py — работает на Windows (использует Pyrogram userbot)
    - test_telegram_html.py — работает на Windows (простые API вызовы)
    """
    if sys.platform.startswith("win"):
        skip_e2e = pytest.mark.skip(reason="e2e tests are unstable on Windows; run them on Linux CI/prod")

        # Файлы которые НЕ пропускаем на Windows
        allowed_on_windows = {"test_userbot_flows.py", "test_telegram_html.py", "test_mute_by_reaction_e2e.py", "test_custom_sections_e2e.py", "test_escort_spam_e2e.py", "test_criterion6_e2e.py", "test_content_filter_ui_e2e.py", "test_scam_settings_comprehensive_e2e.py", "test_content_filter_comprehensive_e2e.py", "test_scam_media_e2e.py", "test_scam_media_ui_e2e.py"}

        for item in items:
            if "e2e" in item.keywords:
                # Проверяем имя файла
                test_file = Path(item.fspath).name
                if test_file not in allowed_on_windows:
                    item.add_marker(skip_e2e)


HANDLER_MODULES = [
    "bot.handlers.bot_activity_handlers",
    "bot.handlers.bot_activity_journal.bot_activity_journal",
    "bot.handlers.deep_link_handlers",
    "bot.handlers.group_settings_handler.groups_settings_in_private_handler",
    "bot.handlers.moderation_handlers.moderation_handler",
    "bot.handlers.visual_captcha.visual_captcha_handler",
    "bot.handlers.broadcast_handlers.broadcast_handlers",
    "bot.handlers.bot_moderation_handlers.new_member_requested_to_join_mute_handlers",
    "bot.handlers.auto_mute_scammers_handlers",
    "bot.handlers.admin_log_handlers",
    "bot.handlers.enhanced_analysis_test_handler",
    "bot.handlers.journal_link_handler",
]


def _reload_module(name: str):
    module = sys.modules.get(name)
    if module is None:
        module = importlib.import_module(name)
    else:
        module = importlib.reload(module)
    return module


def _fresh_handlers_router():
    for module_name in HANDLER_MODULES:
        _reload_module(module_name)
    handlers_module = _reload_module("bot.handlers")
    return handlers_module.create_fresh_handlers_router()


@pytest.fixture
def router_factory():
    def factory():
        return _fresh_handlers_router()

    return factory

