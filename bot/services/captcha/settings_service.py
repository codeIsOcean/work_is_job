# bot/services/captcha/settings_service.py
"""
Сервис настроек капчи - CRUD операции с ChatSettings.

Отвечает за:
- Получение настроек капчи для группы
- Обновление отдельных настроек
- Проверка что капча настроена (все обязательные поля заполнены)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ChatSettings


# Логгер для отслеживания операций с настройками
logger = logging.getLogger(__name__)


class CaptchaMode(str, Enum):
    """
    Режимы капчи - определяют куда отправляется капча.

    VISUAL_DM - капча в личных сообщениях (требует Join Requests в группе)
    JOIN_GROUP - капча в группе при самостоятельном входе
    INVITE_GROUP - капча в группе при приглашении другим пользователем
    """
    VISUAL_DM = "visual_dm"
    JOIN_GROUP = "join_group"
    INVITE_GROUP = "invite_group"


@dataclass
class CaptchaSettings:
    """
    Датакласс с настройками капчи для группы.

    Содержит все настройки из ChatSettings, связанные с капчей.
    NULL значения означают что админ ещё не настроил параметр.
    """

    # Основные флаги включения режимов
    # Visual Captcha - капча в ЛС
    visual_captcha_enabled: Optional[bool]
    # Join Captcha - капча в группе при входе
    join_captcha_enabled: bool
    # Invite Captcha - капча в группе при инвайте
    invite_captcha_enabled: bool

    # Таймауты для каждого режима (секунды)
    # NULL = админ должен настроить
    visual_captcha_timeout: Optional[int]
    join_captcha_timeout: Optional[int]
    invite_captcha_timeout: Optional[int]

    # Общий таймаут (legacy, для обратной совместимости)
    legacy_timeout: int

    # Лимит одновременных капч
    # NULL = админ должен настроить
    max_pending: Optional[int]

    # Действие при переполнении: remove_oldest | auto_decline | queue
    # NULL = админ должен настроить
    overflow_action: Optional[str]

    # Антифлуд настройки
    flood_threshold: int
    flood_window_seconds: int
    flood_action: str

    # TTL системных сообщений (общий, legacy)
    message_ttl_seconds: int

    # TTL сообщения Join Captcha в группе (секунды)
    # Через сколько секунд автоматически удалить сообщение капчи из группы
    join_captcha_message_ttl: int

    # TTL сообщения Invite Captcha в группе (секунды)
    # Через сколько секунд автоматически удалить сообщение капчи из группы
    invite_captcha_message_ttl: int

    # Системные анонсы включены
    system_announcements_enabled: bool

    # ═══════════════════════════════════════════════════════════════════════════
    # НАСТРОЙКИ ДИАЛОГОВ - применяются ко всем режимам капчи
    # ═══════════════════════════════════════════════════════════════════════════

    # Разрешён ли ручной ввод ответа через FSM (дефолт True)
    manual_input_enabled: bool

    # Количество кнопок с вариантами ответов (дефолт 6)
    button_count: int

    # Максимум попыток решения капчи (дефолт 3)
    max_attempts: int

    # Через сколько секунд напоминать (дефолт 60, 0 = выкл)
    reminder_seconds: int

    # Сколько напоминаний отправлять (дефолт 3, 0 = безлимит до таймаута)
    reminder_count: int

    # Через сколько секунд чистить диалог = таймаут капчи в ЛС (дефолт 240)
    dialog_cleanup_seconds: int

    # ═══════════════════════════════════════════════════════════════════════════
    # ДЕЙСТВИЕ ПРИ ПРОВАЛЕ КАПЧИ
    # ═══════════════════════════════════════════════════════════════════════════

    # Действие при провале/таймауте капчи для Visual DM режима:
    # "decline" = отклонить заявку (заявка удаляется из Telegram)
    # "keep" = оставить заявку висеть (админ может одобрить вручную)
    # Дефолт: "decline" (текущее поведение)
    failure_action: str

    def get_timeout_for_mode(self, mode: CaptchaMode) -> int:
        """
        Возвращает таймаут для конкретного режима капчи.

        Для VISUAL_DM: таймаут = время чистки диалога (dialog_cleanup_seconds)
        Для JOIN_GROUP/INVITE_GROUP: таймаут = специфичный или legacy_timeout

        Args:
            mode: Режим капчи (VISUAL_DM, JOIN_GROUP, INVITE_GROUP)

        Returns:
            Таймаут в секундах
        """
        # Маппинг режимов на поля таймаутов
        timeout_map = {
            CaptchaMode.VISUAL_DM: self.visual_captcha_timeout,
            CaptchaMode.JOIN_GROUP: self.join_captcha_timeout,
            CaptchaMode.INVITE_GROUP: self.invite_captcha_timeout,
        }

        # Получаем специфичный таймаут для режима
        specific_timeout = timeout_map.get(mode)

        # Если специфичный таймаут задан - используем его
        if specific_timeout is not None:
            return specific_timeout

        # Для VISUAL_DM (капча в ЛС): fallback на dialog_cleanup_seconds
        # Таймаут капчи = время чистки диалога
        if mode == CaptchaMode.VISUAL_DM:
            return self.dialog_cleanup_seconds

        # Для групповых капч: fallback на legacy_timeout
        return self.legacy_timeout

    def is_mode_enabled(self, mode: CaptchaMode) -> bool:
        """
        Проверяет включён ли конкретный режим капчи.

        Args:
            mode: Режим капчи для проверки

        Returns:
            True если режим включён, False если выключен или не настроен
        """
        # Маппинг режимов на флаги включения
        enabled_map = {
            CaptchaMode.VISUAL_DM: self.visual_captcha_enabled,
            CaptchaMode.JOIN_GROUP: self.join_captcha_enabled,
            CaptchaMode.INVITE_GROUP: self.invite_captcha_enabled,
        }

        # Получаем значение флага
        enabled = enabled_map.get(mode)

        # NULL (None) считается как выключено
        return enabled is True

    def get_message_ttl_for_mode(self, mode: CaptchaMode) -> int:
        """
        Возвращает TTL сообщения капчи в группе для конкретного режима.

        TTL определяет через сколько секунд автоматически удалить
        сообщение капчи из группы.

        Args:
            mode: Режим капчи (JOIN_GROUP или INVITE_GROUP)

        Returns:
            TTL в секундах (дефолт 300 = 5 минут)
        """
        # Для VISUAL_DM не используется (капча в ЛС, не в группе)
        if mode == CaptchaMode.VISUAL_DM:
            return self.message_ttl_seconds

        # Для JOIN_GROUP - используем join_captcha_message_ttl
        if mode == CaptchaMode.JOIN_GROUP:
            return self.join_captcha_message_ttl

        # Для INVITE_GROUP - используем invite_captcha_message_ttl
        if mode == CaptchaMode.INVITE_GROUP:
            return self.invite_captcha_message_ttl

        # Fallback на общий TTL
        return self.message_ttl_seconds

    def is_mode_configured(self, mode: CaptchaMode) -> bool:
        """
        Проверяет полностью ли настроен режим капчи.

        Режим считается настроенным если:
        - Он включён
        - Задан таймаут (или есть legacy_timeout)
        - Для групповых режимов: задан max_pending и overflow_action

        Args:
            mode: Режим капчи для проверки

        Returns:
            True если режим полностью настроен
        """
        # Сначала проверяем что режим включён
        if not self.is_mode_enabled(mode):
            return False

        # Проверяем что есть таймаут (специфичный или legacy)
        timeout = self.get_timeout_for_mode(mode)
        if timeout is None or timeout <= 0:
            return False

        # Для групповых режимов проверяем лимиты
        if mode in (CaptchaMode.JOIN_GROUP, CaptchaMode.INVITE_GROUP):
            # max_pending должен быть задан
            if self.max_pending is None or self.max_pending <= 0:
                return False
            # overflow_action должен быть задан
            if not self.overflow_action:
                return False

        return True


async def get_captcha_settings(
    session: AsyncSession,
    chat_id: int,
) -> CaptchaSettings:
    """
    Получает настройки капчи для группы.

    Если настроек нет - создаёт запись с дефолтными значениями.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы (может быть отрицательным)

    Returns:
        CaptchaSettings с текущими настройками группы
    """
    # Пытаемся получить существующие настройки
    settings = await session.get(ChatSettings, chat_id)

    # Если настроек нет - создаём новую запись
    if settings is None:
        # Логируем создание новых настроек
        logger.info(
            f"📝 [CAPTCHA_SETTINGS] Создаём новые настройки для chat_id={chat_id}"
        )

        # Создаём запись с минимальными дефолтами
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()

    # Конвертируем ORM модель в датакласс
    # Используем дефолты для полей которые могут быть NULL
    return CaptchaSettings(
        # Режимы включения
        visual_captcha_enabled=settings.visual_captcha_enabled,
        join_captcha_enabled=settings.captcha_join_enabled or False,
        invite_captcha_enabled=settings.captcha_invite_enabled or False,

        # Таймауты
        visual_captcha_timeout=settings.visual_captcha_timeout_seconds,
        join_captcha_timeout=settings.join_captcha_timeout_seconds,
        invite_captcha_timeout=settings.invite_captcha_timeout_seconds,
        legacy_timeout=settings.captcha_timeout_seconds or 120,  # 2 мин дефолт

        # Лимиты
        max_pending=settings.captcha_max_pending,
        overflow_action=settings.captcha_overflow_action,

        # Антифлуд (дефолты если не заданы)
        flood_threshold=settings.captcha_flood_threshold or 10,
        flood_window_seconds=settings.captcha_flood_window_seconds or 60,
        flood_action=settings.captcha_flood_action or "mute",

        # TTL и анонсы (дефолты если не заданы)
        message_ttl_seconds=settings.captcha_message_ttl_seconds or 30,

        # TTL сообщений капчи в группе (дефолт 300 сек = 5 минут)
        # Используем getattr для безопасного получения новых колонок
        join_captcha_message_ttl=getattr(settings, 'join_captcha_message_ttl_seconds', None) or 300,
        invite_captcha_message_ttl=getattr(settings, 'invite_captcha_message_ttl_seconds', None) or 300,

        system_announcements_enabled=settings.system_mute_announcements_enabled if settings.system_mute_announcements_enabled is not None else True,

        # ═══════════════════════════════════════════════════════════════════════
        # Настройки диалогов (дефолты согласованы с админом)
        # ═══════════════════════════════════════════════════════════════════════

        # Ручной ввод: NULL → True (включён по умолчанию)
        manual_input_enabled=settings.captcha_manual_input_enabled if settings.captcha_manual_input_enabled is not None else True,

        # Количество кнопок: NULL → 6 (баланс между удобством и защитой)
        button_count=settings.captcha_button_count if settings.captcha_button_count is not None else 6,

        # Макс попыток: NULL → 3
        max_attempts=settings.captcha_max_attempts if settings.captcha_max_attempts is not None else 3,

        # Напоминание: NULL → 60 сек (0 = выключено)
        reminder_seconds=settings.captcha_reminder_seconds if settings.captcha_reminder_seconds is not None else 60,

        # Количество напоминаний: NULL → 3 (0 = безлимит)
        reminder_count=getattr(settings, 'captcha_reminder_count', None) or 3,

        # Чистка диалога = таймаут капчи в ЛС: NULL → 240 сек (4 минуты)
        # Время достаточное для 3 напоминаний по 60 сек + запас
        dialog_cleanup_seconds=settings.captcha_dialog_cleanup_seconds if settings.captcha_dialog_cleanup_seconds is not None else 240,

        # ═══════════════════════════════════════════════════════════════════════
        # Действие при провале капчи (Visual DM)
        # ═══════════════════════════════════════════════════════════════════════

        # failure_action: NULL → "keep" (оставить заявку висеть - старое поведение)
        # "decline" = отклонить заявку (заявка удаляется из Telegram)
        failure_action=getattr(settings, 'captcha_failure_action', None) or "keep",
    )


async def update_captcha_setting(
    session: AsyncSession,
    chat_id: int,
    field: str,
    value: Any,
) -> bool:
    """
    Обновляет одну настройку капчи.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        field: Имя поля для обновления (например "visual_captcha_enabled")
        value: Новое значение

    Returns:
        True если обновление успешно, False если поле не существует
    """
    # Маппинг полей датакласса на колонки модели
    # Ключ - имя в CaptchaSettings, значение - имя колонки в ChatSettings
    field_mapping = {
        # Режимы капчи
        "visual_captcha_enabled": "visual_captcha_enabled",
        "join_captcha_enabled": "captcha_join_enabled",
        "invite_captcha_enabled": "captcha_invite_enabled",

        # Таймауты для режимов
        "visual_captcha_timeout": "visual_captcha_timeout_seconds",
        "join_captcha_timeout": "join_captcha_timeout_seconds",
        "invite_captcha_timeout": "invite_captcha_timeout_seconds",

        # Лимиты и переполнение
        "max_pending": "captcha_max_pending",
        "overflow_action": "captcha_overflow_action",

        # Антифлуд
        "flood_threshold": "captcha_flood_threshold",
        "flood_window_seconds": "captcha_flood_window_seconds",
        "flood_action": "captcha_flood_action",

        # TTL сообщений
        "message_ttl_seconds": "captcha_message_ttl_seconds",

        # TTL сообщений капчи в группе (автоудаление)
        "join_captcha_message_ttl": "join_captcha_message_ttl_seconds",
        "invite_captcha_message_ttl": "invite_captcha_message_ttl_seconds",

        # ═══════════════════════════════════════════════════════════════════════
        # Настройки диалогов (НОВЫЕ)
        # ═══════════════════════════════════════════════════════════════════════
        "manual_input_enabled": "captcha_manual_input_enabled",
        "button_count": "captcha_button_count",
        "max_attempts": "captcha_max_attempts",
        "reminder_seconds": "captcha_reminder_seconds",
        "reminder_count": "captcha_reminder_count",
        "dialog_cleanup_seconds": "captcha_dialog_cleanup_seconds",

        # Действие при провале капчи (Visual DM)
        "failure_action": "captcha_failure_action",
    }

    # Проверяем что поле существует в маппинге
    if field not in field_mapping:
        logger.warning(
            f"⚠️ [CAPTCHA_SETTINGS] Неизвестное поле: {field}"
        )
        return False

    # Получаем имя колонки в модели
    column_name = field_mapping[field]

    # Получаем или создаём настройки
    settings = await session.get(ChatSettings, chat_id)
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)

    # Устанавливаем значение
    setattr(settings, column_name, value)

    # Сохраняем изменения
    await session.flush()

    # Логируем изменение
    logger.info(
        f"✅ [CAPTCHA_SETTINGS] Обновлено: chat_id={chat_id}, "
        f"{field}={value}"
    )

    return True


async def is_captcha_configured(
    session: AsyncSession,
    chat_id: int,
    mode: CaptchaMode,
) -> bool:
    """
    Проверяет полностью ли настроен указанный режим капчи.

    Удобная обёртка для использования в хендлерах.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        mode: Режим капчи для проверки

    Returns:
        True если режим полностью настроен и готов к работе
    """
    # Получаем настройки
    settings = await get_captcha_settings(session, chat_id)

    # Проверяем конфигурацию режима
    return settings.is_mode_configured(mode)


async def get_missing_settings(
    session: AsyncSession,
    chat_id: int,
    mode: CaptchaMode,
) -> list[str]:
    """
    Возвращает список ненастроенных полей для режима.

    Используется в UI для подсказки админу что нужно настроить.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        mode: Режим капчи

    Returns:
        Список названий полей которые нужно настроить
    """
    # Получаем настройки
    settings = await get_captcha_settings(session, chat_id)

    # Список ненастроенных полей
    missing = []

    # Проверяем таймаут
    timeout = settings.get_timeout_for_mode(mode)
    if timeout is None or timeout <= 0:
        # Определяем какой именно таймаут нужен
        timeout_names = {
            CaptchaMode.VISUAL_DM: "visual_captcha_timeout",
            CaptchaMode.JOIN_GROUP: "join_captcha_timeout",
            CaptchaMode.INVITE_GROUP: "invite_captcha_timeout",
        }
        missing.append(timeout_names[mode])

    # Для групповых режимов проверяем лимиты
    if mode in (CaptchaMode.JOIN_GROUP, CaptchaMode.INVITE_GROUP):
        if settings.max_pending is None or settings.max_pending <= 0:
            missing.append("max_pending")
        if not settings.overflow_action:
            missing.append("overflow_action")

    return missing
