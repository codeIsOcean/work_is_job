"""Ensure username column exists on chat_settings

Revision ID: 3e9d3ae1b123
Revises: add_journal_channels
Create Date: 2025-11-23 00:00:00.000000

This migration is defensive: in some environments the earlier
2f852e70babb_add_username_to_chat_settings revision may not have been
applied before the DB reached the current head. To avoid runtime
"column chat_settings.username does not exist" errors, we check for the
column at runtime and add it if missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3e9d3ae1b123"
down_revision: Union[str, None] = "add_journal_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add username column to chat_settings if it does not exist."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {col["name"] for col in insp.get_columns("chat_settings")}

    if "username" not in columns:
        op.add_column("chat_settings", sa.Column("username", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop username column if it exists.

    This keeps downgrade safe on DBs where the column was never created
    by this migration.
    """
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {col["name"] for col in insp.get_columns("chat_settings")}

    if "username" in columns:
        op.drop_column("chat_settings", "username")
