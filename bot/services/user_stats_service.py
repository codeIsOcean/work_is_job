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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        # Шаг 1: Ищем существующую запись
        # ─────────────────────────────────────────────────────────
        query = select(UserStatistics).where(
            UserStatistics.chat_id == chat_id,
            UserStatistics.user_id == user_id
        )

        # Выполняем запрос
        result = await session.execute(query)
        stats = result.scalar_one_or_none()

        # ─────────────────────────────────────────────────────────
        # Шаг 2: Создаём или обновляем запись
        # ─────────────────────────────────────────────────────────
        if stats is None:
            # Записи нет - создаём новую
            stats = UserStatistics(
                chat_id=chat_id,
                user_id=user_id,
                message_count=1,               # Первое сообщение
                last_message_at=now,           # Время сообщения
                active_days=1,                 # Первый день
                last_active_date=today,        # Сегодня
                created_at=now,
                updated_at=now
            )

            # Добавляем в сессию
            session.add(stats)

            # Логируем создание новой записи
            logger.debug(
                f"[USER_STATS] Создана запись: chat={chat_id}, user={user_id}"
            )

        else:
            # Запись есть - обновляем счётчики
            # Увеличиваем счётчик сообщений
            stats.message_count += 1

            # Обновляем время последнего сообщения
            stats.last_message_at = now

            # Проверяем нужно ли увеличить счётчик дней
            # Если последний активный день != сегодня → новый день активности
            if stats.last_active_date is None:
                # Первый раз фиксируем дату
                stats.active_days = 1
                stats.last_active_date = today

            elif _get_date_only(stats.last_active_date) != today:
                # Новый день активности
                stats.active_days += 1
                stats.last_active_date = today

            # updated_at обновится автоматически (onupdate в модели)

            # Логируем обновление
            logger.debug(
                f"[USER_STATS] Обновлена запись: chat={chat_id}, user={user_id}, "
                f"messages={stats.message_count}, days={stats.active_days}"
            )

        # ─────────────────────────────────────────────────────────
        # Шаг 3: Сохраняем в БД
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
