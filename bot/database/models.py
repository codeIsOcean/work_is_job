from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 👤 Пользователи
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    language_code = Column(String, nullable=True)
    is_bot = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    added_to_attachment_menu = Column(Boolean, default=False)
    can_join_groups = Column(Boolean, default=True)
    can_read_all_group_messages = Column(Boolean, default=False)
    supports_inline_queries = Column(Boolean, default=False)
    can_connect_to_business = Column(Boolean, default=False)
    has_main_web_app = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    groups = relationship("Group", back_populates="creator", foreign_keys="Group.creator_user_id")
    added_groups = relationship("Group", back_populates="added_by", foreign_keys="Group.added_by_user_id")
    user_groups = relationship("UserGroup", back_populates="user", cascade="all, delete")


# 🏠 Группы
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String, nullable=False)
    creator_user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    added_by_user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    bot_id = Column(BigInteger, nullable=True)  # ID бота для проверки прав

    creator = relationship("User", back_populates="groups", foreign_keys=[creator_user_id])
    added_by = relationship("User", back_populates="added_groups", foreign_keys=[added_by_user_id])
    user_groups = relationship("UserGroup", back_populates="group", cascade="all, delete")


# 🔁 Связь многие-ко-многим между User и Group
# Хранение информации о том, какие пользователи являются администраторами в каких группах
# Отслеживание прав доступа к управлению группой
# Когда бот добавляется в группу, он сохраняет всех администраторов группы в эту таблицу, создавая для каждого
# администратора запись, связывающую его user_id с group_id группы. На основании этой таблицы бот проверяет права
# пользователей на управление настройками группы.
class UserGroup(Base):
    __tablename__ = "user_group"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="user_groups")
    group = relationship("Group", back_populates="user_groups")

    __table_args__ = (
        Index('ix_user_group_unique', 'user_id', 'group_id', unique=True),
    )


# ⚙️ Настройки капчи
class CaptchaSettings(Base):
    __tablename__ = "captcha_settings"

    group_id = Column(BigInteger, ForeignKey("groups.chat_id"), primary_key=True)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    # добавлен на 07.06.25 для включения капчи
    is_visual_enabled = Column(Boolean, default=False)

    group = relationship("Group")


# ✅ Ответы на капчу
class CaptchaAnswer(Base):
    __tablename__ = "captcha_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id"), index=True)
    answer = Column(String(50))
    expires_at = Column(DateTime, index=True)

    __table_args__ = (
        Index('idx_user_chat', 'user_id', 'chat_id'),
    )


# 💬 Сообщения с капчей
class CaptchaMessageId(Base):
    __tablename__ = "captcha_message_ids"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id"), index=True)
    message_id = Column(BigInteger)
    expires_at = Column(DateTime, index=True)

    __table_args__ = (
        Index('idx_user_chat_msg', 'user_id', 'chat_id'),
    )


class TimeoutMessageId(Base):
    __tablename__ = "timeout_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    chat_id = Column(BigInteger)
    message_id = Column(BigInteger)
    created_at = Column(DateTime, default=utcnow)


class GroupUsers(Base):
    __tablename__ = 'group_users'

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    joined_at = Column(DateTime, default=utcnow)
    last_activity = Column(DateTime, default=utcnow)
    is_admin = Column(Boolean, default=False)
    is_creator = Column(Boolean, default=False)  # Является ли создателем группы
    can_view_admins = Column(Boolean, default=True)  # Право просмотра администраторов
    # Связи с другими таблицами
    user = relationship("User", backref="group_memberships")
    group = relationship("Group", backref="members")

    # Уникальный индекс для пары user_id и chat_id
    __table_args__ = (
        UniqueConstraint('user_id', 'chat_id', name='uix_user_chat'),
    )


# ⚙️ Настройки чата (включение фильтров, параметры мута и пр.)
class ChatSettings(Base):
    __tablename__ = "chat_settings"

    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), primary_key=True)
    # Username публичной группы (для поиска по deep link). Может быть NULL для приватных чатов.
    username = Column(String, nullable=True)
    enable_photo_filter = Column(Boolean, default=False)
    admins_bypass_photo_filter = Column(Boolean, default=False)
    photo_filter_mute_minutes = Column(Integer, default=60)
    mute_new_members = Column(Boolean, default=False)
    auto_mute_scammers = Column(Boolean, default=True)  # Автомут скаммеров
    global_mute_enabled = Column(Boolean, default=False)  # Глобальный мут для всех групп
    reaction_mute_enabled = Column(Boolean, default=False)
    reaction_mute_announce_enabled = Column(Boolean, default=True)
    captcha_join_enabled = Column(Boolean, default=False)
    captcha_invite_enabled = Column(Boolean, default=False)
    captcha_timeout_seconds = Column(Integer, default=300)
    captcha_message_ttl_seconds = Column(Integer, default=900)
    captcha_flood_threshold = Column(Integer, default=5)
    captcha_flood_window_seconds = Column(Integer, default=180)
    captcha_flood_action = Column(String(16), default="warn")
    system_mute_announcements_enabled = Column(Boolean, default=True)
    # Время жизни предупреждений антиспам в секундах (0 = не удалять)
    antispam_warning_ttl_seconds = Column(Integer, default=0)

    group = relationship("Group")


# 🚫 Ограничения пользователей (муты, причины, срок действия)
class UserRestriction(Base):
    __tablename__ = "user_restrictions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False)
    restriction_type = Column(String(50), nullable=False)  # mute, ban и т.п.
    reason = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_user_restriction_user_chat", "user_id", "chat_id"),
    )


# 🎭 Отслеживание скаммеров и непрошедших капчу
class ScammerTracker(Base):
    __tablename__ = "scammer_tracker"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    
    # Тип нарушения
    violation_type = Column(String(50), nullable=False)  # captcha_failed, spam, suspicious_behavior
    violation_count = Column(Integer, default=1)  # Количество нарушений
    
    # Статус пользователя
    is_scammer = Column(Boolean, default=False)  # Является ли скаммером
    scammer_level = Column(Integer, default=0)  # Уровень скаммера (0-5)
    
    # Временные метки
    first_violation_at = Column(DateTime, default=utcnow)
    last_violation_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    # Дополнительная информация
    notes = Column(String, nullable=True)  # Заметки администратора
    is_whitelisted = Column(Boolean, default=False)  # В белом списке

    group = relationship("Group")

    __table_args__ = (
        Index('idx_scammer_user_chat', 'user_id', 'chat_id'),
        Index('idx_scammer_level', 'scammer_level'),
        Index('idx_scammer_violation_type', 'violation_type'),
        UniqueConstraint('user_id', 'chat_id', name='uix_scammer_user_chat'),
    )


# 🤖 Права ботов в группах
class BotPermissions(Base):
    __tablename__ = "bot_permissions"

    id = Column(Integer, primary_key=True)
    bot_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False)
    can_manage_chat = Column(Boolean, default=False)
    can_delete_messages = Column(Boolean, default=False)
    can_restrict_members = Column(Boolean, default=False)
    can_promote_members = Column(Boolean, default=False)
    can_invite_users = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    group = relationship("Group")

    __table_args__ = (
        UniqueConstraint('bot_id', 'chat_id', name='uix_bot_chat'),
        Index("ix_bot_permissions_bot_chat", "bot_id", "chat_id"),
    )


# 🖼️ Визуальная капча
class VisualCaptcha(Base):
    __tablename__ = "visual_captcha"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False, index=True)
    answer = Column(String(10), nullable=False)  # Правильный ответ
    message_id = Column(BigInteger, nullable=True)  # ID сообщения с капчей
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)

    group = relationship("Group")

    __table_args__ = (
        Index('idx_visual_captcha_user_chat', 'user_id', 'chat_id'),
        Index('idx_visual_captcha_expires', 'expires_at'),
    )


# 📢 Журнал действий для групп
class GroupJournalChannel(Base):
    __tablename__ = "group_journal_channels"

    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    journal_channel_id = Column(BigInteger, nullable=False)  # ID канала/группы для журнала
    journal_type = Column(String(20), default="channel")  # channel или group
    journal_title = Column(String, nullable=True)  # Название канала для отображения
    is_active = Column(Boolean, default=True)
    linked_at = Column(DateTime, default=utcnow)
    linked_by_user_id = Column(BigInteger, nullable=True)  # Кто привязал
    last_event_at = Column(DateTime, nullable=True)  # Время последнего события

    group = relationship("Group")

    __table_args__ = (
        Index('ix_group_journal_group_id', 'group_id'),
        Index('ix_group_journal_channel_id', 'journal_channel_id'),
    )

# Ensure additional models are registered with SQLAlchemy metadata
import importlib

# Импортируем дополнительные модели для регистрации в SQLAlchemy metadata
importlib.import_module("bot.database.mute_models")
# Импортируем модели антиспам для регистрации в SQLAlchemy metadata
importlib.import_module("bot.database.models_antispam")
# Импортируем модели content_filter для регистрации в SQLAlchemy metadata
importlib.import_module("bot.database.models_content_filter")