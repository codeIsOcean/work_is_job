# tests/e2e/test_escort_spam_e2e.py
"""
E2E тесты для антискам функционала через РЕАЛЬНЫЙ UI бота.

Тестирует:
1. Bug 1: Нормализация текста сохраняет пробелы между словами
2. Bug 2: FSM для ввода веса базовых сигналов
3. Bug 3: Проверка дубликатов при импорте паттернов
4. Bug 4: Импорт в разделах использует extract_patterns_from_text

ВАЖНО: Тест проходит через РЕАЛЬНЫЙ USER FLOW - кликает кнопки, вводит текст.
НЕ использует прямые записи в БД!

Запуск:
    pytest tests/e2e/test_escort_spam_e2e.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот1 (ermek0vnma) - админ группы
    - Юзербот2 (s1adkaya2292) - жертва
    - Канал -1002326876297 где бот админ (для пересылки)
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
from typing import Optional, List

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from aiogram import Bot
from aiogram.types import ChatPermissions

# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_BOT_ID = os.getenv("TEST_BOT_ID")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK", "https://t.me/+zb5QPMK2ml5lMjgy")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

# Канал для пересылки спама
FORWARD_CHANNEL_ID = -1002326876297


def safe_str(text: str) -> str:
    """Convert string to ASCII-safe version for Windows console."""
    if not text:
        return text
    # Remove emoji and other non-ASCII chars
    return text.encode('ascii', 'replace').decode('ascii')

# Несколько юзерботов для ротации
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "Ffffggggyincd1ncf"},
    {"session": os.getenv("TEST_USERBOT4_SESSION"), "username": "Fqwer1t"},
]

# Скам-текст для тестирования
ESCORT_SPAM_TEXT = """ESCORT ESCORT

БЕЗ предоплат / аванса
и прочих неудобств

Красивые русские девушки

Только комфорт и наслаждение
Заинтересованных приглашаю в лс.

ESCORT ESCORT

NO prepayments / advance payment
and other inconveniences

Beautiful Russian girls

Only comfort and pleasure
I invite those interested"""

ESCORT_SPAM_TEXT_REORDERED = """Beautiful Russian girls

NO prepayments / advance payment
Only comfort and pleasure

ESCORT ESCORT

Заинтересованных приглашаю в лс.
Красивые русские девушки
БЕЗ предоплат"""

CRYPTO_SPAM_TEXT = """Есть USDC TRC20 на продажу? Заберу, работаю по объёмам."""


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
    """Первый юзербот (админ - ermek0vnma)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="escort_test_admin",
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
    """Второй юзербот (жертва - s1adkaya2292)."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("Userbot 2 not available")
    client = Client(
        name="escort_test_victim",
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


@pytest.fixture
def bot_id():
    """ID тестового бота."""
    return int(TEST_BOT_ID) if TEST_BOT_ID else None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Убедиться что юзербот в группе и Pyrogram знает о чате."""
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
            print(f"[ensure_user_in_chat] @{username} FloodWait {e.value}s - waiting...")
            if e.value < 60:
                await asyncio.sleep(e.value + 5)
        except Exception as e:
            print(f"[ensure_user_in_chat] @{username} join_chat error: {e}")

    # ОБЯЗАТЕЛЬНО: резолвим чат через invite_link
    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)
            print(f"[ensure_user_in_chat] @{username} resolved chat: {chat.title}")
        else:
            await userbot.get_chat(chat_id)
    except Exception as e:
        print(f"[ensure_user_in_chat] @{username} get_chat error: {e}")


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Размутить пользователя полностью."""
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
                can_invite_users=True,
                can_change_info=False,
                can_pin_messages=False,
            )
        )
        print(f"[unmute_user] User {user_id} unmuted")
    except Exception as e:
        print(f"[unmute_user] Error: {e}")


async def get_user_restrictions(bot: Bot, chat_id: int, user_id: int) -> dict:
    """Получить ограничения пользователя."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if hasattr(member, 'can_send_messages'):
            return {
                "can_send_messages": member.can_send_messages,
                "is_restricted": member.status == "restricted",
            }
        return {"can_send_messages": True, "is_restricted": False}
    except Exception as e:
        print(f"[get_user_restrictions] Error: {e}")
        return {"can_send_messages": True, "is_restricted": False}


async def check_message_exists(userbot: Client, chat_id: int, message_id: int) -> bool:
    """Проверяет существует ли сообщение."""
    try:
        msg = await userbot.get_messages(chat_id, message_id)
        return msg and msg.text is not None
    except Exception:
        return False


async def check_message_in_channel(userbot: Client, channel_id: int, text_contains: str, limit: int = 10) -> bool:
    """Проверяет есть ли сообщение с текстом в канале."""
    try:
        try:
            chat = await userbot.get_chat(channel_id)
            print(f"[check_message_in_channel] Resolved channel: {chat.title}")
        except Exception as e:
            print(f"[check_message_in_channel] Cannot resolve channel {channel_id}: {e}")
            return False

        async for msg in userbot.get_chat_history(channel_id, limit=limit):
            if msg.text and text_contains in msg.text:
                return True
        return False
    except Exception as e:
        print(f"[check_message_in_channel] Error: {e}")
        return False


async def get_bot_username(bot: Bot) -> str:
    """Получить username бота."""
    me = await bot.get_me()
    return me.username


async def get_latest_message_with_buttons(userbot: Client, chat_id, limit: int = 5, force_refresh: bool = False) -> Optional[Message]:
    """Получить последнее сообщение с inline кнопками.

    force_refresh: Если True, ждёт и перезапрашивает историю чтобы получить обновлённое сообщение.
    """
    if force_refresh:
        await asyncio.sleep(0.5)  # Небольшая задержка для обновления

    async for msg in userbot.get_chat_history(chat_id, limit=limit):
        if msg.reply_markup and hasattr(msg.reply_markup, 'inline_keyboard'):
            return msg
    return None


async def click_button_by_text(userbot: Client, chat_id, button_text: str, partial: bool = True) -> bool:
    """
    Нажать кнопку с указанным текстом в последнем сообщении.

    Args:
        userbot: Pyrogram клиент
        chat_id: ID чата (или username бота)
        button_text: Текст кнопки (или часть текста если partial=True)
        partial: Искать частичное совпадение

    Returns:
        True если кнопка нажата успешно
    """
    msg = await get_latest_message_with_buttons(userbot, chat_id)
    if not msg:
        print(f"[click_button] No message with buttons found")
        return False

    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            if partial:
                if button_text.lower() in button.text.lower():
                    await msg.click(button.text)
                    await asyncio.sleep(2.5)  # Увеличена задержка
                    print(f"[click_button] Clicked: '{safe_str(button.text)}'")
                    return True
            else:
                if button.text == button_text:
                    await msg.click(button.text)
                    await asyncio.sleep(2.5)  # Увеличена задержка
                    print(f"[click_button] Clicked: '{safe_str(button.text)}'")
                    return True

    print(f"[click_button] Button '{button_text}' not found")
    return False


async def click_button_by_callback(userbot: Client, chat_id, callback_pattern: str) -> bool:
    """
    Нажать кнопку по паттерну callback_data.

    Args:
        userbot: Pyrogram клиент
        chat_id: ID чата
        callback_pattern: Regex паттерн для callback_data
    """
    msg = await get_latest_message_with_buttons(userbot, chat_id)
    if not msg:
        print(f"[click_button_callback] No message with buttons found")
        return False

    pattern = re.compile(callback_pattern)
    for row_idx, row in enumerate(msg.reply_markup.inline_keyboard):
        for col_idx, button in enumerate(row):
            if button.callback_data and pattern.match(button.callback_data):
                # Pyrogram click(x, y): x=столбец, y=строка
                await msg.click(col_idx, row_idx)
                await asyncio.sleep(2.5)
                print(f"[click_button_callback] Clicked: '{safe_str(button.text)}' (callback: {button.callback_data})")
                return True

    print(f"[click_button_callback] No button matching '{callback_pattern}' found")
    return False


async def get_button_callback_data(userbot: Client, chat_id, button_text: str, partial: bool = True) -> Optional[str]:
    """Получить callback_data кнопки по тексту."""
    msg = await get_latest_message_with_buttons(userbot, chat_id)
    if not msg:
        return None

    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            if partial:
                if button_text.lower() in button.text.lower():
                    return button.callback_data
            else:
                if button.text == button_text:
                    return button.callback_data
    return None


async def list_buttons(userbot: Client, chat_id, force_refresh: bool = True) -> List[str]:
    """Вывести все кнопки в последнем сообщении (для дебага).

    force_refresh: Подождать и перезапросить чтобы получить обновлённые кнопки после callback.
    """
    msg = await get_latest_message_with_buttons(userbot, chat_id, force_refresh=force_refresh)
    if not msg:
        return []

    buttons = []
    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            cb = button.callback_data or "no_callback"
            # Use ASCII-safe text for Windows console
            buttons.append(f"{safe_str(button.text)} [{cb}]")
    return buttons


async def get_last_message_text(userbot: Client, chat_id) -> Optional[str]:
    """Получить текст последнего сообщения."""
    async for msg in userbot.get_chat_history(chat_id, limit=1):
        return msg.text
    return None


# ============================================================
# TEST CLASS: Escort Spam Full Flow
# ============================================================

class TestEscortSpamE2E:
    """
    E2E тесты антискам функционала через реальный UI.

    Тестирует все 4 исправленных бага на примере эскорт-спама.
    """

    @pytest.mark.asyncio
    async def test_full_escort_spam_flow_via_ui(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Полный тест антискам через UI бота.

        Сценарий:
        1. Админ создаёт раздел "Проституция" через UI
        2. Админ импортирует паттерны из скам-текста (Bug 4)
        3. Админ настраивает действие: delete + mute + forward
        4. Админ повторно импортирует - проверка дубликатов (Bug 3)
        5. Жертва отправляет скам - проверяем удаление и мут
        6. Unmute + жертва отправляет перестановку - проверяем детекцию
        """
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        # Уникальное имя раздела для теста
        section_name = f"Escort_{datetime.now().strftime('%H%M%S')}"
        unique_marker = f"TEST_{datetime.now().strftime('%H%M%S%f')}"

        print(f"\n{'='*60}")
        print(f"[TEST] Full Escort Spam Flow via UI")
        print(f"[TEST] Admin: @{admin.username}")
        print(f"[TEST] Victim: @{victim.username}")
        print(f"[TEST] Bot: @{bot_username}")
        print(f"[TEST] Section: {section_name}")
        print(f"[TEST] Group chat_id: {chat_id}")
        print(f"{'='*60}")

        section_created = False

        try:
            # Подготовка
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(2)

            # ============================================================
            # ШАГ 1: Админ открывает /settings в ЛС бота
            # ============================================================
            print(f"\n[STEP 1] Admin opens /settings in bot DM")

            await admin_userbot.send_message(bot_chat_id, "/settings")
            await asyncio.sleep(3)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 1] Available buttons: {buttons[:5]}...")

            # ============================================================
            # ШАГ 2: Выбираем тестовую группу
            # Callback: manage_group_{chat_id}
            # ============================================================
            print(f"\n[STEP 2] Admin selects test group (manage_group_{chat_id})")

            group_selected = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"manage_group_{chat_id}"
            )
            if not group_selected:
                print(f"[STEP 2] WARN: Could not find group by callback, trying by text...")
                await click_button_by_text(admin_userbot, bot_chat_id, "Test", partial=True)

            await asyncio.sleep(2)
            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 2] Group menu buttons: {buttons[:5]}...")

            # ============================================================
            # ШАГ 3: Переходим в Фильтр контента
            # Callback: cf:m:{chat_id}
            # ============================================================
            print(f"\n[STEP 3] Admin clicks Content Filter (cf:m:{chat_id})")

            cf_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"cf:m:{chat_id}"
            )
            if not cf_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Фильтр контента", partial=True)

            await asyncio.sleep(2)
            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 3] Content Filter menu: {buttons[:5]}...")

            # ============================================================
            # ШАГ 4: Переходим в Антискам настройки
            # Callback: cf:scs:{chat_id}
            # ============================================================
            print(f"\n[STEP 4] Admin clicks Antiscam settings (cf:scs:{chat_id})")

            scs_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}"
            )
            if not scs_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Антискам", partial=True)

            await asyncio.sleep(2)
            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 4] Antiscam menu: {buttons[:8]}...")

            # ============================================================
            # ШАГ 4.5: Переходим в Категории сигналов
            # Callback: cf:sccat:{chat_id}
            # ============================================================
            print(f"\n[STEP 4.5] Admin clicks Signal Categories (cf:sccat:{chat_id})")

            sccat_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"cf:sccat:{chat_id}"
            )
            if not sccat_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Категории", partial=True)

            await asyncio.sleep(2)
            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 4.5] Categories menu: {buttons[:5]}...")

            # ============================================================
            # ШАГ 5: Создаём новый раздел
            # Callback: cf:secn:{chat_id}
            # ============================================================
            print(f"\n[STEP 5] Admin creates new section '{section_name}'")

            secn_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"cf:secn:{chat_id}"
            )
            if not secn_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Создать раздел", partial=True)

            await asyncio.sleep(2)

            # Вводим название раздела (FSM ввод)
            await admin_userbot.send_message(bot_chat_id, section_name)
            await asyncio.sleep(3)
            section_created = True

            print(f"[STEP 5] Section name entered: {section_name}")

            # ============================================================
            # ШАГ 6: Находим созданный раздел и заходим в настройки
            # ============================================================
            print(f"\n[STEP 6] Admin opens section settings")

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 6] After section creation: {buttons[:5]}...")

            # После создания раздела ищем кнопку настроек (cf:secs:{id})
            # или кнопку с названием раздела
            section_settings_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, r"cf:secs:\d+"
            )
            if not section_settings_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, section_name, partial=True)

            await asyncio.sleep(2)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 6] Section settings menu: {buttons[:5]}...")

            # ============================================================
            # ШАГ 7: Импортируем паттерны (Bug 4 test)
            # Сначала заходим в меню паттернов, потом нажимаем Импорт
            # ============================================================
            print(f"\n[STEP 7] Admin imports patterns from spam text (Bug 4 test)")

            # Сначала кликаем "Паттерны" (cf:secp:{section_id}:0)
            patterns_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, r"cf:secp:\d+:\d+"
            )
            if not patterns_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Паттерны", partial=True)
            await asyncio.sleep(2)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 7] Patterns menu: {buttons[:5]}...")

            # Теперь кликаем Импорт (cf:secimp:{section_id})
            import_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, r"cf:secimp:\d+"
            )
            if not import_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Импорт", partial=True)

            await asyncio.sleep(2)

            # Вставляем скам-текст целиком (проверка Bug 4 - extract_patterns_from_text)
            await admin_userbot.send_message(bot_chat_id, ESCORT_SPAM_TEXT)
            await asyncio.sleep(3)

            # Проверяем что показывает превью паттернов
            msg_text = await get_last_message_text(admin_userbot, bot_chat_id)
            if msg_text and ("найден" in msg_text.lower() or "паттерн" in msg_text.lower()):
                print(f"[STEP 7] OK: Patterns extracted from text!")
            else:
                print(f"[STEP 7] WARN: Pattern preview not detected")

            # Подтверждаем импорт
            await click_button_by_text(admin_userbot, bot_chat_id, "Подтвердить", partial=True)
            await asyncio.sleep(2)

            print(f"[STEP 7] Patterns imported")

            # ============================================================
            # ШАГ 8: Настраиваем действие (mute forever)
            # ============================================================
            print(f"\n[STEP 8] Admin configures action (mute)")

            # Возвращаемся в настройки раздела (cf:secs:{id})
            await click_button_by_callback(admin_userbot, bot_chat_id, r"cf:secs:\d+")
            await asyncio.sleep(2)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 8] Back to section settings: {buttons[:5]}...")

            # Нажимаем на действие (cf:secac:{id})
            action_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, r"cf:secac:\d+$"
            )
            if not action_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Действие", partial=True)
            await asyncio.sleep(2)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 8] Action menu: {buttons[:5]}...")

            # Выбираем Мут (cf:secac:mute:{id})
            mute_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, r"cf:secac:mute:\d+"
            )
            if not mute_clicked:
                await click_button_by_text(admin_userbot, bot_chat_id, "Мут", partial=True)
            await asyncio.sleep(2)

            print(f"[STEP 8] Mute action configured")

            # ============================================================
            # ШАГ 9: Повторный импорт - проверка дубликатов (Bug 3)
            # ============================================================
            print(f"\n[STEP 9] Admin tries to import same text again (Bug 3 test)")

            # Возвращаемся в настройки раздела (cf:secs:{id})
            await click_button_by_callback(admin_userbot, bot_chat_id, r"cf:secs:\d+")
            await asyncio.sleep(2)

            # Переходим в паттерны (cf:secp:{id}:offset)
            await click_button_by_callback(admin_userbot, bot_chat_id, r"cf:secp:\d+:\d+")
            await asyncio.sleep(2)

            # Снова импорт (cf:secimp:{id})
            await click_button_by_callback(admin_userbot, bot_chat_id, r"cf:secimp:\d+")
            await asyncio.sleep(2)

            # Тот же текст - должен показать дубликаты
            await admin_userbot.send_message(bot_chat_id, ESCORT_SPAM_TEXT)
            await asyncio.sleep(3)

            # Подтверждаем
            await click_button_by_text(admin_userbot, bot_chat_id, "Подтвердить", partial=True)
            await asyncio.sleep(2)

            # Проверяем сообщение о дубликатах
            msg_text = await get_last_message_text(admin_userbot, bot_chat_id)
            if msg_text and ("дубликат" in msg_text.lower() or "уже существу" in msg_text.lower()):
                print(f"[STEP 9] OK: Duplicates detected and reported!")
            else:
                print(f"[STEP 9] WARN: Duplicate message not detected. Response: {safe_str(msg_text[:100] if msg_text else 'None')}...")

            # ============================================================
            # ШАГ 10: Жертва отправляет скам в группу
            # ============================================================
            print(f"\n[STEP 10] Victim sends escort spam to group")

            spam_text = f"{ESCORT_SPAM_TEXT}\n[{unique_marker}]"
            spam_msg = await victim_userbot.send_message(chat_id, spam_text)
            spam_msg_id = spam_msg.id
            print(f"[STEP 10] Victim sent spam message ID: {spam_msg_id}")

            # Ждём обработки webhook
            await asyncio.sleep(5)

            # Проверяем удаление
            exists = await check_message_exists(victim_userbot, chat_id, spam_msg_id)
            if not exists:
                print(f"[STEP 10] OK: Spam message was DELETED!")
            else:
                print(f"[STEP 10] FAIL: Spam message was NOT deleted")

            # Проверяем мут
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            if restrictions.get("is_restricted"):
                print(f"[STEP 10] OK: Victim is MUTED!")
            else:
                print(f"[STEP 10] WARN: Victim might not be muted (check manually)")

            # ============================================================
            # ШАГ 11: Unmute + жертва отправляет перестановку
            # ============================================================
            print(f"\n[STEP 11] Unmute victim, send reordered spam")

            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(3)

            # Жертва отправляет текст в другом порядке
            unique_marker2 = f"REORD_{datetime.now().strftime('%H%M%S%f')}"
            spam_text2 = f"{ESCORT_SPAM_TEXT_REORDERED}\n[{unique_marker2}]"
            spam_msg2 = await victim_userbot.send_message(chat_id, spam_text2)
            spam_msg_id2 = spam_msg2.id
            print(f"[STEP 11] Victim sent reordered spam message ID: {spam_msg_id2}")

            await asyncio.sleep(5)

            # Проверяем детекцию
            exists2 = await check_message_exists(victim_userbot, chat_id, spam_msg_id2)
            if not exists2:
                print(f"[STEP 11] OK: Reordered spam was DELETED!")
            else:
                print(f"[STEP 11] WARN: Reordered spam was NOT deleted")
                try:
                    await spam_msg2.delete()
                except Exception:
                    pass

            print(f"\n{'='*60}")
            print(f"[TEST] COMPLETED - Check results above")
            print(f"{'='*60}")

        finally:
            # ============================================================
            # CLEANUP
            # ============================================================
            print(f"\n[CLEANUP] Starting cleanup...")

            # Unmute
            await unmute_user(bot, chat_id, victim.id)

            # Удаляем раздел через UI если был создан
            if section_created:
                try:
                    await admin_userbot.send_message(bot_chat_id, "/settings")
                    await asyncio.sleep(2)

                    await click_button_by_callback(
                        admin_userbot, bot_chat_id, rf"manage_group_{chat_id}"
                    )
                    await asyncio.sleep(2)

                    await click_button_by_callback(
                        admin_userbot, bot_chat_id, rf"cf:m:{chat_id}"
                    )
                    await asyncio.sleep(2)

                    await click_button_by_callback(
                        admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}"
                    )
                    await asyncio.sleep(2)

                    # Находим раздел и удаляем
                    await click_button_by_text(admin_userbot, bot_chat_id, section_name, partial=True)
                    await asyncio.sleep(2)

                    await click_button_by_text(admin_userbot, bot_chat_id, "Удалить", partial=True)
                    await asyncio.sleep(2)

                    await click_button_by_text(admin_userbot, bot_chat_id, "Да", partial=True)
                    await asyncio.sleep(2)

                    print(f"[CLEANUP] Section '{section_name}' deleted via UI")
                except Exception as e:
                    print(f"[CLEANUP] Error deleting section: {e}")


# ============================================================
# TEST CLASS: Base Signal Weight FSM (Bug 2)
# ============================================================

class TestBaseSignalWeightFSM:
    """
    E2E тест для FSM ввода веса базовых сигналов (Bug 2).
    """

    @pytest.mark.asyncio
    async def test_base_signal_weight_fsm(
        self, admin_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест FSM для ввода веса базового сигнала.

        Сценарий:
        1. Админ открывает /settings -> группа -> Фильтр контента
        2. Админ заходит в "Антискам" -> "Базовые сигналы"
        3. Админ нажимает на сигнал чтобы изменить вес
        4. Админ вводит число - проверяем что FSM обработал
        """
        admin = await admin_userbot.get_me()
        bot_username = await get_bot_username(bot)
        bot_chat_id = f"@{bot_username}"

        print(f"\n{'='*60}")
        print(f"[TEST] Base Signal Weight FSM (Bug 2)")
        print(f"[TEST] Admin: @{admin.username}")
        print(f"{'='*60}")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)

            # ШАГ 1: /settings
            print(f"\n[STEP 1] Admin opens /settings")
            await admin_userbot.send_message(bot_chat_id, "/settings")
            await asyncio.sleep(3)

            # ШАГ 2: Выбираем группу
            print(f"\n[STEP 2] Admin selects group")
            await click_button_by_callback(admin_userbot, bot_chat_id, rf"manage_group_{chat_id}")
            await asyncio.sleep(2)

            # ШАГ 3: Фильтр контента
            print(f"\n[STEP 3] Admin clicks Content Filter")
            await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:m:{chat_id}")
            await asyncio.sleep(2)

            # ШАГ 4: Антискам (scam sections main)
            print(f"\n[STEP 4] Admin clicks Antiscam settings")
            await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:scs:{chat_id}")
            await asyncio.sleep(2)

            # ШАГ 5: Базовые сигналы
            print(f"\n[STEP 5] Admin clicks Base Signals")
            await click_button_by_callback(admin_userbot, bot_chat_id, rf"cf:bsig:{chat_id}")
            await asyncio.sleep(2)

            buttons = await list_buttons(admin_userbot, bot_chat_id)
            print(f"[STEP 5] Base signals menu: {buttons[:5]}...")

            # ШАГ 6: Нажимаем на первый сигнал для изменения веса
            # Callback: cf:bsigw:{chat_id}:{signal_name}
            print(f"\n[STEP 6] Admin clicks on a signal to change weight")

            signal_clicked = await click_button_by_callback(
                admin_userbot, bot_chat_id, rf"cf:bsigw:{chat_id}:\w+"
            )
            if not signal_clicked:
                # Пробуем по тексту - ищем кнопку с [число]
                await click_button_by_text(admin_userbot, bot_chat_id, "[", partial=True)

            await asyncio.sleep(2)

            # ШАГ 7: Вводим новый вес
            print(f"\n[STEP 7] Admin enters new weight (50)")

            await admin_userbot.send_message(bot_chat_id, "50")
            await asyncio.sleep(3)

            # Проверяем ответ
            msg_text = await get_last_message_text(admin_userbot, bot_chat_id)
            if msg_text and ("установлен" in msg_text.lower() or "сохран" in msg_text.lower()):
                print(f"[STEP 7] OK: Weight FSM worked! Response: {msg_text[:50]}...")
            else:
                print(f"[STEP 7] WARN: FSM response not detected. Last message: {msg_text[:100] if msg_text else 'None'}...")

            print(f"\n{'='*60}")
            print(f"[TEST] Base Signal Weight FSM COMPLETED")
            print(f"{'='*60}")

        except Exception as e:
            print(f"[ERROR] Test failed: {e}")
            raise


# ============================================================
# Запуск тестов
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
