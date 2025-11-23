"""
E2E tests for captcha leave/rejoin security scenario.

Tests the complete real-world flow:
1. User requests to join group
2. Captcha is sent
3. User solves captcha correctly
4. User is approved and joins
5. captcha_passed flag is set
6. User leaves the group
7. captcha_passed flag is deleted
8. User rejoins the group
9. Captcha is sent again (CRITICAL SECURITY CHECK)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import (
    ChatJoinRequest, ChatMemberUpdated, ChatMember, Message,
    Chat, User as TgUser, CallbackQuery
)
from aiogram.enums import ChatMemberStatus

from bot.services import redis_conn


@pytest.mark.asyncio
async def test_full_leave_rejoin_captcha_flow():
    """
    E2E SECURITY TEST: Complete leave/rejoin flow with captcha verification.

    Critical security scenario to prevent scammer bypass:
    1. First join → captcha required → pass → approved
    2. Leave group → flag deleted
    3. Rejoin → captcha required again

    This test ensures scammers cannot bypass captcha by leaving and rejoining.
    
    NOTE: This test focuses on REJOIN behavior. For the initial captcha solving,
    we simulate the end state (flag set) rather than calling process_captcha_answer
    directly, because:
    - process_captcha_answer requires complex FSMContext setup
    - The test goal is to verify rejoin requires captcha again
    - The initial captcha flow is tested in unit tests
    - Setting the flag directly simulates what process_captcha_answer does
      (see bot/handlers/visual_captcha/visual_captcha_handler.py:654, 660, 663, 1365)
    """
    user_id = 987654
    chat_id = -1001234567890
    group_name = "Test Security Group"

    # =====================================
    # PHASE 1: Initial join with captcha
    # =====================================

    # User requests to join
    from bot.handlers.bot_activity_handlers.group_events import handle_join_request

    join_request = MagicMock(spec=ChatJoinRequest)
    join_request.chat = MagicMock(spec=Chat, id=chat_id, title=group_name, username=None)
    join_request.from_user = MagicMock(spec=TgUser, id=user_id, username="security_test_user")
    join_request.bot = AsyncMock()

    session = MagicMock()

    with patch('bot.handlers.bot_activity_handlers.group_events.is_visual_captcha_enabled', return_value=True), \
         patch('bot.handlers.bot_activity_handlers.group_events.create_deeplink_for_captcha', return_value="https://t.me/bot?start=test"), \
         patch('bot.handlers.bot_activity_handlers.group_events.get_captcha_keyboard', return_value=MagicMock()):

        # Join request sent
        await handle_join_request(join_request, session)

        # Verify captcha message sent to user
        join_request.bot.send_message.assert_called()

    # =====================================
    # PHASE 2: User solves captcha
    # =====================================
    # NOTE: This test focuses on REJOIN behavior, not the full captcha flow.
    # The real function is `process_captcha_answer` which requires FSMContext and complex setup.
    # For this e2e test, we simulate that user passed captcha by setting the flag directly.
    # This is acceptable because:
    # 1. The test goal is to verify rejoin requires captcha again
    # 2. The initial captcha flow is tested separately
    # 3. Setting the flag directly simulates the end state after successful captcha
    
    # Simulate: User passed captcha (this is what process_captcha_answer does at the end)
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    # Verify captcha_passed flag was set (TTL: 1 hour)
    flag_after_captcha = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after_captcha == "1", "captcha_passed flag must be set after correct answer"

    # =====================================
    # PHASE 3: User joins group (event)
    # =====================================

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    join_event = MagicMock(spec=ChatMemberUpdated)
    join_event.chat = MagicMock(spec=Chat, id=chat_id, title=group_name)
    join_event.bot = AsyncMock()
    join_event.new_chat_member = MagicMock(spec=ChatMember)
    join_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    join_event.new_chat_member.status = ChatMemberStatus.MEMBER
    join_event.old_chat_member = MagicMock(spec=ChatMember)
    join_event.old_chat_member.status = ChatMemberStatus.LEFT
    join_event.from_user = None  # Self-join

    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event'), \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow'), \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings'), \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.evaluate_admission') as mock_admission, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.clear_captcha_state'), \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.log_new_member'):

        from bot.services.captcha_flow_logic import CaptchaDecision

        mock_prepare = MagicMock()
        mock_prepare.return_value = CaptchaDecision(
            require_captcha=False,  # No captcha on first join (already passed in join_request)
            fallback_mode=False,
            anti_flood=None
        )

        admission = MagicMock()
        admission.muted = False
        mock_admission.return_value = admission

        # User joins
        await handle_member_status_change(join_event, session)

    # Verify flag still exists
    flag_after_join = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after_join == "1", "Flag should still exist after join"

    # =====================================
    # PHASE 4: User leaves group (CRITICAL)
    # =====================================

    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id, title=group_name)
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    # User leaves
    await handle_member_status_change(leave_event, session)

    # CRITICAL VERIFICATION: Flag MUST be deleted on leave
    flag_after_leave = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag_after_leave is None, "🔒 SECURITY: captcha_passed flag MUST be deleted when user leaves"

    # =====================================
    # PHASE 5: User rejoins (SECURITY CHECK)
    # =====================================

    rejoin_event = MagicMock(spec=ChatMemberUpdated)
    rejoin_event.chat = MagicMock(spec=Chat, id=chat_id, title=group_name)
    rejoin_event.bot = AsyncMock()
    rejoin_event.new_chat_member = MagicMock(spec=ChatMember)
    rejoin_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id, username="security_test_user")
    rejoin_event.new_chat_member.status = ChatMemberStatus.MEMBER
    rejoin_event.old_chat_member = MagicMock(spec=ChatMember)
    rejoin_event.old_chat_member.status = ChatMemberStatus.LEFT
    rejoin_event.from_user = None  # Self-join

    with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.prepare_manual_approval_flow') as mock_prepare, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.load_captcha_settings') as mock_settings, \
         patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha:

        from bot.services.event_classifier import JoinEventType
        from bot.services.captcha_flow_logic import CaptchaDecision

        mock_classify.return_value = JoinEventType.SELF_JOIN

        # CRITICAL: Captcha MUST be required on rejoin
        decision = CaptchaDecision(
            require_captcha=True,
            fallback_mode=False,
            anti_flood=None
        )
        mock_prepare.return_value = decision

        settings = MagicMock()
        settings.timeout_seconds = 300
        mock_settings.return_value = settings

        # User rejoins
        await handle_member_status_change(rejoin_event, session)

        # 🔒 CRITICAL SECURITY VERIFICATION: Captcha MUST be sent on rejoin
        mock_send_captcha.assert_called_once()

        # Verify captcha sent to correct user and chat
        call_kwargs = mock_send_captcha.call_args.kwargs
        assert call_kwargs['user'].id == user_id, "Captcha must be sent to correct user"
        assert call_kwargs['chat'].id == chat_id, "Captcha must be sent for correct chat"

        # Verify user was muted/restricted until captcha passes
        rejoin_event.bot.restrict_chat_member.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_leave_rejoin_cycles():
    """
    E2E TEST: Multiple leave/rejoin cycles.

    Ensures captcha is required on EVERY rejoin, not just the first.
    """
    user_id = 111222
    chat_id = -1001234567890

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Cycle 1
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id)
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    await handle_member_status_change(leave_event, session)
    flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag is None, "Cycle 1: Flag must be deleted"

    # Cycle 2
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")
    await handle_member_status_change(leave_event, session)
    flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag is None, "Cycle 2: Flag must be deleted"

    # Cycle 3
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")
    await handle_member_status_change(leave_event, session)
    flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag is None, "Cycle 3: Flag must be deleted"


@pytest.mark.asyncio
async def test_kicked_user_flag_deleted():
    """
    E2E TEST: User kicked by admin also requires captcha on rejoin.
    """
    user_id = 333444
    chat_id = -1001234567890

    # User has captcha_passed flag
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat_id}", 3600, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # Admin kicks user
    kick_event = MagicMock(spec=ChatMemberUpdated)
    kick_event.chat = MagicMock(spec=Chat, id=chat_id)
    kick_event.new_chat_member = MagicMock(spec=ChatMember)
    kick_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    kick_event.new_chat_member.status = ChatMemberStatus.KICKED
    kick_event.old_chat_member = MagicMock(spec=ChatMember)
    kick_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    await handle_member_status_change(kick_event, session)

    # Flag must be deleted even on kick
    flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat_id}")
    assert flag is None, "Flag must be deleted when user is kicked"


@pytest.mark.asyncio
async def test_different_users_independent_flags():
    """
    E2E TEST: Different users have independent captcha_passed flags.

    Ensures one user's leave doesn't affect another user's flag.
    """
    user1_id = 111
    user2_id = 222
    chat_id = -1001234567890

    # Both users have flags
    await redis_conn.redis.setex(f"captcha_passed:{user1_id}:{chat_id}", 3600, "1")
    await redis_conn.redis.setex(f"captcha_passed:{user2_id}:{chat_id}", 3600, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # User 1 leaves
    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat_id)
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user1_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    await handle_member_status_change(leave_event, session)

    # User 1 flag deleted, User 2 flag intact
    user1_flag = await redis_conn.redis.get(f"captcha_passed:{user1_id}:{chat_id}")
    user2_flag = await redis_conn.redis.get(f"captcha_passed:{user2_id}:{chat_id}")

    assert user1_flag is None, "User 1 flag must be deleted"
    assert user2_flag == "1", "User 2 flag must remain intact"


@pytest.mark.asyncio
async def test_same_user_different_groups_independent():
    """
    E2E TEST: Same user in different groups has independent flags.

    Ensures leaving one group doesn't affect captcha_passed flag in another group.
    """
    user_id = 555
    chat1_id = -1001111111111
    chat2_id = -1002222222222

    # User has flags in both groups
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat1_id}", 3600, "1")
    await redis_conn.redis.setex(f"captcha_passed:{user_id}:{chat2_id}", 3600, "1")

    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change

    # User leaves group 1
    leave_event = MagicMock(spec=ChatMemberUpdated)
    leave_event.chat = MagicMock(spec=Chat, id=chat1_id)
    leave_event.new_chat_member = MagicMock(spec=ChatMember)
    leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
    leave_event.new_chat_member.status = ChatMemberStatus.LEFT
    leave_event.old_chat_member = MagicMock(spec=ChatMember)
    leave_event.old_chat_member.status = ChatMemberStatus.MEMBER

    session = MagicMock()

    await handle_member_status_change(leave_event, session)

    # Group 1 flag deleted, Group 2 flag intact
    chat1_flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat1_id}")
    chat2_flag = await redis_conn.redis.get(f"captcha_passed:{user_id}:{chat2_id}")

    assert chat1_flag is None, "Chat 1 flag must be deleted"
    assert chat2_flag == "1", "Chat 2 flag must remain intact"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_rejoin_captcha_with_real_redis_and_db(
    db_session,
    redis_client_e2e,
    bot_mock
):
    """
    E2E TEST WITH REAL INFRASTRUCTURE: Test rejoin captcha fix with real Redis and PostgreSQL.
    
    This test verifies the fix where:
    - visual_captcha_enabled=True (set in CaptchaSettings)
    - captcha_join_enabled=False (in ChatSettings)
    - User rejoins → captcha MUST be sent
    
    Uses real Redis and PostgreSQL via docker-compose.test.yml.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from aiogram.types import ChatMemberUpdated, ChatMember, Chat, User as TgUser
    from aiogram.enums import ChatMemberStatus
    from sqlalchemy import select
    
    from bot.database.models import Group, ChatSettings, CaptchaSettings
    from bot.handlers.visual_captcha.visual_captcha_handler import handle_member_status_change
    from bot.services import redis_conn as redis_module
    
    # Patch redis to use real Redis client
    original_redis = redis_module.redis
    redis_module.redis = redis_client_e2e
    
    user_id = 999888
    chat_id = -1001234567890
    
    try:
        # Setup: Create user first (required for foreign key)
        from bot.database.models import User
        async with db_session.begin():
            user = User(
                user_id=123456,
                username="test_creator",
                first_name="Test",
                is_bot=False
            )
            db_session.add(user)
        await db_session.commit()
        
        # Setup: Create group and settings in real database
        async with db_session.begin():
            # Create group
            group = Group(
                chat_id=chat_id,
                title="E2E Test Group",
                creator_user_id=123456,
                added_by_user_id=123456
            )
            db_session.add(group)
            
            # Create ChatSettings with captcha_join_enabled=False (the bug scenario)
            chat_settings = ChatSettings(
                chat_id=chat_id,
                captcha_join_enabled=False,  # This is False - the bug
                captcha_invite_enabled=False,
                captcha_timeout_seconds=300
            )
            db_session.add(chat_settings)
            
            # Create CaptchaSettings with is_visual_enabled=True (user enabled via UI)
            captcha_settings = CaptchaSettings(
                group_id=chat_id,
                is_visual_enabled=True  # This is True - should trigger captcha
            )
            db_session.add(captcha_settings)
        
        await db_session.commit()
        
        # Setup: Set visual_captcha_enabled in Redis (as it would be in production)
        await redis_client_e2e.set(f"visual_captcha_enabled:{chat_id}", "1")
        
        # Step 1: User leaves (delete flag if exists)
        await redis_client_e2e.delete(f"captcha_passed:{user_id}:{chat_id}")
        
        leave_event = MagicMock(spec=ChatMemberUpdated)
        leave_event.chat = MagicMock(spec=Chat, id=chat_id, title="E2E Test Group")
        leave_event.new_chat_member = MagicMock(spec=ChatMember)
        leave_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id)
        leave_event.new_chat_member.status = ChatMemberStatus.LEFT
        leave_event.old_chat_member = MagicMock(spec=ChatMember)
        leave_event.old_chat_member.status = ChatMemberStatus.MEMBER
        
        await handle_member_status_change(leave_event, db_session)
        
        # Verify flag doesn't exist
        flag_after_leave = await redis_client_e2e.get(f"captcha_passed:{user_id}:{chat_id}")
        assert flag_after_leave is None, "Flag must not exist after leave"
        
        # Step 2: User rejoins
        join_event = MagicMock(spec=ChatMemberUpdated)
        join_event.chat = MagicMock(spec=Chat, id=chat_id, title="E2E Test Group")
        join_event.bot = bot_mock
        join_event.new_chat_member = MagicMock(spec=ChatMember)
        join_event.new_chat_member.user = MagicMock(spec=TgUser, id=user_id, username="e2e_test_user")
        join_event.new_chat_member.status = ChatMemberStatus.MEMBER
        join_event.old_chat_member = MagicMock(spec=ChatMember)
        join_event.old_chat_member.status = ChatMemberStatus.LEFT
        join_event.from_user = None  # Self-join
        
        with patch('bot.handlers.visual_captcha.visual_captcha_handler.classify_join_event') as mock_classify, \
             patch('bot.handlers.visual_captcha.visual_captcha_handler.send_captcha_prompt') as mock_send_captcha:
            
            from bot.services.event_classifier import JoinEventType
            
            mock_classify.return_value = JoinEventType.SELF_JOIN
            mock_send_captcha.return_value = None
            
            # Execute rejoin
            await handle_member_status_change(join_event, db_session)
            
            # CRITICAL VERIFICATION: send_captcha_prompt MUST be called
            # Even though captcha_join_enabled=False, visual_captcha_enabled=True
            # should trigger captcha (this is the fix)
            mock_send_captcha.assert_called_once()
            
            # Verify captcha was sent with correct parameters
            call_args = mock_send_captcha.call_args
            assert call_args.kwargs['user'].id == user_id
            assert call_args.kwargs['chat'].id == chat_id
            
            # Verify user was restricted
            bot_mock.restrict_chat_member.assert_called_once()
    
    finally:
        # Cleanup
        try:
            await redis_client_e2e.delete(f"captcha_passed:{user_id}:{chat_id}")
            await redis_client_e2e.delete(f"visual_captcha_enabled:{chat_id}")
        except Exception:
            pass  # Ignore Redis cleanup errors
        
        # Cleanup database
        try:
            from sqlalchemy import delete
            async with db_session.begin():
                await db_session.execute(delete(CaptchaSettings).where(CaptchaSettings.group_id == chat_id))
                await db_session.execute(delete(ChatSettings).where(ChatSettings.chat_id == chat_id))
                await db_session.execute(delete(Group).where(Group.chat_id == chat_id))
                await db_session.execute(delete(User).where(User.user_id == 123456))
            await db_session.commit()
        except Exception:
            await db_session.rollback()

        # Restore patched redis
        try:
            redis_module.redis = original_redis
        except Exception:
            pass
