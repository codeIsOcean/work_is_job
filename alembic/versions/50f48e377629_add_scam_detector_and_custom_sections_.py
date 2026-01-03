"""add_scam_detector_and_custom_sections_flags

Добавляет два флага в content_filter_settings:
- scam_detector_enabled: включить/выключить общий scam_detector
- custom_sections_enabled: включить/выключить кастомные разделы

Revision ID: 50f48e377629
Revises: b8c9d0e1f2g3
Create Date: 2026-01-03 23:53:29.944171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50f48e377629'
down_revision: Union[str, None] = 'b8c9d0e1f2g3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем флаг для общего scam_detector
    op.add_column(
        'content_filter_settings',
        sa.Column('scam_detector_enabled', sa.Boolean(), nullable=False, server_default='true')
    )

    # Добавляем флаг для кастомных разделов
    op.add_column(
        'content_filter_settings',
        sa.Column('custom_sections_enabled', sa.Boolean(), nullable=False, server_default='true')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_filter_settings', 'custom_sections_enabled')
    op.drop_column('content_filter_settings', 'scam_detector_enabled')
