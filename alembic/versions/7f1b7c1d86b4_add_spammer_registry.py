"""add spammers registry

Revision ID: 7f1b7c1d86b4
Revises: c3c51f8c0c5e_extend_captcha_settings
Create Date: 2025-11-14 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f1b7c1d86b4"
down_revision: Union[str, None] = "c3c51f8c0c5e_extend_captcha_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spammers",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("incidents", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_incident_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_spammers_last_incident", "spammers", ["last_incident_at"])


def downgrade() -> None:
    op.drop_index("ix_spammers_last_incident", table_name="spammers")
    op.drop_table("spammers")

