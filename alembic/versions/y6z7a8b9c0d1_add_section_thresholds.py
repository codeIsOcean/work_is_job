"""add custom section thresholds

Revision ID: y6z7a8b9c0d1
Revises: y5z6a7b8c9d0
Create Date: 2025-12-23

Добавляет таблицу custom_section_thresholds для хранения
порогов баллов категорий сигналов.

Позволяет задать разные действия для разных диапазонов скора:
- 100-199 баллов → удалить
- 200-299 баллов → мут
- 300+ баллов → бан
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'y6z7a8b9c0d1'
down_revision = 'y5z6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём таблицу порогов для кастомных разделов
    op.create_table(
        'custom_section_thresholds',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=False),
        sa.Column('min_score', sa.Integer(), nullable=False),
        sa.Column('max_score', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(20), server_default='delete', nullable=False),
        sa.Column('mute_duration', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ['section_id'],
            ['custom_spam_sections.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )

    # Создаём индекс для быстрого поиска активных порогов раздела
    op.create_index(
        'ix_section_thresholds_section_enabled',
        'custom_section_thresholds',
        ['section_id', 'enabled']
    )

    # Создаём индекс по section_id
    op.create_index(
        'ix_custom_section_thresholds_section_id',
        'custom_section_thresholds',
        ['section_id']
    )


def downgrade() -> None:
    # Удаляем индексы
    op.drop_index('ix_custom_section_thresholds_section_id', table_name='custom_section_thresholds')
    op.drop_index('ix_section_thresholds_section_enabled', table_name='custom_section_thresholds')

    # Удаляем таблицу
    op.drop_table('custom_section_thresholds')
