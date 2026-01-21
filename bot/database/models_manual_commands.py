# ═══════════════════════════════════════════════════════════════════════════
# МОДЕЛИ БАЗЫ ДАННЫХ: Модуль ручных команд (/amute, /aban, /akick)
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит SQLAlchemy модели для хранения настроек модуля
# ручных команд модерации. Админы могут настраивать поведение команд
# /amute, /aban, /akick через UI бота.
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

from sqlalchemy import Column, Integer, BigInteger, Boolean, String
# Импортируем базовый класс для всех моделей
from bot.database.models import Base
# Импортируем миксин для автоматического экспорта настроек при копировании групп
from bot.database.exportable_mixin import ExportableMixin


# ═══════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ РУЧНЫХ КОМАНД МОДЕРАЦИИ
# ═══════════════════════════════════════════════════════════════════════════
# Таблица хранит настройки команд /amute, /aban для каждой группы.
# Каждая группа имеет свои независимые настройки (per-group).
# Все параметры настраиваемые через UI — БЕЗ ХАРДКОДА!
class ManualCommandSettings(Base, ExportableMixin):
    # Имя таблицы в базе данных PostgreSQL
    __tablename__ = 'manual_command_settings'

    # ─── Настройки экспорта ───
    # Ключ в JSON файле экспорта
    __export_key__ = 'manual_command_settings'
    # Колонка с chat_id для фильтрации при экспорте
    __export_chat_id_column__ = 'chat_id'
    # Порядок экспорта: 125 — после AntiRaid (120), перед данными (200+)
    __export_order__ = 125
    # True = одна запись на группу (это настройки, не данные)
    __export_is_settings__ = True

    # ─────────────────────────────────────────────────────────
    # PRIMARY KEY: уникальный идентификатор записи
    # ─────────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True)

    # ─────────────────────────────────────────────────────────
    # CHAT_ID: идентификатор группы
    # ─────────────────────────────────────────────────────────
    # Уникальный — одна запись настроек на группу
    # Индексируем для быстрого поиска по группе
    chat_id = Column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True
    )

    # ═══════════════════════════════════════════════════════════
    # РАЗДЕЛ 1: НАСТРОЙКИ КОМАНДЫ /amute
    # ═══════════════════════════════════════════════════════════

    # Удалять ли сообщение нарушителя при муте
    # По умолчанию True — сообщение удаляется
    mute_delete_message = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Отправлять ли уведомление в группу при муте
    # По умолчанию True — уведомление отправляется
    mute_notify_group = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Время мута по умолчанию в минутах
    # Используется если админ не указал время в команде
    # Дефолт: 1440 минут (24 часа)
    # 0 = навсегда
    mute_default_duration = Column(
        Integer,
        server_default='1440',
        nullable=False
    )

    # Кастомный текст уведомления о муте
    # Доступные переменные: %user%, %time%, %reason%, %admin%
    # NULL = используется стандартный текст
    mute_notify_text = Column(
        String(500),
        nullable=True
    )

    # Задержка удаления сообщения нарушителя (секунды)
    # 0 = удалять сразу, NULL = не удалять
    mute_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # Задержка удаления уведомления о муте (секунды)
    # 0 = не удалять уведомление
    mute_notify_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # ═══════════════════════════════════════════════════════════
    # РАЗДЕЛ 2: НАСТРОЙКИ КОМАНДЫ /aban
    # ═══════════════════════════════════════════════════════════

    # Удалять ли сообщение нарушителя при бане
    # По умолчанию True — сообщение удаляется
    ban_delete_message = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Удалять ли ВСЕ сообщения нарушителя при бане
    # Telegram API позволяет удалить сообщения за последние 48 часов
    # По умолчанию False — удаляется только текущее сообщение
    ban_delete_all_messages = Column(
        Boolean,
        server_default='false',
        nullable=False
    )

    # Отправлять ли уведомление в группу при бане
    # По умолчанию True — уведомление отправляется
    ban_notify_group = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Кастомный текст уведомления о бане
    # Доступные переменные: %user%, %reason%, %admin%
    # NULL = используется стандартный текст
    ban_notify_text = Column(
        String(500),
        nullable=True
    )

    # Задержка удаления сообщения нарушителя (секунды)
    # 0 = удалять сразу
    ban_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # Задержка удаления уведомления о бане (секунды)
    # 0 = не удалять уведомление
    ban_notify_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # ═══════════════════════════════════════════════════════════
    # РАЗДЕЛ 3: НАСТРОЙКИ КОМАНДЫ /akick
    # ═══════════════════════════════════════════════════════════

    # Удалять ли сообщение нарушителя при кике
    # По умолчанию True — сообщение удаляется
    kick_delete_message = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Отправлять ли уведомление в группу при кике
    # По умолчанию True — уведомление отправляется
    kick_notify_group = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    # Кастомный текст уведомления о кике
    # Доступные переменные: %user%, %reason%, %admin%
    # NULL = используется стандартный текст
    kick_notify_text = Column(
        String(500),
        nullable=True
    )

    # Задержка удаления сообщения нарушителя (секунды)
    # 0 = удалять сразу
    kick_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # Задержка удаления уведомления о кике (секунды)
    # 0 = не удалять уведомление
    kick_notify_delete_delay = Column(
        Integer,
        server_default='0',
        nullable=False
    )

    # ═══════════════════════════════════════════════════════════
    # РАЗДЕЛ 4: НАСТРОЙКИ КОМАНДЫ /asend
    # ═══════════════════════════════════════════════════════════

    # Удалять ли команду /asend после отправки сообщения
    # По умолчанию True — команда удаляется
    send_delete_command = Column(
        Boolean,
        server_default='true',
        nullable=False
    )

    def __repr__(self):
        # Строковое представление для отладки
        return (
            f"<ManualCommandSettings(chat_id={self.chat_id}, "
            f"mute_default={self.mute_default_duration}min)>"
        )
