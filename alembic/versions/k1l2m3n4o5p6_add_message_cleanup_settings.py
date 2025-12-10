"""Добавляет настройки модуля удаления сообщений

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2025-12-10

Добавляет настройки для модуля удаления сообщений:
- delete_user_commands - удалять команды от обычных пользователей
- delete_system_messages - удалять системные сообщения
"""
from alembic import op
import sqlalchemy as sa


revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляем колонки для модуля удаления сообщений."""

    # ─────────────────────────────────────────────────────────
    # МОДУЛЬ УДАЛЕНИЯ СООБЩЕНИЙ
    # ─────────────────────────────────────────────────────────
    # Удалять команды от обычных пользователей
    op.add_column('content_filter_settings', sa.Column(
        'delete_user_commands',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))

    # Удалять системные сообщения
    op.add_column('content_filter_settings', sa.Column(
        'delete_system_messages',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))


def downgrade() -> None:
    """Удаляем колонки модуля удаления сообщений."""
    op.drop_column('content_filter_settings', 'delete_system_messages')
    op.drop_column('content_filter_settings', 'delete_user_commands')
