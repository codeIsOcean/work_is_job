"""
Unit тесты для фиксов:
- Баг 1: Ложное срабатывание "Бот добавлен в группу" для private чатов
- Баг 2: Ложное срабатывание антифлуда при одобрении join_request
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.types import ChatMemberUpdated, Chat, User

from bot.services.event_classifier import classify_join_event, JoinEventType


# ============================================================
# Баг 1: Проверка игнорирования private чатов в bot_added_handler
# ============================================================

class TestBug1PrivateChatIgnored:
    """Тесты для Бага 1: bot_added_handler должен игнорировать private чаты"""

    @pytest.mark.asyncio
    async def test_private_chat_ignored_in_my_status_change(self):
        """
        Тест: on_my_status_change должен игнорировать события из private чатов.

        Когда пользователь пишет боту /start в ЛС, происходит событие my_chat_member
        с chat.type = ChatType.PRIVATE. Бот НЕ должен логировать это как
        "добавление в группу".
        """
        from bot.handlers.bot_activity_handlers.bot_added_handler import on_my_status_change

        # Создаем мок события для private чата
        bot = AsyncMock(spec=Bot)
        bot.me = AsyncMock(return_value=MagicMock(id=123456, username="test_bot"))

        session = AsyncMock()

        # Private чат - chat.id == user.id
        user_id = 6638729116

        # Создаем event с ChatType.PRIVATE
        event = MagicMock(spec=ChatMemberUpdated)
        event.chat = MagicMock(spec=Chat)
        event.chat.id = user_id
        event.chat.type = ChatType.PRIVATE  # Ключевой момент!
        event.chat.title = None  # У private чатов нет title

        event.from_user = MagicMock(spec=User)
        event.from_user.id = user_id
        event.from_user.full_name = "Test User"

        event.new_chat_member = MagicMock()
        event.new_chat_member.status = ChatMemberStatus.MEMBER

        # Патчим sync_group_and_admins и safe_send чтобы проверить, что они НЕ вызываются
        # log_bot_added_to_group импортируется локально внутри функции, поэтому патчим источник
        with patch('bot.handlers.bot_activity_handlers.bot_added_handler.sync_group_and_admins') as mock_sync, \
             patch('bot.handlers.bot_activity_handlers.bot_added_handler.safe_send') as mock_send, \
             patch('bot.services.bot_activity_journal.bot_activity_journal_logic.log_bot_added_to_group') as mock_log:

            # Вызываем хендлер
            await on_my_status_change(event, bot, session)

            # Проверяем, что ничего не было вызвано (ранний return для private)
            mock_sync.assert_not_called()
            mock_send.assert_not_called()
            mock_log.assert_not_called()

    def test_chat_type_private_comparison(self):
        """
        Тест: Сравнение chat.type с ChatType.PRIVATE работает корректно.

        Проверяем, что aiogram ChatType enum сравнивается правильно.
        """
        # Симулируем chat.type как в aiogram
        chat = MagicMock()
        chat.type = ChatType.PRIVATE

        # Проверяем что сравнение работает
        assert chat.type == ChatType.PRIVATE
        assert chat.type != ChatType.GROUP
        assert chat.type != ChatType.SUPERGROUP

        # Проверяем что строковое сравнение тоже работает (для обратной совместимости)
        # В aiogram 3.x ChatType.PRIVATE.value == "private"
        assert ChatType.PRIVATE.value == "private"


# ============================================================
# Баг 2: Проверка had_pending_request в classify_join_event
# ============================================================

class TestBug2HadPendingRequest:
    """Тесты для Бага 2: had_pending_request должен превращать INVITE в SELF_JOIN"""

    def _make_event(
        self,
        user_id: int,
        initiator_id: int = None,
        old_status: str = "left",
        new_status: str = "member",
    ):
        """Создает мок ChatMemberUpdated события"""
        user = SimpleNamespace(id=user_id, username="user", first_name="User")
        old_member = SimpleNamespace(status=old_status, user=user)
        new_member = SimpleNamespace(status=new_status, user=user)
        chat = SimpleNamespace(id=-1001234567890, title="Test Group", type="supergroup")

        event = SimpleNamespace(
            old_chat_member=old_member,
            new_chat_member=new_member,
            chat=chat,
            from_user=SimpleNamespace(id=initiator_id) if initiator_id else None,
        )
        return event

    def test_invite_without_pending_request(self):
        """
        Тест: Без pending request, событие с initiator != user классифицируется как INVITE.
        """
        event = self._make_event(user_id=123, initiator_id=456)

        result = classify_join_event(
            event=event,
            user_id=123,
            initiator_id=456,
            had_pending_request=False,  # Нет pending request
        )

        assert result == JoinEventType.INVITE

    def test_invite_becomes_self_join_with_pending_request(self):
        """
        Тест: С pending request, событие с initiator != user классифицируется как SELF_JOIN.

        Это ключевой тест для Бага 2!
        Когда админ одобряет join_request:
        - initiator_id = админ (не равен user_id)
        - НО у пользователя был pending join_request
        - Значит это НЕ invite, а одобрение запроса = SELF_JOIN
        """
        event = self._make_event(user_id=123, initiator_id=456)

        result = classify_join_event(
            event=event,
            user_id=123,
            initiator_id=456,
            had_pending_request=True,  # БЫЛ pending request!
        )

        # Должен быть SELF_JOIN, а не INVITE
        assert result == JoinEventType.SELF_JOIN

    def test_self_join_stays_self_join_with_pending_request(self):
        """
        Тест: SELF_JOIN остается SELF_JOIN независимо от had_pending_request.
        """
        event = self._make_event(user_id=123, initiator_id=None)

        result = classify_join_event(
            event=event,
            user_id=123,
            initiator_id=None,
            had_pending_request=True,
        )

        assert result == JoinEventType.SELF_JOIN


# ============================================================
# Баг 2: Проверка сохранения join_request в Redis при fallback
# ============================================================

class TestBug2SaveJoinRequestOnFallback:
    """Тесты для Бага 2: save_join_request должен вызываться даже при отключенной капче"""

    @pytest.mark.asyncio
    async def test_save_join_request_called_when_captcha_disabled(self, fake_redis):
        """
        Тест: save_join_request вызывается даже когда капча отключена (fallback/disabled).

        Это интеграционный тест для проверки фикса в handle_join_request.
        """
        from bot.services.visual_captcha_logic import save_join_request

        user_id = 123
        chat_id = -1001234567890
        group_id = "test_group"

        # Сохраняем join_request
        await save_join_request(user_id, chat_id, group_id)

        # Проверяем что ключ создан
        key = f"join_request:{user_id}:{group_id}"
        exists = await fake_redis.exists(key)
        assert exists == 1

        # Проверяем значение
        value = await fake_redis.get(key)
        assert value == str(chat_id)

    @pytest.mark.asyncio
    async def test_had_pending_request_detected_after_save(self, fake_redis):
        """
        Тест: После save_join_request, проверка had_pending_request возвращает True.

        Симулирует полный флоу:
        1. Приходит join_request
        2. Вызывается save_join_request (даже если капча отключена)
        3. Позже приходит ChatMemberUpdated
        4. had_pending_request = True → классификация = SELF_JOIN
        """
        from bot.services.visual_captcha_logic import save_join_request

        user_id = 456
        chat_id = -1001234567890
        group_id = "private_-1001234567890"

        # Шаг 1: join_request приходит, save_join_request вызывается
        await save_join_request(user_id, chat_id, group_id)

        # Шаг 2: ChatMemberUpdated приходит, проверяем had_pending_request
        key = f"join_request:{user_id}:{group_id}"
        had_pending_request = await fake_redis.exists(key)

        assert had_pending_request == 1  # True

        # Шаг 3: Классификация должна быть SELF_JOIN
        event = SimpleNamespace(
            old_chat_member=SimpleNamespace(status="left"),
            new_chat_member=SimpleNamespace(status="member"),
            from_user=SimpleNamespace(id=789),  # Админ, который одобрил
        )

        result = classify_join_event(
            event=event,
            user_id=user_id,
            initiator_id=789,
            had_pending_request=bool(had_pending_request),
        )

        assert result == JoinEventType.SELF_JOIN


# ============================================================
# Интеграционный тест: Полный флоу handle_join_request
# ============================================================

class TestHandleJoinRequestIntegration:
    """Интеграционные тесты для handle_join_request"""

    @pytest.mark.asyncio
    async def test_handle_join_request_saves_key_before_approve(self, fake_redis, monkeypatch):
        """
        Тест: handle_join_request сохраняет ключ в Redis ДО вызова approve.

        Проверяем что фикс работает: save_join_request вызывается
        в блоке if decision.fallback_mode or not decision.require_captcha
        """
        # Патчим зависимости
        mock_decision = MagicMock()
        mock_decision.fallback_mode = False
        mock_decision.require_captcha = False  # Капча отключена

        mock_admission = MagicMock()

        # Флаг для проверки порядка вызовов
        call_order = []

        async def mock_save_join_request(user_id, chat_id, group_id):
            call_order.append(('save_join_request', user_id, group_id))
            # Реально сохраняем в fake_redis
            await fake_redis.setex(f"join_request:{user_id}:{group_id}", 3600, str(chat_id))

        async def mock_approve(*args, **kwargs):
            call_order.append(('approve',))

        monkeypatch.setattr(
            "bot.handlers.visual_captcha.visual_captcha_handler.save_join_request",
            mock_save_join_request
        )
        monkeypatch.setattr(
            "bot.handlers.visual_captcha.visual_captcha_handler.approve_chat_join_request",
            mock_approve
        )

        with patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings', new_callable=AsyncMock), \
             patch('bot.handlers.visual_captcha.visual_captcha_handler.should_require_captcha', new_callable=AsyncMock) as mock_should, \
             patch('bot.handlers.visual_captcha.visual_captcha_handler.evaluate_admission', new_callable=AsyncMock) as mock_eval, \
             patch('bot.handlers.visual_captcha.visual_captcha_handler.log_join_request', new_callable=AsyncMock), \
             patch('bot.handlers.visual_captcha.visual_captcha_handler.get_session') as mock_session:

            mock_should.return_value = mock_decision
            mock_eval.return_value = mock_admission

            # Создаем async context manager для session
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            # Создаем join_request
            from aiogram.types import ChatJoinRequest

            join_request = MagicMock(spec=ChatJoinRequest)
            join_request.from_user = MagicMock(id=123, username="test_user")
            join_request.chat = MagicMock(id=-1001234567890, username="test_group")
            join_request.bot = AsyncMock()

            # Импортируем и вызываем хендлер
            from bot.handlers.visual_captcha.visual_captcha_handler import handle_join_request

            await handle_join_request(join_request)

            # Проверяем порядок вызовов: save_join_request ДОЛЖЕН быть ДО approve
            assert len(call_order) >= 2
            save_index = next(i for i, c in enumerate(call_order) if c[0] == 'save_join_request')
            approve_index = next(i for i, c in enumerate(call_order) if c[0] == 'approve')

            assert save_index < approve_index, \
                f"save_join_request должен вызываться ДО approve! Порядок: {call_order}"
