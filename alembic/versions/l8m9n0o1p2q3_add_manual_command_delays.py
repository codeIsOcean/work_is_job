"""add_manual_command_delays

Добавляет поля задержки удаления сообщений для модуля ручных команд:
- mute_delete_delay: задержка удаления сообщения нарушителя (секунды)
- mute_notify_delete_delay: задержка удаления уведомления о муте
- ban_delete_delay, ban_notify_delete_delay: аналогично для бана
- kick_notify_text: кастомный текст уведомления о кике
- kick_delete_delay, kick_notify_delete_delay: аналогично для кика

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l8m9n0o1p2q3'
down_revision: Union[str, None] = 'k7l8m9n0o1p2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет поля задержки удаления для mute, ban, kick.
    """
    # ═══════════════════════════════════════════════
    # MUTE: задержки удаления
    # ═══════════════════════════════════════════════

    # Задержка удаления сообщения нарушителя (0 = сразу)
    op.add_column(
        'manual_command_settings',
        sa.Column('mute_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    # Задержка удаления уведомления о муте (0 = не удалять)
    op.add_column(
        'manual_command_settings',
        sa.Column('mute_notify_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    # ═══════════════════════════════════════════════
    # BAN: задержки удаления
    # ═══════════════════════════════════════════════

    # Задержка удаления сообщения нарушителя (0 = сразу)
    op.add_column(
        'manual_command_settings',
        sa.Column('ban_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    # Задержка удаления уведомления о бане (0 = не удалять)
    op.add_column(
        'manual_command_settings',
        sa.Column('ban_notify_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    # ═══════════════════════════════════════════════
    # KICK: кастомный текст + задержки удаления
    # ═══════════════════════════════════════════════

    # Кастомный текст уведомления о кике (было пропущено)
    op.add_column(
        'manual_command_settings',
        sa.Column('kick_notify_text', sa.String(500), nullable=True)
    )

    # Задержка удаления сообщения нарушителя (0 = сразу)
    op.add_column(
        'manual_command_settings',
        sa.Column('kick_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    # Задержка удаления уведомления о кике (0 = не удалять)
    op.add_column(
        'manual_command_settings',
        sa.Column('kick_notify_delete_delay', sa.Integer(), server_default='0', nullable=False)
    )

    print("[OK] Added delay columns to manual_command_settings")


def downgrade() -> None:
    """
    Откатывает миграцию — удаляет поля задержки.
    """
    # MUTE
    op.drop_column('manual_command_settings', 'mute_delete_delay')
    op.drop_column('manual_command_settings', 'mute_notify_delete_delay')

    # BAN
    op.drop_column('manual_command_settings', 'ban_delete_delay')
    op.drop_column('manual_command_settings', 'ban_notify_delete_delay')

    # KICK
    op.drop_column('manual_command_settings', 'kick_notify_text')
    op.drop_column('manual_command_settings', 'kick_delete_delay')
    op.drop_column('manual_command_settings', 'kick_notify_delete_delay')

    print("[ROLLBACK] Removed delay columns from manual_command_settings")
