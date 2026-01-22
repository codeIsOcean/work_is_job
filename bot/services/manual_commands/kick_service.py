# ═══════════════════════════════════════════════════════════════════════════
# СЕРВИС КИКА — БИЗНЕС-ЛОГИКА КОМАНДЫ /akick
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит всю бизнес-логику для команды /akick:
# - Кик пользователя из группы (без бана)
# - Пользователь может вернуться после кика
#
# Создано: 2026-01-22
# ═══════════════════════════════════════════════════════════════════════════

import logging
from typing import Optional
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATACLASS ДЛЯ РЕЗУЛЬТАТА КИКА
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class KickResult:
    """
    Результат операции кика.

    Attributes:
        success: Успешно ли выполнена операция
        error: Текст ошибки (если success=False)
    """
    # Успешно ли выполнена операция кика
    success: bool = False
    # Текст ошибки при неуспехе
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# ПРИМЕНЕНИЕ КИКА
# ═══════════════════════════════════════════════════════════════════════════
async def apply_kick(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    admin_id: int,
    reason: Optional[str] = None,
) -> KickResult:
    """
    Кикает пользователя из группы (без бана).

    Кик выполняется через бан + разбан:
    1. ban_chat_member — удаляет из группы
    2. unban_chat_member — разрешает вернуться

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        admin_id: ID админа который выполняет команду
        reason: Причина кика (для лога)

    Returns:
        KickResult: Результат операции
    """
    result = KickResult()

    try:
        # ─── Шаг 1: Проверяем что цель не админ и не бот ───
        try:
            # Получаем информацию о пользователе в группе
            member = await bot.get_chat_member(chat_id, user_id)

            # Проверка на админа/владельца — НЕЛЬЗЯ кикать!
            if member.status in ('creator', 'administrator'):
                result.error = "Нельзя кикнуть администратора"
                logger.warning(
                    f"[MANUAL_CMD] Attempt to kick admin: user_id={user_id}, chat_id={chat_id}"
                )
                return result

            # Проверка на бота — НЕЛЬЗЯ кикать!
            if member.user.is_bot:
                result.error = "Нельзя кикнуть бота"
                return result

        except TelegramAPIError as e:
            # Пользователь не в группе — нечего кикать
            result.error = f"Пользователь не найден в группе"
            logger.debug(f"[MANUAL_CMD] User not in group for kick: {e}")
            return result

        # ─── Шаг 2: Баним (удаляем из группы) ───
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        # ─── Шаг 3: Сразу разбаниваем (разрешаем вернуться) ───
        await bot.unban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            only_if_banned=True,
        )

        logger.info(
            f"[MANUAL_CMD] Kicked user_id={user_id} from chat_id={chat_id}, "
            f"by admin_id={admin_id}, reason='{reason or '—'}'"
        )

        result.success = True
        return result

    except TelegramAPIError as e:
        result.error = f"Ошибка Telegram API: {e}"
        logger.error(f"[MANUAL_CMD] Telegram API error during kick: {e}")
        return result
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"
        logger.exception(f"[MANUAL_CMD] Unexpected error during kick: {e}")
        return result
