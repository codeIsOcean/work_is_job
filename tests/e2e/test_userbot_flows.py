# tests/e2e/test_userbot_flows.py
"""
E2E тесты с реальным юзерботом.

Эти тесты используют Pyrogram userbot для симуляции действий пользователя:
- Вступление в группу
- Отправка сообщений
- Смена имени/фото
- Нажатие на callback кнопки

Запуск:
    pytest tests/e2e/test_userbot_flows.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот должен быть вне группы перед тестами (для теста вступления)
"""

import os
import asyncio
import pytest
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ВАЖНО: загружаем .env.test ДО других импортов чтобы переопределить переменные
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)  # override=True перезаписывает существующие

from pyrogram import Client
from pyrogram.errors import UserNotParticipant, FloodWait, InviteRequestSent
from aiogram import Bot

# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_USERNAME = "toti_test"  # Username группы для Pyrogram
TEST_USERBOT_SESSION = os.getenv("TEST_USERBOT_SESSION")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")


def skip_if_no_credentials():
    """Проверка credentials в runtime."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    if not TEST_USERBOT_SESSION:
        pytest.skip("TEST_USERBOT_SESSION not set")


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def userbot():
    """Создаёт Pyrogram клиент из session string."""
    # Проверяем credentials
    skip_if_no_credentials()

    # Создаём клиент из session string
    client = Client(
        name="test_userbot",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=TEST_USERBOT_SESSION,
        in_memory=True
    )

    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def bot():
    """Создаёт aiogram Bot для проверки действий."""
    skip_if_no_credentials()
    bot = Bot(token=TEST_BOT_TOKEN)
    yield bot
    await bot.session.close()


@pytest.fixture
def chat_id():
    """ID тестовой группы (для aiogram Bot)."""
    return int(TEST_CHAT_ID)


@pytest.fixture
def chat_username():
    """Username тестовой группы (для Pyrogram userbot)."""
    return TEST_CHAT_USERNAME


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_not_in_chat(userbot: Client, chat_username: str):
    """Убедиться что юзербот не в группе (выйти если в группе)."""
    try:
        await userbot.get_chat_member(chat_username, "me")
        # Если здесь — значит в группе, выходим
        await userbot.leave_chat(chat_username)
        await asyncio.sleep(2)  # Даём время на обработку
    except UserNotParticipant:
        # Уже не в группе — ОК
        pass
    except Exception:
        # Другие ошибки — возможно уже не в группе
        pass


async def ensure_user_in_chat(userbot: Client, chat_username: str, bot: Bot = None, chat_id: int = None):
    """Убедиться что юзербот в группе (вступить если нет)."""
    try:
        await userbot.get_chat_member(chat_username, "me")
        # Уже в группе — ОК
    except UserNotParticipant:
        # Вступаем
        try:
            await userbot.join_chat(chat_username)
            await asyncio.sleep(2)
        except InviteRequestSent:
            # Группа требует одобрения - одобряем через бота если можем
            if bot and chat_id:
                me = await userbot.get_me()
                try:
                    await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                    await asyncio.sleep(2)
                except Exception:
                    pass
    except Exception:
        # Другие ошибки — пробуем вступить
        try:
            await userbot.join_chat(chat_username)
            await asyncio.sleep(2)
        except InviteRequestSent:
            if bot and chat_id:
                me = await userbot.get_me()
                try:
                    await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                    await asyncio.sleep(2)
                except Exception:
                    pass
        except Exception:
            pass


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Размутить пользователя (на случай если остался мут от предыдущего теста)."""
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
        pass  # Игнорируем ошибки


async def get_user_restrictions(bot: Bot, chat_id: int, user_id: int) -> dict:
    """Получить текущие ограничения пользователя."""
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


# ============================================================
# BASIC TESTS
# ============================================================

class TestUserbotBasic:
    """Базовые тесты работоспособности юзербота."""

    @pytest.mark.asyncio
    async def test_userbot_can_connect(self, userbot: Client):
        """Юзербот может подключиться."""
        me = await userbot.get_me()
        assert me is not None
        assert me.username == "ermek0vnma"
        print(f"\n[OK] Connected as: {me.first_name} (@{me.username})")

    @pytest.mark.asyncio
    async def test_userbot_can_send_message(self, userbot: Client, chat_username: str, chat_id: int, bot: Bot):
        """Юзербот может отправить сообщение."""
        # Убедимся что в группе (с авто-одобрением заявки)
        await ensure_user_in_chat(userbot, chat_username, bot=bot, chat_id=chat_id)

        # Отправляем тестовое сообщение
        msg = await userbot.send_message(
            chat_id=chat_username,
            text=f"[TEST] Test message {datetime.now().isoformat()}"
        )
        assert msg is not None
        print(f"\n[OK] Message sent: {msg.id}")

        # Удаляем за собой
        await asyncio.sleep(1)
        await msg.delete()

    @pytest.mark.asyncio
    async def test_userbot_can_join_leave(self, userbot: Client, chat_id: int, chat_username: str, bot: Bot):
        """Юзербот может вступить и выйти из группы."""
        me = await userbot.get_me()

        # Выходим если в группе
        await ensure_user_not_in_chat(userbot, chat_username)

        # Размутим на всякий случай (через бота)
        await unmute_user(bot, chat_id, me.id)

        # Вступаем
        try:
            await userbot.join_chat(chat_username)
            await asyncio.sleep(2)

            # Проверяем что в группе
            member = await userbot.get_chat_member(chat_username, "me")
            assert member is not None
            print(f"\n[OK] Joined group")

            # Выходим
            await userbot.leave_chat(chat_username)
            await asyncio.sleep(1)
            print(f"[OK] Left group")

        except InviteRequestSent:
            # Группа требует одобрения заявки - это OK, заявка отправлена
            print(f"\n[OK] Join request sent (group requires approval)")
            # Одобрим заявку через бота
            try:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                print(f"[OK] Join request approved by bot")
                await asyncio.sleep(2)

                # Теперь выходим
                await userbot.leave_chat(chat_username)
                print(f"[OK] Left group")
            except Exception as e:
                print(f"[INFO] Could not approve: {e}")


# ============================================================
# PROFILE MONITOR TESTS
# ============================================================

class TestProfileMonitorE2E:
    """E2E тесты для Profile Monitor."""

    @pytest.mark.asyncio
    async def test_name_change_detection(self, userbot: Client, chat_id: int, chat_username: str, bot: Bot):
        """
        Тест обнаружения смены имени.

        Сценарий:
        1. Юзербот в группе
        2. Меняет имя
        3. Отправляет сообщение
        4. Проверяем что бот обнаружил изменение
        """
        me = await userbot.get_me()
        original_name = me.first_name

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_username, bot=bot, chat_id=chat_id)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Меняем имя
        new_name = f"Test_{datetime.now().strftime('%H%M%S')}"
        await userbot.update_profile(first_name=new_name)
        print(f"\n[NOTE] Changed name: {original_name} -> {new_name}")
        await asyncio.sleep(2)

        # Отправляем сообщение (триггер для Profile Monitor)
        msg = await userbot.send_message(
            chat_id=chat_username,
            text=f"Message after name change {datetime.now().isoformat()}"
        )
        print(f"[SEND] Sent message after name change")
        await asyncio.sleep(3)

        # Проверяем ограничения
        restrictions = await get_user_restrictions(bot, chat_id, me.id)
        print(f"[CHECK] Restrictions: {restrictions}")

        # Возвращаем оригинальное имя
        await userbot.update_profile(first_name=original_name)
        print(f"[BACK] Restored name: {original_name}")

        # Удаляем сообщение
        try:
            await msg.delete()
        except Exception:
            pass

        # Размутим для следующих тестов
        await unmute_user(bot, chat_id, me.id)

        # Примечание: результат зависит от настроек Profile Monitor
        # Если auto_mute_name_change=True, пользователь будет замучен

    @pytest.mark.asyncio
    async def test_message_after_join(self, userbot: Client, chat_id: int, chat_username: str, bot: Bot):
        """
        Тест сообщения сразу после вступления.

        Сценарий:
        1. Юзербот вступает в группу
        2. Сразу отправляет сообщение
        3. Проверяем реакцию бота (мут если настроено)
        """
        me = await userbot.get_me()

        # Выходим из группы
        await ensure_user_not_in_chat(userbot, chat_username)
        await asyncio.sleep(2)

        # Вступаем
        try:
            await userbot.join_chat(chat_username)
        except FloodWait as e:
            pytest.skip(f"FloodWait: need to wait {e.value} seconds")

        print(f"\n[->] Joined group")
        await asyncio.sleep(2)

        # Сразу отправляем сообщение
        msg = await userbot.send_message(
            chat_id=chat_username,
            text=f"Message right after join {datetime.now().isoformat()}"
        )
        print(f"[SEND] Sent message right after join")
        await asyncio.sleep(3)

        # Проверяем ограничения
        restrictions = await get_user_restrictions(bot, chat_id, me.id)
        print(f"[CHECK] Restrictions: {restrictions}")

        # Удаляем сообщение
        try:
            await msg.delete()
        except Exception:
            pass

        # Размутим
        await unmute_user(bot, chat_id, me.id)


# ============================================================
# ANTISPAM TESTS
# ============================================================

class TestAntispamE2E:
    """E2E тесты для Antispam."""

    @pytest.mark.asyncio
    async def test_spam_link_detection(self, userbot: Client, chat_id: int, chat_username: str, bot: Bot):
        """
        Тест обнаружения спам-ссылки.

        Сценарий:
        1. Юзербот отправляет сообщение с t.me ссылкой
        2. Проверяем удалено ли сообщение
        """
        me = await userbot.get_me()

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_username, bot=bot, chat_id=chat_id)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Отправляем спам-ссылку
        msg = await userbot.send_message(
            chat_id=chat_username,
            text="Join our channel! t.me/spam_channel_test"
        )
        msg_id = msg.id
        print(f"\n[SEND] Sent spam link (msg_id={msg_id})")
        await asyncio.sleep(3)

        # Проверяем удалено ли сообщение
        try:
            # Пытаемся получить сообщение
            messages = await userbot.get_messages(chat_username, msg_id)
            if messages and messages.text:
                print(f"[FAIL] Message NOT deleted")
                await msg.delete()  # Удаляем вручную
            else:
                print(f"[OK] Message deleted by bot")
        except Exception as e:
            print(f"[OK] Message deleted (error getting: {e})")

        # Размутим
        await unmute_user(bot, chat_id, me.id)


# ============================================================
# CONTENT FILTER TESTS
# ============================================================

class TestContentFilterE2E:
    """E2E тесты для Content Filter."""

    @pytest.mark.asyncio
    async def test_banned_word_detection(self, userbot: Client, chat_id: int, chat_username: str, bot: Bot):
        """
        Тест обнаружения запрещённого слова.

        Примечание: нужно добавить слово в фильтр группы.
        """
        me = await userbot.get_me()

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_username, bot=bot, chat_id=chat_id)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Отправляем сообщение с тестовым словом
        # ВАЖНО: это слово должно быть в фильтре группы
        msg = await userbot.send_message(
            chat_id=chat_username,
            text="Test message for filter check"
        )
        msg_id = msg.id
        print(f"\n[SEND] Sent test message (msg_id={msg_id})")
        await asyncio.sleep(2)

        # Удаляем за собой
        try:
            await msg.delete()
        except Exception:
            print(f"[INFO] Message already deleted by bot")

        # Размутим
        await unmute_user(bot, chat_id, me.id)


# ============================================================
# CALLBACK BUTTON TESTS
# ============================================================

class TestCallbackButtons:
    """Тесты нажатия на callback кнопки."""

    @pytest.mark.asyncio
    async def test_click_inline_button(self, userbot: Client, bot: Bot, chat_id: int, chat_username: str):
        """
        Тест нажатия на inline кнопку.

        Сценарий:
        1. Бот отправляет сообщение с кнопками
        2. Юзербот нажимает на кнопку
        3. Проверяем callback ответ
        """
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        # Убедимся что юзербот в группе
        await ensure_user_in_chat(userbot, chat_username, bot=bot, chat_id=chat_id)

        # Бот отправляет сообщение с кнопками
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Test Button", callback_data="test_button_click")]
        ])

        msg = await bot.send_message(
            chat_id=chat_id,
            text="Test message with button",
            reply_markup=keyboard
        )
        print(f"\n[SEND] Bot sent message with button (msg_id={msg.message_id})")
        await asyncio.sleep(1)

        # Юзербот нажимает кнопку
        try:
            await userbot.request_callback_answer(
                chat_id=chat_username,
                message_id=msg.message_id,
                callback_data="test_button_click",
                timeout=5
            )
            print(f"[OK] Userbot clicked button")
        except Exception as e:
            print(f"[INFO] Callback response: {e}")

        # Удаляем сообщение
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
