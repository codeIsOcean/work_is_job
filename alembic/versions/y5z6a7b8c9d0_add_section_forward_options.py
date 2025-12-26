"""Добавляет поля пересылки по действиям в custom_spam_sections

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2025-12-23

Добавляет в таблицу custom_spam_sections:
- forward_on_delete: пересылать в канал при действии "удалить"
- forward_on_mute: пересылать в канал при действии "мут"
- forward_on_ban: пересылать в канал при действии "бан"

Это позволяет включать пересылку независимо для каждого типа действия,
а не только для специального действия "forward_delete".
"""
# Импортируем op для операций с БД (добавление колонок)
from alembic import op
# Импортируем sa для определения типов данных колонок
import sqlalchemy as sa


# ─────────────────────────────────────────────────────────
# МЕТАДАННЫЕ МИГРАЦИИ
# ─────────────────────────────────────────────────────────
# Уникальный идентификатор этой миграции
revision = 'y5z6a7b8c9d0'
# Предыдущая миграция от которой зависит эта
down_revision = 'x4y5z6a7b8c9'
# Метки веток (не используем)
branch_labels = None
# Зависимости от других миграций (не используем)
depends_on = None


def upgrade() -> None:
    """
    Применяет миграцию: добавляет колонки пересылки по действиям.

    Эта функция вызывается при alembic upgrade head.
    """

    # ─────────────────────────────────────────────────────────
    # ДОБАВЛЯЕМ КОЛОНКУ forward_on_delete
    # ─────────────────────────────────────────────────────────
    # Если True - пересылать сообщение в канал при действии "удалить"
    # По умолчанию False - не пересылать
    op.add_column(
        'custom_spam_sections',
        sa.Column(
            'forward_on_delete',
            sa.Boolean(),
            nullable=False,
            server_default='false'
        )
    )

    # ─────────────────────────────────────────────────────────
    # ДОБАВЛЯЕМ КОЛОНКУ forward_on_mute
    # ─────────────────────────────────────────────────────────
    # Если True - пересылать сообщение в канал при действии "мут"
    # По умолчанию False - не пересылать
    op.add_column(
        'custom_spam_sections',
        sa.Column(
            'forward_on_mute',
            sa.Boolean(),
            nullable=False,
            server_default='false'
        )
    )

    # ─────────────────────────────────────────────────────────
    # ДОБАВЛЯЕМ КОЛОНКУ forward_on_ban
    # ─────────────────────────────────────────────────────────
    # Если True - пересылать сообщение в канал при действии "бан"
    # По умолчанию False - не пересылать
    op.add_column(
        'custom_spam_sections',
        sa.Column(
            'forward_on_ban',
            sa.Boolean(),
            nullable=False,
            server_default='false'
        )
    )


def downgrade() -> None:
    """
    Откатывает миграцию: удаляет колонки пересылки.

    Эта функция вызывается при alembic downgrade.
    """

    # ─────────────────────────────────────────────────────────
    # УДАЛЯЕМ КОЛОНКИ В ОБРАТНОМ ПОРЯДКЕ
    # ─────────────────────────────────────────────────────────
    # Удаляем forward_on_ban
    op.drop_column('custom_spam_sections', 'forward_on_ban')
    # Удаляем forward_on_mute
    op.drop_column('custom_spam_sections', 'forward_on_mute')
    # Удаляем forward_on_delete
    op.drop_column('custom_spam_sections', 'forward_on_delete')
