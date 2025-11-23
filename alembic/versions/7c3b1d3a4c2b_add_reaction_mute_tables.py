"""add reaction mute tables and settings

Revision ID: 7c3b1d3a4c2b
Revises: df251fa0997f_add_global_mute_enabled
Create Date: 2025-11-13 02:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c3b1d3a4c2b"
down_revision: Union[str, None] = "df251fa0997f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_mutes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("target_user_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("reaction", sa.String(length=16), nullable=False),
        sa.Column("mute_until", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "user_scores",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "chat_settings",
        sa.Column(
            "reaction_mute_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column(
        "chat_settings",
        "reaction_mute_enabled",
        server_default=None,
    )
    op.add_column(
        "chat_settings",
        sa.Column(
            "reaction_mute_announce_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.alter_column(
        "chat_settings",
        "reaction_mute_announce_enabled",
        server_default=None,
    )

    op.create_index("ix_group_mutes_group_id", "group_mutes", ["group_id"])
    op.create_index("ix_group_mutes_target_user_id", "group_mutes", ["target_user_id"])
    op.create_index("ix_group_mutes_admin_user_id", "group_mutes", ["admin_user_id"])


def downgrade() -> None:
    op.drop_index("ix_group_mutes_admin_user_id", table_name="group_mutes")
    op.drop_index("ix_group_mutes_target_user_id", table_name="group_mutes")
    op.drop_index("ix_group_mutes_group_id", table_name="group_mutes")
    op.drop_column("chat_settings", "reaction_mute_announce_enabled")
    op.drop_column("chat_settings", "reaction_mute_enabled")
    op.drop_table("user_scores")
    op.drop_table("group_mutes")

