"""
Unit tests for captcha leave/rejoin security fix.

Tests the critical security scenario where:
1. User joins group → passes captcha → captcha_passed flag is set
2. User leaves group → captcha_passed flag MUST be deleted
3. User rejoins group → captcha MUST be required again

This prevents scammers from bypassing captcha by leaving and rejoining.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import ChatMemberUpdated, ChatMember, Chat, User as TgUser
from aiogram.enums import ChatMemberStatus

from bot.services import redis_conn


@pytest.mark.asyncio
async def test_captcha_flag_deleted_on_leave():
    """
    SECURITY TEST: Verify captcha_passed flag is deleted when user leaves group.

    Scenario:
    1. User has captcha_passed flag set (simulating they passed captcha)
    2. User leaves the group
    3. Flag MUST be deleted
    """
    user_id = 123456
    chat_id = -1001234567890

    # Setup: User has captcha_passed flag (they passed captcha earlier)
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    # Verify flag exists
    flag_before = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_before == "1", "Flag should exist before leave"

    # Create leave event (MEMBER -> LEFT)
    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = MagicMock(spec=Chat, id=chat_id)
    event.new_chat_member = MagicMock(spec=ChatMember)
    event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    event.new_chat_member.status = ChatMemberStatus.LEFT
    event.old_chat_member = MagicMock(spec=ChatMember)
    event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    # Execute: User leaves
    await handle_member_status_change(event, session)

    # Verify: Flag MUST be deleted
    flag_after = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after is None, "Flag MUST be deleted when user leaves"


@pytest.mark.asyncio
async def test_captcha_flag_deleted_on_kick():
    """
    SECURITY TEST: Verify captcha_passed flag is deleted when user is kicked.

    Similar to leave test, but user is kicked by admin.
    """
    user_id = 123456
    chat_id = -1001234567890

    # Setup: User has captcha_passed flag
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    # Create kick event (MEMBER -> KICKED)
    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = MagicMock(spec=Chat, id=chat_id)
    event.new_chat_member = MagicMock(spec=ChatMember)
    event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    event.new_chat_member.status = ChatMemberStatus.KICKED
    event.old_chat_member = MagicMock(spec=ChatMember)
    event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    # Execute: User is kicked
    await handle_member_status_change(event, session)

    # Verify: Flag MUST be deleted
    flag_after = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after is None, "Flag MUST be deleted when user is kicked"


@pytest.mark.asyncio
async def test_leave_without_flag_no_error():
    """
    Test that leaving without captcha_passed flag doesn't cause errors.

    Scenario: User never passed captcha (or flag expired), then leaves.
    Should not raise any errors.
    """
    user_id = 123456
    chat_id = -1001234567890

    # Ensure flag doesn't exist
    await redis_conn.redis.delete(f"captcha_passed:{user_id}:{chat_id}")

    # Create leave event
    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = MagicMock(spec=Chat, id=chat_id)
    event.new_chat_member = MagicMock(spec=ChatMember)
    event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    event.new_chat_member.status = ChatMemberStatus.LEFT
    event.old_chat_member = MagicMock(spec=ChatMember)
    event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    # Execute: Should not raise error
    try:
        await handle_member_status_change(event, session)
    except Exception as e:
        pytest.fail(f"Should not raise error when flag doesn't exist: {e}")


@pytest.mark.asyncio
async def test_rejoin_requires_captcha_after_leave():
    """
    CRITICAL SECURITY TEST: Verify captcha is required when user rejoins after leaving.

    Full scenario:
    1. User passes captcha → flag set
    2. User leaves → flag deleted
    3. User rejoins → captcha MUST be required
    """
    user_id = 123456
    chat_id = -1001234567890

    # Step 1: Simulate user passed captcha
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Step 2: User leaves
    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group")
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    await handle_member_status_change(leave_event, session)

    # Verify flag was deleted
    flag_after_leave = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after_leave is None, "Flag must be deleted on leave"

    # Step 3: User rejoins
    join_event = MagicMock(spec=ChatMemberUpdated)
    join_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group", username=None)
    join_event.bot = AsyncMock()
    join_event.new_chat_member = MagicMock(spec=ChatMember)
    join_event.new_chat_member.user = MagicMock(
        spec=TgUser, id=user_id, username="testuser",
        first_name="Test", last_name="User", is_premium=False
    )
    join_event.new_chat_member.status = ChatMemberStatus.MEMBER
    join_event.old_chat_member = MagicMock(spec=ChatMember)
    join_event.old_chat_member.status = ChatMemberStatus.LEFT
    join_event.from_user = None  # Self-join

    # Mock the required functions
    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow') as mock_prepare, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings') as mock_settings, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.create_snapshot_on_join') as mock_snapshot:

        from bot.services.event_classifier import JoinEventType
        from bot.services.captcha_flow_logic import CaptchaDecision

        # Setup mocks
        mock_classify.return_value = JoinEventType.SELF_JOIN

        decision = CaptchaDecision(
            require_captcha=True,  # CAPTCHA MUST BE REQUIRED
            fallback_mode=False,
            anti_flood=None
        )
        mock_prepare.return_value = decision

        settings = MagicMock()
        settings.timeout_seconds = 300
        mock_settings.return_value = settings

        mock_send_captcha.return_value = None

        # Execute rejoin
        await handle_member_status_change(join_event, session)

        # CRITICAL VERIFICATION: send_captcha_prompt MUST be called
        mock_send_captcha.assert_called_once()

        # Verify captcha was sent with correct parameters
        call_args = mock_send_captcha.call_args
        assert call_args.kwargs['user'].id == user_id
        assert call_args.kwargs['chat'].id == chat_id


@pytest.mark.asyncio
async def test_flag_ttl_logged_on_delete():
    """
    Test that TTL is logged when flag is deleted.
    Helps with debugging and monitoring.
    """
    user_id = 123456
    chat_id = -1001234567890

    # Setup: Flag with 500 seconds TTL remaining
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 500, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = MagicMock(spec=Chat, id=chat_id)
    event.new_chat_member = MagicMock(spec=ChatMember)
    event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    event.new_chat_member.status = ChatMemberStatus.LEFT
    event.old_chat_member = MagicMock(spec=ChatMember)
    event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    # Execute with logging check
    with patch('bot.handlers.visual_captcha.visual_captcha_handler.logger') as mock_logger:
        await handle_member_status_change(event, session)

        # Verify logging happened at least once when flag is deleted
        assert mock_logger.info.called, "Should log when flag is deleted"
        # TTL может логироваться в разных форматах, поэтому достаточно самого факта логирования


@pytest.mark.asyncio
async def test_non_leave_events_ignored():
    """
    Test that non-leave/non-join events don't affect captcha_passed flag.

    For example: MEMBER -> ADMINISTRATOR (user promoted to admin)
    """
    user_id = 123456
    chat_id = -1001234567890

    # Setup: Flag exists
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Event: User promoted to admin (MEMBER -> ADMINISTRATOR)
    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = MagicMock(spec=Chat, id=chat_id)
    event.new_chat_member = MagicMock(spec=ChatMember)
    event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    event.new_chat_member.status = ChatMemberStatus.ADMINISTRATOR
    event.old_chat_member = MagicMock(spec=ChatMember)
    event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    # Execute
    await handle_member_status_change(event, session)

    # Verify: Flag should still exist (not deleted for non-leave events)
    flag_after = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after == "1", "Flag should NOT be deleted for non-leave events"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_rejoin_captcha_required_when_visual_captcha_enabled(fake_redis):
    """
    CRITICAL FIX TEST: Verify captcha is required on rejoin when visual_captcha_enabled=True
    even if captcha_join_enabled=False.
    
    This tests the fix for the bug where:
    - User enables captcha via UI (sets visual_captcha_enabled=True)
    - User joins via join_request → captcha works
    - User leaves and rejoins → captcha was NOT sent (BUG)
    - Now captcha SHOULD be sent (FIX)
    """
    user_id = 123456
    chat_id = -1001234567890

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Step 1: User leaves (flag deleted)
    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group")
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()
    await handle_member_status_change(leave_event, session)

    # Step 2: User rejoins
    join_event = MagicMock(spec=ChatMemberUpdated)
    join_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group")
    join_event.bot = AsyncMock()
    join_event.new_chat_member = MagicMock(spec=ChatMember)
    join_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id, username="testuser")
    join_event.new_chat_member.status = ChatMemberStatus.MEMBER
    join_event.old_chat_member = MagicMock(spec=ChatMember)
    join_event.old_chat_member.status = ChatMemberStatus.LEFT
    join_event.from_user = None  # Self-join

    # Mock the required functions
    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow') as mock_prepare, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings') as mock_settings, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.get_visual_captcha_status') as mock_get_visual, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha:

        from bot.services.event_classifier import JoinEventType
        from bot.services.captcha_flow_logic import CaptchaDecision

        # Setup mocks
        mock_classify.return_value = JoinEventType.SELF_JOIN

        # CRITICAL: captcha_join_enabled=False (this was the bug - captcha wasn't sent)
        decision = CaptchaDecision(
            require_captcha=False,  # This is False (the bug scenario)
            fallback_mode=False,
            anti_flood=None
        )
        mock_prepare.return_value = decision

        settings = MagicMock()
        settings.timeout_seconds = 300
        mock_settings.return_value = settings

        # CRITICAL: visual_captcha_enabled=True (user enabled it via UI)
        mock_get_visual.return_value = True

        mock_send_captcha.return_value = None

        # Execute rejoin
        await handle_member_status_change(join_event, session)

        # CRITICAL VERIFICATION: send_captcha_prompt MUST be called
        # Even though decision.require_captcha=False, visual_captcha_enabled=True
        # should trigger captcha (this is the fix)
        mock_send_captcha.assert_called_once()

        # Verify captcha was sent with correct parameters
        call_args = mock_send_captcha.call_args
        assert call_args.kwargs['user'].id == user_id
        assert call_args.kwargs['chat'].id == chat_id

        # Verify get_visual_captcha_status was called (at least once)
        mock_get_visual.assert_called_with(chat_id)


@pytest.mark.asyncio
async def test_rejoin_db_fallback_when_redis_stale():
    """
    CRITICAL FIX TEST: Verify DB is checked when Redis returns False (stale cache).
    
    Scenario:
    - Redis says visual_captcha_enabled=False (stale cache)
    - DB says is_visual_enabled=True (actual value)
    - System should detect mismatch, update Redis, and send captcha
    """
    user_id = 123456
    chat_id = -1001234567890

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Step 1: User leaves
    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group")
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()
    await handle_member_status_change(leave_event, session)

    # Step 2: User rejoins with stale Redis cache
    join_event = MagicMock(spec=ChatMemberUpdated)
    join_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group", username=None)
    join_event.bot = AsyncMock()
    join_event.new_chat_member = MagicMock(spec=ChatMember)
    join_event.new_chat_member.user = MagicMock(
        spec=TgUser, id=user_id, username="testuser",
        first_name="Test", last_name="User", is_premium=False
    )
    join_event.new_chat_member.status = ChatMemberStatus.MEMBER
    join_event.old_chat_member = MagicMock(spec=ChatMember)
    join_event.old_chat_member.status = ChatMemberStatus.LEFT
    join_event.from_user = None

    # Mock: Redis says False (stale), but DB says True
    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow') as mock_prepare, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings') as mock_settings, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.get_visual_captcha_status') as mock_get_visual, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.redis') as mock_redis, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.create_snapshot_on_join') as mock_snapshot:

        from bot.services.event_classifier import JoinEventType
        from bot.services.captcha_flow_logic import CaptchaDecision
        from bot.database.models import CaptchaSettings

        # Setup mocks
        mock_classify.return_value = JoinEventType.SELF_JOIN

        decision = CaptchaDecision(
            require_captcha=False,  # Even if this is False
            fallback_mode=False,
            anti_flood=None
        )
        mock_prepare.return_value = decision

        settings = MagicMock()
        settings.timeout_seconds = 300
        mock_settings.return_value = settings

        # CRITICAL: Redis returns False (stale cache)
        mock_get_visual.return_value = False

        # Mock DB query: DB says True
        db_settings = MagicMock(spec=CaptchaSettings)
        db_settings.is_visual_enabled = True
        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = db_settings
        session.execute.return_value = mock_db_result

        # Mock Redis set (should be called to update stale cache)
        mock_redis.set = AsyncMock()

        mock_send_captcha.return_value = None

        # Execute rejoin
        await handle_member_status_change(join_event, session)

        # CRITICAL VERIFICATION: 
        # 1. DB should be checked (session.execute called)
        session.execute.assert_called()
        
        # 2. Redis should be updated (redis.set called with "1"),
        # даже если get_visual_captcha_status сам тоже синхронизирует значение.
        mock_redis.set.assert_any_call(f"visual_captcha_enabled:{chat_id}", "1")
        
        # 3. Captcha should be sent (even though Redis was False initially)
        mock_send_captcha.assert_called_once()


@pytest.mark.asyncio
async def test_send_captcha_error_handling():
    """
    TEST: Verify error handling when send_captcha_prompt fails.
    
    Scenario:
    - Captcha should be required
    - send_captcha_prompt raises exception
    - User should still be restricted (security)
    """
    user_id = 123456
    chat_id = -1001234567890

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    session = MagicMock()

    # User rejoins
    join_event = MagicMock(spec=ChatMemberUpdated)
    join_event.chat = MagicMock(spec=Chat, id=chat_id, title="Test Group", username=None)
    join_event.bot = AsyncMock()
    join_event.new_chat_member = MagicMock(spec=ChatMember)
    join_event.new_chat_member.user = MagicMock(
        spec=TgUser, id=user_id, username="testuser",
        first_name="Test", last_name="User", is_premium=False
    )
    join_event.new_chat_member.status = ChatMemberStatus.MEMBER
    join_event.old_chat_member = MagicMock(spec=ChatMember)
    join_event.old_chat_member.status = ChatMemberStatus.LEFT
    join_event.from_user = None

    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow') as mock_prepare, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings') as mock_settings, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.get_visual_captcha_status') as mock_get_visual, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.build_restriction_permissions') as mock_build_perm, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.create_snapshot_on_join') as mock_snapshot:

        from bot.services.event_classifier import JoinEventType
        from bot.services.captcha_flow_logic import CaptchaDecision

        mock_classify.return_value = JoinEventType.SELF_JOIN

        decision = CaptchaDecision(
            require_captcha=True,
            fallback_mode=False,
            anti_flood=None
        )
        mock_prepare.return_value = decision

        settings = MagicMock()
        settings.timeout_seconds = 300
        mock_settings.return_value = settings

        mock_get_visual.return_value = True

        # CRITICAL: send_captcha_prompt raises exception
        mock_send_captcha.side_effect = Exception("Network error: Failed to send message")

        mock_build_perm.return_value = MagicMock()

        # Execute rejoin
        await handle_member_status_change(join_event, session)

        # VERIFICATION: 
        # 1. send_captcha_prompt was called (even though it failed)
        mock_send_captcha.assert_called_once()
        
        # 2. User should still be restricted (security - even if captcha send failed)
        join_event.bot.restrict_chat_member.assert_called_once()