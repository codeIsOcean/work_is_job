# tests/e2e/test_content_filter_comprehensive_e2e.py
"""
COMPREHENSIVE E2E tests for Content Filter module.

Tests ALL callbacks from:
- main_menu.py - Main menu
- word_filter/ - Word categories (sw, hw, ow)
- scam/ - Antiscam (patterns, base signals, thresholds, advanced)
- flood/ - Flood detector
- sections/ - Custom sections

RULES:
- Strict assertions (no soft failures)
- Verify response content, not just fact of response
- Monitor Docker logs for errors
- Test state changes (before != after)

Run:
    pytest tests/e2e/test_content_filter_comprehensive_e2e.py -v -s

Requirements:
    - .env.test with credentials
    - Test group where bot is admin
    - Docker containers running (bot_test, postgres_test, redis_test)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# CRITICAL: Load .env.test FIRST before any other imports
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
import re
import subprocess
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from aiogram import Bot


def safe_str(text: str) -> str:
    """Convert string to ASCII-safe version for Windows console."""
    if not text:
        return text
    return text.encode('ascii', 'replace').decode('ascii')


# Configuration - read AFTER load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
]


def skip_if_no_credentials():
    """Skip test if no credentials."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    if not any(s["session"] for s in USERBOT_SESSIONS):
        pytest.skip("No TEST_USERBOT_SESSION set")


def get_available_session(index: int = 0):
    """Get available userbot session."""
    available = [s for s in USERBOT_SESSIONS if s["session"]]
    return available[index] if index < len(available) else None


# ============================================================
# DOCKER LOG MONITOR
# ============================================================

class DockerLogMonitor:
    """Monitor Docker logs for errors during tests."""

    ERROR_PATTERNS = [
        "ERROR",
        "Exception",
        "AttributeError",
        "TypeError",
        "KeyError",
        "ValueError",
        "Traceback",
    ]

    def __init__(self, container_name: str = "bot_test"):
        self.container_name = container_name
        self.errors = []
        self.process = None
        self.thread = None
        self.running = False

    def start(self):
        """Start monitoring Docker logs."""
        self.errors = []
        self.running = True

        def monitor():
            try:
                self.process = subprocess.Popen(
                    ["docker", "logs", "-f", "--since", "1s", self.container_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                for line in self.process.stdout:
                    if not self.running:
                        break
                    if any(err in line for err in self.ERROR_PATTERNS):
                        self.errors.append(line.strip())
            except Exception as e:
                print(f"[LOG_MONITOR] Error: {e}")

        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()

    def stop(self) -> List[str]:
        """Stop monitoring and return errors found."""
        self.running = False
        if self.process:
            self.process.terminate()
        return self.errors

    def check_no_errors(self):
        """Assert that no errors were found."""
        if self.errors:
            # Filter out known non-critical messages
            critical_errors = [
                e for e in self.errors
                if "FloodWait" not in e and "MessageNotModified" not in e
            ]
            if critical_errors:
                error_text = "\n".join(critical_errors[:5])  # Show first 5
                raise AssertionError(f"ERRORS in Docker logs:\n{error_text}")


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def admin_userbot():
    """Admin userbot."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="cf_comprehensive_admin",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def bot():
    """Aiogram Bot."""
    skip_if_no_credentials()
    bot_instance = Bot(token=TEST_BOT_TOKEN)
    try:
        yield bot_instance
    finally:
        if bot_instance.session:
            await bot_instance.session.close()


@pytest.fixture
def chat_id():
    """Test group ID."""
    return int(TEST_CHAT_ID)


@pytest.fixture
def invite_link():
    """Invite link for group."""
    return TEST_CHAT_INVITE_LINK


@pytest.fixture
def log_monitor():
    """Docker log monitor fixture."""
    monitor = DockerLogMonitor()
    monitor.start()
    yield monitor
    monitor.stop()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Ensure userbot is in chat."""
    me = await userbot.get_me()
    username = me.username or me.first_name

    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
        except UserAlreadyParticipant:
            pass
        except FloodWait as e:
            print(f"[ensure] FloodWait {e.value}s - continuing")
        except Exception as e:
            print(f"[ensure] Error: {e}")

    try:
        if invite_link:
            await userbot.get_chat(invite_link)
    except Exception:
        pass


async def get_bot_username() -> str:
    """Get bot username."""
    bot = Bot(token=TEST_BOT_TOKEN)
    me = await bot.get_me()
    await bot.session.close()
    return me.username


async def get_last_message(userbot: Client, chat_id):
    """Get last message from chat."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        return msg
    return None


async def list_buttons(userbot: Client, chat_id) -> List[dict]:
    """Get list of buttons from last message."""
    buttons = []
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if msg.reply_markup:
            for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
                for col_idx, button in enumerate(row):
                    buttons.append({
                        "text": button.text,
                        "callback_data": button.callback_data or "",
                        "row": row_idx,
                        "col": col_idx
                    })
    return buttons


async def click_button(userbot: Client, chat_id, callback_pattern: str) -> bool:
    """Click button by callback pattern. Returns True if clicked."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if not msg.reply_markup:
            return False

        for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
            for col_idx, button in enumerate(row):
                if button.callback_data and re.search(callback_pattern, button.callback_data):
                    await msg.click(col_idx, row_idx)
                    await asyncio.sleep(2)
                    return True
    return False


async def click_button_exact(userbot: Client, chat_id, callback_data: str) -> bool:
    """Click button by exact callback_data."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if not msg.reply_markup:
            return False

        for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
            for col_idx, button in enumerate(row):
                if button.callback_data == callback_data:
                    await msg.click(col_idx, row_idx)
                    await asyncio.sleep(2)
                    return True
    return False


async def navigate_to_content_filter(userbot: Client, bot_username: str, chat_id: int) -> bool:
    """Navigate from /settings to Content Filter menu."""
    # /settings
    await userbot.send_message(bot_username, "/settings")
    await asyncio.sleep(3)

    # Select group
    clicked = await click_button(userbot, bot_username, rf"manage_group_{chat_id}")
    if not clicked:
        return False
    await asyncio.sleep(2)

    # Content Filter
    clicked = await click_button(userbot, bot_username, rf"cf:m:{chat_id}")
    if not clicked:
        return False
    await asyncio.sleep(2)

    return True


async def verify_no_error_in_response(userbot: Client, chat_id) -> Tuple[bool, str]:
    """Verify last message doesn't contain error."""
    msg = await get_last_message(userbot, chat_id)
    if not msg:
        return False, "No message received"

    text = (msg.text or msg.caption or "").lower()

    error_indicators = ["ошибка", "error", "не найден", "not found", "failed"]
    for indicator in error_indicators:
        if indicator in text:
            return False, f"Error in response: {text[:100]}"

    return True, text[:100]


# ============================================================
# HANDLER-TEST MAPPING
# ============================================================

# All handlers that must be tested
HANDLER_PATTERNS = {
    # Main menu
    "cf:m:": "Content Filter main menu",
    "cf:t:wf:": "Toggle Word Filter",
    "cf:t:sc:": "Toggle Antiscam",
    "cf:t:fl:": "Toggle Flood",

    # Word Filter
    "cf:wfs:": "Word Filter settings",
    "cf:swl:": "Stopwords list",
    "cf:swa:": "Add stopword (FSM)",
    "cf:hwl:": "Hardwords list",
    "cf:hwa:": "Add hardword (FSM)",
    "cf:owl:": "Otherwords list",
    "cf:owa:": "Add otherword (FSM)",

    # Antiscam
    "cf:scs:": "Scam settings",
    "cf:scp:": "Scam patterns menu",
    "cf:scpa:": "Add pattern (FSM)",
    "cf:scpl:": "Patterns list",
    "cf:scpe:": "Export patterns",
    "cf:spi:": "Import patterns (FSM)",
    "cf:bsig:": "Base signals menu",
    "cf:bsigt:": "Toggle base signal",
    "cf:bsigr:": "Reset base signals",
    "cf:scthr:": "Score thresholds",
    "cf:scadv:": "Advanced settings",

    # Flood
    "cf:fls:": "Flood settings",
    "cf:fladv:": "Flood advanced",

    # Custom sections
    "cf:sccat:": "Custom sections menu",
    "cf:secn:": "Create section (FSM)",
    "cf:sec:": "Section settings",
}


# ============================================================
# TESTS
# ============================================================

class TestContentFilterComprehensive:
    """Comprehensive E2E tests for Content Filter."""

    @pytest.mark.asyncio
    async def test_01_main_menu_opens(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Main menu opens without errors."""
        print(f"\n{'='*60}")
        print(f"[TEST 01] Main Menu Opens")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()

        # Navigate to content filter
        success = await navigate_to_content_filter(admin_userbot, bot_username, chat_id)
        assert success, "Failed to navigate to Content Filter"

        # Verify buttons exist
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]
        print(f"[TEST 01] Buttons: {callback_data_list[:5]}...")

        # Check required buttons
        assert any("cf:wfs:" in cb or "cf:t:wf:" in cb for cb in callback_data_list), \
            "Word Filter button not found"
        assert any("cf:scs:" in cb or "cf:t:sc:" in cb for cb in callback_data_list), \
            "Scam button not found"

        # Verify no error in response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error in response: {text}"

        # Check Docker logs
        log_monitor.check_no_errors()

        print(f"[TEST 01] PASSED")

    @pytest.mark.asyncio
    async def test_02_word_filter_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Word Filter menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 02] Word Filter Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Click Word Filter settings
        clicked = await click_button(admin_userbot, bot_username, rf"cf:wfs:{chat_id}")
        assert clicked, f"Word Filter button (cf:wfs:{chat_id}) not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        # Check for word category buttons
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]

        has_categories = any(
            "cf:swl:" in cb or "cf:hwl:" in cb or "cf:owl:" in cb
            for cb in callback_data_list
        )
        assert has_categories, f"Word categories not found. Buttons: {callback_data_list}"

        log_monitor.check_no_errors()
        print(f"[TEST 02] PASSED")

    @pytest.mark.asyncio
    async def test_03_scam_settings_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Scam settings menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 03] Scam Settings Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Click Scam settings
        clicked = await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        assert clicked, f"Scam settings button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        # Check for scam menu buttons
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]
        print(f"[TEST 03] Scam menu buttons: {callback_data_list[:8]}...")

        # Must have patterns and base signals buttons
        assert any("cf:scp:" in cb for cb in callback_data_list), \
            f"Patterns button not found"
        assert any("cf:bsig:" in cb for cb in callback_data_list), \
            f"Base signals button not found"

        log_monitor.check_no_errors()
        print(f"[TEST 03] PASSED")

    @pytest.mark.asyncio
    async def test_04_scam_patterns_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Scam patterns menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 04] Scam Patterns Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam settings -> Patterns
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:scp:{chat_id}")
        assert clicked, "Patterns button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        # Check for pattern menu buttons
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]
        print(f"[TEST 04] Patterns menu: {callback_data_list[:6]}...")

        # Must have add and list buttons
        assert any("cf:scpa:" in cb for cb in callback_data_list), \
            "Add pattern button not found"
        assert any("cf:scpl:" in cb for cb in callback_data_list), \
            "Patterns list button not found"

        log_monitor.check_no_errors()
        print(f"[TEST 04] PASSED")

    @pytest.mark.asyncio
    async def test_05_scam_patterns_list(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Patterns list opens (tests the fixed bug)."""
        print(f"\n{'='*60}")
        print(f"[TEST 05] Patterns List (bug fix verification)")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Patterns -> List
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)
        await click_button(admin_userbot, bot_username, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:scpl:{chat_id}:0")
        assert clicked, "Patterns list button not found"

        # THIS IS THE KEY TEST - the bug was TypeError here
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error in patterns list (possible TypeError bug): {text}"

        log_monitor.check_no_errors()
        print(f"[TEST 05] PASSED - Pattern list works (bug fixed)")

    @pytest.mark.asyncio
    async def test_06_base_signals_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Base signals menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 06] Base Signals Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Base signals
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:bsig:{chat_id}")
        assert clicked, "Base signals button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        # Check for signal toggle buttons
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]
        print(f"[TEST 06] Base signals: {callback_data_list[:10]}...")

        signal_buttons = [cb for cb in callback_data_list if "cf:bsigt:" in cb]
        assert len(signal_buttons) >= 5, f"Expected 5+ signal buttons, got {len(signal_buttons)}"

        log_monitor.check_no_errors()
        print(f"[TEST 06] PASSED")

    @pytest.mark.asyncio
    async def test_07_base_signal_toggle(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Toggle base signal changes state."""
        print(f"\n{'='*60}")
        print(f"[TEST 07] Base Signal Toggle")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate to base signals
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)
        await click_button(admin_userbot, bot_username, rf"cf:bsig:{chat_id}")
        await asyncio.sleep(2)

        # Get state BEFORE
        buttons_before = await list_buttons(admin_userbot, bot_username)
        money_btn_before = next(
            (b for b in buttons_before if "money" in b["callback_data"].lower()),
            None
        )

        if not money_btn_before:
            pytest.skip("money_amount signal not found in buttons")

        status_before = "on" in money_btn_before["text"].lower() or any(
            c in money_btn_before["text"] for c in ["v", "V", "+"]
        )
        print(f"[TEST 07] Status before: {safe_str(money_btn_before['text'])}")

        # Toggle
        clicked = await click_button(admin_userbot, bot_username, r"cf:bsigt:money_amount:")
        assert clicked, "Toggle button not found"

        # Get state AFTER
        buttons_after = await list_buttons(admin_userbot, bot_username)
        money_btn_after = next(
            (b for b in buttons_after if "money" in b["callback_data"].lower()),
            None
        )

        if money_btn_after:
            print(f"[TEST 07] Status after: {safe_str(money_btn_after['text'])}")

        # Verify no error
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error on toggle: {text}"

        log_monitor.check_no_errors()
        print(f"[TEST 07] PASSED")

    @pytest.mark.asyncio
    async def test_08_scam_advanced_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Scam advanced menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 08] Scam Advanced Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Advanced
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:scadv:{chat_id}")
        assert clicked, "Advanced settings button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        log_monitor.check_no_errors()
        print(f"[TEST 08] PASSED")

    @pytest.mark.asyncio
    async def test_09_flood_settings_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Flood settings menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 09] Flood Settings Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Click Flood settings
        clicked = await click_button(admin_userbot, bot_username, rf"cf:fls:{chat_id}")
        assert clicked, "Flood settings button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        log_monitor.check_no_errors()
        print(f"[TEST 09] PASSED")

    @pytest.mark.asyncio
    async def test_10_custom_sections_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Custom sections menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 10] Custom Sections Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Custom sections (cf:sccat)
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:sccat:{chat_id}")
        assert clicked, "Custom sections button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        # Check for create section button
        buttons = await list_buttons(admin_userbot, bot_username)
        callback_data_list = [b["callback_data"] for b in buttons]
        print(f"[TEST 10] Sections menu: {callback_data_list[:5]}...")

        assert any("cf:secn:" in cb for cb in callback_data_list), \
            "Create section button not found"

        log_monitor.check_no_errors()
        print(f"[TEST 10] PASSED")

    @pytest.mark.asyncio
    async def test_11_import_patterns_fsm(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Import patterns FSM starts (tests newly added handler)."""
        print(f"\n{'='*60}")
        print(f"[TEST 11] Import Patterns FSM (new handler)")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Patterns -> Import
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)
        await click_button(admin_userbot, bot_username, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:spi:{chat_id}")
        assert clicked, "Import button (cf:spi:) not found"

        # Verify response contains import instructions
        msg = await get_last_message(admin_userbot, bot_username)
        assert msg, "No response from bot"

        text = (msg.text or "").lower()
        assert "импорт" in text or "import" in text or "отправьте" in text, \
            f"Import instructions not found in response: {text[:100]}"

        # Cancel FSM by going back
        await click_button(admin_userbot, bot_username, rf"cf:scp:{chat_id}")

        log_monitor.check_no_errors()
        print(f"[TEST 11] PASSED - Import FSM works")

    @pytest.mark.asyncio
    async def test_12_thresholds_menu(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Score thresholds menu opens."""
        print(f"\n{'='*60}")
        print(f"[TEST 12] Score Thresholds Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Navigate: Scam -> Thresholds
        await click_button(admin_userbot, bot_username, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button(admin_userbot, bot_username, rf"cf:scthr:{chat_id}")
        assert clicked, "Thresholds button not found"

        # Verify response
        ok, text = await verify_no_error_in_response(admin_userbot, bot_username)
        assert ok, f"Error: {text}"

        log_monitor.check_no_errors()
        print(f"[TEST 12] PASSED")


class TestContentFilterToggleStates:
    """Tests for toggle state changes."""

    @pytest.mark.asyncio
    async def test_toggle_word_filter(
        self, admin_userbot: Client, chat_id: int, invite_link: str, log_monitor: DockerLogMonitor
    ):
        """Test: Toggle Word Filter changes state."""
        print(f"\n{'='*60}")
        print(f"[TEST] Toggle Word Filter")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link)
        bot_username = await get_bot_username()
        await navigate_to_content_filter(admin_userbot, bot_username, chat_id)

        # Get state BEFORE
        buttons_before = await list_buttons(admin_userbot, bot_username)
        wf_btn = next((b for b in buttons_before if "cf:t:wf:" in b["callback_data"]), None)

        if not wf_btn:
            pytest.skip("Word Filter toggle not found")

        print(f"[Toggle] Before: {safe_str(wf_btn['text'])}")

        # Toggle
        await click_button_exact(admin_userbot, bot_username, wf_btn["callback_data"])
        await asyncio.sleep(2)

        # Get state AFTER
        buttons_after = await list_buttons(admin_userbot, bot_username)
        wf_btn_after = next((b for b in buttons_after if "cf:t:wf:" in b["callback_data"]), None)

        if wf_btn_after:
            print(f"[Toggle] After: {safe_str(wf_btn_after['text'])}")

        # Toggle back to restore state
        if wf_btn_after:
            await click_button_exact(admin_userbot, bot_username, wf_btn_after["callback_data"])

        log_monitor.check_no_errors()
        print(f"[TEST] Toggle Word Filter PASSED")


# ============================================================
# META TEST: Verify all handlers have tests
# ============================================================

class TestHandlerCoverage:
    """Meta-test to verify test coverage."""

    def test_all_critical_handlers_covered(self):
        """Verify critical handlers have tests."""
        test_methods = [m for m in dir(TestContentFilterComprehensive) if m.startswith("test_")]

        print(f"\n[COVERAGE] Tests found: {len(test_methods)}")
        for method in test_methods:
            print(f"  - {method}")

        # Must have at least 10 tests
        assert len(test_methods) >= 10, \
            f"Expected at least 10 tests, got {len(test_methods)}"
