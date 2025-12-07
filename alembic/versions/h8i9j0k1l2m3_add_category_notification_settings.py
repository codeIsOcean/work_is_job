"""Add category notification and delay settings

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2025-12-08

Добавляет колонки для настроек уведомлений и задержек удаления
для каждой категории слов (simple, harmful, obfuscated):
- *_mute_text - кастомный текст уведомления при муте (с плейсхолдером %user%)
- *_ban_text - кастомный текст уведомления при бане (с плейсхолдером %user%)
- *_delete_delay - задержка перед удалением сообщения нарушителя (секунды)
- *_notification_delete_delay - время до автоудаления уведомления бота (секунды)
"""
from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизий для цепочки миграций
revision = 'h8i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляем колонки для уведомлений и задержек удаления."""

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ПРОСТЫЕ СЛОВА (simple)
    # ─────────────────────────────────────────────────────────────
    # Кастомный текст уведомления при муте (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_mute_text',
        sa.String(500),
        nullable=True
    ))

    # Кастомный текст уведомления при бане (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_ban_text',
        sa.String(500),
        nullable=True
    ))

    # Задержка перед удалением сообщения нарушителя (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # Задержка перед автоудалением уведомления бота (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'simple_words_notification_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ВРЕДНЫЕ СЛОВА (harmful)
    # ─────────────────────────────────────────────────────────────
    # Кастомный текст уведомления при муте (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_mute_text',
        sa.String(500),
        nullable=True
    ))

    # Кастомный текст уведомления при бане (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_ban_text',
        sa.String(500),
        nullable=True
    ))

    # Задержка перед удалением сообщения нарушителя (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # Задержка перед автоудалением уведомления бота (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'harmful_words_notification_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # ─────────────────────────────────────────────────────────────
    # КАТЕГОРИЯ: ОБФУСКАЦИЯ (obfuscated)
    # ─────────────────────────────────────────────────────────────
    # Кастомный текст уведомления при муте (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_mute_text',
        sa.String(500),
        nullable=True
    ))

    # Кастомный текст уведомления при бане (поддерживает %user% плейсхолдер)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_ban_text',
        sa.String(500),
        nullable=True
    ))

    # Задержка перед удалением сообщения нарушителя (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # Задержка перед автоудалением уведомления бота (в секундах)
    op.add_column('content_filter_settings', sa.Column(
        'obfuscated_words_notification_delete_delay',
        sa.Integer(),
        nullable=True
    ))


def downgrade() -> None:
    """Удаляем колонки уведомлений и задержек при откате."""
    # Удаляем в обратном порядке

    # ─────────────────────────────────────────────────────────────
    # Обфускация (obfuscated)
    # ─────────────────────────────────────────────────────────────
    op.drop_column('content_filter_settings', 'obfuscated_words_notification_delete_delay')
    op.drop_column('content_filter_settings', 'obfuscated_words_delete_delay')
    op.drop_column('content_filter_settings', 'obfuscated_words_ban_text')
    op.drop_column('content_filter_settings', 'obfuscated_words_mute_text')

    # ─────────────────────────────────────────────────────────────
    # Вредные (harmful)
    # ─────────────────────────────────────────────────────────────
    op.drop_column('content_filter_settings', 'harmful_words_notification_delete_delay')
    op.drop_column('content_filter_settings', 'harmful_words_delete_delay')
    op.drop_column('content_filter_settings', 'harmful_words_ban_text')
    op.drop_column('content_filter_settings', 'harmful_words_mute_text')

    # ─────────────────────────────────────────────────────────────
    # Простые (simple)
    # ─────────────────────────────────────────────────────────────
    op.drop_column('content_filter_settings', 'simple_words_notification_delete_delay')
    op.drop_column('content_filter_settings', 'simple_words_delete_delay')
    op.drop_column('content_filter_settings', 'simple_words_ban_text')
    op.drop_column('content_filter_settings', 'simple_words_mute_text')