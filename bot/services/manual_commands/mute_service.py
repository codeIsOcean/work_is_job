# ═══════════════════════════════════════════════════════════════════════════
# СЕРВИС МУТА — БИЗНЕС-ЛОГИКА КОМАНДЫ /amute
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит всю бизнес-логику для команды /amute:
# - Получение настроек модуля
# - Применение мута (одиночного и кросс-группового)
# - Снятие мута
# - Интеграция с БД спаммеров
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

import logging
import html
from datetime import datetime, timedelta, timezone
from typing import Optional, List, NamedTuple
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import ChatPermissions, User
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модель настроек
from bot.database.models_manual_commands import ManualCommandSettings
# Импортируем функцию для работы со спаммерами
from bot.services.spammer_registry import (
    record_spammer_incident,
    delete_spammer_record,
)
# Импортируем функцию кросс-группового мута
from bot.services.mute_by_reaction_service import mute_across_groups

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATACLASS ДЛЯ РЕЗУЛЬТАТА МУТА
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class MuteResult:
    """
    Результат операции мута.

    Attributes:
        success: Успешно ли выполнена операция
        message: Сообщение для отображения
        muted_groups: Список chat_id где замучен (для кросс-группового)
        added_to_spammers: True если добавлен в БД спаммеров
        error: Текст ошибки (если success=False)
    """
    success: bool = False
    message: str = ""
    muted_groups: List[int] = None
    added_to_spammers: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        # Инициализируем список если None
        if self.muted_groups is None:
            self.muted_groups = []


# ═══════════════════════════════════════════════════════════════════════════
# ПОЛУЧЕНИЕ/СОЗДАНИЕ НАСТРОЕК
# ═══════════════════════════════════════════════════════════════════════════
async def get_manual_command_settings(
    session: AsyncSession,
    chat_id: int
) -> ManualCommandSettings:
    """
    Получает настройки модуля ручных команд для группы.
    Если настроек нет — создаёт с дефолтными значениями.

    Args:
        session: Сессия БД
        chat_id: ID группы

    Returns:
        ManualCommandSettings: Настройки модуля
    """
    # Пытаемся найти существующие настройки
    result = await session.execute(
        select(ManualCommandSettings).where(
            ManualCommandSettings.chat_id == chat_id
        )
    )
    settings = result.scalar_one_or_none()

    # Если настроек нет — создаём с дефолтами
    if settings is None:
        settings = ManualCommandSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
        logger.info(f"[MANUAL_CMD] Created default settings for chat_id={chat_id}")

    return settings


async def update_mute_settings(
    session: AsyncSession,
    chat_id: int,
    **kwargs
) -> ManualCommandSettings:
    """
    Обновляет настройки мута для группы.

    Args:
        session: Сессия БД
        chat_id: ID группы
        **kwargs: Поля для обновления

    Returns:
        ManualCommandSettings: Обновлённые настройки
    """
    # Получаем настройки (или создаём если нет)
    settings = await get_manual_command_settings(session, chat_id)

    # Обновляем переданные поля
    for key, value in kwargs.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    await session.flush()
    return settings


# ═══════════════════════════════════════════════════════════════════════════
# ПРИМЕНЕНИЕ МУТА
# ═══════════════════════════════════════════════════════════════════════════
async def apply_mute(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    admin_id: int,
    duration_minutes: Optional[int],
    reason: Optional[str] = None,
    is_forever: bool = False,
) -> MuteResult:
    """
    Применяет мут к пользователю.

    При муте навсегда (is_forever=True):
    1. Добавляет в БД спаммеров
    2. Мутит во всех группах где есть бот

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы где выполняется команда
        user_id: ID пользователя которого мутим
        admin_id: ID админа который выполняет команду
        duration_minutes: Длительность в минутах (None = навсегда)
        reason: Причина мута
        is_forever: True если мут навсегда

    Returns:
        MuteResult: Результат операции
    """
    result = MuteResult()

    try:
        # ─── Шаг 1: Проверяем что цель не админ и не бот ───
        try:
            member = await bot.get_chat_member(chat_id, user_id)

            # Проверка на админа/владельца
            if member.status in ('creator', 'administrator'):
                result.error = "Нельзя замутить администратора"
                logger.warning(
                    f"[MANUAL_CMD] Attempt to mute admin: user_id={user_id}, chat_id={chat_id}"
                )
                return result

            # Проверка на бота
            if member.user.is_bot:
                result.error = "Нельзя замутить бота"
                return result

        except TelegramAPIError as e:
            # Пользователь не найден в группе
            result.error = f"Пользователь не найден в группе: {e}"
            return result

        # ─── Шаг 2: Вычисляем until_date ───
        if is_forever or duration_minutes is None or duration_minutes == 0:
            # Мут навсегда — не указываем until_date
            until_date = None
            duration_for_cross = None  # timedelta
        else:
            # Мут на конкретное время
            until_date = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
            duration_for_cross = timedelta(minutes=duration_minutes)

        # ─── Шаг 3: Применяем мут в текущей группе ───
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )

        logger.info(
            f"[MANUAL_CMD] Muted user_id={user_id} in chat_id={chat_id}, "
            f"duration={'forever' if is_forever else f'{duration_minutes}min'}, "
            f"by admin_id={admin_id}"
        )

        result.success = True
        result.muted_groups = [chat_id]

        # ─── Шаг 4: Если навсегда — кросс-групповой мут ───
        if is_forever:
            # Добавляем в БД спаммеров
            await record_spammer_incident(
                session=session,
                user_id=user_id,
                risk_score=100,  # Максимальный риск — админ решил
                reason=reason or "Ручной мут навсегда",
            )
            result.added_to_spammers = True
            logger.info(f"[MANUAL_CMD] Added to spammers: user_id={user_id}")

            # Мутим во всех группах
            cross_results = await mute_across_groups(
                admin_id=admin_id,
                target_id=user_id,
                duration=duration_for_cross,  # None = навсегда
                reason=reason or "Ручной мут навсегда (кросс-групповой)",
                session=session,
                bot=bot,
            )

            # Собираем список успешных групп
            for r in cross_results:
                if r.success and r.chat_id != chat_id:
                    result.muted_groups.append(r.chat_id)

            logger.info(
                f"[MANUAL_CMD] Cross-group mute: user_id={user_id}, "
                f"muted in {len(result.muted_groups)} groups"
            )

        return result

    except TelegramAPIError as e:
        result.error = f"Ошибка Telegram API: {e}"
        logger.error(f"[MANUAL_CMD] Telegram API error: {e}")
        return result
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"
        logger.exception(f"[MANUAL_CMD] Unexpected error: {e}")
        return result


# ═══════════════════════════════════════════════════════════════════════════
# СНЯТИЕ МУТА
# ═══════════════════════════════════════════════════════════════════════════
async def apply_unmute(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    unmute_everywhere: bool = False,
    admin_id: Optional[int] = None,
) -> MuteResult:
    """
    Снимает мут с пользователя.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        unmute_everywhere: Размутить во всех группах
        admin_id: ID админа (для кросс-группового размута)

    Returns:
        MuteResult: Результат операции
    """
    result = MuteResult()

    try:
        # Стандартные права — всё разрешено кроме управления группой
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        # Размут в текущей группе
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
        )

        result.success = True
        result.muted_groups = [chat_id]

        logger.info(f"[MANUAL_CMD] Unmuted user_id={user_id} in chat_id={chat_id}")

        # Если нужно размутить везде
        if unmute_everywhere and admin_id:
            # Удаляем из БД спаммеров
            deleted = await delete_spammer_record(session, user_id)
            if deleted:
                logger.info(f"[MANUAL_CMD] Removed from spammers: user_id={user_id}")

            # Размут во всех группах
            # Используем mute_across_groups с duration=None но permissions разрешающими
            # TODO: Реализовать unmute_across_groups если понадобится

        return result

    except TelegramAPIError as e:
        result.error = f"Ошибка Telegram API: {e}"
        logger.error(f"[MANUAL_CMD] Unmute error: {e}")
        return result
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"
        logger.exception(f"[MANUAL_CMD] Unmute unexpected error: {e}")
        return result


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ФОРМАТИРОВАНИЕ ССЫЛКИ НА ПОЛЬЗОВАТЕЛЯ
# ═══════════════════════════════════════════════════════════════════════════
def format_user_link(user: User) -> str:
    """
    Форматирует ссылку на пользователя для HTML сообщения.

    Args:
        user: Объект User из aiogram

    Returns:
        str: HTML ссылка вида <a href="tg://user?id=123">Имя</a>
    """
    # Экранируем имя для HTML
    name = html.escape(user.full_name or str(user.id))
    # Формируем кликабельную ссылку
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def format_user_link_by_id(user_id: int, name: str) -> str:
    """
    Форматирует ссылку на пользователя по ID и имени.

    Args:
        user_id: ID пользователя
        name: Имя для отображения

    Returns:
        str: HTML ссылка вида <a href="tg://user?id=123">Имя</a>
    """
    # Экранируем имя для HTML
    safe_name = html.escape(name)
    # Формируем кликабельную ссылку
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'
