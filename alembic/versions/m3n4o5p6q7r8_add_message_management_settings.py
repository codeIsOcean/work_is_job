"""add_message_management_settings

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2025-12-10

Эта миграция создаёт таблицу message_management_settings
для хранения настроек модуля "Управление сообщениями":
- Удаление команд (от админов и пользователей)
- Удаление системных сообщений (вход, выход, закреп, фото)
- Репин (автозакрепление сообщения)
"""

# Импортируем Alembic для управления миграцией
from alembic import op

# Импортируем SQLAlchemy для определения типов колонок
import sqlalchemy as sa


# ID этой ревизии (уникальный идентификатор миграции)
revision = 'm3n4o5p6q7r8'

# ID предыдущей ревизии (для цепочки миграций)
# Должен соответствовать последней миграции в проекте
down_revision = 'l2m3n4o5p6q7'

# Ветка миграции (обычно None для линейной истории)
branch_labels = None

# Зависимости (обычно None)
depends_on = None


def upgrade() -> None:
    """
    Применяет миграцию — создаёт таблицу message_management_settings.

    Таблица содержит настройки управления сообщениями для каждой группы:
    - Удаление команд
    - Удаление системных сообщений
    - Репин (автозакрепление)
    """
    # Создаём таблицу message_management_settings
    op.create_table(
        # Имя таблицы
        'message_management_settings',

        # ─────────────────────────────────────────────────────────
        # ПЕРВИЧНЫЙ КЛЮЧ
        # ─────────────────────────────────────────────────────────
        # Автоинкрементный ID записи
        sa.Column(
            'id',
            sa.Integer(),
            nullable=False,
            comment='Первичный ключ'
        ),

        # ─────────────────────────────────────────────────────────
        # ID ГРУППЫ
        # ─────────────────────────────────────────────────────────
        # BigInteger для Telegram ID (могут быть большими числами)
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            nullable=False,
            comment='ID группы (Telegram chat_id)'
        ),

        # ─────────────────────────────────────────────────────────
        # УДАЛЕНИЕ КОМАНД
        # ─────────────────────────────────────────────────────────
        # Удалять команды /xxx от администраторов
        sa.Column(
            'delete_admin_commands',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять команды от админов'
        ),

        # Удалять команды /xxx от обычных пользователей
        sa.Column(
            'delete_user_commands',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять команды от пользователей'
        ),

        # ─────────────────────────────────────────────────────────
        # СИСТЕМНЫЕ СООБЩЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Удалять сообщения о входе участников
        sa.Column(
            'delete_join_messages',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять сообщения о входе участников'
        ),

        # Удалять сообщения о выходе участников
        sa.Column(
            'delete_leave_messages',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять сообщения о выходе участников'
        ),

        # Удалять уведомления о закреплении сообщений
        sa.Column(
            'delete_pin_messages',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять уведомления о закрепе'
        ),

        # Удалять сообщения об изменении фото/названия группы
        sa.Column(
            'delete_chat_photo_messages',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Удалять сообщения об изменении фото/названия'
        ),

        # ─────────────────────────────────────────────────────────
        # РЕПИН (АВТОЗАКРЕПЛЕНИЕ)
        # ─────────────────────────────────────────────────────────
        # Включён ли автозакреп
        sa.Column(
            'repin_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Включён ли автозакреп'
        ),

        # ID сообщения для автозакрепа (может быть NULL)
        sa.Column(
            'repin_message_id',
            sa.BigInteger(),
            nullable=True,
            comment='ID сообщения для автозакрепа'
        ),

        # ─────────────────────────────────────────────────────────
        # МЕТАДАННЫЕ
        # ─────────────────────────────────────────────────────────
        # Дата создания записи
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=True,
            comment='Дата создания'
        ),

        # Дата последнего обновления
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=True,
            comment='Дата обновления'
        ),

        # ─────────────────────────────────────────────────────────
        # ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Первичный ключ на колонку id
        sa.PrimaryKeyConstraint('id'),

        # Уникальный индекс на chat_id (одна запись на группу)
        sa.UniqueConstraint('chat_id'),
    )

    # Создаём индекс на chat_id для быстрого поиска
    # Индекс ускоряет SELECT WHERE chat_id = ?
    op.create_index(
        'ix_message_management_settings_chat_id',  # Имя индекса
        'message_management_settings',              # Имя таблицы
        ['chat_id'],                                # Колонки индекса
        unique=True                                 # Уникальный индекс
    )


def downgrade() -> None:
    """
    Откатывает миграцию — удаляет таблицу message_management_settings.

    Используется при откате миграции (alembic downgrade).
    """
    # Сначала удаляем индекс
    op.drop_index(
        'ix_message_management_settings_chat_id',
        table_name='message_management_settings'
    )

    # Затем удаляем таблицу
    op.drop_table('message_management_settings')
