"""Add extended flood detection settings

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2025-12-10

Добавляет настройки для расширенного антифлуда:
- flood_detect_any_messages - детекция любых сообщений подряд
- flood_any_max_messages - лимит любых сообщений
- flood_any_time_window - временное окно для любых сообщений
- flood_detect_media - детекция медиа-флуда (фото, стикеры, видео, войсы)
"""
from alembic import op
import sqlalchemy as sa


revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляем колонки для расширенного антифлуда."""

    # ─────────────────────────────────────────────────────────
    # РАСШИРЕННЫЙ АНТИФЛУД: ЛЮБЫЕ СООБЩЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Включить детекцию любых сообщений подряд
    op.add_column('content_filter_settings', sa.Column(
        'flood_detect_any_messages',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))

    # Максимум любых сообщений за временное окно
    op.add_column('content_filter_settings', sa.Column(
        'flood_any_max_messages',
        sa.Integer(),
        nullable=False,
        server_default='5'
    ))

    # Временное окно для подсчёта любых сообщений (секунды)
    op.add_column('content_filter_settings', sa.Column(
        'flood_any_time_window',
        sa.Integer(),
        nullable=False,
        server_default='10'
    ))

    # ─────────────────────────────────────────────────────────
    # РАСШИРЕННЫЙ АНТИФЛУД: МЕДИА
    # ─────────────────────────────────────────────────────────
    # Включить детекцию медиа-флуда
    op.add_column('content_filter_settings', sa.Column(
        'flood_detect_media',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))


def downgrade() -> None:
    """Удаляем колонки расширенного антифлуда."""
    op.drop_column('content_filter_settings', 'flood_detect_media')
    op.drop_column('content_filter_settings', 'flood_any_time_window')
    op.drop_column('content_filter_settings', 'flood_any_max_messages')
    op.drop_column('content_filter_settings', 'flood_detect_any_messages')
