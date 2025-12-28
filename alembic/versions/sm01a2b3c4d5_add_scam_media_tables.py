"""add_scam_media_tables

Revision ID: sm01a2b3c4d5
Revises: 419235295cd9
Create Date: 2025-12-28 12:00:00.000000

Создаёт таблицы для модуля Scam Media Filter (фильтр скам-фото):
- scam_media_settings: настройки модуля для каждой группы
- banned_image_hashes: хеши запрещённых изображений (pHash + dHash)
- scam_media_violations: логи всех срабатываний фильтра

Модуль использует perceptual hashing для обнаружения скам-фото
даже после изменения размера, сжатия или небольших правок.
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
revision: str = 'sm01a2b3c4d5'
# Предыдущая миграция, от которой зависит эта
down_revision: Union[str, None] = '419235295cd9'
# Метки веток (не используется в линейных миграциях)
branch_labels: Union[str, Sequence[str], None] = None
# Зависимости от других миграций (не используется)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Применить миграцию: создать таблицы для модуля Scam Media Filter.

    Создаваемые таблицы:
    1. scam_media_settings - настройки модуля для группы
    2. banned_image_hashes - хеши запрещённых изображений
    3. scam_media_violations - логи нарушений
    """

    # ============================================================
    # ТАБЛИЦА 1: НАСТРОЙКИ SCAM MEDIA FILTER
    # ============================================================
    # Хранит настройки модуля фильтрации скам-фото для каждой группы
    # Одна запись на группу (chat_id как primary key)
    op.create_table(
        # Имя таблицы в базе данных
        'scam_media_settings',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY: ID группы
        # ─────────────────────────────────────────────────────────
        # Используем chat_id как первичный ключ
        # BigInteger для Telegram chat_id (может быть отрицательным)
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ГЛОБАЛЬНЫЙ ПЕРЕКЛЮЧАТЕЛЬ
        # ─────────────────────────────────────────────────────────
        # Включён ли модуль для этой группы (по умолчанию выключен)
        # Админ должен явно включить модуль
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),

        # ─────────────────────────────────────────────────────────
        # РЕЖИМ БАЗЫ ХЕШЕЙ
        # ─────────────────────────────────────────────────────────
        # True = использовать глобальную базу хешей (хеши из всех групп)
        # False = только локальные хеши (добавленные в этой группе)
        # По умолчанию локальный режим - безопаснее
        sa.Column('use_global_hashes', sa.Boolean(), nullable=False, server_default='false'),

        # ─────────────────────────────────────────────────────────
        # ДЕЙСТВИЕ ПРИ ОБНАРУЖЕНИИ
        # ─────────────────────────────────────────────────────────
        # Что делать при срабатывании фильтра:
        # - "delete" = только удалить сообщение
        # - "delete_warn" = удалить + предупреждение
        # - "delete_mute" = удалить + мут на mute_duration секунд
        # - "delete_ban" = удалить + бан на ban_duration секунд
        sa.Column('action', sa.String(20), nullable=False, server_default='delete_mute'),

        # ─────────────────────────────────────────────────────────
        # ДЛИТЕЛЬНОСТЬ МУТА (В СЕКУНДАХ)
        # ─────────────────────────────────────────────────────────
        # Используется когда action = "delete_mute"
        # 86400 секунд = 24 часа (значение по умолчанию)
        # 0 = навсегда (перманентный мут)
        sa.Column('mute_duration', sa.Integer(), nullable=False, server_default='86400'),

        # ─────────────────────────────────────────────────────────
        # ДЛИТЕЛЬНОСТЬ БАНА (В СЕКУНДАХ)
        # ─────────────────────────────────────────────────────────
        # Используется когда action = "delete_ban"
        # 0 = навсегда (перманентный бан) - значение по умолчанию
        sa.Column('ban_duration', sa.Integer(), nullable=False, server_default='0'),

        # ─────────────────────────────────────────────────────────
        # ПОРОГ ПОХОЖЕСТИ (HAMMING DISTANCE)
        # ─────────────────────────────────────────────────────────
        # Максимальное расстояние Хэмминга для срабатывания
        # 0 = только точное совпадение
        # 5 = небольшие изменения (рекомендуется)
        # 10 = умеренные изменения (по умолчанию)
        # 15+ = значительные изменения (может давать false positives)
        sa.Column('threshold', sa.Integer(), nullable=False, server_default='10'),

        # ─────────────────────────────────────────────────────────
        # ПРОВЕРКА ПРЕВЬЮ ВИДЕО
        # ─────────────────────────────────────────────────────────
        # True = проверять thumbnail видео на совпадение
        # False = проверять только фото
        # По умолчанию включено - скамеры шлют видео с теми же превью
        sa.Column('check_thumbnails', sa.Boolean(), nullable=False, server_default='true'),

        # ─────────────────────────────────────────────────────────
        # КАСТОМНЫЕ ТЕКСТЫ УВЕДОМЛЕНИЙ
        # ─────────────────────────────────────────────────────────
        # NULL = использовать текст по умолчанию
        # %user% и %duration% будут заменены на реальные значения

        # Текст при муте (action = "delete_mute")
        sa.Column('mute_text', sa.String(500), nullable=True),

        # Текст при бане (action = "delete_ban")
        sa.Column('ban_text', sa.String(500), nullable=True),

        # Текст предупреждения (action = "delete_warn")
        sa.Column('warn_text', sa.String(500), nullable=True),

        # ─────────────────────────────────────────────────────────
        # АВТОУДАЛЕНИЕ СИСТЕМНЫХ СООБЩЕНИЙ
        # ─────────────────────────────────────────────────────────
        # Через сколько секунд удалять уведомление бота
        # NULL = не удалять автоматически
        sa.Column('notification_delete_delay', sa.Integer(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # ДОБАВЛЕНИЕ В ГЛОБАЛЬНУЮ БД СКАММЕРОВ
        # ─────────────────────────────────────────────────────────
        # True = добавлять нарушителя в глобальную БД скаммеров
        # False = только локальное действие
        # По умолчанию включено
        sa.Column('add_to_scammer_db', sa.Boolean(), nullable=False, server_default='true'),

        # ─────────────────────────────────────────────────────────
        # ЛОГИРОВАНИЕ В ЖУРНАЛ
        # ─────────────────────────────────────────────────────────
        # True = отправлять записи в журнал группы
        # False = тихий режим
        sa.Column('log_to_journal', sa.Boolean(), nullable=False, server_default='true'),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Первичный ключ по chat_id
        sa.PrimaryKeyConstraint('chat_id'),
        # Внешний ключ на таблицу groups с каскадным удалением
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
    )

    # ============================================================
    # ТАБЛИЦА 2: ХЕШИ ЗАПРЕЩЁННЫХ ИЗОБРАЖЕНИЙ
    # ============================================================
    # Хранит perceptual hash (pHash + dHash) скам-изображений
    op.create_table(
        # Имя таблицы
        'banned_image_hashes',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY
        # ─────────────────────────────────────────────────────────
        # Автоинкрементный ID записи
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # PERCEPTUAL HASH (pHash)
        # ─────────────────────────────────────────────────────────
        # 64-битный хеш изображения в hex формате (16 символов)
        # pHash устойчив к ресайзу, сжатию, небольшим изменениям
        sa.Column('phash', sa.String(16), nullable=False),

        # ─────────────────────────────────────────────────────────
        # DIFFERENCE HASH (dHash)
        # ─────────────────────────────────────────────────────────
        # 64-битный хеш в hex формате (16 символов)
        # dHash дополняет pHash, ловит другие типы изменений
        # NULL если используется только pHash
        sa.Column('dhash', sa.String(16), nullable=True),

        # ─────────────────────────────────────────────────────────
        # РЕЖИМ: ГЛОБАЛЬНЫЙ ИЛИ ЛОКАЛЬНЫЙ
        # ─────────────────────────────────────────────────────────
        # True = хеш работает во ВСЕХ группах с глобальным режимом
        # False = хеш работает только в группе chat_id
        sa.Column('is_global', sa.Boolean(), nullable=False, server_default='false'),

        # ─────────────────────────────────────────────────────────
        # ID ГРУППЫ (для локальных хешей)
        # ─────────────────────────────────────────────────────────
        # chat_id группы где был добавлен хеш
        # NULL = глобальный хеш (is_global = True)
        # Без ForeignKey - группа может быть удалена, хеш остаётся
        sa.Column('chat_id', sa.BigInteger(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # КТО ДОБАВИЛ ХЕШ
        # ─────────────────────────────────────────────────────────
        # user_id админа который добавил фото в базу
        sa.Column('added_by_user_id', sa.BigInteger(), nullable=False),

        # username админа (может быть NULL если нет username)
        sa.Column('added_by_username', sa.String(255), nullable=True),

        # ─────────────────────────────────────────────────────────
        # ДАТА ДОБАВЛЕНИЯ
        # ─────────────────────────────────────────────────────────
        # UTC timestamp когда хеш был добавлен в базу
        sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # ОПИСАНИЕ (ОПЦИОНАЛЬНО)
        # ─────────────────────────────────────────────────────────
        # Текстовое описание что это за фото
        # Например: "VIP Kazashki spam", "Narcotics ad"
        sa.Column('description', sa.String(255), nullable=True),

        # ─────────────────────────────────────────────────────────
        # ДЕТЕКЦИЯ ЛОГО (ОПЦИОНАЛЬНО)
        # ─────────────────────────────────────────────────────────
        # Если это хеш для области лого, а не всего изображения
        # NULL = хеш всего изображения
        # 'top_left', 'top_right', etc. = хеш конкретной области
        sa.Column('logo_region', sa.String(20), nullable=True),

        # ─────────────────────────────────────────────────────────
        # СТАТИСТИКА: КОЛИЧЕСТВО СРАБАТЫВАНИЙ
        # ─────────────────────────────────────────────────────────
        # Счётчик сколько раз этот хеш сработал
        sa.Column('matches_count', sa.Integer(), nullable=False, server_default='0'),

        # ─────────────────────────────────────────────────────────
        # СТАТИСТИКА: ПОСЛЕДНЕЕ СРАБАТЫВАНИЕ
        # ─────────────────────────────────────────────────────────
        # UTC timestamp последнего срабатывания
        # NULL = ещё ни разу не сработал
        sa.Column('last_match_at', sa.DateTime(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ
        # ─────────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint('id'),
    )

    # Индекс для быстрого поиска по pHash
    op.create_index(
        'ix_banned_image_hashes_phash',
        'banned_image_hashes',
        ['phash'],
        unique=False
    )

    # Индекс для быстрого поиска по dHash
    op.create_index(
        'ix_banned_image_hashes_dhash',
        'banned_image_hashes',
        ['dhash'],
        unique=False
    )

    # Индекс для поиска локальных хешей группы
    op.create_index(
        'ix_banned_image_hashes_chat_id',
        'banned_image_hashes',
        ['chat_id'],
        unique=False
    )

    # Составной индекс для поиска хешей по группе и режиму
    op.create_index(
        'ix_banned_image_hashes_chat_global',
        'banned_image_hashes',
        ['chat_id', 'is_global'],
        unique=False
    )

    # ============================================================
    # ТАБЛИЦА 3: ЛОГИ СРАБАТЫВАНИЙ ФИЛЬТРА
    # ============================================================
    # Записывает каждое срабатывание фильтра для аналитики
    op.create_table(
        'scam_media_violations',

        # ─────────────────────────────────────────────────────────
        # PRIMARY KEY
        # ─────────────────────────────────────────────────────────
        # Автоинкрементный ID записи
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # ─────────────────────────────────────────────────────────
        # ССЫЛКА НА СРАБОТАВШИЙ ХЕШ
        # ─────────────────────────────────────────────────────────
        # ID хеша который сработал
        # ForeignKey с CASCADE - при удалении хеша удаляются логи
        sa.Column('hash_id', sa.Integer(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ГРУППА ГДЕ ПРОИЗОШЛО СРАБАТЫВАНИЕ
        # ─────────────────────────────────────────────────────────
        # chat_id группы
        sa.Column('chat_id', sa.BigInteger(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # НАРУШИТЕЛЬ
        # ─────────────────────────────────────────────────────────
        # user_id отправителя скам-фото
        sa.Column('user_id', sa.BigInteger(), nullable=False),

        # username нарушителя (может быть NULL)
        sa.Column('username', sa.String(255), nullable=True),

        # Полное имя нарушителя
        sa.Column('full_name', sa.String(255), nullable=True),

        # ─────────────────────────────────────────────────────────
        # ИНФОРМАЦИЯ О СООБЩЕНИИ
        # ─────────────────────────────────────────────────────────
        # ID сообщения которое было удалено
        sa.Column('message_id', sa.BigInteger(), nullable=True),

        # ─────────────────────────────────────────────────────────
        # РЕЗУЛЬТАТ СРАВНЕНИЯ
        # ─────────────────────────────────────────────────────────
        # Расстояние Хэмминга между хешами (0 = точное совпадение)
        sa.Column('hamming_distance', sa.Integer(), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ПРИМЕНЁННОЕ ДЕЙСТВИЕ
        # ─────────────────────────────────────────────────────────
        # Какое действие было применено
        sa.Column('action_taken', sa.String(20), nullable=False),

        # ─────────────────────────────────────────────────────────
        # ДАТА СРАБАТЫВАНИЯ
        # ─────────────────────────────────────────────────────────
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # ─────────────────────────────────────────────────────────
        # КЛЮЧИ И ОГРАНИЧЕНИЯ
        # ─────────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['hash_id'], ['banned_image_hashes.id'], ondelete='CASCADE'),
    )

    # Индекс для поиска по хешу
    op.create_index(
        'ix_scam_media_violations_hash_id',
        'scam_media_violations',
        ['hash_id'],
        unique=False
    )

    # Индекс для поиска по группе
    op.create_index(
        'ix_scam_media_violations_chat_id',
        'scam_media_violations',
        ['chat_id'],
        unique=False
    )

    # Индекс для поиска по пользователю
    op.create_index(
        'ix_scam_media_violations_user_id',
        'scam_media_violations',
        ['user_id'],
        unique=False
    )

    # Составной индекс для поиска нарушений пользователя в группе
    op.create_index(
        'ix_scam_media_violations_chat_user',
        'scam_media_violations',
        ['chat_id', 'user_id'],
        unique=False
    )

    # Индекс для сортировки по дате
    op.create_index(
        'ix_scam_media_violations_created_at',
        'scam_media_violations',
        ['created_at'],
        unique=False
    )


def downgrade() -> None:
    """
    Откатить миграцию: удалить таблицы Scam Media Filter.

    Порядок удаления обратный созданию (сначала зависимые таблицы).
    """

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ scam_media_violations
    # ============================================================
    # Сначала удаляем индексы
    op.drop_index('ix_scam_media_violations_created_at', table_name='scam_media_violations')
    op.drop_index('ix_scam_media_violations_chat_user', table_name='scam_media_violations')
    op.drop_index('ix_scam_media_violations_user_id', table_name='scam_media_violations')
    op.drop_index('ix_scam_media_violations_chat_id', table_name='scam_media_violations')
    op.drop_index('ix_scam_media_violations_hash_id', table_name='scam_media_violations')
    # Удаляем таблицу
    op.drop_table('scam_media_violations')

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ banned_image_hashes
    # ============================================================
    op.drop_index('ix_banned_image_hashes_chat_global', table_name='banned_image_hashes')
    op.drop_index('ix_banned_image_hashes_chat_id', table_name='banned_image_hashes')
    op.drop_index('ix_banned_image_hashes_dhash', table_name='banned_image_hashes')
    op.drop_index('ix_banned_image_hashes_phash', table_name='banned_image_hashes')
    op.drop_table('banned_image_hashes')

    # ============================================================
    # УДАЛЕНИЕ ТАБЛИЦЫ scam_media_settings
    # ============================================================
    op.drop_table('scam_media_settings')
