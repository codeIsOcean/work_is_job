"""
Unit-тесты для сервиса статистики пользователей.

Этот модуль тестирует функции из bot.services.user_stats_service:
- increment_message_count: инкремент счётчика сообщений
- Подсчёт уникальных дней активности
"""

# Импорт pytest для тестирования
import pytest

# Импорт datetime для работы с временем
from datetime import datetime, timezone, timedelta

# Импорт unittest.mock для создания заглушек
from unittest.mock import MagicMock, AsyncMock, patch

# Импорт тестируемых функций
from bot.services.user_stats_service import (
    increment_message_count,
    _utcnow_naive,
    _get_date_only,
)

# Импорт модели статистики
from bot.database.models_user_stats import UserStatistics


# ============================================================
# ТЕСТЫ ДЛЯ ВСПОМОГАТЕЛЬНЫХ ФУНКЦИЙ
# ============================================================

class TestHelperFunctions:
    """Тесты для вспомогательных функций модуля."""

    # Тест: _utcnow_naive возвращает datetime без timezone
    def test_utcnow_naive_returns_naive_datetime(self):
        # Вызываем функцию
        result = _utcnow_naive()

        # Проверяем что результат - datetime
        assert isinstance(result, datetime)

        # Проверяем что timezone отсутствует (naive)
        assert result.tzinfo is None

    # Тест: _get_date_only возвращает дату без времени
    def test_get_date_only_removes_time(self):
        # Создаём datetime с временем
        dt = datetime(2025, 12, 19, 14, 30, 45, 123456)

        # Вызываем функцию
        result = _get_date_only(dt)

        # Проверяем что время обнулено
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0

        # Проверяем что дата сохранилась
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 19


# ============================================================
# ТЕСТЫ ДЛЯ increment_message_count
# ============================================================

class TestIncrementMessageCount:
    """Тесты для функции increment_message_count."""

    # Тест: создание новой записи если её нет
    @pytest.mark.asyncio
    async def test_creates_new_record_if_not_exists(self):
        # Создаём mock сессии
        mock_session = AsyncMock()

        # Mock execute возвращает результат без записей
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Вызываем функцию
        await increment_message_count(
            session=mock_session,
            chat_id=-1001234567890,
            user_id=123456789
        )

        # Проверяем что session.add был вызван (создание записи)
        assert mock_session.add.called

        # Проверяем что flush был вызван
        assert mock_session.flush.called

    # Тест: обновление существующей записи
    @pytest.mark.asyncio
    async def test_updates_existing_record(self):
        # Создаём mock сессии
        mock_session = AsyncMock()

        # Создаём mock существующей записи
        existing_stats = MagicMock(spec=UserStatistics)
        existing_stats.message_count = 5
        existing_stats.active_days = 2
        existing_stats.last_active_date = datetime(2025, 12, 18)

        # Mock execute возвращает существующую запись
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_stats
        mock_session.execute.return_value = mock_result

        # Вызываем функцию
        await increment_message_count(
            session=mock_session,
            chat_id=-1001234567890,
            user_id=123456789
        )

        # Проверяем что message_count увеличился на 1
        assert existing_stats.message_count == 6

        # Проверяем что flush был вызван
        assert mock_session.flush.called

    # Тест: увеличение active_days при новом дне
    @pytest.mark.asyncio
    async def test_increments_active_days_on_new_day(self):
        # Создаём mock сессии
        mock_session = AsyncMock()

        # Создаём mock записи с датой вчера
        yesterday = datetime(2025, 12, 18, 0, 0, 0)
        existing_stats = MagicMock(spec=UserStatistics)
        existing_stats.message_count = 5
        existing_stats.active_days = 2
        existing_stats.last_active_date = yesterday

        # Mock execute возвращает существующую запись
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_stats
        mock_session.execute.return_value = mock_result

        # Патчим _utcnow_naive чтобы вернуть "сегодня"
        with patch('bot.services.user_stats_service._utcnow_naive') as mock_now:
            # "Сегодня" = 19 декабря
            mock_now.return_value = datetime(2025, 12, 19, 14, 30, 0)

            # Вызываем функцию
            await increment_message_count(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789
            )

        # Проверяем что active_days увеличился
        assert existing_stats.active_days == 3

    # Тест: НЕ увеличение active_days в тот же день
    @pytest.mark.asyncio
    async def test_does_not_increment_active_days_same_day(self):
        # Создаём mock сессии
        mock_session = AsyncMock()

        # Создаём mock записи с датой сегодня
        today = datetime(2025, 12, 19, 0, 0, 0)
        existing_stats = MagicMock(spec=UserStatistics)
        existing_stats.message_count = 5
        existing_stats.active_days = 2
        existing_stats.last_active_date = today

        # Mock execute возвращает существующую запись
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_stats
        mock_session.execute.return_value = mock_result

        # Патчим _utcnow_naive чтобы вернуть "сегодня" позже
        with patch('bot.services.user_stats_service._utcnow_naive') as mock_now:
            # Тот же день, но позже
            mock_now.return_value = datetime(2025, 12, 19, 18, 0, 0)

            # Вызываем функцию
            await increment_message_count(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789
            )

        # Проверяем что active_days НЕ увеличился
        assert existing_stats.active_days == 2

    # Тест: обработка ошибок без падения
    @pytest.mark.asyncio
    async def test_handles_errors_gracefully(self):
        # Создаём mock сессии который бросает ошибку
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")

        # Вызываем функцию - не должна падать
        await increment_message_count(
            session=mock_session,
            chat_id=-1001234567890,
            user_id=123456789
        )

        # Если дошли сюда - тест прошёл (функция не упала)


# ============================================================
# ТЕСТЫ ДЛЯ МОДЕЛИ UserStatistics
# ============================================================

class TestUserStatisticsModel:
    """Тесты для модели UserStatistics."""

    # Тест: создание модели с указанными значениями
    def test_model_creation(self):
        # Создаём экземпляр модели с указанными значениями
        # Примечание: дефолтные значения (default=0) применяются при INSERT в БД,
        # а не при создании объекта Python
        stats = UserStatistics(
            chat_id=-1001234567890,
            user_id=123456789,
            message_count=0,
            active_days=0
        )

        # Проверяем установленные значения
        assert stats.chat_id == -1001234567890
        assert stats.user_id == 123456789
        assert stats.message_count == 0
        assert stats.active_days == 0
        assert stats.last_message_at is None
        assert stats.last_active_date is None

    # Тест: строковое представление модели
    def test_model_repr(self):
        # Создаём экземпляр модели
        stats = UserStatistics(
            chat_id=-1001234567890,
            user_id=123456789,
            message_count=10,
            active_days=3
        )

        # Получаем строковое представление
        result = repr(stats)

        # Проверяем что содержит нужные данные
        assert "chat_id=-1001234567890" in result
        assert "user_id=123456789" in result
        assert "messages=10" in result
        assert "active_days=3" in result
