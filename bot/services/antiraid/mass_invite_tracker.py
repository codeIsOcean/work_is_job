# bot/services/antiraid/mass_invite_tracker.py
"""
Трекер массовых инвайтов для модуля Anti-Raid.

Отслеживает количество инвайтов от одного пользователя за временное окно.
Если один юзер приглашает слишком много людей за короткое время — это подозрительно.

Использует Redis для хранения timestamp'ов инвайтов.
Ключи: antiraid:mass_invite:{chat_id}:{inviter_id} → Sorted Set с timestamps

Пороги берутся из AntiRaidSettings в БД (без хардкода!):
- mass_invite_enabled: включён ли модуль
- mass_invite_window: временное окно (секунды)
- mass_invite_threshold: макс. инвайтов за окно
- mass_invite_action: warn/kick/ban
"""

# Импортируем логгер для записи событий
import logging
# Импортируем time для получения текущего timestamp
import time
# Импортируем типы для аннотаций
from typing import Optional, NamedTuple

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем Redis клиент
from redis.asyncio import Redis

# Импортируем функцию получения настроек
from bot.services.antiraid.settings_service import get_antiraid_settings


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ НА МАССОВЫЕ ИНВАЙТЫ
# ============================================================
class MassInviteCheckResult(NamedTuple):
    """
    Результат проверки на массовые инвайты.

    Attributes:
        is_abuse: True если обнаружено злоупотребление
        invite_count: Количество инвайтов за окно
        threshold: Порог срабатывания
        window_seconds: Временное окно (секунды)
    """
    is_abuse: bool
    invite_count: int
    threshold: int
    window_seconds: int


# ============================================================
# КЛАСС ТРЕКЕРА МАССОВЫХ ИНВАЙТОВ
# ============================================================
class MassInviteTracker:
    """
    Трекер массовых инвайтов на основе Redis.

    Для каждого инвайтера в каждой группе хранит Sorted Set с timestamp'ами.
    При каждом инвайте:
    1. Удаляем старые записи (за пределами окна)
    2. Добавляем новый timestamp
    3. Считаем количество записей
    4. Если >= threshold — возвращаем is_abuse=True
    """

    # Префикс для ключей Redis
    KEY_PREFIX = "antiraid:mass_invite"

    def __init__(
        self,
        redis: Redis,
        window_seconds: int = 300,
        threshold: int = 5
    ):
        """
        Инициализация трекера.

        Args:
            redis: Подключение к Redis
            window_seconds: Временное окно для подсчёта (дефолт 300 = 5 минут)
            threshold: Порог срабатывания (дефолт 5 инвайтов)
        """
        self._redis = redis
        self._window_seconds = window_seconds
        self._threshold = threshold

    def _get_key(self, chat_id: int, inviter_id: int) -> str:
        """
        Формирует ключ Redis для конкретного инвайтера в группе.

        Args:
            chat_id: ID чата
            inviter_id: ID пользователя-инвайтера

        Returns:
            Ключ вида antiraid:mass_invite:{chat_id}:{inviter_id}
        """
        return f"{self.KEY_PREFIX}:{chat_id}:{inviter_id}"

    async def record_and_check(
        self,
        chat_id: int,
        inviter_id: int,
        invited_user_id: int
    ) -> MassInviteCheckResult:
        """
        Записывает инвайт и проверяет на злоупотребление.

        Атомарно выполняет:
        1. Удаление старых записей (за пределами окна)
        2. Добавление нового timestamp с invited_user_id как уникальным ID
        3. Подсчёт записей в окне
        4. Установка TTL для автоочистки

        Args:
            chat_id: ID чата
            inviter_id: ID пользователя-инвайтера
            invited_user_id: ID приглашённого пользователя

        Returns:
            MassInviteCheckResult с результатом проверки
        """
        # Текущий timestamp
        now = time.time()
        # Граница окна (удаляем старее этого)
        window_start = now - self._window_seconds

        # Ключ для этого инвайтера в этой группе
        key = self._get_key(chat_id, inviter_id)

        # Используем pipeline для атомарности
        pipe = self._redis.pipeline()

        # 1. Удаляем старые записи (score < window_start)
        pipe.zremrangebyscore(key, '-inf', window_start)

        # 2. Добавляем новый timestamp
        # Используем invited_user_id как member, timestamp как score
        # Это гарантирует уникальность (один инвайт на юзера)
        pipe.zadd(key, {str(invited_user_id): now})

        # 3. Считаем количество записей в окне
        pipe.zcount(key, window_start, '+inf')

        # 4. Устанавливаем TTL для автоочистки (окно + буфер)
        pipe.expire(key, self._window_seconds + 60)

        # Выполняем pipeline
        results = await pipe.execute()

        # Извлекаем количество инвайтов
        invite_count = results[2]  # Результат zcount

        # Проверяем превышение порога
        is_abuse = invite_count >= self._threshold

        if is_abuse:
            logger.warning(
                f"[ANTIRAID] Mass invite abuse detected! "
                f"chat_id={chat_id}, inviter_id={inviter_id}, "
                f"invites={invite_count}/{self._threshold} in {self._window_seconds}s"
            )

        return MassInviteCheckResult(
            is_abuse=is_abuse,
            invite_count=invite_count,
            threshold=self._threshold,
            window_seconds=self._window_seconds
        )

    async def get_invite_count(
        self,
        chat_id: int,
        inviter_id: int
    ) -> int:
        """
        Получает текущее количество инвайтов в окне.

        Args:
            chat_id: ID чата
            inviter_id: ID пользователя-инвайтера

        Returns:
            Количество инвайтов за окно
        """
        now = time.time()
        window_start = now - self._window_seconds
        key = self._get_key(chat_id, inviter_id)

        count = await self._redis.zcount(key, window_start, '+inf')
        return count

    async def clear_inviter(
        self,
        chat_id: int,
        inviter_id: int
    ) -> None:
        """
        Очищает счётчик инвайтов для инвайтера.

        Используется при ручном сбросе или после применения действия.

        Args:
            chat_id: ID чата
            inviter_id: ID пользователя-инвайтера
        """
        key = self._get_key(chat_id, inviter_id)
        await self._redis.delete(key)
        logger.debug(
            f"[ANTIRAID] Cleared invite counter: "
            f"chat_id={chat_id}, inviter_id={inviter_id}"
        )


# ============================================================
# ФАБРИЧНАЯ ФУНКЦИЯ
# ============================================================
def create_mass_invite_tracker(
    redis: Redis,
    window_seconds: int = 300,
    threshold: int = 5
) -> MassInviteTracker:
    """
    Создаёт экземпляр MassInviteTracker.

    Args:
        redis: Подключение к Redis
        window_seconds: Временное окно (секунды)
        threshold: Порог срабатывания

    Returns:
        Настроенный MassInviteTracker
    """
    return MassInviteTracker(
        redis=redis,
        window_seconds=window_seconds,
        threshold=threshold
    )


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ ПРОВЕРКИ (С НАСТРОЙКАМИ ИЗ БД)
# ============================================================
async def check_mass_invite(
    redis: Redis,
    session: AsyncSession,
    chat_id: int,
    inviter_id: int,
    invited_user_id: int
) -> Optional[MassInviteCheckResult]:
    """
    Записывает инвайт и проверяет на злоупотребление с настройками из БД.

    Это главная функция для вызова из хендлеров.
    Автоматически получает настройки из БД и создаёт трекер.

    Args:
        redis: Подключение к Redis
        session: Сессия SQLAlchemy
        chat_id: ID чата
        inviter_id: ID пользователя-инвайтера
        invited_user_id: ID приглашённого пользователя

    Returns:
        MassInviteCheckResult если модуль включён, иначе None
    """
    # ─────────────────────────────────────────────────────────
    # Получаем настройки группы
    # ─────────────────────────────────────────────────────────
    settings = await get_antiraid_settings(session, chat_id)

    # Если настроек нет или модуль выключен — пропускаем
    if settings is None or not settings.mass_invite_enabled:
        return None

    # ─────────────────────────────────────────────────────────
    # Создаём трекер с настройками из БД
    # ─────────────────────────────────────────────────────────
    tracker = create_mass_invite_tracker(
        redis=redis,
        window_seconds=settings.mass_invite_window,
        threshold=settings.mass_invite_threshold
    )

    # ─────────────────────────────────────────────────────────
    # Записываем и проверяем
    # ─────────────────────────────────────────────────────────
    result = await tracker.record_and_check(
        chat_id=chat_id,
        inviter_id=inviter_id,
        invited_user_id=invited_user_id
    )

    return result
