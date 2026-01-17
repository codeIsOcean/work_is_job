"""antiraid_v2_redesign

Редизайн модуля Anti-Raid v2:

Mass Join:
- Добавлен mass_join_protection_duration — время режима защиты (сек)
- Добавлен mass_join_ban_duration — длительность бана (0 = навсегда)
- Изменён дефолт mass_join_action на 'ban' (было 'slowmode')

Mass Reaction:
- Удалены mass_reaction_threshold_user и mass_reaction_threshold_msg
- Добавлен mass_reaction_threshold — порог разных сообщений
- Добавлен mass_reaction_ban_duration — длительность бана (0 = навсегда)

Новая логика:
- Mass Join: при рейде включается "режим защиты", все новые вступления = бан
- Mass Reaction: считаем на сколько РАЗНЫХ сообщений юзер поставил реакции

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-01-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'f2g3h4i5j6k7'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'e1f2g3h4i5j6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменения Anti-Raid v2."""

    # ═══════════════════════════════════════════════════════════
    # MASS JOIN: ДОБАВЛЯЕМ НОВЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════

    # Длительность режима защиты в секундах
    # После детекции рейда все новые вступления банятся в течение этого времени
    # Дефолт: 180 секунд (3 минуты)
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_join_protection_duration',
            sa.Integer(),
            server_default='180',
            nullable=False
        )
    )

    # Длительность бана при рейде в часах (0 = навсегда)
    # Дефолт: 0 (перманентный бан для рейдеров)
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_join_ban_duration',
            sa.Integer(),
            server_default='0',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # MASS JOIN: МЕНЯЕМ ДЕФОЛТ ACTION НА 'ban'
    # ═══════════════════════════════════════════════════════════
    # Старый дефолт был 'slowmode' — теперь 'ban'
    # Это влияет только на НОВЫЕ записи, существующие сохранят своё значение
    op.alter_column(
        'antiraid_settings',
        'mass_join_action',
        server_default='ban'
    )

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: УДАЛЯЕМ СТАРЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════
    # Старая логика: threshold_user (реакций от юзера) + threshold_msg (реакций на сообщение)
    # Новая логика: threshold (на сколько РАЗНЫХ сообщений юзер поставил реакции)

    # Удаляем колонку порога реакций от одного юзера
    op.drop_column('antiraid_settings', 'mass_reaction_threshold_user')

    # Удаляем колонку порога реакций на одно сообщение
    op.drop_column('antiraid_settings', 'mass_reaction_threshold_msg')

    # Удаляем колонку длительности мута (заменена на ban_duration)
    op.drop_column('antiraid_settings', 'mass_reaction_mute_duration')

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: ДОБАВЛЯЕМ НОВЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════

    # Порог срабатывания — на сколько РАЗНЫХ сообщений за окно
    # Паттерн спаммера: ставит по 1 реакции на разные сообщения (идёт вниз по чату)
    # Дефолт: 5 разных сообщений за окно = спам реакциями
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_reaction_threshold',
            sa.Integer(),
            server_default='5',
            nullable=False
        )
    )

    # Длительность бана в часах (для action='ban', 0 = навсегда)
    # Дефолт: 0 (перманентный бан для спаммеров реакциями)
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_reaction_ban_duration',
            sa.Integer(),
            server_default='0',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: МЕНЯЕМ ДЕФОЛТ ACTION НА 'ban'
    # ═══════════════════════════════════════════════════════════
    # Старый дефолт был 'mute' — теперь 'ban'
    # Спам реакциями = бан, не просто мут
    op.alter_column(
        'antiraid_settings',
        'mass_reaction_action',
        server_default='ban'
    )


def downgrade() -> None:
    """Откатывает изменения Anti-Raid v2."""

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: ВОССТАНАВЛИВАЕМ СТАРЫЙ ДЕФОЛТ
    # ═══════════════════════════════════════════════════════════
    op.alter_column(
        'antiraid_settings',
        'mass_reaction_action',
        server_default='mute'
    )

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: УДАЛЯЕМ НОВЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════
    op.drop_column('antiraid_settings', 'mass_reaction_ban_duration')
    op.drop_column('antiraid_settings', 'mass_reaction_threshold')

    # ═══════════════════════════════════════════════════════════
    # MASS REACTION: ВОССТАНАВЛИВАЕМ СТАРЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_reaction_threshold_msg',
            sa.Integer(),
            server_default='20',
            nullable=False
        )
    )

    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_reaction_threshold_user',
            sa.Integer(),
            server_default='10',
            nullable=False
        )
    )

    # Восстанавливаем колонку длительности мута
    op.add_column(
        'antiraid_settings',
        sa.Column(
            'mass_reaction_mute_duration',
            sa.Integer(),
            server_default='60',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # MASS JOIN: ВОССТАНАВЛИВАЕМ СТАРЫЙ ДЕФОЛТ
    # ═══════════════════════════════════════════════════════════
    op.alter_column(
        'antiraid_settings',
        'mass_join_action',
        server_default='slowmode'
    )

    # ═══════════════════════════════════════════════════════════
    # MASS JOIN: УДАЛЯЕМ НОВЫЕ КОЛОНКИ
    # ═══════════════════════════════════════════════════════════
    op.drop_column('antiraid_settings', 'mass_join_ban_duration')
    op.drop_column('antiraid_settings', 'mass_join_protection_duration')