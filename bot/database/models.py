from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

# Импортируем миксин для автоматического экспорта моделей
from bot.database.exportable_mixin import ExportableMixin


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
class CaptchaSettings(Base, ExportableMixin):
    __tablename__ = "captcha_settings"

    # ─── Настройки экспорта ───
    __export_key__ = 'captcha_settings'
    __export_exclude__ = ('created_at',)
    __export_is_settings__ = True
    __export_chat_id_column__ = 'group_id'
    __export_order__ = 20

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
class ChatSettings(Base, ExportableMixin):
    __tablename__ = "chat_settings"

    # ─── Настройки экспорта ───
    __export_key__ = 'chat_settings'
    __export_exclude__ = ('username',)  # username - идентификатор конкретной группы
    __export_is_settings__ = True
    __export_order__ = 10  # Основные настройки - импортируются первыми

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
    # По умолчанию НЕ отправлять сообщения в группу о муте по реакции
    # (информация идёт только в журнал активности)
    reaction_mute_announce_enabled = Column(Boolean, default=False)
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

    # ═══════════════════════════════════════════════════════════════════════════
    # РЕДИЗАЙН КАПЧИ: Три режима с раздельными настройками
    # ═══════════════════════════════════════════════════════════════════════════

    # Visual Captcha (ЛС) - капча отправляется в личные сообщения
    # Работает только если в группе включён режим "Join Requests"
    # NULL = не настроено, админ должен включить и настроить
    visual_captcha_enabled = Column(Boolean, nullable=True)

    # Таймаут для Visual Captcha (секунды)
    # Сколько времени пользователь может решать капчу в ЛС
    # NULL = админ введёт значение при включении режима
    visual_captcha_timeout_seconds = Column(Integer, nullable=True)

    # Таймаут для Join Captcha (секунды)
    # Капча в группе при самостоятельном входе (открытые группы)
    # NULL = админ введёт значение при включении режима
    join_captcha_timeout_seconds = Column(Integer, nullable=True)

    # Таймаут для Invite Captcha (секунды)
    # Капча в группе когда пользователя пригласили
    # NULL = админ введёт значение при включении режима
    invite_captcha_timeout_seconds = Column(Integer, nullable=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # АВТОУДАЛЕНИЕ СООБЩЕНИЙ КАПЧИ В ГРУППЕ
    # Через сколько секунд удалить сообщение капчи из группы
    # ═══════════════════════════════════════════════════════════════════════════

    # TTL сообщения Join Captcha в группе (секунды)
    # Через сколько секунд автоматически удалить сообщение капчи из группы
    # NULL = использовать дефолт (300 секунд = 5 минут)
    join_captcha_message_ttl_seconds = Column(Integer, nullable=True)

    # TTL сообщения Invite Captcha в группе (секунды)
    # Через сколько секунд автоматически удалить сообщение капчи из группы
    # NULL = использовать дефолт (300 секунд = 5 минут)
    invite_captcha_message_ttl_seconds = Column(Integer, nullable=True)

    # Максимум одновременных капч в группе
    # Предотвращает накопление сообщений при массовом входе
    # NULL = админ введёт значение при включении капчи
    captcha_max_pending = Column(Integer, nullable=True)

    # Действие при превышении лимита капч
    # Варианты: "remove_oldest" | "auto_decline" | "queue"
    # NULL = админ выберет при настройке
    captcha_overflow_action = Column(String(32), nullable=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # НАСТРОЙКИ ДИАЛОГОВ КАПЧИ
    # Применяются ко всем режимам капчи (Join Request, Join, Invite)
    # ═══════════════════════════════════════════════════════════════════════════

    # Разрешён ли ручной ввод ответа через FSM
    # True = пользователь может ввести ответ текстом
    # False = только кнопки
    # NULL = использовать дефолт (True)
    captcha_manual_input_enabled = Column(Boolean, nullable=True)

    # Количество кнопок с вариантами ответов
    # Допустимые значения: 4, 6, 9
    # 6 кнопок - баланс между удобством и защитой (42% угадывания за 3 попытки)
    # NULL = использовать дефолт (6)
    captcha_button_count = Column(Integer, nullable=True)

    # Максимум попыток решения капчи
    # После исчерпания - капча провалена
    # NULL = использовать дефолт (3)
    captcha_max_attempts = Column(Integer, nullable=True)

    # Через сколько секунд напоминать о капче
    # 0 = напоминания выключены
    # NULL = использовать дефолт (60 секунд)
    captcha_reminder_seconds = Column(Integer, nullable=True)

    # Сколько напоминаний отправлять
    # 0 = безлимит (до истечения таймаута капчи)
    # NULL = использовать дефолт (3 напоминания)
    captcha_reminder_count = Column(Integer, nullable=True)

    # Через сколько секунд чистить диалог после завершения капчи
    # Удаляет все сообщения и очищает FSM состояние
    # NULL = использовать дефолт (120 секунд = 2 минуты)
    captcha_dialog_cleanup_seconds = Column(Integer, nullable=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # ДЕЙСТВИЕ ПРИ ПРОВАЛЕ КАПЧИ (Visual DM)
    # ═══════════════════════════════════════════════════════════════════════════

    # Действие при провале/таймауте капчи для Visual DM режима
    # "keep" = оставить заявку висеть (заявка остаётся в списке, админ может одобрить
    #          вручную или пользователь может попробовать капчу снова)
    # "decline" = отклонить заявку (заявка удаляется из Telegram, пользователь должен
    #             повторно подать заявку чтобы попробовать ещё раз)
    # NULL = использовать дефолт ("keep" - старое поведение, заявки продолжают висеть)
    captcha_failure_action = Column(String(16), nullable=True)

    group = relationship("Group")


# 🚫 Ограничения пользователей (муты, причины, срок действия)
class UserRestriction(Base):
    """
    Хранит все ограничения (муты/баны), применённые к пользователям.
    Используется для восстановления мута после повторного входа через капчу.
    """
    __tablename__ = "user_restrictions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False)
    restriction_type = Column(String(50), nullable=False)  # mute, ban, kick
    reason = Column(String(50), nullable=True)  # antispam, content_filter, reaction, manual, risk_gate
    restricted_by = Column(BigInteger, nullable=True)  # bot ID или admin user_id
    until_date = Column(DateTime, nullable=True)  # NULL = бессрочно (заменяет expires_at)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_user_restriction_user_chat", "user_id", "chat_id"),
        Index("ix_user_restrictions_active", "is_active"),
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