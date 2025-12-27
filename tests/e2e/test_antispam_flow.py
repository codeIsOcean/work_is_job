"""
E2E-тесты для антиспам модуля.

РЕАЛЬНЫЕ E2E ТЕСТЫ с использованием Pyrogram юзерботов.
Тестирует полный поток работы антиспам системы:
- Фильтрация сообщений с Telegram ссылками
- Фильтрация пересылок из разных источников
- Работа белого списка
- Применение различных действий (WARN, RESTRICT, BAN)

Запуск:
    pytest tests/e2e/test_antispam_flow.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот1 (админ) - настраивает правила
    - Юзербот2 (жертва) - отправляет спам
"""

import os
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
from aiogram import Bot

# Конфигурация
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH")

USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "admin_user"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "victim_user"},
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
        name="antispam_admin",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def victim_userbot():
    """Victim userbot fixture."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("No victim userbot session available")
    client = Client(
        name="antispam_victim",
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
                await asyncio.sleep(e.value + 5)


async def get_bot_username(bot: Bot) -> str:
    """Get bot username."""
    me = await bot.get_me()
    return me.username


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Unmute user in chat."""
    from aiogram.types import ChatPermissions
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
    except Exception:
        pass


async def check_message_exists(userbot: Client, chat_id: int, message_id: int) -> bool:
    """Check if message exists."""
    try:
        msg = await userbot.get_messages(chat_id, message_id)
        return msg and msg.text is not None
    except Exception:
        return False


async def get_user_restrictions(bot: Bot, chat_id: int, user_id: int) -> dict:
    """Get user restrictions in chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if hasattr(member, 'can_send_messages'):
            return {
                "is_restricted": member.can_send_messages is False,
                "can_send_messages": member.can_send_messages
            }
        return {"is_restricted": False}
    except Exception:
        return {"is_restricted": False}


async def enable_antispam_telegram_links(chat_id: int, action: str = "delete"):
    """Enable antispam rule for Telegram links."""
    from bot.database.session import get_session
    from bot.database.models_antispam import AntiSpamRule, RuleType, ActionType
    from sqlalchemy import select, delete

    action_map = {
        "warn": ActionType.WARN,
        "delete": ActionType.WARN,  # delete with warn
        "mute": ActionType.RESTRICT,
        "ban": ActionType.BAN,
    }

    async with get_session() as session:
        # Remove existing rule
        await session.execute(
            delete(AntiSpamRule).where(
                AntiSpamRule.chat_id == chat_id,
                AntiSpamRule.rule_type == RuleType.TELEGRAM_LINK
            )
        )
        # Create new rule
        rule = AntiSpamRule(
            chat_id=chat_id,
            rule_type=RuleType.TELEGRAM_LINK,
            action=action_map.get(action, ActionType.WARN),
            enabled=True,
            delete_message=True,
            restrict_minutes=60 if action == "mute" else None
        )
        session.add(rule)
        await session.commit()


async def disable_antispam_telegram_links(chat_id: int):
    """Disable antispam rule for Telegram links."""
    from bot.database.session import get_session
    from bot.database.models_antispam import AntiSpamRule, RuleType
    from sqlalchemy import update

    async with get_session() as session:
        await session.execute(
            update(AntiSpamRule).where(
                AntiSpamRule.chat_id == chat_id,
                AntiSpamRule.rule_type == RuleType.TELEGRAM_LINK
            ).values(enabled=False)
        )
        await session.commit()


async def add_to_whitelist(chat_id: int, pattern: str):
    """Add pattern to whitelist."""
    from bot.database.session import get_session
    from bot.database.models_antispam import AntiSpamWhitelist, WhitelistScope

    async with get_session() as session:
        whitelist = AntiSpamWhitelist(
            chat_id=chat_id,
            scope=WhitelistScope.TELEGRAM_LINK,
            pattern=pattern,
            added_by=123456789
        )
        session.add(whitelist)
        await session.commit()


async def clear_whitelist(chat_id: int):
    """Clear whitelist for chat."""
    from bot.database.session import get_session
    from bot.database.models_antispam import AntiSpamWhitelist
    from sqlalchemy import delete

    async with get_session() as session:
        await session.execute(
            delete(AntiSpamWhitelist).where(AntiSpamWhitelist.chat_id == chat_id)
        )
        await session.commit()


# ============================================================
# TEST CLASS: Telegram Link Detection
# ============================================================

@pytest.mark.e2e
class TestAntispamTelegramLinks:
    """E2E tests for Telegram link detection."""

    @pytest.mark.asyncio
    async def test_telegram_link_detected_and_deleted(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: Telegram link is detected and message is deleted.

        Scenario:
        1. Enable antispam rule for Telegram links
        2. Victim sends message with t.me link
        3. Verify message is deleted by bot
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Enable antispam
        await enable_antispam_telegram_links(chat_id, action="delete")
        await asyncio.sleep(1)

        try:
            # Victim sends spam
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Join our channel https://t.me/spam_channel_{datetime.now().strftime('%H%M%S')}"
            )
            msg_id = spam_msg.id
            print(f"[SEND] Sent spam link (msg_id={msg_id})")
            await asyncio.sleep(3)

            # Verify message deleted
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            assert not exists, "FAIL: Spam message with Telegram link was NOT deleted"
            print(f"[OK] Spam message deleted by antispam")

        finally:
            await disable_antispam_telegram_links(chat_id)
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_telegram_link_whitelisted_allowed(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: Whitelisted Telegram link is allowed.

        Scenario:
        1. Enable antispam rule for Telegram links
        2. Add link pattern to whitelist
        3. Victim sends message with whitelisted link
        4. Verify message is NOT deleted
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Enable antispam and add to whitelist
        await enable_antispam_telegram_links(chat_id, action="delete")
        await add_to_whitelist(chat_id, "t.me/allowed_channel")
        await asyncio.sleep(1)

        try:
            # Victim sends whitelisted link
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Check our official https://t.me/allowed_channel"
            )
            msg_id = msg.id
            print(f"[SEND] Sent whitelisted link (msg_id={msg_id})")
            await asyncio.sleep(3)

            # Verify message NOT deleted
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            assert exists, "FAIL: Whitelisted link message was deleted (should be allowed)"
            print(f"[OK] Whitelisted link allowed")

            # Cleanup
            await msg.delete()

        finally:
            await disable_antispam_telegram_links(chat_id)
            await clear_whitelist(chat_id)
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_clean_text_allowed(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: Clean text without links is allowed.

        Scenario:
        1. Enable antispam rule for Telegram links
        2. Victim sends normal message without links
        3. Verify message is NOT deleted
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Enable antispam
        await enable_antispam_telegram_links(chat_id, action="delete")
        await asyncio.sleep(1)

        try:
            # Victim sends clean message
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Hello everyone! Great weather today! {datetime.now().strftime('%H:%M:%S')}"
            )
            msg_id = msg.id
            print(f"[SEND] Sent clean message (msg_id={msg_id})")
            await asyncio.sleep(3)

            # Verify message NOT deleted
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            assert exists, "FAIL: Clean message was deleted (false positive)"
            print(f"[OK] Clean message allowed")

            # Cleanup
            await msg.delete()

        finally:
            await disable_antispam_telegram_links(chat_id)
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_rule_disabled_allows_links(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: When rule is disabled, links are allowed.

        Scenario:
        1. Disable antispam rule
        2. Victim sends message with Telegram link
        3. Verify message is NOT deleted
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Disable antispam
        await disable_antispam_telegram_links(chat_id)
        await asyncio.sleep(1)

        try:
            # Victim sends link
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Check https://t.me/some_channel_{datetime.now().strftime('%H%M%S')}"
            )
            msg_id = msg.id
            print(f"[SEND] Sent link with rule disabled (msg_id={msg_id})")
            await asyncio.sleep(3)

            # Verify message NOT deleted (rule disabled)
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            assert exists, "FAIL: Message deleted even with rule disabled"
            print(f"[OK] Link allowed when rule disabled")

            # Cleanup
            await msg.delete()

        finally:
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Mute Action
# ============================================================

@pytest.mark.e2e
class TestAntispamMuteAction:
    """E2E tests for mute action."""

    @pytest.mark.asyncio
    async def test_telegram_link_triggers_mute(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: Telegram link triggers mute action.

        Scenario:
        1. Enable antispam with mute action
        2. Victim sends spam link
        3. Verify victim is muted
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Enable antispam with mute
        await enable_antispam_telegram_links(chat_id, action="mute")
        await asyncio.sleep(1)

        try:
            # Victim sends spam
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Join spam https://t.me/mute_test_{datetime.now().strftime('%H%M%S')}"
            )
            print(f"[SEND] Sent spam to trigger mute")
            await asyncio.sleep(3)

            # Verify mute
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            assert restrictions.get("is_restricted"), "FAIL: Victim was NOT muted for spam link"
            print(f"[OK] Victim muted for spam link")

        finally:
            await disable_antispam_telegram_links(chat_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: External Links
# ============================================================

@pytest.mark.e2e
class TestAntispamExternalLinks:
    """E2E tests for external link detection."""

    @pytest.mark.asyncio
    async def test_external_link_detected(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot,
        chat_id: int, invite_link: str
    ):
        """
        Test: External links are detected.

        Note: This test depends on having an "any link" rule configured.
        """
        victim = await victim_userbot.get_me()

        await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Enable any link rule
        from bot.database.session import get_session
        from bot.database.models_antispam import AntiSpamRule, RuleType, ActionType
        from sqlalchemy import delete

        async with get_session() as session:
            await session.execute(
                delete(AntiSpamRule).where(
                    AntiSpamRule.chat_id == chat_id,
                    AntiSpamRule.rule_type == RuleType.ANY_LINK
                )
            )
            rule = AntiSpamRule(
                chat_id=chat_id,
                rule_type=RuleType.ANY_LINK,
                action=ActionType.WARN,
                enabled=True,
                delete_message=True
            )
            session.add(rule)
            await session.commit()

        await asyncio.sleep(1)

        try:
            # Victim sends external link
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Check out https://spam-site.com/offer_{datetime.now().strftime('%H%M%S')}"
            )
            msg_id = spam_msg.id
            print(f"[SEND] Sent external link (msg_id={msg_id})")
            await asyncio.sleep(3)

            # Verify message deleted
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            assert not exists, "FAIL: External link was NOT deleted"
            print(f"[OK] External link deleted by antispam")

        finally:
            # Disable rule
            async with get_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(AntiSpamRule).where(
                        AntiSpamRule.chat_id == chat_id,
                        AntiSpamRule.rule_type == RuleType.ANY_LINK
                    ).values(enabled=False)
                )
                await session.commit()
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# Run tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
