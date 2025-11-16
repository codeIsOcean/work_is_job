"""add username to chat_settings

Revision ID: 2f852e70babb
Revises: 7f1b7c1d86b4
Create Date: 2025-11-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2f852e70babb"
down_revision: Union[str, None] = "7f1b7c1d86b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chat_settings", sa.Column("username", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chat_settings", "username")
