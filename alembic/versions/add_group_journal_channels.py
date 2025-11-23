"""add_group_journal_channels

Revision ID: add_journal_channels
Revises: 2f852e70babb
Create Date: 2025-10-30 14:00:00.000000

Multi-tenant журнал действий: каждая группа может иметь свой канал для журнала.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import DateTime


# revision identifiers, used by Alembic.
revision: str = 'add_journal_channels'
down_revision: Union[str, None] = '2f852e70babb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Создаем таблицу для журнала действий групп
    op.create_table(
        'group_journal_channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.BigInteger(), nullable=False),
        sa.Column('journal_channel_id', sa.BigInteger(), nullable=False),
        sa.Column('journal_type', sa.String(20), nullable=True, server_default='channel'),
        sa.Column('journal_title', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('linked_at', sa.DateTime(), nullable=True),
        sa.Column('linked_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('last_event_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['groups.chat_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id'),
    )
    
    # Создаем индексы для производительности
    op.create_index('ix_group_journal_group_id', 'group_journal_channels', ['group_id'])
    op.create_index('ix_group_journal_channel_id', 'group_journal_channels', ['journal_channel_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_group_journal_channel_id', table_name='group_journal_channels')
    op.drop_index('ix_group_journal_group_id', table_name='group_journal_channels')
    op.drop_table('group_journal_channels')

