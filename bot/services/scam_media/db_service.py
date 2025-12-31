# ============================================================
# СЕРВИС РАБОТЫ С БАЗОЙ ДАННЫХ ДЛЯ SCAM MEDIA FILTER
# ============================================================
# Этот файл реализует CRUD операции для:
# - ScamMediaSettings: настройки модуля для группы
# - BannedImageHash: хеши запрещённых изображений
# - ScamMediaViolation: логи срабатываний
# ============================================================

# Импорт для работы с датами
from datetime import datetime, timezone, timedelta
# Импорт для аннотации типов
from typing import Optional, List
# Импорт для логирования
import logging

# Импорт SQLAlchemy для работы с БД
from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт моделей БД
from bot.database.models_scam_media import (
    ScamMediaSettings,
    BannedImageHash,
    ScamMediaViolation,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# СЕРВИС НАСТРОЕК ГРУППЫ
# ============================================================
class SettingsService:
    """
    Сервис для работы с настройками ScamMediaSettings.

    Каждая группа имеет свои независимые настройки.
    Настройки создаются автоматически при первом обращении.
    """

    @staticmethod
    async def get_settings(
        session: AsyncSession,
        chat_id: int
    ) -> Optional[ScamMediaSettings]:
        """
        Получает настройки модуля для группы.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы

        Returns:
            ScamMediaSettings или None если не найдено
        """
        # Выполняем запрос к БД
        result = await session.execute(
            select(ScamMediaSettings).where(ScamMediaSettings.chat_id == chat_id)
        )
        # Возвращаем первую запись или None
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create_settings(
        session: AsyncSession,
        chat_id: int
    ) -> ScamMediaSettings:
        """
        Получает настройки или создаёт дефолтные.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы

        Returns:
            ScamMediaSettings (существующие или новые)
        """
        # Пробуем получить существующие настройки
        settings = await SettingsService.get_settings(session, chat_id)
        # Если не найдено - создаём новые с дефолтными значениями
        if settings is None:
            settings = ScamMediaSettings(chat_id=chat_id)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings

    @staticmethod
    async def update_settings(
        session: AsyncSession,
        chat_id: int,
        **kwargs
    ) -> Optional[ScamMediaSettings]:
        """
        Обновляет настройки модуля для группы.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            **kwargs: Поля для обновления

        Returns:
            Обновлённые ScamMediaSettings или None
        """
        # Выполняем обновление
        await session.execute(
            update(ScamMediaSettings)
            .where(ScamMediaSettings.chat_id == chat_id)
            .values(**kwargs)
        )
        await session.commit()
        # Возвращаем обновлённые настройки
        return await SettingsService.get_settings(session, chat_id)

    @staticmethod
    async def is_enabled(
        session: AsyncSession,
        chat_id: int
    ) -> bool:
        """
        Проверяет включён ли модуль для группы.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы

        Returns:
            True если модуль включён, False иначе
        """
        settings = await SettingsService.get_settings(session, chat_id)
        # Если настроек нет или модуль выключен
        if settings is None:
            return False
        return settings.enabled


# ============================================================
# СЕРВИС ХЕШЕЙ ИЗОБРАЖЕНИЙ (БД)
# ============================================================
class BannedHashService:
    """
    Сервис для работы с BannedImageHash.

    Поддерживает:
    - Добавление/удаление хешей
    - Поиск похожих хешей
    - Глобальный/локальный режимы
    - Статистику срабатываний
    """

    @staticmethod
    async def add_hash(
        session: AsyncSession,
        phash: str,
        dhash: Optional[str],
        added_by_user_id: int,
        added_by_username: Optional[str] = None,
        chat_id: Optional[int] = None,
        is_global: bool = False,
        description: Optional[str] = None,
        logo_region: Optional[str] = None,
    ) -> BannedImageHash:
        """
        Добавляет хеш изображения в базу.

        Args:
            session: Сессия SQLAlchemy
            phash: Perceptual hash (обязательный)
            dhash: Difference hash (опциональный)
            added_by_user_id: ID админа который добавил
            added_by_username: Username админа
            chat_id: ID группы (для локальных хешей)
            is_global: Глобальный режим
            description: Описание изображения
            logo_region: Область лого если это хеш области

        Returns:
            Созданный BannedImageHash
        """
        # Создаём новую запись
        hash_entry = BannedImageHash(
            phash=phash,
            dhash=dhash,
            added_by_user_id=added_by_user_id,
            added_by_username=added_by_username,
            chat_id=chat_id,
            is_global=is_global,
            description=description,
            logo_region=logo_region,
        )
        session.add(hash_entry)
        await session.commit()
        await session.refresh(hash_entry)
        return hash_entry

    @staticmethod
    async def find_by_phash(
        session: AsyncSession,
        phash: str,
        chat_id: Optional[int] = None
    ) -> Optional[BannedImageHash]:
        """
        Ищет существующий хеш по значению pHash.

        Используется для проверки дубликатов перед добавлением.
        Ищет точное совпадение pHash для данной группы.

        Args:
            session: Сессия SQLAlchemy
            phash: Значение pHash для поиска
            chat_id: ID группы (если None — ищет глобальные)

        Returns:
            BannedImageHash если найден, иначе None
        """
        # Строим запрос на поиск по pHash
        query = select(BannedImageHash).where(BannedImageHash.phash == phash)
        # Если указан chat_id — ищем только в этой группе
        if chat_id is not None:
            query = query.where(BannedImageHash.chat_id == chat_id)
        # Выполняем запрос
        result = await session.execute(query)
        # Возвращаем первую найденную запись или None
        return result.scalar_one_or_none()

    @staticmethod
    async def get_hash_by_id(
        session: AsyncSession,
        hash_id: int
    ) -> Optional[BannedImageHash]:
        """
        Получает хеш по ID.

        Args:
            session: Сессия SQLAlchemy
            hash_id: ID записи

        Returns:
            BannedImageHash или None
        """
        result = await session.execute(
            select(BannedImageHash).where(BannedImageHash.id == hash_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_hashes_for_group(
        session: AsyncSession,
        chat_id: int,
        include_global: bool = False
    ) -> List[BannedImageHash]:
        """
        Получает все хеши для проверки в группе.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            include_global: Включать глобальные хеши

        Returns:
            Список BannedImageHash для сравнения
        """
        if include_global:
            # Локальные + глобальные хеши
            query = select(BannedImageHash).where(
                or_(
                    BannedImageHash.chat_id == chat_id,
                    BannedImageHash.is_global == True
                )
            )
        else:
            # Только локальные хеши
            query = select(BannedImageHash).where(
                BannedImageHash.chat_id == chat_id
            )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def delete_hash(
        session: AsyncSession,
        hash_id: int
    ) -> bool:
        """
        Удаляет хеш по ID.

        Args:
            session: Сессия SQLAlchemy
            hash_id: ID записи

        Returns:
            True если удалено, False если не найдено
        """
        result = await session.execute(
            delete(BannedImageHash).where(BannedImageHash.id == hash_id)
        )
        await session.commit()
        return result.rowcount > 0

    @staticmethod
    async def delete_hash_by_phash(
        session: AsyncSession,
        phash: str,
        chat_id: Optional[int] = None
    ) -> int:
        """
        Удаляет хеши по значению pHash.

        Args:
            session: Сессия SQLAlchemy
            phash: Значение pHash
            chat_id: Ограничить удаление группой (опционально)

        Returns:
            Количество удалённых записей
        """
        query = delete(BannedImageHash).where(BannedImageHash.phash == phash)
        if chat_id is not None:
            query = query.where(BannedImageHash.chat_id == chat_id)
        result = await session.execute(query)
        await session.commit()
        return result.rowcount

    @staticmethod
    async def increment_match_count(
        session: AsyncSession,
        hash_id: int
    ) -> None:
        """
        Увеличивает счётчик срабатываний хеша.

        Args:
            session: Сессия SQLAlchemy
            hash_id: ID хеша
        """
        # Обновляем счётчик и время последнего срабатывания
        await session.execute(
            update(BannedImageHash)
            .where(BannedImageHash.id == hash_id)
            .values(
                matches_count=BannedImageHash.matches_count + 1,
                last_match_at=datetime.now(timezone.utc)
            )
        )
        await session.commit()

    @staticmethod
    async def get_inactive_hashes(
        session: AsyncSession,
        days: int = 90
    ) -> List[BannedImageHash]:
        """
        Получает хеши которые не срабатывали N дней.

        Args:
            session: Сессия SQLAlchemy
            days: Количество дней неактивности

        Returns:
            Список неактивных хешей
        """
        # Вычисляем дату отсечки
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        # Ищем хеши которые либо никогда не срабатывали,
        # либо не срабатывали давно
        query = select(BannedImageHash).where(
            or_(
                BannedImageHash.last_match_at.is_(None),
                BannedImageHash.last_match_at < cutoff_date
            )
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_hashes(
        session: AsyncSession,
        chat_id: Optional[int] = None,
        is_global: Optional[bool] = None
    ) -> int:
        """
        Считает количество хешей в базе.

        Args:
            session: Сессия SQLAlchemy
            chat_id: Фильтр по группе
            is_global: Фильтр по режиму

        Returns:
            Количество хешей
        """
        from sqlalchemy import func
        query = select(func.count()).select_from(BannedImageHash)
        if chat_id is not None:
            query = query.where(BannedImageHash.chat_id == chat_id)
        if is_global is not None:
            query = query.where(BannedImageHash.is_global == is_global)
        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_hashes_paginated(
        session: AsyncSession,
        chat_id: int,
        limit: int = 10,
        offset: int = 0
    ) -> List[BannedImageHash]:
        """
        Получает хеши с пагинацией для UI списка.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            limit: Количество записей на странице
            offset: Смещение от начала

        Returns:
            Список BannedImageHash для текущей страницы
        """
        query = (
            select(BannedImageHash)
            .where(BannedImageHash.chat_id == chat_id)
            .order_by(BannedImageHash.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return list(result.scalars().all())


# ============================================================
# СЕРВИС ЛОГОВ НАРУШЕНИЙ
# ============================================================
class ViolationService:
    """
    Сервис для работы с ScamMediaViolation.

    Записывает все срабатывания фильтра для аналитики.
    """

    @staticmethod
    async def log_violation(
        session: AsyncSession,
        hash_id: int,
        chat_id: int,
        user_id: int,
        hamming_distance: int,
        action_taken: str,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        message_id: Optional[int] = None,
    ) -> ScamMediaViolation:
        """
        Записывает срабатывание фильтра.

        Args:
            session: Сессия SQLAlchemy
            hash_id: ID сработавшего хеша
            chat_id: ID группы
            user_id: ID нарушителя
            hamming_distance: Расстояние Хэмминга
            action_taken: Применённое действие
            username: Username нарушителя
            full_name: Полное имя нарушителя
            message_id: ID удалённого сообщения

        Returns:
            Созданный ScamMediaViolation
        """
        violation = ScamMediaViolation(
            hash_id=hash_id,
            chat_id=chat_id,
            user_id=user_id,
            hamming_distance=hamming_distance,
            action_taken=action_taken,
            username=username,
            full_name=full_name,
            message_id=message_id,
        )
        session.add(violation)
        await session.commit()
        await session.refresh(violation)
        return violation

    @staticmethod
    async def get_user_violations(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
        limit: int = 10
    ) -> List[ScamMediaViolation]:
        """
        Получает нарушения пользователя в группе.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            user_id: ID пользователя
            limit: Максимум записей

        Returns:
            Список нарушений
        """
        query = (
            select(ScamMediaViolation)
            .where(
                and_(
                    ScamMediaViolation.chat_id == chat_id,
                    ScamMediaViolation.user_id == user_id
                )
            )
            .order_by(ScamMediaViolation.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_recent_violations(
        session: AsyncSession,
        chat_id: int,
        limit: int = 20
    ) -> List[ScamMediaViolation]:
        """
        Получает последние нарушения в группе.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            limit: Максимум записей

        Returns:
            Список нарушений
        """
        query = (
            select(ScamMediaViolation)
            .where(ScamMediaViolation.chat_id == chat_id)
            .order_by(ScamMediaViolation.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_violations(
        session: AsyncSession,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        since: Optional[datetime] = None
    ) -> int:
        """
        Считает количество нарушений.

        Args:
            session: Сессия SQLAlchemy
            chat_id: Фильтр по группе
            user_id: Фильтр по пользователю
            since: Начиная с даты

        Returns:
            Количество нарушений
        """
        from sqlalchemy import func
        query = select(func.count()).select_from(ScamMediaViolation)
        if chat_id is not None:
            query = query.where(ScamMediaViolation.chat_id == chat_id)
        if user_id is not None:
            query = query.where(ScamMediaViolation.user_id == user_id)
        if since is not None:
            query = query.where(ScamMediaViolation.created_at >= since)
        result = await session.execute(query)
        return result.scalar() or 0
