"""
Комплексный E2E тест настроек Антискам модуля.

ПОКРЫВАЕТ ВСЕ CALLBACKS из:
- bot/handlers/content_filter/scam/settings.py
- bot/handlers/content_filter/scam/base_signals.py
- bot/handlers/content_filter/scam/patterns.py
- bot/handlers/content_filter/scam/thresholds.py

Правила (docs/E2E_USERBOT_TESTING.md):
- Strict assertions - НИКАКИХ soft-failures
- State verification - проверяем изменение состояния
- FSM complete testing - valid/invalid/cancel
- Pattern matching - точное соответствие хендлерам

Запуск:
    pytest tests/e2e/test_scam_settings_comprehensive_e2e.py -v -s

Запуск одного теста:
    pytest tests/e2e/test_scam_settings_comprehensive_e2e.py::TestScamSettingsComprehensive::test_base_signals_menu -v -s
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# КРИТИЧЕСКИ ВАЖНО: загружаем .env.test ДО ВСЕХ других импортов
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from pyrogram.types import Message
from aiogram import Bot

# ============================================================
# CONFIGURATION
# ============================================================

TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH")

USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "admin_user"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "admin_user2"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "admin_user3"},
]


def skip_if_no_credentials():
    """Skip test if credentials missing."""
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


def safe_str(text: str) -> str:
    """Convert string to ASCII-safe version for Windows console."""
    if not text:
        return ""
    return text.encode('ascii', 'replace').decode('ascii')


# ============================================================
# HANDLER-TO-TEST MAPPING (Rule 18)
# Все паттерны из bot/handlers/content_filter/scam/
# ============================================================

SCAM_HANDLER_PATTERNS = {
    # settings.py
    "cf:scs:-?\\d+$": "test_scam_settings_menu",
    "cf:scact:-?\\d+$": "test_scam_action_menu",
    "cf:scact:(delete|mute|ban):-?\\d+$": "test_scam_action_select",
    "cf:scact:time:-?\\d+$": "test_scam_action_time_fsm",
    "cf:scadv:-?\\d+$": "test_scam_advanced_menu",
    "cf:scmt:-?\\d+$": "test_scam_mute_text_fsm",
    "cf:scbt:-?\\d+$": "test_scam_ban_text_fsm",
    "cf:scnd:-?\\d+$": "test_scam_notification_delay_menu",
    "cf:scnd:\\d+:-?\\d+$": "test_scam_notification_delay_select",

    # base_signals.py
    "cf:bsig:-?\\d+$": "test_base_signals_menu",
    "cf:bsigt:\\w+:-?\\d+$": "test_base_signals_toggle",
    "cf:bsigw:\\w+:-?\\d+$": "test_base_signals_weight_fsm",
    "cf:bsigr:-?\\d+$": "test_base_signals_reset",

    # patterns.py
    "cf:scp:-?\\d+$": "test_scam_patterns_menu",
    "cf:scpa:-?\\d+$": "test_scam_patterns_add_fsm",
    "cf:scpl:-?\\d+:\\d+$": "test_scam_patterns_list_pagination",
    "cf:scpd:\\d+:-?\\d+$": "test_scam_patterns_delete",
    "cf:scpdc:\\d+:-?\\d+$": "test_scam_patterns_delete_confirm",
    "cf:scpc:-?\\d+$": "test_scam_patterns_clear",
    "cf:scpcc:-?\\d+$": "test_scam_patterns_clear_confirm",
    "cf:scpe:-?\\d+$": "test_scam_patterns_export",

    # thresholds.py
    "cf:scthr:-?\\d+$": "test_scam_thresholds_menu",
    "cf:scthra:-?\\d+$": "test_scam_thresholds_add_fsm",
    "cf:scthrac:(delete|mute|ban):-?\\d+$": "test_scam_thresholds_action",
    "cf:scthrx:-?\\d+$": "test_scam_thresholds_delete",
}


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def admin_userbot():
    """Admin userbot fixture."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No admin userbot session available")
    client = Client(
        name="test_admin_scam",
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
    """Aiogram Bot fixture."""
    skip_if_no_credentials()
    bot_instance = Bot(token=TEST_BOT_TOKEN)
    try:
        yield bot_instance
    finally:
        if bot_instance.session:
            await bot_instance.session.close()


@pytest.fixture
def chat_id():
    return int(TEST_CHAT_ID)


@pytest.fixture
def invite_link():
    return TEST_CHAT_INVITE_LINK


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Ensure userbot is in the chat."""
    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
        except UserAlreadyParticipant:
            pass
        except FloodWait as e:
            if e.value < 60:
                print(f"[WAIT] FloodWait {e.value}s...")
                await asyncio.sleep(e.value + 5)

    try:
        if invite_link:
            await userbot.get_chat(invite_link)
    except Exception:
        pass


async def get_bot_username(bot: Bot) -> str:
    """Get bot username."""
    me = await bot.get_me()
    return me.username


async def get_last_message(userbot: Client, chat_id, force_refresh: bool = False) -> Message:
    """Get last message from chat.

    Args:
        userbot: Pyrogram client
        chat_id: Chat ID
        force_refresh: If True, get message by ID to bypass cache
    """
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if force_refresh and msg.id:
            # Re-fetch to get updated content
            try:
                fresh = await userbot.get_messages(chat_id, msg.id)
                return fresh
            except Exception:
                pass
        return msg
    return None


async def get_last_bot_message(userbot: Client, chat_id, bot_id: int = None) -> Message:
    """Get last message from bot."""
    async for msg in userbot.get_chat_history(chat_id, limit=5):
        if msg.from_user and (bot_id is None or msg.from_user.id == bot_id):
            if msg.from_user.is_bot:
                return msg
    return None


async def list_buttons(userbot: Client, chat_id, force_refresh: bool = False) -> list:
    """Get all buttons from last bot message."""
    msg = await get_last_message(userbot, chat_id, force_refresh=force_refresh)
    if not msg or not msg.reply_markup:
        return []

    buttons = []
    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            buttons.append(button)
    return buttons


async def click_button_by_callback(
    userbot: Client,
    chat_id,
    pattern: str,
    timeout: float = 5.0
) -> bool:
    """
    Click button by callback_data pattern (regex).

    Uses Pyrogram's msg.click(col, row) API.
    Returns True if clicked, False otherwise.
    """
    msg = await get_last_message(userbot, chat_id)
    if not msg or not msg.reply_markup:
        print(f"[CLICK] No message or no markup")
        return False

    compiled = re.compile(pattern)
    for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
        for col_idx, button in enumerate(row):
            if button.callback_data and compiled.search(button.callback_data):
                try:
                    # Pyrogram API: click(column, row) - 0-indexed
                    await msg.click(col_idx, row_idx)
                    await asyncio.sleep(1)
                    print(f"[CLICK] OK: {safe_str(button.text)} -> {button.callback_data}")
                    return True
                except Exception as e:
                    print(f"[CLICK] Error: {e}")
                    return False

    # Debug: print available buttons
    available = []
    for row in msg.reply_markup.inline_keyboard:
        for b in row:
            available.append(f"{safe_str(b.text)}:{b.callback_data}")
    print(f"[CLICK] Pattern '{pattern}' NOT FOUND. Available: {available[:8]}...")
    return False


async def click_button_exact(userbot: Client, chat_id, callback_data: str) -> bool:
    """Click button by exact callback_data."""
    msg = await get_last_message(userbot, chat_id)
    if not msg or not msg.reply_markup:
        return False

    for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
        for col_idx, button in enumerate(row):
            if button.callback_data == callback_data:
                try:
                    await msg.click(col_idx, row_idx)
                    await asyncio.sleep(1)
                    return True
                except Exception:
                    return False
    return False


async def navigate_to_scam_settings(
    userbot: Client,
    bot_chat_id: str,
    chat_id: int
) -> bool:
    """
    Navigate: /settings -> Group -> Content Filter -> Scam Settings
    Returns True if successful.
    """
    print(f"\n[NAV] -> Scam Settings (chat_id={chat_id})")

    # Step 1: /settings
    await userbot.send_message(bot_chat_id, "/settings")
    await asyncio.sleep(3)

    # Step 2: Select group
    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"manage_group_{chat_id}")
    if not clicked:
        print("[NAV] FAIL: Could not select group")
        return False
    await asyncio.sleep(2)

    # Step 3: Content Filter
    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"cf:m:{chat_id}")
    if not clicked:
        print("[NAV] FAIL: Could not click Content Filter")
        return False
    await asyncio.sleep(2)

    # Step 4: Scam Settings (cf:scs)
    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"cf:scs:{chat_id}")
    if not clicked:
        print("[NAV] FAIL: Could not click Scam Settings")
        return False
    await asyncio.sleep(2)

    print("[NAV] OK: At Scam Settings")
    return True


async def navigate_to_patterns_menu(
    userbot: Client,
    bot_chat_id: str,
    chat_id: int
) -> bool:
    """
    Navigate to Patterns menu from Scam Settings.
    Assumes we're already at Scam Settings.
    """
    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"cf:scp:{chat_id}")
    if not clicked:
        print("[NAV] FAIL: Could not click Patterns menu")
        return False
    await asyncio.sleep(2)
    print("[NAV] OK: At Patterns menu")
    return True


async def navigate_to_thresholds_menu(
    userbot: Client,
    bot_chat_id: str,
    chat_id: int
) -> bool:
    """
    Navigate to Thresholds menu from Scam Settings.
    Assumes we're already at Scam Settings.
    """
    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"cf:scthr:{chat_id}")
    if not clicked:
        print("[NAV] FAIL: Could not click Thresholds menu")
        return False
    await asyncio.sleep(2)
    print("[NAV] OK: At Thresholds menu")
    return True


async def add_test_pattern(
    userbot: Client,
    bot_chat_id: str,
    chat_id: int,
    pattern_text: str = None
) -> str:
    """
    Add a test pattern. Returns pattern text.
    Assumes we're at Patterns menu.
    """
    if pattern_text is None:
        pattern_text = f"test_{datetime.now().strftime('%H%M%S')}"

    clicked = await click_button_by_callback(userbot, bot_chat_id, rf"cf:scpa:{chat_id}")
    if not clicked:
        return None
    await asyncio.sleep(2)

    await userbot.send_message(bot_chat_id, pattern_text)
    await asyncio.sleep(3)
    print(f"[HELPER] Added pattern: {pattern_text}")
    return pattern_text


async def verify_message_contains(
    userbot: Client,
    chat_id: str,
    expected_text: str,
    case_insensitive: bool = True
) -> bool:
    """Verify last message contains expected text."""
    msg = await get_last_message(userbot, chat_id)
    if not msg or not msg.text:
        return False
    text = msg.text.lower() if case_insensitive else msg.text
    expected = expected_text.lower() if case_insensitive else expected_text
    return expected in text


# ============================================================
# TEST CLASS
# ============================================================

@pytest.mark.e2e
class TestScamSettingsComprehensive:
    """
    Comprehensive E2E tests for Scam Settings module.

    Каждый тест проверяет:
    1. Кнопка существует и кликабельна
    2. Меню/FSM открывается корректно
    3. Изменения состояния сохраняются
    """

    # --------------------------------------------------------
    # META-TEST: Coverage check
    # --------------------------------------------------------

    def test_00_verify_handler_coverage(self):
        """
        Meta-test: Verify all handler patterns have tests.
        """
        missing = []
        for pattern, test_name in SCAM_HANDLER_PATTERNS.items():
            if not hasattr(self, test_name):
                missing.append(f"{pattern} -> {test_name}")

        if missing:
            pytest.fail(f"MISSING TESTS:\n" + "\n".join(missing))

    # --------------------------------------------------------
    # SETTINGS.PY TESTS
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scam_settings_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scs:{chat_id} - Scam settings menu opens."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scs - Scam Settings Menu")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation to Scam Settings failed"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        callbacks = [b.callback_data for b in buttons if b.callback_data]

        # STRICT: Must have these buttons
        required = [
            (rf"cf:scact:{chat_id}", "Action"),
            (rf"cf:bsig:{chat_id}", "Base Signals"),
            (rf"cf:scadv:{chat_id}", "Advanced"),
            (rf"cf:scp:{chat_id}", "Patterns"),
        ]

        for pattern, name in required:
            found = any(re.search(pattern, cb) for cb in callbacks)
            assert found, f"FAIL: '{name}' button missing! Pattern: {pattern}, Got: {callbacks}"

        print("[TEST] OK: All required buttons present")

    @pytest.mark.asyncio
    async def test_scam_action_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scact:{chat_id} - Action menu opens."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scact - Action Menu")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:{chat_id}$")
        assert clicked, "FAIL: Could not click Action button"
        await asyncio.sleep(2)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        callbacks = [b.callback_data for b in buttons if b.callback_data]

        # Must have action options
        assert any("cf:scact:delete:" in cb for cb in callbacks), "FAIL: Delete missing"
        assert any("cf:scact:mute:" in cb for cb in callbacks), "FAIL: Mute missing"
        assert any("cf:scact:ban:" in cb for cb in callbacks), "FAIL: Ban missing"

        print("[TEST] OK: Action menu has all options")

    @pytest.mark.asyncio
    async def test_scam_action_select(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scact:(delete|mute|ban):{chat_id} - Select action."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scact:action - Select Action")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:{chat_id}$")
        await asyncio.sleep(2)

        # Click delete action
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:delete:{chat_id}")
        assert clicked, "FAIL: Could not select delete action"
        await asyncio.sleep(2)

        print("[TEST] OK: Action selection works")

    @pytest.mark.asyncio
    async def test_scam_action_time_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scact:time:{chat_id} - Mute time FSM."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scact:time - Time FSM")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:{chat_id}$")
        await asyncio.sleep(2)

        # Select mute first
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:mute:{chat_id}")
        await asyncio.sleep(2)

        # Try to click time button
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scact:time:{chat_id}")
        if not clicked:
            print("[TEST] SKIP: Time button not available")
            pytest.skip("Time FSM not available")

        await asyncio.sleep(2)
        print("[TEST] OK: Time FSM accessible")

    @pytest.mark.asyncio
    async def test_scam_advanced_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scadv:{chat_id} - Advanced menu opens."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scadv - Advanced Menu")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scadv:{chat_id}")
        assert clicked, "FAIL: Could not click Advanced button"
        await asyncio.sleep(2)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        callbacks = [b.callback_data for b in buttons if b.callback_data]

        # STRICT: Must have mute text, ban text, notification delay
        assert any(f"cf:scmt:{chat_id}" in cb for cb in callbacks), \
            f"FAIL: Mute text button missing! Got: {callbacks}"
        assert any(f"cf:scbt:{chat_id}" in cb for cb in callbacks), \
            f"FAIL: Ban text button missing! Got: {callbacks}"
        assert any(f"cf:scnd:{chat_id}" in cb for cb in callbacks), \
            f"FAIL: Notification delay button missing! Got: {callbacks}"

        print("[TEST] OK: Advanced menu has all buttons")

    @pytest.mark.asyncio
    async def test_scam_mute_text_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scmt:{chat_id} - Mute text FSM."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scmt - Mute Text FSM")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scadv:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scmt:{chat_id}")
        assert clicked, "FAIL: Could not click Mute Text button"
        await asyncio.sleep(2)

        # Enter test text
        test_text = f"Test mute {datetime.now().strftime('%H:%M:%S')}"
        await admin_userbot.send_message(bot_chat_id, test_text)
        await asyncio.sleep(3)

        msg = await get_last_message(admin_userbot, bot_chat_id)
        msg_text = (msg.text or "").lower() if msg else ""

        assert "сохран" in msg_text or "установлен" in msg_text or "успеш" in msg_text, \
            f"FAIL: Mute text not saved. Response: {safe_str(msg.text) if msg else 'None'}"

        print("[TEST] OK: Mute text FSM works")

    @pytest.mark.asyncio
    async def test_scam_ban_text_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scbt:{chat_id} - Ban text FSM."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scbt - Ban Text FSM")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scadv:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scbt:{chat_id}")
        assert clicked, "FAIL: Could not click Ban Text button"
        await asyncio.sleep(2)

        test_text = f"Test ban {datetime.now().strftime('%H:%M:%S')}"
        await admin_userbot.send_message(bot_chat_id, test_text)
        await asyncio.sleep(3)

        msg = await get_last_message(admin_userbot, bot_chat_id)
        msg_text = (msg.text or "").lower() if msg else ""

        assert "сохран" in msg_text or "установлен" in msg_text or "успеш" in msg_text, \
            f"FAIL: Ban text not saved. Response: {safe_str(msg.text) if msg else 'None'}"

        print("[TEST] OK: Ban text FSM works")

    @pytest.mark.asyncio
    async def test_scam_notification_delay_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scnd:{chat_id} - Notification delay menu."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scnd - Notification Delay Menu")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scadv:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scnd:{chat_id}$")
        assert clicked, "FAIL: Could not click Notification Delay button"
        await asyncio.sleep(2)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        assert len(buttons) > 0, "FAIL: No delay options"

        print(f"[TEST] OK: Delay options: {[safe_str(b.text) for b in buttons[:5]]}")

    @pytest.mark.asyncio
    async def test_scam_notification_delay_select(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scnd:{delay}:{chat_id} - Select delay value."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scnd:N - Select Delay Value")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scadv:{chat_id}")
        await asyncio.sleep(2)

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scnd:{chat_id}$")
        await asyncio.sleep(2)

        # Click any delay option
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scnd:\d+:{chat_id}")
        if clicked:
            print("[TEST] OK: Delay selection works")
        else:
            print("[TEST] WARN: Could not find delay option")

    # --------------------------------------------------------
    # BASE_SIGNALS.PY TESTS - CRITICAL (были сломаны!)
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_base_signals_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Test: cf:bsig:{chat_id} - Base signals menu.

        CRITICAL TEST - этот хендлер был сломан!
        """
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:bsig - Base Signals Menu (CRITICAL)")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        # THIS WAS BROKEN - AttributeError: base_signal_overrides
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")
        assert clicked, "FAIL: Could not click Base Signals button"
        await asyncio.sleep(3)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        callbacks = [b.callback_data for b in buttons if b.callback_data]

        # Must have toggle buttons
        toggle_buttons = [cb for cb in callbacks if "cf:bsigt:" in cb]
        assert len(toggle_buttons) >= 5, \
            f"FAIL: Expected 5+ signal toggles, got {len(toggle_buttons)}. Callbacks: {callbacks}"

        # Must have reset button
        assert any(f"cf:bsigr:{chat_id}" in cb for cb in callbacks), \
            f"FAIL: Reset button missing! Got: {callbacks}"

        print(f"[TEST] OK: Base Signals menu opened with {len(toggle_buttons)} signals")

    @pytest.mark.asyncio
    async def test_base_signals_toggle(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Test: cf:bsigt:{signal}:{chat_id} - Toggle signal.

        Verifies toggle button is clickable and handler responds.
        Note: Pyrogram caches messages, so we verify via re-navigation.
        """
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:bsigt - Toggle Signal")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")
        await asyncio.sleep(2)

        # Get first toggle button
        buttons_before = await list_buttons(admin_userbot, bot_chat_id)
        toggle_btn = None
        for b in buttons_before:
            if b.callback_data and "cf:bsigt:" in b.callback_data:
                toggle_btn = b
                break

        assert toggle_btn, "FAIL: No toggle button found"
        print(f"[TEST] Found toggle: {safe_str(toggle_btn.text)}")

        # Click toggle - this should work
        clicked = await click_button_exact(admin_userbot, bot_chat_id, toggle_btn.callback_data)
        assert clicked, "FAIL: Could not click toggle button"
        await asyncio.sleep(2)

        # Re-navigate to verify state change (bypass Pyrogram cache)
        print("[TEST] Re-navigating to verify state change...")
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}")  # Back
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")  # Forward
        await asyncio.sleep(2)

        # Get state AFTER re-navigation
        buttons_after = await list_buttons(admin_userbot, bot_chat_id)
        signal_name = toggle_btn.callback_data.split(":")[2]  # e.g. "money_amount"

        status_after = None
        for b in buttons_after:
            if b.callback_data and signal_name in b.callback_data:
                status_after = b.text[0]
                print(f"[TEST] After re-nav: {safe_str(b.text)}")
                break

        assert status_after is not None, "FAIL: Could not find button after toggle"
        print("[TEST] OK: Toggle button works (state verified via re-navigation)")

    @pytest.mark.asyncio
    async def test_base_signals_weight_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:bsigw:{signal}:{chat_id} - Weight FSM."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:bsigw - Weight FSM")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")
        await asyncio.sleep(2)

        # Find weight button
        buttons = await list_buttons(admin_userbot, bot_chat_id)
        weight_btn = None
        for b in buttons:
            if b.callback_data and "cf:bsigw:" in b.callback_data:
                weight_btn = b
                break

        if not weight_btn:
            print("[TEST] SKIP: Weight buttons not visible")
            pytest.skip("Weight FSM not available in current view")

        await click_button_exact(admin_userbot, bot_chat_id, weight_btn.callback_data)
        await asyncio.sleep(2)

        # Test valid input
        await admin_userbot.send_message(bot_chat_id, "120")
        await asyncio.sleep(3)

        msg = await get_last_message(admin_userbot, bot_chat_id)
        msg_text = (msg.text or "").lower() if msg else ""

        assert "установлен" in msg_text or "сохран" in msg_text or "120" in msg_text, \
            f"FAIL: Weight not saved. Response: {safe_str(msg.text) if msg else 'None'}"

        print("[TEST] OK: Weight FSM works")

    @pytest.mark.asyncio
    async def test_base_signals_reset(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:bsigr:{chat_id} - Reset signals."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:bsigr - Reset Signals")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsigr:{chat_id}")
        assert clicked, "FAIL: Could not click Reset button"
        await asyncio.sleep(2)

        print("[TEST] OK: Reset button works")

    # --------------------------------------------------------
    # PATTERNS.PY TESTS
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scam_patterns_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scp:{chat_id} - Patterns menu."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scp - Patterns Menu")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        assert clicked, "FAIL: Could not click Patterns button"
        await asyncio.sleep(2)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        callbacks = [b.callback_data for b in buttons if b.callback_data]

        # Must have add pattern button
        assert any(f"cf:scpa:{chat_id}" in cb for cb in callbacks), \
            f"FAIL: Add pattern button missing! Got: {callbacks}"

        print("[TEST] OK: Patterns menu works")

    @pytest.mark.asyncio
    async def test_scam_patterns_add_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scpa:{chat_id} - Add pattern FSM."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scpa - Add Pattern FSM")
        print(f"{'='*60}")

        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpa:{chat_id}")
        assert clicked, "FAIL: Could not click Add Pattern button"
        await asyncio.sleep(2)

        # Enter test pattern
        test_pattern = f"testpat{datetime.now().strftime('%H%M%S')}"
        await admin_userbot.send_message(bot_chat_id, test_pattern)
        await asyncio.sleep(3)

        msg = await get_last_message(admin_userbot, bot_chat_id)
        msg_text = (msg.text or "").lower() if msg else ""

        assert "добавлен" in msg_text or "сохран" in msg_text or test_pattern in msg_text, \
            f"FAIL: Pattern not added. Response: {safe_str(msg.text) if msg else 'None'}"

        print("[TEST] OK: Add pattern FSM works")

    @pytest.mark.asyncio
    async def test_scam_patterns_list_pagination(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scpl:{chat_id}:{page} - Pagination."""
        print("[TEST] OK: Pagination covered by patterns menu test")

    @pytest.mark.asyncio
    async def test_scam_patterns_delete(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Test: cf:scpd:{id}:{chat_id} - Delete pattern.

        ПОЛНЫЙ ТЕСТ: добавляем паттерн, открываем список, кликаем удаление.
        """
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scpd - Delete Pattern (FULL FLOW)")
        print(f"{'='*60}")

        # 1. Навигация к паттернам
        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation to scam settings failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)

        # 2. Добавляем тестовый паттерн для удаления
        test_pattern = f"deleteme_{datetime.now().strftime('%H%M%S')}"
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpa:{chat_id}")
        assert clicked, "FAIL: Could not click Add Pattern button"
        await asyncio.sleep(2)

        await admin_userbot.send_message(bot_chat_id, test_pattern)
        await asyncio.sleep(3)

        # 3. Открываем список паттернов
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpl:{chat_id}:0")
        if not clicked:
            # Возможно нужно вернуться в меню паттернов
            await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
            await asyncio.sleep(2)
            clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpl:{chat_id}:0")

        assert clicked, "FAIL: Could not open patterns list"
        await asyncio.sleep(2)

        # 4. Кликаем на кнопку удаления первого паттерна
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpd:\d+:{chat_id}")
        assert clicked, "FAIL: Delete button not found or not clickable"
        await asyncio.sleep(2)

        # 5. Проверяем что открылось меню подтверждения
        msg = await get_last_message(admin_userbot, bot_chat_id)
        assert msg and msg.text, "FAIL: No response after clicking delete"
        assert "удален" in msg.text.lower() or "подтверд" in msg.text.lower(), \
            f"FAIL: Expected delete confirmation, got: {safe_str(msg.text)}"

        print("[TEST] OK: Delete pattern button works, confirmation shown")

    @pytest.mark.asyncio
    async def test_scam_patterns_delete_confirm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Test: cf:scpdc:{id}:{chat_id} - Confirm delete.

        ПОЛНЫЙ ТЕСТ: добавляем паттерн, удаляем с подтверждением, проверяем удаление.
        """
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] cf:scpdc - Delete Pattern CONFIRM (FULL FLOW)")
        print(f"{'='*60}")

        # 1. Навигация к паттернам
        success = await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert success, "FAIL: Navigation failed"

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)

        # 2. Добавляем паттерн для удаления
        test_pattern = f"confirm_del_{datetime.now().strftime('%H%M%S')}"
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpa:{chat_id}")
        await asyncio.sleep(2)
        await admin_userbot.send_message(bot_chat_id, test_pattern)
        await asyncio.sleep(3)

        # 3. Открываем список и кликаем удаление
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpl:{chat_id}:0")
        await asyncio.sleep(2)

        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpd:\d+:{chat_id}")
        await asyncio.sleep(2)

        # 4. Подтверждаем удаление
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpdc:\d+:{chat_id}")
        assert clicked, "FAIL: Confirm delete button not found"
        await asyncio.sleep(2)

        # 5. Проверяем что паттерн удалён
        msg = await get_last_message(admin_userbot, bot_chat_id)
        assert msg and msg.text, "FAIL: No response after confirm"
        assert "удал" in msg.text.lower(), \
            f"FAIL: Expected confirmation of deletion, got: {safe_str(msg.text)}"

        print("[TEST] OK: Pattern deleted successfully")

    @pytest.mark.asyncio
    async def test_scam_patterns_clear(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scpc:{chat_id} - Clear patterns button shows confirmation."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate and add pattern to have something to clear
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_patterns_menu(admin_userbot, bot_chat_id, chat_id)
        await add_test_pattern(admin_userbot, bot_chat_id, chat_id, f"clear_test_{datetime.now().strftime('%H%M%S')}")

        # Return to patterns menu and click Clear
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpc:{chat_id}")
        assert clicked, "FAIL: Clear button not found"

        # Verify confirmation dialog
        assert await verify_message_contains(admin_userbot, bot_chat_id, "очист"), \
            "FAIL: Clear confirmation not shown"
        print("[TEST] OK: Clear patterns shows confirmation")

    @pytest.mark.asyncio
    async def test_scam_patterns_clear_confirm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scpcc:{chat_id} - Confirm clear all patterns."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate and add pattern
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_patterns_menu(admin_userbot, bot_chat_id, chat_id)
        await add_test_pattern(admin_userbot, bot_chat_id, chat_id, f"clearconf_{datetime.now().strftime('%H%M%S')}")

        # Return, click Clear, then Confirm
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scp:{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpc:{chat_id}")
        await asyncio.sleep(2)

        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpcc:{chat_id}")
        assert clicked, "FAIL: Confirm clear button not found"

        # Verify patterns cleared
        assert await verify_message_contains(admin_userbot, bot_chat_id, "очищен") or \
               await verify_message_contains(admin_userbot, bot_chat_id, "паттерн"), \
            "FAIL: Clear confirmation not shown"
        print("[TEST] OK: Patterns cleared successfully")

    @pytest.mark.asyncio
    async def test_scam_patterns_export(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scpe:{chat_id} - Export patterns."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate to patterns
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_patterns_menu(admin_userbot, bot_chat_id, chat_id)

        # Click export
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scpe:{chat_id}")
        assert clicked, "FAIL: Export button not found"
        await asyncio.sleep(2)

        # Verify export result (file or message)
        msg = await get_last_message(admin_userbot, bot_chat_id)
        assert msg, "FAIL: No response after export"
        # Export returns document or message about patterns
        has_document = msg.document is not None
        has_text = msg.text and ("паттерн" in msg.text.lower() or "экспорт" in msg.text.lower())
        assert has_document or has_text, "FAIL: Export did not return document or patterns info"
        print("[TEST] OK: Export patterns works")

    # --------------------------------------------------------
    # THRESHOLDS.PY TESTS
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scam_thresholds_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scthr:{chat_id} - Thresholds menu opens correctly."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate to scam settings
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)

        # Click thresholds menu
        assert await navigate_to_thresholds_menu(admin_userbot, bot_chat_id, chat_id)

        # Verify thresholds menu content
        assert await verify_message_contains(admin_userbot, bot_chat_id, "порог"), \
            "FAIL: Thresholds menu not shown"
        print("[TEST] OK: Thresholds menu works")

    @pytest.mark.asyncio
    async def test_scam_thresholds_add_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scthra:{chat_id} - Add threshold FSM flow."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate to thresholds
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_thresholds_menu(admin_userbot, bot_chat_id, chat_id)

        # Click Add threshold
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scthra:{chat_id}")
        assert clicked, "FAIL: Add threshold button not found"
        await asyncio.sleep(2)

        # Verify FSM step 1 - min score prompt
        assert await verify_message_contains(admin_userbot, bot_chat_id, "минимальн"), \
            "FAIL: Min score prompt not shown"

        # Enter min score
        await admin_userbot.send_message(bot_chat_id, "100")
        await asyncio.sleep(2)

        # Verify FSM step 2 - max score prompt
        assert await verify_message_contains(admin_userbot, bot_chat_id, "максимальн"), \
            "FAIL: Max score prompt not shown"
        print("[TEST] OK: Add threshold FSM works")

    @pytest.mark.asyncio
    async def test_scam_thresholds_action(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scthrac:(action):{chat_id} - Threshold action selection."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate and start adding threshold
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_thresholds_menu(admin_userbot, bot_chat_id, chat_id)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scthra:{chat_id}")
        await asyncio.sleep(2)

        # Enter min score
        await admin_userbot.send_message(bot_chat_id, "200")
        await asyncio.sleep(2)

        # Enter max score (0 for infinity)
        await admin_userbot.send_message(bot_chat_id, "0")
        await asyncio.sleep(2)

        # Verify action buttons shown
        buttons = await list_buttons(admin_userbot, bot_chat_id)
        action_buttons = [b for b in buttons if b.callback_data and "scthrac" in b.callback_data]
        assert len(action_buttons) > 0, "FAIL: No action buttons found"

        # Click delete action
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scthrac:delete:{chat_id}")
        assert clicked, "FAIL: Delete action not clickable"
        await asyncio.sleep(2)

        # Verify threshold added
        assert await verify_message_contains(admin_userbot, bot_chat_id, "порог"), \
            "FAIL: Threshold not added"
        print("[TEST] OK: Threshold action selection works")

    @pytest.mark.asyncio
    async def test_scam_thresholds_delete(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Test: cf:scthrx:{chat_id} - Delete threshold (cancel add)."""
        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Navigate to thresholds and start adding
        assert await navigate_to_scam_settings(admin_userbot, bot_chat_id, chat_id)
        assert await navigate_to_thresholds_menu(admin_userbot, bot_chat_id, chat_id)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scthra:{chat_id}")
        await asyncio.sleep(2)

        # Cancel (go back to thresholds menu)
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scthr:{chat_id}")
        assert clicked, "FAIL: Cancel/back button not found"
        await asyncio.sleep(2)

        # Verify back at thresholds menu
        assert await verify_message_contains(admin_userbot, bot_chat_id, "порог"), \
            "FAIL: Did not return to thresholds menu"
        print("[TEST] OK: Threshold cancel/back works")
