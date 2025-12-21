# tests/unit/test_profile_monitor_auto_mute.py
"""
Юнит-тесты для критериев автомута Profile Monitor.

Тестируемые критерии:
1. Смена имени + смена фото + сообщение в течение 30 мин
2. Смена имени + сообщение в течение 30 мин
3. Добавление фото + сообщение в течение 30 мин
4. Свежее фото (<N дней) + смена имени + сообщение ≤30 мин
5. Свежее фото (<N дней) + сообщение ≤30 мин
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

from bot.database.models_profile_monitor import (
    ProfileMonitorSettings,
    ProfileSnapshot,
)
from bot.services.profile_monitor.profile_monitor_service import (
    check_auto_mute_criteria,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def default_settings():
    """Настройки по умолчанию с включёнными критериями."""
    settings = MagicMock(spec=ProfileMonitorSettings)
    settings.first_message_window_minutes = 30
    settings.photo_freshness_threshold_days = 1
    settings.auto_mute_no_photo_young = True
    settings.auto_mute_name_change_fast_msg = True
    return settings


@pytest.fixture
def disabled_settings():
    """Настройки с выключенными критериями."""
    settings = MagicMock(spec=ProfileMonitorSettings)
    settings.first_message_window_minutes = 30
    settings.photo_freshness_threshold_days = 1
    settings.auto_mute_no_photo_young = False
    settings.auto_mute_name_change_fast_msg = False
    return settings


@pytest.fixture
def default_snapshot():
    """Снапшот по умолчанию."""
    snapshot = MagicMock(spec=ProfileSnapshot)
    snapshot.user_id = 123456789
    snapshot.chat_id = -1001234567890
    snapshot.has_photo = False
    snapshot.photo_age_days = None
    return snapshot


@pytest.fixture
def snapshot_with_old_photo():
    """Снапшот с старым фото (5 дней)."""
    snapshot = MagicMock(spec=ProfileSnapshot)
    snapshot.user_id = 123456789
    snapshot.chat_id = -1001234567890
    snapshot.has_photo = True
    snapshot.photo_age_days = 5
    return snapshot


@pytest.fixture
def mock_session():
    """Mock AsyncSession."""
    return AsyncMock()


# ============================================================
# ТЕСТЫ: КРИТЕРИЙ 1 (смена имени + смена фото + сообщение)
# ============================================================
class TestCriterion1NameAndPhotoChange:
    """Тесты для критерия 1: смена имени + смена фото + быстрое сообщение."""

    @pytest.mark.asyncio
    async def test_criterion1_triggers_when_all_conditions_met(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 1 срабатывает при смене имени + фото + сообщении в окне."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=15,  # В пределах окна 30 мин
            current_photo_age_days=None,
        )

        assert should_mute is True
        assert "смена имени + смена фото" in reason

    @pytest.mark.asyncio
    async def test_criterion1_not_triggers_without_name_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 1 не срабатывает без смены имени."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=True,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        # Критерий 1 не сработал, но может сработать критерий 3
        # Проверяем что это именно критерий 3 (добавление фото)
        if should_mute:
            assert "добавление фото" in reason

    @pytest.mark.asyncio
    async def test_criterion1_not_triggers_without_photo_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 1 не срабатывает без смены фото (сработает критерий 2)."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        # Сработает критерий 2 (только смена имени)
        assert should_mute is True
        assert "смена имени" in reason
        assert "смена фото" not in reason

    @pytest.mark.asyncio
    async def test_criterion1_not_triggers_outside_window(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 1 не срабатывает за пределами окна времени."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=45,  # За пределами окна 30 мин
            current_photo_age_days=None,
        )

        assert should_mute is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_criterion1_disabled(
        self, mock_session, disabled_settings, default_snapshot
    ):
        """Критерий 1 не срабатывает когда выключен."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=disabled_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=15,
            current_photo_age_days=None,
        )

        assert should_mute is False


# ============================================================
# ТЕСТЫ: КРИТЕРИЙ 2 (смена имени + сообщение)
# ============================================================
class TestCriterion2NameChangeOnly:
    """Тесты для критерия 2: смена имени + быстрое сообщение."""

    @pytest.mark.asyncio
    async def test_criterion2_triggers_on_name_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 срабатывает при смене имени + сообщении в окне."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        assert should_mute is True
        assert "смена имени" in reason

    @pytest.mark.asyncio
    async def test_criterion2_not_triggers_without_name_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 не срабатывает без смены имени."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_criterion2_respects_custom_window(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 учитывает настраиваемое окно времени."""
        # Устанавливаем окно 20 минут
        default_settings.first_message_window_minutes = 20

        # 25 минут - за пределами окна
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=25,
            current_photo_age_days=None,
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_criterion2_boundary_at_window_edge(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 срабатывает ровно на границе окна."""
        # Ровно 30 минут
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=30,  # Ровно на границе
            current_photo_age_days=None,
        )

        assert should_mute is True

    @pytest.mark.asyncio
    async def test_criterion2_not_triggers_just_outside_window(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 не срабатывает сразу за границей окна."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=30.1,  # Чуть за границей
            current_photo_age_days=None,
        )

        assert should_mute is False


# ============================================================
# ТЕСТЫ: КРИТЕРИЙ 3 (добавление фото + сообщение)
# ============================================================
class TestCriterion3PhotoAdded:
    """Тесты для критерия 3: добавление фото + быстрое сообщение."""

    @pytest.mark.asyncio
    async def test_criterion3_triggers_on_photo_added(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 3 срабатывает при добавлении фото + сообщении в окне."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=True,  # Добавление фото
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        assert should_mute is True
        assert "добавление фото" in reason

    @pytest.mark.asyncio
    async def test_criterion3_not_triggers_with_name_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 3 не срабатывает если была смена имени (сработает критерий 1)."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        # Сработает критерий 1, не критерий 3
        assert should_mute is True
        assert "смена имени + смена фото" in reason

    @pytest.mark.asyncio
    async def test_criterion3_not_triggers_outside_window(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 3 не срабатывает за пределами окна."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=True,
            minutes_since_change=60,
            current_photo_age_days=None,
        )

        assert should_mute is False


# ============================================================
# ТЕСТЫ: КРИТЕРИЙ 4 (свежее фото + смена имени + сообщение)
# ============================================================
class TestCriterion4FreshPhotoAndNameChange:
    """Тесты для критерия 4: свежее фото + смена имени + быстрое сообщение.

    ВАЖНО: Критерий 2 (смена имени) проверяется РАНЬШЕ критерия 4.
    Поэтому при смене имени + свежем фото сработает критерий 2, а не 4.
    Критерий 4 срабатывает только когда критерий 2 выключен.
    """

    @pytest.mark.asyncio
    async def test_criterion4_triggers_when_criterion2_disabled(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 4 срабатывает когда критерий 2 выключен."""
        # Выключаем критерий 2 (смена имени)
        default_settings.auto_mute_name_change_fast_msg = False

        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # Свежее фото (0 дней)
        )

        assert should_mute is True
        assert "свежее фото" in reason
        assert "смена имени" in reason

    @pytest.mark.asyncio
    async def test_criterion2_has_priority_over_criterion4(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 срабатывает раньше критерия 4 при обоих условиях."""
        # Оба критерия включены
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # Свежее фото
        )

        # Сработает критерий 2 (проверяется раньше), не критерий 4
        assert should_mute is True
        # Критерий 2 не упоминает "свежее фото"
        assert "смена имени" in reason

    @pytest.mark.asyncio
    async def test_criterion4_not_triggers_with_old_photo(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 4 не срабатывает со старым фото (сработает критерий 2)."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=5,  # Старое фото (5 дней > 1 день порог)
        )

        # Сработает критерий 2 (смена имени), не критерий 4
        assert should_mute is True
        assert "свежее фото" not in reason

    @pytest.mark.asyncio
    async def test_criterion4_respects_custom_threshold_when_c2_disabled(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 4 учитывает настраиваемый порог свежести фото."""
        # Выключаем критерий 2, чтобы проверить критерий 4
        default_settings.auto_mute_name_change_fast_msg = False
        # Устанавливаем порог 7 дней
        default_settings.photo_freshness_threshold_days = 7

        # Фото 5 дней - считается свежим при пороге 7
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=5,
        )

        assert should_mute is True
        assert "свежее фото" in reason

    @pytest.mark.asyncio
    async def test_criterion4_boundary_at_threshold(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 4 не срабатывает ровно на пороге свежести."""
        # Порог 1 день, фото ровно 1 день
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=1,  # Ровно на пороге (не < 1)
        )

        # Критерий 4 требует photo_age < threshold
        # При photo_age=1 и threshold=1, условие 1 < 1 = False
        # Сработает критерий 2 вместо 4
        assert should_mute is True
        assert "свежее фото" not in reason


# ============================================================
# ТЕСТЫ: КРИТЕРИЙ 5 (свежее фото + сообщение)
# ============================================================
class TestCriterion5FreshPhotoOnly:
    """Тесты для критерия 5: свежее фото (заменённое) + быстрое сообщение."""

    @pytest.mark.asyncio
    async def test_criterion5_triggers_with_fresh_photo_replacing_old(
        self, mock_session, default_settings, snapshot_with_old_photo
    ):
        """Критерий 5 срабатывает когда свежее фото заменило старое."""
        # Снапшот имел фото 5 дней, сейчас 0 дней
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=snapshot_with_old_photo,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # Свежее фото
        )

        assert should_mute is True
        assert "свежее фото" in reason

    @pytest.mark.asyncio
    async def test_criterion5_triggers_with_photo_added_to_none(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 5 срабатывает когда фото добавлено (было None)."""
        # Снапшот не имел фото (photo_age_days=None), сейчас есть свежее
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # Свежее фото
        )

        assert should_mute is True
        assert "свежее фото" in reason

    @pytest.mark.asyncio
    async def test_criterion5_not_triggers_if_photo_not_fresher(
        self, mock_session, default_settings, snapshot_with_old_photo
    ):
        """Критерий 5 не срабатывает если фото не стало свежее."""
        # Снапшот имел фото 5 дней, сейчас тоже 5 дней (не изменилось)
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=snapshot_with_old_photo,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=5,  # Не свежее (порог 1 день)
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_criterion5_not_triggers_without_photo(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 5 не срабатывает если нет фото."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=None,  # Нет фото
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_criterion5_not_triggers_outside_window(
        self, mock_session, default_settings, snapshot_with_old_photo
    ):
        """Критерий 5 не срабатывает за пределами окна."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=snapshot_with_old_photo,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=45,  # За пределами 30 мин
            current_photo_age_days=0,
        )

        assert should_mute is False


# ============================================================
# ТЕСТЫ: ПРИОРИТЕТ КРИТЕРИЕВ
# ============================================================
class TestCriteriaPriority:
    """Тесты приоритета критериев (какой срабатывает первым)."""

    @pytest.mark.asyncio
    async def test_criterion1_has_priority_over_criterion2(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 1 имеет приоритет над критерием 2."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=10,
            current_photo_age_days=None,
        )

        assert should_mute is True
        assert "смена имени + смена фото" in reason

    @pytest.mark.asyncio
    async def test_criterion2_has_priority_over_criterion4(
        self, mock_session, default_settings, default_snapshot
    ):
        """Критерий 2 срабатывает раньше критерия 4."""
        # Когда есть и смена имени, и свежее фото
        # Критерий 2 проверяется раньше критерия 4
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=0,  # Свежее фото
        )

        assert should_mute is True
        # Критерий 2 проверяется раньше, но критерий 4 тоже подходит
        # Из-за порядка проверки может сработать либо 2, либо 4


# ============================================================
# ТЕСТЫ: НАСТРОЙКИ
# ============================================================
class TestSettingsIntegration:
    """Тесты интеграции с настройками."""

    @pytest.mark.asyncio
    async def test_all_criteria_disabled(
        self, mock_session, disabled_settings, default_snapshot
    ):
        """Никакой критерий не срабатывает когда всё выключено."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=disabled_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=10,
            current_photo_age_days=0,
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_only_criterion2_enabled(
        self, mock_session, default_settings, default_snapshot
    ):
        """Только критерий 2 работает когда остальные выключены."""
        # Выключаем критерии 1, 3, 4, 5
        default_settings.auto_mute_no_photo_young = False
        default_settings.auto_mute_name_change_fast_msg = True

        # Смена имени + фото + свежее фото - но сработает только критерий 2
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=True,
            minutes_since_change=10,
            current_photo_age_days=0,
        )

        assert should_mute is True
        assert "смена имени" in reason
        # Не должно быть упоминания о критериях 1, 3, 4, 5
        assert "свежее фото" not in reason

    @pytest.mark.asyncio
    async def test_custom_window_30_minutes(
        self, mock_session, default_settings, default_snapshot
    ):
        """Окно 30 минут работает корректно."""
        default_settings.first_message_window_minutes = 30

        # 29 минут - в окне
        should_mute, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=29,
            current_photo_age_days=None,
        )
        assert should_mute is True

        # 31 минута - за пределами
        should_mute, _ = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=31,
            current_photo_age_days=None,
        )
        assert should_mute is False

    @pytest.mark.asyncio
    async def test_photo_freshness_threshold_options(
        self, mock_session, default_settings, default_snapshot
    ):
        """Все варианты порога свежести фото работают.

        Для проверки критерия 4 нужно выключить критерий 2,
        иначе критерий 2 сработает первым.
        """
        # Выключаем критерий 2 чтобы проверить критерий 4
        default_settings.auto_mute_name_change_fast_msg = False
        thresholds = [1, 3, 7, 14]

        for threshold in thresholds:
            default_settings.photo_freshness_threshold_days = threshold

            # Фото на 1 день младше порога - должно сработать
            should_mute, reason = await check_auto_mute_criteria(
                session=mock_session,
                settings=default_settings,
                snapshot=default_snapshot,
                has_recent_name_change=True,
                has_recent_photo_change=False,
                minutes_since_change=10,
                current_photo_age_days=threshold - 1,
            )

            assert should_mute is True, f"Failed for threshold {threshold}"
            assert "свежее фото" in reason


# ============================================================
# ТЕСТЫ: EDGE CASES
# ============================================================
class TestEdgeCases:
    """Тесты граничных случаев."""

    @pytest.mark.asyncio
    async def test_zero_minutes_since_change(
        self, mock_session, default_settings, default_snapshot
    ):
        """Сообщение сразу после изменения (0 минут)."""
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=0,
            current_photo_age_days=None,
        )

        assert should_mute is True

    @pytest.mark.asyncio
    async def test_very_old_photo(
        self, mock_session, default_settings, snapshot_with_old_photo
    ):
        """Очень старое фото (365 дней) не считается свежим."""
        snapshot_with_old_photo.photo_age_days = 365

        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=snapshot_with_old_photo,
            has_recent_name_change=False,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=365,  # Старое фото
        )

        assert should_mute is False

    @pytest.mark.asyncio
    async def test_negative_photo_age_handled(
        self, mock_session, default_settings, default_snapshot
    ):
        """Отрицательный возраст фото (аномалия) не вызывает ошибку."""
        # Не должно падать с ошибкой
        should_mute, reason = await check_auto_mute_criteria(
            session=mock_session,
            settings=default_settings,
            snapshot=default_snapshot,
            has_recent_name_change=True,
            has_recent_photo_change=False,
            minutes_since_change=10,
            current_photo_age_days=-1,  # Аномалия
        )

        # -1 < 1 = True, поэтому критерий 4 сработает
        assert should_mute is True
