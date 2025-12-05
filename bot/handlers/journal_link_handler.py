# handlers/journal_link_handler.py
"""
Handler для автоматической привязки журнала к группе через пересылку сообщений.
Паттерн: админ пересылает сообщение из канала журнала в группу с ботом.
"""
import logging
import html
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command, Filter
from sqlalchemy.ext.asyncio import AsyncSession
from bot.services.group_journal_service import (
    link_journal_channel,
    get_group_journal_channel,
    unlink_journal_channel
)
from bot.services.groups_settings_in_private_logic import check_granular_permissions

logger = logging.getLogger(__name__)

journal_link_router = Router()


class IsAdminWithChangeInfoFilter(Filter):
    """
    Фильтр: проверяет что пользователь админ с правом change_info.
    Если НЕ админ - фильтр НЕ срабатывает и сообщение идёт в следующие хендлеры.
    """

    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        if not message.from_user:
            return False
        if message.chat.type not in ("group", "supergroup"):
            return False

        user_id = message.from_user.id
        chat_id = message.chat.id

        # Проверяем права - если не админ, возвращаем False (не матчим)
        is_admin = await check_granular_permissions(
            message.bot, user_id, chat_id, 'change_info', session
        )
        return is_admin


@journal_link_router.message(Command("linkjournal"))
async def link_journal_command(message: Message, session: AsyncSession):
    """
    Команда для привязки журнала через пересылку сообщения.
    Использование: /linkjournal и затем переслать сообщение из канала журнала.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("❌ Эта команда работает только в группах!")
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем права: нужно can_change_info для привязки журнала
    if not await check_granular_permissions(message.bot, user_id, chat_id, 'change_info', session):
        await message.reply(
            "❌ Недостаточно прав!\n"
            "Нужно право 'Изменять информацию о группе' для привязки журнала."
        )
        return
    
    # Проверяем, есть ли уже привязанный журнал
    existing = await get_group_journal_channel(session, chat_id)
    
    if existing:
        text = (
            f"📢 <b>Журнал уже привязан</b>\n\n"
            f"Канал журнала: <b>{existing.journal_title or f'ID: {existing.journal_channel_id}'}</b>\n"
            f"Привязан: {existing.linked_at.strftime('%d.%m.%Y %H:%M') if existing.linked_at else 'Неизвестно'}\n\n"
            f"Чтобы перепривязать, перешлите сообщение из нового канала журнала в эту группу.\n"
            f"Чтобы отвязать, используйте /unlinkjournal"
        )
    else:
        text = (
            f"📢 <b>Привязка журнала</b>\n\n"
            f"Чтобы привязать журнал к этой группе:\n"
            f"1. Перешлите любое сообщение из канала/группы журнала в эту группу\n"
            f"2. Бот автоматически определит канал и привяжет его\n\n"
            f"<i>Журнал будет получать все события этой группы</i>"
        )
    
    await message.reply(text, parse_mode="HTML")


@journal_link_router.message(Command("unlinkjournal"))
async def unlink_journal_command(message: Message, session: AsyncSession):
    """
    Команда для отвязки журнала от группы.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("❌ Эта команда работает только в группах!")
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем права
    if not await check_granular_permissions(message.bot, user_id, chat_id, 'change_info', session):
        await message.reply(
            "❌ Недостаточно прав!\n"
            "Нужно право 'Изменять информацию о группе' для отвязки журнала."
        )
        return
    
    existing = await get_group_journal_channel(session, chat_id)
    
    if not existing:
        await message.reply("❌ Журнал не привязан к этой группе.")
        return
    
    # Отвязываем
    success = await unlink_journal_channel(session, chat_id)
    
    if success:
        await message.reply("✅ Журнал успешно отвязан от группы.")
    else:
        await message.reply("❌ Ошибка при отвязке журнала.")


@journal_link_router.message(F.forward_from_chat, IsAdminWithChangeInfoFilter())
async def handle_journal_link_forward(message: Message, session: AsyncSession):
    """
    Обрабатывает пересылку сообщения для автоматической привязки журнала.
    Когда админ пересылает сообщение из канала в группу - привязываем канал как журнал.

    ВАЖНО: Фильтр IsAdminWithChangeInfoFilter проверяет права админа.
    Если НЕ админ - хендлер НЕ вызывается и сообщение идёт в антиспам фильтр.
    """
    # Пропускаем команды
    if message.text and message.text.startswith("/"):
        return

    forward_from_chat = message.forward_from_chat

    # Проверяем, что пересылка из канала или группы
    if not forward_from_chat or forward_from_chat.type not in ("channel", "group", "supergroup"):
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Проверяем, что канал не является самой группой
    if forward_from_chat.id == chat_id:
        return
    
    try:
        # Получаем информацию о канале
        journal_channel_id = forward_from_chat.id
        journal_title = forward_from_chat.title or forward_from_chat.username or f"Канал {journal_channel_id}"
        journal_type = "channel" if forward_from_chat.type == "channel" else "group"
        
        # Привязываем журнал
        success = await link_journal_channel(
            session=session,
            group_id=chat_id,
            journal_channel_id=journal_channel_id,
            journal_type=journal_type,
            journal_title=journal_title,
            linked_by_user_id=user_id
        )
        
        if success:
            # Проверяем, новая ли это привязка
            existing = await get_group_journal_channel(session, chat_id)
            if existing and existing.linked_at and (datetime.utcnow() - existing.linked_at).total_seconds() < 5:
                # Это новая привязка (только что создана)
                journal_link = None
                if forward_from_chat.username:
                    journal_link = f"https://t.me/{forward_from_chat.username}"
                else:
                    journal_link = getattr(forward_from_chat, "invite_link", None)

                group_title = message.chat.title or f"ID: {message.chat.id}"
                if message.chat.username:
                    group_link = f"https://t.me/{message.chat.username}"
                else:
                    group_link = f"tg://openmessage?chat_id={message.chat.id}"

                journal_title_text = html.escape(journal_title)
                group_title_text = html.escape(group_title)

                if journal_link:
                    journal_title_display = f"<a href='{html.escape(journal_link)}'>{journal_title_text}</a>"
                else:
                    journal_title_display = f"<b>{journal_title_text}</b>"

                group_title_display = f"<a href='{html.escape(group_link)}'>{group_title_text}</a>"

                await message.reply(
                    f"✅ <b>Журнал привязан!</b>\n\n"
                    f"📢 Канал журнала: {journal_title_display}\n"
                    f"🏢 Группа: {group_title_display}\n\n"
                    f"Теперь все события этой группы будут логироваться в указанный канал.\n"
                    f"Для отвязки используйте /unlinkjournal",
                    parse_mode="HTML"
                )
            else:
                # Обновлена существующая привязка
                await message.reply(
                    f"✅ <b>Журнал обновлён!</b>\n\n"
                    f"📢 Новый канал: <b>{journal_title}</b>\n"
                    f"🏢 Группа: <b>{message.chat.title}</b>",
                    parse_mode="HTML"
                )
            
            logger.info(
                f"✅ Журнал привязан: группа {chat_id} -> канал {journal_channel_id} "
                f"(привязал пользователь {user_id})"
            )
        else:
            await message.reply("❌ Ошибка при привязке журнала.")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке пересылки для привязки журнала: {e}")
        await message.reply("❌ Ошибка при привязке журнала. Проверьте логи.")

