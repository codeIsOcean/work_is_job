# Модуль обработки кнопок действий из журнала антиспама
# Обрабатывает callback-запросы: Мут, Бан, Снять ограничения
import logging
# Импорт datetime для работы с временем ограничений
from datetime import datetime, timedelta, timezone
# Импорт Router для создания роутера
from aiogram import Router, F
# Импорт типов для callback запросов
from aiogram.types import CallbackQuery, ChatPermissions
# Импорт исключений aiogram
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
# Импорт AsyncSession для БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт сервиса сохранения ограничений
from bot.services.restriction_service import save_restriction, deactivate_restriction

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаем роутер для обработки callback кнопок журнала антиспам
antispam_journal_actions_router = Router()


@antispam_journal_actions_router.callback_query(F.data.startswith("aslog:mute:"))
async def handle_mute_from_journal(callback: CallbackQuery, session: AsyncSession):
    """
    Обработчик кнопки "Мут" из журнала антиспам.

    Формат callback_data: aslog:mute:{user_id}:{chat_id}:{restrict_minutes}

    Args:
        callback: Callback запрос от кнопки
        session: Сессия БД
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) < 5:
            await callback.answer("Ошибка: некорректные данные", show_alert=True)
            return

        # Извлекаем параметры
        user_id = int(parts[2])
        chat_id = int(parts[3])
        restrict_minutes = int(parts[4]) if parts[4] != "0" else None

        # Создаем объект с пустыми правами (полный мут)
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        # Определяем время ограничения
        until_date = None
        until_datetime = None
        if restrict_minutes and restrict_minutes > 0:
            until_date = timedelta(minutes=restrict_minutes)
            until_datetime = datetime.now(timezone.utc) + timedelta(minutes=restrict_minutes)

        # Применяем мут через API
        await callback.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date
        )

        # Сохраняем в БД
        bot_info = await callback.bot.me()
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="mute",
            reason="antispam_journal",
            restricted_by=bot_info.id,
            until_date=until_datetime,
        )

        # Формируем сообщение об успехе
        duration_text = f"{restrict_minutes} мин" if restrict_minutes else "навсегда"
        await callback.answer(f"Пользователь замучен на {duration_text}", show_alert=True)

        # Логируем
        logger.info(
            f"[ANTISPAM_JOURNAL] Мут из журнала: user_id={user_id}, "
            f"chat_id={chat_id}, duration={duration_text}"
        )

    except TelegramBadRequest as e:
        await callback.answer(f"Ошибка: {e.message}", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Ошибка мута: {e}")
    except TelegramForbiddenError:
        await callback.answer("У бота нет прав на ограничение участников", show_alert=True)
        logger.error("[ANTISPAM_JOURNAL] Нет прав на ограничение участников")
    except Exception as e:
        await callback.answer("Произошла ошибка", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Неожиданная ошибка мута: {e}", exc_info=True)


@antispam_journal_actions_router.callback_query(F.data.startswith("aslog:ban:"))
async def handle_ban_from_journal(callback: CallbackQuery, session: AsyncSession):
    """
    Обработчик кнопки "Бан" из журнала антиспам.

    Формат callback_data: aslog:ban:{user_id}:{chat_id}

    Args:
        callback: Callback запрос от кнопки
        session: Сессия БД
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Ошибка: некорректные данные", show_alert=True)
            return

        # Извлекаем параметры
        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Баним пользователя через API
        await callback.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)

        # Сохраняем в БД
        bot_info = await callback.bot.me()
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="ban",
            reason="antispam_journal",
            restricted_by=bot_info.id,
            until_date=None,  # Бан навсегда
        )

        await callback.answer("Пользователь заблокирован", show_alert=True)

        # Логируем
        logger.info(
            f"[ANTISPAM_JOURNAL] Бан из журнала: user_id={user_id}, chat_id={chat_id}"
        )

    except TelegramBadRequest as e:
        await callback.answer(f"Ошибка: {e.message}", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Ошибка бана: {e}")
    except TelegramForbiddenError:
        await callback.answer("У бота нет прав на блокировку участников", show_alert=True)
        logger.error("[ANTISPAM_JOURNAL] Нет прав на блокировку участников")
    except Exception as e:
        await callback.answer("Произошла ошибка", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Неожиданная ошибка бана: {e}", exc_info=True)


@antispam_journal_actions_router.callback_query(F.data.startswith("aslog:unmute:"))
async def handle_unmute_from_journal(callback: CallbackQuery, session: AsyncSession):
    """
    Обработчик кнопки "Снять ограничения" из журнала антиспам.

    Формат callback_data: aslog:unmute:{user_id}:{chat_id}

    Args:
        callback: Callback запрос от кнопки
        session: Сессия БД
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Ошибка: некорректные данные", show_alert=True)
            return

        # Извлекаем параметры
        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Сначала пробуем разбанить (на случай если был бан)
        try:
            await callback.bot.unban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                only_if_banned=True  # Только если был забанен
            )
        except TelegramBadRequest:
            # Пользователь не был забанен - это нормально
            pass

        # Затем снимаем ограничения (восстанавливаем права)
        # Получаем дефолтные права чата
        try:
            chat = await callback.bot.get_chat(chat_id)
            default_permissions = chat.permissions or ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            )

            # Восстанавливаем права пользователя
            await callback.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=default_permissions
            )
        except TelegramBadRequest:
            # Если не удалось - пользователь возможно уже не в чате
            pass

        # Деактивируем запись в БД
        await deactivate_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id
        )

        await callback.answer("Ограничения сняты", show_alert=True)

        # Логируем
        logger.info(
            f"[ANTISPAM_JOURNAL] Снятие ограничений из журнала: "
            f"user_id={user_id}, chat_id={chat_id}"
        )

    except TelegramBadRequest as e:
        await callback.answer(f"Ошибка: {e.message}", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Ошибка снятия ограничений: {e}")
    except TelegramForbiddenError:
        await callback.answer("У бота нет прав на управление участниками", show_alert=True)
        logger.error("[ANTISPAM_JOURNAL] Нет прав на управление участниками")
    except Exception as e:
        await callback.answer("Произошла ошибка", show_alert=True)
        logger.error(f"[ANTISPAM_JOURNAL] Неожиданная ошибка снятия ограничений: {e}", exc_info=True)
