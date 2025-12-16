"""add_profile_monitor_tables

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2025-12-13

Создаёт таблицы для модуля Profile Monitor:
- profile_monitor_settings: настройки мониторинга для групп
- profile_snapshots: снимки профилей при входе
- profile_change_logs: журнал изменений профилей
"""

from alembic import op
import sqlalchemy as sa


# Revision идентификаторы
revision = 'o5p6q7r8s9t0'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт таблицы для Profile Monitor."""

    # ─────────────────────────────────────────────────────────
    # ТАБЛИЦА: profile_monitor_settings
    # ─────────────────────────────────────────────────────────
    # Настройки модуля мониторинга профилей для каждой группы
    op.create_table(
        'profile_monitor_settings',
        # PRIMARY KEY: ID группы
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
            primary_key=True,
            comment='ID группы (первичный ключ)'
        ),
        # Глобальный переключатель
        sa.Column(
            'enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Включён ли модуль'
        ),
        # Настройки логирования
        sa.Column(
            'log_name_changes',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Логировать изменение имени'
        ),
        sa.Column(
            'log_username_changes',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Логировать изменение username'
        ),
        sa.Column(
            'log_photo_changes',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Логировать изменение фото'
        ),
        # Автомут: критерий 1 (нет фото + молодой аккаунт)
        sa.Column(
            'auto_mute_no_photo_young',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Автомут: нет фото + аккаунт моложе N дней'
        ),
        sa.Column(
            'auto_mute_account_age_days',
            sa.Integer(),
            nullable=False,
            server_default='15',
            comment='Порог возраста аккаунта в днях'
        ),
        sa.Column(
            'auto_mute_delete_messages',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Удалять сообщения при автомуте'
        ),
        # Автомут: критерий 2 (нет фото + смена имени + быстрые сообщения)
        sa.Column(
            'auto_mute_name_change_fast_msg',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Автомут: смена имени + быстрые сообщения'
        ),
        sa.Column(
            'name_change_window_hours',
            sa.Integer(),
            nullable=False,
            server_default='24',
            comment='Окно для смены имени (часы)'
        ),
        sa.Column(
            'first_message_window_minutes',
            sa.Integer(),
            nullable=False,
            server_default='10',
            comment='Окно для первого сообщения (минуты)'
        ),
        # Настройки уведомлений
        sa.Column(
            'send_to_journal',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='Отправлять в журнал'
        ),
        sa.Column(
            'min_changes_for_journal',
            sa.Integer(),
            nullable=False,
            server_default='1',
            comment='Минимум изменений для журнала'
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
    # ТАБЛИЦА: profile_snapshots
    # ─────────────────────────────────────────────────────────
    # Снимки профилей при входе в группу
    op.create_table(
        'profile_snapshots',
        # PRIMARY KEY
        sa.Column(
            'id',
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment='Уникальный ID записи'
        ),
        # Идентификаторы
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='ID группы'
        ),
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=False,
            index=True,
            comment='ID пользователя'
        ),
        # Данные профиля
        sa.Column(
            'first_name',
            sa.String(256),
            nullable=True,
            comment='Имя'
        ),
        sa.Column(
            'last_name',
            sa.String(256),
            nullable=True,
            comment='Фамилия'
        ),
        sa.Column(
            'full_name',
            sa.String(512),
            nullable=True,
            comment='Полное имя'
        ),
        sa.Column(
            'username',
            sa.String(256),
            nullable=True,
            comment='Username (@)'
        ),
        sa.Column(
            'has_photo',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Есть ли фото'
        ),
        sa.Column(
            'photo_id',
            sa.String(256),
            nullable=True,
            comment='ID фото профиля'
        ),
        # Метаданные аккаунта
        sa.Column(
            'account_age_days',
            sa.Integer(),
            nullable=True,
            comment='Возраст аккаунта в днях'
        ),
        sa.Column(
            'account_created_at',
            sa.DateTime(),
            nullable=True,
            comment='Дата создания аккаунта'
        ),
        sa.Column(
            'is_premium',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Premium аккаунт'
        ),
        # Временные метки
        sa.Column(
            'joined_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Когда вошёл в группу'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            comment='Когда обновлён снимок'
        ),
        sa.Column(
            'first_message_at',
            sa.DateTime(),
            nullable=True,
            comment='Когда отправил первое сообщение'
        ),
    )

    # Уникальный индекс: один снимок на пользователя в группе
    op.create_index(
        'ix_profile_snapshot_chat_user',
        'profile_snapshots',
        ['chat_id', 'user_id'],
        unique=True
    )

    # ─────────────────────────────────────────────────────────
    # ТАБЛИЦА: profile_change_logs
    # ─────────────────────────────────────────────────────────
    # Журнал изменений профилей
    op.create_table(
        'profile_change_logs',
        # PRIMARY KEY
        sa.Column(
            'id',
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment='Уникальный ID записи'
        ),
        # Идентификаторы
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='ID группы'
        ),
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=False,
            index=True,
            comment='ID пользователя'
        ),
        # Тип изменения
        sa.Column(
            'change_type',
            sa.String(50),
            nullable=False,
            comment='Тип изменения (name, username, photo_*)'
        ),
        # Старые и новые значения
        sa.Column(
            'old_value',
            sa.Text(),
            nullable=True,
            comment='Старое значение'
        ),
        sa.Column(
            'new_value',
            sa.Text(),
            nullable=True,
            comment='Новое значение'
        ),
        # Контекст
        sa.Column(
            'minutes_since_join',
            sa.Integer(),
            nullable=True,
            comment='Минут с момента входа'
        ),
        sa.Column(
            'detected_at_message_id',
            sa.BigInteger(),
            nullable=True,
            comment='ID сообщения при обнаружении'
        ),
        # Действия
        sa.Column(
            'action_taken',
            sa.String(50),
            nullable=True,
            comment='Применённое действие'
        ),
        sa.Column(
            'journal_message_id',
            sa.BigInteger(),
            nullable=True,
            comment='ID сообщения в журнале'
        ),
        sa.Column(
            'sent_to_group',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Отправлено ли в группу'
        ),
        # Временная метка
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
            index=True,
            comment='Дата создания'
        ),
    )

    # Индексы для profile_change_logs
    op.create_index(
        'ix_profile_changes_chat_user',
        'profile_change_logs',
        ['chat_id', 'user_id']
    )
    op.create_index(
        'ix_profile_changes_chat_date',
        'profile_change_logs',
        ['chat_id', 'created_at']
    )


def downgrade() -> None:
    """Удаляет таблицы Profile Monitor."""
    # Удаляем индексы profile_change_logs
    op.drop_index('ix_profile_changes_chat_date', table_name='profile_change_logs')
    op.drop_index('ix_profile_changes_chat_user', table_name='profile_change_logs')
    # Удаляем таблицу profile_change_logs
    op.drop_table('profile_change_logs')

    # Удаляем индекс profile_snapshots
    op.drop_index('ix_profile_snapshot_chat_user', table_name='profile_snapshots')
    # Удаляем таблицу profile_snapshots
    op.drop_table('profile_snapshots')

    # Удаляем таблицу profile_monitor_settings
    op.drop_table('profile_monitor_settings')
