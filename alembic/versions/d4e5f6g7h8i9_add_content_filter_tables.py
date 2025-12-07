"""add_content_filter_tables

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2025-12-06 12:00:00.000000

Создаёт таблицы для модуля Content Filter:
- content_filter_settings: настройки модуля для каждой группы
- filter_words: запрещённые слова/фразы
- filter_whitelist: исключения (слова которые НЕ фильтровать)
- filter_violations: логи всех срабатываний фильтра
"""
# Импорт типов для аннотаций
from typing import Sequence, Union

# Импорт операций Alembic для миграций
from alembic import op
# Импорт типов данных SQLAlchemy
import sqlalchemy as sa


# ============================================================
# ИДЕНТИФИКАТОРЫ РЕВИЗИЙ
# ============================================================
# Уникальный идентификатор этой миграции
revision: str = 'd4e5f6g7h8i9'
# Предыдущая миграция, от которой зависит эта
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
# Метки веток (не используется в линейных миграциях)
branch_labels: Union[str, Sequence[str], None] = None
# Зависимости от других миграций (не используется)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Применить миграцию: создать таблицы для модуля Content Filter.

    Создаваемые таблицы:
    1. content_filter_settings - настройки модуля для группы
    2. filter_words - запрещённые слова
    3. filter_whitelist - исключения
    4. filter_violations - логи нарушений
    """

    # ============================================================
    # ТАБЛИЦА 1: НАСТРОЙКИ CONTENT FILTER
    # ============================================================
    # Хранит настройки модуля фильтрации для каждой группы
    # Одна запись на группу (chat_id как primary key)
    op.create_table(
        # Имя таблицы в базе данных
        'content_filter_settings',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY: ID группы
        # ─────────────────────────────────────────────────────────
        # Используем chat_id как первичный ключ
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ГЛОБАЛЬНЫЙ ПЕРЕКЛЮЧАТЕЛЬ
        # ─────────────────────────────────────────────────────────
        # Включён ли модуль для этой группы (по умолчанию выключен)
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),

        # ─────────────────────────────────────────────────────────
        # ПЕРЕКЛЮЧАТЕЛИ ПОДМОДУЛЕЙ
        # ─────────────────────────────────────────────────────────
        # Фильтр запрещённых слов (по умолчанию включён)
        sa.Column('word_filter_enabled', sa.Boolean(), nullable=False, server_default='true'),
        # Детектор скама по эвристике (по умолчанию включён)
        sa.Column('scam_detection_enabled', sa.Boolean(), nullable=False, server_default='true'),
        # Детектор повторяющихся сообщений (по умолчанию включён)
        sa.Column('flood_detection_enabled', sa.Boolean(), nullable=False, server_default='true'),
        # Детектор referral спама (по умолчанию ВЫКЛЮЧЕН)
        sa.Column('referral_detection_enabled', sa.Boolean(), nullable=False, server_default='false'),

        # ─────────────────────────────────────────────────────────
        # НАСТРОЙКИ SCAM DETECTOR
        # ─────────────────────────────────────────────────────────
        # Порог чувствительности (40=высокая, 60=средняя, 90=низкая)
        sa.Column('scam_sensitivity', sa.Integer(), nullable=False, server_default='60'),

        # ─────────────────────────────────────────────────────────
        # НАСТРОЙКИ FLOOD DETECTOR
        # ─────────────────────────────────────────────────────────
        # Максимум одинаковых сообщений до срабатывания
        sa.Column('flood_max_repeats', sa.Integer(), nullable=False, server_default='2'),
        # Временное окно в секундах
        sa.Column('flood_time_window', sa.Integer(), nullable=False, server_default='60'),

        # ─────────────────────────────────────────────────────────
        # ДЕЙСТВИЕ ПО УМОЛЧАНИЮ
        # ─────────────────────────────────────────────────────────
        # Что делать при срабатывании: delete, warn, mute, kick, ban
        sa.Column('default_action', sa.String(20), nullable=False, server_default='delete'),
        # Длительность мута в минутах (1440 = 24 часа)
        sa.Column('default_mute_duration', sa.Integer(), nullable=False, server_default='1440'),

        # ─────────────────────────────────────────────────────────
        # ЛОГИРОВАНИЕ
        # ─────────────────────────────────────────────────────────
        # Отправлять ли уведомления в лог-канал
        sa.Column('log_violations', sa.Boolean(), nullable=False, server_default='true'),

        # ─────────────────────────────────────────────────────────
        # ВРЕМЕННЫЕ МЕТКИ
        # ─────────────────────────────────────────────────────────
        # Когда созданы настройки
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        # Когда последний раз обновлены
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Первичный ключ по chat_id
        sa.PrimaryKeyConstraint('chat_id'),
        # Внешний ключ на таблицу groups с каскадным удалением
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
    )

    # ============================================================
    # ТАБЛИЦА 2: ЗАПРЕЩЁННЫЕ СЛОВА
    # ============================================================
    # Хранит список запрещённых слов для каждой группы
    op.create_table(
        # Имя таблицы
        'filter_words',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY
        # ─────────────────────────────────────────────────────────
        # Автоинкрементный ID
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # FOREIGN KEY: ID группы
        # ─────────────────────────────────────────────────────────
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # СЛОВО/ФРАЗА
        # ─────────────────────────────────────────────────────────
        # Оригинальное слово как ввёл админ
        sa.Column('word', sa.String(500), nullable=False),
        # Нормализованная версия для поиска
        sa.Column('normalized', sa.String(500), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ТИП СОВПАДЕНИЯ
        # ─────────────────────────────────────────────────────────
        # word = как отдельное слово, phrase = как подстрока, regex = регулярка
        sa.Column('match_type', sa.String(20), nullable=False, server_default='word'),

        # ─────────────────────────────────────────────────────────
        # ИНДИВИДУАЛЬНОЕ ДЕЙСТВИЕ (опционально)
        # ─────────────────────────────────────────────────────────
        # NULL = использовать default из settings
        sa.Column('action', sa.String(20), nullable=True),
        # Длительность мута для этого слова (в минутах)
        sa.Column('action_duration', sa.Integer(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # КАТЕГОРИЯ
        # ─────────────────────────────────────────────────────────
        # profanity, drugs, spam, custom
        sa.Column('category', sa.String(50), nullable=True),

        # ─────────────────────────────────────────────────────────
        # АУДИТ
        # ─────────────────────────────────────────────────────────
        # Кто добавил слово
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        # Когда добавлено
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
        # Одно слово один раз в группе
        sa.UniqueConstraint('chat_id', 'word', name='uq_filter_chat_word'),
    )

    # Создаём индекс для быстрого поиска слов по группе
    op.create_index(
        'ix_filter_words_chat_id',
        'filter_words',
        ['chat_id'],
        unique=False
    )

    # Создаём индекс для поиска по нормализованному слову
    op.create_index(
        'ix_filter_words_normalized',
        'filter_words',
        ['normalized'],
        unique=False
    )

    # Создаём составной индекс для быстрого поиска по группе и слову
    op.create_index(
        'ix_filter_words_chat_normalized',
        'filter_words',
        ['chat_id', 'normalized'],
        unique=False
    )

    # ============================================================
    # ТАБЛИЦА 3: БЕЛЫЙ СПИСОК (ИСКЛЮЧЕНИЯ)
    # ============================================================
    # Слова которые НЕ нужно фильтровать
    op.create_table(
        'filter_whitelist',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY
        # ─────────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # FOREIGN KEY
        # ─────────────────────────────────────────────────────────
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # СЛОВО-ИСКЛЮЧЕНИЕ
        # ─────────────────────────────────────────────────────────
        sa.Column('word', sa.String(500), nullable=False),
        sa.Column('normalized', sa.String(500), nullable=False),

        # ─────────────────────────────────────────────────────────
        # АУДИТ
        # ─────────────────────────────────────────────────────────
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('chat_id', 'word', name='uq_whitelist_chat_word'),
    )

    # Индекс для поиска исключений по группе
    op.create_index(
        'ix_filter_whitelist_chat_id',
        'filter_whitelist',
        ['chat_id'],
        unique=False
    )

    # ============================================================
    # ТАБЛИЦА 4: ЛОГИ НАРУШЕНИЙ
    # ============================================================
    # Записывает каждое срабатывание фильтра
    op.create_table(
        'filter_violations',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY
        # ─────────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # ИДЕНТИФИКАТОРЫ
        # ─────────────────────────────────────────────────────────
        # Группа где произошло нарушение
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        # Пользователь-нарушитель
        sa.Column('user_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ДЕТАЛИ СРАБАТЫВАНИЯ
        # ─────────────────────────────────────────────────────────
        # Какой детектор сработал: word_filter, scam_detector, flood, referral
        sa.Column('detector_type', sa.String(30), nullable=False),
        # Что именно сработало (слово, описание, паттерн)
        sa.Column('trigger', sa.String(500), nullable=True),
        # Скор для scam_detector
        sa.Column('scam_score', sa.Integer(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # СООБЩЕНИЕ
        # ─────────────────────────────────────────────────────────
        # Текст сообщения (для аудита)
        sa.Column('message_text', sa.Text(), nullable=True),
        # ID сообщения в Telegram
        sa.Column('message_id', sa.BigInteger(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # ДЕЙСТВИЕ
        # ─────────────────────────────────────────────────────────
        # Что сделали: delete, warn, mute, kick, ban
        sa.Column('action_taken', sa.String(20), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ВРЕМЕННАЯ МЕТКА
        # ─────────────────────────────────────────────────────────
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ
        # ─────────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
    )

    # Индекс для поиска по группе
    op.create_index(
        'ix_filter_violations_chat_id',
        'filter_violations',
        ['chat_id'],
        unique=False
    )

    # Индекс для поиска по пользователю
    op.create_index(
        'ix_filter_violations_user_id',
        'filter_violations',
        ['user_id'],
        unique=False
    )

    # Составной индекс для поиска нарушений пользователя в группе
    op.create_index(
        'ix_violations_chat_user',
        'filter_violations',
        ['chat_id', 'user_id'],
        unique=False
    )

    # Составной индекс для поиска по дате в группе
    op.create_index(
        'ix_violations_chat_date',
        'filter_violations',
        ['chat_id', 'created_at'],
        unique=False
    )

    # Индекс для сортировки по дате
    op.create_index(
        'ix_filter_violations_created_at',
        'filter_violations',
        ['created_at'],
        unique=False
    )


def downgrade() -> None:
    """
    Откатить миграцию: удалить таблицы Content Filter.

    Порядок удаления обратный созданию (сначала зависимые таблицы).
    """

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ filter_violations
    # ============================================================
    # Сначала удаляем индексы
    op.drop_index('ix_filter_violations_created_at', table_name='filter_violations')
    op.drop_index('ix_violations_chat_date', table_name='filter_violations')
    op.drop_index('ix_violations_chat_user', table_name='filter_violations')
    op.drop_index('ix_filter_violations_user_id', table_name='filter_violations')
    op.drop_index('ix_filter_violations_chat_id', table_name='filter_violations')
    # Удаляем таблицу
    op.drop_table('filter_violations')

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ filter_whitelist
    # ============================================================
    op.drop_index('ix_filter_whitelist_chat_id', table_name='filter_whitelist')
    op.drop_table('filter_whitelist')

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ filter_words
    # ============================================================
    op.drop_index('ix_filter_words_chat_normalized', table_name='filter_words')
    op.drop_index('ix_filter_words_normalized', table_name='filter_words')
    op.drop_index('ix_filter_words_chat_id', table_name='filter_words')
    op.drop_table('filter_words')

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ content_filter_settings
    # ============================================================
    op.drop_table('content_filter_settings')
