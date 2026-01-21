"""add_cross_message_notification_fields

Добавляет поля для уведомлений кросс-сообщение детекции в ContentFilterSettings:
- cross_message_mute_text: текст уведомления при муте (%user%, %time%)
- cross_message_ban_text: текст уведомления при бане (%user%)
- cross_message_notification_delete_delay: автоудаление уведомления через N секунд

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'j6k7l8m9n0o1'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'i5j6k7l8m9n0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавляет поля уведомлений в content_filter_settings."""

    # ═══════════════════════════════════════════════════════════
    # Текст уведомления при муте кросс-сообщений
    # Плейсхолдеры: %user% = имя пользователя, %time% = длительность
    # ═══════════════════════════════════════════════════════════
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_mute_text',
            sa.String(500),
            nullable=True
        )
    )

    # ═══════════════════════════════════════════════════════════
    # Текст уведомления при бане кросс-сообщений
    # Плейсхолдеры: %user% = имя пользователя
    # ═══════════════════════════════════════════════════════════
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_ban_text',
            sa.String(500),
            nullable=True
        )
    )

    # ═══════════════════════════════════════════════════════════
    # Задержка автоудаления уведомления в секундах
    # NULL = не удалять автоматически
    # ═══════════════════════════════════════════════════════════
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_notification_delete_delay',
            sa.Integer(),
            nullable=True
        )
    )


def downgrade() -> None:
    """Удаляет поля уведомлений из content_filter_settings."""

    op.drop_column('content_filter_settings', 'cross_message_notification_delete_delay')
    op.drop_column('content_filter_settings', 'cross_message_ban_text')
    op.drop_column('content_filter_settings', 'cross_message_mute_text')
