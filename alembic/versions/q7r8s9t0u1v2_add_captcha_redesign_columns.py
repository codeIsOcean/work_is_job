"""add captcha redesign columns

Добавляет новые колонки для редизайна системы капчи:
- visual_captcha_enabled: включение Visual Captcha (в ЛС)
- visual_captcha_timeout_seconds: таймаут для Visual Captcha
- join_captcha_timeout_seconds: таймаут для Join Captcha (группа)
- invite_captcha_timeout_seconds: таймаут для Invite Captcha (группа)
- captcha_max_pending: макс. кол-во одновременных капч
- captcha_overflow_action: действие при переполнении

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2025-12-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизий для Alembic
revision: str = "q7r8s9t0u1v2"
# Указываем предыдущую миграцию в цепочке
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет новые колонки для трёх режимов капчи.

    Архитектура капчи после редизайна:
    1. Visual Captcha (ЛС) - visual_captcha_enabled
    2. Join Captcha (группа) - captcha_join_enabled (уже есть)
    3. Invite Captcha (группа) - captcha_invite_enabled (уже есть)
    """

    # ═══════════════════════════════════════════════════════════════════════
    # visual_captcha_enabled - включает Visual Captcha (капча в ЛС)
    # Консолидирует логику из CaptchaSettings.is_visual_enabled в ChatSettings
    # NULL означает что админ ещё не настроил (без дефолта по правилу 22)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "visual_captcha_enabled",
            sa.Boolean(),
            nullable=True,  # NULL = не настроено
            server_default=None,
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # visual_captcha_timeout_seconds - таймаут для Visual Captcha (ЛС)
    # Сколько секунд пользователь может решать капчу в ЛС
    # NULL = админ должен настроить при включении
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "visual_captcha_timeout_seconds",
            sa.Integer(),
            nullable=True,  # NULL = не настроено
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # join_captcha_timeout_seconds - таймаут для Join Captcha (группа)
    # Сколько секунд пользователь может решать капчу в группе при входе
    # NULL = админ должен настроить при включении
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "join_captcha_timeout_seconds",
            sa.Integer(),
            nullable=True,  # NULL = не настроено
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # invite_captcha_timeout_seconds - таймаут для Invite Captcha (группа)
    # Сколько секунд пользователь может решать капчу когда его пригласили
    # NULL = админ должен настроить при включении
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "invite_captcha_timeout_seconds",
            sa.Integer(),
            nullable=True,  # NULL = не настроено
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_max_pending - максимум одновременных капч в группе
    # Предотвращает накопление капч при массовом входе
    # NULL = админ должен настроить при включении капчи
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_max_pending",
            sa.Integer(),
            nullable=True,  # NULL = не настроено
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_overflow_action - действие при превышении лимита капч
    # Варианты: "remove_oldest" | "auto_decline" | "queue"
    # NULL = админ выберет при настройке
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_overflow_action",
            sa.String(length=32),
            nullable=True,  # NULL = не настроено
        ),
    )


def downgrade() -> None:
    """
    Откатывает миграцию - удаляет добавленные колонки.
    Порядок удаления обратный порядку добавления.
    """

    # Удаляем колонки в обратном порядке
    op.drop_column("chat_settings", "captcha_overflow_action")
    op.drop_column("chat_settings", "captcha_max_pending")
    op.drop_column("chat_settings", "invite_captcha_timeout_seconds")
    op.drop_column("chat_settings", "join_captcha_timeout_seconds")
    op.drop_column("chat_settings", "visual_captcha_timeout_seconds")
    op.drop_column("chat_settings", "visual_captcha_enabled")
