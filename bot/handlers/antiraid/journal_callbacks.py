# bot/handlers/antiraid/journal_callbacks.py
"""
Обработчики callback кнопок в журнале Anti-Raid.

Кнопки в журнале позволяют админу:
- Разбанить пользователя
- Удалить сообщение (OK)
- Забанить навсегда
- Снять slowmode
- Закрыть группу

Формат callback_data: ar:action:chat_id:user_id
"""

# Импортируем логгер для записи событий
import logging

# Импортируем aiogram
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для callback обработчиков
antiraid_callbacks_router = Router(name="antiraid_callbacks")


def parse_callback_data(data: str) -> tuple:
    """
    Парсит callback_data формата ar:action:chat_id:user_id.

    Args:
        data: Строка callback_data

    Returns:
        Кортеж (action, chat_id, user_id) или (None, None, None) при ошибке
    """
    # Разбиваем строку по двоеточию
    parts = data.split(":")

    # Проверяем что это наш callback (начинается с 'ar')
    if len(parts) != 4 or parts[0] != "ar":
        return None, None, None

    # Извлекаем данные
    action = parts[1]
    try:
        chat_id = int(parts[2])
        user_id = int(parts[3])
    except ValueError:
        return None, None, None

    return action, chat_id, user_id


@antiraid_callbacks_router.callback_query(F.data.startswith("ar:"))
async def handle_antiraid_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Единый обработчик всех callback кнопок Anti-Raid.

    Поддерживаемые действия:
    - unban: Разбанить пользователя
    - ok: Удалить сообщение в журнале
    - permban: Забанить пользователя навсегда
    - unmute: Размутить пользователя (для join/exit)
    - unslowmode: Снять slowmode (для raid)
    - lock: Закрыть группу (для raid)

    Args:
        callback: Callback query от Telegram
        session: Асинхронная сессия SQLAlchemy
    """
    # Парсим callback_data
    action, chat_id, user_id = parse_callback_data(callback.data)

    # Если парсинг не удался — игнорируем
    if action is None:
        logger.warning(f"[ANTIRAID] Невалидный callback_data: {callback.data}")
        await callback.answer("Ошибка: невалидные данные")
        return

    # Получаем бота
    bot = callback.bot

    # Получаем ID админа который нажал кнопку
    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name or str(admin_id)

    # Логируем действие
    logger.info(
        f"[ANTIRAID] Callback: action={action}, chat_id={chat_id}, "
        f"user_id={user_id}, admin_id={admin_id}"
    )

    # ─────────────────────────────────────────────────────────
    # Обрабатываем действие
    # ─────────────────────────────────────────────────────────
    if action == "ok":
        # Просто удаляем сообщение в журнале
        try:
            await callback.message.delete()
            await callback.answer("✅ Сообщение удалено")
        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка удаления сообщения: {e}")
            await callback.answer("❌ Не удалось удалить сообщение")
        return

    elif action == "unban":
        # Разбаниваем пользователя
        try:
            await bot.unban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                only_if_banned=True,  # Разбанит только если забанен
            )

            # Обновляем сообщение в журнале
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"✅ <b>Разбанен</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,  # Убираем кнопки
                )
            except TelegramAPIError:
                pass  # Сообщение могло не измениться

            await callback.answer("✅ Пользователь разбанен")

            logger.info(
                f"[ANTIRAID] Разбан: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка разбана: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    elif action == "permban":
        # Баним пользователя навсегда (until_date=None)
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
                f"🔒 <b>Забанен навсегда</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🔒 Пользователь забанен навсегда")

            logger.info(
                f"[ANTIRAID] Перманентный бан: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка перманентного бана: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    elif action == "unmute":
        # Размучиваем пользователя (восстанавливаем права)
        from aiogram.types import ChatPermissions

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
                f"🔊 <b>Размучен</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🔊 Пользователь размучен")

            logger.info(
                f"[ANTIRAID] Размут: user_id={user_id}, chat_id={chat_id}, "
                f"admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка размута: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    elif action == "unslowmode":
        # Снимаем slowmode с группы
        try:
            await bot.set_chat_slow_mode_delay(
                chat_id=chat_id,
                slow_mode_delay=0,  # Отключаем slowmode
            )

            # Обновляем сообщение
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"⏩ <b>Slowmode снят</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("⏩ Slowmode снят")

            logger.info(
                f"[ANTIRAID] Slowmode снят: chat_id={chat_id}, admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка снятия slowmode: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    elif action == "lock":
        # Закрываем группу (запрещаем вступление)
        from aiogram.types import ChatPermissions

        try:
            # Ограничиваем права для всех (новые участники не смогут писать)
            locked_permissions = ChatPermissions(
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

            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=locked_permissions,
            )

            # Обновляем сообщение
            old_text = callback.message.text or callback.message.caption or ""
            new_text = (
                f"{old_text}\n\n"
                f"🔐 <b>Группа закрыта</b> админом {admin_name}"
            )

            try:
                await callback.message.edit_text(
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except TelegramAPIError:
                pass

            await callback.answer("🔐 Группа закрыта")

            logger.info(
                f"[ANTIRAID] Группа закрыта: chat_id={chat_id}, admin_id={admin_id}"
            )

        except TelegramAPIError as e:
            logger.error(f"[ANTIRAID] Ошибка закрытия группы: {e}")
            await callback.answer(f"❌ Ошибка: {e}")
        return

    else:
        # Неизвестное действие
        logger.warning(f"[ANTIRAID] Неизвестное действие: {action}")
        await callback.answer(f"❓ Неизвестное действие: {action}")
