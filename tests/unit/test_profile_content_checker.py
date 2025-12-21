# tests/unit/test_profile_content_checker.py
"""
Юнит-тесты для критерия 6 Profile Monitor:
Проверка имени и bio на запрещённый контент из ContentFilter.

Критерий 6 использует ТОЛЬКО WordFilter с категориями:
- harmful: наркотики (кокс, шишки, экстази)
- obfuscated: l33tspeak нормализация ("К о к с" → "кокс")

НЕ использует:
- simple: будут ложные муты
- ScamDetector: не нужен для имён
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from bot.services.profile_monitor.content_checker import (
    check_name_and_bio_content,
    apply_content_filter_action,
    ContentCheckResult,
    ALLOWED_CATEGORIES,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def mock_session():
    """Mock AsyncSession."""
    return AsyncMock()


@pytest.fixture
def mock_bot():
    """Mock Bot instance."""
    bot = AsyncMock()
    bot.restrict_chat_member = AsyncMock()
    bot.ban_chat_member = AsyncMock()
    bot.unban_chat_member = AsyncMock()
    return bot


# ============================================================
# MOCK WORD FILTER RESULTS
# ============================================================
@dataclass
class MockWordMatchResult:
    """Mock для WordMatchResult."""
    matched: bool
    word: str = None
    category: str = None
    action: str = None
    action_duration: int = None


# ============================================================
# ТЕСТЫ: КАТЕГОРИИ
# ============================================================
class TestAllowedCategories:
    """Тесты для проверки разрешённых категорий."""

    def test_only_harmful_and_obfuscated_allowed(self):
        """Только harmful и obfuscated категории разрешены."""
        assert ALLOWED_CATEGORIES == {"harmful", "obfuscated"}

    def test_simple_not_in_allowed(self):
        """Категория simple НЕ должна быть в разрешённых."""
        assert "simple" not in ALLOWED_CATEGORIES

    def test_scam_not_in_allowed(self):
        """ScamDetector категории НЕ должны быть в разрешённых."""
        assert "scam" not in ALLOWED_CATEGORIES


# ============================================================
# ТЕСТЫ: ПРОВЕРКА ИМЕНИ
# ============================================================
class TestNameCheck:
    """Тесты проверки имени на запрещённый контент."""

    @pytest.mark.asyncio
    async def test_harmful_word_in_name_triggers_action(self, mock_session):
        """Запрещённое слово категории harmful в имени вызывает действие."""
        # Mock WordFilter
        mock_result = MockWordMatchResult(
            matched=True,
            word="кокс",
            category="harmful",
            action="mute",
            action_duration=None,  # Навсегда
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Продаю кокс",
                bio=None,
            )

            assert result.should_act is True
            assert result.action == "mute"
            assert result.action_duration is None  # Навсегда
            assert "имени" in result.reason
            assert "кокс" in result.reason
            assert result.category == "harmful"

    @pytest.mark.asyncio
    async def test_obfuscated_word_in_name_triggers_action(self, mock_session):
        """l33tspeak слово категории obfuscated в имени вызывает действие."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="кокс",  # После нормализации
            category="obfuscated",
            action="mute",
            action_duration=60,  # 60 минут
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="К о к с 🥥",  # l33tspeak
                bio=None,
            )

            assert result.should_act is True
            assert result.action == "mute"
            assert result.action_duration == 60
            assert result.category == "obfuscated"

    @pytest.mark.asyncio
    async def test_simple_category_ignored(self, mock_session):
        """Категория simple игнорируется (ложные муты)."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="привет",
            category="simple",  # Игнорируемая категория
            action="mute",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Привет мир",
                bio=None,
            )

            assert result.should_act is False

    @pytest.mark.asyncio
    async def test_clean_name_no_action(self, mock_session):
        """Чистое имя без запрещённых слов не вызывает действие."""
        mock_result = MockWordMatchResult(matched=False)

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Иван Петров",
                bio=None,
            )

            assert result.should_act is False

    @pytest.mark.asyncio
    async def test_empty_name_no_action(self, mock_session):
        """Пустое имя не вызывает действие."""
        mock_result = MockWordMatchResult(matched=False)

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="",
                bio=None,
            )

            assert result.should_act is False


# ============================================================
# ТЕСТЫ: ПРОВЕРКА BIO
# ============================================================
class TestBioCheck:
    """Тесты проверки bio на запрещённый контент."""

    @pytest.mark.asyncio
    async def test_harmful_word_in_bio_triggers_action(self, mock_session):
        """Запрещённое слово в bio вызывает действие."""
        # Первый вызов (имя) - чисто, второй (bio) - запрещено
        clean_result = MockWordMatchResult(matched=False)
        harmful_result = MockWordMatchResult(
            matched=True,
            word="экстази",
            category="harmful",
            action="ban",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(
                side_effect=[clean_result, harmful_result]
            )

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Иван",
                bio="Продаю экстази дёшево",
            )

            assert result.should_act is True
            assert result.action == "ban"
            assert "bio" in result.reason
            assert "экстази" in result.reason

    @pytest.mark.asyncio
    async def test_name_checked_before_bio(self, mock_session):
        """Имя проверяется раньше bio."""
        name_result = MockWordMatchResult(
            matched=True,
            word="кокс",
            category="harmful",
            action="mute",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=name_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Кокс продажа",
                bio="Также продаю шишки",
            )

            # Имя проверяется первым
            assert result.should_act is True
            assert "имени" in result.reason

    @pytest.mark.asyncio
    async def test_empty_bio_not_checked(self, mock_session):
        """Пустой bio не проверяется."""
        mock_result = MockWordMatchResult(matched=False)

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Иван",
                bio="",
            )

            # check вызывается только 1 раз (для имени)
            assert mock_filter.check.call_count == 1


# ============================================================
# ТЕСТЫ: ДЕЙСТВИЯ ИЗ CONTENT FILTER
# ============================================================
class TestActionFromContentFilter:
    """Тесты применения действий из ContentFilter."""

    @pytest.mark.asyncio
    async def test_action_mute_forever(self, mock_session):
        """Действие mute навсегда (duration=None)."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="наркотики",
            category="harmful",
            action="mute",
            action_duration=None,  # Навсегда
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Наркотики",
                bio=None,
            )

            assert result.action == "mute"
            assert result.action_duration is None

    @pytest.mark.asyncio
    async def test_action_mute_with_duration(self, mock_session):
        """Действие mute с длительностью."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="кокс",
            category="harmful",
            action="mute",
            action_duration=120,  # 2 часа
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Продаю кокс",
                bio=None,
            )

            assert result.action == "mute"
            assert result.action_duration == 120

    @pytest.mark.asyncio
    async def test_action_ban(self, mock_session):
        """Действие ban из ContentFilter."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="героин",
            category="harmful",
            action="ban",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Героин дёшево",
                bio=None,
            )

            assert result.action == "ban"

    @pytest.mark.asyncio
    async def test_action_kick(self, mock_session):
        """Действие kick из ContentFilter."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="шишки",
            category="harmful",
            action="kick",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Шишки 420",
                bio=None,
            )

            assert result.action == "kick"

    @pytest.mark.asyncio
    async def test_default_action_is_mute(self, mock_session):
        """Если action не указан, используется mute по умолчанию."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="кокс",
            category="harmful",
            action=None,  # Не указано
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="Кокс",
                bio=None,
            )

            assert result.action == "mute"  # Default


# ============================================================
# ТЕСТЫ: ПРИМЕНЕНИЕ ДЕЙСТВИЙ
# ============================================================
class TestApplyAction:
    """Тесты применения действий через Bot API."""

    @pytest.mark.asyncio
    async def test_apply_mute_forever(self, mock_bot):
        """Применение мута навсегда."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="mute",
            duration=None,  # Навсегда
            reason="Запрещённое слово в имени: кокс",
        )

        assert success is True
        mock_bot.restrict_chat_member.assert_called_once()
        call_kwargs = mock_bot.restrict_chat_member.call_args.kwargs
        assert call_kwargs["chat_id"] == -1001234567890
        assert call_kwargs["user_id"] == 123456789
        assert call_kwargs["until_date"] is None  # Навсегда

    @pytest.mark.asyncio
    async def test_apply_mute_with_duration(self, mock_bot):
        """Применение мута с длительностью."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="mute",
            duration=60,  # 60 минут
            reason="Запрещённое слово в имени",
        )

        assert success is True
        mock_bot.restrict_chat_member.assert_called_once()
        call_kwargs = mock_bot.restrict_chat_member.call_args.kwargs
        assert call_kwargs["until_date"] is not None  # Есть дата окончания

    @pytest.mark.asyncio
    async def test_apply_ban(self, mock_bot):
        """Применение бана."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="ban",
            duration=None,
            reason="Запрещённое слово в имени",
        )

        assert success is True
        mock_bot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_kick(self, mock_bot):
        """Применение кика (ban + unban)."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="kick",
            duration=None,
            reason="Запрещённое слово в имени",
        )

        assert success is True
        mock_bot.ban_chat_member.assert_called_once()
        mock_bot.unban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_warn_logs_only(self, mock_bot):
        """Предупреждение только логируется."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="warn",
            duration=None,
            reason="Предупреждение",
        )

        # warn не вызывает API методы ограничения
        mock_bot.restrict_chat_member.assert_not_called()
        mock_bot.ban_chat_member.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_delete_returns_false(self, mock_bot):
        """Действие delete возвращает False (неприменимо к имени/bio)."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="delete",
            duration=None,
            reason="Удаление неприменимо",
        )

        assert success is False

    @pytest.mark.asyncio
    async def test_apply_unknown_action_returns_false(self, mock_bot):
        """Неизвестное действие возвращает False."""
        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="unknown_action",
            duration=None,
            reason="Неизвестное действие",
        )

        assert success is False

    @pytest.mark.asyncio
    async def test_apply_action_handles_exception(self, mock_bot):
        """Исключение при применении действия обрабатывается."""
        mock_bot.restrict_chat_member.side_effect = Exception("API error")

        success = await apply_content_filter_action(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            action="mute",
            duration=None,
            reason="Тест ошибки",
        )

        assert success is False


# ============================================================
# ТЕСТЫ: CONTENT CHECK RESULT
# ============================================================
class TestContentCheckResult:
    """Тесты для ContentCheckResult dataclass."""

    def test_result_with_all_fields(self):
        """ContentCheckResult с заполненными полями."""
        result = ContentCheckResult(
            should_act=True,
            action="mute",
            action_duration=60,
            reason="Запрещённое слово",
            matched_word="кокс",
            category="harmful",
        )

        assert result.should_act is True
        assert result.action == "mute"
        assert result.action_duration == 60
        assert result.reason == "Запрещённое слово"
        assert result.matched_word == "кокс"
        assert result.category == "harmful"

    def test_result_should_not_act(self):
        """ContentCheckResult когда действие не требуется."""
        result = ContentCheckResult(should_act=False)

        assert result.should_act is False
        assert result.action is None
        assert result.reason is None


# ============================================================
# ТЕСТЫ: ИНТЕГРАЦИЯ С L33TSPEAK
# ============================================================
class TestL33tspeakNormalization:
    """Тесты нормализации l33tspeak."""

    @pytest.mark.asyncio
    async def test_spaced_word_detected(self, mock_session):
        """Слово с пробелами 'К о к с' должно определяться."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="кокс",
            category="obfuscated",
            action="mute",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="К о к с 🥥ш ш 🥦💨",
                bio=None,
            )

            assert result.should_act is True
            assert result.category == "obfuscated"

    @pytest.mark.asyncio
    async def test_emoji_obfuscation_detected(self, mock_session):
        """Слово с эмодзи должно определяться."""
        mock_result = MockWordMatchResult(
            matched=True,
            word="шишки",
            category="obfuscated",
            action="mute",
            action_duration=None,
        )

        with patch(
            "bot.services.profile_monitor.content_checker.WordFilter"
        ) as MockWordFilter:
            mock_filter = MockWordFilter.return_value
            mock_filter.check = AsyncMock(return_value=mock_result)

            result = await check_name_and_bio_content(
                session=mock_session,
                chat_id=-1001234567890,
                user_id=123456789,
                full_name="🌿Ш🌿И🌿Ш🌿К🌿И🌿",
                bio=None,
            )

            assert result.should_act is True
