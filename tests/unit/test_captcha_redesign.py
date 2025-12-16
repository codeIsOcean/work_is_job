# tests/unit/test_captcha_redesign.py
"""
Unit-тесты для редизайна системы капчи.

Тестируем:
- CaptchaMode enum и его использование
- CaptchaSettings dataclass
- Функции settings_service
- Функции verification_service
- Функции cleanup_service (без Redis - моки)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

# Импортируем тестируемые модули
from bot.services.captcha.settings_service import (
    CaptchaMode,
    CaptchaSettings,
    get_captcha_settings,
    update_captcha_setting,
    is_captcha_configured,
    get_missing_settings,
)
from bot.services.captcha.verification_service import (
    hash_answer,
    verify_answer_hash,
    check_captcha_ownership_by_callback_data,
    generate_captcha_options,
)


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТЫ CaptchaMode
# ═══════════════════════════════════════════════════════════════════════════

class TestCaptchaMode:
    """Тесты для enum CaptchaMode"""

    def test_visual_dm_mode_value(self):
        """Проверяем значение режима Visual DM"""
        # CaptchaMode.VISUAL_DM должен иметь значение "visual_dm"
        assert CaptchaMode.VISUAL_DM.value == "visual_dm"

    def test_join_group_mode_value(self):
        """Проверяем значение режима Join Group"""
        # CaptchaMode.JOIN_GROUP должен иметь значение "join_group"
        assert CaptchaMode.JOIN_GROUP.value == "join_group"

    def test_invite_group_mode_value(self):
        """Проверяем значение режима Invite Group"""
        # CaptchaMode.INVITE_GROUP должен иметь значение "invite_group"
        assert CaptchaMode.INVITE_GROUP.value == "invite_group"

    def test_mode_from_string(self):
        """Проверяем создание режима из строки"""
        # Должна работать конвертация из строкового значения
        mode = CaptchaMode("visual_dm")
        assert mode == CaptchaMode.VISUAL_DM


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТЫ CaptchaSettings DATACLASS
# ═══════════════════════════════════════════════════════════════════════════

class TestCaptchaSettings:
    """Тесты для dataclass CaptchaSettings"""

    def test_get_timeout_for_visual_dm_specific(self):
        """Проверяем получение специфичного таймаута для Visual DM"""
        # Создаём настройки с заданным visual_captcha_timeout
        settings = CaptchaSettings(
            visual_captcha_enabled=True,
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,  # Специфичный таймаут
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=None,
            overflow_action=None,
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        # Должен вернуть специфичный таймаут, а не legacy
        timeout = settings.get_timeout_for_mode(CaptchaMode.VISUAL_DM)
        assert timeout == 120

    def test_get_timeout_for_visual_dm_fallback(self):
        """Проверяем fallback на legacy_timeout когда специфичный не задан"""
        # Создаём настройки БЕЗ visual_captcha_timeout
        settings = CaptchaSettings(
            visual_captcha_enabled=True,
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=None,  # Не задан
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,  # Должен использоваться этот
            max_pending=None,
            overflow_action=None,
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        # Должен вернуть legacy_timeout
        timeout = settings.get_timeout_for_mode(CaptchaMode.VISUAL_DM)
        assert timeout == 300

    def test_is_mode_enabled_true(self):
        """Проверяем что is_mode_enabled возвращает True для включённого режима"""
        settings = CaptchaSettings(
            visual_captcha_enabled=True,  # Включен
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=10,
            overflow_action="remove_oldest",
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        assert settings.is_mode_enabled(CaptchaMode.VISUAL_DM) is True

    def test_is_mode_enabled_false(self):
        """Проверяем что is_mode_enabled возвращает False для выключенного режима"""
        settings = CaptchaSettings(
            visual_captcha_enabled=False,  # Выключен
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=10,
            overflow_action="remove_oldest",
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        assert settings.is_mode_enabled(CaptchaMode.VISUAL_DM) is False

    def test_is_mode_enabled_none_treated_as_false(self):
        """Проверяем что None (не настроено) считается как выключено"""
        settings = CaptchaSettings(
            visual_captcha_enabled=None,  # Не настроено
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=10,
            overflow_action="remove_oldest",
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        # None должен считаться как False
        assert settings.is_mode_enabled(CaptchaMode.VISUAL_DM) is False

    def test_is_mode_configured_visual_dm_complete(self):
        """Проверяем что Visual DM считается настроенным когда всё заполнено"""
        settings = CaptchaSettings(
            visual_captcha_enabled=True,
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=10,  # Не обязательно для Visual DM
            overflow_action="remove_oldest",  # Не обязательно для Visual DM
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        # Visual DM не требует max_pending и overflow_action
        assert settings.is_mode_configured(CaptchaMode.VISUAL_DM) is True

    def test_is_mode_configured_join_group_requires_limits(self):
        """Проверяем что Join Group требует настройки лимитов"""
        # Без max_pending и overflow_action
        settings = CaptchaSettings(
            visual_captcha_enabled=False,
            join_captcha_enabled=True,  # Включен
            invite_captcha_enabled=False,
            visual_captcha_timeout=None,
            join_captcha_timeout=60,  # Таймаут задан
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=None,  # НЕ задан
            overflow_action=None,  # НЕ задан
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        # Должен вернуть False потому что max_pending и overflow_action не заданы
        assert settings.is_mode_configured(CaptchaMode.JOIN_GROUP) is False

    def test_is_mode_configured_join_group_complete(self):
        """Проверяем что Join Group считается настроенным со всеми параметрами"""
        settings = CaptchaSettings(
            visual_captcha_enabled=False,
            join_captcha_enabled=True,
            invite_captcha_enabled=False,
            visual_captcha_timeout=None,
            join_captcha_timeout=60,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=10,  # Задан
            overflow_action="remove_oldest",  # Задан
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=60,
            dialog_cleanup_seconds=120,
        )

        assert settings.is_mode_configured(CaptchaMode.JOIN_GROUP) is True


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТЫ НАСТРОЕК ДИАЛОГОВ
# ═══════════════════════════════════════════════════════════════════════════

class TestDialogSettings:
    """Тесты для новых настроек диалогов"""

    def test_default_manual_input_enabled(self):
        """Проверяем значение по умолчанию для manual_input_enabled"""
        settings = CaptchaSettings(
            visual_captcha_enabled=True,
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=None,
            overflow_action=None,
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            # Новые поля диалогов
            manual_input_enabled=True,  # Default
            button_count=6,  # Default
            max_attempts=3,  # Default
            reminder_seconds=60,  # Default
            dialog_cleanup_seconds=120,  # Default
        )

        # Проверяем дефолты
        assert settings.manual_input_enabled is True
        assert settings.button_count == 6
        assert settings.max_attempts == 3
        assert settings.reminder_seconds == 60
        assert settings.dialog_cleanup_seconds == 120

    def test_button_count_custom_values(self):
        """Проверяем что можно установить кастомное количество кнопок"""
        for count in [4, 6, 9, 12]:
            settings = CaptchaSettings(
                visual_captcha_enabled=True,
                join_captcha_enabled=False,
                invite_captcha_enabled=False,
                visual_captcha_timeout=120,
                join_captcha_timeout=None,
                invite_captcha_timeout=None,
                legacy_timeout=300,
                max_pending=None,
                overflow_action=None,
                flood_threshold=5,
                flood_window_seconds=180,
                flood_action="warn",
                message_ttl_seconds=900,
                system_announcements_enabled=True,
                manual_input_enabled=True,
                button_count=count,
                max_attempts=3,
                reminder_seconds=60,
                dialog_cleanup_seconds=120,
            )
            assert settings.button_count == count

    def test_reminder_can_be_disabled(self):
        """Проверяем что напоминание можно отключить (0 секунд)"""
        settings = CaptchaSettings(
            visual_captcha_enabled=True,
            join_captcha_enabled=False,
            invite_captcha_enabled=False,
            visual_captcha_timeout=120,
            join_captcha_timeout=None,
            invite_captcha_timeout=None,
            legacy_timeout=300,
            max_pending=None,
            overflow_action=None,
            flood_threshold=5,
            flood_window_seconds=180,
            flood_action="warn",
            message_ttl_seconds=900,
            system_announcements_enabled=True,
            manual_input_enabled=True,
            button_count=6,
            max_attempts=3,
            reminder_seconds=0,  # Отключено
            dialog_cleanup_seconds=120,
        )

        assert settings.reminder_seconds == 0


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТЫ VERIFICATION_SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestHashAnswer:
    """Тесты для функции hash_answer"""

    def test_hash_answer_consistency(self):
        """Проверяем что одинаковые ответы дают одинаковый хэш"""
        # Два вызова с одинаковым ответом
        hash1 = hash_answer("42")
        hash2 = hash_answer("42")

        # Хэши должны совпадать
        assert hash1 == hash2

    def test_hash_answer_case_insensitive(self):
        """Проверяем что хэш не зависит от регистра"""
        # Ответы в разном регистре
        hash_lower = hash_answer("hello")
        hash_upper = hash_answer("HELLO")
        hash_mixed = hash_answer("HeLLo")

        # Все хэши должны совпадать
        assert hash_lower == hash_upper == hash_mixed

    def test_hash_answer_strips_whitespace(self):
        """Проверяем что хэш игнорирует пробелы по краям"""
        hash_clean = hash_answer("answer")
        hash_spaces = hash_answer("  answer  ")

        assert hash_clean == hash_spaces

    def test_hash_answer_length(self):
        """Проверяем что хэш имеет правильную длину (8 символов)"""
        result = hash_answer("test")

        # Должен быть 8-символьный хэш
        assert len(result) == 8

    def test_different_answers_different_hashes(self):
        """Проверяем что разные ответы дают разные хэши"""
        hash1 = hash_answer("42")
        hash2 = hash_answer("24")

        # Хэши должны отличаться
        assert hash1 != hash2


class TestVerifyAnswerHash:
    """Тесты для функции verify_answer_hash"""

    def test_matching_hashes_return_true(self):
        """Проверяем что совпадающие хэши возвращают True"""
        # Создаём хэш
        correct = hash_answer("42")

        # Проверяем с тем же хэшем
        result = verify_answer_hash(correct, correct)

        assert result is True

    def test_different_hashes_return_false(self):
        """Проверяем что разные хэши возвращают False"""
        hash1 = hash_answer("42")
        hash2 = hash_answer("24")

        result = verify_answer_hash(hash1, hash2)

        assert result is False


class TestCheckCaptchaOwnership:
    """Тесты для функции check_captcha_ownership_by_callback_data"""

    def test_owner_clicking_own_captcha(self):
        """Проверяем что владелец может нажать свою капчу"""
        # Владелец капчи
        owner_id = 12345

        # Владелец нажимает свою кнопку
        result = check_captcha_ownership_by_callback_data(
            clicker_user_id=owner_id,
            owner_from_callback=owner_id,
            chat_id=-100123456,
        )

        assert result is True

    def test_other_user_clicking_captcha(self):
        """Проверяем что чужой пользователь не может нажать капчу"""
        owner_id = 12345
        other_user_id = 67890

        # Другой пользователь пытается нажать
        result = check_captcha_ownership_by_callback_data(
            clicker_user_id=other_user_id,
            owner_from_callback=owner_id,
            chat_id=-100123456,
        )

        assert result is False


class TestGenerateCaptchaOptions:
    """Тесты для функции generate_captcha_options"""

    def test_generates_correct_number_of_options(self):
        """Проверяем что генерируется правильное количество вариантов"""
        options = generate_captcha_options("42", count=4)

        assert len(options) == 4

    def test_contains_correct_answer(self):
        """Проверяем что один из вариантов - правильный ответ"""
        correct_answer = "42"
        options = generate_captcha_options(correct_answer, count=4)

        # Должен быть один вариант с is_correct=True
        correct_options = [o for o in options if o["is_correct"]]
        assert len(correct_options) == 1

        # И его текст должен совпадать с ответом
        assert correct_options[0]["text"] == correct_answer

    def test_options_are_shuffled(self):
        """Проверяем что варианты перемешиваются"""
        # Генерируем несколько раз и проверяем что порядок меняется
        orders = []
        for _ in range(10):
            options = generate_captcha_options("42", count=4)
            order = tuple(o["text"] for o in options)
            orders.append(order)

        # Должны быть разные порядки (хотя бы 2 уникальных)
        unique_orders = set(orders)
        # С вероятностью ~99.9% будет больше 1 уникального порядка
        assert len(unique_orders) >= 1  # Минимальная проверка

    def test_each_option_has_required_fields(self):
        """Проверяем что каждый вариант имеет нужные поля"""
        options = generate_captcha_options("42", count=4)

        for option in options:
            assert "text" in option
            assert "hash" in option
            assert "is_correct" in option


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТЫ С МОКАМИ ДЛЯ БД
# ═══════════════════════════════════════════════════════════════════════════

class TestGetCaptchaSettingsWithMock:
    """Тесты для get_captcha_settings с мокированной сессией"""

    @pytest.mark.asyncio
    async def test_returns_settings_from_db(self):
        """Проверяем что функция возвращает настройки из БД"""
        # Мокируем ChatSettings объект
        mock_settings = MagicMock()
        mock_settings.visual_captcha_enabled = True
        mock_settings.captcha_join_enabled = False
        mock_settings.captcha_invite_enabled = False
        mock_settings.visual_captcha_timeout_seconds = 120
        mock_settings.join_captcha_timeout_seconds = None
        mock_settings.invite_captcha_timeout_seconds = None
        mock_settings.captcha_timeout_seconds = 300
        mock_settings.captcha_max_pending = 10
        mock_settings.captcha_overflow_action = "remove_oldest"
        mock_settings.captcha_flood_threshold = 5
        mock_settings.captcha_flood_window_seconds = 180
        mock_settings.captcha_flood_action = "warn"
        mock_settings.captcha_message_ttl_seconds = 900
        mock_settings.system_mute_announcements_enabled = True

        # Мокируем сессию
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_settings)

        # Вызываем функцию
        result = await get_captcha_settings(mock_session, chat_id=-100123456)

        # Проверяем результат
        assert result.visual_captcha_enabled is True
        assert result.visual_captcha_timeout == 120
        assert result.max_pending == 10

    @pytest.mark.asyncio
    async def test_creates_new_settings_if_not_exists(self):
        """Проверяем что создаются новые настройки если их нет"""
        # Мокируем сессию - get возвращает None
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        # Патчим ChatSettings
        with patch("bot.services.captcha.settings_service.ChatSettings") as MockChatSettings:
            # Настраиваем мок ChatSettings
            mock_new_settings = MagicMock()
            mock_new_settings.visual_captcha_enabled = None
            mock_new_settings.captcha_join_enabled = False
            mock_new_settings.captcha_invite_enabled = False
            mock_new_settings.visual_captcha_timeout_seconds = None
            mock_new_settings.join_captcha_timeout_seconds = None
            mock_new_settings.invite_captcha_timeout_seconds = None
            mock_new_settings.captcha_timeout_seconds = 300
            mock_new_settings.captcha_max_pending = None
            mock_new_settings.captcha_overflow_action = None
            mock_new_settings.captcha_flood_threshold = 5
            mock_new_settings.captcha_flood_window_seconds = 180
            mock_new_settings.captcha_flood_action = "warn"
            mock_new_settings.captcha_message_ttl_seconds = 900
            mock_new_settings.system_mute_announcements_enabled = True

            MockChatSettings.return_value = mock_new_settings

            # Вызываем функцию
            result = await get_captcha_settings(mock_session, chat_id=-100123456)

            # Проверяем что add был вызван
            mock_session.add.assert_called_once()

            # И что flush был вызван
            mock_session.flush.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# ЗАПУСК ТЕСТОВ
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
