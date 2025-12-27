"""add flood_delete_messages column

Revision ID: 419235295cd9
Revises: z6a7b8c9d0e1
Create Date: 2025-12-28 01:59:17.180587

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '419235295cd9'
down_revision: Union[str, None] = 'z6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет колонку flood_delete_messages в content_filter_settings.

    Эта колонка определяет, удалять ли флуд-сообщения нарушителя:
    - True (default) = удалять все сообщения флуда
    - False = не удалять, только применить действие (мут/бан/warn)
    """
    # Добавляем колонку с server_default для существующих записей
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'flood_delete_messages',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true')
        )
    )


def downgrade() -> None:
    """Откат: удаляем колонку flood_delete_messages."""
    op.drop_column('content_filter_settings', 'flood_delete_messages')
