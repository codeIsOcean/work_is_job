"""add captcha dialog settings

Добавляет новые колонки для "Настроек диалогов" капчи:
- captcha_manual_input_enabled: разрешён ли ручной ввод ответа (FSM)
- captcha_button_count: количество кнопок с вариантами (4, 6, 9)
- captcha_max_attempts: максимум попыток решения капчи
- captcha_reminder_seconds: через сколько секунд напоминать
- captcha_dialog_cleanup_seconds: через сколько секунд чистить диалог

Дефолтные значения (согласованы с админом):
- manual_input: True (включён)
- button_count: 6
- max_attempts: 3
- reminder: 60 сек
- cleanup: 120 сек (2 мин)

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2025-12-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизий для Alembic
# Уникальный ID этой миграции
revision: str = "r8s9t0u1v2w3"
# Предыдущая миграция в цепочке (captcha redesign columns)
down_revision: Union[str, None] = "q7r8s9t0u1v2"
# Нет веток - линейная цепочка миграций
branch_labels: Union[str, Sequence[str], None] = None
# Нет зависимостей от других миграций
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет колонки для настроек диалогов капчи.

    Эти настройки применяются ко ВСЕМ режимам капчи:
    - Join Request Captcha (ЛС)
    - Join Captcha (группа)
    - Invite Captcha (группа)
    """

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_manual_input_enabled - разрешает ручной ввод ответа
    # Если True - пользователь может ввести ответ текстом через FSM
    # Если False - только кнопки
    # NULL = использовать дефолт (True)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_manual_input_enabled",
            sa.Boolean(),
            # NULL = не настроено, дефолт True в коде
            nullable=True,
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_button_count - количество кнопок с вариантами ответов
    # Допустимые значения: 4, 6, 9
    # 6 кнопок - баланс между удобством и защитой
    # NULL = использовать дефолт (6)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_button_count",
            sa.Integer(),
            # NULL = не настроено, дефолт 6 в коде
            nullable=True,
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_max_attempts - максимум попыток решения капчи
    # После исчерпания попыток - капча провалена
    # Допустимые значения: 2, 3, 5 или любое через ручной ввод
    # NULL = использовать дефолт (3)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_max_attempts",
            sa.Integer(),
            # NULL = не настроено, дефолт 3 в коде
            nullable=True,
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_reminder_seconds - через сколько секунд напоминать
    # Отправляет напоминание пользователю о необходимости решить капчу
    # 0 = напоминания выключены
    # NULL = использовать дефолт (60 секунд)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_reminder_seconds",
            sa.Integer(),
            # NULL = не настроено, дефолт 60 в коде
            # 0 = выключено
            nullable=True,
        ),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # captcha_dialog_cleanup_seconds - через сколько секунд чистить диалог
    # После завершения капчи (успех или провал) удаляет все сообщения
    # и очищает FSM состояние
    # NULL = использовать дефолт (120 секунд = 2 минуты)
    # ═══════════════════════════════════════════════════════════════════════
    op.add_column(
        "chat_settings",
        sa.Column(
            "captcha_dialog_cleanup_seconds",
            sa.Integer(),
            # NULL = не настроено, дефолт 120 в коде
            nullable=True,
        ),
    )


def downgrade() -> None:
    """
    Откатывает миграцию - удаляет добавленные колонки.
    Порядок удаления обратный порядку добавления.
    """

    # Удаляем колонки в обратном порядке добавления
    op.drop_column("chat_settings", "captcha_dialog_cleanup_seconds")
    op.drop_column("chat_settings", "captcha_reminder_seconds")
    op.drop_column("chat_settings", "captcha_max_attempts")
    op.drop_column("chat_settings", "captcha_button_count")
    op.drop_column("chat_settings", "captcha_manual_input_enabled")
