# tests/e2e/test_scam_media_e2e.py
"""
E2E тесты для модуля ScamMedia Filter.

Тестирует:
1. Добавление хеша изображения через /mutein
2. Детекция повторного изображения -> удаление/мут
3. Удаление хеша через /scamrm
4. UI настроек модуля

Запуск:
    pytest tests/e2e/test_scam_media_e2e.py -v -s

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
import io
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

# Реальные скам-изображения для тестирования (средний уровень сложности)
SCAM_IMAGES_DIR = Path(__file__).parent.parent.parent / "docs" / "image_filter"
SCAM_IMAGES = {
    "vip_kazashki": SCAM_IMAGES_DIR / "scam_vip_kazashki.jpg",
    "narcotics": SCAM_IMAGES_DIR / "scam_narcotics.jpg",
    "tiktok": SCAM_IMAGES_DIR / "scam_tiktok.jpg",
    "icos": SCAM_IMAGES_DIR / "scam_icos.jpg",
    "gaz": SCAM_IMAGES_DIR / "scam_gaz.jpg",
    "invite": SCAM_IMAGES_DIR / "scam_invite.jpg",
    "massage": SCAM_IMAGES_DIR / "home_service_massage.jpg",
}


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
    """Первый юзербот (админ - ermek0vnma)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = await create_userbot_client(session_info, "sm_test_userbot_1")
    yield client
    await client.stop()


@pytest.fixture
async def userbot2():
    """Второй юзербот (жертва - s1adkaya2292)."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("Userbot 2 not available")
    client = await create_userbot_client(session_info, "sm_test_userbot_2")
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


@pytest.fixture
async def db_session():
    """Создаёт сессию БД для тестов.

    E2E тесты запускаются на хост-машине, поэтому используем 127.0.0.1:5433
    (порт проброшен из Docker контейнера postgres_test).
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    # Для E2E тестов используем прямое подключение через проброшенный порт
    # postgres_test:5432 -> 127.0.0.1:5433
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5433")
    db_name = os.getenv("POSTGRES_DB", "jobs_inDubai_testBot")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")

    database_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        echo=False
    )

    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with async_session() as session:
        yield session


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, bot: Bot = None, invite_link: str = None):
    """Убедиться что юзербот в группе."""
    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
        except UserAlreadyParticipant:
            pass
        except FloodWait as e:
            # Ждём указанное время вместо skip
            wait_time = e.value + 5  # +5 секунд запаса
            print(f"[FloodWait] Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
            # Пробуем снова
            try:
                await userbot.join_chat(invite_link)
            except UserAlreadyParticipant:
                pass
        except Exception as e:
            print(f"[ensure_user_in_chat] join_chat error: {e}")

    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)
            print(f"[ensure_user_in_chat] Resolved chat: {chat.title}")
        else:
            await userbot.get_chat(chat_id)
    except Exception as e:
        print(f"[ensure_user_in_chat] get_chat error: {e}")


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Размутить пользователя с проверкой."""
    from aiogram.types import ChatPermissions

    try:
        # Полные права для размута
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
        )
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )
        await asyncio.sleep(1)  # Даём время на применение

        # Проверяем что размут применился
        member = await bot.get_chat_member(chat_id, user_id)
        if hasattr(member, 'status') and member.status == "restricted":
            # Пробуем ещё раз
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions
            )
            await asyncio.sleep(1)
        print(f"[UNMUTE] User {user_id} unmuted")
    except Exception as e:
        print(f"[UNMUTE] Error: {e}")


async def get_user_restrictions(bot: Bot, chat_id: int, user_id: int) -> dict:
    """Получить ограничения пользователя.

    ВАЖНО: is_restricted = True означает что пользователь НЕ может писать.
    Статус "restricted" в Telegram может сохраняться даже когда права выданы.
    Поэтому проверяем can_send_messages, а не статус.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        can_send = True
        if hasattr(member, 'can_send_messages'):
            can_send = member.can_send_messages if member.can_send_messages is not None else True

        return {
            "can_send_messages": can_send,
            # is_restricted = True только если пользователь НЕ МОЖЕТ писать
            "is_restricted": not can_send,
        }
    except Exception:
        return {"can_send_messages": True, "is_restricted": False}


async def check_message_exists(userbot: Client, chat_id: int, message_id: int) -> bool:
    """Проверяет существует ли сообщение."""
    try:
        msg = await userbot.get_messages(chat_id, message_id)
        # Pyrogram возвращает объект сообщения даже если сообщение удалено
        # Но у удалённого сообщения empty=True
        return msg and not msg.empty
    except Exception:
        return False


async def setup_scam_media_settings(session, chat_id: int, enabled: bool = True, action: str = "delete_mute"):
    """Настраивает ScamMedia модуль для группы."""
    from bot.services.scam_media import SettingsService

    # Создаём или получаем настройки
    settings = await SettingsService.get_or_create_settings(session, chat_id)

    # Обновляем настройки
    await SettingsService.update_settings(
        session,
        chat_id,
        enabled=enabled,
        action=action,
        threshold=10,  # Стандартный порог
        mute_duration=300,  # 5 минут мут
        use_global_hashes=False,
        log_to_journal=False,
        add_to_scammer_db=False,
    )
    print(f"[SETUP] ScamMedia settings: enabled={enabled}, action={action}")
    return settings


async def cleanup_scam_media_hashes(session, chat_id: int):
    """Удаляет все хеши для группы."""
    from bot.services.scam_media import BannedHashService
    from sqlalchemy import delete
    from bot.database.models_scam_media import BannedImageHash

    # Удаляем все хеши для этой группы
    await session.execute(
        delete(BannedImageHash).where(BannedImageHash.chat_id == chat_id)
    )
    await session.commit()
    print(f"[CLEANUP] Removed all scam media hashes for chat_id={chat_id}")


async def add_hash_to_db(session, chat_id: int, phash: str, dhash: str, user_id: int):
    """Добавляет хеш напрямую в БД."""
    from bot.services.scam_media import BannedHashService

    hash_entry = await BannedHashService.add_hash(
        session=session,
        phash=phash,
        dhash=dhash,
        added_by_user_id=user_id,
        added_by_username="test_admin",
        chat_id=chat_id,
        is_global=False,
        description="E2E test hash",
    )
    print(f"[DB] Added hash id={hash_entry.id}")
    return hash_entry


async def get_hash_count(session, chat_id: int) -> int:
    """Получает количество хешей для группы."""
    from bot.services.scam_media import BannedHashService
    return await BannedHashService.count_hashes(session, chat_id=chat_id)


async def compute_image_hash(image_bytes: bytes) -> tuple:
    """Вычисляет pHash и dHash изображения."""
    from bot.services.scam_media import HashService

    # Создаём экземпляр сервиса
    service = HashService()
    result = service.compute_hash(image_bytes)
    return result.phash, result.dhash


async def download_file_from_pyrogram(userbot: Client, file_id: str) -> bytes:
    """Скачивает файл через Pyrogram."""
    buffer = io.BytesIO()
    await userbot.download_media(file_id, in_memory=buffer)
    buffer.seek(0)
    return buffer.read()


# ============================================================
# TEST CLASS: ScamMedia Detection
# ============================================================

class TestScamMediaDetection:
    """Тесты детекции скам-изображений."""

    @pytest.mark.asyncio
    async def test_mutein_adds_hash_and_detects(
        self, userbot: Client, userbot2: Client, bot: Bot,
        chat_id: int, invite_link: str, db_session
    ):
        """
        Тест: /mutein добавляет хеш, повторное изображение детектится.

        Сценарий:
        1. Админ отправляет изображение
        2. Админ отвечает /mutein
        3. Жертва отправляет то же изображение
        4. Бот удаляет сообщение и мутит жертву
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

        # Настраиваем ScamMedia модуль
        await setup_scam_media_settings(db_session, chat_id, enabled=True, action="delete_mute")

        # Очищаем старые хеши
        await cleanup_scam_media_hashes(db_session, chat_id)
        await asyncio.sleep(1)

        # Используем реальное скам-изображение VIP Kazashki
        scam_image_path = SCAM_IMAGES["vip_kazashki"]
        assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"
        test_image_bytes = scam_image_path.read_bytes()

        # Админ отправляет скам-изображение
        admin_msg = await admin_userbot.send_photo(
            chat_id=chat_id,
            photo=str(scam_image_path),
            caption=f"[TEST] VIP Kazashki scam test {datetime.now().isoformat()}"
        )
        print(f"[1] Admin sent test image (id={admin_msg.id})")
        await asyncio.sleep(2)

        # Админ отвечает командой /mutein
        try:
            mutein_msg = await admin_userbot.send_message(
                chat_id=chat_id,
                text="/mutein",
                reply_to_message_id=admin_msg.id
            )
            print(f"[2] Admin sent /mutein reply")
        except Exception as e:
            # Очистка
            try:
                await admin_msg.delete()
            except:
                pass
            pytest.skip(f"Cannot send /mutein: {e}")

        # Ждём обработки команды ботом
        await asyncio.sleep(4)

        # Проверяем что хеш добавлен
        hash_count = await get_hash_count(db_session, chat_id)
        print(f"[3] Hash count after /mutein: {hash_count}")
        assert hash_count >= 1, "FAIL: Hash was not added by /mutein"

        # Жертва отправляет то же скам-изображение
        victim_msg = await victim_userbot.send_photo(
            chat_id=chat_id,
            photo=str(scam_image_path),
            caption=f"[TEST] Same VIP Kazashki scam {datetime.now().isoformat()}"
        )
        victim_msg_id = victim_msg.id
        print(f"[4] Victim sent same image (id={victim_msg_id})")

        # Ждём обработки
        await asyncio.sleep(4)

        # Проверяем что сообщение жертвы удалено
        exists = await check_message_exists(victim_userbot, chat_id, victim_msg_id)
        print(f"[5] Victim message exists: {exists}")

        # Проверяем мут жертвы
        restrictions = await get_user_restrictions(bot, chat_id, victim.id)
        print(f"[6] Victim restrictions: {restrictions}")

        # Очистка
        try:
            await admin_msg.delete()
        except:
            pass
        try:
            await mutein_msg.delete()
        except:
            pass
        await unmute_user(bot, chat_id, victim.id)
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Asserts (в конце после очистки)
        assert not exists, "FAIL: Victim message was NOT deleted"
        assert restrictions.get("is_restricted"), "FAIL: Victim was NOT muted"
        print(f"[OK] ScamMedia detection working!")

    @pytest.mark.asyncio
    async def test_scamrm_removes_hash(
        self, userbot: Client, bot: Bot,
        chat_id: int, invite_link: str, db_session
    ):
        """
        Тест: /scamrm удаляет хеш изображения.

        Сценарий:
        1. Добавляем хеш через /mutein
        2. Отвечаем /scamrm
        3. Проверяем что хеш удалён
        """
        admin_userbot = userbot
        admin = await admin_userbot.get_me()

        print(f"\n[TEST] Testing /scamrm command")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await asyncio.sleep(1)

        # Настраиваем ScamMedia модуль
        await setup_scam_media_settings(db_session, chat_id, enabled=True, action="delete")
        await cleanup_scam_media_hashes(db_session, chat_id)
        await asyncio.sleep(1)

        # Используем реальное скам-изображение (наркотики)
        scam_image_path = SCAM_IMAGES["narcotics"]
        assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"

        # Админ отправляет изображение
        admin_msg = await admin_userbot.send_photo(
            chat_id=chat_id,
            photo=str(scam_image_path),
            caption=f"[TEST] Narcotics scam for /scamrm test"
        )
        print(f"[1] Admin sent test image")
        await asyncio.sleep(2)

        # Добавляем хеш через /mutein
        mutein_msg = await admin_userbot.send_message(
            chat_id=chat_id,
            text="/mutein",
            reply_to_message_id=admin_msg.id
        )
        await asyncio.sleep(3)

        # Проверяем что хеш добавлен
        hash_count_before = await get_hash_count(db_session, chat_id)
        print(f"[2] Hash count after /mutein: {hash_count_before}")
        assert hash_count_before >= 1, "FAIL: Hash was not added"

        # Удаляем хеш через /scamrm
        scamrm_msg = await admin_userbot.send_message(
            chat_id=chat_id,
            text="/scamrm",
            reply_to_message_id=admin_msg.id
        )
        print(f"[3] Admin sent /scamrm")
        await asyncio.sleep(3)

        # Проверяем что хеш удалён
        hash_count_after = await get_hash_count(db_session, chat_id)
        print(f"[4] Hash count after /scamrm: {hash_count_after}")

        # Очистка
        try:
            await admin_msg.delete()
        except:
            pass
        try:
            await mutein_msg.delete()
        except:
            pass
        try:
            await scamrm_msg.delete()
        except:
            pass
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Assert
        assert hash_count_after < hash_count_before, "FAIL: Hash was NOT removed by /scamrm"
        print(f"[OK] /scamrm working!")

    @pytest.mark.asyncio
    async def test_module_disabled_no_filtering(
        self, userbot: Client, userbot2: Client, bot: Bot,
        chat_id: int, invite_link: str, db_session
    ):
        """
        Тест: при выключенном модуле фильтрация не работает.

        Сценарий:
        1. Добавляем хеш в БД
        2. Выключаем модуль
        3. Жертва отправляет скам-изображение
        4. Сообщение НЕ удаляется
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing disabled module")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        # ВЫКЛЮЧАЕМ модуль
        await setup_scam_media_settings(db_session, chat_id, enabled=False, action="delete_mute")
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Используем реальное скам-изображение TikTok
        scam_image_path = SCAM_IMAGES["tiktok"]
        assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"
        test_image_bytes = scam_image_path.read_bytes()

        # Вычисляем хеш
        phash, dhash = await compute_image_hash(test_image_bytes)

        # Добавляем в БД
        await add_hash_to_db(db_session, chat_id, phash, dhash, admin.id)
        print(f"[1] Added TikTok scam hash to DB, module DISABLED")

        # Жертва отправляет то же изображение - НЕ должно фильтроваться (модуль выключен)
        victim_msg = await victim_userbot.send_photo(
            chat_id=chat_id,
            photo=str(scam_image_path),
            caption=f"[TEST] TikTok scam - should NOT be filtered"
        )
        victim_msg_id = victim_msg.id
        print(f"[2] Victim sent image (id={victim_msg_id})")

        # Ждём обработки
        await asyncio.sleep(4)

        # Проверяем что сообщение НЕ удалено
        exists = await check_message_exists(victim_userbot, chat_id, victim_msg_id)
        print(f"[3] Victim message exists: {exists}")

        # Очистка
        try:
            await victim_msg.delete()
        except:
            pass
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Assert
        assert exists, "FAIL: Message was deleted despite module being DISABLED"
        print(f"[OK] Disabled module doesn't filter!")


# ============================================================
# TEST CLASS: ScamMedia Actions
# ============================================================

class TestScamMediaActions:
    """Тесты различных действий при детекции."""

    @pytest.mark.asyncio
    async def test_action_delete_only(
        self, userbot: Client, userbot2: Client, bot: Bot,
        chat_id: int, invite_link: str, db_session
    ):
        """
        Тест: действие 'delete' только удаляет без мута.
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing 'delete' action (no mute)")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)

        # ВАЖНО: Размучиваем жертву ДВАЖДЫ для надёжности
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(2)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(2)

        # Проверяем что жертва НЕ замучена перед тестом
        initial_restrictions = await get_user_restrictions(bot, chat_id, victim.id)
        print(f"[INIT] Victim initial state: {initial_restrictions}")
        assert not initial_restrictions.get("is_restricted"), "SETUP FAIL: Victim is still muted before test!"

        # Настраиваем: действие = только удалить (без мута!)
        await setup_scam_media_settings(db_session, chat_id, enabled=True, action="delete")
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Используем реальное скам-изображение ICOS
        scam_image_path = SCAM_IMAGES["icos"]
        assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"
        test_image_bytes = scam_image_path.read_bytes()

        # Добавляем хеш
        phash, dhash = await compute_image_hash(test_image_bytes)
        await add_hash_to_db(db_session, chat_id, phash, dhash, admin.id)
        print(f"[1] Added ICOS scam hash, action='delete'")

        # Жертва отправляет скам-изображение - должно быть удалено, но БЕЗ мута
        victim_msg = await victim_userbot.send_photo(
            chat_id=chat_id,
            photo=str(scam_image_path),
            caption=f"[TEST] ICOS scam - delete only test"
        )
        victim_msg_id = victim_msg.id
        print(f"[2] Victim sent image")

        await asyncio.sleep(4)

        # Проверки
        exists = await check_message_exists(victim_userbot, chat_id, victim_msg_id)
        restrictions = await get_user_restrictions(bot, chat_id, victim.id)

        print(f"[3] Message exists: {exists}, Muted: {restrictions.get('is_restricted')}")

        # Очистка
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Asserts
        assert not exists, "FAIL: Message was NOT deleted"
        assert not restrictions.get("is_restricted"), "FAIL: User was muted (unexpected for 'delete' action)"
        print(f"[OK] 'delete' action works correctly!")


# ============================================================
# TEST CLASS: Hash Matching
# ============================================================

class TestScamMediaHashMatching:
    """Тесты сравнения хешей."""

    @pytest.mark.asyncio
    async def test_slightly_modified_image_detected(
        self, userbot: Client, userbot2: Client, bot: Bot,
        chat_id: int, invite_link: str, db_session
    ):
        """
        Тест: слегка изменённое изображение всё равно детектится.

        Сценарий:
        1. Добавляем хеш оригинального изображения
        2. Жертва отправляет слегка изменённую версию (resize)
        3. Изображение всё равно детектится
        """
        admin_userbot = userbot
        victim_userbot = userbot2
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()

        print(f"\n[TEST] Testing detection of modified image")

        # Подготовка
        await ensure_user_in_chat(admin_userbot, chat_id, bot=bot, invite_link=invite_link)
        await ensure_user_in_chat(victim_userbot, chat_id, bot=bot, invite_link=invite_link)
        await unmute_user(bot, chat_id, victim.id)
        await asyncio.sleep(1)

        await setup_scam_media_settings(db_session, chat_id, enabled=True, action="delete")
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Используем реальное скам-изображение GAZ
        from PIL import Image
        scam_image_path = SCAM_IMAGES["gaz"]
        assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"
        original_bytes = scam_image_path.read_bytes()

        # Добавляем хеш оригинала
        phash, dhash = await compute_image_hash(original_bytes)
        await add_hash_to_db(db_session, chat_id, phash, dhash, admin.id)
        print(f"[1] Added GAZ scam original hash")

        # Создаём модифицированную версию (resize + небольшое изменение)
        original_img = Image.open(scam_image_path)
        # Изменяем размер на 90%
        new_size = (int(original_img.width * 0.9), int(original_img.height * 0.9))
        modified = original_img.resize(new_size)

        modified_buffer = io.BytesIO()
        modified.save(modified_buffer, format='JPEG', quality=85)
        modified_buffer.seek(0)

        # Жертва отправляет модифицированную версию - должна быть детектирована!
        victim_msg = await victim_userbot.send_photo(
            chat_id=chat_id,
            photo=modified_buffer,
            caption=f"[TEST] Modified GAZ scam (resized 90%)"
        )
        victim_msg_id = victim_msg.id
        print(f"[2] Victim sent modified image")

        await asyncio.sleep(4)

        # Проверка
        exists = await check_message_exists(victim_userbot, chat_id, victim_msg_id)
        print(f"[3] Modified image message exists: {exists}")

        # Очистка
        await cleanup_scam_media_hashes(db_session, chat_id)

        # Assert
        assert not exists, "FAIL: Modified image was NOT detected (perceptual hashing should catch it)"
        print(f"[OK] Modified image detected!")


# ============================================================
# Запуск тестов
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])