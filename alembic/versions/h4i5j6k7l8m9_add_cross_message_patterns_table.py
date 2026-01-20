"""add_cross_message_patterns_table

Создаёт таблицу для ОТДЕЛЬНЫХ паттернов кросс-сообщение детекции.

Зачем отдельная таблица:
- Текущая реализация использует score от разделов (CustomSectionPattern)
- Паттерны разделов рассчитаны на ОДИН спам-месседж
- При накоплении обычные пользователи могут набрать баллы ("пиши в лс" × 5)
- Нужны паттерны с ДРУГИМИ весами, специфичные для накопления

Таблица cross_message_patterns:
- Отдельная от custom_section_patterns
- Свои веса (обычно НИЖЕ чем в разделах)
- Привязка к chat_id (каждая группа — свои паттерны)
- Поддержка word/phrase/regex типов
- Статистика срабатываний

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-01-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# Уникальный идентификатор этой миграции
revision: str = 'h4i5j6k7l8m9'
# Предыдущая миграция от которой зависит эта
down_revision: Union[str, None] = 'g3h4i5j6k7l8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт таблицу cross_message_patterns."""

    # ═══════════════════════════════════════════════════════════
    # ТАБЛИЦА: ПАТТЕРНЫ КРОСС-СООБЩЕНИЕ ДЕТЕКЦИИ
    # ═══════════════════════════════════════════════════════════
    # Отдельная таблица паттернов, НЕ использующая паттерны разделов!
    # Позволяет настроить веса специально для накопления скора.
    op.create_table(
        'cross_message_patterns',

        # ───────────────────────────────────────────────────────
        # PRIMARY KEY: Автоинкрементный ID
        # ───────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),

        # ───────────────────────────────────────────────────────
        # FOREIGN KEY: ID группы
        # ───────────────────────────────────────────────────────
        # Каждая группа имеет свой независимый набор паттернов
        # ondelete=CASCADE — при удалении группы удаляются и паттерны
        sa.Column(
            'chat_id',
            sa.BigInteger(),
            sa.ForeignKey('groups.chat_id', ondelete='CASCADE'),
            nullable=False,
            index=True
        ),

        # ───────────────────────────────────────────────────────
        # ПАТТЕРН (текст для поиска)
        # ───────────────────────────────────────────────────────
        # Оригинальный паттерн как его ввёл админ
        sa.Column('pattern', sa.String(500), nullable=False),

        # Нормализованная версия для поиска (lowercase, без спецсимволов)
        sa.Column('normalized', sa.String(500), nullable=False, index=True),

        # ───────────────────────────────────────────────────────
        # ТИП ПАТТЕРНА
        # ───────────────────────────────────────────────────────
        # word = как отдельное слово (\b границы)
        # phrase = как подстрока (дефолт)
        # regex = регулярное выражение
        sa.Column(
            'pattern_type',
            sa.String(20),
            server_default='phrase',
            nullable=False
        ),

        # ───────────────────────────────────────────────────────
        # ВЕС ПАТТЕРНА
        # ───────────────────────────────────────────────────────
        # Сколько баллов добавить к накопленному скору
        # ВАЖНО: веса должны быть НИЖЕ чем в разделах!
        # Дефолт: 10 (средний вес)
        sa.Column(
            'weight',
            sa.Integer(),
            server_default='10',
            nullable=False
        ),

        # ───────────────────────────────────────────────────────
        # АКТИВНОСТЬ
        # ───────────────────────────────────────────────────────
        # True = паттерн активен, False = временно отключён
        sa.Column(
            'is_active',
            sa.Boolean(),
            server_default='true',
            nullable=False
        ),

        # ───────────────────────────────────────────────────────
        # СТАТИСТИКА
        # ───────────────────────────────────────────────────────
        # Счётчик срабатываний для аналитики
        sa.Column(
            'triggers_count',
            sa.Integer(),
            server_default='0',
            nullable=False
        ),

        # Когда последний раз сработал
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),

        # ───────────────────────────────────────────────────────
        # АУДИТ
        # ───────────────────────────────────────────────────────
        # ID админа который добавил паттерн
        sa.Column('created_by', sa.BigInteger(), nullable=True),

        # Дата создания
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
    )

    # ═══════════════════════════════════════════════════════════
    # УНИКАЛЬНОЕ ОГРАНИЧЕНИЕ: один паттерн один раз в группе
    # ═══════════════════════════════════════════════════════════
    # Нельзя добавить одинаковый паттерн дважды в одну группу
    op.create_unique_constraint(
        'uq_cross_msg_pattern_chat_pattern',
        'cross_message_patterns',
        ['chat_id', 'pattern']
    )

    # ═══════════════════════════════════════════════════════════
    # СОСТАВНОЙ ИНДЕКС: для быстрого поиска активных паттернов
    # ═══════════════════════════════════════════════════════════
    # Ускоряет: SELECT * FROM cross_message_patterns
    #           WHERE chat_id=X AND is_active=True
    op.create_index(
        'ix_cross_msg_patterns_chat_active',
        'cross_message_patterns',
        ['chat_id', 'is_active']
    )


def downgrade() -> None:
    """Удаляет таблицу cross_message_patterns."""

    # Удаляем индекс
    op.drop_index('ix_cross_msg_patterns_chat_active', 'cross_message_patterns')

    # Удаляем уникальное ограничение
    op.drop_constraint(
        'uq_cross_msg_pattern_chat_pattern',
        'cross_message_patterns',
        type_='unique'
    )

    # Удаляем таблицу
    op.drop_table('cross_message_patterns')
