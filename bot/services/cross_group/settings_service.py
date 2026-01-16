# bot/services/cross_group/settings_service.py
"""
Сервис для работы с настройками кросс-групповой детекции.

Содержит CRUD операции для таблицы cross_group_scammer_settings.
Настройки глобальные для всего бота (singleton — одна запись).
"""

# Импортируем логгер для записи событий
import logging
# Импортируем типы для аннотаций
from typing import Optional, List

# Импортируем AsyncSession для асинхронной работы с БД
from sqlalchemy.ext.asyncio import AsyncSession
# Импортируем select для построения запросов
from sqlalchemy import select

# Импортируем модели кросс-групповой детекции
from bot.database.models_cross_group import (
    CrossGroupScammerSettings,
    CrossGroupActionType,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


async def get_cross_group_settings(
    session: AsyncSession
) -> CrossGroupScammerSettings:
    """
    Получает настройки кросс-групповой детекции.

    Если настроек нет — создаёт запись с дефолтными значениями.
    Всегда возвращает объект настроек (singleton).

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        CrossGroupScammerSettings: Объект настроек модуля
    """
    # Строим запрос для получения настроек (id=1 — singleton)
    query = select(CrossGroupScammerSettings).where(
        CrossGroupScammerSettings.id == 1
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Получаем первую (и единственную) запись
    settings = result.scalar_one_or_none()

    # Если настроек нет — создаём с дефолтными значениями
    if settings is None:
        # Логируем создание новых настроек
        logger.info("Создаём дефолтные настройки кросс-групповой детекции")

        # Создаём объект с дефолтными значениями
        settings = CrossGroupScammerSettings(id=1)

        # Добавляем в сессию
        session.add(settings)
        # Сохраняем в БД
        await session.commit()
        # Обновляем объект из БД
        await session.refresh(settings)

        # Логируем успешное создание
        logger.info("Настройки кросс-групповой детекции созданы")

    return settings


async def update_cross_group_settings(
    session: AsyncSession,
    **kwargs
) -> CrossGroupScammerSettings:
    """
    Обновляет настройки кросс-групповой детекции.

    Принимает любые поля модели как keyword arguments.
    Обновляет только переданные поля.

    Args:
        session: Асинхронная сессия SQLAlchemy
        **kwargs: Поля для обновления (enabled, join_interval_seconds, etc.)

    Returns:
        CrossGroupScammerSettings: Обновлённый объект настроек

    Example:
        await update_cross_group_settings(
            session,
            enabled=True,
            join_interval_seconds=43200
        )
    """
    # Получаем текущие настройки
    settings = await get_cross_group_settings(session)

    # Логируем что будем обновлять
    logger.info(f"Обновляем настройки кросс-групповой детекции: {kwargs}")

    # Обновляем только переданные поля
    for key, value in kwargs.items():
        # Проверяем что атрибут существует в модели
        if hasattr(settings, key):
            # Устанавливаем новое значение
            setattr(settings, key, value)
        else:
            # Логируем предупреждение о неизвестном поле
            logger.warning(f"Неизвестное поле настроек: {key}")

    # Сохраняем изменения в БД
    await session.commit()
    # Обновляем объект из БД
    await session.refresh(settings)

    # Логируем успешное обновление
    logger.info("Настройки кросс-групповой детекции обновлены")

    return settings


async def toggle_cross_group_detection(
    session: AsyncSession
) -> bool:
    """
    Переключает статус кросс-групповой детекции.

    Если включено — выключает. Если выключено — включает.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        bool: Новый статус (True = включено)
    """
    # Получаем текущие настройки
    settings = await get_cross_group_settings(session)

    # Инвертируем статус
    new_status = not settings.enabled

    # Логируем изменение
    action = "Включаем" if new_status else "Выключаем"
    logger.info(f"{action} кросс-групповую детекцию")

    # Обновляем статус
    settings.enabled = new_status

    # Сохраняем в БД
    await session.commit()

    return new_status


async def add_excluded_group(
    session: AsyncSession,
    chat_id: int
) -> bool:
    """
    Добавляет группу в список исключений (белый список).

    Группы из белого списка игнорируются при детекции.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы для исключения

    Returns:
        bool: True если группа добавлена, False если уже была в списке
    """
    # Получаем текущие настройки
    settings = await get_cross_group_settings(session)

    # Получаем текущий список исключений
    excluded = settings.excluded_groups or []

    # Проверяем не добавлена ли уже эта группа
    if chat_id in excluded:
        # Логируем что группа уже в списке
        logger.info(f"Группа {chat_id} уже в списке исключений")
        return False

    # Добавляем группу в список
    excluded.append(chat_id)

    # Обновляем настройки (JSONB требует явного присваивания)
    settings.excluded_groups = excluded

    # Сохраняем в БД
    await session.commit()

    # Логируем успешное добавление
    logger.info(f"Группа {chat_id} добавлена в список исключений")

    return True


async def remove_excluded_group(
    session: AsyncSession,
    chat_id: int
) -> bool:
    """
    Удаляет группу из списка исключений.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы для удаления из списка

    Returns:
        bool: True если группа удалена, False если не была в списке
    """
    # Получаем текущие настройки
    settings = await get_cross_group_settings(session)

    # Получаем текущий список исключений
    excluded = settings.excluded_groups or []

    # Проверяем есть ли группа в списке
    if chat_id not in excluded:
        # Логируем что группы нет в списке
        logger.info(f"Группа {chat_id} не найдена в списке исключений")
        return False

    # Удаляем группу из списка
    excluded.remove(chat_id)

    # Обновляем настройки (JSONB требует явного присваивания)
    settings.excluded_groups = excluded

    # Сохраняем в БД
    await session.commit()

    # Логируем успешное удаление
    logger.info(f"Группа {chat_id} удалена из списка исключений")

    return True


async def is_group_excluded(
    session: AsyncSession,
    chat_id: int
) -> bool:
    """
    Проверяет находится ли группа в списке исключений.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы для проверки

    Returns:
        bool: True если группа в списке исключений
    """
    # Получаем текущие настройки
    settings = await get_cross_group_settings(session)

    # Получаем список исключений
    excluded = settings.excluded_groups or []

    # Проверяем наличие группы в списке
    return chat_id in excluded


async def get_action_type_display(
    action_type: CrossGroupActionType
) -> str:
    """
    Возвращает человекочитаемое название действия.

    Args:
        action_type: Тип действия из enum

    Returns:
        str: Название действия на русском
    """
    # Словарь соответствия типов действий и их названий
    action_names = {
        CrossGroupActionType.delete: "Удаление сообщений",
        CrossGroupActionType.mute: "Мут",
        CrossGroupActionType.ban: "Бан",
        CrossGroupActionType.kick: "Кик",
    }

    # Возвращаем название или "Неизвестно" если тип не найден
    return action_names.get(action_type, "Неизвестно")


def format_seconds_to_human(seconds: int) -> str:
    """
    Форматирует секунды в человекочитаемый формат.

    Args:
        seconds: Количество секунд

    Returns:
        str: Форматированная строка (напр. "24 часа", "30 минут")
    """
    # Если секунды равны нулю
    if seconds == 0:
        return "0 секунд"

    # Количество секунд в минуте, часе, дне
    minute = 60
    hour = minute * 60
    day = hour * 24

    # Определяем наибольшую единицу времени
    if seconds >= day:
        # Конвертируем в дни
        value = seconds // day
        # Выбираем правильное склонение
        if value == 1:
            return "1 день"
        elif 2 <= value <= 4:
            return f"{value} дня"
        else:
            return f"{value} дней"
    elif seconds >= hour:
        # Конвертируем в часы
        value = seconds // hour
        # Выбираем правильное склонение
        if value == 1:
            return "1 час"
        elif 2 <= value <= 4:
            return f"{value} часа"
        else:
            return f"{value} часов"
    elif seconds >= minute:
        # Конвертируем в минуты
        value = seconds // minute
        # Выбираем правильное склонение
        if value == 1:
            return "1 минута"
        elif 2 <= value <= 4:
            return f"{value} минуты"
        else:
            return f"{value} минут"
    else:
        # Оставляем в секундах
        if seconds == 1:
            return "1 секунда"
        elif 2 <= seconds <= 4:
            return f"{seconds} секунды"
        else:
            return f"{seconds} секунд"