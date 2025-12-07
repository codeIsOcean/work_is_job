"""add_separate_actions_columns

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2025-12-06 16:00:00.000000

Добавляет колонки для раздельных действий в content_filter_settings:
- word_filter_action: действие для запрещённых слов
- word_filter_mute_duration: длительность мута для слов
- flood_action: действие для антифлуда
- flood_mute_duration: длительность мута для флуда
- word_filter_normalize: флаг нормализатора для слов
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
revision: str = 'f6g7h8i9j0k1'
# Предыдущая миграция (scam_patterns_table)
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
# Метки веток (не используется)
branch_labels: Union[str, Sequence[str], None] = None
# Зависимости от других миграций (не используется)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Применить миграцию: добавить колонки для раздельных действий.

    Все новые колонки nullable=True или имеют server_default,
    что делает миграцию безопасной для существующих данных.
    """

    # ─────────────────────────────────────────────────────────
    # КОЛОНКИ ДЛЯ ДЕЙСТВИЙ WORD FILTER
    # ─────────────────────────────────────────────────────────
    # Действие для запрещённых слов (NULL = использовать default_action)
    op.add_column(
        'content_filter_settings',
        sa.Column('word_filter_action', sa.String(20), nullable=True)
    )

    # Длительность мута для запрещённых слов (NULL = использовать default)
    op.add_column(
        'content_filter_settings',
        sa.Column('word_filter_mute_duration', sa.Integer(), nullable=True)
    )

    # ─────────────────────────────────────────────────────────
    # КОЛОНКИ ДЛЯ ДЕЙСТВИЙ FLOOD DETECTOR
    # ─────────────────────────────────────────────────────────
    # Действие для антифлуда (NULL = использовать default_action)
    op.add_column(
        'content_filter_settings',
        sa.Column('flood_action', sa.String(20), nullable=True)
    )

    # Длительность мута для антифлуда (NULL = использовать default)
    op.add_column(
        'content_filter_settings',
        sa.Column('flood_mute_duration', sa.Integer(), nullable=True)
    )

    # ─────────────────────────────────────────────────────────
    # ФЛАГ НОРМАЛИЗАТОРА ДЛЯ WORD FILTER
    # ─────────────────────────────────────────────────────────
    # True = применять TextNormalizer к словам (обход l33tspeak)
    # False = искать слова как есть
    # По умолчанию True для обратной совместимости
    op.add_column(
        'content_filter_settings',
        sa.Column('word_filter_normalize', sa.Boolean(), nullable=False, server_default='true')
    )


def downgrade() -> None:
    """
    Откатить миграцию: удалить добавленные колонки.
    """

    # Удаляем колонки в обратном порядке
    op.drop_column('content_filter_settings', 'word_filter_normalize')
    op.drop_column('content_filter_settings', 'flood_mute_duration')
    op.drop_column('content_filter_settings', 'flood_action')
    op.drop_column('content_filter_settings', 'word_filter_mute_duration')
    op.drop_column('content_filter_settings', 'word_filter_action')
