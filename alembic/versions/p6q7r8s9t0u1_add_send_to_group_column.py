"""add_send_to_group_column

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2025-12-13

Добавляет колонку send_to_group в таблицу profile_monitor_settings.
Эта колонка позволяет отправлять простые уведомления в группу (для всех участников),
а не только в журнал (для админов).
"""

# Импортируем модуль операций Alembic
from alembic import op
# Импортируем SQLAlchemy для определения типов колонок
import sqlalchemy as sa


# Уникальный идентификатор этой миграции
revision = 'p6q7r8s9t0u1'
# Идентификатор предыдущей миграции (от которой зависит эта)
down_revision = 'o5p6q7r8s9t0'
# Метки веток (не используем)
branch_labels = None
# Зависимости (не используем)
depends_on = None


def upgrade() -> None:
    """
    Добавляет колонку send_to_group в таблицу profile_monitor_settings.

    Колонка позволяет включить отправку простых уведомлений
    об изменениях профиля прямо в группу (для всех участников).
    По умолчанию выключена (False).
    """

    # ─────────────────────────────────────────────────────────
    # Добавляем колонку send_to_group
    # ─────────────────────────────────────────────────────────
    # Boolean колонка с default=False
    # nullable=False - колонка обязательна
    # server_default='false' - значение по умолчанию на уровне БД
    op.add_column(
        'profile_monitor_settings',
        sa.Column(
            'send_to_group',
            sa.Boolean(),
            nullable=False,
            server_default='false'
        )
    )


def downgrade() -> None:
    """
    Откатывает миграцию - удаляет колонку send_to_group.
    """

    # ─────────────────────────────────────────────────────────
    # Удаляем колонку send_to_group
    # ─────────────────────────────────────────────────────────
    op.drop_column('profile_monitor_settings', 'send_to_group')
