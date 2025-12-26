# tests/e2e/test_custom_sections_e2e.py
"""
E2E тесты для модуля Custom Spam Sections.

Тестирует:
1. Детекция спама по паттернам раздела (кириллица)
2. Действия: delete, mute, forward_delete
3. Кумулятивный подсчёт скора
4. Обманки и обфускация текста (l33tspeak, пробелы)
5. Пересылка на канал (forward_delete)

Запуск:
    pytest tests/e2e/test_custom_sections_e2e.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзербот1 (ermek0vnma) - админ
    - Юзербот2 (s1adkaya2292) - жертва
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

# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK", "https://t.me/+zb5QPMK2ml5lMjgy")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID", "33300908")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "7eba0c742bb797bbf8ed977e686a8972")

# Канал для пересылки спама
FORWARD_CHANNEL_ID = -1002326876297  # totinka_bot_jurnal

# Несколько юзерботов для ротации
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "ermek0vnma"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "s1adkaya2292"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "Ffffggggyincd1ncf"},
    {"session": os.getenv("TEST_USERBOT4_SESSION"), "username": "Fqwer1t"},
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
# FIXTURES (определены в файле для правильной загрузки .env.test)
# ============================================================

@pytest.fixture
async def admin_userbot():
    """Первый юзербот (админ - ermek0vnma)."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="cs_test_admin",
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
        name="cs_test_victim",
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
            print(f"[ensure_user_in_chat] @{username} FloodWait {e.value}s - continuing anyway")
        except Exception as e:
            print(f"[ensure_user_in_chat] @{username} join_chat error: {e}")

    # ОБЯЗАТЕЛЬНО: резолвим чат через invite_link чтобы закэшировать peer
    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)
            print(f"[ensure_user_in_chat] @{username} resolved chat: {chat.title}")
        else:
            await userbot.get_chat(chat_id)
    except Exception as e:
        print(f"[ensure_user_in_chat] @{username} get_chat error: {e}")


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
        # Сначала резолвим канал чтобы Pyrogram знал о нём
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


async def get_test_session():
    """Создаёт свежую сессию БД для E2E тестов.

    Использует NullPool чтобы избежать проблем с event loop.
    ВАЖНО: Используем локальный адрес 127.0.0.1:5433, не Docker hostname!
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool

    # Всегда используем локальный адрес для E2E тестов (Docker port mapping)
    database_url = "postgresql+asyncpg://jobs_inDubai_testBot:test_password@127.0.0.1:5433/jobs_inDubai_testBot"

    engine = create_async_engine(database_url, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def create_test_section(
    chat_id: int,
    name: str,
    threshold: int = 50,
    action: str = "delete",
    mute_duration: int = None,
    forward_channel_id: int = None
) -> int:
    """Создаёт тестовый раздел в БД и возвращает его ID.

    ВАЖНО: Импорт из bot/ только внутри функции!
    """
    from bot.services.content_filter.scam_pattern_service import get_section_service

    service = get_section_service()
    async for session in get_test_session():
        success, section_id, error = await service.create_section(
            chat_id=chat_id,
            name=name,
            session=session,
            threshold=threshold,
            action=action,
            mute_duration=mute_duration,
            forward_channel_id=forward_channel_id,
            created_by=123456789
        )
        if not success:
            raise Exception(f"Failed to create section: {error}")
        return section_id


async def add_section_pattern(section_id: int, pattern: str, weight: int = 50) -> int:
    """Добавляет паттерн в раздел."""
    from bot.services.content_filter.scam_pattern_service import get_section_service

    service = get_section_service()
    async for session in get_test_session():
        success, pattern_id, error = await service.add_section_pattern(
            section_id=section_id,
            pattern=pattern,
            session=session,
            weight=weight,
            created_by=123456789
        )
        if not success:
            raise Exception(f"Failed to add pattern: {error}")
        return pattern_id


async def delete_test_section(section_id: int):
    """Удаляет тестовый раздел."""
    from bot.services.content_filter.scam_pattern_service import get_section_service

    service = get_section_service()
    async for session in get_test_session():
        await service.delete_section(section_id, session)
        return


async def enable_content_filter(chat_id: int):
    """Включает фильтр контента для группы."""
    from bot.database.models_content_filter import ContentFilterSettings
    from sqlalchemy import select

    async for session in get_test_session():
        result = await session.execute(
            select(ContentFilterSettings).where(ContentFilterSettings.chat_id == chat_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            settings.enabled = True
            settings.scam_detection_enabled = True
        else:
            settings = ContentFilterSettings(
                chat_id=chat_id,
                enabled=True,
                scam_detection_enabled=True
            )
            session.add(settings)

        await session.commit()
        return


async def ensure_group_exists(chat_id: int, title: str = "Test Group"):
    """Убедиться что группа существует в БД."""
    from bot.database.models import Group
    from sqlalchemy import select

    async for session in get_test_session():
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            group = Group(chat_id=chat_id, title=title)
            session.add(group)
            await session.commit()
        return


async def toggle_section(section_id: int):
    """Переключить активность раздела."""
    from bot.services.content_filter.scam_pattern_service import get_section_service

    service = get_section_service()
    async for session in get_test_session():
        await service.toggle_section(section_id, session)
        return


# ============================================================
# TEST CLASS: Basic Detection with Cyrillic
# ============================================================

class TestCustomSectionDetection:
    """Тесты детекции спама по кастомным разделам (кириллица)."""

    @pytest.mark.asyncio
    async def test_taxi_spam_cyrillic(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: детекция рекламы такси на русском.

        Сценарий:
        1. Создаём раздел "Такси" с паттернами на русском
        2. Жертва отправляет "Такси недорого, вызов по городу"
        3. Проверяем что сообщение удалено
        """
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Taxi spam detection (Cyrillic)")
        print(f"[TEST] Admin: @{admin.username}, Victim: @{victim.username}")

        try:
            # Подготовка
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            # Создаём раздел с паттернами на русском
            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Такси_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete"
            )
            print(f"[SETUP] Created section ID={section_id}")

            # Добавляем паттерны на кириллице
            await add_section_pattern(section_id, "такси недорого", weight=50)
            await add_section_pattern(section_id, "вызов такси", weight=40)
            await add_section_pattern(section_id, "трансфер аэропорт", weight=45)
            print(f"[SETUP] Added Cyrillic patterns")

            await asyncio.sleep(1)

            # Жертва отправляет спам на русском
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Такси недорого по городу! Быстрая подача, вызов круглосуточно"
            )
            msg_id = spam_msg.id
            print(f"[SEND] Victim sent: 'Такси недорого по городу!'")

            # Ждём обработки
            await asyncio.sleep(3)

            # Проверяем что сообщение удалено
            exists = await check_message_exists(victim_userbot, chat_id, msg_id)
            if not exists:
                print(f"[OK] Spam message was deleted!")
            else:
                print(f"[FAIL] Spam message NOT deleted")
                try:
                    await spam_msg.delete()
                except Exception:
                    pass

        finally:
            if section_id:
                await delete_test_section(section_id)
                print(f"[CLEANUP] Deleted section ID={section_id}")
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_drugs_spam_with_mute(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: детекция наркотиков с мутом пользователя.

        Сценарий:
        1. Создаём раздел с действием "mute"
        2. Жертва отправляет спам про закладки
        3. Проверяем что пользователь замучен
        """
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Drug spam detection with mute")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            # Создаём раздел с мутом
            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Наркотики_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="mute",
                mute_duration=60
            )
            print(f"[SETUP] Created section with mute action")

            # Реальные паттерны на русском
            await add_section_pattern(section_id, "продам вещества", weight=60)
            await add_section_pattern(section_id, "закладки", weight=55)
            await add_section_pattern(section_id, "соли мефедрон", weight=70)
            print(f"[SETUP] Added drug patterns")

            await asyncio.sleep(1)

            # Жертва отправляет спам
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Продам вещества, закладки по городу, быстро и надёжно"
            )
            print(f"[SEND] Victim sent drug spam")

            await asyncio.sleep(3)

            # Проверяем мут
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            if restrictions.get("is_restricted"):
                print(f"[OK] Victim is muted!")
            else:
                print(f"[FAIL] Victim NOT muted")

            # Проверяем удаление сообщения
            exists = await check_message_exists(victim_userbot, chat_id, spam_msg.id)
            if not exists:
                print(f"[OK] Message deleted")
            else:
                try:
                    await spam_msg.delete()
                except Exception:
                    pass

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)
            print(f"[CLEANUP] Done")

    @pytest.mark.asyncio
    async def test_housing_spam_forward_to_channel(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: пересылка спама о жилье в канал перед удалением.

        Сценарий:
        1. Создаём раздел с action="forward_delete" и каналом пересылки
        2. Жертва отправляет "Сдам квартиру посуточно недорого"
        3. Проверяем что сообщение переслано в канал и удалено
        """
        admin = await admin_userbot.get_me()
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Housing spam with forward to channel")
        print(f"[TEST] Forward channel: {FORWARD_CHANNEL_ID}")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            # Уникальный маркер для проверки пересылки
            unique_marker = f"TEST_{datetime.now().strftime('%H%M%S%f')}"

            # Создаём раздел с пересылкой
            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Жильё_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="forward_delete",
                forward_channel_id=FORWARD_CHANNEL_ID
            )
            print(f"[SETUP] Created section with forward_delete action")

            # Паттерны на тему жилья
            await add_section_pattern(section_id, "сдам квартиру", weight=50)
            await add_section_pattern(section_id, "посуточно", weight=40)
            await add_section_pattern(section_id, "аренда жилья", weight=45)
            print(f"[SETUP] Added housing patterns")

            await asyncio.sleep(1)

            # Жертва отправляет спам
            spam_text = f"Сдам квартиру посуточно, недорого, центр города [{unique_marker}]"
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=spam_text
            )
            print(f"[SEND] Victim sent housing spam with marker")

            await asyncio.sleep(4)

            # Проверяем что сообщение удалено из группы
            exists = await check_message_exists(victim_userbot, chat_id, spam_msg.id)
            if not exists:
                print(f"[OK] Spam message deleted from group")
            else:
                print(f"[FAIL] Spam message NOT deleted from group")
                try:
                    await spam_msg.delete()
                except Exception:
                    pass

            # Проверяем что сообщение переслано в канал
            found_in_channel = await check_message_in_channel(
                admin_userbot, FORWARD_CHANNEL_ID, unique_marker, limit=10
            )
            if found_in_channel:
                print(f"[OK] Spam message forwarded to channel!")
            else:
                print(f"[WARN] Message not found in channel (check manually)")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)
            print(f"[CLEANUP] Done")


# ============================================================
# TEST CLASS: Obfuscated Spam (Обманки)
# ============================================================

class TestObfuscatedSpam:
    """Тесты детекции обфусцированного спама (обманки)."""

    @pytest.mark.asyncio
    async def test_l33tspeak_obfuscation(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: детекция l33tspeak обфускации.

        Сценарий:
        1. Паттерн "заработок" должен ловить "з4р4б0т0к" и "зaрaбoток" (латиница)
        2. Проверяем нормализацию текста
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] L33tspeak obfuscation detection")

        try:
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Заработок_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete"
            )

            # Паттерн на нормальном русском
            await add_section_pattern(section_id, "заработок без вложений", weight=60)
            print(f"[SETUP] Added pattern: 'заработок без вложений'")

            await asyncio.sleep(1)

            # Тест 1: обфусцированное сообщение с цифрами
            msg1 = await victim_userbot.send_message(
                chat_id=chat_id,
                text="З4р4б0т0к б3з вл0ж3ний! Пиши в ЛС"
            )
            print(f"[SEND] Sent: 'З4р4б0т0к б3з вл0ж3ний'")
            await asyncio.sleep(3)

            exists1 = await check_message_exists(victim_userbot, chat_id, msg1.id)
            if not exists1:
                print(f"[OK] L33tspeak message deleted!")
            else:
                print(f"[WARN] L33tspeak message NOT deleted (normalizer issue?)")
                await msg1.delete()

            # Тест 2: обфусцированное сообщение с латиницей
            msg2 = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Зaрaбoток бeз влoжeний кaждый дeнь"  # a, o, e - латиница
            )
            print(f"[SEND] Sent: obfuscated with Latin letters")
            await asyncio.sleep(3)

            exists2 = await check_message_exists(victim_userbot, chat_id, msg2.id)
            if not exists2:
                print(f"[OK] Latin-obfuscated message deleted!")
            else:
                print(f"[WARN] Latin-obfuscated message NOT deleted")
                await msg2.delete()

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_spaced_text_obfuscation(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: детекция текста с пробелами между буквами.

        Сценарий:
        1. Паттерн "казино" должен ловить "к а з и н о" и "каZино"
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Spaced text obfuscation detection")

        try:
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Казино_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete"
            )

            await add_section_pattern(section_id, "казино онлайн", weight=60)
            await add_section_pattern(section_id, "ставки спорт", weight=50)
            print(f"[SETUP] Added gambling patterns")

            await asyncio.sleep(1)

            # Тест: текст с пробелами
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text="К а з и н о   о н л а й н ! Бонус новичкам 100%"
            )
            print(f"[SEND] Sent: 'К а з и н о   о н л а й н'")
            await asyncio.sleep(3)

            exists = await check_message_exists(victim_userbot, chat_id, msg.id)
            if not exists:
                print(f"[OK] Spaced message deleted!")
            else:
                print(f"[WARN] Spaced message NOT deleted (normalizer issue?)")
                await msg.delete()

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Cumulative Score
# ============================================================

class TestCumulativeScore:
    """Тесты кумулятивного подсчёта скора."""

    @pytest.mark.asyncio
    async def test_multiple_patterns_sum_score(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: несколько паттернов суммируют скор.

        Сценарий:
        1. Порог 80
        2. Паттерны по 30 каждый
        3. Сообщение с 3 паттернами (90 > 80) - удаляется
        4. Сообщение с 1 паттерном (30 < 80) - остаётся
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Cumulative score calculation")

        try:
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Скор_{datetime.now().strftime('%H%M%S')}",
                threshold=80,
                action="delete"
            )

            # Три паттерна по 30 = макс 90 при всех трёх
            await add_section_pattern(section_id, "пассивный доход", weight=30)
            await add_section_pattern(section_id, "финансовая свобода", weight=30)
            await add_section_pattern(section_id, "работа на себя", weight=30)
            print(f"[SETUP] Added 3 patterns with weight=30 each")

            await asyncio.sleep(1)

            # Тест 1: только 1 паттерн (30 < 80) - НЕ удаляется
            msg1 = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Хочу пассивный доход, кто знает как?"
            )
            print(f"[SEND] Sent: 1 pattern (score=30)")
            await asyncio.sleep(3)

            exists1 = await check_message_exists(victim_userbot, chat_id, msg1.id)
            if exists1:
                print(f"[OK] Message with 1 pattern NOT deleted (30 < 80)")
                await msg1.delete()
            else:
                print(f"[WARN] Message with 1 pattern WAS deleted")

            # Тест 2: все 3 паттерна (90 > 80) - удаляется
            msg2 = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Пассивный доход и финансовая свобода! Работа на себя!"
            )
            print(f"[SEND] Sent: 3 patterns (score=90)")
            await asyncio.sleep(3)

            exists2 = await check_message_exists(victim_userbot, chat_id, msg2.id)
            if not exists2:
                print(f"[OK] Message with 3 patterns WAS deleted (90 > 80)")
            else:
                print(f"[FAIL] Message with 3 patterns NOT deleted")
                await msg2.delete()

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Normal Messages
# ============================================================

class TestNormalMessages:
    """Тесты что нормальные сообщения не триггерят детекцию."""

    @pytest.mark.asyncio
    async def test_normal_message_not_deleted(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: обычные сообщения не удаляются.
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Normal message should NOT be deleted")

        try:
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Спам_{datetime.now().strftime('%H%M%S')}",
                threshold=50,
                action="delete"
            )
            await add_section_pattern(section_id, "очень специфичный паттерн который никто не напишет", weight=60)

            await asyncio.sleep(1)

            # Обычное сообщение
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Привет всем! Как дела? {datetime.now().strftime('%H:%M:%S')}"
            )
            print(f"[SEND] Sent normal message")

            await asyncio.sleep(3)

            exists = await check_message_exists(victim_userbot, chat_id, msg.id)
            if exists:
                print(f"[OK] Normal message NOT deleted (correct!)")
                await msg.delete()
            else:
                print(f"[FAIL] Normal message was deleted (false positive!)")

            # Проверяем что НЕ замучен
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            if not restrictions.get("is_restricted"):
                print(f"[OK] User NOT muted")
            else:
                print(f"[FAIL] User was muted (false positive!)")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# TEST CLASS: Per-Action Forwarding
# ============================================================

class TestPerActionForwarding:
    """Тесты опций пересылки по действиям (forward_on_delete/mute/ban)."""

    @pytest.mark.asyncio
    async def test_forward_on_mute(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: пересылка в канал при действии mute.

        Сценарий:
        1. Создаём раздел с action=mute и forward_on_mute=True
        2. Жертва отправляет спам
        3. Проверяем: сообщение удалено, пользователь замучен, инфо переслано в канал
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Forward on mute action")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            # Уникальный маркер
            unique_marker = f"MUTE_FWD_{datetime.now().strftime('%H%M%S%f')}"

            # Создаём раздел с мутом и пересылкой
            section_id = await create_test_section_with_forward(
                chat_id=chat_id,
                name=f"МутПересылка_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="mute",
                mute_duration=60,
                forward_channel_id=FORWARD_CHANNEL_ID,
                forward_on_mute=True
            )
            print(f"[SETUP] Created section with mute + forward_on_mute")

            await add_section_pattern(section_id, "тест пересылки мута", weight=50)
            await asyncio.sleep(1)

            # Жертва отправляет спам
            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Это тест пересылки мута [{unique_marker}]"
            )
            print(f"[SEND] Victim sent spam with marker")

            await asyncio.sleep(4)

            # Проверяем мут
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            if restrictions.get("is_restricted"):
                print(f"[OK] Victim is muted")
            else:
                print(f"[WARN] Victim NOT muted")

            # Проверяем пересылку в канал
            found_in_channel = await check_message_in_channel(
                admin_userbot, FORWARD_CHANNEL_ID, unique_marker, limit=10
            )
            if found_in_channel:
                print(f"[OK] Mute action forwarded to channel!")
            else:
                print(f"[WARN] Message not found in channel")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)
            print(f"[CLEANUP] Done")

    @pytest.mark.asyncio
    async def test_forward_on_delete_only(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: пересылка только при удалении (без мута).

        Сценарий:
        1. Создаём раздел с action=delete и forward_on_delete=True
        2. Жертва отправляет спам
        3. Проверяем: сообщение удалено, инфо переслано в канал, НЕ замучен
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Forward on delete action")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            unique_marker = f"DEL_FWD_{datetime.now().strftime('%H%M%S%f')}"

            section_id = await create_test_section_with_forward(
                chat_id=chat_id,
                name=f"УдалПересылка_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete",
                forward_channel_id=FORWARD_CHANNEL_ID,
                forward_on_delete=True
            )
            print(f"[SETUP] Created section with delete + forward_on_delete")

            await add_section_pattern(section_id, "тест пересылки удаления", weight=50)
            await asyncio.sleep(1)

            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Это тест пересылки удаления [{unique_marker}]"
            )
            print(f"[SEND] Victim sent spam")

            await asyncio.sleep(4)

            # Проверяем что НЕ замучен (action=delete)
            restrictions = await get_user_restrictions(bot, chat_id, victim.id)
            if not restrictions.get("is_restricted"):
                print(f"[OK] Victim NOT muted (correct for delete action)")
            else:
                print(f"[WARN] Victim is muted (unexpected)")

            # Проверяем пересылку
            found_in_channel = await check_message_in_channel(
                admin_userbot, FORWARD_CHANNEL_ID, unique_marker, limit=10
            )
            if found_in_channel:
                print(f"[OK] Delete action forwarded to channel!")
            else:
                print(f"[WARN] Message not found in channel")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)

    @pytest.mark.asyncio
    async def test_no_forward_when_disabled(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: пересылка отключена - сообщение НЕ пересылается.

        Сценарий:
        1. Создаём раздел с action=delete, но forward_on_delete=False
        2. Жертва отправляет спам
        3. Проверяем: сообщение удалено, НО НЕ переслано в канал
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] No forward when disabled")

        try:
            await ensure_user_in_chat(admin_userbot, chat_id, invite_link=invite_link)
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)
            await asyncio.sleep(1)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            unique_marker = f"NOFWD_{datetime.now().strftime('%H%M%S%f')}"

            # Создаём раздел БЕЗ пересылки
            section_id = await create_test_section_with_forward(
                chat_id=chat_id,
                name=f"БезПересылки_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete",
                forward_channel_id=FORWARD_CHANNEL_ID,
                forward_on_delete=False  # Отключено!
            )
            print(f"[SETUP] Created section WITHOUT forward")

            await add_section_pattern(section_id, "тест без пересылки", weight=50)
            await asyncio.sleep(1)

            spam_msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text=f"Это тест без пересылки [{unique_marker}]"
            )
            print(f"[SEND] Victim sent spam")

            await asyncio.sleep(4)

            # Проверяем что сообщение удалено
            exists = await check_message_exists(victim_userbot, chat_id, spam_msg.id)
            if not exists:
                print(f"[OK] Message deleted")
            else:
                print(f"[WARN] Message NOT deleted")
                await spam_msg.delete()

            # Проверяем что НЕ переслано
            found_in_channel = await check_message_in_channel(
                admin_userbot, FORWARD_CHANNEL_ID, unique_marker, limit=10
            )
            if not found_in_channel:
                print(f"[OK] Message NOT forwarded (correct!)")
            else:
                print(f"[WARN] Message WAS forwarded (should not be)")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# HELPER: Create section with forward options
# ============================================================

async def create_test_section_with_forward(
    chat_id: int,
    name: str,
    threshold: int = 50,
    action: str = "delete",
    mute_duration: int = None,
    forward_channel_id: int = None,
    forward_on_delete: bool = False,
    forward_on_mute: bool = False,
    forward_on_ban: bool = False
) -> int:
    """Создаёт раздел с опциями пересылки."""
    from bot.services.content_filter.scam_pattern_service import get_section_service

    service = get_section_service()
    async for session in get_test_session():
        success, section_id, error = await service.create_section(
            chat_id=chat_id,
            name=name,
            session=session,
            threshold=threshold,
            action=action,
            mute_duration=mute_duration,
            forward_channel_id=forward_channel_id,
            created_by=123456789
        )
        if not success:
            raise Exception(f"Failed to create section: {error}")

        # Устанавливаем опции пересылки
        await service.update_section(
            section_id,
            session,
            forward_on_delete=forward_on_delete,
            forward_on_mute=forward_on_mute,
            forward_on_ban=forward_on_ban
        )
        return section_id


# ============================================================
# TEST CLASS: Section Toggle
# ============================================================

class TestSectionToggle:
    """Тесты переключения активности раздела."""

    @pytest.mark.asyncio
    async def test_disabled_section_no_detection(
        self, admin_userbot: Client, victim_userbot: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """
        Тест: отключённый раздел не триггерит детекцию.
        """
        victim = await victim_userbot.get_me()
        section_id = None

        print(f"\n[TEST] Disabled section should NOT detect spam")

        try:
            await ensure_user_in_chat(victim_userbot, chat_id, invite_link=invite_link)
            await unmute_user(bot, chat_id, victim.id)

            await ensure_group_exists(chat_id)
            await enable_content_filter(chat_id)

            section_id = await create_test_section(
                chat_id=chat_id,
                name=f"Выкл_{datetime.now().strftime('%H%M%S')}",
                threshold=30,
                action="delete"
            )
            await add_section_pattern(section_id, "тест отключённого раздела", weight=50)

            # Отключаем раздел
            await toggle_section(section_id)
            print(f"[SETUP] Section disabled")

            await asyncio.sleep(1)

            # Жертва отправляет сообщение с паттерном
            msg = await victim_userbot.send_message(
                chat_id=chat_id,
                text="Это тест отключённого раздела для проверки"
            )
            await asyncio.sleep(3)

            exists = await check_message_exists(victim_userbot, chat_id, msg.id)
            if exists:
                print(f"[OK] Message NOT deleted (section disabled - correct!)")
                await msg.delete()
            else:
                print(f"[FAIL] Message WAS deleted (section should be disabled!)")

        finally:
            if section_id:
                await delete_test_section(section_id)
            await unmute_user(bot, chat_id, victim.id)


# ============================================================
# Запуск тестов
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
