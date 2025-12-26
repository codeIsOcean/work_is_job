"""add base signal overrides

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2025-12-23

Добавляет таблицу base_signal_overrides для переопределения
базовых SCAM_SIGNALS на уровне группы (убираем хардкод).

Позволяет для каждой группы:
- Включить/выключить отдельные базовые сигналы
- Изменить вес (score) для сигналов
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'z6a7b8c9d0e1'
down_revision = 'y6z7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём таблицу переопределений базовых сигналов
    op.create_table(
        'base_signal_overrides',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('signal_name', sa.String(50), nullable=False),
        sa.Column('weight_override', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ['chat_id'],
            ['groups.chat_id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_id', 'signal_name', name='uq_chat_signal')
    )

    # Индекс для быстрого поиска настроек группы
    op.create_index(
        'ix_base_signal_overrides_chat',
        'base_signal_overrides',
        ['chat_id']
    )


def downgrade() -> None:
    # Удаляем индекс
    op.drop_index('ix_base_signal_overrides_chat', table_name='base_signal_overrides')

    # Удаляем таблицу
    op.drop_table('base_signal_overrides')
