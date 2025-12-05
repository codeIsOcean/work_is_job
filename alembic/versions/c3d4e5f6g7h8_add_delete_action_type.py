"""add_delete_action_type

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-12-05 03:35:00.000000

Добавляет значение DELETE в enum action_type_enum.
"""
from typing import Sequence, Union

from alembic import op


# Идентификаторы ревизий
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить значение DELETE в enum action_type_enum."""
    # PostgreSQL позволяет добавлять новые значения в enum через ALTER TYPE
    op.execute("ALTER TYPE action_type_enum ADD VALUE IF NOT EXISTS 'DELETE'")


def downgrade() -> None:
    """
    Удаление значения из enum в PostgreSQL невозможно напрямую.
    Нужно было бы пересоздавать enum, что сложно.
    Поэтому downgrade просто предупреждает.
    """
    # PostgreSQL не поддерживает удаление значений из enum
    # Для полного отката нужно:
    # 1. Создать новый enum без DELETE
    # 2. Обновить все записи с DELETE на другое значение
    # 3. Изменить колонку на новый enum
    # 4. Удалить старый enum
    pass
