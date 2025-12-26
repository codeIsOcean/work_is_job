"""Добавляет таблицы кастомных разделов спама

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2025-12-23

Добавляет:
1. Таблица custom_spam_sections - кастомные разделы спама
   Позволяет создавать отдельные разделы для разных типов спама:
   - "Такси" — реклама такси
   - "Жильё" — аренда недвижимости
   - "Наркотики" — запрещённые вещества

   Каждый раздел имеет свои паттерны, порог, действие и
   опционально канал для пересылки.

2. Таблица custom_section_patterns - паттерны кастомных разделов
   Аналогично scam_patterns, но привязаны к разделу.
"""
# Импортируем op для операций с БД (создание таблиц, колонок)
from alembic import op
# Импортируем sa для определения типов данных колонок
import sqlalchemy as sa


# ─────────────────────────────────────────────────────────
# МЕТАДАННЫЕ МИГРАЦИИ
# ─────────────────────────────────────────────────────────
# Уникальный идентификатор этой миграции
revision = 'x4y5z6a7b8c9'
# Предыдущая миграция от которой зависит эта
down_revision = 'w3x4y5z6a7b8'
# Метки веток (не используем)
branch_labels = None
# Зависимости от других миграций (не используем)
depends_on = None


def upgrade() -> None:
    """
    Применяет миграцию: создаёт таблицы кастомных разделов.

    Эта функция вызывается при alembic upgrade head.
    """

    # ─────────────────────────────────────────────────────────
    # 1. СОЗДАЁМ ТАБЛИЦУ КАСТОМНЫХ РАЗДЕЛОВ СПАМА
    # ─────────────────────────────────────────────────────────
    op.create_table(
        # Имя таблицы в БД
        'custom_spam_sections',

        # PRIMARY KEY
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),

        # FOREIGN KEY: ID группы
        sa.Column('chat_id', sa.BigInteger(),
                  sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
                  nullable=False, index=True),

        # Название раздела
        sa.Column('name', sa.String(100), nullable=False),
        # Описание
        sa.Column('description', sa.String(500), nullable=True),

        # Активность
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),

        # Порог чувствительности
        sa.Column('threshold', sa.Integer(), nullable=False, server_default='60'),

        # Действие при срабатывании (delete, mute, ban, kick, forward_delete)
        sa.Column('action', sa.String(30), nullable=False, server_default='delete'),
        # Длительность мута в минутах
        sa.Column('mute_duration', sa.Integer(), nullable=True),

        # ID канала для пересылки
        sa.Column('forward_channel_id', sa.BigInteger(), nullable=True),

        # Кастомные тексты
        sa.Column('mute_text', sa.String(500), nullable=True),
        sa.Column('ban_text', sa.String(500), nullable=True),

        # Задержки
        sa.Column('delete_delay', sa.Integer(), nullable=True),
        sa.Column('notification_delete_delay', sa.Integer(), nullable=True),

        # Логирование
        sa.Column('log_violations', sa.Boolean(), nullable=False, server_default='true'),

        # Временные метки
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),

        # Аудит
        sa.Column('created_by', sa.BigInteger(), nullable=True),
    )

    # Уникальное ограничение: одно название раздела один раз в группе
    op.create_unique_constraint(
        'uq_custom_section_chat_name',
        'custom_spam_sections',
        ['chat_id', 'name']
    )

    # Индекс для поиска активных разделов группы
    op.create_index(
        'ix_custom_sections_chat_enabled',
        'custom_spam_sections',
        ['chat_id', 'enabled']
    )

    # ─────────────────────────────────────────────────────────
    # 2. СОЗДАЁМ ТАБЛИЦУ ПАТТЕРНОВ КАСТОМНЫХ РАЗДЕЛОВ
    # ─────────────────────────────────────────────────────────
    op.create_table(
        # Имя таблицы в БД
        'custom_section_patterns',

        # PRIMARY KEY
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),

        # FOREIGN KEY: ID раздела
        sa.Column('section_id', sa.Integer(),
                  sa.ForeignKey('custom_spam_sections.id', ondelete='CASCADE'),
                  nullable=False, index=True),

        # Паттерн
        sa.Column('pattern', sa.String(500), nullable=False),
        # Нормализованная версия
        sa.Column('normalized', sa.String(500), nullable=False, index=True),
        # Тип паттерна (word, phrase, regex)
        sa.Column('pattern_type', sa.String(20), nullable=False, server_default='phrase'),

        # Вес паттерна
        sa.Column('weight', sa.Integer(), nullable=False, server_default='25'),

        # Активность
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),

        # Статистика
        sa.Column('triggers_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),

        # Временная метка
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),

        # Аудит
        sa.Column('created_by', sa.BigInteger(), nullable=True),
    )

    # Уникальное ограничение: один паттерн один раз в разделе
    op.create_unique_constraint(
        'uq_section_pattern',
        'custom_section_patterns',
        ['section_id', 'pattern']
    )

    # Индекс для поиска активных паттернов раздела
    op.create_index(
        'ix_section_patterns_section_active',
        'custom_section_patterns',
        ['section_id', 'is_active']
    )


def downgrade() -> None:
    """
    Откатывает миграцию: удаляет таблицы.

    Эта функция вызывается при alembic downgrade.
    """

    # ─────────────────────────────────────────────────────────
    # УДАЛЯЕМ ТАБЛИЦУ ПАТТЕРНОВ (сначала, из-за FK)
    # ─────────────────────────────────────────────────────────
    op.drop_index('ix_section_patterns_section_active', table_name='custom_section_patterns')
    op.drop_constraint('uq_section_pattern', 'custom_section_patterns', type_='unique')
    op.drop_table('custom_section_patterns')

    # ─────────────────────────────────────────────────────────
    # УДАЛЯЕМ ТАБЛИЦУ РАЗДЕЛОВ
    # ─────────────────────────────────────────────────────────
    op.drop_index('ix_custom_sections_chat_enabled', table_name='custom_spam_sections')
    op.drop_constraint('uq_custom_section_chat_name', 'custom_spam_sections', type_='unique')
    op.drop_table('custom_spam_sections')
