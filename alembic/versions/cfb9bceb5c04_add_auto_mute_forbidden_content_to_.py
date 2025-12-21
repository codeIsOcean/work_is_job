"""add auto_mute_forbidden_content to profile_monitor

Revision ID: cfb9bceb5c04
Revises: v2w3x4y5z6a7
Create Date: 2025-12-21 17:52:26.276089

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfb9bceb5c04'
down_revision: Union[str, None] = 'v2w3x4y5z6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавляет поле auto_mute_forbidden_content в profile_monitor_settings.

    Критерий 6: Проверка имени и bio на запрещённый контент из ContentFilter.
    Использует WordFilter с категориями: harmful (наркотики), obfuscated (l33tspeak).
    Мутит СРАЗУ при обнаружении, не ждёт сообщения.
    """
    op.add_column(
        'profile_monitor_settings',
        sa.Column(
            'auto_mute_forbidden_content',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment='Критерий 6: мут за запрещённый контент в имени/bio'
        )
    )


def downgrade() -> None:
    """Удаляет поле auto_mute_forbidden_content."""
    op.drop_column('profile_monitor_settings', 'auto_mute_forbidden_content')
