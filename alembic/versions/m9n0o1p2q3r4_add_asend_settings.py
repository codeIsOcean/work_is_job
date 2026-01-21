"""add_asend_settings

Добавляет настройки для команды /asend:
- send_delete_command: удалять ли команду после отправки

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm9n0o1p2q3r4'
down_revision: Union[str, None] = 'l8m9n0o1p2q3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет настройки команды /asend.
    """
    # Удалять ли команду /asend после отправки (по умолчанию — да)
    op.add_column(
        'manual_command_settings',
        sa.Column('send_delete_command', sa.Boolean(), server_default='true', nullable=False)
    )

    print("[OK] Added send_delete_command column to manual_command_settings")


def downgrade() -> None:
    """
    Откатывает миграцию — удаляет настройки /asend.
    """
    op.drop_column('manual_command_settings', 'send_delete_command')

    print("[ROLLBACK] Removed send_delete_command from manual_command_settings")
