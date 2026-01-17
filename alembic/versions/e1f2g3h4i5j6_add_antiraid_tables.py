"""add_antiraid_tables

Создаёт таблицы для модуля Anti-Raid:
- antiraid_settings: настройки модуля для каждой группы
- antiraid_name_patterns: паттерны имён для бана при входе

Модуль Anti-Raid защищает группу от:
1. Частых входов/выходов (join/exit abuse)
2. Бана по паттернам имени (name pattern ban)
3. Массовых вступлений (mass join / raid)
4. Массовых инвайтов (mass invite)
5. Массовых реакций (mass reaction)

Revision ID: e1f2g3h4i5j6
Revises: d0e1f2g3h4i5
Create Date: 2026-01-17

Все настройки гибкие — админ может менять через UI.
Дефолтные значения выбраны на основе практики борьбы со спамом.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'e1f2g3h4i5j6'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'd0e1f2g3h4i5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт таблицы для модуля Anti-Raid."""

    # ═══════════════════════════════════════════════════════════
    # ТАБЛИЦА 1: НАСТРОЙКИ ANTI-RAID (antiraid_settings)
    # ═══════════════════════════════════════════════════════════
    # Хранит все настройки модуля для каждой группы
    # Одна запись на группу (chat_id уникален)
    op.create_table(
        'antiraid_settings',

        # ─── PRIMARY KEY ───
        # Уникальный идентификатор записи
        sa.Column('id', sa.Integer(), nullable=False),

        # ─── CHAT_ID ───
        # Идентификатор группы (уникален — одна запись на группу)
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ═══════════════════════════════════════════════════════
        # РАЗДЕЛ 1: ЧАСТЫЕ ВХОДЫ/ВЫХОДЫ (JOIN/EXIT ABUSE)
        # ═══════════════════════════════════════════════════════

        # Включён ли компонент защиты (по умолчанию выключен)
        sa.Column('join_exit_enabled', sa.Boolean(), server_default='false', nullable=False),
        # Временное окно в секундах (дефолт: 60 сек)
        sa.Column('join_exit_window', sa.Integer(), server_default='60', nullable=False),
        # Порог срабатывания — макс. событий за окно (дефолт: 3)
        sa.Column('join_exit_threshold', sa.Integer(), server_default='3', nullable=False),
        # Действие: 'kick', 'ban', 'mute' (дефолт: 'ban')
        sa.Column('join_exit_action', sa.String(20), server_default='ban', nullable=False),
        # Длительность бана в часах, 0=навсегда (дефолт: 168 = 7 дней)
        sa.Column('join_exit_ban_duration', sa.Integer(), server_default='168', nullable=False),

        # ═══════════════════════════════════════════════════════
        # РАЗДЕЛ 2: БАН ПО ПАТТЕРНАМ ИМЕНИ (NAME PATTERN BAN)
        # ═══════════════════════════════════════════════════════

        # Включён ли компонент защиты (по умолчанию выключен)
        sa.Column('name_pattern_enabled', sa.Boolean(), server_default='false', nullable=False),
        # Действие: 'kick', 'ban' (дефолт: 'ban')
        sa.Column('name_pattern_action', sa.String(20), server_default='ban', nullable=False),
        # Длительность бана в часах, 0=навсегда (дефолт: 0 = навсегда)
        sa.Column('name_pattern_ban_duration', sa.Integer(), server_default='0', nullable=False),

        # ═══════════════════════════════════════════════════════
        # РАЗДЕЛ 3: МАССОВЫЕ ВСТУПЛЕНИЯ (MASS JOIN / RAID)
        # ═══════════════════════════════════════════════════════

        # Включён ли компонент защиты (по умолчанию выключен)
        sa.Column('mass_join_enabled', sa.Boolean(), server_default='false', nullable=False),
        # Временное окно в секундах (дефолт: 60 сек)
        sa.Column('mass_join_window', sa.Integer(), server_default='60', nullable=False),
        # Порог срабатывания — макс. вступлений за окно (дефолт: 10)
        sa.Column('mass_join_threshold', sa.Integer(), server_default='10', nullable=False),
        # Действие: 'slowmode', 'lock', 'notify' (дефолт: 'slowmode')
        sa.Column('mass_join_action', sa.String(20), server_default='slowmode', nullable=False),
        # Значение slowmode в секундах (дефолт: 60 сек)
        sa.Column('mass_join_slowmode', sa.Integer(), server_default='60', nullable=False),
        # Авто-снятие ограничений через N минут, 0=вручную (дефолт: 30 мин)
        sa.Column('mass_join_auto_unlock', sa.Integer(), server_default='30', nullable=False),

        # ═══════════════════════════════════════════════════════
        # РАЗДЕЛ 4: МАССОВЫЕ ИНВАЙТЫ (MASS INVITE)
        # ═══════════════════════════════════════════════════════

        # Включён ли компонент защиты (по умолчанию выключен)
        sa.Column('mass_invite_enabled', sa.Boolean(), server_default='false', nullable=False),
        # Временное окно в секундах (дефолт: 300 сек = 5 мин)
        sa.Column('mass_invite_window', sa.Integer(), server_default='300', nullable=False),
        # Порог срабатывания — макс. инвайтов от одного юзера (дефолт: 5)
        sa.Column('mass_invite_threshold', sa.Integer(), server_default='5', nullable=False),
        # Действие: 'warn', 'kick', 'ban' (дефолт: 'warn')
        sa.Column('mass_invite_action', sa.String(20), server_default='warn', nullable=False),
        # Длительность бана в часах, 0=навсегда (дефолт: 24 часа)
        sa.Column('mass_invite_ban_duration', sa.Integer(), server_default='24', nullable=False),

        # ═══════════════════════════════════════════════════════
        # РАЗДЕЛ 5: МАССОВЫЕ РЕАКЦИИ (MASS REACTION)
        # ═══════════════════════════════════════════════════════

        # Включён ли компонент защиты (по умолчанию выключен)
        sa.Column('mass_reaction_enabled', sa.Boolean(), server_default='false', nullable=False),
        # Временное окно в секундах (дефолт: 60 сек)
        sa.Column('mass_reaction_window', sa.Integer(), server_default='60', nullable=False),
        # Порог по юзеру — макс. реакций от одного юзера (дефолт: 10)
        sa.Column('mass_reaction_threshold_user', sa.Integer(), server_default='10', nullable=False),
        # Порог по сообщению — макс. разных реакций на сообщение (дефолт: 20)
        sa.Column('mass_reaction_threshold_msg', sa.Integer(), server_default='20', nullable=False),
        # Действие: 'warn', 'mute', 'kick' (дефолт: 'mute')
        sa.Column('mass_reaction_action', sa.String(20), server_default='mute', nullable=False),
        # Длительность мута в минутах (дефолт: 60 мин = 1 час)
        sa.Column('mass_reaction_mute_duration', sa.Integer(), server_default='60', nullable=False),

        # ═══════════════════════════════════════════════════════
        # СЛУЖЕБНЫЕ ПОЛЯ
        # ═══════════════════════════════════════════════════════

        # Дата создания записи
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        # Дата последнего обновления
        sa.Column('updated_at', sa.DateTime(), nullable=True),

        # ─── CONSTRAINTS ───
        # Первичный ключ по id
        sa.PrimaryKeyConstraint('id'),
        # Уникальность chat_id — одна запись на группу
        sa.UniqueConstraint('chat_id', name='uq_antiraid_settings_chat_id')
    )

    # ─── ИНДЕКСЫ ДЛЯ antiraid_settings ───
    # Индекс по chat_id для быстрого поиска настроек группы
    op.create_index(
        'ix_antiraid_settings_chat_id',
        'antiraid_settings',
        ['chat_id'],
        unique=True
    )

    # ═══════════════════════════════════════════════════════════
    # ТАБЛИЦА 2: ПАТТЕРНЫ ИМЁН (antiraid_name_patterns)
    # ═══════════════════════════════════════════════════════════
    # Хранит паттерны для проверки имён при входе
    # Много записей на группу (list of patterns)
    op.create_table(
        'antiraid_name_patterns',

        # ─── PRIMARY KEY ───
        # Уникальный идентификатор паттерна
        sa.Column('id', sa.Integer(), nullable=False),

        # ─── CHAT_ID ───
        # Идентификатор группы (много паттернов на группу)
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─── ПАТТЕРН ───
        # Текст или regex для проверки имени
        # Пример: "детск", "педо", "cp"
        sa.Column('pattern', sa.String(255), nullable=False),

        # ─── ТИП ПАТТЕРНА ───
        # 'contains' — имя содержит паттерн (с нормализацией)
        # 'regex' — имя матчит regex
        # 'exact' — точное совпадение
        sa.Column('pattern_type', sa.String(20), server_default='contains', nullable=False),

        # ─── ВКЛЮЧЁН ЛИ ПАТТЕРН ───
        # Можно временно отключить без удаления
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),

        # ─── КТО ДОБАВИЛ ───
        # user_id админа который добавил паттерн
        sa.Column('created_by', sa.BigInteger(), nullable=True),

        # ─── ДАТА СОЗДАНИЯ ───
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),

        # ─── CONSTRAINTS ───
        sa.PrimaryKeyConstraint('id')
    )

    # ─── ИНДЕКСЫ ДЛЯ antiraid_name_patterns ───
    # Индекс по chat_id для быстрого поиска паттернов группы
    op.create_index(
        'ix_antiraid_name_patterns_chat_id',
        'antiraid_name_patterns',
        ['chat_id']
    )

    # Составной индекс для быстрого поиска активных паттернов группы
    # Используется в check_name_pattern() для получения только включённых паттернов
    op.create_index(
        'ix_antiraid_name_patterns_chat_enabled',
        'antiraid_name_patterns',
        ['chat_id', 'is_enabled']
    )


def downgrade() -> None:
    """Откатывает миграцию — удаляет таблицы Anti-Raid."""

    # ─── Удаляем индексы antiraid_name_patterns ───
    op.drop_index('ix_antiraid_name_patterns_chat_enabled', table_name='antiraid_name_patterns')
    op.drop_index('ix_antiraid_name_patterns_chat_id', table_name='antiraid_name_patterns')

    # ─── Удаляем таблицу antiraid_name_patterns ───
    op.drop_table('antiraid_name_patterns')

    # ─── Удаляем индексы antiraid_settings ───
    op.drop_index('ix_antiraid_settings_chat_id', table_name='antiraid_settings')

    # ─── Удаляем таблицу antiraid_settings ───
    op.drop_table('antiraid_settings')
