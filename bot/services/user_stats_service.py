# ============================================================
# СЕРВИС СТАТИСТИКИ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
# Этот сервис управляет статистикой сообщений пользователей.
# Вызывается из group_message_coordinator для инкремента счётчиков.
#
# ВАЖНО: Полностью изолирован от profile_monitor!
# Работает только с таблицей user_statistics.
# ============================================================

# Импортируем logging для логирования
import logging

# Импортируем datetime для работы с датами
from datetime import datetime, timezone

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select, case, func
from sqlalchemy.ext.asyncio import AsyncSession
# Импортируем PostgreSQL-specific insert для ON CONFLICT DO UPDATE (upsert)
# Это атомарная операция которая решает race condition при параллельных INSERT
from sqlalchemy.dialects.postgresql import insert

# Импортируем модель статистики
from bot.database.models_user_stats import UserStatistics


# ============================================================
# НАСТРОЙКА ЛОГГЕРА
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _utcnow_naive() -> datetime:
    """
    Возвращает текущее UTC время без timezone info.
    Используется для совместимости с БД (naive datetime).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_date_only(dt: datetime) -> datetime:
    """
    Возвращает дату без времени (для подсчёта уникальных дней).

    Args:
        dt: Datetime объект

    Returns:
        Datetime с временем 00:00:00
    """
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ ИНКРЕМЕНТА
# ============================================================


async def increment_message_count(
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> None:
    """
    Увеличивает счётчик сообщений пользователя в группе.

    Также обновляет:
    - last_message_at: время последнего сообщения
    - active_days: количество уникальных дней с сообщениями

    Если записи нет - создаёт новую.

    ВАЖНО: Эта функция безопасна для вызова из coordinator.
    Все ошибки ловятся и логируются, не прерывая основной поток.

    ИСПРАВЛЕНИЕ: Используем INSERT ... ON CONFLICT DO UPDATE (upsert)
    вместо SELECT + INSERT для избежания race condition при параллельных
    сообщениях (например, когда пользователь отправляет альбом из 4 фото).

    Args:
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя
    """
    try:
        # Текущее время UTC (naive для совместимости с БД)
        now = _utcnow_naive()

        # Дата без времени для подсчёта уникальных дней
        today = _get_date_only(now)

        # ─────────────────────────────────────────────────────────
        # UPSERT: INSERT ... ON CONFLICT DO UPDATE
        # ─────────────────────────────────────────────────────────
        # Это атомарная операция которая:
        # 1. Пытается INSERT новую запись
        # 2. При конфликте (запись уже есть) - делает UPDATE
        # Решает race condition при параллельных сообщениях от одного юзера

        # Формируем INSERT statement с PostgreSQL-specific синтаксисом
        stmt = insert(UserStatistics).values(
            # Значения для новой записи (если её нет)
            chat_id=chat_id,
            user_id=user_id,
            message_count=1,           # Первое сообщение
            last_message_at=now,       # Время сообщения
            active_days=1,             # Первый день активности
            last_active_date=today,    # Сегодня
            created_at=now,
            updated_at=now
        )

        # Определяем что делать при конфликте (запись уже существует)
        # Constraint 'uq_user_statistics_chat_user' = уникальность chat_id + user_id
        stmt = stmt.on_conflict_do_update(
            # Имя constraint из модели UserStatistics
            constraint='uq_user_statistics_chat_user',
            # Что обновлять при конфликте:
            set_={
                # message_count += 1 (атомарный инкремент)
                'message_count': UserStatistics.message_count + 1,

                # Обновляем время последнего сообщения
                'last_message_at': now,

                # active_days: увеличиваем только если это новый день
                # CASE WHEN last_active_date IS NULL OR DATE(last_active_date) != DATE(today)
                #      THEN active_days + 1
                #      ELSE active_days
                # END
                'active_days': case(
                    # Условие: last_active_date NULL или другой день
                    (
                        # func.coalesce заменяет NULL на '1970-01-01' для сравнения
                        # func.date() извлекает только дату (без времени)
                        func.coalesce(
                            func.date(UserStatistics.last_active_date),
                            func.date('1970-01-01')
                        ) != func.date(today),
                        # Если условие True - увеличиваем счётчик дней
                        UserStatistics.active_days + 1
                    ),
                    # Иначе - оставляем как есть (тот же день)
                    else_=UserStatistics.active_days
                ),

                # Обновляем дату последней активности
                'last_active_date': today,

                # Обновляем время модификации
                'updated_at': now
            }
        )

        # Выполняем upsert запрос
        await session.execute(stmt)

        # Логируем успешную операцию
        logger.debug(
            f"[USER_STATS] Upsert выполнен: chat={chat_id}, user={user_id}"
        )

        # ─────────────────────────────────────────────────────────
        # Сохраняем в БД
        # ─────────────────────────────────────────────────────────
        # Коммит будет выполнен middleware после завершения хендлера
        # Здесь только flush для синхронизации
        await session.flush()

    except Exception as e:
        # Ловим все ошибки чтобы не прерывать основной поток
        # Статистика не критична - логируем и продолжаем
        logger.warning(
            f"[USER_STATS] Ошибка инкремента: chat={chat_id}, user={user_id}, error={e}"
        )
