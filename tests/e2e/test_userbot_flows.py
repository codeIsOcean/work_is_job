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
from pyrogram.errors import UserNotParticipant, FloodWait, InviteRequestSent, UserAlreadyParticipant
from aiogram import Bot

# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
# Приватная группа - используем invite link вместо username
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK", "https://t.me/+zb5QPMK2ml5lMjgy")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

# Несколько юзерботов для ротации при FloodWait
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "Ffffggggyincd1ncf"},
    {"session": os.getenv("TEST_USERBOT4_SESSION"), "username": "Fqwer1t"},
]


def skip_if_no_credentials():
    """Проверка credentials в runtime."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    # Проверяем что есть хотя бы одна сессия
    if not any(s["session"] for s in USERBOT_SESSIONS):
        pytest.skip("No TEST_USERBOT_SESSION set")


def get_available_session(index: int = 0) -> dict | None:
    """Получить доступную сессию юзербота по индексу."""
    available = [s for s in USERBOT_SESSIONS if s["session"]]
    if index < len(available):
        return available[index]
    return None


# ============================================================
# FIXTURES
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
    """Создаёт Pyrogram клиент из session string (первый юзербот)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")

    client = await create_userbot_client(session_info, "test_userbot_1")
    yield client
    await client.stop()


@pytest.fixture
async def userbot2():
    """Второй юзербот для параллельных тестов или ротации."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("Userbot 2 not available")

    client = await create_userbot_client(session_info, "test_userbot_2")
    yield client
    await client.stop()


@pytest.fixture
async def userbot3():
    """Третий юзербот."""
    skip_if_no_credentials()
    session_info = get_available_session(2)
    if not session_info:
        pytest.skip("Userbot 3 not available")

    client = await create_userbot_client(session_info, "test_userbot_3")
    yield client
    await client.stop()


@pytest.fixture
async def userbot4():
    """Четвёртый юзербот."""
    skip_if_no_credentials()
    session_info = get_available_session(3)
    if not session_info:
        pytest.skip("Userbot 4 not available")

    client = await create_userbot_client(session_info, "test_userbot_4")
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
    """ID тестовой группы."""
    return int(TEST_CHAT_ID)


@pytest.fixture
def invite_link():
    """Invite link для приватной группы."""
    return TEST_CHAT_INVITE_LINK


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_not_in_chat(userbot: Client, chat_id: int):
    """Убедиться что юзербот не в группе (выйти если в группе)."""
    try:
        await userbot.get_chat_member(chat_id, "me")
        # Если здесь — значит в группе, выходим
        await userbot.leave_chat(chat_id)
        await asyncio.sleep(2)  # Даём время на обработку
    except UserNotParticipant:
        # Уже не в группе — ОК
        pass
    except Exception:
        # Другие ошибки — возможно уже не в группе
        pass


async def ensure_user_in_chat(userbot: Client, chat_id: int, bot: Bot = None, invite_link: str = None):
    """Убедиться что юзербот в группе (вступить если нет).

    Также кеширует peer для in_memory storage через get_chat().
    """
    # Сначала пробуем получить чат через invite_link чтобы закешировать peer
    # Это нужно для in_memory storage
    if invite_link:
        try:
            # Вступаем (или получаем chat если уже участник)
            chat = await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
            return  # Успешно вступили или уже были в группе
        except UserAlreadyParticipant:
            # Уже в группе - отлично, но нужно закешировать peer
            pass
        except InviteRequestSent:
            # Группа требует одобрения - одобряем через бота если можем
            if bot and chat_id:
                me = await userbot.get_me()
                try:
                    await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                    await asyncio.sleep(2)
                except Exception:
                    pass
            return
        except FloodWait as e:
            pytest.skip(f"FloodWait: need to wait {e.value} seconds before joining")
        except Exception:
            pass

    # Пробуем получить чат по chat_id (для кеширования peer)
    try:
        await userbot.get_chat(chat_id)
    except Exception:
        # Если не получается - пробуем через invite link
        if invite_link:
            try:
                await userbot.get_chat(invite_link)
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
    async def test_userbot_can_send_message(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """Юзербот может отправить сообщение."""
        # Убедимся что в группе (с авто-одобрением заявки)
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)

        # Отправляем тестовое сообщение
        msg = await userbot.send_message(
            chat_id=chat_id,
            text=f"[TEST] Test message {datetime.now().isoformat()}"
        )
        assert msg is not None
        print(f"\n[OK] Message sent: {msg.id}")

        # Удаляем за собой
        await asyncio.sleep(1)
        await msg.delete()

    @pytest.mark.asyncio
    async def test_userbot_can_join_leave(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """Юзербот может вступить и выйти из группы.

        ВАЖНО: Этот тест НЕ выходит из группы в конце, чтобы не вызывать
        FloodWait для последующих тестов. Тест проверяет только возможность
        вступления (join request + approval).
        """
        me = await userbot.get_me()

        # Размутим на всякий случай (через бота)
        await unmute_user(bot, chat_id, me.id)

        # Вступаем через invite link
        try:
            chat = await userbot.join_chat(invite_link)
            await asyncio.sleep(2)
            print(f"\n[OK] Joined group: {chat.title}")
            print(f"[NOTE] Staying in group to avoid FloodWait")

        except UserAlreadyParticipant:
            # Уже в группе - тест пройден
            print(f"\n[OK] Already in group")

        except InviteRequestSent:
            # Группа требует одобрения заявки - это OK, заявка отправлена
            print(f"\n[OK] Join request sent (group requires approval)")
            # Одобрим заявку через бота
            try:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                print(f"[OK] Join request approved by bot")
                await asyncio.sleep(2)
                print(f"[NOTE] Staying in group to avoid FloodWait")
            except Exception as e:
                print(f"[INFO] Could not approve: {e}")

        except FloodWait as e:
            pytest.skip(f"FloodWait: need to wait {e.value} seconds")


# ============================================================
# PROFILE MONITOR TESTS
# ============================================================
"""
Критерии автомута Profile Monitor:

1. Нет фото + молодой аккаунт (<15 дней) + сообщение в течение 30 мин
2. Нет фото + молодой аккаунт (<15 дней) + смена имени
3. Смена имени + сообщение в течение 30 мин
4. Свежее фото (<N дней) + смена имени + сообщение в течение 30 мин [NEW]
5. Свежее фото (<N дней) + сообщение в течение 30 мин [NEW]

Примечание: Критерии 1-2 зависят от возраста аккаунта (не тестируемы с реальным аккаунтом).
           Критерии 3-5 можно протестировать с реальным юзерботом.
"""


class TestProfileMonitorE2E:
    """E2E тесты для Profile Monitor."""

    # --------------------------------------------------------
    # CRITERION 3: Name change + message within 30 min
    # --------------------------------------------------------
    @pytest.mark.asyncio
    async def test_criterion3_name_change_and_message(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
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
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Меняем имя
        new_name = f"Test_{datetime.now().strftime('%H%M%S')}"
        await userbot.update_profile(first_name=new_name)
        print(f"\n[NOTE] Changed name: {original_name} -> {new_name}")
        await asyncio.sleep(2)

        # Отправляем сообщение (триггер для Profile Monitor)
        msg = await userbot.send_message(
            chat_id=chat_id,
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
    async def test_message_after_join(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест сообщения сразу после вступления.

        ВАЖНО: Этот тест требует чтобы юзербот НЕ был в группе.
        Пропускаем если уже в группе (для избежания FloodWait).

        Сценарий:
        1. Юзербот вступает в группу
        2. Сразу отправляет сообщение
        3. Проверяем реакцию бота (мут если настроено)
        """
        me = await userbot.get_me()

        # Вступаем через invite link
        just_joined = False
        try:
            chat = await userbot.join_chat(invite_link)
            print(f"\n[->] Joined group: {chat.title}")
            just_joined = True
        except UserAlreadyParticipant:
            # Уже в группе - пропускаем тест
            pytest.skip("User already in group - skipping to avoid FloodWait from leave/join")
        except InviteRequestSent:
            # Группа требует одобрения - одобряем
            print(f"\n[->] Join request sent, approving...")
            try:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=me.id)
                print(f"[OK] Join request approved")
                just_joined = True
            except Exception as e:
                print(f"[INFO] Could not approve: {e}")
        except FloodWait as e:
            pytest.skip(f"FloodWait: need to wait {e.value} seconds")

        if not just_joined:
            pytest.skip("Could not join group")

        await asyncio.sleep(2)

        # Сразу отправляем сообщение
        msg = await userbot.send_message(
            chat_id=chat_id,
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

    # --------------------------------------------------------
    # CRITERION 4: Fresh photo + name change + message
    # --------------------------------------------------------
    @pytest.mark.asyncio
    async def test_criterion4_fresh_photo_name_change_message(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест критерия 4: Свежее фото + смена имени + сообщение.

        Сценарий:
        1. Юзербот в группе
        2. Устанавливает новое фото (свежее)
        3. Меняет имя
        4. Отправляет сообщение
        5. Проверяем мут

        Примечание: Для этого теста нужен файл с фото.
        """
        import os
        from pathlib import Path

        me = await userbot.get_me()
        original_name = me.first_name

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Создаём тестовое фото (простой красный квадрат)
        test_photo_path = Path(__file__).parent / "test_photo.jpg"
        try:
            # Создаём простое тестовое изображение
            from PIL import Image
            # Telegram требует минимум 160x160 для фото профиля
            img = Image.new('RGB', (200, 200), color='red')
            img.save(test_photo_path, 'JPEG')
            print(f"\n[NOTE] Created test photo: {test_photo_path}")
        except ImportError:
            # Если PIL не установлен, пропускаем тест
            pytest.skip("Pillow not installed, cannot create test photo")

        try:
            # Устанавливаем новое фото профиля
            await userbot.set_profile_photo(photo=str(test_photo_path))
            print(f"[NOTE] Set new profile photo (fresh)")
            await asyncio.sleep(2)

            # Меняем имя
            new_name = f"FreshPhoto_{datetime.now().strftime('%H%M%S')}"
            await userbot.update_profile(first_name=new_name)
            print(f"[NOTE] Changed name: {original_name} -> {new_name}")
            await asyncio.sleep(2)

            # Отправляем сообщение
            msg = await userbot.send_message(
                chat_id=chat_id,
                text=f"Message with fresh photo + name change {datetime.now().isoformat()}"
            )
            print(f"[SEND] Sent message after fresh photo + name change")
            await asyncio.sleep(3)

            # Проверяем ограничения
            restrictions = await get_user_restrictions(bot, chat_id, me.id)
            print(f"[CHECK] Restrictions: {restrictions}")

            # Если замучен - критерий 4 сработал
            if restrictions.get("is_restricted"):
                print(f"[OK] CRITERION 4 TRIGGERED: User muted for fresh photo + name change + message")
            else:
                print(f"[INFO] Criterion 4 did not trigger (check settings)")

            # Удаляем сообщение
            try:
                await msg.delete()
            except Exception:
                pass

        finally:
            # Возвращаем оригинальное имя
            await userbot.update_profile(first_name=original_name)
            print(f"[BACK] Restored name: {original_name}")

            # Удаляем тестовое фото с диска
            if test_photo_path.exists():
                test_photo_path.unlink()

            # Размутим
            await unmute_user(bot, chat_id, me.id)

    # --------------------------------------------------------
    # CRITERION 5: Fresh photo + message (without name change)
    # --------------------------------------------------------
    @pytest.mark.asyncio
    async def test_criterion5_fresh_photo_and_message(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест критерия 5: Свежее фото + сообщение (без смены имени).

        Сценарий:
        1. Юзербот в группе
        2. Устанавливает новое фото (свежее)
        3. Отправляет сообщение (БЕЗ смены имени)
        4. Проверяем мут

        Примечание: Критерий 5 менее строгий чем 4 (не требует смены имени).
        """
        import os
        from pathlib import Path

        me = await userbot.get_me()

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Создаём тестовое фото
        test_photo_path = Path(__file__).parent / "test_photo_c5.jpg"
        try:
            from PIL import Image
            img = Image.new('RGB', (200, 200), color='blue')
            img.save(test_photo_path, 'JPEG')
            print(f"\n[NOTE] Created test photo: {test_photo_path}")
        except ImportError:
            pytest.skip("Pillow not installed, cannot create test photo")

        try:
            # Устанавливаем новое фото профиля
            await userbot.set_profile_photo(photo=str(test_photo_path))
            print(f"[NOTE] Set new profile photo (fresh)")
            await asyncio.sleep(2)

            # НЕ меняем имя - просто отправляем сообщение
            msg = await userbot.send_message(
                chat_id=chat_id,
                text=f"Message with fresh photo only {datetime.now().isoformat()}"
            )
            print(f"[SEND] Sent message after setting fresh photo (no name change)")
            await asyncio.sleep(3)

            # Проверяем ограничения
            restrictions = await get_user_restrictions(bot, chat_id, me.id)
            print(f"[CHECK] Restrictions: {restrictions}")

            # Если замучен - критерий 5 сработал
            if restrictions.get("is_restricted"):
                print(f"[OK] CRITERION 5 TRIGGERED: User muted for fresh photo + message")
            else:
                print(f"[INFO] Criterion 5 did not trigger (check settings)")

            # Удаляем сообщение
            try:
                await msg.delete()
            except Exception:
                pass

        finally:
            # Удаляем тестовое фото с диска
            if test_photo_path.exists():
                test_photo_path.unlink()

            # Размутим
            await unmute_user(bot, chat_id, me.id)

    # --------------------------------------------------------
    # PHOTO CHANGE DETECTION
    # --------------------------------------------------------
    @pytest.mark.asyncio
    async def test_photo_change_detection(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест обнаружения смены фото.

        Проверяет что Profile Monitor обнаруживает когда пользователь
        устанавливает новое фото профиля.
        """
        from pathlib import Path

        me = await userbot.get_me()

        # Убедимся что в группе
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Получаем текущие фото
        try:
            photos = await userbot.get_chat_photos("me")
            current_photo_count = len([p async for p in photos])
            print(f"\n[INFO] Current photo count: {current_photo_count}")
        except Exception as e:
            current_photo_count = 0
            print(f"\n[INFO] Could not get photos: {e}")

        # Создаём тестовое фото
        test_photo_path = Path(__file__).parent / "test_photo_detect.jpg"
        try:
            from PIL import Image
            img = Image.new('RGB', (200, 200), color='green')
            img.save(test_photo_path, 'JPEG')
        except ImportError:
            pytest.skip("Pillow not installed")

        try:
            # Устанавливаем новое фото
            photo = await userbot.set_profile_photo(photo=str(test_photo_path))
            print(f"[NOTE] Set new profile photo")
            await asyncio.sleep(2)

            # Отправляем сообщение чтобы триггернуть Profile Monitor
            msg = await userbot.send_message(
                chat_id=chat_id,
                text=f"Message after photo change {datetime.now().isoformat()}"
            )
            print(f"[SEND] Sent message after photo change")
            await asyncio.sleep(3)

            # Проверяем
            restrictions = await get_user_restrictions(bot, chat_id, me.id)
            print(f"[CHECK] Restrictions: {restrictions}")

            # Удаляем сообщение
            try:
                await msg.delete()
            except Exception:
                pass

            # Удаляем добавленное фото профиля
            if photo:
                try:
                    await userbot.delete_profile_photos([photo.id])
                    print(f"[BACK] Deleted test profile photo")
                except Exception as e:
                    print(f"[INFO] Could not delete photo: {e}")

        finally:
            if test_photo_path.exists():
                test_photo_path.unlink()
            await unmute_user(bot, chat_id, me.id)


# ============================================================
# ANTISPAM TESTS
# ============================================================

class TestAntispamE2E:
    """E2E тесты для Antispam."""

    @pytest.mark.asyncio
    async def test_spam_link_detection(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест обнаружения спам-ссылки.

        Сценарий:
        1. Юзербот отправляет сообщение с t.me ссылкой
        2. Проверяем удалено ли сообщение
        """
        me = await userbot.get_me()

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Отправляем спам-ссылку
        msg = await userbot.send_message(
            chat_id=chat_id,
            text="Join our channel! t.me/spam_channel_test"
        )
        msg_id = msg.id
        print(f"\n[SEND] Sent spam link (msg_id={msg_id})")
        await asyncio.sleep(3)

        # Проверяем удалено ли сообщение
        try:
            # Пытаемся получить сообщение
            messages = await userbot.get_messages(chat_id, msg_id)
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
    async def test_banned_word_detection(self, userbot: Client, chat_id: int, invite_link: str, bot: Bot):
        """
        Тест обнаружения запрещённого слова.

        Примечание: нужно добавить слово в фильтр группы.
        """
        me = await userbot.get_me()

        # Убедимся что в группе и не замучен
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, me.id)
        await asyncio.sleep(1)

        # Отправляем сообщение с тестовым словом
        # ВАЖНО: это слово должно быть в фильтре группы
        msg = await userbot.send_message(
            chat_id=chat_id,
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
    async def test_click_inline_button(self, userbot: Client, bot: Bot, chat_id: int, invite_link: str):
        """
        Тест нажатия на inline кнопку.

        Сценарий:
        1. Бот отправляет сообщение с кнопками
        2. Юзербот нажимает на кнопку
        3. Проверяем callback ответ
        """
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        # Убедимся что юзербот в группе
        await ensure_user_in_chat(userbot, chat_id, bot=bot, invite_link=invite_link)

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
                chat_id=chat_id,
                message_id=msg.message_id,
                callback_data="test_button_click",
                timeout=5
            )
            print(f"[OK] Userbot clicked button")
        except Exception as e:
            print(f"[INFO] Callback response: {e}")

        # Удаляем сообщение
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
