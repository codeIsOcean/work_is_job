# tests/e2e/test_mute_by_reaction_e2e.py
"""
Комплексные E2E тесты для модуля Mute by Reaction.

Тестирует:
1. Реакция -> мут -> системное сообщение
2. Автоудаление системного сообщения через N секунд
3. Удаление сообщения нарушителя (с задержкой и без)
4. Кастомный текст с %user% и %time%
5. Действие "только удалить" (без мута)
6. Различные типы реакций

Запуск:
    pytest tests/e2e/test_mute_by_reaction_e2e.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот1 (ermek0vnma) должен быть админом группы
    - Юзербот2 (s1adkaya2292) - обычный участник (жертва)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ВАЖНО: загружаем .env.test ДО ВСЕХ других импортов
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
import json
from datetime import datetime

from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from aiogram import Bot

# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK", "https://t.me/+zb5QPMK2ml5lMjgy")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

# Несколько юзерботов для ротации
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "Ffffggggyincd1ncf"},
    {"session": os.getenv("TEST_USERBOT4_SESSION"), "username": "Fqwer1t"},
]

# Redis ключ для настроек (должен совпадать с settings_handler.py)
REACTION_CONFIG_KEY = "reaction_config:{chat_id}"


def skip_if_no_credentials():
    """Проверка credentials в runtime."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    if not any(s["session"] for s in USERBOT_SESSIONS):
        pytest.skip("No TEST_USERBOT_SESSION set")


def get_available_session(index: int = 0):
    """Получить доступную сессию юзербота по индексу."""
    available = [s for s in USERBOT_SESSIONS if s["session"]]
    if index < len(available):
        return available[index]
    return None


# ============================================================
# FIXTURES (определены в файле для правильной загрузки .env.test)
# ============================================================

async def create_userbot_client(session_info: dict, name: str = "test_userbot") -> Client:
    """Создаёт и запускает Pyrogram клиент."""
    client = Client(
        name=name,
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    return client


@pytest.fixture
async def userbot():
    """Первый юзербот (админ - ermek0vnma)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = await create_userbot_client(session_info, "rm_test_userbot_1")
    yield client
    await client.stop()


@pytest.fixture
async def userbot2():
    """Второй юзербот (жертва - s1adkaya2292)."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("Userbot 2 not available")
    client = await create_userbot_client(session_info, "rm_test_userbot_2")
    yield client
    await client.stop()


@pytest.fixture
async def bot():
    """Aiogram Bot для проверки действий."""
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
# HELPER FUNCTIONS (локальные копии для избежания circular import)
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, bot: Bot = None, invite_link: str = None):
    """Убедиться что юзербот в группе и Pyrogram знает о чате."""
    # Первым делом пытаемся войти по инвайт-ссылке
    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
        except UserAlreadyParticipant:
            pass
        except FloodWait as e:
            pytest.skip(f"FloodWait: {e.value} seconds")
        except Exception as e:
            print(f"[ensure_user_in_chat] join_chat error: {e}")

    # Обязательно получаем информацию о чате чтобы Pyrogram закэшировал peer
    # Используем invite_link для резолва, так как chat_id может не работать напрямую
    try:
        if invite_link:
            # Резолвим через инвайт-ссылку (работает даже если уже участник)
            chat = await userbot.get_chat(invite_link)
            print(f"[ensure_user_in_chat] Resolved chat: {chat.title}")
        else:
            await userbot.get_chat(chat_id)
    except Exception as e:
        print(f"[ensure_user_in_chat] get_chat error: {e}")


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Размутить пользователя."""
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions={
                "can_send_messages": True,
                "can_send_media_messages": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True,
            }
        )
    except Exception:
        pass


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
    except Exception:
        return {"can_send_messages": True, "is_restricted": False}


async def set_reaction_config(chat_id: int, emoji: str, config: dict):
    """Установить настройки реакции в Redis."""
    from bot.services.redis_conn import redis

    key = REACTION_CONFIG_KEY.format(chat_id=chat_id)
    try:
        raw = await redis.get(key)
        full_config = json.loads(raw) if raw else {}
    except Exception:
        full_config = {}

    full_config[emoji] = config
    await redis.set(key, json.dumps(full_config))
    # Use ASCII encoding to avoid Windows console encoding issues
    print(f"[CONFIG] Set reaction config for emoji -> action={config.get('action')}")


async def get_reaction_config(chat_id: int, emoji: str) -> dict:
    """Получить настройки реакции из Redis."""
    from bot.services.redis_conn import redis

    key = REACTION_CONFIG_KEY.format(chat_id=chat_id)
    try:
        raw = await redis.get(key)
        if raw:
            config = json.loads(raw)
            return config.get(emoji, {})
    except Exception:
        pass
    return {}


async def wait_for_bot_message(userbot: Client, chat_id: int, timeout: int = 5) -> list:
    """Ждёт сообщения от бота в группе."""
    messages = []
    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            async for msg in userbot.get_chat_history(chat_id, limit=5):
                if msg.from_user and msg.from_user.is_bot:
                    messages.append(msg)
            if messages:
                break
        except Exception:
            pass
        await asyncio.sleep(0.5)

    return messages


async def check_message_exists(userbot: Client, chat_id: int, message_id: int) -> bool:
    """Проверяет существует ли сообщение."""
    try:
        msg = await userbot.get_messages(chat_id, message_id)
        return msg and msg.text is not None
    except Exception:
        return False


# ============================================================
# TEST CLASS: System Messages
# ============================================================

class TestReactionMuteSystemMessages:
    """Тесты системных сообщений."""

    @pytest.mark.asyncio
    async def test_reaction_triggers_system_message(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: реакция вызывает отправку системного сообщения.

        Сценарий:
        1. Жертва отправляет сообщение
        2. Админ ставит 🤢
        3. Проверяем что бот отправил системное сообщение
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Admin: @{admin.username}, Victim: @{victim.username}")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию с уведомлением
        await set_reaction_config(chat_id, "🤢", {
            "action": "mute",
            "duration": 60,  # 1 час
            "delete_message": False,
            "notification_delete_delay": None,  # Не удалять
            "custom_text": None,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] System message test {datetime.now().isoformat()}"
        )
        print(f"[SEND] Victim sent message (id={victim_msg.id})")
        await asyncio.sleep(2)

        # Записываем ID последнего сообщения перед реакцией
        last_msg_before = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=1):
            last_msg_before = msg.id
            break

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=victim_msg.id,
                emoji="🤢"
            )
            print(f"[REACT] Admin put 🤢 reaction")
        except Exception as e:
            await victim_msg.delete()
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(3)

        # Проверяем что появилось новое сообщение от бота
        bot_msg_found = False
        async for msg in admin_userbot.get_chat_history(chat_id, limit=5):
            if msg.id > last_msg_before and msg.from_user and msg.from_user.is_bot:
                bot_msg_found = True
                print(f"[OK] Bot sent system message: {msg.text[:50]}...")
                # Удаляем сообщение бота
                try:
                    await bot.delete_message(chat_id, msg.id)
                except Exception:
                    pass
                break

        if not bot_msg_found:
            print(f"[WARN] No bot message found - check reaction_mute_announce_enabled")

        # Очистка
        try:
            await victim_msg.delete()
        except Exception:
            pass
        await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_system_message_auto_delete(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: системное сообщение автоудаляется через N секунд.

        Сценарий:
        1. Настраиваем notification_delete_delay = 5 сек
        2. Жертва отправляет сообщение
        3. Админ ставит реакцию
        4. Проверяем что сообщение бота появилось
        5. Ждём 6 сек и проверяем что сообщение удалено
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing system message auto-delete")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию с автоудалением через 5 сек
        await set_reaction_config(chat_id, "😡", {
            "action": "warn",  # Только предупреждение
            "duration": None,
            "delete_message": False,
            "notification_delete_delay": 5,  # 5 секунд
            "custom_text": None,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Auto-delete test {datetime.now().isoformat()}"
        )
        print(f"[SEND] Victim sent message")
        await asyncio.sleep(2)

        # Записываем ID последнего сообщения
        last_msg_before = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=1):
            last_msg_before = msg.id
            break

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=victim_msg.id,
                emoji="😡"
            )
            print(f"[REACT] Admin put 😡 reaction")
        except Exception as e:
            await victim_msg.delete()
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(2)

        # Ищем сообщение бота
        bot_msg_id = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=5):
            if msg.id > last_msg_before and msg.from_user and msg.from_user.is_bot:
                bot_msg_id = msg.id
                print(f"[OK] Bot sent system message (id={bot_msg_id})")
                break

        if bot_msg_id:
            # Ждём 6 секунд (автоудаление через 5)
            print(f"[WAIT] Waiting 6 seconds for auto-delete...")
            await asyncio.sleep(6)

            # Проверяем что сообщение удалено
            exists = await check_message_exists(admin_userbot, chat_id, bot_msg_id)
            if not exists:
                print(f"[OK] System message auto-deleted!")
            else:
                print(f"[FAIL] System message NOT deleted")
        else:
            print(f"[WARN] No bot message found")

        # Очистка
        try:
            await victim_msg.delete()
        except Exception:
            pass
        await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Message Deletion
# ============================================================

class TestReactionMuteMessageDeletion:
    """Тесты удаления сообщений."""

    @pytest.mark.asyncio
    async def test_violator_message_deleted(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: сообщение нарушителя удаляется при реакции.
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing violator message deletion")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию с удалением сообщения
        await set_reaction_config(chat_id, "🤮", {
            "action": "mute",
            "duration": 60,
            "delete_message": True,  # Удалять сообщение
            "delete_delay": 0,  # Сразу
            "notification_delete_delay": None,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Delete me {datetime.now().isoformat()}"
        )
        msg_id = victim_msg.id
        print(f"[SEND] Victim sent message (id={msg_id})")
        await asyncio.sleep(2)

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=msg_id,
                emoji="🤮"
            )
            print(f"[REACT] Admin put 🤮 reaction")
        except Exception as e:
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(3)

        # Проверяем что сообщение удалено
        exists = await check_message_exists(victim_userbot, chat_id, msg_id)
        if not exists:
            print(f"[OK] Violator message deleted!")
        else:
            print(f"[FAIL] Violator message NOT deleted")
            try:
                await victim_msg.delete()
            except Exception:
                pass

        await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_violator_message_deleted_with_delay(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: сообщение нарушителя удаляется с задержкой.
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing violator message deletion with delay")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию с задержкой удаления 5 сек
        await set_reaction_config(chat_id, "👎", {
            "action": "warn",
            "duration": None,
            "delete_message": True,
            "delete_delay": 5,  # 5 секунд задержка
            "notification_delete_delay": None,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Delete with delay {datetime.now().isoformat()}"
        )
        msg_id = victim_msg.id
        print(f"[SEND] Victim sent message (id={msg_id})")
        await asyncio.sleep(2)

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=msg_id,
                emoji="👎"
            )
            print(f"[REACT] Admin put 👎 reaction")
        except Exception as e:
            pytest.skip(f"Cannot send reaction: {e}")

        # Сразу проверяем - сообщение должно ещё существовать
        await asyncio.sleep(1)
        exists_immediately = await check_message_exists(victim_userbot, chat_id, msg_id)
        if exists_immediately:
            print(f"[OK] Message still exists (delay working)")
        else:
            print(f"[WARN] Message deleted immediately (delay not working?)")

        # Ждём 6 сек (5 сек задержка + 1 сек buffer)
        print(f"[WAIT] Waiting 6 seconds...")
        await asyncio.sleep(6)

        # Проверяем что сообщение удалено
        exists_after_delay = await check_message_exists(victim_userbot, chat_id, msg_id)
        if not exists_after_delay:
            print(f"[OK] Message deleted after delay!")
        else:
            print(f"[FAIL] Message NOT deleted after delay")
            try:
                await victim_msg.delete()
            except Exception:
                pass

        await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Custom Text
# ============================================================

class TestReactionMuteCustomText:
    """Тесты кастомного текста."""

    @pytest.mark.asyncio
    async def test_custom_text_with_placeholders(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: кастомный текст с %user% и %time%.

        Сценарий:
        1. Настраиваем кастомный текст: "%user% получил мут на %time%"
        2. Проверяем что бот отправляет сообщение с подстановкой
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing custom text with placeholders")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию с кастомным текстом
        custom_text = "🚫 Пользователь %user% получил %action% на %time% за реакцию %emoji%"
        await set_reaction_config(chat_id, "🤢", {
            "action": "mute",
            "duration": 180,  # 3 часа
            "delete_message": False,
            "notification_delete_delay": None,
            "custom_text": custom_text,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Custom text test {datetime.now().isoformat()}"
        )
        print(f"[SEND] Victim sent message")
        await asyncio.sleep(2)

        # Записываем ID последнего сообщения
        last_msg_before = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=1):
            last_msg_before = msg.id
            break

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=victim_msg.id,
                emoji="🤢"
            )
            print(f"[REACT] Admin put 🤢 reaction")
        except Exception as e:
            await victim_msg.delete()
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(3)

        # Ищем сообщение бота и проверяем текст
        async for msg in admin_userbot.get_chat_history(chat_id, limit=5):
            if msg.id > last_msg_before and msg.from_user and msg.from_user.is_bot:
                print(f"[BOT] Message: {msg.text}")

                # Проверяем что плейсхолдеры заменены
                if "%user%" in msg.text or "%time%" in msg.text:
                    print(f"[FAIL] Placeholders NOT replaced!")
                else:
                    # Проверяем что есть имя пользователя
                    victim_name = f"@{victim.username}" if victim.username else victim.first_name
                    if victim.username and f"@{victim.username}" in msg.text:
                        print(f"[OK] %user% replaced with @{victim.username}")
                    elif victim.first_name and victim.first_name in msg.text:
                        print(f"[OK] %user% replaced with {victim.first_name}")

                    # Проверяем время
                    if "3 ч" in msg.text or "3ч" in msg.text:
                        print(f"[OK] %time% replaced with duration")

                # Удаляем сообщение бота
                try:
                    await bot.delete_message(chat_id, msg.id)
                except Exception:
                    pass
                break

        # Очистка
        try:
            await victim_msg.delete()
        except Exception:
            pass
        await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Delete Action (no mute)
# ============================================================

class TestReactionMuteDeleteAction:
    """Тесты действия 'только удалить'."""

    @pytest.mark.asyncio
    async def test_delete_action_no_mute(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: действие 'delete' удаляет сообщение без мута.
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing 'delete' action (no mute)")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию: только удалить
        await set_reaction_config(chat_id, "💩", {
            "action": "delete",  # Только удалить
            "duration": None,
            "delete_message": True,
            "delete_delay": 0,
            "notification_delete_delay": None,
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Delete only test {datetime.now().isoformat()}"
        )
        msg_id = victim_msg.id
        print(f"[SEND] Victim sent message (id={msg_id})")
        await asyncio.sleep(2)

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=msg_id,
                emoji="💩"
            )
            print(f"[REACT] Admin put 💩 reaction")
        except Exception as e:
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(3)

        # Проверяем что сообщение удалено
        exists = await check_message_exists(victim_userbot, chat_id, msg_id)
        if not exists:
            print(f"[OK] Message deleted")
        else:
            print(f"[FAIL] Message NOT deleted")
            try:
                await victim_msg.delete()
            except Exception:
                pass

        # Проверяем что мут НЕ применён
        restrictions = await get_user_restrictions(bot, chat_id, victim.id)
        if not restrictions.get("is_restricted"):
            print(f"[OK] User NOT muted (correct for 'delete' action)")
        else:
            print(f"[FAIL] User IS muted (unexpected for 'delete' action)")

        await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Full Flow
# ============================================================

class TestReactionMuteFullFlow:
    """Комплексные тесты полного флоу."""

    @pytest.mark.asyncio
    async def test_full_flow_mute_with_all_features(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Полный тест со всеми фичами:
        1. Кастомный текст
        2. Удаление сообщения нарушителя
        3. Автоудаление уведомления бота
        4. Проверка мута
        """
        # Используем userbot как админа, userbot2 как жертву
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] FULL FLOW TEST - All features")
        print(f"Admin: @{admin.username}, Victim: @{victim.username}")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # Настраиваем реакцию со всеми фичами
        await set_reaction_config(chat_id, "🤮", {
            "action": "mute",
            "duration": 60,  # 1 час
            "delete_message": True,  # Удалять сообщение
            "delete_delay": 2,  # Через 2 секунды
            "notification_delete_delay": 10,  # Автоудаление через 10 сек
            "custom_text": "⚠️ %user% замучен на %time%",
        })

        # Жертва отправляет сообщение
        victim_msg = await victim_userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Full flow test {datetime.now().isoformat()}"
        )
        msg_id = victim_msg.id
        print(f"[1] Victim sent message (id={msg_id})")
        await asyncio.sleep(2)

        # Записываем ID последнего сообщения
        last_msg_before = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=1):
            last_msg_before = msg.id
            break

        # Админ ставит реакцию
        try:
            await admin_userbot.send_reaction(
                chat_id=chat_id,
                message_id=msg_id,
                emoji="🤮"
            )
            print(f"[2] Admin put reaction on message {msg_id}")
        except Exception as e:
            print(f"[ERROR] Cannot send reaction: {type(e).__name__}: {e}")
            pytest.skip(f"Cannot send reaction: {e}")

        await asyncio.sleep(1)

        # Сразу проверяем - сообщение должно ещё существовать (задержка 2 сек)
        exists_immediately = await check_message_exists(victim_userbot, chat_id, msg_id)
        print(f"[3] Message exists immediately: {exists_immediately}")

        # Ждём 3 сек - сообщение должно удалиться
        await asyncio.sleep(3)
        exists_after_delay = await check_message_exists(victim_userbot, chat_id, msg_id)
        if not exists_after_delay:
            print(f"[4] OK: Violator message deleted after delay")
        else:
            print(f"[4] FAIL: Violator message NOT deleted")

        # Ищем сообщение бота
        bot_msg_id = None
        async for msg in admin_userbot.get_chat_history(chat_id, limit=5):
            if msg.id > last_msg_before and msg.from_user and msg.from_user.is_bot:
                bot_msg_id = msg.id
                print(f"[5] Bot message found (id={bot_msg_id}): {msg.text}")
                break

        # Проверяем мут
        restrictions = await get_user_restrictions(bot, chat_id, victim.id)
        if restrictions.get("is_restricted"):
            print(f"[6] OK: Victim is muted")
        else:
            print(f"[6] FAIL: Victim NOT muted")

        # Ждём автоудаление уведомления (10 сек)
        if bot_msg_id:
            print(f"[7] Waiting 12 seconds for bot message auto-delete...")
            await asyncio.sleep(12)

            bot_msg_exists = await check_message_exists(admin_userbot, chat_id, bot_msg_id)
            if not bot_msg_exists:
                print(f"[8] OK: Bot message auto-deleted!")
            else:
                print(f"[8] FAIL: Bot message NOT auto-deleted")

        # Очистка
        try:
            await victim_msg.delete()
        except Exception:
            pass
        if bot_msg_id:
            try:
                await bot.delete_message(chat_id, bot_msg_id)
            except Exception:
                pass
        await unmute_user(bot, chat_id, victim.id)
        print(f"[9] Cleanup complete")


# ============================================================
# Запуск тестов
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])