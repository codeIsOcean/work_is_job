"""add_bot_global_settings_table

Revision ID: 9356cadad695
Revises: t0u1v2w3x4y5
Create Date: 2025-12-18 03:02:32.142105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9356cadad695'
down_revision: Union[str, None] = 't0u1v2w3x4y5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаём таблицу bot_global_settings для хранения глобальных настроек бота."""
    op.create_table(
        'bot_global_settings',
        sa.Column('key', sa.String(100), primary_key=True, comment='Уникальный ключ настройки'),
        sa.Column('value', sa.Text(), nullable=False, comment='Значение настройки'),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            comment='Время последнего обновления'
        ),
    )

    # Вставляем начальное значение max_seen_user_id (декабрь 2025)
    op.execute("""
        INSERT INTO bot_global_settings (key, value)
        VALUES ('max_seen_user_id', '8600000000')
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    """Удаляем таблицу bot_global_settings."""
    op.drop_table('bot_global_settings')
