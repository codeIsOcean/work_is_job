# ============================================================
# МОДЕЛИ БАЗЫ ДАННЫХ ДЛЯ МОДУЛЯ PROFILE MONITOR
# ============================================================
# Этот файл содержит все SQLAlchemy модели для мониторинга профилей:
# - ProfileMonitorSettings: настройки модуля для каждой группы
# - ProfileChangeLog: журнал изменений профиля пользователей
# - ProfileSnapshot: снимок профиля при входе в группу
# ============================================================

# Импортируем Column для определения колонок таблицы
from sqlalchemy import Column
# Импортируем типы данных для колонок
from sqlalchemy import Integer, String, BigInteger, Boolean, DateTime, Text
# Импортируем ForeignKey для связей между таблицами
from sqlalchemy import ForeignKey
# Импортируем Index для создания индексов (ускорение поиска)
from sqlalchemy import Index
# Импортируем relationship для связей ORM
from sqlalchemy.orm import relationship

# Импортируем базовый класс Base и функцию utcnow из основных моделей
# Base - базовый класс от которого наследуются все модели
# utcnow - функция возвращающая текущее UTC время
from bot.database.models import Base, utcnow

# Импортируем миксин для автоматического экспорта моделей
from bot.database.exportable_mixin import ExportableMixin


# ============================================================
# МОДЕЛЬ: НАСТРОЙКИ PROFILE MONITOR ДЛЯ ГРУППЫ
# ============================================================
# Хранит все настройки модуля мониторинга для конкретной группы
# Каждая группа имеет свои независимые настройки (мультитенантность)
class ProfileMonitorSettings(Base, ExportableMixin):
    # Имя таблицы в базе данных PostgreSQL
    __tablename__ = 'profile_monitor_settings'

    # ─── Настройки экспорта ───
    __export_key__ = 'profile_monitor_settings'
    __export_is_settings__ = True
    __export_order__ = 110

    # ─────────────────────────────────────────────────────────
    # PRIMARY KEY: ID группы (chat_id)
    # ─────────────────────────────────────────────────────────
    # Используем chat_id как первичный ключ (одна запись на группу)
    # ForeignKey связывает с таблицей groups
    # ondelete="CASCADE" - при удалении группы удаляются и настройки
    chat_id = Column(
        BigInteger,
        ForeignKey("groups.chat_id", ondelete="CASCADE"),
        primary_key=True
    )

    # ─────────────────────────────────────────────────────────
    # ГЛОБАЛЬНЫЙ ПЕРЕКЛЮЧАТЕЛЬ МОДУЛЯ
    # ─────────────────────────────────────────────────────────
    # True = модуль включён, False = выключен
    # По умолчанию выключен - админ должен явно включить
    enabled = Column(Boolean, default=False, nullable=False)

    # ─────────────────────────────────────────────────────────
    # НАСТРОЙКИ ЛОГИРОВАНИЯ
    # ─────────────────────────────────────────────────────────
    # Логировать изменение имени (first_name + last_name)
    log_name_changes = Column(Boolean, default=True, nullable=False)

    # Логировать изменение username (@username)
    log_username_changes = Column(Boolean, default=True, nullable=False)

    # Логировать изменение фото профиля
    log_photo_changes = Column(Boolean, default=True, nullable=False)

    # ─────────────────────────────────────────────────────────
    # АВТОМУТ: КРИТЕРИЙ 1 - НЕТ ФОТО + МОЛОДОЙ АККАУНТ
    # ─────────────────────────────────────────────────────────
    # Включить автомут для аккаунтов без фото и младше N дней
    auto_mute_no_photo_young = Column(Boolean, default=True, nullable=False)

    # Порог возраста аккаунта в днях (по умолчанию 15 дней)
    # Если нет фото И аккаунт моложе этого порога → мут навсегда
    auto_mute_account_age_days = Column(Integer, default=15, nullable=False)

    # Удалять все сообщения спаммера при автомуте
    auto_mute_delete_messages = Column(Boolean, default=True, nullable=False)

    # ─────────────────────────────────────────────────────────
    # АВТОМУТ: КРИТЕРИЙ 2 - НЕТ ФОТО + СМЕНА ИМЕНИ + БЫСТРЫЕ СООБЩЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Включить автомут для смены имени + быстрых сообщений без фото
    auto_mute_name_change_fast_msg = Column(Boolean, default=True, nullable=False)

    # Временное окно для смены имени (в часах, по умолчанию 24 часа)
    # Если нет фото И имя менялось в течение этого времени → проверяем следующий критерий
    name_change_window_hours = Column(Integer, default=24, nullable=False)

    # Временное окно для сообщения после смены профиля (в минутах, по умолчанию 30 минут)
    # Если пользователь сменил имя/фото и написал в течение этого времени → мут
    first_message_window_minutes = Column(Integer, default=30, nullable=False)

    # ─────────────────────────────────────────────────────────
    # АВТОМУТ: КРИТЕРИЙ 4,5 - СВЕЖЕЕ ФОТО
    # ─────────────────────────────────────────────────────────
    # Порог свежести фото в днях (по умолчанию 1 день)
    # Если фото моложе этого порога → считается "свежим" и подозрительным
    # Используется в критериях 4 и 5 для определения смены фото на провокационное
    photo_freshness_threshold_days = Column(Integer, default=1, nullable=False)

    # ─────────────────────────────────────────────────────────
    # АВТОМУТ: КРИТЕРИЙ 6 - ЗАПРЕЩЁННЫЙ КОНТЕНТ В ИМЕНИ/BIO
    # ─────────────────────────────────────────────────────────
    # Включить проверку имени и bio на запрещённый контент из ContentFilter
    # Использует WordFilter с категориями: harmful (наркотики), obfuscated (l33tspeak)
    # Мутит СРАЗУ при обнаружении, не ждёт сообщения
    # Действие берётся из ContentFilter (мут/бан/кик + длительность)
    auto_mute_forbidden_content = Column(Boolean, default=False, nullable=False)

    # ─────────────────────────────────────────────────────────
    # НАСТРОЙКИ УВЕДОМЛЕНИЙ В ЖУРНАЛ
    # ─────────────────────────────────────────────────────────
    # Отправлять уведомления в журнал группы (GroupJournalChannel)
    send_to_journal = Column(Boolean, default=True, nullable=False)

    # Минимальное количество изменений для отправки в журнал
    # 1 = отправлять каждое изменение, 2+ = только если несколько изменений
    min_changes_for_journal = Column(Integer, default=1, nullable=False)

    # Отправлять простые уведомления в саму группу (для всех участников)
    # Формат: "Пользователь X сменил имя на Y" + история имен
    # По умолчанию выключено - включается админом через настройки
    send_to_group = Column(Boolean, default=False, nullable=False)

    # ─────────────────────────────────────────────────────────
    # ВРЕМЕННЫЕ МЕТКИ
    # ─────────────────────────────────────────────────────────
    # Когда настройки были созданы
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Когда настройки были последний раз обновлены
    # onupdate=utcnow автоматически обновляет при изменении записи
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # ─────────────────────────────────────────────────────────
    # СВЯЗИ ORM
    # ─────────────────────────────────────────────────────────
    # Связь с таблицей Group для удобного доступа к данным группы
    group = relationship("Group", backref="profile_monitor_settings")


# ============================================================
# МОДЕЛЬ: СНИМОК ПРОФИЛЯ ПРИ ВХОДЕ
# ============================================================
# Хранит снимок профиля пользователя в момент входа в группу
# Используется для сравнения и определения изменений
class ProfileSnapshot(Base):
    # Имя таблицы в базе данных
    __tablename__ = 'profile_snapshots'

    # ─────────────────────────────────────────────────────────
    # PRIMARY KEY: Автоинкрементный ID
    # ─────────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ─────────────────────────────────────────────────────────
    # ИДЕНТИФИКАТОРЫ
    # ─────────────────────────────────────────────────────────
    # ID группы где пользователь находится
    chat_id = Column(
        BigInteger,
        ForeignKey("groups.chat_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # ID пользователя
    user_id = Column(BigInteger, nullable=False, index=True)

    # ─────────────────────────────────────────────────────────
    # ДАННЫЕ ПРОФИЛЯ
    # ─────────────────────────────────────────────────────────
    # Имя пользователя (first_name)
    first_name = Column(String(256), nullable=True)

    # Фамилия пользователя (last_name)
    last_name = Column(String(256), nullable=True)

    # Полное имя (first_name + last_name)
    full_name = Column(String(512), nullable=True)

    # Username (@username)
    username = Column(String(256), nullable=True)

    # Есть ли фото профиля (True/False)
    has_photo = Column(Boolean, default=False, nullable=False)

    # ID фото профиля (для определения изменения)
    photo_id = Column(String(256), nullable=True)

    # Возраст самого свежего фото профиля в днях (из MTProto)
    # Используется для критериев 4 и 5: если фото "свежее" → подозрительно
    # NULL если фото нет или не удалось получить возраст
    photo_age_days = Column(Integer, nullable=True)

    # ─────────────────────────────────────────────────────────
    # МЕТАДАННЫЕ АККАУНТА
    # ─────────────────────────────────────────────────────────
    # Возраст аккаунта в днях (приблизительный, из MTProto)
    account_age_days = Column(Integer, nullable=True)

    # Дата регистрации аккаунта (если доступна через MTProto)
    account_created_at = Column(DateTime, nullable=True)

    # Является ли Premium аккаунтом
    is_premium = Column(Boolean, default=False, nullable=False)

    # ─────────────────────────────────────────────────────────
    # ВРЕМЕННЫЕ МЕТКИ
    # ─────────────────────────────────────────────────────────
    # Когда пользователь вошёл в группу (создан снимок)
    joined_at = Column(DateTime, default=utcnow, nullable=False)

    # Когда снимок был последний раз обновлён
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Когда пользователь отправил первое сообщение после входа
    first_message_at = Column(DateTime, nullable=True)

    # ─────────────────────────────────────────────────────────
    # СВЯЗИ ORM
    # ─────────────────────────────────────────────────────────
    group = relationship("Group", backref="profile_snapshots")

    # ─────────────────────────────────────────────────────────
    # ИНДЕКСЫ
    # ─────────────────────────────────────────────────────────
    __table_args__ = (
        # Уникальный индекс: один снимок на пользователя в группе
        Index('ix_profile_snapshot_chat_user', 'chat_id', 'user_id', unique=True),
    )


# ============================================================
# МОДЕЛЬ: ЖУРНАЛ ИЗМЕНЕНИЙ ПРОФИЛЯ
# ============================================================
# Записывает каждое изменение профиля пользователя после входа
# Позволяет отслеживать историю изменений: имя, username, фото
class ProfileChangeLog(Base):
    # Имя таблицы в базе данных
    __tablename__ = 'profile_change_logs'

    # ─────────────────────────────────────────────────────────
    # PRIMARY KEY: Автоинкрементный ID
    # ─────────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ─────────────────────────────────────────────────────────
    # ИДЕНТИФИКАТОРЫ
    # ─────────────────────────────────────────────────────────
    # ID группы где произошло изменение
    chat_id = Column(
        BigInteger,
        ForeignKey("groups.chat_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # ID пользователя который изменил профиль
    user_id = Column(BigInteger, nullable=False, index=True)

    # ─────────────────────────────────────────────────────────
    # ТИП ИЗМЕНЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Тип изменения:
    # - "name" = изменение имени (first_name/last_name)
    # - "username" = изменение @username
    # - "photo_added" = добавлено фото
    # - "photo_removed" = удалено фото
    # - "photo_changed" = изменено фото
    change_type = Column(String(50), nullable=False)

    # ─────────────────────────────────────────────────────────
    # СТАРЫЕ И НОВЫЕ ЗНАЧЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Старое значение (до изменения)
    old_value = Column(Text, nullable=True)

    # Новое значение (после изменения)
    new_value = Column(Text, nullable=True)

    # ─────────────────────────────────────────────────────────
    # КОНТЕКСТ ИЗМЕНЕНИЯ
    # ─────────────────────────────────────────────────────────
    # Сколько прошло времени с момента входа (в минутах)
    minutes_since_join = Column(Integer, nullable=True)

    # ID сообщения при котором обнаружено изменение
    detected_at_message_id = Column(BigInteger, nullable=True)

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЯ
    # ─────────────────────────────────────────────────────────
    # Какое действие было применено:
    # - NULL = только логирование
    # - "auto_mute" = автоматический мут
    # - "manual_mute" = ручной мут через кнопку
    # - "manual_ban" = ручной бан через кнопку
    # - "manual_kick" = ручной кик через кнопку
    action_taken = Column(String(50), nullable=True)

    # ID сообщения в журнале (для кнопки "Отправить в группу")
    journal_message_id = Column(BigInteger, nullable=True)

    # Было ли отправлено уведомление в группу
    sent_to_group = Column(Boolean, default=False, nullable=False)

    # ─────────────────────────────────────────────────────────
    # ВРЕМЕННАЯ МЕТКА
    # ─────────────────────────────────────────────────────────
    # Когда было зафиксировано изменение
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)

    # ─────────────────────────────────────────────────────────
    # СВЯЗИ ORM
    # ─────────────────────────────────────────────────────────
    group = relationship("Group", backref="profile_change_logs")

    # ─────────────────────────────────────────────────────────
    # ИНДЕКСЫ
    # ─────────────────────────────────────────────────────────
    __table_args__ = (
        # Составной индекс для поиска изменений пользователя в группе
        # Ускоряет: "все изменения user_id в chat_id"
        Index('ix_profile_changes_chat_user', 'chat_id', 'user_id'),

        # Составной индекс для поиска изменений по дате в группе
        # Ускоряет: "все изменения в chat_id за последний час"
        Index('ix_profile_changes_chat_date', 'chat_id', 'created_at'),
    )
