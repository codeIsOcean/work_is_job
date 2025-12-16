"""add join_captcha_message_ttl and invite_captcha_message_ttl columns

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2025-12-16 00:00:00.000000

Добавляет колонки для настройки TTL автоудаления сообщений капчи в группе:
- join_captcha_message_ttl_seconds - TTL для Join Captcha
- invite_captcha_message_ttl_seconds - TTL для Invite Captcha
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't0u1v2w3x4y5'
down_revision: Union[str, None] = 's9t0u1v2w3x4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет колонки для TTL автоудаления сообщений капчи в группе.

    join_captcha_message_ttl_seconds:
    - Через сколько секунд удалить сообщение Join Captcha из группы
    - NULL → дефолт 300 секунд (5 минут)

    invite_captcha_message_ttl_seconds:
    - Через сколько секунд удалить сообщение Invite Captcha из группы
    - NULL → дефолт 300 секунд (5 минут)
    """
    # Добавляем колонку для TTL сообщения Join Captcha
    op.add_column(
        'chat_settings',
        sa.Column('join_captcha_message_ttl_seconds', sa.Integer(), nullable=True)
    )

    # Добавляем колонку для TTL сообщения Invite Captcha
    op.add_column(
        'chat_settings',
        sa.Column('invite_captcha_message_ttl_seconds', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Удаляет колонки TTL сообщений капчи."""
    # Удаляем колонку TTL Invite Captcha
    op.drop_column('chat_settings', 'invite_captcha_message_ttl_seconds')
    # Удаляем колонку TTL Join Captcha
    op.drop_column('chat_settings', 'join_captcha_message_ttl_seconds')
