# services/group_journal_service.py
"""
Сервис для работы с журналами действий групп (multi-tenant архитектура).
Каждая группа может иметь свой канал для журнала событий.
"""
import logging
from typing import Optional
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from bot.database.models import GroupJournalChannel
from datetime import datetime

logger = logging.getLogger(__name__)


async def get_group_journal_channel(
    session: AsyncSession,
    group_id: int
) -> Optional[GroupJournalChannel]:
    """
    Получает канал журнала для группы.
    
    Args:
        session: Сессия БД
        group_id: ID группы
        
    Returns:
        GroupJournalChannel или None если не привязан
    """
    try:
        result = await session.execute(
            select(GroupJournalChannel).where(
                GroupJournalChannel.group_id == group_id,
                GroupJournalChannel.is_active == True
            )
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Ошибка при получении канала журнала для группы {group_id}: {e}")
        return None


async def link_journal_channel(
    session: AsyncSession,
    group_id: int,
    journal_channel_id: int,
    journal_type: str = "channel",
    journal_title: Optional[str] = None,
    linked_by_user_id: Optional[int] = None
) -> bool:
    """
    Привязывает канал журнала к группе.
    Если уже существует - обновляет.
    
    Args:
        session: Сессия БД
        group_id: ID группы
        journal_channel_id: ID канала/группы журнала
        journal_type: Тип (channel или group)
        journal_title: Название канала
        linked_by_user_id: ID пользователя, который привязал
        
    Returns:
        True если успешно
    """
    try:
        # Проверяем существующую привязку
        existing = await get_group_journal_channel(session, group_id)
        
        if existing:
            # Обновляем существующую
            await session.execute(
                update(GroupJournalChannel)
                .where(GroupJournalChannel.id == existing.id)
                .values(
                    journal_channel_id=journal_channel_id,
                    journal_type=journal_type,
                    journal_title=journal_title,
                    linked_by_user_id=linked_by_user_id,
                    linked_at=datetime.utcnow(),
                    is_active=True
                )
            )
            logger.info(f"✅ Обновлен журнал для группы {group_id}: канал {journal_channel_id}")
        else:
            # Создаем новую
            new_journal = GroupJournalChannel(
                group_id=group_id,
                journal_channel_id=journal_channel_id,
                journal_type=journal_type,
                journal_title=journal_title,
                linked_by_user_id=linked_by_user_id,
                linked_at=datetime.utcnow(),
                is_active=True
            )
            session.add(new_journal)
            logger.info(f"✅ Создан новый журнал для группы {group_id}: канал {journal_channel_id}")
        
        await session.commit()
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при привязке журнала для группы {group_id}: {e}")
        await session.rollback()
        return False


async def unlink_journal_channel(
    session: AsyncSession,
    group_id: int
) -> bool:
    """
    Отвязывает канал журнала от группы.
    
    Args:
        session: Сессия БД
        group_id: ID группы
        
    Returns:
        True если успешно
    """
    try:
        await session.execute(
            delete(GroupJournalChannel).where(
                GroupJournalChannel.group_id == group_id
            )
        )
        await session.commit()
        logger.info(f"✅ Журнал отвязан от группы {group_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отвязке журнала от группы {group_id}: {e}")
        await session.rollback()
        return False


async def send_journal_event(
    bot: Bot,
    session: AsyncSession,
    group_id: int,
    message_text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True
) -> bool:
    """
    Отправляет событие в журнал группы.
    Если журнал не привязан - ничего не делает.
    
    Args:
        bot: Экземпляр бота
        session: Сессия БД
        group_id: ID группы
        message_text: Текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (HTML/Markdown)
        disable_web_page_preview: Отключить превью ссылок
        
    Returns:
        True если отправлено успешно, False если не привязан или ошибка
    """
    try:
        # Получаем канал журнала
        journal = await get_group_journal_channel(session, group_id)
        
        if not journal:
            logger.debug(f"⚠️ Журнал не привязан для группы {group_id}, пропускаем отправку")
            return False
        
        # Отправляем сообщение в канал
        await bot.send_message(
            chat_id=journal.journal_channel_id,
            text=message_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview
        )
        
        # Обновляем время последнего события
        await session.execute(
            update(GroupJournalChannel)
            .where(GroupJournalChannel.id == journal.id)
            .values(last_event_at=datetime.utcnow())
        )
        await session.commit()
        
        logger.debug(f"✅ Событие отправлено в журнал группы {group_id} (канал {journal.journal_channel_id})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке события в журнал группы {group_id}: {e}")
        return False

