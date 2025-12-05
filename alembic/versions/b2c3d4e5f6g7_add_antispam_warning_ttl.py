"""add_antispam_warning_ttl

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-05 00:00:00.000000

Добавляет настройку времени жизни предупреждений антиспам.
"""
# Импорт типов для аннотаций
from typing import Sequence, Union

# Импорт операций Alembic для миграций
from alembic import op
# Импорт типов данных SQLAlchemy
import sqlalchemy as sa


# Идентификаторы ревизий, используемые Alembic
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить колонку antispam_warning_ttl_seconds в chat_settings."""
    op.add_column(
        "chat_settings",
        sa.Column(
            "antispam_warning_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0"
        ),
    )
    # Убираем server_default после создания
    op.alter_column(
        "chat_settings",
        "antispam_warning_ttl_seconds",
        server_default=None
    )


def downgrade() -> None:
    """Удалить колонку antispam_warning_ttl_seconds из chat_settings."""
    op.drop_column("chat_settings", "antispam_warning_ttl_seconds")
