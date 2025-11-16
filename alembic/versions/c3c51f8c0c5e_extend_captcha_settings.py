"""extend captcha and notification settings

Revision ID: c3c51f8c0c5e
Revises: 7c3b1d3a4c2b_add_reaction_mute_tables
Create Date: 2025-11-13 10:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3c51f8c0c5e"
down_revision: Union[str, None] = "7c3b1d3a4c2b_add_reaction_mute_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_settings",
        sa.Column("captcha_join_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_invite_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_message_ttl_seconds", sa.Integer(), nullable=False, server_default="900"),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_flood_threshold", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_flood_window_seconds", sa.Integer(), nullable=False, server_default="180"),
    )
    op.add_column(
        "chat_settings",
        sa.Column("captcha_flood_action", sa.String(length=16), nullable=False, server_default="warn"),
    )
    op.add_column(
        "chat_settings",
        sa.Column("system_mute_announcements_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )

    for column in (
        "captcha_join_enabled",
        "captcha_invite_enabled",
        "captcha_timeout_seconds",
        "captcha_message_ttl_seconds",
        "captcha_flood_threshold",
        "captcha_flood_window_seconds",
        "captcha_flood_action",
        "system_mute_announcements_enabled",
    ):
        op.alter_column("chat_settings", column, server_default=None)


def downgrade() -> None:
    op.drop_column("chat_settings", "system_mute_announcements_enabled")
    op.drop_column("chat_settings", "captcha_flood_action")
    op.drop_column("chat_settings", "captcha_flood_window_seconds")
    op.drop_column("chat_settings", "captcha_flood_threshold")
    op.drop_column("chat_settings", "captcha_message_ttl_seconds")
    op.drop_column("chat_settings", "captcha_timeout_seconds")
    op.drop_column("chat_settings", "captcha_invite_enabled")
    op.drop_column("chat_settings", "captcha_join_enabled")
