"""add_check_profile_photo_filter

Добавляет колонку check_profile_photo_filter в profile_monitor_settings.
Эта настройка включает проверку фото профиля пользователя через
модуль Scam Media Filter (по хешу изображения).

Revision ID: c9d0e1f2g3h4
Revises: 50f48e377629
Create Date: 2026-01-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2g3h4'
down_revision: Union[str, None] = '50f48e377629'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade schema.

    Добавляет колонку check_profile_photo_filter в таблицу profile_monitor_settings.
    По умолчанию False — требует явного включения администратором.
    """
    # Добавляем колонку для проверки фото профиля через Scam Media Filter
    op.add_column(
        'profile_monitor_settings',
        sa.Column(
            'check_profile_photo_filter',
            sa.Boolean(),
            nullable=False,
            server_default='false'
        )
    )


def downgrade() -> None:
    """
    Downgrade schema.

    Удаляет колонку check_profile_photo_filter.
    """
    op.drop_column('profile_monitor_settings', 'check_profile_photo_filter')