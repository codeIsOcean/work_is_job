"""add_manual_command_settings

Создаёт таблицу manual_command_settings для хранения настроек
модуля ручных команд модерации (/amute, /aban, /akick).

Каждая группа имеет свои независимые настройки:
- mute_delete_message: удалять ли сообщение при муте
- mute_notify_group: уведомление в группу при муте
- mute_default_duration: время мута по умолчанию (минуты)
- mute_notify_text: кастомный текст уведомления
- ban_*: аналогичные настройки для /aban
- kick_*: аналогичные настройки для /akick

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'k7l8m9n0o1p2'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'j6k7l8m9n0o1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Создаёт таблицу manual_command_settings.

    Таблица хранит настройки команд /amute, /aban, /akick для каждой группы.
    """
    # Создаём таблицу manual_command_settings
    op.create_table(
        'manual_command_settings',

        # ─── PRIMARY KEY ───
        # Уникальный идентификатор записи
        sa.Column('id', sa.Integer(), primary_key=True),

        # ─── CHAT_ID ───
        # Идентификатор группы (уникальный — одна запись на группу)
        sa.Column('chat_id', sa.BigInteger(), nullable=False, unique=True, index=True),

        # ═══════════════════════════════════════════════
        # НАСТРОЙКИ /amute
        # ═══════════════════════════════════════════════

        # Удалять ли сообщение нарушителя при муте
        sa.Column('mute_delete_message', sa.Boolean(), server_default='true', nullable=False),

        # Отправлять ли уведомление в группу при муте
        sa.Column('mute_notify_group', sa.Boolean(), server_default='true', nullable=False),

        # Время мута по умолчанию в минутах (1440 = 24 часа)
        # 0 = навсегда
        sa.Column('mute_default_duration', sa.Integer(), server_default='1440', nullable=False),

        # Кастомный текст уведомления о муте
        # Переменные: %user%, %time%, %reason%, %admin%
        sa.Column('mute_notify_text', sa.String(500), nullable=True),

        # ═══════════════════════════════════════════════
        # НАСТРОЙКИ /aban
        # ═══════════════════════════════════════════════

        # Удалять ли сообщение нарушителя при бане
        sa.Column('ban_delete_message', sa.Boolean(), server_default='true', nullable=False),

        # Удалять ли ВСЕ сообщения нарушителя (за последние 48ч)
        sa.Column('ban_delete_all_messages', sa.Boolean(), server_default='false', nullable=False),

        # Отправлять ли уведомление в группу при бане
        sa.Column('ban_notify_group', sa.Boolean(), server_default='true', nullable=False),

        # Кастомный текст уведомления о бане
        # Переменные: %user%, %reason%, %admin%
        sa.Column('ban_notify_text', sa.String(500), nullable=True),

        # ═══════════════════════════════════════════════
        # НАСТРОЙКИ /akick
        # ═══════════════════════════════════════════════

        # Удалять ли сообщение нарушителя при кике
        sa.Column('kick_delete_message', sa.Boolean(), server_default='true', nullable=False),

        # Отправлять ли уведомление в группу при кике
        sa.Column('kick_notify_group', sa.Boolean(), server_default='true', nullable=False),
    )

    # Логирование
    print("[OK] Created table manual_command_settings")


def downgrade() -> None:
    """
    Откатывает миграцию — удаляет таблицу manual_command_settings.
    """
    # Удаляем таблицу
    op.drop_table('manual_command_settings')

    # Логирование
    print("[ROLLBACK] Dropped table manual_command_settings")
