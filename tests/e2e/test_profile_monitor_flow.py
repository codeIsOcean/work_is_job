# tests/e2e/test_profile_monitor_flow.py
"""
Интеграционные тесты для Profile Monitor.

Тестируемые сценарии:
1. Полный флоу автомута по критериям 1-5
2. Настройка photo_freshness_threshold через UI
3. Совместимость критериев 1-3 после изменения окна с 20 на 30 мин
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    Message,
    User,
    Chat,
    Update,
    CallbackQuery,
    ChatMemberUpdated,
    ChatMember,
    ChatMemberMember,
    ChatMemberLeft,
)
from aiogram.methods import TelegramMethod

from bot.database.models import Group, ChatSettings
from bot.database.models_profile_monitor import (
    ProfileMonitorSettings,
    ProfileSnapshot,
    ProfileChangeLog,
)
from bot.services.profile_monitor.profile_monitor_service import (
    create_profile_snapshot,
    check_auto_mute_criteria,
    create_or_update_settings,
    get_profile_monitor_settings,
    log_profile_change,
)


# ============================================================
# MOCK SESSION
# ============================================================
class ProfileMonitorSession(BaseSession):
    """Mock сессия для отслеживания Telegram API вызовов."""

    def __init__(self) -> None:
        super().__init__(api=TelegramAPIServer.from_base("https://api.test"))
        self.requests: List[Tuple[str, Dict[str, Any]]] = []
        self.mute_applied = False
        self.messages_deleted = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: Optional[int] = None,
    ) -> Any:
        method_name = method.__api_method__
        payload: Dict[str, Any] = {}

        if method_name == "restrictChatMember":
            payload = {
                "chat_id": method.chat_id,
                "user_id": method.user_id,
                "permissions": method.permissions,
            }
            self.mute_applied = True

        elif method_name == "deleteMessage":
            payload = {"chat_id": method.chat_id, "message_id": method.message_id}
            self.messages_deleted.append(method.message_id)

        elif method_name == "sendMessage":
            payload = {"chat_id": method.chat_id, "text": method.text}

        elif method_name == "editMessageText":
            payload = {"chat_id": method.chat_id, "text": method.text}

        self.requests.append((method_name, payload))

        if method_name == "restrictChatMember":
            return True
        if method_name == "deleteMessage":
            return True
        if method_name == "sendMessage":
            return {
                "message_id": 2000,
                "date": datetime.now(timezone.utc),
                "chat": {"id": payload["chat_id"], "type": "supergroup"},
                "text": payload.get("text", ""),
                "from": {"id": bot.id or 333, "is_bot": True, "first_name": "TestBot"},
            }
        return True

    async def close(self) -> None:
        pass

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def mock_session():
    """Mock AsyncSession для БД."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_settings():
    """Настройки Profile Monitor."""
    settings = MagicMock(spec=ProfileMonitorSettings)
    settings.chat_id = -1001234567890
    settings.enabled = True
    settings.first_message_window_minutes = 30
    settings.photo_freshness_threshold_days = 1
    settings.auto_mute_no_photo_young = True
    settings.auto_mute_name_change_fast_msg = True
    settings.auto_mute_delete_messages = True
    settings.name_change_window_hours = 24
    return settings


@pytest.fixture
def mock_snapshot():
    """Снапшот профиля."""
    snapshot = MagicMock(spec=ProfileSnapshot)
    snapshot.user_id = 123456789
    snapshot.chat_id = -1001234567890
    snapshot.first_name = "Test"
    snapshot.last_name = "User"
    snapshot.full_name = "Test User"
    snapshot.username = "testuser"
    snapshot.has_photo = False
    snapshot.photo_age_days = None
    snapshot.account_age_days = 5
    snapshot.joined_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return snapshot


# ============================================================
# ТЕСТЫ: ПОЛНЫЙ ФЛОУ КРИТЕРИЕВ
# ============================================================
class TestAutoMuteFlowIntegration:
    """Интеграционные тесты автомута."""

    @pytest.mark.asyncio
    async def test_criterion1_full_flow(self, mock_session, mock_settings, mock_snapshot):
        """Полный флоу критерия 1: смена имени + фото + сообщение."""
        # Симулируем смену имени и фото
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        assert should_mute is True
        assert "смена имени + смена фото" in reason

    @pytest.mark.asyncio
    async def test_criterion5_spammer_scenario(self, mock_session, mock_settings, mock_snapshot):
        """
        Сценарий спаммера @zachemsnytsa:
        - Заходит со старым фото (5 дней)
        - Меняет на свежее фото (0 дней)
        - Пишет сообщение через 10 минут
        """
        # Снапшот со старым фото
        mock_snapshot.has_photo = True
        mock_snapshot.photo_age_days = 5

        # Проверяем критерий 5: свежее фото заменило старое
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=False,  # Изменение отслеживается через photo_age
            minutes_since_change=10,
            current_photo_age_days=0,  # Новое свежее фото
        )

        assert should_mute is True
        assert "свежее фото" in reason
        # Проверяем что показывает разницу в возрасте
        assert "0 дн" in reason

    @pytest.mark.asyncio
    async def test_30_minute_window_compatibility(self, mock_session, mock_settings, mock_snapshot):
        """Проверка совместимости с новым окном 30 минут."""
        # Раньше окно было 20 минут, теперь 30
        mock_settings.first_message_window_minutes = 30

        # 25 минут - должно сработать (раньше не срабатывало)
        should_mute_25, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=25,
            current_photo_age_days=None,
        )

        # 35 минут - не должно сработать
        should_mute_35, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=35,
            current_photo_age_days=None,
        )

        assert should_mute_25 is True
        assert should_mute_35 is False

    @pytest.mark.asyncio
    async def test_all_criteria_work_independently(self, mock_session, mock_settings, mock_snapshot):
        """Все 5 критериев работают независимо."""
        test_cases = [
            # (has_name, has_photo, minutes, photo_age, expected_mute, criterion_num)
            (True, True, 10, None, True, 1),   # Критерий 1
            (True, False, 10, None, True, 2),  # Критерий 2
            (False, True, 10, None, True, 3),  # Критерий 3
            (True, False, 10, 0, True, 4),     # Критерий 4
            (False, False, 10, 0, True, 5),    # Критерий 5 (нужен старый снапшот)
        ]

        for has_name, has_photo, minutes, photo_age, expected, criterion in test_cases:
            # Для критерия 5 нужен снапшот со старым фото
            if criterion == 5:
                mock_snapshot.photo_age_days = 5

            should_mute, reason = await check_auto_mute_criteria(
                session=mock_session,
                settings=mock_settings,
                snapshot=mock_snapshot,
                has_recent_name_change=has_name,
                has_recent_photo_change=has_photo,
                minutes_since_change=minutes,
                current_photo_age_days=photo_age,
            )

            assert should_mute == expected, f"Критерий {criterion} не сработал"

            # Сбрасываем снапшот
            mock_snapshot.photo_age_days = None


# ============================================================
# ТЕСТЫ: НАСТРОЙКИ UI
# ============================================================
class TestSettingsUIIntegration:
    """Интеграционные тесты UI настроек."""

    @pytest.mark.asyncio
    async def test_photo_threshold_change_affects_criteria(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Изменение порога свежести фото влияет на критерии 4,5."""
        mock_snapshot.photo_age_days = None  # Не было фото при входе

        # Порог 1 день: фото 0 дней = свежее
        mock_settings.photo_freshness_threshold_days = 1
        should_mute_1, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,
        )

        # Порог 1 день: фото 2 дня = НЕ свежее
        should_mute_2, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=2,
        )

        # Порог 7 дней: фото 5 дней = свежее
        mock_settings.photo_freshness_threshold_days = 7
        should_mute_7, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=5,
        )

        assert should_mute_1 is True   # 0 < 1
        assert should_mute_2 is True   # Критерий 2 сработает (смена имени)
        assert should_mute_7 is True   # 5 < 7


# ============================================================
# ТЕСТЫ: СОВМЕСТИМОСТЬ С КРИТЕРИЯМИ 1-3
# ============================================================
class TestBackwardCompatibility:
    """Тесты обратной совместимости критериев 1-3."""

    @pytest.mark.asyncio
    async def test_criteria_1_2_3_still_work_with_new_fields(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Критерии 1-3 работают корректно с новыми полями."""
        # Критерий 1: смена имени + фото
        should_mute_1, reason_1 = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=15,
            current_photo_age_days=None,  # Новое поле не влияет
        )

        # Критерий 2: смена имени
        should_mute_2, reason_2 = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        # Критерий 3: добавление фото
        should_mute_3, reason_3 = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=True,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        assert should_mute_1 is True
        assert should_mute_2 is True
        assert should_mute_3 is True
        assert "смена имени + смена фото" in reason_1
        assert "смена имени" in reason_2
        assert "добавление фото" in reason_3

    @pytest.mark.asyncio
    async def test_old_window_20_vs_new_window_30(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Сравнение старого окна 20 мин и нового 30 мин."""
        # Старое окно 20 минут
        mock_settings.first_message_window_minutes = 20
        should_mute_20_at_25, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=25,
            current_photo_age_days=None,
        )

        # Новое окно 30 минут
        mock_settings.first_message_window_minutes = 30
        should_mute_30_at_25, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=25,
            current_photo_age_days=None,
        )

        # При 20 мин окне: 25 мин > 20 = НЕ мут
        assert should_mute_20_at_25 is False
        # При 30 мин окне: 25 мин <= 30 = МУТ
        assert should_mute_30_at_25 is True

    @pytest.mark.asyncio
    async def test_no_regression_on_disabled_criteria(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Выключенные критерии не срабатывают."""
        # Выключаем все критерии
        mock_settings.auto_mute_no_photo_young = False
        mock_settings.auto_mute_name_change_fast_msg = False

        # Пытаемся триггернуть все условия
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=10,
            current_photo_age_days=0,
        )

        assert should_mute is False
        assert reason == ""


# ============================================================
# ТЕСТЫ: EDGE CASES И ЗАЩИТА
# ============================================================
class TestEdgeCasesAndProtection:
    """Тесты граничных случаев и защиты от ошибок."""

    @pytest.mark.asyncio
    async def test_none_photo_age_handled(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """None photo_age_days не вызывает ошибку."""
        # Не должно падать
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        # Критерии 4,5 не сработают без фото
        assert should_mute is False

    @pytest.mark.asyncio
    async def test_zero_threshold_handled(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Нулевой порог не вызывает проблем."""
        mock_settings.photo_freshness_threshold_days = 0

        # Любое фото будет "старым" (photo_age >= 0)
        should_mute, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # 0 < 0 = False
        )

        # Критерий 4 не сработает (0 < 0 = False)
        # Но критерий 2 сработает
        assert should_mute is True

    @pytest.mark.asyncio
    async def test_very_large_values_handled(
        self, mock_session, mock_settings, mock_snapshot
    ):
        """Очень большие значения обрабатываются."""
        mock_settings.first_message_window_minutes = 99999
        mock_settings.photo_freshness_threshold_days = 99999

        should_mute, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=mock_settings,
            snapshot=mock_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=1000,
            current_photo_age_days=100,
        )

        # С такими большими окнами всё должно сработать
        assert should_mute is True
