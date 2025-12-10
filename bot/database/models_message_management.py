# ============================================================
# МОДЕЛЬ НАСТРОЕК УПРАВЛЕНИЯ СООБЩЕНИЯМИ
# ============================================================
# Этот файл содержит SQLAlchemy модель для хранения настроек
# модуля "Управление сообщениями":
# - Удаление команд (от админов и пользователей)
# - Удаление системных сообщений (вход, выход, закреп, фото)
# - Репин (автозакрепление сообщения)
# ============================================================

# Импортируем базовые типы SQLAlchemy для определения колонок
from sqlalchemy import (
    Column,          # Для определения колонок таблицы
    Integer,         # Целочисленный тип
    BigInteger,      # Большие целые числа (для Telegram ID)
    Boolean,         # Логический тип (True/False)
    DateTime,        # Дата и время
)

# Импортируем datetime для значений по умолчанию
from datetime import datetime

# Импортируем базовый класс из session.py
# Base — это declarative_base() от SQLAlchemy
from bot.database.session import Base


class MessageManagementSettings(Base):
    """
    Модель настроек управления сообщениями для группы.

    Каждая группа имеет одну запись с настройками.
    Настройки определяют какие сообщения удалять автоматически
    и включён ли репин (автозакрепление).

    Attributes:
        id: Первичный ключ записи
        chat_id: ID группы (уникальный, одна запись на группу)

        # Удаление команд
        delete_admin_commands: Удалять команды /xxx от админов
        delete_user_commands: Удалять команды /xxx от пользователей

        # Системные сообщения
        delete_join_messages: Удалять сообщения о входе участников
        delete_leave_messages: Удалять сообщения о выходе участников
        delete_pin_messages: Удалять уведомления о закрепе
        delete_chat_photo_messages: Удалять сообщения об изменении фото/названия

        # Репин
        repin_enabled: Включён ли автозакреп
        repin_message_id: ID сообщения которое нужно перезакреплять

        # Метаданные
        created_at: Дата создания записи
        updated_at: Дата последнего обновления
    """

    # Имя таблицы в БД (snake_case, множественное число)
    __tablename__ = 'message_management_settings'

    # ─────────────────────────────────────────────────────────
    # ПЕРВИЧНЫЙ КЛЮЧ
    # ─────────────────────────────────────────────────────────
    # Автоинкрементный ID записи
    id = Column(
        Integer,
        primary_key=True,
        comment="Первичный ключ"
    )

    # ─────────────────────────────────────────────────────────
    # ID ГРУППЫ (уникальный)
    # ─────────────────────────────────────────────────────────
    # BigInteger потому что Telegram ID могут быть большими числами
    # unique=True — одна запись на группу
    # nullable=False — обязательное поле
    # index=True — индекс для быстрого поиска по chat_id
    chat_id = Column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
        comment="ID группы (Telegram chat_id)"
    )

    # ─────────────────────────────────────────────────────────
    # УДАЛЕНИЕ КОМАНД
    # ─────────────────────────────────────────────────────────
    # Удалять команды /xxx от администраторов
    # По умолчанию False — админские команды не удаляются
    delete_admin_commands = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять команды от админов"
    )

    # Удалять команды /xxx от обычных пользователей
    # По умолчанию False — пользовательские команды не удаляются
    delete_user_commands = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять команды от пользователей"
    )

    # ─────────────────────────────────────────────────────────
    # СИСТЕМНЫЕ СООБЩЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Удалять сообщения "Пользователь вступил в группу"
    delete_join_messages = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять сообщения о входе участников"
    )

    # Удалять сообщения "Пользователь покинул группу"
    delete_leave_messages = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять сообщения о выходе участников"
    )

    # Удалять уведомления о закреплении сообщений
    delete_pin_messages = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять уведомления о закрепе"
    )

    # Удалять сообщения об изменении фото/названия группы
    delete_chat_photo_messages = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Удалять сообщения об изменении фото/названия"
    )

    # ─────────────────────────────────────────────────────────
    # РЕПИН (АВТОЗАКРЕПЛЕНИЕ)
    # ─────────────────────────────────────────────────────────
    # Включён ли автозакреп
    # Если True — при закрепе другого сообщения бот перезакрепит repin_message_id
    repin_enabled = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Включён ли автозакреп"
    )

    # ID сообщения которое нужно перезакреплять
    # nullable=True — может быть не задано
    # Задаётся командой /repin в ответ на сообщение
    repin_message_id = Column(
        BigInteger,
        nullable=True,
        comment="ID сообщения для автозакрепа"
    )

    # ─────────────────────────────────────────────────────────
    # МЕТАДАННЫЕ
    # ─────────────────────────────────────────────────────────
    # Дата создания записи (автоматически при INSERT)
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        comment="Дата создания"
    )

    # Дата последнего обновления (автоматически при UPDATE)
    updated_at = Column(
        DateTime,
        onupdate=datetime.utcnow,
        comment="Дата обновления"
    )

    def __repr__(self) -> str:
        """
        Строковое представление объекта для отладки.

        Returns:
            str: Информация о настройках группы
        """
        return (
            f"<MessageManagementSettings("
            f"chat_id={self.chat_id}, "
            f"del_admin_cmd={self.delete_admin_commands}, "
            f"del_user_cmd={self.delete_user_commands}, "
            f"repin={self.repin_enabled}"
            f")>"
        )
