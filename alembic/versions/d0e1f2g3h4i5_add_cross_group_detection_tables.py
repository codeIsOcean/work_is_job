"""add_cross_group_detection_tables

Создаёт таблицы для модуля кросс-групповой детекции скамеров:
- cross_group_scammer_settings: глобальные настройки модуля (singleton)
- cross_group_user_activity: трекинг активности пользователей
- cross_group_detection_logs: лог детекций

Revision ID: d0e1f2g3h4i5
Revises: c9d0e1f2g3h4
Create Date: 2026-01-17

Кросс-групповая детекция обнаруживает скамеров которые:
1. Входят в несколько групп бота в течение интервала
2. Меняют профиль (имя/фото) после входа
3. Отправляют сообщения в несколько групп
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# Импортируем JSONB и ENUM для PostgreSQL
from sqlalchemy.dialects.postgresql import JSONB, ENUM


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2g3h4i5'
down_revision: Union[str, None] = 'c9d0e1f2g3h4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт таблицы для кросс-групповой детекции."""

    # ─────────────────────────────────────────────────────────
    # СОЗДАНИЕ ENUM ТИПОВ
    # ─────────────────────────────────────────────────────────
    # Создаём enum для типа действия при детекции
    # Идемпотентно — не упадёт если тип уже существует
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE cross_group_action_type AS ENUM (
                'delete', 'mute', 'ban', 'kick'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Создаём enum для типа изменения профиля
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE profile_change_type AS ENUM (
                'name', 'photo', 'both'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ─────────────────────────────────────────────────────────
    # ТАБЛИЦА: cross_group_scammer_settings
    # ─────────────────────────────────────────────────────────
    # Глобальные настройки модуля (singleton — одна запись)
    op.create_table(
        'cross_group_scammer_settings',
        # PRIMARY KEY: фиксированный ID (singleton)
        sa.Column(
            'id',
            sa.Integer(),
            primary_key=True,
            comment='ID настроек (всегда 1 — singleton)'
        ),
        # Глобальный переключатель модуля
        sa.Column(
            'enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Включён ли модуль'
        ),
        # Критерий 1: интервал входов в группы (секунды)
        sa.Column(
            'join_interval_seconds',
            sa.Integer(),
            nullable=False,
            server_default='86400',
            comment='Интервал для трекинга входов (сек, default 24ч)'
        ),
        # Критерий 2: окно смены профиля (секунды)
        sa.Column(
            'profile_change_window_seconds',
            sa.Integer(),
            nullable=False,
            server_default='43200',
            comment='Окно для смены профиля (сек, default 12ч)'
        ),
        # Критерий 3: интервал сообщений (секунды)
        sa.Column(
            'message_interval_seconds',
            sa.Integer(),
            nullable=False,
            server_default='3600',
            comment='Интервал для трекинга сообщений (сек, default 1ч)'
        ),
        # Минимальное количество групп для срабатывания
        sa.Column(
            'min_groups',
            sa.Integer(),
            nullable=False,
            server_default='2',
            comment='Минимум групп для детекции'
        ),
        # Тип действия при детекции
        sa.Column(
            'action_type',
            ENUM('delete', 'mute', 'ban', 'kick', name='cross_group_action_type', create_type=False),
            nullable=False,
            server_default='mute',
            comment='Действие при детекции'
        ),
        # Длительность мута в минутах (0 = навсегда)
        sa.Column(
            'mute_duration_minutes',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Длительность мута (мин, 0=навсегда)'
        ),
        # Задержка перед удалением сообщений
        sa.Column(
            'delete_delay_seconds',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Задержка удаления сообщений (сек)'
        ),
        # Задержка перед мутом
        sa.Column(
            'mute_delay_seconds',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Задержка мута (сек)'
        ),
        # Задержка перед уведомлением
        sa.Column(
            'notification_delay_seconds',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Задержка уведомления (сек)'
        ),
        # Текст уведомления (опционально)
        sa.Column(
            'notification_text',
            sa.Text(),
            nullable=True,
            comment='Кастомный текст уведомления'
        ),
        # Отправлять ли в журнал
        sa.Column(
            'send_to_journal',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Отправлять в журнал группы'
        ),
        # Исключённые группы (белый список)
        sa.Column(
            'excluded_groups',
            JSONB,
            nullable=False,
            server_default='[]',
            comment='Список исключённых chat_id'
        ),
        # Временные метки
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Дата создания'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Дата обновления'
        ),
    )

    # ─────────────────────────────────────────────────────────
    # ТАБЛИЦА: cross_group_user_activity
    # ─────────────────────────────────────────────────────────
    # Трекинг активности пользователей в группах
    op.create_table(
        'cross_group_user_activity',
        # PRIMARY KEY: ID пользователя
        sa.Column(
            'user_id',
            sa.BigInteger(),
            primary_key=True,
            comment='ID пользователя Telegram'
        ),
        # Трекинг входов в группы (JSONB)
        sa.Column(
            'groups_joined',
            JSONB,
            nullable=False,
            server_default='{}',
            comment='Группы и время входа {chat_id: {joined_at, title}}'
        ),
        # Трекинг смены профиля
        sa.Column(
            'profile_changed_at',
            sa.DateTime(),
            nullable=True,
            comment='Когда профиль был изменён'
        ),
        sa.Column(
            'profile_change_type',
            ENUM('name', 'photo', 'both', name='profile_change_type', create_type=False),
            nullable=True,
            comment='Тип изменения профиля'
        ),
        sa.Column(
            'original_name',
            sa.String(512),
            nullable=True,
            comment='Оригинальное имя до изменения'
        ),
        sa.Column(
            'original_photo_id',
            sa.String(256),
            nullable=True,
            comment='ID оригинального фото'
        ),
        # Трекинг сообщений в группах (JSONB)
        sa.Column(
            'messages_in_groups',
            JSONB,
            nullable=False,
            server_default='{}',
            comment='Сообщения в группах {chat_id: {last_message_at, count}}'
        ),
        # Статус детекции
        sa.Column(
            'is_flagged',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Помечен как подозрительный'
        ),
        sa.Column(
            'flagged_at',
            sa.DateTime(),
            nullable=True,
            comment='Когда помечен как подозрительный'
        ),
        sa.Column(
            'action_taken',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Было ли применено действие'
        ),
        sa.Column(
            'actioned_groups',
            JSONB,
            nullable=False,
            server_default='[]',
            comment='В каких группах применено действие'
        ),
        # Временные метки
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Дата создания записи'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Дата обновления'
        ),
    )

    # ─────────────────────────────────────────────────────────
    # ТАБЛИЦА: cross_group_detection_logs
    # ─────────────────────────────────────────────────────────
    # Лог детекций кросс-групповых скамеров
    op.create_table(
        'cross_group_detection_logs',
        # PRIMARY KEY: автоинкремент
        sa.Column(
            'id',
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment='ID записи лога'
        ),
        # ID пользователя
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=False,
            index=True,
            comment='ID обнаруженного пользователя'
        ),
        # Время детекции
        sa.Column(
            'detected_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            index=True,
            comment='Когда произошла детекция'
        ),
        # Информация о группах (JSONB)
        sa.Column(
            'groups_involved',
            JSONB,
            nullable=False,
            comment='Затронутые группы {chat_id: {title, joined_at, message_at}}'
        ),
        # Информация об изменениях профиля (JSONB)
        sa.Column(
            'profile_changes',
            JSONB,
            nullable=True,
            comment='Изменения профиля {type, old, new, at}'
        ),
        # Применённое действие
        sa.Column(
            'action_type',
            ENUM('delete', 'mute', 'ban', 'kick', name='cross_group_action_type', create_type=False),
            nullable=False,
            comment='Какое действие применено'
        ),
        # ID сообщений в журналах
        sa.Column(
            'journal_message_ids',
            JSONB,
            nullable=False,
            server_default='{}',
            comment='ID сообщений в журналах {chat_id: msg_id}'
        ),
        # Данные пользователя на момент детекции
        sa.Column(
            'user_name',
            sa.String(512),
            nullable=True,
            comment='Имя пользователя на момент детекции'
        ),
        sa.Column(
            'username',
            sa.String(256),
            nullable=True,
            comment='Username (@) на момент детекции'
        ),
    )

    # ─────────────────────────────────────────────────────────
    # ИНДЕКСЫ
    # ─────────────────────────────────────────────────────────
    # Индекс для поиска детекций пользователя
    op.create_index(
        'ix_cross_group_detection_user',
        'cross_group_detection_logs',
        ['user_id']
    )
    # Индекс для поиска детекций по дате
    op.create_index(
        'ix_cross_group_detection_date',
        'cross_group_detection_logs',
        ['detected_at']
    )


def downgrade() -> None:
    """Удаляет таблицы кросс-групповой детекции."""
    # Удаляем индексы
    op.drop_index('ix_cross_group_detection_date', table_name='cross_group_detection_logs')
    op.drop_index('ix_cross_group_detection_user', table_name='cross_group_detection_logs')

    # Удаляем таблицы
    op.drop_table('cross_group_detection_logs')
    op.drop_table('cross_group_user_activity')
    op.drop_table('cross_group_scammer_settings')

    # Удаляем enum типы
    op.execute('DROP TYPE IF EXISTS profile_change_type')
    op.execute('DROP TYPE IF EXISTS cross_group_action_type')