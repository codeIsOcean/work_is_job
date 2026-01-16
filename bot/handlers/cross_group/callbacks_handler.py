# bot/handlers/cross_group/callbacks_handler.py
"""
Обработчики callback кнопок для сообщений в журнале.

Обрабатывает действия с кнопок:
- Размут
- Мут на 7 дней
- Бан
- Удаление сообщений
- OK (закрыть)
"""

# Импортируем логгер для записи событий
import logging
# Импортируем datetime для работы со временем
from datetime import datetime, timedelta

# Импортируем типы aiogram
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, ChatPermissions
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для callback хендлеров
router = Router(name="cross_group_callbacks")


# ============================================================
# РАЗМУТ
# ============================================================
@router.callback_query(F.data.startswith("cg:unmute:"))
async def unmute_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик кнопки размута.

    Формат callback_data: cg:unmute:{user_id}:{chat_id}
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Создаём разрешения (всё разрешено)
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

        # Применяем размут
        await callback.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
        )

        # Отправляем уведомление
        await callback.answer(
            f"Пользователь {user_id} размучен в группе",
            show_alert=True
        )

        # Логируем действие
        logger.info(
            f"Размут пользователя {user_id} в группе {chat_id} "
            f"выполнен администратором {callback.from_user.id}"
        )

        # Обновляем сообщение — убираем кнопки
        await _update_journal_message(
            callback=callback,
            action_text=f"Размучен администратором {callback.from_user.full_name}"
        )

    except TelegramAPIError as e:
        logger.error(f"Ошибка при размуте: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Неожиданная ошибка при размуте: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# МУТ НА 7 ДНЕЙ
# ============================================================
@router.callback_query(F.data.startswith("cg:mute7d:"))
async def mute_7d_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик кнопки мута на 7 дней.

    Формат callback_data: cg:mute7d:{user_id}:{chat_id}
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Создаём ограничения (ничего нельзя)
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

        # Дата окончания мута — через 7 дней
        until_date = datetime.utcnow() + timedelta(days=7)

        # Применяем мут
        await callback.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )

        # Отправляем уведомление
        await callback.answer(
            f"Пользователь {user_id} замучен на 7 дней",
            show_alert=True
        )

        # Логируем действие
        logger.info(
            f"Мут на 7 дней пользователя {user_id} в группе {chat_id} "
            f"выполнен администратором {callback.from_user.id}"
        )

        # Обновляем сообщение
        await _update_journal_message(
            callback=callback,
            action_text=f"Мут 7д администратором {callback.from_user.full_name}"
        )

    except TelegramAPIError as e:
        logger.error(f"Ошибка при муте на 7 дней: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Неожиданная ошибка при муте на 7 дней: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# БАН
# ============================================================
@router.callback_query(F.data.startswith("cg:ban:"))
async def ban_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик кнопки бана.

    Формат callback_data: cg:ban:{user_id}:{chat_id}
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Применяем бан
        await callback.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        # Отправляем уведомление
        await callback.answer(
            f"Пользователь {user_id} забанен",
            show_alert=True
        )

        # Логируем действие
        logger.info(
            f"Бан пользователя {user_id} в группе {chat_id} "
            f"выполнен администратором {callback.from_user.id}"
        )

        # Обновляем сообщение
        await _update_journal_message(
            callback=callback,
            action_text=f"Забанен администратором {callback.from_user.full_name}"
        )

    except TelegramAPIError as e:
        logger.error(f"Ошибка при бане: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Неожиданная ошибка при бане: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# УДАЛЕНИЕ СООБЩЕНИЙ
# ============================================================
@router.callback_query(F.data.startswith("cg:delete:"))
async def delete_messages_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик кнопки удаления сообщений.

    Формат callback_data: cg:delete:{user_id}:{chat_id}

    ПРИМЕЧАНИЕ: Telegram Bot API не позволяет удалять все сообщения пользователя.
    Можно удалить только конкретные сообщения по ID.
    Для массового удаления нужен Pyrogram.
    """
    try:
        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Отправляем уведомление
        # TODO: реализовать удаление через Pyrogram
        await callback.answer(
            "Функция удаления сообщений требует Pyrogram. "
            "Пока недоступна.",
            show_alert=True
        )

        # Логируем попытку
        logger.info(
            f"Попытка удаления сообщений пользователя {user_id} в группе {chat_id} "
            f"администратором {callback.from_user.id}"
        )

    except Exception as e:
        logger.error(f"Ошибка при удалении сообщений: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# OK (ЗАКРЫТЬ)
# ============================================================
@router.callback_query(F.data.startswith("cg:ok:"))
async def ok_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик кнопки OK.

    Убирает кнопки с сообщения в журнале.
    """
    try:
        # Обновляем сообщение — убираем клавиатуру
        await callback.message.edit_reply_markup(reply_markup=None)

        # Отправляем уведомление
        await callback.answer("Готово")

    except TelegramAPIError as e:
        # Игнорируем ошибку "message is not modified"
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при закрытии: {e}")
            await callback.answer(f"Ошибка: {e}", show_alert=True)
        else:
            await callback.answer()
    except Exception as e:
        logger.error(f"Неожиданная ошибка при закрытии: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
async def _update_journal_message(
    callback: CallbackQuery,
    action_text: str
):
    """
    Обновляет сообщение в журнале — добавляет информацию о действии.

    Args:
        callback: Callback запрос
        action_text: Текст действия для добавления
    """
    try:
        # Получаем текущий текст сообщения
        current_text = callback.message.text or callback.message.caption or ""

        # Добавляем информацию о действии
        new_text = f"{current_text}\n\n<b>Действие:</b> {action_text}"

        # Обновляем сообщение (убираем клавиатуру)
        await callback.message.edit_text(
            text=new_text,
            parse_mode="HTML",
            reply_markup=None
        )

    except TelegramAPIError as e:
        # Если не удалось обновить текст — просто убираем клавиатуру
        logger.warning(f"Не удалось обновить текст сообщения: {e}")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
