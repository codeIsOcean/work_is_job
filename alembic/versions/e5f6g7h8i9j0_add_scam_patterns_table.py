"""add_scam_patterns_table

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-12-06 14:00:00.000000

Создаёт таблицу для кастомных паттернов скама (scam_patterns).
Админы групп могут добавлять свои паттерны для детектора скама.
Каждый паттерн имеет вес (weight) — сумма весов сработавших паттернов
сравнивается с порогом чувствительности (scam_sensitivity).
"""
# Импорт типов для аннотаций
from typing import Sequence, Union

# Импорт операций Alembic для миграций
from alembic import op
# Импорт типов данных SQLAlchemy
import sqlalchemy as sa


# ============================================================
# ИДЕНТИФИКАТОРЫ РЕВИЗИЙ
# ============================================================
# Уникальный идентификатор этой миграции
revision: str = 'e5f6g7h8i9j0'
# Предыдущая миграция (content_filter_tables)
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
# Метки веток (не используется)
branch_labels: Union[str, Sequence[str], None] = None
# Зависимости (не используется)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Применить миграцию: создать таблицу scam_patterns.

    Таблица хранит кастомные паттерны для детектора скама.
    Каждая группа может добавлять свои паттерны.
    """

    # ============================================================
    # ТАБЛИЦА: КАСТОМНЫЕ ПАТТЕРНЫ СКАМА
    # ============================================================
    # Хранит паттерны для антискам-детектора каждой группы
    op.create_table(
        # Имя таблицы в базе данных
        'scam_patterns',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY: Автоинкрементный ID
        # ─────────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # FOREIGN KEY: ID группы
        # ─────────────────────────────────────────────────────────
        # Привязка паттерна к конкретной группе
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ПАТТЕРН (текст для поиска)
        # ─────────────────────────────────────────────────────────
        # Оригинальный паттерн как ввёл админ
        sa.Column('pattern', sa.String(500), nullable=False),
        # Нормализованная версия для поиска (lowercase, trim)
        sa.Column('normalized', sa.String(500), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ТИП ПАТТЕРНА
        # ─────────────────────────────────────────────────────────
        # word = как отдельное слово
        # phrase = как подстрока (по умолчанию)
        # regex = регулярное выражение
        sa.Column('pattern_type', sa.String(20), nullable=False, server_default='phrase'),

        # ─────────────────────────────────────────────────────────
        # ВЕС ПАТТЕРНА (влияет на итоговый скор)
        # ─────────────────────────────────────────────────────────
        # 10-15 = слабый сигнал, 20-30 = средний, 35-50 = сильный
        # По умолчанию 25 (средний)
        sa.Column('weight', sa.Integer(), nullable=False, server_default='25'),

        # ─────────────────────────────────────────────────────────
        # КАТЕГОРИЯ (для группировки)
        # ─────────────────────────────────────────────────────────
        # money, crypto, gambling, drugs, adult, other
        sa.Column('category', sa.String(50), nullable=True),

        # ─────────────────────────────────────────────────────────
        # АКТИВНОСТЬ
        # ─────────────────────────────────────────────────────────
        # True = паттерн активен, False = временно отключён
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),

        # ─────────────────────────────────────────────────────────
        # СТАТИСТИКА СРАБАТЫВАНИЙ
        # ─────────────────────────────────────────────────────────
        # Сколько раз сработал (для аналитики)
        sa.Column('triggers_count', sa.Integer(), nullable=False, server_default='0'),
        # Когда последний раз сработал
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # АУДИТ
        # ─────────────────────────────────────────────────────────
        # ID админа который добавил паттерн
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        # Когда добавлен
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Первичный ключ
        sa.PrimaryKeyConstraint('id'),
        # Внешний ключ на groups с каскадным удалением
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
        # Уникальное ограничение: один паттерн один раз в группе
        sa.UniqueConstraint('chat_id', 'pattern', name='uq_scam_pattern_chat_pattern'),
    )

    # ============================================================
    # СОЗДАНИЕ ИНДЕКСОВ
    # ============================================================

    # Индекс для быстрого поиска паттернов по группе
    op.create_index(
        'ix_scam_patterns_chat_id',
        'scam_patterns',
        ['chat_id'],
        unique=False
    )

    # Индекс для поиска по нормализованному паттерну
    op.create_index(
        'ix_scam_patterns_normalized',
        'scam_patterns',
        ['normalized'],
        unique=False
    )

    # Составной индекс для поиска активных паттернов группы
    # Ускоряет: SELECT * FROM scam_patterns WHERE chat_id=X AND is_active=True
    op.create_index(
        'ix_scam_patterns_chat_active',
        'scam_patterns',
        ['chat_id', 'is_active'],
        unique=False
    )


def downgrade() -> None:
    """
    Откатить миграцию: удалить таблицу scam_patterns.
    """

    # Сначала удаляем индексы
    op.drop_index('ix_scam_patterns_chat_active', table_name='scam_patterns')
    op.drop_index('ix_scam_patterns_normalized', table_name='scam_patterns')
    op.drop_index('ix_scam_patterns_chat_id', table_name='scam_patterns')

    # Удаляем таблицу
    op.drop_table('scam_patterns')
