"""add_user_restrictions_columns

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2025-12-13

Добавляет новые колонки в таблицу user_restrictions для сохранения мутов.
Позволяет восстанавливать ограничения после повторного входа через капчу.
"""

from alembic import op
import sqlalchemy as sa


revision = 'n4o5p6q7r8s9'
down_revision = 'm3n4o5p6q7r8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет новые колонки в user_restrictions."""
    # Добавляем колонку restricted_by (ID бота или админа)
    op.add_column(
        'user_restrictions',
        sa.Column(
            'restricted_by',
            sa.BigInteger(),
            nullable=True,
            comment='ID бота или админа, применившего ограничение'
        )
    )

    # Добавляем колонку until_date (дата окончания)
    op.add_column(
        'user_restrictions',
        sa.Column(
            'until_date',
            sa.DateTime(),
            nullable=True,
            comment='Дата окончания (NULL = бессрочно)'
        )
    )

    # Добавляем колонку is_active
    op.add_column(
        'user_restrictions',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Активно ли ограничение'
        )
    )

    # Добавляем колонку created_at
    op.add_column(
        'user_restrictions',
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=True,
            comment='Дата создания'
        )
    )

    # Добавляем колонку updated_at
    op.add_column(
        'user_restrictions',
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=True,
            comment='Дата обновления'
        )
    )

    # Создаём индекс для фильтрации по is_active
    op.create_index(
        'ix_user_restrictions_active',
        'user_restrictions',
        ['is_active'],
        unique=False
    )


def downgrade() -> None:
    """Удаляет добавленные колонки."""
    op.drop_index('ix_user_restrictions_active', table_name='user_restrictions')
    op.drop_column('user_restrictions', 'updated_at')
    op.drop_column('user_restrictions', 'created_at')
    op.drop_column('user_restrictions', 'is_active')
    op.drop_column('user_restrictions', 'until_date')
    op.drop_column('user_restrictions', 'restricted_by')
