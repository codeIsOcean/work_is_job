"""add cas_enabled and add_to_spammer_db to custom_spam_sections

Revision ID: b8c9d0e1f2g3
Revises: a7b8c9d0e1f2
Create Date: 2026-01-01

Добавляет колонки для интеграции CAS и глобальной базы спаммеров
в кастомные разделы антискам.

Новые поля:
- cas_enabled: проверять ли пользователя в базе CAS (Combot Anti-Spam)
- add_to_spammer_db: добавлять ли нарушителя в глобальную БД спаммеров бота
"""

from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизии, используемые Alembic
revision = 'b8c9d0e1f2g3'
# Предыдущая ревизия, от которой зависит данная миграция
down_revision = 'a7b8c9d0e1f2'
# Метки веток (не используются)
branch_labels = None
# Зависимости (не используются)
depends_on = None


def upgrade() -> None:
    """
    Добавляет колонки cas_enabled и add_to_spammer_db
    в таблицу custom_spam_sections.

    cas_enabled: включить проверку CAS при срабатывании раздела.
    CAS — бесплатная глобальная база забаненных спамеров Telegram.

    add_to_spammer_db: добавлять нарушителя в глобальную БД спаммеров бота.
    Это позволяет мутить/банить спаммера во всех группах где бот админ.
    """
    # Добавляем колонку cas_enabled — проверка CAS
    # По умолчанию выключена (False)
    op.add_column(
        'custom_spam_sections',
        sa.Column('cas_enabled', sa.Boolean(), nullable=False, server_default='false')
    )

    # Добавляем колонку add_to_spammer_db — добавление в БД спаммеров
    # По умолчанию выключена (False)
    op.add_column(
        'custom_spam_sections',
        sa.Column('add_to_spammer_db', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """
    Удаляет колонки cas_enabled и add_to_spammer_db
    из таблицы custom_spam_sections.

    При откате миграции настройки CAS и БД спаммеров будут потеряны.
    """
    # Удаляем колонку add_to_spammer_db
    op.drop_column('custom_spam_sections', 'add_to_spammer_db')
    # Удаляем колонку cas_enabled
    op.drop_column('custom_spam_sections', 'cas_enabled')
