# bot/handlers/content_filter/crossmsg_callbacks.py
"""
Обработчики callback кнопок в журнале кросс-сообщение детекции.

Кнопки в журнале позволяют админу:
- Размутить пользователя
- Мут навсегда
- Бан навсегда
- OK (подтвердить, убрать кнопки)

Формат callback_data: cm:action:chat_id:user_id
cm = cross message
"""

# Импортируем логгер для записи событий
import logging

# Импортируем aiogram
from aiogram import Router, F
from aiogram.types import CallbackQuery, ChatPermissions
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для callback обработчиков
crossmsg_callbacks_router = Router(name="crossmsg_callbacks")


def parse_callback_data(data: str) -> tuple:
    """
    Парсит callback_data формата cm:action:chat_id:user_id.

    Args:
        data: Строка callback_data

    Returns:
        Кортеж (action, chat_id, user_id) или (None, None, None) при ошибке
    """
    # Разбиваем строку по двоеточию
    parts = data.split(":")

    # Проверяем что это наш callback (начинается с 'cm')
    if len(parts) != 4 or parts[0] != "cm":
        return None, None, None

    # Извлекаем данные
    action = parts[1]
    try:
        chat_id = int(parts[2])
        user_id = int(parts[3])
    except ValueError:
        return None, None, None

    return action, chat_id, user_id


@crossmsg_callbacks_router.callback_query(F.data.startswith("cm:"))
async def handle_crossmsg_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Единый обработчик всех callback кнопок кросс-сообщение детекции.

    Поддерживаемые действия:
    - unmute: Размутить пользователя
    - permmute: Мут навсегда
    - ban: Бан навсегда
    - ok: Подтвердить (убрать кнопки)

    Args:
        callback: Callback query от Telegram
        session: Асинхронная сессия SQLAlchemy
    """
    # Парсим callback_data
    action, chat_id, user_id = parse_callback_data(callback.data)

    # Если парсинг не удался — игнорируем
    if action is None:
        logger.warning(f"[CROSSMSG] Невалидный callback_data: {callback.data}")
        await callback.answer("Ошибка: невалидные данные")
        return

    # Получаем бота
    bot = callback.bot

    # Получаем ID админа который нажал кнопку
    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name or str(admin_id)

    # Логируем действие
    logger.info(
        f"[CROSSMSG] Callback: action={action}, chat_id={chat_id}, "
        f"user_id={user_id}, admin_id={admin_id}"
    )

    # ─────────────────────────────────────────────────────────
    # OK — подтвердить (убираем кнопки)
    # ─────────────────────────────────────────────────────────
    if action == "ok":
        try:
            # Убираем кнопки, добавляем отметку
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"✅ <b>Подтверждено</b> админом {admin_name}"
            )

            await callback.message.edit_text(
                text=new_text,
                parse_mode="HTML",
                reply_markup=None,  # Убираем кнопки
            )
            await callback.answer("✅ Подтверждено")

        except TelegramAPIError as e:
            logger.error(f"[CROSSMSG] Ошибка подтверждения: {e}")
            await callback.answer("❌ Ошибка")
        return

    # ─────────────────────────────────────────────────────────
    # UNMUTE — размутить пользователя
    # ─────────────────────────────────────────────────────────
    elif action == "unmute":
        try:
            # Восстанавливаем все права (стандартные для группы)
            full_permissions = ChatPermissions(
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
                can_change_info=False,  # Обычно нельзя
                can_invite_users=True,
                can_pin_messages=False,  # Обычно нельзя
            )

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=full_permissions,
            )

            # Обновляем сообщение
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"🔓 <b>Размучен</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🔓 Пользователь размучен")

            logger.info(
                f"[CROSSMSG] Размут: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[CROSSMSG] Ошибка размута: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    # ─────────────────────────────────────────────────────────
    # PERMMUTE — мут навсегда
    # ─────────────────────────────────────────────────────────
    elif action == "permmute":
        try:
            # Мут навсегда (все права запрещены)
            no_permissions = ChatPermissions(
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
            )

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=no_permissions,
                until_date=None,  # Навсегда
            )

            # Обновляем сообщение
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"🔇 <b>Мут навсегда</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🔇 Пользователь замучен навсегда")

            logger.info(
                f"[CROSSMSG] Перманентный мут: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[CROSSMSG] Ошибка перманентного мута: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    # ─────────────────────────────────────────────────────────
    # BAN — бан навсегда
    # ─────────────────────────────────────────────────────────
    elif action == "ban":
        try:
            await bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=None,  # Навсегда
            )

            # Обновляем сообщение в журнале
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"🚫 <b>Забанен навсегда</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🚫 Пользователь забанен навсегда")

            logger.info(
                f"[CROSSMSG] Перманентный бан: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[CROSSMSG] Ошибка перманентного бана: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    else:
        # Неизвестное действие
        logger.warning(f"[CROSSMSG] Неизвестное действие: {action}")
        await callback.answer("❌ Неизвестное действие")
