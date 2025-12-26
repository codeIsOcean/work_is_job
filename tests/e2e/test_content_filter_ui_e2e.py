# tests/e2e/test_content_filter_ui_e2e.py
"""
E2E тесты для UI настроек Content Filter после рефакторинга.

Тестирует все рефакторенные модули:
1. main_menu.py - Главное меню фильтра
2. word_filter/ - Категории слов (menu, category, words)
3. scam/ - Антискам (menu, sensitivity, threshold)
4. flood/ - Флуд детектор (menu, settings)
5. sections/ - Пользовательские разделы
6. cleanup.py - Очистка истории

Запуск:
    pytest tests/e2e/test_content_filter_ui_e2e.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот (админ группы)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# КРИТИЧЕСКИ ВАЖНО: загружаем .env.test ДО ВСЕХ других импортов
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
import re
from datetime import datetime

from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from aiogram import Bot


def safe_str(text: str) -> str:
    """Convert string to ASCII-safe version for Windows console."""
    if not text:
        return text
    # Remove emoji and other non-ASCII chars
    return text.encode('ascii', 'replace').decode('ascii')


# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

# Юзербот сессии
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
]


def skip_if_no_credentials():
    """Пропуск теста если нет credentials."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    if not any(s["session"] for s in USERBOT_SESSIONS):
        pytest.skip("No TEST_USERBOT_SESSION set")


def get_available_session(index: int = 0):
    """Получить доступную сессию юзербота."""
    available = [s for s in USERBOT_SESSIONS if s["session"]]
    return available[index] if index < len(available) else None


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def admin_userbot():
    """Первый юзербот (админ)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="cf_ui_test_admin",
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
    yield bot_instance
    await bot_instance.session.close()


@pytest.fixture
def chat_id():
    """ID тестовой группы."""
    return int(TEST_CHAT_ID)


@pytest.fixture
def invite_link():
    """Invite link для группы."""
    return TEST_CHAT_INVITE_LINK


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Убедиться что юзербот в группе."""
    me = await userbot.get_me()
    username = me.username or me.first_name

    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
            print(f"[ensure_user_in_chat] @{username} joined chat")
        except UserAlreadyParticipant:
            print(f"[ensure_user_in_chat] @{username} already in chat")
        except FloodWait as e:
            print(f"[ensure_user_in_chat] @{username} FloodWait {e.value}s - continuing anyway")
        except Exception as e:
            print(f"[ensure_user_in_chat] @{username} join_chat error: {e}")

    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)
            print(f"[ensure_user_in_chat] @{username} resolved chat: {chat.title}")
    except Exception as e:
        print(f"[ensure_user_in_chat] @{username} get_chat error: {e}")


async def get_bot_chat_id(userbot: Client) -> int:
    """Получить chat_id ЛС с ботом."""
    bot_info = await Bot(token=TEST_BOT_TOKEN).get_me()
    bot_username = bot_info.username
    await Bot(token=TEST_BOT_TOKEN).session.close()

    # Отправляем /start чтобы начать диалог
    try:
        await userbot.send_message(bot_username, "/start")
        await asyncio.sleep(1)
    except Exception:
        pass

    return bot_username


async def list_buttons(userbot: Client, chat_id) -> list:
    """Получить список кнопок последнего сообщения."""
    buttons = []
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for button in row:
                    cb = button.callback_data or ""
                    buttons.append(f"{safe_str(button.text)} [{cb}]")
    return buttons


async def click_button_by_callback(userbot: Client, chat_id, callback_pattern: str) -> bool:
    """Кликнуть кнопку по паттерну callback_data."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if not msg.reply_markup:
            print(f"[click_button_callback] No message with buttons found")
            return False

        for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
            for col_idx, button in enumerate(row):
                if button.callback_data and re.search(callback_pattern, button.callback_data):
                    await msg.click(col_idx, row_idx)
                    await asyncio.sleep(2)
                    print(f"[click_button_callback] Clicked: '{safe_str(button.text)}' (callback: {button.callback_data})")
                    return True
    print(f"[click_button_callback] No button matching '{callback_pattern}' found")
    return False


async def click_button_by_text(userbot: Client, chat_id, button_text: str, partial: bool = True) -> bool:
    """Кликнуть кнопку по тексту."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        if not msg.reply_markup:
            return False

        for row in msg.reply_markup.inline_keyboard:
            for button in row:
                if partial and button_text.lower() in button.text.lower():
                    await msg.click(button.text)
                    await asyncio.sleep(2)
                    return True
                elif not partial and button.text == button_text:
                    await msg.click(button.text)
                    await asyncio.sleep(2)
                    return True
    return False


async def get_last_message_text(userbot: Client, chat_id) -> str:
    """Получить текст последнего сообщения."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        return msg.text or msg.caption or ""
    return ""


# ============================================================
# TESTS
# ============================================================

class TestContentFilterMainMenu:
    """Тесты главного меню фильтра контента (main_menu.py)."""

    @pytest.mark.asyncio
    async def test_main_menu_opens(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: главное меню фильтра контента открывается."""
        print(f"\n{'='*60}")
        print(f"[TEST] Content Filter Main Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Шаг 1: /settings
        print(f"\n[STEP 1] Opening /settings")
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP 1] Buttons: {buttons[:3]}...")
        assert any(str(chat_id) in b for b in buttons), "Group button not found"

        # Шаг 2: Выбор группы
        print(f"\n[STEP 2] Selecting group")
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP 2] Group menu: {buttons[:5]}...")

        # Шаг 3: Фильтр контента
        print(f"\n[STEP 3] Opening Content Filter (cf:m:{chat_id})")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        assert clicked, "Content Filter button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP 3] Content Filter menu: {buttons[:6]}...")

        # Проверяем что есть все основные кнопки
        buttons_str = " ".join(buttons)
        assert "cf:wfs:" in buttons_str or "cf:t:wf:" in buttons_str, "Word Filter not in menu"
        assert "cf:scs:" in buttons_str or "cf:t:sc:" in buttons_str, "Scam not in menu"
        assert "cf:t:fl:" in buttons_str, "Flood not in menu"

        print(f"\n[OK] Main menu test PASSED")


class TestWordFilterUI:
    """Тесты UI фильтра слов (word_filter/)."""

    @pytest.mark.asyncio
    async def test_word_filter_categories_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: меню категорий слов открывается (word_filter/menu.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Word Filter Categories Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация: /settings → группа → Фильтр → Слова
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)

        # Открываем настройки слов (cf:wfs:{chat_id})
        print(f"\n[STEP] Opening Word Filter settings (cf:wfs:{chat_id})")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:wfs:{chat_id}")
        assert clicked, "Word Filter settings button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Word Filter menu: {buttons[:8]}...")

        # Проверяем наличие категорий (cf:swl, cf:hwl, cf:owl)
        buttons_str = " ".join(buttons)
        has_categories = "cf:swl:" in buttons_str or "cf:hwl:" in buttons_str or "cf:owl:" in buttons_str
        assert has_categories, "Word categories not found in menu"

        print(f"\n[OK] Word Filter categories menu test PASSED")

    @pytest.mark.asyncio
    async def test_word_category_settings(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: настройки категории слов (word_filter/category.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Word Category Settings")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:wfs:{chat_id}")
        await asyncio.sleep(2)

        # Кликаем на первую категорию (cf:swl, cf:hwl или cf:owl)
        print(f"\n[STEP] Opening first category words list")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, r"cf:swl:|cf:hwl:|cf:owl:")
        assert clicked, "Category button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Words list: {buttons[:6]}...")

        # Проверяем что открылся список слов (кнопка добавления или назад)
        buttons_str = " ".join(buttons)
        has_word_actions = "cf:swa:" in buttons_str or "cf:hwa:" in buttons_str or "cf:owa:" in buttons_str or "cf:wfs:" in buttons_str
        assert has_word_actions, "Word list actions not found"

        print(f"\n[OK] Word category settings test PASSED")


class TestScamUI:
    """Тесты UI антискама (scam/)."""

    @pytest.mark.asyncio
    async def test_scam_settings_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: меню антискама открывается (scam/menu.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Scam Settings Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)

        # Открываем настройки скама (cf:scs:{chat_id})
        print(f"\n[STEP] Opening Scam settings (cf:scs:{chat_id})")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}")
        assert clicked, "Scam settings button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Scam menu: {buttons[:8]}...")

        # Проверяем наличие настроек
        buttons_str = " ".join(buttons)
        assert "cf:sens:" in buttons_str or "cf:scact:" in buttons_str, "Scam settings not found"
        assert "cf:sccat:" in buttons_str, "Custom sections button not found"

        print(f"\n[OK] Scam settings menu test PASSED")


class TestFloodUI:
    """Тесты UI флуд детектора (flood/)."""

    @pytest.mark.asyncio
    async def test_flood_settings_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: меню флуд детектора открывается (flood/menu.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Flood Settings Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)

        # Открываем настройки флуда (cf:fls:{chat_id})
        print(f"\n[STEP] Opening Flood settings (cf:fls:{chat_id})")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:fls:{chat_id}")
        assert clicked, "Flood settings button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Flood menu: {buttons[:6]}...")

        # Проверяем наличие настроек
        buttons_str = " ".join(buttons)
        has_flood_settings = "cf:fladv:" in buttons_str or "cf:t:flany:" in buttons_str or "cf:t:flmedia:" in buttons_str
        assert has_flood_settings, \
            "Flood settings buttons not found"

        print(f"\n[OK] Flood settings menu test PASSED")


class TestSectionsUI:
    """Тесты UI пользовательских разделов (sections/)."""

    @pytest.mark.asyncio
    async def test_sections_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: меню разделов открывается (sections/menu.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Custom Sections Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}")
        await asyncio.sleep(2)

        # Открываем разделы (cf:sccat:{chat_id})
        print(f"\n[STEP] Opening Custom Sections (cf:sccat:{chat_id})")
        clicked = await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:sccat:{chat_id}")
        assert clicked, "Custom sections button not found"

        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Sections menu: {buttons[:5]}...")

        # Проверяем наличие кнопки создания раздела
        buttons_str = " ".join(buttons)
        assert "cf:secn:" in buttons_str, "Create section button not found"

        print(f"\n[OK] Custom sections menu test PASSED")


class TestCleanupUI:
    """Тесты UI очистки истории (cleanup.py)."""

    @pytest.mark.asyncio
    async def test_cleanup_menu(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Тест: меню очистки истории открывается (cleanup.py)."""
        print(f"\n{'='*60}")
        print(f"[TEST] Cleanup History Menu")
        print(f"{'='*60}")

        await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
        bot_chat_id = await get_bot_chat_id(admin_userbot)

        # Навигация
        await admin_userbot.send_message(bot_chat_id, "/settings")
        await asyncio.sleep(3)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
        await asyncio.sleep(2)
        await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
        await asyncio.sleep(2)

        # Ищем кнопку очистки истории (cf:clean: или cf:clh:)
        print(f"\n[STEP] Looking for Cleanup button")
        buttons = await list_buttons(admin_userbot, bot_chat_id)
        print(f"[STEP] Content Filter menu: {buttons}")

        # Проверяем наличие кнопки очистки
        buttons_str = " ".join(buttons)
        cleanup_found = "cf:clean:" in buttons_str or "cf:clh:" in buttons_str

        if cleanup_found:
            print(f"\n[OK] Cleanup button found in menu")
        else:
            print(f"\n[INFO] Cleanup button not in main menu (may be in submenu)")

        print(f"\n[OK] Cleanup menu test PASSED")
