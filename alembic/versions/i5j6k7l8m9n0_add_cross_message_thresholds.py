"""add_cross_message_thresholds

Создаёт таблицу порогов баллов для кросс-сообщение детекции.

Позволяет задать разные действия для разных диапазонов накопленного скора:
- 100-149 баллов → мут 30 минут
- 150-199 баллов → мут 2 часа
- 200-299 баллов → мут 24 часа
- 300+ баллов → бан

Аналог CustomSectionThreshold, но привязан к группе (chat_id), а не к разделу.

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'i5j6k7l8m9n0'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'h4i5j6k7l8m9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт таблицу cross_message_thresholds."""

    # ═══════════════════════════════════════════════════════════
    # ТАБЛИЦА: ПОРОГИ БАЛЛОВ КРОСС-СООБЩЕНИЕ ДЕТЕКЦИИ
    # ═══════════════════════════════════════════════════════════
    # Позволяет задать разные действия для разных диапазонов скора.
    # Если порог не найден — используется cross_message_action из ContentFilterSettings.
    op.create_table(
        'cross_message_thresholds',

        # ───────────────────────────────────────────────────────
        # PRIMARY KEY: Автоинкрементный ID
        # ───────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),

        # ───────────────────────────────────────────────────────
        # FOREIGN KEY: ID группы
        # ───────────────────────────────────────────────────────
        # Каждая группа имеет свой независимый набор порогов
        # ondelete=CASCADE — при удалении группы удаляются и пороги
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
            nullable=False,
            index=True
        ),

        # ───────────────────────────────────────────────────────
        # ДИАПАЗОН БАЛЛОВ
        # ───────────────────────────────────────────────────────
        # Минимальный порог (включительно): score >= min_score
        sa.Column('min_score', sa.Integer(), nullable=False),

        # Максимальный порог (включительно): score <= max_score
        # NULL = без верхнего ограничения (∞)
        sa.Column('max_score', sa.Integer(), nullable=True),

        # ───────────────────────────────────────────────────────
        # ДЕЙСТВИЕ ПРИ СРАБАТЫВАНИИ
        # ───────────────────────────────────────────────────────
        # mute = замутить на mute_duration минут
        # kick = кикнуть (можно вернуться)
        # ban = забанить навсегда
        sa.Column(
            'action',
            sa.String(20),
            server_default='mute',
            nullable=False
        ),

        # Длительность мута в минутах (только для action='mute')
        # NULL = использовать default_mute_duration из ContentFilterSettings
        sa.Column('mute_duration', sa.Integer(), nullable=True),

        # ───────────────────────────────────────────────────────
        # АКТИВНОСТЬ ПОРОГА
        # ───────────────────────────────────────────────────────
        # True = порог активен, False = временно отключён
        sa.Column(
            'enabled',
            sa.Boolean(),
            server_default='true',
            nullable=False
        ),

        # ───────────────────────────────────────────────────────
        # ПРИОРИТЕТ ПОРОГА
        # ───────────────────────────────────────────────────────
        # Порядок проверки (меньше = раньше)
        # Если несколько порогов подходят — выбирается с меньшим priority
        sa.Column(
            'priority',
            sa.Integer(),
            server_default='0',
            nullable=False
        ),

        # ───────────────────────────────────────────────────────
        # МЕТАДАННЫЕ
        # ───────────────────────────────────────────────────────
        # Описание порога для UI (опционально)
        sa.Column('description', sa.String(200), nullable=True),

        # Дата создания
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False
        ),

        # Дата последнего обновления
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False
        ),

        # ID админа который создал порог
        sa.Column('created_by', sa.BigInteger(), nullable=True),
    )

    # ═══════════════════════════════════════════════════════════
    # ИНДЕКС: для быстрого поиска активных порогов группы
    # ═══════════════════════════════════════════════════════════
    # Ускоряет: SELECT * FROM cross_message_thresholds
    #           WHERE chat_id=X AND enabled=True
    #           ORDER BY priority
    op.create_index(
        'ix_cross_msg_thresholds_chat_enabled',
        'cross_message_thresholds',
        ['chat_id', 'enabled']
    )


def downgrade() -> None:
    """Удаляет таблицу cross_message_thresholds."""

    # Удаляем индекс
    op.drop_index('ix_cross_msg_thresholds_chat_enabled', 'cross_message_thresholds')

    # Удаляем таблицу
    op.drop_table('cross_message_thresholds')
