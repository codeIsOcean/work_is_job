"""add_user_statistics_table

Revision ID: u1v2w3x4y5z6
Revises: 9356cadad695
Create Date: 2025-12-19

Добавляет таблицу user_statistics для хранения статистики
пользователей в группах (счётчики сообщений, дни активности).
Используется командой /stat.

ВАЖНО: Эта таблица ПОЛНОСТЬЮ ИЗОЛИРОВАНА от profile_snapshots!
"""

# Импорты стандартные для миграций Alembic
from typing import Sequence, Union

# op - операции с БД (create_table, drop_table и т.д.)
from alembic import op

# sa - SQLAlchemy для определения типов колонок
import sqlalchemy as sa


# ============================================================
# ИДЕНТИФИКАТОРЫ РЕВИЗИИ
# ============================================================
# Уникальный ID этой миграции
revision: str = 'u1v2w3x4y5z6'

# ID предыдущей миграции (от которой зависит эта)
down_revision: Union[str, None] = '9356cadad695'

# Метки веток (не используем)
branch_labels: Union[str, Sequence[str], None] = None

# Зависимости (не используем)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Создаём таблицу user_statistics для хранения статистики пользователей.

    Таблица хранит:
    - message_count: количество сообщений от пользователя в группе
    - last_message_at: время последнего сообщения
    - active_days: количество уникальных дней с сообщениями
    - last_active_date: дата последнего дня активности
    """

    # Создаём таблицу user_statistics
    op.create_table(
        # Имя таблицы в БД
        'user_statistics',

        # ─────────────────────────────────────────────────────
        # PRIMARY KEY: автоинкрементный ID
        # ─────────────────────────────────────────────────────
        sa.Column(
            'id',
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment='Уникальный ID записи'
        ),

        # ─────────────────────────────────────────────────────
        # ИДЕНТИФИКАТОРЫ: chat_id + user_id
        # ─────────────────────────────────────────────────────
        # ID группы (BigInteger для больших ID Telegram)
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            nullable=False,
            index=True,
            comment='ID группы Telegram'
        ),

        # ID пользователя (BigInteger для больших ID Telegram)
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=False,
            index=True,
            comment='ID пользователя Telegram'
        ),

        # ─────────────────────────────────────────────────────
        # СЧЁТЧИКИ СООБЩЕНИЙ
        # ─────────────────────────────────────────────────────
        # Общее количество сообщений
        sa.Column(
            'message_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Количество сообщений от пользователя'
        ),

        # Время последнего сообщения
        sa.Column(
            'last_message_at',
            sa.DateTime(),
            nullable=True,
            comment='Время последнего сообщения (UTC)'
        ),

        # ─────────────────────────────────────────────────────
        # ДНИ АКТИВНОСТИ
        # ─────────────────────────────────────────────────────
        # Количество уникальных дней с сообщениями
        sa.Column(
            'active_days',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Количество уникальных дней с сообщениями'
        ),

        # Дата последнего дня активности
        sa.Column(
            'last_active_date',
            sa.DateTime(),
            nullable=True,
            comment='Дата последнего дня активности (для подсчёта)'
        ),

        # ─────────────────────────────────────────────────────
        # ВРЕМЕННЫЕ МЕТКИ
        # ─────────────────────────────────────────────────────
        # Когда запись создана
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            comment='Время создания записи (UTC)'
        ),

        # Когда запись обновлена
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            comment='Время последнего обновления (UTC)'
        ),
    )

    # ─────────────────────────────────────────────────────────
    # УНИКАЛЬНОЕ ОГРАНИЧЕНИЕ: один пользователь - одна запись в группе
    # ─────────────────────────────────────────────────────────
    # Предотвращает дубликаты: не может быть двух записей
    # для одного user_id в одном chat_id
    op.create_unique_constraint(
        'uq_user_statistics_chat_user',      # Имя ограничения
        'user_statistics',                    # Таблица
        ['chat_id', 'user_id']               # Колонки
    )

    # ─────────────────────────────────────────────────────────
    # СОСТАВНОЙ ИНДЕКС для быстрого поиска
    # ─────────────────────────────────────────────────────────
    # Ускоряет основной запрос: "статистика user_id в chat_id"
    op.create_index(
        'ix_user_statistics_chat_user',      # Имя индекса
        'user_statistics',                    # Таблица
        ['chat_id', 'user_id']               # Колонки
    )


def downgrade() -> None:
    """
    Откат миграции: удаляем таблицу user_statistics.

    Порядок важен:
    1. Сначала удаляем индексы
    2. Потом удаляем ограничения
    3. Потом удаляем таблицу
    """

    # Удаляем составной индекс
    op.drop_index('ix_user_statistics_chat_user', table_name='user_statistics')

    # Удаляем уникальное ограничение
    op.drop_constraint('uq_user_statistics_chat_user', 'user_statistics', type_='unique')

    # Удаляем таблицу
    op.drop_table('user_statistics')