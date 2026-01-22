# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK ХЕНДЛЕРЫ ДЛЯ КНОПОК ЖУРНАЛА (РУЧНЫЕ КОМАНДЫ)
# ═══════════════════════════════════════════════════════════════════════════
# Этот файл обрабатывает нажатия на кнопки в журнале модуля ручных команд:
# - mc:unmute — размут в текущей группе
# - mc:unmute_all — размут везде + удаление из БД спаммеров
# - mc:ban — бан пользователя
# - mc:ok — подтверждение (удаление клавиатуры)
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы
from bot.services.manual_commands import apply_unmute, apply_unban
from bot.services.spammer_registry import delete_spammer_record

# Создаём роутер для callbacks
callbacks_router = Router(name="manual_commands_callbacks")

# Настраиваем логгер
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ПАРСИНГ CALLBACK DATA
# ═══════════════════════════════════════════════════════════════════════════
def parse_callback_data(data: str) -> tuple[str, int, int]:
    """
    Парсит callback_data вида "mc:action:user_id:chat_id".

    Returns:
        tuple[str, int, int]: (action, user_id, chat_id)
    """
    parts = data.split(":")
    if len(parts) != 4:
        return ("", 0, 0)

    action = parts[1]
    try:
        user_id = int(parts[2])
        chat_id = int(parts[3])
    except ValueError:
        return ("", 0, 0)

    return (action, user_id, chat_id)


# ═══════════════════════════════════════════════════════════════════════════
# ХЕЛПЕР: ОБНОВЛЕНИЕ СООБЩЕНИЯ ЖУРНАЛА
# ═══════════════════════════════════════════════════════════════════════════
async def update_journal_message(
    callback: CallbackQuery,
    action_text: str,
    admin_name: str,
):
    """
    Обновляет сообщение журнала — добавляет информацию о действии.

    Args:
        callback: CallbackQuery объект
        action_text: Текст действия (например, "Размучен")
        admin_name: Имя админа выполнившего действие
    """
    # Получаем текущий текст сообщения
    old_text = callback.message.text or callback.message.caption or ""

    # Добавляем информацию о действии
    now = datetime.now(timezone.utc)
    action_info = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━"
        f"\n✅ <b>{action_text}</b>"
        f"\n👮 Админ: {admin_name}"
        f"\n🕐 {now.strftime('%d.%m.%Y %H:%M')} UTC"
    )

    new_text = old_text + action_info

    try:
        # Обновляем сообщение (убираем клавиатуру)
        await callback.message.edit_text(
            text=new_text,
            parse_mode="HTML",
            reply_markup=None,
        )
    except TelegramAPIError as e:
        logger.warning(f"[MANUAL_CMD_CB] Failed to update journal: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: РАЗМУТ В ТЕКУЩЕЙ ГРУППЕ
# ═══════════════════════════════════════════════════════════════════════════
@callbacks_router.callback_query(F.data.startswith("mc:unmute:"))
async def handle_unmute_callback(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """Обработчик кнопки 'Размут' — снимает мут в текущей группе."""
    # Парсим callback data
    action, user_id, chat_id = parse_callback_data(callback.data)

    if user_id == 0 or chat_id == 0:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return

    # Применяем размут
    result = await apply_unmute(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        unmute_everywhere=False,
        admin_id=callback.from_user.id,
    )

    if result.success:
        await callback.answer("✅ Пользователь размучен")
        # Обновляем сообщение журнала
        admin_name = callback.from_user.full_name
        await update_journal_message(callback, "Размучен", admin_name)
    else:
        await callback.answer(f"❌ {result.error}", show_alert=True)

    logger.info(
        f"[MANUAL_CMD_CB] unmute: user_id={user_id}, chat_id={chat_id}, "
        f"success={result.success}, by admin={callback.from_user.id}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: РАЗМУТ ВЕЗДЕ + УДАЛЕНИЕ ИЗ БД
# ═══════════════════════════════════════════════════════════════════════════
@callbacks_router.callback_query(F.data.startswith("mc:unmute_all:"))
async def handle_unmute_all_callback(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработчик кнопки 'Размут везде':
    1. Удаляет из БД спаммеров
    2. Размучивает в текущей группе
    """
    # Парсим callback data
    action, user_id, chat_id = parse_callback_data(callback.data)

    if user_id == 0 or chat_id == 0:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return

    # Удаляем из БД спаммеров
    deleted = await delete_spammer_record(session, user_id)

    # Размучиваем в текущей группе
    result = await apply_unmute(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        unmute_everywhere=True,
        admin_id=callback.from_user.id,
    )

    if result.success:
        if deleted:
            await callback.answer("✅ Размучен везде + удалён из БД спаммеров")
            action_text = "Размучен везде + удалён из БД"
        else:
            await callback.answer("✅ Размучен (не был в БД спаммеров)")
            action_text = "Размучен"

        admin_name = callback.from_user.full_name
        await update_journal_message(callback, action_text, admin_name)
    else:
        await callback.answer(f"❌ {result.error}", show_alert=True)

    logger.info(
        f"[MANUAL_CMD_CB] unmute_all: user_id={user_id}, chat_id={chat_id}, "
        f"deleted_from_spammers={deleted}, success={result.success}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: БАН
# ═══════════════════════════════════════════════════════════════════════════
@callbacks_router.callback_query(F.data.startswith("mc:ban:"))
async def handle_ban_callback(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """Обработчик кнопки 'Бан' — банит пользователя."""
    # Парсим callback data
    action, user_id, chat_id = parse_callback_data(callback.data)

    if user_id == 0 or chat_id == 0:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return

    try:
        # Проверяем что пользователь не админ
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ('creator', 'administrator'):
            await callback.answer("❌ Нельзя забанить администратора", show_alert=True)
            return

        # Баним пользователя
        await bot.ban_chat_member(chat_id, user_id)

        await callback.answer("✅ Пользователь забанен")

        # Обновляем сообщение журнала
        admin_name = callback.from_user.full_name
        await update_journal_message(callback, "Забанен", admin_name)

        logger.info(
            f"[MANUAL_CMD_CB] ban: user_id={user_id}, chat_id={chat_id}, "
            f"by admin={callback.from_user.id}"
        )

    except TelegramAPIError as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        logger.error(f"[MANUAL_CMD_CB] ban error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: РАЗБАН
# ═══════════════════════════════════════════════════════════════════════════
@callbacks_router.callback_query(F.data.startswith("mc:unban:"))
async def handle_unban_callback(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """Обработчик кнопки 'Разбан' — разбанивает пользователя."""
    # Парсим callback data
    action, user_id, chat_id = parse_callback_data(callback.data)

    if user_id == 0 or chat_id == 0:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return

    # Применяем разбан
    result = await apply_unban(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        unban_everywhere=True,
        admin_id=callback.from_user.id,
    )

    if result.success:
        await callback.answer("✅ Пользователь разбанен")
        # Обновляем сообщение журнала
        admin_name = callback.from_user.full_name
        await update_journal_message(callback, "Разбанен", admin_name)
    else:
        await callback.answer(f"❌ {result.error}", show_alert=True)

    logger.info(
        f"[MANUAL_CMD_CB] unban: user_id={user_id}, chat_id={chat_id}, "
        f"success={result.success}, by admin={callback.from_user.id}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: OK (ПОДТВЕРЖДЕНИЕ)
# ═══════════════════════════════════════════════════════════════════════════
@callbacks_router.callback_query(F.data.startswith("mc:ok:"))
async def handle_ok_callback(
    callback: CallbackQuery,
):
    """
    Обработчик кнопки 'OK' — просто убирает клавиатуру.
    Означает что админ принял информацию к сведению.
    """
    try:
        # Просто убираем клавиатуру, сообщение оставляем как есть
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅")
    except TelegramAPIError as e:
        logger.warning(f"[MANUAL_CMD_CB] ok error: {e}")
        await callback.answer("✅")

    logger.debug(f"[MANUAL_CMD_CB] ok: by admin={callback.from_user.id}")
