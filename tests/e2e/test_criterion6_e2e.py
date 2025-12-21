# tests/e2e/test_criterion6_e2e.py
"""
E2E тест для критерия 6: Запрещённый контент в имени/bio.

Полный тест через UI бота с реальными юзерботами:
1. Админ (@ermek0vnma) настраивает бота через UI
2. Жертва (@s1adkaya2292) меняет имя на запрещённое
3. Бот должен замутить жертву
"""

import sys
import io

# Фикс для Windows - правильная кодировка Unicode
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import os
import logging
from datetime import datetime

from pyrogram import Client
from pyrogram.types import Message
from aiogram import Bot
from dotenv import load_dotenv

# Загружаем переменные из .env.test
load_dotenv(".env.test")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация из .env.test
BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
BOT_USERNAME = "test_KvdModerBot"  # Username тестового бота
CHAT_ID = int(os.getenv("TEST_CHAT_ID", "-1002302638465"))

# Юзерботы
ADMIN_SESSION = os.getenv("TEST_USERBOT_SESSION")  # @ermek0vnma
VICTIM_SESSION = os.getenv("TEST_USERBOT2_SESSION")  # @s1adkaya2292

# Pyrogram API
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"


async def create_client(session: str, name: str) -> Client:
    """Создаёт Pyrogram клиент."""
    return Client(
        name=name,
        session_string=session,
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True
    )


async def wait_for_message(client: Client, chat_id: int, timeout: int = 10) -> Message:
    """Ждёт новое сообщение от бота."""
    start = datetime.now()
    last_msg_id = 0

    # Получаем последнее сообщение
    async for msg in client.get_chat_history(chat_id, limit=1):
        last_msg_id = msg.id
        break

    while (datetime.now() - start).seconds < timeout:
        async for msg in client.get_chat_history(chat_id, limit=1):
            if msg.id > last_msg_id:
                return msg
        await asyncio.sleep(0.5)

    return None


async def click_button(client: Client, msg: Message, text_contains: str) -> bool:
    """Нажимает на inline кнопку с указанным текстом."""
    if not msg.reply_markup:
        logger.error("Сообщение не содержит кнопок")
        return False

    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            if text_contains.lower() in button.text.lower():
                try:
                    await client.request_callback_answer(
                        chat_id=msg.chat.id,
                        message_id=msg.id,
                        callback_data=button.callback_data
                    )
                    logger.info(f"✅ Нажата кнопка: {button.text}")
                    await asyncio.sleep(1)  # Ждём обновления
                    return True
                except Exception as e:
                    logger.error(f"❌ Ошибка нажатия кнопки: {e}")
                    return False

    logger.error(f"Кнопка с текстом '{text_contains}' не найдена")
    return False


async def run_criterion6_test():
    """Основной E2E тест критерия 6."""

    logger.info("=" * 60)
    logger.info("🧪 НАЧАЛО E2E ТЕСТА: Критерий 6 - Запрещённый контент в имени")
    logger.info("=" * 60)

    # Создаём клиенты
    admin_client = await create_client(ADMIN_SESSION, "admin_ermek")
    victim_client = await create_client(VICTIM_SESSION, "victim_sladkaya")
    bot = Bot(token=BOT_TOKEN)

    original_name = None

    try:
        # ═══════════════════════════════════════════════════════════════
        # ФАЗА 1: НАСТРОЙКА ЧЕРЕЗ UI (Админ @ermek0vnma)
        # ═══════════════════════════════════════════════════════════════
        logger.info("\n📱 ФАЗА 1: Настройка бота через UI")

        async with admin_client:
            admin_me = await admin_client.get_me()
            logger.info(f"👤 Админ: @{admin_me.username} (ID: {admin_me.id})")

            # 1. Сначала /start чтобы активировать бота
            logger.info("📤 Отправляем /start боту...")
            await admin_client.send_message(BOT_USERNAME, "/start")
            await asyncio.sleep(2)

            # 2. Отправляем /settings боту в ЛС
            logger.info("📤 Отправляем /settings боту...")
            await admin_client.send_message(BOT_USERNAME, "/settings")
            await asyncio.sleep(3)

            # Получаем ответ с кнопками групп
            msg = None
            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            if not msg or not msg.reply_markup:
                logger.error("❌ Бот не ответил с кнопками групп")
                return False

            logger.info(f"📩 Получен ответ: {msg.text[:100] if msg.text else 'Сообщение без текста'}...")

            # 2. Выбираем тестовую группу
            logger.info(f"🔘 Выбираем группу с ID {CHAT_ID}...")

            # Ищем кнопку с chat_id
            found = False
            for row in msg.reply_markup.inline_keyboard:
                for button in row:
                    if str(CHAT_ID) in (button.callback_data or ""):
                        await admin_client.request_callback_answer(
                            chat_id=msg.chat.id,
                            message_id=msg.id,
                            callback_data=button.callback_data
                        )
                        found = True
                        logger.info(f"✅ Выбрана группа: {button.text}")
                        break
                if found:
                    break

            if not found:
                # Пробуем нажать на первую группу
                await click_button(admin_client, msg, "")  # Первая кнопка

            await asyncio.sleep(2)

            # 3. Получаем меню настроек группы
            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            logger.info(f"📩 Меню группы: {msg.text[:100] if msg.text else 'Нет текста'}...")

            # 4. Переходим в Profile Monitor
            logger.info("🔘 Переходим в Profile Monitor...")
            clicked = await click_button(admin_client, msg, "Profile Monitor")
            if not clicked:
                clicked = await click_button(admin_client, msg, "Мониторинг")

            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            # 5. Включаем Profile Monitor если выключен
            if "Включить" in (msg.text or "") or "🔴" in (msg.text or ""):
                logger.info("🔘 Включаем Profile Monitor...")
                await click_button(admin_client, msg, "Включить")
                await asyncio.sleep(2)
                async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                    msg = m
                    break

            # 6. Переходим в настройки автомута
            logger.info("🔘 Переходим в настройки автомута...")
            await click_button(admin_client, msg, "автомут")
            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            logger.info(f"📩 Меню автомута: {msg.text[:200] if msg.text else 'Нет текста'}...")

            # 7. Включаем критерий 6 (запрещённый контент)
            # Проверяем текущий статус - нажимаем только если ❌ (выключен)
            logger.info("🔘 Проверяем статус критерия 6...")

            # Ищем кнопку критерия 6
            criterion6_enabled = False
            for row in msg.reply_markup.inline_keyboard:
                for button in row:
                    if "запрещённый контент" in button.text.lower():
                        if "✅" in button.text:
                            criterion6_enabled = True
                            logger.info("✅ Критерий 6 уже включён")
                        else:
                            logger.info("❌ Критерий 6 выключен, включаем...")
                        break

            # Если выключен - включаем
            if not criterion6_enabled:
                clicked = await click_button(admin_client, msg, "запрещённый контент")
                await asyncio.sleep(2)

                # Проверяем что критерий 6 включён
                async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                    msg = m
                    break

                # Проверяем ещё раз статус
                for row in msg.reply_markup.inline_keyboard:
                    for button in row:
                        if "запрещённый контент" in button.text.lower() and "✅" in button.text:
                            logger.info("✅ Критерий 6 успешно включён!")
                            criterion6_enabled = True
                            break

            if not criterion6_enabled:
                logger.warning("⚠️ Не удалось включить критерий 6!")

        # ═══════════════════════════════════════════════════════════════
        # ФАЗА 2: ДОБАВЛЕНИЕ ЗАПРЕЩЁННОГО СЛОВА ЧЕРЕЗ ФИЛЬТР КОНТЕНТА
        # ═══════════════════════════════════════════════════════════════
        logger.info("\n📝 ФАЗА 2: Добавление запрещённого слова 'кокс' через фильтр")

        async with admin_client:
            # Возвращаемся в главное меню настроек
            await admin_client.send_message(BOT_USERNAME, "/settings")
            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            # Выбираем группу
            for row in msg.reply_markup.inline_keyboard:
                for button in row:
                    if str(CHAT_ID) in (button.callback_data or ""):
                        await admin_client.request_callback_answer(
                            chat_id=msg.chat.id,
                            message_id=msg.id,
                            callback_data=button.callback_data
                        )
                        break
            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            # Переходим в Фильтр контента
            logger.info("🔘 Переходим в Фильтр контента...")
            await click_button(admin_client, msg, "Фильтр")
            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            # Переходим в Запрещённые слова
            logger.info("🔘 Переходим в Запрещённые слова...")
            clicked = await click_button(admin_client, msg, "слова")
            if not clicked:
                clicked = await click_button(admin_client, msg, "words")
            await asyncio.sleep(2)

            async for m in admin_client.get_chat_history(BOT_USERNAME, limit=1):
                msg = m
                break

            # Добавляем слово
            logger.info("🔘 Добавляем слово 'кокс'...")
            clicked = await click_button(admin_client, msg, "Добавить")
            if not clicked:
                clicked = await click_button(admin_client, msg, "add")
            await asyncio.sleep(2)

            # Отправляем слово
            await admin_client.send_message(BOT_USERNAME, "кокс")
            await asyncio.sleep(3)

            logger.info("✅ Слово 'кокс' добавлено в фильтр")

        # ═══════════════════════════════════════════════════════════════
        # ФАЗА 2.5: АДМИН ПРИГЛАШАЕТ ЖЕРТВУ В ГРУППУ
        # ═══════════════════════════════════════════════════════════════
        logger.info("\n📨 ФАЗА 2.5: Админ приглашает жертву в группу")

        # Получаем ID жертвы
        victim_id = None
        async with victim_client:
            victim_me = await victim_client.get_me()
            victim_id = victim_me.id
            original_name = victim_me.first_name
            logger.info(f"👤 Жертва: @{victim_me.username} (ID: {victim_id})")

        # Проверяем статус жертвы и при необходимости приглашаем через invite link
        try:
            member = await bot.get_chat_member(CHAT_ID, victim_id)
            logger.info(f"👤 Жертва в группе: {member.status}")

            # Если жертва забанена или вышла - снимаем бан
            if member.status in ("left", "kicked"):
                logger.info("📨 Снимаем бан с жертвы...")
                await bot.unban_chat_member(CHAT_ID, victim_id, only_if_banned=True)

            # Если жертва не в группе - приглашаем через invite link
            if member.status in ("left", "kicked"):
                logger.info("📨 Жертва вступает в группу через invite link...")
                async with victim_client:
                    # Получаем invite link
                    invite_link = await bot.export_chat_invite_link(CHAT_ID)
                    logger.info(f"🔗 Invite link: {invite_link}")
                    # Вступаем по ссылке
                    await victim_client.join_chat(invite_link)
                    logger.info("✅ Жертва вступила в группу")
                    await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки/приглашения жертвы: {e}")

        # ═══════════════════════════════════════════════════════════════
        # ФАЗА 3: ЖЕРТВА МЕНЯЕТ ИМЯ И ПИШЕТ СООБЩЕНИЕ
        # ═══════════════════════════════════════════════════════════════
        logger.info("\n👿 ФАЗА 3: Жертва меняет имя и пишет сообщение")

        async with victim_client:
            victim_me = await victim_client.get_me()
            logger.info(f"📝 Оригинальное имя: {original_name}")

            # Меняем имя на запрещённое
            forbidden_name = "Кокс продажа 🔥"
            logger.info(f"📝 Меняем имя на: {forbidden_name}")

            await victim_client.update_profile(first_name=forbidden_name)
            await asyncio.sleep(2)

            # Используем get_dialogs чтобы загрузить все чаты в кэш Pyrogram
            try:
                logger.info("📍 Загружаем диалоги для кэширования...")
                async for dialog in victim_client.get_dialogs(limit=50):
                    if dialog.chat.id == CHAT_ID:
                        logger.info(f"📍 Нашли группу в диалогах: {dialog.chat.title}")
                        break
                else:
                    logger.warning("⚠️ Группа не найдена в диалогах")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки диалогов: {e}")

            # Отправляем сообщение в группу
            logger.info(f"📤 Жертва отправляет сообщение в группу...")
            try:
                sent_msg = await victim_client.send_message(
                    CHAT_ID,
                    f"Привет всем! Тестовое сообщение {datetime.now().isoformat()}"
                )
                logger.info(f"✅ Сообщение отправлено: ID={sent_msg.id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки: {e}")

            await asyncio.sleep(3)

            # ═══════════════════════════════════════════════════════════
            # ФАЗА 4: ПРОВЕРКА РЕЗУЛЬТАТА
            # ═══════════════════════════════════════════════════════════
            logger.info("\n🔍 ФАЗА 4: Проверка результата")

            # Проверяем статус жертвы
            try:
                member = await bot.get_chat_member(CHAT_ID, victim_me.id)
                logger.info(f"📊 Статус жертвы после теста: {member.status}")

                if member.status == "restricted":
                    can_send = member.can_send_messages
                    logger.info(f"🔇 Жертва ЗАМУЧЕНА! can_send_messages={can_send}")
                    if not can_send:
                        logger.info("✅✅✅ ТЕСТ ПРОЙДЕН! Критерий 6 работает!")
                        return True
                    else:
                        logger.warning("⚠️ Жертва ограничена, но может писать")
                        return False
                else:
                    logger.error(f"❌ ТЕСТ ПРОВАЛЕН! Жертва НЕ замучена. Статус: {member.status}")
                    return False

            except Exception as e:
                logger.error(f"❌ Ошибка проверки статуса: {e}")
                return False

    except Exception as e:
        logger.error(f"❌ Ошибка теста: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # ═══════════════════════════════════════════════════════════════
        # CLEANUP: Возвращаем оригинальное имя
        # ═══════════════════════════════════════════════════════════════
        logger.info("\n🧹 CLEANUP: Восстановление оригинального имени")

        if original_name:
            try:
                async with victim_client:
                    await victim_client.update_profile(first_name=original_name)
                    logger.info(f"✅ Имя восстановлено: {original_name}")
            except Exception as e:
                logger.error(f"❌ Ошибка восстановления имени: {e}")

        # Размучиваем жертву
        try:
            victim_id = 0
            async with victim_client:
                me = await victim_client.get_me()
                victim_id = me.id

            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(
                CHAT_ID,
                victim_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            logger.info("✅ Жертва размучена")
        except Exception as e:
            logger.error(f"⚠️ Ошибка размута: {e}")

        await bot.session.close()


if __name__ == "__main__":
    result = asyncio.run(run_criterion6_test())

    print("\n" + "=" * 60)
    if result:
        print("✅ E2E ТЕСТ КРИТЕРИЯ 6: УСПЕШНО ПРОЙДЕН")
    else:
        print("❌ E2E ТЕСТ КРИТЕРИЯ 6: ПРОВАЛЕН")
    print("=" * 60)
