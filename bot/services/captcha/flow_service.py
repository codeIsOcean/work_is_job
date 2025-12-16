# bot/services/captcha/flow_service.py
"""
Сервис потока капчи - основная бизнес-логика.

Отвечает за:
- Определение нужного режима капчи
- Отправку капчи пользователю
- Обработку успешного/неуспешного прохождения
- Восстановление мутов при повторном входе
"""

import asyncio
import logging
import time
from typing import Optional
from datetime import datetime, timezone, timedelta

from aiogram import Bot
from aiogram.types import Chat, User, ChatPermissions
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.markdown import hlink
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import UserRestriction
from bot.services.captcha.settings_service import (
    CaptchaMode,
    CaptchaSettings,
    get_captcha_settings,
)
from bot.services.captcha.cleanup_service import (
    cleanup_user_captcha,
    enforce_captcha_limit,
    save_captcha_data,
    save_captcha_message,
    CaptchaOverflowError,
)
from bot.services.captcha.dm_flow_service import (
    save_captcha_message_id,
)
from bot.services.captcha.verification_service import (
    hash_answer,
    generate_captcha_options,
)
from bot.services.captcha.reminder_service import (
    cancel_reminders,
    schedule_dialog_cleanup,
)


# Логгер для отслеживания потока капчи
logger = logging.getLogger(__name__)


# Реэкспорт CaptchaMode для удобства импорта
__all__ = [
    "CaptchaMode",
    "determine_captcha_mode",
    "send_captcha",
    "process_captcha_success",
    "process_captcha_failure",
    "check_and_restore_restriction",
    "is_group_closed",
]


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ТИПА ГРУППЫ
# ═══════════════════════════════════════════════════════════════════════════════

async def is_group_closed(bot: Bot, chat_id: int) -> bool:
    """
    Проверяет закрыта ли группа (включён ли Join Request).

    Закрытая группа = требуется одобрение заявки на вступление (join_by_request=True).
    Открытая группа = любой может войти по ссылке (join_by_request=False).

    Args:
        bot: Экземпляр бота для API запроса
        chat_id: ID группы для проверки

    Returns:
        True если группа закрыта (есть Join Request)
        False если группа открыта (нет Join Request)
    """
    try:
        # Получаем информацию о чате через Telegram API
        chat = await bot.get_chat(chat_id)

        # join_by_request = True означает что нужно одобрение заявки
        # Это "закрытая" группа для наших целей
        is_closed = getattr(chat, 'join_by_request', False) or False

        # Логируем результат для отладки
        logger.debug(
            f"🔍 [GROUP_TYPE] chat_id={chat_id}, "
            f"join_by_request={is_closed}, "
            f"тип={'закрытая' if is_closed else 'открытая'}"
        )

        return is_closed

    except TelegramAPIError as e:
        # При ошибке API - логируем и считаем группу открытой (безопасный fallback)
        logger.warning(
            f"⚠️ [GROUP_TYPE] Ошибка получения типа группы: "
            f"chat_id={chat_id}, error={e}"
        )
        return False


async def determine_captcha_mode(
    session: AsyncSession,
    chat_id: int,
    event_type: str,
) -> Optional[CaptchaMode]:
    """
    Определяет какой режим капчи использовать для события.

    Args:
        session: Сессия БД
        chat_id: ID группы
        event_type: Тип события ("join_request" | "self_join" | "invite")

    Returns:
        CaptchaMode если капча нужна, None если нет
    """
    # Получаем настройки группы
    settings = await get_captcha_settings(session, chat_id)

    # Маппинг типов событий на режимы капчи
    event_to_mode = {
        "join_request": CaptchaMode.VISUAL_DM,
        "self_join": CaptchaMode.JOIN_GROUP,
        "invite": CaptchaMode.INVITE_GROUP,
    }

    # Получаем режим для этого типа события
    mode = event_to_mode.get(event_type)

    if mode is None:
        logger.warning(
            f"⚠️ [CAPTCHA_MODE] Неизвестный тип события: {event_type}"
        )
        return None

    # Проверяем включён ли этот режим
    if not settings.is_mode_enabled(mode):
        logger.debug(
            f"🔍 [CAPTCHA_MODE] Режим {mode.value} выключен для chat_id={chat_id}"
        )
        return None

    # Проверяем полностью ли настроен режим
    if not settings.is_mode_configured(mode):
        logger.warning(
            f"⚠️ [CAPTCHA_MODE] Режим {mode.value} не полностью настроен "
            f"для chat_id={chat_id}"
        )
        return None

    logger.info(
        f"✅ [CAPTCHA_MODE] Определён режим: {mode.value} "
        f"для chat_id={chat_id}, event={event_type}"
    )

    return mode


async def check_and_restore_restriction(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> Optional[UserRestriction]:
    """
    Проверяет и восстанавливает активное ограничение пользователя.

    Критически важная функция - предотвращает снятие мута
    при повторном входе через капчу.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        UserRestriction если был восстановлен мут, None если мута нет
    """
    # Ищем активное ограничение в БД
    result = await session.execute(
        select(UserRestriction)
        .where(
            # Фильтруем по пользователю и группе
            UserRestriction.user_id == user_id,
            UserRestriction.chat_id == chat_id,
            # Только активные ограничения
            UserRestriction.is_active == True,
            # Ещё не истёкшие (или бессрочные)
            # Используем utcnow() т.к. until_date в БД без timezone
            or_(
                UserRestriction.until_date.is_(None),
                UserRestriction.until_date > datetime.utcnow(),
            ),
        )
    )

    restriction = result.scalar_one_or_none()

    # Если ограничения нет - пользователь чист
    if restriction is None:
        return None

    # Восстанавливаем ограничение через Telegram API
    try:
        # Формируем права (всё запрещено)
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        # Применяем ограничение
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=restriction.until_date,
        )

        logger.info(
            f"🔒 [RESTRICTION_RESTORED] Мут восстановлен: "
            f"user_id={user_id}, chat_id={chat_id}, "
            f"reason={restriction.reason}, "
            f"until={restriction.until_date}"
        )

        return restriction

    except TelegramAPIError as e:
        logger.error(
            f"❌ [RESTRICTION_RESTORE] Ошибка восстановления мута: "
            f"user_id={user_id}, chat_id={chat_id}, error={e}"
        )
        return None


async def send_captcha(
    bot: Bot,
    session: AsyncSession,
    chat: Chat,
    user: User,
    mode: CaptchaMode,
    settings: CaptchaSettings,
) -> bool:
    """
    Отправляет капчу пользователю.

    Основная функция отправки капчи - определяет куда отправлять
    (ЛС или группа), генерирует капчу и отправляет.

    Для VISUAL_DM: отправляет deep link invitation, капча генерируется
    когда пользователь нажмёт кнопку (в FSM handler).

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat: Объект чата (группы)
        user: Объект пользователя
        mode: Режим капчи
        settings: Настройки капчи

    Returns:
        True если капча успешно отправлена
    """
    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Очищаем предыдущую капчу пользователя
    # Предотвращает накопление капч при повторном входе
    # ═══════════════════════════════════════════════════════════════════════
    await cleanup_user_captcha(
        bot=bot,
        chat_id=chat.id,
        user_id=user.id,
        delete_message=True,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # VISUAL_DM: Отправляем deep link invitation вместо прямой капчи
    # Капча будет сгенерирована когда пользователь нажмёт кнопку
    # ═══════════════════════════════════════════════════════════════════════
    if mode == CaptchaMode.VISUAL_DM:
        return await _send_visual_dm_deep_link(
            bot=bot,
            chat=chat,
            user=user,
            settings=settings,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Для JOIN_GROUP и INVITE_GROUP: отправляем капчу напрямую в группу
    # ═══════════════════════════════════════════════════════════════════════
    return await _send_group_captcha(
        bot=bot,
        session=session,
        chat=chat,
        user=user,
        mode=mode,
        settings=settings,
    )


async def _send_visual_dm_deep_link(
    bot: Bot,
    chat: Chat,
    user: User,
    settings: CaptchaSettings,
) -> bool:
    """
    Отправляет deep link invitation для Visual Captcha.

    Пользователь получает сообщение с кнопкой в ЛС.
    При нажатии на кнопку - открывается /start с deep link,
    и FSM handler отправляет капчу.

    Это позволяет:
    1. Записать пользователя в БД при нажатии кнопки
    2. В будущем отправлять рассылки тем кто взаимодействовал с ботом

    Args:
        bot: Экземпляр бота
        chat: Объект чата (группы)
        user: Объект пользователя
        settings: Настройки капчи

    Returns:
        True если сообщение отправлено успешно
    """
    from bot.services.captcha.dm_flow_service import (
        create_captcha_deep_link,
        save_join_request,
        save_captcha_message_id,
    )
    from bot.handlers.captcha.captcha_messages import send_deep_link_invite

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Создаём deep link
    # ВАЖНО: user_id включён в deep link для защиты от чужих пользователей!
    # ═══════════════════════════════════════════════════════════════════════
    deep_link = await create_captcha_deep_link(
        bot=bot,
        chat_id=chat.id,
        user_id=user.id,
        chat_username=chat.username,
    )

    # Формируем group_id для Redis
    if chat.username:
        group_id = chat.username
    else:
        group_id = f"private_{chat.id}"

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Сохраняем join request в Redis
    # Это позволит FSM handler знать что пользователь пришёл через join request
    # ═══════════════════════════════════════════════════════════════════════
    await save_join_request(
        user_id=user.id,
        chat_id=chat.id,
        group_id=group_id,
    )

    logger.info(
        f"💾 [VISUAL_DM] Join request сохранён: "
        f"user_id={user.id}, chat_id={chat.id}, group_id={group_id}"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Отправляем deep link invitation в ЛС
    # ═══════════════════════════════════════════════════════════════════════
    try:
        msg = await send_deep_link_invite(
            bot=bot,
            user_id=user.id,
            group_name=chat.title or "группу",
            deep_link=deep_link,
        )

        if not msg:
            logger.warning(
                f"⚠️ [VISUAL_DM] Не удалось отправить deep link invite: "
                f"user_id={user.id}"
            )
            return False

        # Сохраняем ID сообщения для последующей чистки
        await save_captcha_message_id(user.id, msg.message_id)

        logger.info(
            f"📤 [VISUAL_DM] Deep link invite отправлен: "
            f"user_id={user.id}, chat_id={chat.id}, msg_id={msg.message_id}"
        )

    except TelegramAPIError as e:
        error_msg = str(e).lower()

        if "bot can't initiate conversation" in error_msg:
            logger.warning(
                f"⚠️ [VISUAL_DM] Пользователь не начал диалог с ботом: "
                f"user_id={user.id}"
            )
        elif "bot was blocked" in error_msg:
            logger.warning(
                f"⚠️ [VISUAL_DM] Бот заблокирован пользователем: "
                f"user_id={user.id}"
            )
        else:
            logger.error(f"❌ [VISUAL_DM] Ошибка отправки: {e}")

        return False

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 4: Планируем таймаут (decline join request если не нажмёт кнопку)
    # Таймаут = dialog_cleanup_seconds (время на всю капчу)
    # ═══════════════════════════════════════════════════════════════════════
    timeout = settings.get_timeout_for_mode(CaptchaMode.VISUAL_DM)

    asyncio.create_task(
        _decline_join_request_after_timeout(
            bot=bot,
            chat_id=chat.id,
            user_id=user.id,
            timeout=timeout,
        )
    )

    logger.info(
        f"⏰ [VISUAL_DM] Таймаут запланирован: "
        f"user_id={user.id}, через {timeout}с"
    )

    return True


async def _decline_join_request_after_timeout(
    bot: Bot,
    chat_id: int,
    user_id: int,
    timeout: int,
) -> None:
    """
    Отклоняет join request после таймаута если пользователь не прошёл капчу.

    Проверяет есть ли ещё active join request в Redis.
    Если есть - значит пользователь не нажал кнопку или не прошёл капчу.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя
        timeout: Таймаут в секундах
    """
    from bot.services.captcha.dm_flow_service import (
        get_join_request,
        delete_join_request,
        get_captcha_message_ids,
        delete_captcha_message_ids,
    )
    from bot.handlers.captcha.captcha_messages import send_failure_message

    # Ждём таймаут
    await asyncio.sleep(timeout)

    # Проверяем есть ли ещё join request
    join_request = await get_join_request(user_id, chat_id)

    if join_request:
        # Join request ещё активен - значит капча не пройдена
        logger.info(
            f"⏰ [VISUAL_DM_TIMEOUT] Время вышло: user_id={user_id}, chat_id={chat_id}"
        )

        # Отклоняем join request
        try:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
            logger.info(
                f"🚫 [VISUAL_DM_TIMEOUT] Join request отклонён: "
                f"user_id={user_id}, chat_id={chat_id}"
            )
        except Exception as e:
            logger.warning(f"⚠️ [VISUAL_DM_TIMEOUT] Ошибка отклонения: {e}")

        # Удаляем join request из Redis
        await delete_join_request(user_id, chat_id)

        # Удаляем все сообщения капчи
        message_ids = await get_captcha_message_ids(user_id)
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass

        await delete_captcha_message_ids(user_id)

        # Отправляем сообщение о провале
        await send_failure_message(bot, user_id, reason="timeout")

    else:
        # Join request уже обработан (капча пройдена или отклонена)
        logger.debug(
            f"🔍 [VISUAL_DM_TIMEOUT] Join request уже обработан: "
            f"user_id={user_id}, chat_id={chat_id}"
        )


async def _send_group_captcha(
    bot: Bot,
    session: AsyncSession,
    chat: Chat,
    user: User,
    mode: CaptchaMode,
    settings: CaptchaSettings,
) -> bool:
    """
    Отправляет капчу для групповых режимов (JOIN_GROUP, INVITE_GROUP).

    Для JOIN_GROUP (открытая группа):
    - Отправляет сообщение в группу с deep link кнопкой
    - Мутит пользователя БЕССРОЧНО
    - Капча генерируется когда пользователь нажмёт кнопку (в FSM handler)
    - При успехе: размут, при провале: остаётся в муте

    Для INVITE_GROUP:
    - Аналогичная логика как для JOIN_GROUP

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat: Объект чата (группы)
        user: Объект пользователя
        mode: Режим капчи
        settings: Настройки капчи

    Returns:
        True если успешно отправлено
    """
    from bot.services.captcha.dm_flow_service import (
        create_captcha_deep_link,
        save_join_request,
    )
    from bot.handlers.captcha.captcha_messages import (
        CAPTCHA_GROUP_DEEP_LINK,
        CAPTCHA_START_BUTTON,
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Проверяем лимит капч
    # ═══════════════════════════════════════════════════════════════════════
    try:
        await enforce_captcha_limit(
            bot=bot,
            session=session,
            chat_id=chat.id,
            new_user_id=user.id,
        )
    except CaptchaOverflowError:
        logger.warning(
            f"⚠️ [GROUP_CAPTCHA] Превышен лимит капч, "
            f"пользователь отклонён: user_id={user.id}"
        )
        return False

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Создаём deep link
    # ВАЖНО: user_id включён в deep link для защиты от чужих пользователей!
    # ═══════════════════════════════════════════════════════════════════════
    deep_link = await create_captcha_deep_link(
        bot=bot,
        chat_id=chat.id,
        user_id=user.id,
        chat_username=chat.username,
    )

    # Формируем group_id для Redis
    if chat.username:
        group_id = chat.username
    else:
        group_id = f"private_{chat.id}"

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Сохраняем данные в Redis для FSM handler
    # ═══════════════════════════════════════════════════════════════════════
    await save_join_request(
        user_id=user.id,
        chat_id=chat.id,
        group_id=group_id,
    )

    # Сохраняем режим капчи в данные для FSM handler
    captcha_data = {
        "mode": mode.value,
        "chat_id": chat.id,
        "group_id": group_id,
        "created_at": time.time(),
    }

    # TTL = 24 часа (бессрочный мут, но данные не вечные)
    await save_captcha_data(
        user_id=user.id,
        chat_id=chat.id,
        data=captcha_data,
        ttl=86400,  # 24 часа
    )

    logger.info(
        f"💾 [GROUP_CAPTCHA] Данные сохранены: "
        f"user_id={user.id}, chat_id={chat.id}, mode={mode.value}"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 4: Формируем и отправляем сообщение в группу
    # ═══════════════════════════════════════════════════════════════════════
    user_mention = hlink(
        user.first_name or user.username or str(user.id),
        f"tg://user?id={user.id}",
    )

    message_text = CAPTCHA_GROUP_DEEP_LINK.format(user_mention=user_mention)

    # Клавиатура с deep link кнопкой
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=CAPTCHA_START_BUTTON,
            url=deep_link,
        )]
    ])

    try:
        msg = await bot.send_message(
            chat_id=chat.id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        logger.info(
            f"📤 [GROUP_CAPTCHA] Сообщение отправлено в группу: "
            f"user_id={user.id}, chat_id={chat.id}, msg_id={msg.message_id}"
        )

    except TelegramAPIError as e:
        logger.error(f"❌ [GROUP_CAPTCHA] Ошибка отправки: {e}")
        return False

    # Сохраняем ID сообщения для удаления при успехе/провале
    await save_captcha_message(
        user_id=user.id,
        chat_id=chat.id,
        target_chat_id=chat.id,
        message_id=msg.message_id,
        ttl=86400,  # 24 часа
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 5: Мутим пользователя БЕССРОЧНО
    # Размут произойдёт только при успешном прохождении капчи
    # ═══════════════════════════════════════════════════════════════════════
    try:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_invite_users=False,
        )

        # until_date=None или очень далёкая дата = бессрочный мут
        # Telegram API: если until_date не указан или > 366 дней - бессрочно
        await bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=permissions,
            # Не указываем until_date = бессрочный мут
        )

        logger.info(
            f"🔇 [GROUP_CAPTCHA] Пользователь замучен БЕССРОЧНО: "
            f"user_id={user.id}, chat_id={chat.id}"
        )

    except TelegramAPIError as e:
        logger.error(f"❌ [GROUP_CAPTCHA] Ошибка мута: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 6: Планируем удаление сообщения через TTL
    # TTL берётся из настроек (join_captcha_message_ttl или invite_captcha_message_ttl)
    # Сообщение удаляется, но мут остаётся (бессрочный)
    # ═══════════════════════════════════════════════════════════════════════
    # Используем get_message_ttl_for_mode - время автоудаления сообщения в группе
    message_ttl = settings.get_message_ttl_for_mode(mode)

    asyncio.create_task(
        _delete_group_captcha_message_after_timeout(
            bot=bot,
            chat_id=chat.id,
            user_id=user.id,
            message_id=msg.message_id,
            timeout=message_ttl,
        )
    )

    logger.info(
        f"⏰ [GROUP_CAPTCHA] Удаление сообщения через {message_ttl}с (настройка TTL)"
    )

    return True


async def _delete_group_captcha_message_after_timeout(
    bot: Bot,
    chat_id: int,
    user_id: int,
    message_id: int,
    timeout: int,
) -> None:
    """
    Удаляет сообщение капчи в группе после таймаута.

    Мут остаётся! Пользователь остаётся замученным пока не пройдёт капчу.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя
        message_id: ID сообщения
        timeout: Таймаут в секундах
    """
    from bot.services.captcha.dm_flow_service import get_join_request

    # Ждём таймаут
    logger.debug(
        f"⏳ [GROUP_CAPTCHA_TTL] Ожидание: {timeout}с, "
        f"user_id={user_id}, chat_id={chat_id}, msg_id={message_id}"
    )
    await asyncio.sleep(timeout)

    # Проверяем не прошёл ли уже пользователь капчу
    join_request = await get_join_request(user_id, chat_id)
    logger.debug(
        f"🔍 [GROUP_CAPTCHA_TTL] После ожидания: join_request={'найден' if join_request else 'НЕ найден'}, "
        f"user_id={user_id}, chat_id={chat_id}"
    )

    if join_request:
        # Капча ещё не пройдена - удаляем сообщение
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(
                f"🗑️ [GROUP_CAPTCHA] Сообщение удалено: "
                f"user_id={user_id}, chat_id={chat_id}"
            )
        except Exception as e:
            logger.debug(f"Не удалось удалить сообщение: {e}")

        # НЕ снимаем мут - пользователь остаётся замученным
        logger.info(
            f"⏰ [GROUP_CAPTCHA] Время вышло, мут сохранён: "
            f"user_id={user_id}, chat_id={chat_id}"
        )
    else:
        # Капча уже пройдена - ничего не делаем
        logger.debug(
            f"🔍 [GROUP_CAPTCHA] Капча уже пройдена: "
            f"user_id={user_id}, chat_id={chat_id}"
        )


async def _delete_captcha_after_timeout(
    bot: Bot,
    chat_id: int,
    user_id: int,
    target_chat_id: int,
    message_id: int,
    timeout: int,
) -> None:
    """
    Удаляет сообщение с капчей после таймаута.

    Внутренняя функция, запускается как asyncio task.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя
        target_chat_id: ID чата с сообщением
        message_id: ID сообщения
        timeout: Таймаут в секундах
    """
    # Ждём таймаут
    await asyncio.sleep(timeout)

    # Отменяем напоминания и удаляем последнее
    from bot.services.captcha.reminder_service import (
        cancel_reminders,
        _delete_previous_reminder,
        schedule_dialog_cleanup,
    )

    # Удаляем последнее напоминание
    await _delete_previous_reminder(bot, user_id)

    # Отменяем оставшиеся напоминания
    await cancel_reminders(user_id, chat_id)

    # Очищаем капчу
    await cleanup_user_captcha(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        delete_message=True,
    )

    logger.info(
        f"⏰ [CAPTCHA_TIMEOUT] Капча удалена по таймауту: "
        f"user_id={user_id}, chat_id={chat_id}"
    )

    # Для VISUAL_DM: отклоняем join request и планируем чистку диалога
    if target_chat_id == user_id:
        # Отклоняем join request
        try:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
            logger.info(
                f"🚫 [CAPTCHA_TIMEOUT] Join request отклонён: "
                f"user_id={user_id}, chat_id={chat_id}"
            )
        except Exception as e:
            logger.warning(f"⚠️ [CAPTCHA_TIMEOUT] Не удалось отклонить: {e}")

        # Отправляем сообщение о провале
        from bot.handlers.captcha.captcha_messages import send_failure_message
        from bot.services.captcha.dm_flow_service import save_captcha_message_id

        failure_msg = await send_failure_message(bot, user_id, reason="timeout")
        if failure_msg:
            await save_captcha_message_id(user_id, failure_msg.message_id)

        # Планируем чистку диалога (берём из настроек)
        try:
            from bot.database.session import get_session
            async with get_session() as session:
                settings = await get_captcha_settings(session, chat_id)
                cleanup_delay = settings.dialog_cleanup_seconds

                if cleanup_delay > 0:
                    await schedule_dialog_cleanup(
                        bot=bot,
                        user_id=user_id,
                        cleanup_seconds=cleanup_delay,
                    )
                    logger.info(
                        f"🧹 [CAPTCHA_TIMEOUT] Чистка запланирована через {cleanup_delay}с"
                    )
        except Exception as e:
            logger.error(f"❌ [CAPTCHA_TIMEOUT] Ошибка планирования чистки: {e}")


async def process_captcha_success(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    mode: CaptchaMode,
) -> None:
    """
    Обрабатывает успешное прохождение капчи.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        mode: Режим капчи
    """
    from bot.handlers.captcha.captcha_messages import send_success_message

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 0: Отменяем напоминания
    # ═══════════════════════════════════════════════════════════════════════
    await cancel_reminders(user_id, chat_id)

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Очищаем капчу
    # ═══════════════════════════════════════════════════════════════════════
    await cleanup_user_captcha(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        delete_message=True,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1.5: Удаляем join_request из Redis
    # КРИТИЧНО: Это останавливает GROUP captcha timeout от повторного мута!
    # ═══════════════════════════════════════════════════════════════════════
    from bot.services.captcha.dm_flow_service import delete_join_request
    await delete_join_request(user_id, chat_id)

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Для Visual Captcha - одобряем join request и отправляем сообщение успеха
    # ═══════════════════════════════════════════════════════════════════════
    if mode == CaptchaMode.VISUAL_DM:
        try:
            await bot.approve_chat_join_request(chat_id, user_id)
            logger.info(
                f"✅ [CAPTCHA_SUCCESS] Join request одобрен: "
                f"user_id={user_id}, chat_id={chat_id}"
            )
        except TelegramAPIError as e:
            logger.error(
                f"❌ [CAPTCHA_SUCCESS] Ошибка одобрения join request: {e}"
            )

        # ═══════════════════════════════════════════════════════════════════
        # Отправляем сообщение об успехе с кнопкой перехода в группу
        # ═══════════════════════════════════════════════════════════════════
        try:
            # Получаем информацию о группе
            chat = await bot.get_chat(chat_id)
            group_name = chat.title or "группу"

            # Формируем ссылку на группу
            if chat.username:
                group_link = f"https://t.me/{chat.username}"
            else:
                # Для приватных групп пробуем создать invite link
                try:
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        member_limit=1,
                    )
                    group_link = invite.invite_link
                except Exception:
                    group_link = None

            # Отправляем сообщение об успехе
            success_msg = await send_success_message(
                bot=bot,
                user_id=user_id,
                group_name=group_name,
                group_link=group_link,
            )

            # Сохраняем ID для последующей чистки
            if success_msg:
                await save_captcha_message_id(user_id, success_msg.message_id)

        except TelegramAPIError as e:
            logger.warning(
                f"⚠️ [CAPTCHA_SUCCESS] Не удалось отправить сообщение успеха: {e}"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Для групповых капч - снимаем мут
    # Но сначала проверяем нет ли активного ограничения в БД
    # ═══════════════════════════════════════════════════════════════════════
    if mode in (CaptchaMode.JOIN_GROUP, CaptchaMode.INVITE_GROUP):
        # Проверяем есть ли активное ограничение
        restriction = await check_and_restore_restriction(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user_id=user_id,
        )

        if restriction:
            # Есть активное ограничение - не снимаем мут
            logger.info(
                f"🔒 [CAPTCHA_SUCCESS] Мут сохранён из-за ограничения: "
                f"user_id={user_id}, reason={restriction.reason}"
            )
        else:
            # Нет активного ограничения - снимаем мут
            try:
                # Полные права
                permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                    can_pin_messages=False,  # Пин оставляем выключенным
                    can_change_info=False,
                )

                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                )

                logger.info(
                    f"🔊 [CAPTCHA_SUCCESS] Мут снят: "
                    f"user_id={user_id}, chat_id={chat_id}"
                )

            except TelegramAPIError as e:
                logger.error(
                    f"❌ [CAPTCHA_SUCCESS] Ошибка снятия мута: {e}"
                )

        # ═══════════════════════════════════════════════════════════════════
        # ШАГ 3.5: Отправляем сообщение успеха для JOIN_GROUP/INVITE_GROUP
        # ═══════════════════════════════════════════════════════════════════
        try:
            # Получаем информацию о группе
            chat = await bot.get_chat(chat_id)
            group_name = chat.title or "группу"

            # Формируем ссылку на группу
            if chat.username:
                group_link = f"https://t.me/{chat.username}"
            else:
                group_link = None

            # Отправляем сообщение об успехе
            success_msg = await send_success_message(
                bot=bot,
                user_id=user_id,
                group_name=group_name,
                group_link=group_link,
            )

            # Сохраняем ID для последующей чистки
            if success_msg:
                await save_captcha_message_id(user_id, success_msg.message_id)

            # Планируем чистку диалога
            settings = await get_captcha_settings(session, chat_id)
            if settings.dialog_cleanup_seconds > 0:
                await schedule_dialog_cleanup(
                    bot=bot,
                    user_id=user_id,
                    cleanup_seconds=settings.dialog_cleanup_seconds,
                )

        except TelegramAPIError as e:
            logger.warning(
                f"⚠️ [CAPTCHA_SUCCESS] Не удалось отправить сообщение успеха: {e}"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 4: Планируем чистку диалога (только для VISUAL_DM)
    # ═══════════════════════════════════════════════════════════════════════
    if mode == CaptchaMode.VISUAL_DM:
        # Получаем настройки для dialog_cleanup_seconds
        settings = await get_captcha_settings(session, chat_id)
        if settings.dialog_cleanup_seconds > 0:
            await schedule_dialog_cleanup(
                bot=bot,
                user_id=user_id,
                cleanup_seconds=settings.dialog_cleanup_seconds,
            )

    logger.info(
        f"🎉 [CAPTCHA_SUCCESS] Капча пройдена: "
        f"user_id={user_id}, chat_id={chat_id}, mode={mode.value}"
    )


async def process_captcha_failure(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    mode: CaptchaMode,
    reason: str = "wrong_answer",
) -> None:
    """
    Обрабатывает неудачное прохождение капчи.

    Args:
        bot: Экземпляр бота
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
        mode: Режим капчи
        reason: Причина ("wrong_answer" | "timeout" | "max_attempts")
    """
    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 0: Отменяем напоминания
    # ═══════════════════════════════════════════════════════════════════════
    await cancel_reminders(user_id, chat_id)

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Очищаем капчу
    # ═══════════════════════════════════════════════════════════════════════
    await cleanup_user_captcha(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        delete_message=True,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Для Visual Captcha - отклоняем join request
    # ═══════════════════════════════════════════════════════════════════════
    if mode == CaptchaMode.VISUAL_DM:
        try:
            await bot.decline_chat_join_request(chat_id, user_id)
            logger.info(
                f"❌ [CAPTCHA_FAILURE] Join request отклонён: "
                f"user_id={user_id}, chat_id={chat_id}, reason={reason}"
            )
        except TelegramAPIError as e:
            logger.debug(
                f"Не удалось отклонить join request: {e}"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Для групповых капч - оставляем в муте (НЕ кикаем!)
    # Пользователь был замучен бессрочно при входе
    # При провале капчи мут сохраняется
    # ═══════════════════════════════════════════════════════════════════════
    if mode in (CaptchaMode.JOIN_GROUP, CaptchaMode.INVITE_GROUP):
        # НЕ кикаем пользователя - оставляем в муте
        # Мут уже установлен бессрочно при входе в группу
        # Пользователь может попробовать ещё раз позже
        logger.info(
            f"🔇 [CAPTCHA_FAILURE] Мут сохранён (без кика): "
            f"user_id={user_id}, chat_id={chat_id}, reason={reason}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # ШАГ 4: Планируем чистку диалога (только для VISUAL_DM)
    # ═══════════════════════════════════════════════════════════════════════
    if mode == CaptchaMode.VISUAL_DM:
        # Получаем настройки для dialog_cleanup_seconds
        settings = await get_captcha_settings(session, chat_id)
        if settings.dialog_cleanup_seconds > 0:
            await schedule_dialog_cleanup(
                bot=bot,
                user_id=user_id,
                cleanup_seconds=settings.dialog_cleanup_seconds,
            )

    logger.info(
        f"❌ [CAPTCHA_FAILURE] Капча провалена: "
        f"user_id={user_id}, chat_id={chat_id}, "
        f"mode={mode.value}, reason={reason}"
    )
