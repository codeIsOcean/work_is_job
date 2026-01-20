"""add_cross_message_detection

Добавляет колонки для детекции паттернов через множественные сообщения.

Кросс-сообщение детекция:
- cross_message_enabled — включить/выключить модуль
- cross_message_window_seconds — окно накопления скора (дефолт: 2 часа)
- cross_message_threshold — порог срабатывания (дефолт: 100 баллов)
- cross_message_action — действие при превышении (mute/ban/kick)

Логика работы:
1. Каждое сообщение проверяется через ContentFilter
2. Если скор < threshold раздела — сообщение пропускается
3. Но скор накапливается в Redis: cross_msg:{chat_id}:{user_id}
4. Когда накопленный скор >= cross_message_threshold — применяется действие

Это позволяет ловить спаммеров которые разбивают спам на несколько частей,
чтобы каждая часть по отдельности не превышала порог.

Revision ID: g3h4i5j6k7l8
Revises: f2g3h4i5j6k7
Create Date: 2026-01-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'g3h4i5j6k7l8'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'f2g3h4i5j6k7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавляет колонки для кросс-сообщение детекции."""

    # ═══════════════════════════════════════════════════════════
    # CROSS-MESSAGE DETECTION: ОСНОВНОЙ ПЕРЕКЛЮЧАТЕЛЬ
    # ═══════════════════════════════════════════════════════════
    # Включает/выключает накопление скора через несколько сообщений
    # По умолчанию выключен — админ должен явно включить
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_enabled',
            sa.Boolean(),
            server_default='false',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # CROSS-MESSAGE DETECTION: ВРЕМЕННОЕ ОКНО
    # ═══════════════════════════════════════════════════════════
    # За какое время накапливать скор (в секундах)
    # Дефолт: 7200 секунд = 2 часа
    # После истечения окна скор сбрасывается автоматически (TTL в Redis)
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_window_seconds',
            sa.Integer(),
            server_default='7200',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # CROSS-MESSAGE DETECTION: ПОРОГ СРАБАТЫВАНИЯ
    # ═══════════════════════════════════════════════════════════
    # Сколько накопленных баллов нужно для срабатывания
    # Дефолт: 100 баллов
    # Пример: 3 сообщения по 35 баллов = 105 → срабатывание
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_threshold',
            sa.Integer(),
            server_default='100',
            nullable=False
        )
    )

    # ═══════════════════════════════════════════════════════════
    # CROSS-MESSAGE DETECTION: ДЕЙСТВИЕ
    # ═══════════════════════════════════════════════════════════
    # Что делать когда накопленный скор превышает порог:
    # - "mute" = замутить (дефолт)
    # - "ban" = забанить
    # - "kick" = кикнуть
    # NULL = использовать default_action из ContentFilterSettings
    op.add_column(
        'content_filter_settings',
        sa.Column(
            'cross_message_action',
            sa.String(20),
            server_default='mute',
            nullable=True
        )
    )


def downgrade() -> None:
    """Удаляет колонки кросс-сообщение детекции."""

    # Удаляем колонки в обратном порядке
    op.drop_column('content_filter_settings', 'cross_message_action')
    op.drop_column('content_filter_settings', 'cross_message_threshold')
    op.drop_column('content_filter_settings', 'cross_message_window_seconds')
    op.drop_column('content_filter_settings', 'cross_message_enabled')