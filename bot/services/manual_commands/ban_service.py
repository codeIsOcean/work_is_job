# ═══════════════════════════════════════════════════════════════════════════
# СЕРВИС БАНА — БИЗНЕС-ЛОГИКА КОМАНДЫ /aban
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл содержит всю бизнес-логику для команды /aban:
# - Применение бана (одиночного и кросс-группового)
# - Добавление в БД спаммеров
# - Удаление всех сообщений пользователя (если включено)
#
# Создано: 2026-01-22
# ═══════════════════════════════════════════════════════════════════════════

import logging
from typing import Optional, List
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модели для работы с группами
from bot.database.models import Group, UserGroup

# Импортируем функцию для работы со спаммерами
from bot.services.spammer_registry import record_spammer_incident

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATACLASS ДЛЯ РЕЗУЛЬТАТА БАНА
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class BanResult:
    """
    Результат операции бана.

    Attributes:
        success: Успешно ли выполнена операция
        banned_groups: Список chat_id где забанен (для кросс-группового)
        added_to_spammers: True если добавлен в БД спаммеров
        error: Текст ошибки (если success=False)
    """
    # Успешно ли выполнена операция бана
    success: bool = False
    # Список групп где пользователь забанен
    banned_groups: List[int] = field(default_factory=list)
    # Добавлен ли пользователь в БД спаммеров
    added_to_spammers: bool = False
    # Текст ошибки при неуспехе
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# ПРИМЕНЕНИЕ БАНА
# ═══════════════════════════════════════════════════════════════════════════
async def apply_ban(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    admin_id: int,
    reason: Optional[str] = None,
    add_to_spammers: bool = True,
    cross_group_ban: bool = True,
) -> BanResult:
    """
    Применяет бан к пользователю.

    По умолчанию:
    1. Добавляет в БД спаммеров
    2. Банит во всех группах где есть бот и пользователь — админ

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы где выполняется команда
        user_id: ID пользователя которого баним
        admin_id: ID админа который выполняет команду
        reason: Причина бана
        add_to_spammers: Добавить в БД спаммеров (по умолчанию True)
        cross_group_ban: Банить во всех группах (по умолчанию True)

    Returns:
        BanResult: Результат операции
    """
    result = BanResult()

    try:
        # ─── Шаг 1: Проверяем что цель не админ и не бот ───
        try:
            # Получаем информацию о пользователе в группе
            member = await bot.get_chat_member(chat_id, user_id)

            # Проверка на админа/владельца — НЕЛЬЗЯ банить!
            if member.status in ('creator', 'administrator'):
                result.error = "Нельзя забанить администратора"
                logger.warning(
                    f"[MANUAL_CMD] Attempt to ban admin: user_id={user_id}, chat_id={chat_id}"
                )
                return result

            # Проверка на бота — НЕЛЬЗЯ банить!
            if member.user.is_bot:
                result.error = "Нельзя забанить бота"
                return result

        except TelegramAPIError as e:
            # Пользователь не найден в группе — всё равно можно забанить
            logger.debug(f"[MANUAL_CMD] User not in group, proceeding with ban: {e}")

        # ─── Шаг 2: Добавляем в БД спаммеров (если включено) ───
        if add_to_spammers:
            await record_spammer_incident(
                session=session,
                user_id=user_id,
                risk_score=100,  # Максимальный риск — админ принял решение
                reason=reason or "Ручной бан (/aban)",
            )
            result.added_to_spammers = True
            logger.info(f"[MANUAL_CMD] Added to spammers: user_id={user_id}")

        # ─── Шаг 3: Баним в текущей группе ───
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        logger.info(
            f"[MANUAL_CMD] Banned user_id={user_id} in chat_id={chat_id}, "
            f"by admin_id={admin_id}, reason='{reason or '—'}'"
        )

        result.success = True
        result.banned_groups = [chat_id]

        # ─── Шаг 4: Кросс-групповой бан (если включено) ───
        if cross_group_ban:
            # Получаем все группы где админ является админом
            cross_results = await ban_across_groups(
                bot=bot,
                session=session,
                admin_id=admin_id,
                user_id=user_id,
                exclude_chat_id=chat_id,  # Исключаем текущую группу
            )

            # Добавляем успешные группы
            for cross_result in cross_results:
                if cross_result['success']:
                    result.banned_groups.append(cross_result['chat_id'])

            logger.info(
                f"[MANUAL_CMD] Cross-group ban: user_id={user_id}, "
                f"banned in {len(result.banned_groups)} groups total"
            )

        return result

    except TelegramAPIError as e:
        result.error = f"Ошибка Telegram API: {e}"
        logger.error(f"[MANUAL_CMD] Telegram API error during ban: {e}")
        return result
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"
        logger.exception(f"[MANUAL_CMD] Unexpected error during ban: {e}")
        return result


# ═══════════════════════════════════════════════════════════════════════════
# КРОСС-ГРУППОВОЙ БАН
# ═══════════════════════════════════════════════════════════════════════════
async def ban_across_groups(
    bot: Bot,
    session: AsyncSession,
    admin_id: int,
    user_id: int,
    exclude_chat_id: Optional[int] = None,
) -> List[dict]:
    """
    Банит пользователя во всех группах где админ является админом.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        admin_id: ID админа (ищем группы где он админ)
        user_id: ID пользователя для бана
        exclude_chat_id: ID группы которую исключить (уже забанен там)

    Returns:
        List[dict]: Список результатов: [{chat_id, success, error}, ...]
    """
    results = []

    try:
        # ─── Получаем все группы где админ является админом ───
        # Ищем через UserGroup где is_admin=True
        query = select(UserGroup).where(
            UserGroup.user_id == admin_id,
            UserGroup.is_admin == True,
        )
        user_groups = await session.execute(query)
        admin_groups = user_groups.scalars().all()

        # ─── Баним в каждой группе ───
        for ug in admin_groups:
            chat_id = ug.chat_id

            # Пропускаем исключённую группу
            if exclude_chat_id and chat_id == exclude_chat_id:
                continue

            try:
                # Проверяем что цель не админ в этой группе
                try:
                    member = await bot.get_chat_member(chat_id, user_id)
                    if member.status in ('creator', 'administrator'):
                        logger.debug(
                            f"[MANUAL_CMD] Skip cross-ban: user_id={user_id} "
                            f"is admin in chat_id={chat_id}"
                        )
                        continue
                except TelegramAPIError:
                    # Пользователь не в группе — можно банить
                    pass

                # Баним
                await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)

                results.append({
                    'chat_id': chat_id,
                    'success': True,
                    'error': None,
                })

                logger.debug(
                    f"[MANUAL_CMD] Cross-ban: user_id={user_id} in chat_id={chat_id}"
                )

            except TelegramAPIError as e:
                # Ошибка бана в этой группе — не прерываем процесс
                results.append({
                    'chat_id': chat_id,
                    'success': False,
                    'error': str(e),
                })
                logger.warning(
                    f"[MANUAL_CMD] Cross-ban failed: user_id={user_id}, "
                    f"chat_id={chat_id}, error={e}"
                )

    except Exception as e:
        logger.exception(f"[MANUAL_CMD] Error in ban_across_groups: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# СНЯТИЕ БАНА (РАЗБАН)
# ═══════════════════════════════════════════════════════════════════════════
async def apply_unban(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    unban_everywhere: bool = False,
    admin_id: Optional[int] = None,
) -> BanResult:
    """
    Снимает бан с пользователя.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        unban_everywhere: Разбанить во всех группах
        admin_id: ID админа (для кросс-группового разбана)

    Returns:
        BanResult: Результат операции
    """
    result = BanResult()

    try:
        # Разбан в текущей группе
        await bot.unban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            only_if_banned=True,
        )

        result.success = True
        result.banned_groups = [chat_id]

        logger.info(f"[MANUAL_CMD] Unbanned user_id={user_id} in chat_id={chat_id}")

        # Если нужно разбанить везде
        if unban_everywhere and admin_id:
            # Удаляем из БД спаммеров
            from bot.services.spammer_registry import delete_spammer_record
            deleted = await delete_spammer_record(session, user_id)
            if deleted:
                logger.info(f"[MANUAL_CMD] Removed from spammers: user_id={user_id}")

            # TODO: Можно реализовать unban_across_groups если нужно

        return result

    except TelegramAPIError as e:
        result.error = f"Ошибка Telegram API: {e}"
        logger.error(f"[MANUAL_CMD] Unban error: {e}")
        return result
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"
        logger.exception(f"[MANUAL_CMD] Unban unexpected error: {e}")
        return result
