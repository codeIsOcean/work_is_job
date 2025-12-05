# Импорт функции для создания колонок таблицы
from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Boolean, Enum as SQLEnum, Text, Index
# Импорт функции для создания отношений между таблицами
from sqlalchemy.orm import relationship
# Импорт базового класса для всех моделей
from bot.database.models import Base, utcnow
# Импорт enum для типобезопасного определения констант
import enum


# ============================================================
# ENUM ТИПЫ ДЛЯ АНТИСПАМ ПРАВИЛ
# ============================================================

# Enum для типов правил антиспам - определяет какой тип контента проверяется
class RuleType(str, enum.Enum):
    # Правило для ссылок на Telegram (t.me, telegram.me, tg://)
    TELEGRAM_LINK = "TELEGRAM_LINK"
    # Правило для любых HTTP/HTTPS ссылок
    ANY_LINK = "ANY_LINK"
    # Правило для пересылок из каналов
    FORWARD_CHANNEL = "FORWARD_CHANNEL"
    # Правило для пересылок из групп
    FORWARD_GROUP = "FORWARD_GROUP"
    # Правило для пересылок от пользователей
    FORWARD_USER = "FORWARD_USER"
    # Правило для пересылок от ботов
    FORWARD_BOT = "FORWARD_BOT"
    # Правило для цитат из каналов
    QUOTE_CHANNEL = "QUOTE_CHANNEL"
    # Правило для цитат из групп
    QUOTE_GROUP = "QUOTE_GROUP"
    # Правило для цитат от пользователей
    QUOTE_USER = "QUOTE_USER"
    # Правило для цитат от ботов
    QUOTE_BOT = "QUOTE_BOT"


# Enum для действий при срабатывании правила антиспам
class ActionType(str, enum.Enum):
    # Правило выключено, никаких действий не предпринимается
    OFF = "OFF"
    # Только удалить сообщение, без наказания пользователя
    DELETE = "DELETE"
    # Отправить предупреждение пользователю, но не ограничивать
    WARN = "WARN"
    # Исключить пользователя из группы (kick)
    KICK = "KICK"
    # Ограничить пользователя (mute) на определённое время
    RESTRICT = "RESTRICT"
    # Заблокировать пользователя навсегда (ban)
    BAN = "BAN"


# Enum для областей применения белого списка
class WhitelistScope(str, enum.Enum):
    # Белый список для ссылок на Telegram
    TELEGRAM_LINK = "TELEGRAM_LINK"
    # Белый список для любых ссылок
    ANY_LINK = "ANY_LINK"
    # Белый список для пересылок (по ID канала/группы/бота)
    FORWARD = "FORWARD"
    # Белый список для цитат (по ID канала/группы/бота)
    QUOTE = "QUOTE"


# ============================================================
# МОДЕЛЬ: ПРАВИЛА АНТИСПАМ
# ============================================================

# Таблица для хранения правил антиспам для каждой группы
class AntiSpamRule(Base):
    # Имя таблицы в базе данных
    __tablename__ = "antispam_rules"

    # Уникальный идентификатор правила (первичный ключ)
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ID чата (группы) к которой применяется правило
    # Внешний ключ на таблицу groups, при удалении группы правила тоже удаляются
    chat_id = Column(
        BigInteger,
        ForeignKey("groups.chat_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Тип правила (ссылки Telegram, любые ссылки, пересылки, цитаты и т.д.)
    # Используется SQLEnum для хранения enum в БД
    rule_type = Column(
        SQLEnum(RuleType, name="rule_type_enum", create_type=True),
        nullable=False,
        index=True
    )

    # Действие при срабатывании правила (выкл, предупреждение, кик, мут, бан)
    action = Column(
        SQLEnum(ActionType, name="action_type_enum", create_type=True),
        nullable=False,
        default=ActionType.OFF
    )

    # Флаг: удалять ли сообщение при срабатывании правила
    delete_message = Column(Boolean, default=False, nullable=False)

    # Длительность ограничения в минутах (используется только если action=RESTRICT)
    # NULL если действие не требует длительности
    restrict_minutes = Column(Integer, nullable=True)

    # Дата и время создания правила
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Дата и время последнего обновления правила
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Связь с таблицей групп (Many-to-One: много правил для одной группы)
    group = relationship("Group", backref="antispam_rules")

    # Определение индексов для оптимизации запросов
    __table_args__ = (
        # Составной индекс для быстрого поиска правил по группе и типу
        Index("ix_antispam_rules_chat_rule", "chat_id", "rule_type"),
        # Индекс для поиска активных правил (где action не OFF)
        Index("ix_antispam_rules_action", "action"),
    )


# ============================================================
# МОДЕЛЬ: БЕЛЫЙ СПИСОК АНТИСПАМ
# ============================================================

# Таблица для хранения исключений (белого списка) для антиспам правил
class AntiSpamWhitelist(Base):
    # Имя таблицы в базе данных
    __tablename__ = "antispam_whitelist"

    # Уникальный идентификатор записи белого списка (первичный ключ)
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ID чата (группы) для которой применяется исключение
    # Внешний ключ на таблицу groups, при удалении группы записи тоже удаляются
    chat_id = Column(
        BigInteger,
        ForeignKey("groups.chat_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Область применения исключения (для каких правил действует)
    scope = Column(
        SQLEnum(WhitelistScope, name="whitelist_scope_enum", create_type=True),
        nullable=False,
        index=True
    )

    # Паттерн для проверки (часть URL, домен или ID канала/группы)
    # Примеры: "t.me/mygroup", "youtube.com", "-1001234567890"
    # Используется Text для возможности хранить длинные строки
    pattern = Column(Text, nullable=False)

    # ID пользователя (администратора) который добавил запись в белый список
    added_by = Column(BigInteger, nullable=False)

    # Дата и время добавления записи в белый список
    added_at = Column(DateTime, default=utcnow, nullable=False)

    # Связь с таблицей групп (Many-to-One: много записей белого списка для одной группы)
    group = relationship("Group", backref="antispam_whitelist")

    # Определение индексов для оптимизации запросов
    __table_args__ = (
        # Составной индекс для быстрого поиска записей белого списка по группе и области
        Index("ix_antispam_whitelist_chat_scope", "chat_id", "scope"),
        # Индекс для поиска по паттерну (для избежания дубликатов)
        Index("ix_antispam_whitelist_pattern", "pattern", postgresql_ops={"pattern": "text_pattern_ops"}),
    )
