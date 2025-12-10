# ============================================================
# МОДУЛЬ "УПРАВЛЕНИЕ СООБЩЕНИЯМИ" - ФИЛЬТР-ХЕНДЛЕРЫ
# ============================================================
# Этот файл содержит обработчики для:
# - Удаления команд (/xxx) от админов и пользователей
# - Удаления системных сообщений (вход, выход, закреп, фото)
# - Репин (автозакрепление) - перезакреп при закрепе другого сообщения
#
# Все хендлеры вызываются из group_message_coordinator.py
# для избежания конфликтов с другими модулями.
# ============================================================

# Импортируем логгер для записи событий
import logging

# Импортируем типы из aiogram
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatType

# Импортируем SQLAlchemy сессию
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервис для работы с настройками
from bot.services.message_management_service import (
    should_delete_command,
    should_delete_system_message,
    get_settings
)

# Импортируем утилиту проверки прав админа
from bot.handlers.antispam_handlers.antispam_filter_handler import is_user_admin

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для фильтров
mm_filter_router = Router(name='mm_filters')


# ============================================================
# ФУНКЦИИ ДЛЯ ВЫЗОВА ИЗ КООРДИНАТОРА
# ============================================================
# Эти функции вызываются из group_message_coordinator.py
# и возвращают True если сообщение было обработано (удалено)

async def process_command_message(
    message: Message,
    session: AsyncSession
) -> bool:
    """
    Обрабатывает сообщение-команду для возможного удаления.

    Проверяет настройки группы и удаляет команду если:
    - Для админов включено delete_admin_commands
    - Для пользователей включено delete_user_commands

    Args:
        message: Сообщение с командой
        session: Сессия БД

    Returns:
        True если команда была удалена, False иначе
    """
    # Проверяем что сообщение в группе
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False

    # Проверяем что это команда (начинается с /)
    if not message.text or not message.text.startswith('/'):
        return False

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Определяем является ли пользователь админом
    is_admin = await is_user_admin(message.bot, chat_id, user_id)

    # Проверяем нужно ли удалять команду
    should_delete = await should_delete_command(
        chat_id=chat_id,
        is_admin=is_admin,
        session=session
    )

    if not should_delete:
        return False

    # Удаляем команду
    try:
        await message.delete()
        logger.debug(
            f"[MessageManagement] Удалена команда: chat_id={chat_id}, "
            f"user_id={user_id}, is_admin={is_admin}, text={message.text[:20]}"
        )
        return True
    except Exception as e:
        logger.warning(
            f"[MessageManagement] Не удалось удалить команду: {e}"
        )
        return False


async def process_system_message(
    message: Message,
    session: AsyncSession
) -> bool:
    """
    Обрабатывает системное сообщение для возможного удаления.

    Проверяет тип сообщения и настройки группы:
    - new_chat_members - вход участников
    - left_chat_member - выход участников
    - pinned_message - закреп сообщения
    - new_chat_title/new_chat_photo/delete_chat_photo - изменение группы

    Args:
        message: Системное сообщение
        session: Сессия БД

    Returns:
        True если сообщение было удалено, False иначе
    """
    # Проверяем что сообщение в группе
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False

    chat_id = message.chat.id

    # Определяем тип системного сообщения
    message_type = _get_system_message_type(message)

    if message_type is None:
        return False

    # Проверяем нужно ли удалять это сообщение
    should_delete = await should_delete_system_message(
        chat_id=chat_id,
        message_type=message_type,
        session=session
    )

    if not should_delete:
        return False

    # Удаляем сообщение
    try:
        await message.delete()
        logger.debug(
            f"[MessageManagement] Удалено системное сообщение: "
            f"chat_id={chat_id}, type={message_type}"
        )
        return True
    except Exception as e:
        logger.warning(
            f"[MessageManagement] Не удалось удалить системное сообщение: {e}"
        )
        return False


async def process_pin_event(
    message: Message,
    session: AsyncSession
) -> bool:
    """
    Обрабатывает событие закрепления сообщения для репина.

    Если включён репин и закреплено другое сообщение,
    перезакрепляет защищённое сообщение.

    Args:
        message: Сообщение с уведомлением о закрепе
        session: Сессия БД

    Returns:
        True если был выполнен репин, False иначе
    """
    # Проверяем что это уведомление о закрепе
    if message.pinned_message is None:
        return False

    # Проверяем что сообщение в группе
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False

    chat_id = message.chat.id

    # ─────────────────────────────────────────────────────────
    # ИГНОРИРУЕМ ЗАКРЕПЫ ОТ СВЯЗАННЫХ КАНАЛОВ
    # ─────────────────────────────────────────────────────────
    # Если sender_chat существует и это канал — игнорируем
    if message.sender_chat and message.sender_chat.type == 'channel':
        logger.debug(
            f"[MessageManagement] Игнорируем закреп от канала: "
            f"chat_id={chat_id}, channel_id={message.sender_chat.id}"
        )
        return False

    # ─────────────────────────────────────────────────────────
    # ПОЛУЧАЕМ НАСТРОЙКИ РЕПИНА
    # ─────────────────────────────────────────────────────────
    settings = await get_settings(chat_id, session)

    # Если настроек нет или репин выключен — ничего не делаем
    if settings is None or not settings.repin_enabled:
        return False

    # Если message_id не задан — ничего не делаем
    if settings.repin_message_id is None:
        return False

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРЯЕМ: ЗАКРЕПЛЕНО ДРУГОЕ СООБЩЕНИЕ?
    # ─────────────────────────────────────────────────────────
    pinned_message_id = message.pinned_message.message_id

    # Если закреплено то же сообщение — ничего не делаем
    if pinned_message_id == settings.repin_message_id:
        return False

    # ─────────────────────────────────────────────────────────
    # ПЕРЕЗАКРЕПЛЯЕМ ЗАЩИЩЁННОЕ СООБЩЕНИЕ
    # ─────────────────────────────────────────────────────────
    try:
        await message.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=settings.repin_message_id,
            disable_notification=True  # Без уведомления
        )

        logger.info(
            f"[MessageManagement] Репин: перезакреплено сообщение "
            f"chat_id={chat_id}, message_id={settings.repin_message_id}"
        )

        return True

    except Exception as e:
        logger.error(
            f"[MessageManagement] Ошибка репина: chat_id={chat_id}, "
            f"message_id={settings.repin_message_id}, error={e}"
        )
        return False


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _get_system_message_type(message: Message) -> str | None:
    """
    Определяет тип системного сообщения.

    Args:
        message: Сообщение для анализа

    Returns:
        Строка с типом или None если это не системное сообщение
    """
    # Вход участников
    if message.new_chat_members:
        return 'new_chat_members'

    # Выход участника
    if message.left_chat_member:
        return 'left_chat_member'

    # Закреп сообщения
    if message.pinned_message:
        return 'pinned_message'

    # Изменение названия группы
    if message.new_chat_title:
        return 'new_chat_title'

    # Изменение фото группы
    if message.new_chat_photo:
        return 'new_chat_photo'

    # Удаление фото группы
    if message.delete_chat_photo:
        return 'delete_chat_photo'

    # Не системное сообщение
    return None


def is_system_message(message: Message) -> bool:
    """
    Проверяет является ли сообщение системным.

    Args:
        message: Сообщение для проверки

    Returns:
        True если это системное сообщение
    """
    return _get_system_message_type(message) is not None


def is_command_message(message: Message) -> bool:
    """
    Проверяет является ли сообщение командой.

    Args:
        message: Сообщение для проверки

    Returns:
        True если это команда (начинается с /)
    """
    return bool(message.text and message.text.startswith('/'))
