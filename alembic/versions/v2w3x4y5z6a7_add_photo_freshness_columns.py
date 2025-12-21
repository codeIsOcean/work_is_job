"""add_photo_freshness_columns

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2025-12-21

Добавляет колонки для отслеживания свежести фото:
- photo_freshness_threshold_days в profile_monitor_settings
- photo_age_days в profile_snapshots

Используется для критериев автомута 4 и 5:
- Критерий 4: Свежее фото + смена имени + сообщение ≤30 мин
- Критерий 5: Свежее фото + сообщение ≤30 мин
"""

# Импорты стандартные для миграций Alembic
from typing import Sequence, Union

# op - операции с БД (add_column, drop_column и т.д.)
from alembic import op

# sa - SQLAlchemy для определения типов колонок
import sqlalchemy as sa


# ============================================================
# ИДЕНТИФИКАТОРЫ РЕВИЗИИ
# ============================================================
# Уникальный ID этой миграции
revision: str = 'v2w3x4y5z6a7'

# ID предыдущей миграции (от которой зависит эта)
down_revision: Union[str, None] = 'u1v2w3x4y5z6'

# Метки веток (не используем)
branch_labels: Union[str, Sequence[str], None] = None

# Зависимости (не используем)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляем колонки для отслеживания свежести фото профиля.

    1. photo_freshness_threshold_days в profile_monitor_settings:
       - Порог свежести фото в днях (по умолчанию 1 день)
       - Если фото моложе этого порога → считается подозрительным

    2. photo_age_days в profile_snapshots:
       - Возраст самого свежего фото при входе (в днях)
       - Получаем через MTProto API
    """

    # ─────────────────────────────────────────────────────────
    # Добавляем photo_freshness_threshold_days в profile_monitor_settings
    # ─────────────────────────────────────────────────────────
    # Порог свежести фото в днях (default = 1)
    # Если текущее фото моложе этого порога → подозрительно
    op.add_column(
        'profile_monitor_settings',
        sa.Column(
            'photo_freshness_threshold_days',
            sa.Integer(),
            nullable=False,
            server_default='1',
            comment='Порог свежести фото в днях для критериев 4,5'
        )
    )

    # ─────────────────────────────────────────────────────────
    # Добавляем photo_age_days в profile_snapshots
    # ─────────────────────────────────────────────────────────
    # Возраст самого свежего фото при входе пользователя
    # NULL если фото нет или возраст не удалось получить
    op.add_column(
        'profile_snapshots',
        sa.Column(
            'photo_age_days',
            sa.Integer(),
            nullable=True,
            comment='Возраст фото в днях при входе (из MTProto)'
        )
    )


def downgrade() -> None:
    """
    Откат миграции: удаляем добавленные колонки.

    Порядок обратный upgrade.
    """

    # Удаляем photo_age_days из profile_snapshots
    op.drop_column('profile_snapshots', 'photo_age_days')

    # Удаляем photo_freshness_threshold_days из profile_monitor_settings
    op.drop_column('profile_monitor_settings', 'photo_freshness_threshold_days')
