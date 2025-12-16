"""add captcha_reminder_count column

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2025-12-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's9t0u1v2w3x4'
down_revision: Union[str, None] = 'r8s9t0u1v2w3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет колонку captcha_reminder_count в chat_settings.

    Количество напоминаний о капче:
    - NULL → дефолт 3
    - 0 → безлимит (до таймаута)
    - N → максимум N напоминаний
    """
    op.add_column(
        'chat_settings',
        sa.Column('captcha_reminder_count', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Удаляет колонку captcha_reminder_count."""
    op.drop_column('chat_settings', 'captcha_reminder_count')
