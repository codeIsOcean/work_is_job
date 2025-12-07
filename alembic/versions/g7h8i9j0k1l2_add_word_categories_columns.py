"""Add word categories columns (simple, harmful, obfuscated)

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2025-12-07

Добавляет колонки для 3 категорий слов с раздельными настройками:
- simple (простые слова) - реклама, спам
- harmful (вредные) - наркотики, запрещённый контент
- obfuscated (обманки) - l33tspeak обходы
"""
from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизий для цепочки миграций
revision = 'g7h8i9j0k1l2'
down_revision = 'f6g7h8i9j0k1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляем колонки для раздельных настроек категорий слов."""

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ПРОСТЫЕ СЛОВА (simple)
    # ─────────────────────────────────────────────────────────────
    # Включить/выключить фильтрацию простых слов
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_enabled',
        sa.Boolean(),
        nullable=True,
        server_default='true'  # По умолчанию включено
    ))

    # Действие для простых слов (delete/warn/mute/kick/ban)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_action',
        sa.String(20),
        nullable=True,
        server_default='delete'  # По умолчанию только удалять
    ))

    # Длительность мута для простых слов (в минутах)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_mute_duration',
        sa.Integer(),
        nullable=True
    ))

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ВРЕДНЫЕ СЛОВА (harmful)
    # ─────────────────────────────────────────────────────────────
    # Включить/выключить фильтрацию вредных слов
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_enabled',
        sa.Boolean(),
        nullable=True,
        server_default='true'  # По умолчанию включено
    ))

    # Действие для вредных слов
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_action',
        sa.String(20),
        nullable=True,
        server_default='ban'  # По умолчанию бан
    ))

    # Длительность мута для вредных слов (в минутах)
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_mute_duration',
        sa.Integer(),
        nullable=True
    ))

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ОБФУСКАЦИЯ (obfuscated)
    # ─────────────────────────────────────────────────────────────
    # Включить/выключить фильтрацию обфускации (l33tspeak)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_enabled',
        sa.Boolean(),
        nullable=True,
        server_default='true'  # По умолчанию включено
    ))

    # Действие для обфускации
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_action',
        sa.String(20),
        nullable=True,
        server_default='mute'  # По умолчанию мут
    ))

    # Длительность мута для обфускации (в минутах)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_mute_duration',
        sa.Integer(),
        nullable=True,
        server_default='1440'  # По умолчанию 24 часа
    ))


def downgrade() -> None:
    """Удаляем колонки категорий слов при откате."""
    # Удаляем в обратном порядке

    # Обфускация
    op.drop_column('content_filter_settings', 'obfuscated_words_mute_duration')
    op.drop_column('content_filter_settings', 'obfuscated_words_action')
    op.drop_column('content_filter_settings', 'obfuscated_words_enabled')

    # Вредные
    op.drop_column('content_filter_settings', 'harmful_words_mute_duration')
    op.drop_column('content_filter_settings', 'harmful_words_action')
    op.drop_column('content_filter_settings', 'harmful_words_enabled')

    # Простые
    op.drop_column('content_filter_settings', 'simple_words_mute_duration')
    op.drop_column('content_filter_settings', 'simple_words_action')
    op.drop_column('content_filter_settings', 'simple_words_enabled')
