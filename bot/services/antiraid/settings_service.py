# bot/services/antiraid/settings_service.py
"""
Сервис для работы с настройками модуля Anti-Raid.

Содержит CRUD операции для:
- AntiRaidSettings: настройки модуля для каждой группы (per-group)
- AntiRaidNamePattern: паттерны имён для бана при входе

Все настройки гибкие — админ может менять через UI (без хардкода!)
"""

# Импортируем логгер для записи событий
import logging
# Импортируем типы для аннотаций
from typing import Optional, List

# Импортируем AsyncSession для асинхронной работы с БД
from sqlalchemy.ext.asyncio import AsyncSession
# Импортируем select для построения запросов
from sqlalchemy import select, delete

# Импортируем модели Anti-Raid
from bot.database.models_antiraid import (
    AntiRaidSettings,
    AntiRaidNamePattern,
)


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# CRUD ДЛЯ НАСТРОЕК ГРУППЫ (AntiRaidSettings)
# ============================================================


async def get_antiraid_settings(
    session: AsyncSession,
    chat_id: int
) -> Optional[AntiRaidSettings]:
    """
    Получает настройки Anti-Raid для группы.

    Возвращает None если настройки не существуют.
    Для автоматического создания используйте get_or_create_antiraid_settings().

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы (может быть отрицательным!)

    Returns:
        AntiRaidSettings или None если настроек нет
    """
    # Строим запрос для получения настроек по chat_id
    query = select(AntiRaidSettings).where(
        AntiRaidSettings.chat_id == chat_id
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Получаем первую (и единственную) запись для этой группы
    settings = result.scalar_one_or_none()

    return settings


async def get_or_create_antiraid_settings(
    session: AsyncSession,
    chat_id: int
) -> AntiRaidSettings:
    """
    Получает настройки Anti-Raid для группы, создавая если не существуют.

    Всегда возвращает объект настроек.
    Если настроек нет — создаёт с дефолтными значениями.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы (может быть отрицательным!)

    Returns:
        AntiRaidSettings: Объект настроек модуля
    """
    # Пытаемся получить существующие настройки
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет — создаём с дефолтными значениями
    if settings is None:
        # Логируем создание новых настроек
        logger.info(f"Создаём дефолтные настройки Anti-Raid для chat_id={chat_id}")

        # Создаём объект с дефолтными значениями (указаны в модели через server_default)
        settings = AntiRaidSettings(chat_id=chat_id)

        # Добавляем в сессию
        session.add(settings)
        # Сохраняем в БД
        await session.commit()
        # Обновляем объект из БД (подтянет server_default значения)
        await session.refresh(settings)

        # Логируем успешное создание
        logger.info(f"Настройки Anti-Raid созданы для chat_id={chat_id}")

    return settings


async def update_antiraid_settings(
    session: AsyncSession,
    chat_id: int,
    **kwargs
) -> AntiRaidSettings:
    """
    Обновляет настройки Anti-Raid для группы.

    Принимает любые поля модели как keyword arguments.
    Обновляет только переданные поля.
    Создаёт настройки если не существуют.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы (может быть отрицательным!)
        **kwargs: Поля для обновления
            - join_exit_enabled, join_exit_window, join_exit_threshold, etc.
            - name_pattern_enabled, name_pattern_action, etc.
            - mass_join_enabled, mass_join_window, etc.
            - mass_invite_enabled, mass_invite_window, etc.
            - mass_reaction_enabled, mass_reaction_window, etc.

    Returns:
        AntiRaidSettings: Обновлённый объект настроек

    Example:
        await update_antiraid_settings(
            session,
            chat_id=-1001234567890,
            join_exit_enabled=True,
            join_exit_threshold=5
        )
    """
    # Получаем текущие настройки (создаст если нет)
    settings = await get_or_create_antiraid_settings(session, chat_id)

    # Логируем что будем обновлять
    logger.info(f"Обновляем настройки Anti-Raid для chat_id={chat_id}: {kwargs}")

    # Обновляем только переданные поля
    for key, value in kwargs.items():
        # Проверяем что атрибут существует в модели
        if hasattr(settings, key):
            # Устанавливаем новое значение
            setattr(settings, key, value)
        else:
            # Логируем предупреждение о неизвестном поле
            logger.warning(f"Неизвестное поле настроек Anti-Raid: {key}")

    # Сохраняем изменения в БД
    await session.commit()
    # Обновляем объект из БД
    await session.refresh(settings)

    # Логируем успешное обновление
    logger.info(f"Настройки Anti-Raid обновлены для chat_id={chat_id}")

    return settings


# ============================================================
# CRUD ДЛЯ ПАТТЕРНОВ ИМЁН (AntiRaidNamePattern)
# ============================================================


async def get_name_patterns(
    session: AsyncSession,
    chat_id: int
) -> List[AntiRaidNamePattern]:
    """
    Получает ВСЕ паттерны имён для группы (включая отключённые).

    Используется для UI отображения списка паттернов.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы

    Returns:
        List[AntiRaidNamePattern]: Список всех паттернов группы
    """
    # Строим запрос для получения всех паттернов группы
    # Сортируем по дате создания (новые сверху)
    query = (
        select(AntiRaidNamePattern)
        .where(AntiRaidNamePattern.chat_id == chat_id)
        .order_by(AntiRaidNamePattern.created_at.desc())
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Получаем все записи как список
    patterns = list(result.scalars().all())

    return patterns


async def get_enabled_name_patterns(
    session: AsyncSession,
    chat_id: int
) -> List[AntiRaidNamePattern]:
    """
    Получает только ВКЛЮЧЁННЫЕ паттерны имён для группы.

    Используется при проверке имени юзера при входе.
    Оптимизировано через индекс ix_antiraid_name_patterns_chat_enabled.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы

    Returns:
        List[AntiRaidNamePattern]: Список включённых паттернов группы
    """
    # Строим запрос для получения только включённых паттернов
    # Использует составной индекс (chat_id, is_enabled)
    query = (
        select(AntiRaidNamePattern)
        .where(
            AntiRaidNamePattern.chat_id == chat_id,
            AntiRaidNamePattern.is_enabled == True  # noqa: E712
        )
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Получаем все записи как список
    patterns = list(result.scalars().all())

    return patterns


async def add_name_pattern(
    session: AsyncSession,
    chat_id: int,
    pattern: str,
    pattern_type: str = 'contains',
    created_by: Optional[int] = None
) -> AntiRaidNamePattern:
    """
    Добавляет новый паттерн имени для группы.

    Args:
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID группы
        pattern: Текст паттерна (например "детск", "педо")
        pattern_type: Тип паттерна ('contains', 'regex', 'exact')
        created_by: user_id админа который добавил (опционально)

    Returns:
        AntiRaidNamePattern: Созданный объект паттерна
    """
    # Логируем добавление
    logger.info(
        f"Добавляем паттерн имени для chat_id={chat_id}: "
        f"pattern='{pattern}', type={pattern_type}"
    )

    # Создаём объект паттерна
    new_pattern = AntiRaidNamePattern(
        chat_id=chat_id,
        pattern=pattern,
        pattern_type=pattern_type,
        is_enabled=True,  # По умолчанию включён
        created_by=created_by
    )

    # Добавляем в сессию
    session.add(new_pattern)
    # Сохраняем в БД
    await session.commit()
    # Обновляем объект из БД (получаем id и created_at)
    await session.refresh(new_pattern)

    # Логируем успешное добавление
    logger.info(f"Паттерн имени добавлен: id={new_pattern.id}")

    return new_pattern


async def remove_name_pattern(
    session: AsyncSession,
    pattern_id: int
) -> bool:
    """
    Удаляет паттерн имени по ID.

    Args:
        session: Асинхронная сессия SQLAlchemy
        pattern_id: ID паттерна для удаления

    Returns:
        bool: True если паттерн был удалён, False если не найден
    """
    # Логируем удаление
    logger.info(f"Удаляем паттерн имени: id={pattern_id}")

    # Строим запрос на удаление
    query = delete(AntiRaidNamePattern).where(
        AntiRaidNamePattern.id == pattern_id
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Сохраняем изменения
    await session.commit()

    # Проверяем было ли что-то удалено
    deleted = result.rowcount > 0

    if deleted:
        logger.info(f"Паттерн имени удалён: id={pattern_id}")
    else:
        logger.warning(f"Паттерн имени не найден: id={pattern_id}")

    return deleted


async def toggle_name_pattern(
    session: AsyncSession,
    pattern_id: int
) -> Optional[bool]:
    """
    Переключает статус паттерна (включён/выключен).

    Если включён — выключает. Если выключен — включает.

    Args:
        session: Асинхронная сессия SQLAlchemy
        pattern_id: ID паттерна для переключения

    Returns:
        bool: Новый статус (True = включён) или None если не найден
    """
    # Получаем паттерн по ID
    query = select(AntiRaidNamePattern).where(
        AntiRaidNamePattern.id == pattern_id
    )
    result = await session.execute(query)
    pattern = result.scalar_one_or_none()

    # Если не найден — возвращаем None
    if pattern is None:
        logger.warning(f"Паттерн имени не найден для toggle: id={pattern_id}")
        return None

    # Инвертируем статус
    new_status = not pattern.is_enabled
    pattern.is_enabled = new_status

    # Логируем изменение
    action = "Включаем" if new_status else "Выключаем"
    logger.info(f"{action} паттерн имени: id={pattern_id}, pattern='{pattern.pattern}'")

    # Сохраняем изменения
    await session.commit()

    return new_status


async def get_name_pattern_by_id(
    session: AsyncSession,
    pattern_id: int
) -> Optional[AntiRaidNamePattern]:
    """
    Получает паттерн по ID.

    Args:
        session: Асинхронная сессия SQLAlchemy
        pattern_id: ID паттерна

    Returns:
        AntiRaidNamePattern или None если не найден
    """
    # Строим запрос
    query = select(AntiRaidNamePattern).where(
        AntiRaidNamePattern.id == pattern_id
    )

    # Выполняем запрос
    result = await session.execute(query)
    # Получаем запись
    pattern = result.scalar_one_or_none()

    return pattern
