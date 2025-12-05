"""add_antispam_tables

Revision ID: a1b2c3d4e5f6
Revises: 3e9d3ae1b123
Create Date: 2025-12-04 00:00:00.000000

"""
# Импорт типов для аннотаций
from typing import Sequence, Union

# Импорт операций Alembic для миграций
from alembic import op
# Импорт типов данных SQLAlchemy
import sqlalchemy as sa
# Импорт PostgreSQL-специфичных типов
from sqlalchemy.dialects import postgresql


# Идентификаторы ревизий, используемые Alembic
# Уникальный идентификатор этой миграции
revision: str = 'a1b2c3d4e5f6'
# Предыдущая миграция, на которую опирается эта
down_revision: Union[str, None] = '3e9d3ae1b123'
# Метки веток (не используется в линейных миграциях)
branch_labels: Union[str, Sequence[str], None] = None
# Зависимости от других миграций (не используется)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить миграцию: создать таблицы и enum типы для антиспам модуля."""

    # ============================================================
    # СОЗДАНИЕ ENUM ТИПОВ (через raw SQL с проверкой существования)
    # ============================================================

    # Используем raw SQL для создания enum с проверкой - работает надёжнее чем checkfirst
    connection = op.get_bind()

    # Создаем enum для типов правил антиспам
    connection.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE rule_type_enum AS ENUM (
                'TELEGRAM_LINK', 'ANY_LINK', 'FORWARD_CHANNEL', 'FORWARD_GROUP',
                'FORWARD_USER', 'FORWARD_BOT', 'QUOTE_CHANNEL', 'QUOTE_GROUP',
                'QUOTE_USER', 'QUOTE_BOT'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Создаем enum для действий при срабатывании правила
    connection.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE action_type_enum AS ENUM ('OFF', 'WARN', 'KICK', 'RESTRICT', 'BAN');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Создаем enum для областей применения белого списка
    connection.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE whitelist_scope_enum AS ENUM ('TELEGRAM_LINK', 'ANY_LINK', 'FORWARD', 'QUOTE');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Определяем enum типы для использования в колонках (без создания)
    # ВАЖНО: используем postgresql.ENUM вместо sa.Enum для корректной работы create_type=False
    rule_type_enum = postgresql.ENUM(
        'TELEGRAM_LINK', 'ANY_LINK', 'FORWARD_CHANNEL', 'FORWARD_GROUP',
        'FORWARD_USER', 'FORWARD_BOT', 'QUOTE_CHANNEL', 'QUOTE_GROUP',
        'QUOTE_USER', 'QUOTE_BOT',
        name='rule_type_enum', create_type=False
    )
    action_type_enum = postgresql.ENUM(
        'OFF', 'WARN', 'KICK', 'RESTRICT', 'BAN',
        name='action_type_enum', create_type=False
    )
    whitelist_scope_enum = postgresql.ENUM(
        'TELEGRAM_LINK', 'ANY_LINK', 'FORWARD', 'QUOTE',
        name='whitelist_scope_enum', create_type=False
    )

    # ============================================================
    # СОЗДАНИЕ ТАБЛИЦЫ ПРАВИЛ АНТИСПАМ
    # ============================================================

    # Создаем таблицу для хранения правил антиспам
    op.create_table(
        # Имя таблицы в базе данных
        'antispam_rules',
        # Первичный ключ, автоинкремент
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # ID группы, к которой применяется правило
        # Внешний ключ на groups.chat_id с каскадным удалением
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        # Тип правила (используем созданный enum)
        sa.Column('rule_type', rule_type_enum, nullable=False),
        # Действие при срабатывании (используем созданный enum)
        sa.Column('action', action_type_enum, nullable=False),
        # Флаг удаления сообщения
        sa.Column('delete_message', sa.Boolean(), nullable=False, server_default='false'),
        # Длительность ограничения в минутах (NULL если не применимо)
        sa.Column('restrict_minutes', sa.Integer(), nullable=True),
        # Дата и время создания правила
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        # Дата и время последнего обновления
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        # Определяем первичный ключ
        sa.PrimaryKeyConstraint('id'),
        # Создаем внешний ключ на таблицу groups
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
    )

    # Создаем индекс для быстрого поиска правил по chat_id
    op.create_index(
        'ix_antispam_rules_chat_id',
        'antispam_rules',
        ['chat_id'],
        unique=False
    )

    # Создаем составной индекс для быстрого поиска правил по группе и типу
    op.create_index(
        'ix_antispam_rules_chat_rule',
        'antispam_rules',
        ['chat_id', 'rule_type'],
        unique=False
    )

    # Создаем индекс для поиска по типу правила
    op.create_index(
        'ix_antispam_rules_rule_type',
        'antispam_rules',
        ['rule_type'],
        unique=False
    )

    # Создаем индекс для поиска активных правил (где action не OFF)
    op.create_index(
        'ix_antispam_rules_action',
        'antispam_rules',
        ['action'],
        unique=False
    )

    # ============================================================
    # СОЗДАНИЕ ТАБЛИЦЫ БЕЛОГО СПИСКА
    # ============================================================

    # Создаем таблицу для хранения исключений (белого списка)
    op.create_table(
        # Имя таблицы в базе данных
        'antispam_whitelist',
        # Первичный ключ, автоинкремент
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # ID группы, для которой применяется исключение
        # Внешний ключ на groups.chat_id с каскадным удалением
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        # Область применения исключения (используем созданный enum)
        sa.Column('scope', whitelist_scope_enum, nullable=False),
        # Паттерн для проверки (часть URL, домен или ID канала)
        sa.Column('pattern', sa.Text(), nullable=False),
        # ID пользователя, который добавил запись
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        # Дата и время добавления записи
        sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        # Определяем первичный ключ
        sa.PrimaryKeyConstraint('id'),
        # Создаем внешний ключ на таблицу groups
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
    )

    # Создаем индекс для быстрого поиска записей белого списка по chat_id
    op.create_index(
        'ix_antispam_whitelist_chat_id',
        'antispam_whitelist',
        ['chat_id'],
        unique=False
    )

    # Создаем индекс для быстрого поиска по области применения
    op.create_index(
        'ix_antispam_whitelist_scope',
        'antispam_whitelist',
        ['scope'],
        unique=False
    )

    # Создаем составной индекс для быстрого поиска по группе и области
    op.create_index(
        'ix_antispam_whitelist_chat_scope',
        'antispam_whitelist',
        ['chat_id', 'scope'],
        unique=False
    )


def downgrade() -> None:
    """Откатить миграцию: удалить таблицы и enum типы для антиспам модуля."""

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦ
    # ============================================================

    # Удаляем индексы таблицы antispam_whitelist
    op.drop_index('ix_antispam_whitelist_chat_scope', table_name='antispam_whitelist')
    # Удаляем индекс по области применения
    op.drop_index('ix_antispam_whitelist_scope', table_name='antispam_whitelist')
    # Удаляем индекс по chat_id
    op.drop_index('ix_antispam_whitelist_chat_id', table_name='antispam_whitelist')
    # Удаляем таблицу белого списка
    op.drop_table('antispam_whitelist')

    # Удаляем индексы таблицы antispam_rules
    op.drop_index('ix_antispam_rules_action', table_name='antispam_rules')
    # Удаляем индекс по типу правила
    op.drop_index('ix_antispam_rules_rule_type', table_name='antispam_rules')
    # Удаляем составной индекс
    op.drop_index('ix_antispam_rules_chat_rule', table_name='antispam_rules')
    # Удаляем индекс по chat_id
    op.drop_index('ix_antispam_rules_chat_id', table_name='antispam_rules')
    # Удаляем таблицу правил антиспам
    op.drop_table('antispam_rules')

    # ============================================================
    # УДАЛЕНИЕ ENUM ТИПОВ
    # ============================================================

    # Получаем соединение с БД
    bind = op.get_bind()

    # Удаляем enum тип для областей применения белого списка
    sa.Enum(name='whitelist_scope_enum').drop(bind, checkfirst=True)
    # Удаляем enum тип для действий
    sa.Enum(name='action_type_enum').drop(bind, checkfirst=True)
    # Удаляем enum тип для типов правил
    sa.Enum(name='rule_type_enum').drop(bind, checkfirst=True)
