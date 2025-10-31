import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
# 1. Загружаем .env в самом начале
from dotenv import load_dotenv

# ✅ Добавляем путь до корня проекта (чтобы работал импорт bot) изменения сделаны на 24.04.25
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Определяем окружение и загружаем соответствующий .env файл
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
if ENVIRONMENT == "production":
    env_file = ".env.prod"
elif ENVIRONMENT == "testing":
    env_file = ".env.test"
else:
    env_file = ".env.dev"

# Загружаем .env файл
load_dotenv(env_file)

from bot.database.models import Base

# 2. Берем URL из переменной окружения
ALEMBIC_URL = os.getenv("ALEMBIC_URL") or os.getenv("DATABASE_URL")

# 3. Доступ к конфигу alembic ini
config = context.config

# 4. Устанавливаем значение sqlalchemy.url
if ALEMBIC_URL:
    config.set_main_option("sqlalchemy.url", ALEMBIC_URL)

# 5. Настройка логов
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 6. Метаданные моделей
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
