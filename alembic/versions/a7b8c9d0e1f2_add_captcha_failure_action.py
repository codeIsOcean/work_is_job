"""add captcha_failure_action column

Revision ID: a7b8c9d0e1f2
Revises: sm01a2b3c4d5
Create Date: 2025-12-29

Добавляет колонку captcha_failure_action в chat_settings.

Определяет действие при провале/таймауте капчи для Visual DM режима:
- "keep" = оставить заявку висеть (пользователь может попробовать снова)
- "decline" = отклонить заявку (заявка удаляется из Telegram)
- NULL = использовать дефолт ("keep" - старое поведение)
"""

from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизии, используемые Alembic
revision = 'a7b8c9d0e1f2'
# Предыдущая ревизия, от которой зависит данная миграция
down_revision = 'sm01a2b3c4d5'
# Метки веток (не используются)
branch_labels = None
# Зависимости (не используются)
depends_on = None


def upgrade() -> None:
    """
    Добавляет колонку captcha_failure_action в таблицу chat_settings.

    Колонка определяет что делать при провале капчи (Visual DM):
    - "keep" = оставить заявку висеть (дефолт - старое поведение)
    - "decline" = отклонить заявку (заявка удаляется из Telegram)
    - NULL = использовать дефолт ("keep")
    """
    # Добавляем колонку captcha_failure_action типа VARCHAR(16)
    # nullable=True позволяет использовать NULL как "дефолт"
    op.add_column(
        'chat_settings',
        sa.Column('captcha_failure_action', sa.String(16), nullable=True)
    )


def downgrade() -> None:
    """
    Удаляет колонку captcha_failure_action из таблицы chat_settings.

    При откате миграции все группы вернутся к дефолтному поведению
    (decline_chat_join_request при провале капчи).
    """
    # Удаляем колонку captcha_failure_action
    op.drop_column('chat_settings', 'captcha_failure_action')
