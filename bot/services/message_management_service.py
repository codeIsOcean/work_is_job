# ============================================================
# СЕРВИС УПРАВЛЕНИЯ СООБЩЕНИЯМИ
# ============================================================
# Этот файл содержит бизнес-логику для модуля "Управление сообщениями":
# - CRUD операции с настройками
# - Получение/обновление настроек группы
# - Логика репина
#
# Сервис работает с моделью MessageManagementSettings
# и инкапсулирует все операции с БД.
# ============================================================

# Импортируем логгер для записи событий
import logging

# Импортируем типы для аннотаций
from typing import Optional

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модель настроек
from bot.database.models_message_management import MessageManagementSettings

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ФУНКЦИИ ПОЛУЧЕНИЯ НАСТРОЕК
# ============================================================

async def get_settings(
    chat_id: int,
    session: AsyncSession
) -> Optional[MessageManagementSettings]:
    """
    Получает настройки управления сообщениями для группы.

    Ищет запись в БД по chat_id. Если не найдена — возвращает None.
    Для создания записи если не существует — используй get_or_create_settings().

    Args:
        chat_id: ID группы (Telegram chat_id)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        MessageManagementSettings или None если не найдено
    """
    # Формируем SQL запрос SELECT * WHERE chat_id = ?
    query = select(MessageManagementSettings).where(
        MessageManagementSettings.chat_id == chat_id
    )

    # Выполняем запрос и получаем результат
    result = await session.execute(query)

    # Возвращаем первую (и единственную) запись или None
    return result.scalar_one_or_none()


async def get_or_create_settings(
    chat_id: int,
    session: AsyncSession
) -> MessageManagementSettings:
    """
    Получает или создаёт настройки управления сообщениями для группы.

    Если запись существует — возвращает её.
    Если не существует — создаёт новую с дефолтными значениями.

    Это основной метод для получения настроек — он гарантирует
    что запись всегда существует.

    Args:
        chat_id: ID группы (Telegram chat_id)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        MessageManagementSettings: Настройки группы (существующие или новые)
    """
    # Пробуем получить существующие настройки
    settings = await get_settings(chat_id, session)

    # Если настройки уже существуют — возвращаем их
    if settings is not None:
        return settings

    # Настройки не существуют — создаём новые с дефолтными значениями
    # Все Boolean поля по умолчанию False (определено в модели)
    settings = MessageManagementSettings(chat_id=chat_id)

    # Добавляем запись в сессию (INSERT)
    session.add(settings)

    # Сохраняем изменения в БД
    await session.commit()

    # Обновляем объект из БД (получаем сгенерированный id)
    await session.refresh(settings)

    # Логируем создание новых настроек
    logger.info(
        f"[MessageManagement] Созданы настройки для группы chat_id={chat_id}"
    )

    return settings


# ============================================================
# ФУНКЦИИ ОБНОВЛЕНИЯ НАСТРОЕК
# ============================================================

async def update_settings(
    chat_id: int,
    session: AsyncSession,
    **kwargs
) -> MessageManagementSettings:
    """
    Обновляет настройки управления сообщениями для группы.

    Принимает любые поля модели MessageManagementSettings как **kwargs.
    Обновляет только переданные поля, остальные не трогает.

    Args:
        chat_id: ID группы
        session: Сессия БД
        **kwargs: Поля для обновления (например: delete_user_commands=True)

    Returns:
        MessageManagementSettings: Обновлённые настройки

    Example:
        # Включить удаление команд пользователей
        await update_settings(chat_id, session, delete_user_commands=True)

        # Включить репин с указанием message_id
        await update_settings(
            chat_id, session,
            repin_enabled=True,
            repin_message_id=12345
        )
    """
    # Получаем или создаём настройки
    settings = await get_or_create_settings(chat_id, session)

    # Обновляем только переданные поля
    for key, value in kwargs.items():
        # Проверяем что атрибут существует в модели
        if hasattr(settings, key):
            # Устанавливаем новое значение
            setattr(settings, key, value)
        else:
            # Логируем попытку установить несуществующий атрибут
            logger.warning(
                f"[MessageManagement] Попытка установить неизвестный атрибут: {key}"
            )

    # Сохраняем изменения в БД
    await session.commit()

    # Обновляем объект из БД
    await session.refresh(settings)

    # Логируем обновление
    logger.info(
        f"[MessageManagement] Обновлены настройки для chat_id={chat_id}: {kwargs}"
    )

    return settings


# ============================================================
# ФУНКЦИИ ДЛЯ РЕПИНА
# ============================================================

async def set_repin_message(
    chat_id: int,
    message_id: int,
    session: AsyncSession
) -> MessageManagementSettings:
    """
    Устанавливает сообщение для репина и включает репин.

    Вызывается командой /repin в ответ на сообщение.
    После вызова бот будет автоматически перезакреплять это сообщение.

    Args:
        chat_id: ID группы
        message_id: ID сообщения которое нужно закреплять
        session: Сессия БД

    Returns:
        MessageManagementSettings: Обновлённые настройки
    """
    # Обновляем оба поля: включаем репин и устанавливаем message_id
    settings = await update_settings(
        chat_id,
        session,
        repin_enabled=True,
        repin_message_id=message_id
    )

    # Логируем установку репина
    logger.info(
        f"[MessageManagement] Установлен репин: chat_id={chat_id}, "
        f"message_id={message_id}"
    )

    return settings


async def disable_repin(
    chat_id: int,
    session: AsyncSession
) -> MessageManagementSettings:
    """
    Отключает репин для группы.

    Вызывается командой /unrepin.
    После вызова бот перестаёт автоматически перезакреплять сообщение.

    Args:
        chat_id: ID группы
        session: Сессия БД

    Returns:
        MessageManagementSettings: Обновлённые настройки
    """
    # Отключаем репин (message_id оставляем — вдруг включат снова)
    settings = await update_settings(
        chat_id,
        session,
        repin_enabled=False
    )

    # Логируем отключение репина
    logger.info(
        f"[MessageManagement] Отключён репин: chat_id={chat_id}"
    )

    return settings


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def should_delete_command(
    chat_id: int,
    is_admin: bool,
    session: AsyncSession
) -> bool:
    """
    Проверяет нужно ли удалять команду.

    Учитывает настройки группы и статус пользователя (админ/не админ).

    Args:
        chat_id: ID группы
        is_admin: Является ли пользователь администратором
        session: Сессия БД

    Returns:
        bool: True если команду нужно удалить
    """
    # Получаем настройки (если нет — значит удаление выключено)
    settings = await get_settings(chat_id, session)

    # Если настроек нет — не удаляем
    if settings is None:
        return False

    # Проверяем в зависимости от статуса пользователя
    if is_admin:
        # Для админов проверяем delete_admin_commands
        return settings.delete_admin_commands
    else:
        # Для пользователей проверяем delete_user_commands
        return settings.delete_user_commands


async def should_delete_system_message(
    chat_id: int,
    message_type: str,
    session: AsyncSession
) -> bool:
    """
    Проверяет нужно ли удалять системное сообщение.

    Args:
        chat_id: ID группы
        message_type: Тип сообщения (new_chat_members, left_chat_member, и т.д.)
        session: Сессия БД

    Returns:
        bool: True если сообщение нужно удалить
    """
    # Получаем настройки
    settings = await get_settings(chat_id, session)

    # Если настроек нет — не удаляем
    if settings is None:
        return False

    # Маппинг типа сообщения на настройку
    # Ключ — content_type из aiogram, значение — имя атрибута модели
    type_mapping = {
        'new_chat_members': 'delete_join_messages',
        'left_chat_member': 'delete_leave_messages',
        'pinned_message': 'delete_pin_messages',
        'new_chat_title': 'delete_chat_photo_messages',
        'new_chat_photo': 'delete_chat_photo_messages',
        'delete_chat_photo': 'delete_chat_photo_messages',
    }

    # Получаем имя атрибута для этого типа сообщения
    setting_name = type_mapping.get(message_type)

    # Если тип не в маппинге — не удаляем
    if setting_name is None:
        return False

    # Возвращаем значение соответствующей настройки
    return getattr(settings, setting_name, False)
