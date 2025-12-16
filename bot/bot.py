import asyncio
import os
import sys

# Настройка путей для запуска из любой директории
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
# При инициализации бота добавьте параметр timeout
from aiogram.client.session.aiohttp import AiohttpSession

# ВАЖНО: сначала загружаем конфиг (.env), потом инициализируем Redis
from bot.config import BOT_TOKEN, USE_WEBHOOK, WEBHOOK_URL
from bot.services.redis_conn import test_connection

from bot.database.session import engine, async_session
from bot.database.models import Base
from bot.middleware.db_session import DbSessionMiddleware  # Добавляем импорт DbSessionMiddleware
from bot.handlers import handlers_router

# ============================================================
# ИМПОРТ PYROGRAM СЕРВИСА для расширенной информации о пользователях
# ============================================================
# Pyrogram позволяет получить данные, недоступные через Bot API:
# - Точная дата создания аккаунта
# - Даты загрузки фото профиля
from bot.services.pyrogram_client import pyrogram_service

# ============================================================
# ИМПОРТ СЕРВИСА ЗАЩИТЫ ГРУПП от потери данных
# ============================================================
# Решает проблему исчезновения групп после перезапуска:
# - Бэкап групп в Redis при старте
# - Автоматическое восстановление при потере
# - Логирование попыток удаления Group записей
from bot.services.group_protection import (
    setup_group_delete_listeners,
    check_and_protect_groups,
)

# Логгер
import logging
from bot.utils.logger import TelegramLogHandler

# Настройка логгера
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Создаем обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Создаем обработчик для Telegram
telegram_handler = TelegramLogHandler(level=logging.INFO)
telegram_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
telegram_handler.setFormatter(telegram_formatter)
logger.addHandler(telegram_handler)

# КРИТИЧНО: Отключаем встроенное логирование aiogram для апдейтов
# Это должно предотвратить логирование "📩 Получен апдейт от Telegram"
for logger_name in ("aiogram", "aiogram.dispatcher", "aiogram.event"):
    log = logging.getLogger(logger_name)
    log.addHandler(console_handler)
    log.setLevel(logging.ERROR)  # Только ошибки - отключаем INFO и WARNING логи
    log.propagate = False

# определяем, где мы запускаемся
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)  # Добавляем поддержку пароля


# главная асинхронная функция, запускающая бота
async def main():
    logging.info("🤖 Бот успешно запущен и готов к работе.")

    # ============================================================
    # ЗАЩИТА ГРУПП: Настройка логирования удаления Group записей
    # ============================================================
    # Должно быть вызвано ДО любых операций с БД
    setup_group_delete_listeners()

    # Создаем отказоустойчивое хранилище - если Redis недоступен, используем MemoryStorage
    try:
        # пробуем подключиться к Redis
        await test_connection()
        redis_url = f"redis://{':' + REDIS_PASSWORD + '@' if REDIS_PASSWORD else ''}{REDIS_HOST}:{REDIS_PORT}"
        storage = RedisStorage.from_url(redis_url)
    except Exception as e:
        # В случае ошибки подключения к Redis используем MemoryStorage
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        logging.warning(f"⚠️ Ошибка подключения к Redis: {e}")
        logging.info("ℹ️ Используется MemoryStorage для хранения состояний (данные будут утеряны при перезапуске)")

    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ============================================================
    # ЗАЩИТА ГРУПП: Проверка и восстановление при потере данных
    # ============================================================
    # Если groups таблица пустая, но есть бэкап в Redis - восстанавливаем
    # Иначе создаём свежий бэкап для защиты от потери
    try:
        from bot.database.session import get_session
        async with get_session() as db_session:
            protection_result = await check_and_protect_groups(db_session)
            if protection_result:
                logging.info("✅ [GROUP_PROTECTION] Проверка групп завершена успешно")
            else:
                logging.warning("⚠️ [GROUP_PROTECTION] Проверка групп выявила проблемы")
    except Exception as e:
        logging.error(f"❌ [GROUP_PROTECTION] Ошибка проверки групп: {e}")

    # ✅ Создание бота по токену из .env
    session = AiohttpSession(timeout=60.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    # ============================================================
    # ИНИЦИАЛИЗАЦИЯ PYROGRAM СЕРВИСА
    # ============================================================
    # Pyrogram используется для получения расширенной информации о пользователях:
    # - Точная дата создания аккаунта (через MTProto API)
    # - Даты загрузки фото профиля (недоступно через Bot API)
    #
    # ВАЖНО: Pyrogram запускается параллельно с основным ботом
    # и использует те же учетные данные (BOT_TOKEN)
    try:
        logging.info("🔧 Инициализация Pyrogram клиента...")
        await pyrogram_service.initialize()  # Запускаем Pyrogram клиент
        logging.info("✅ Pyrogram клиент готов к работе")
    except Exception as e:
        logging.error(f"❌ Ошибка инициализации Pyrogram: {e}")
        logging.warning("⚠️ Функции проверки фото и точного возраста будут недоступны")

    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=storage)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))

    # ✅ Подключение автосинхронизации групп
    # При любом событии из группы - автоматически создаёт записи в БД если их нет
    from bot.middleware.group_auto_sync_middleware import GroupAutoSyncMiddleware
    dp.update.middleware(GroupAutoSyncMiddleware())

    # ✅ Подключение структурированного логирования ПЕРВЫМ (чтобы перехватить все логи)
    from bot.middleware.structured_logging import StructuredLoggingMiddleware
    # ВАЖНО: middleware выполняется в обратном порядке регистрации, поэтому регистрируем последним
    # чтобы он выполнился первым
    dp.update.middleware(StructuredLoggingMiddleware())

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(handlers_router)
    print(f"Подключен: {handlers_router}")
    
    # ФИКС №2: Восстановление состояния групп после перезапуска
    try:
        from bot.database.session import get_session
        from bot.database.models import Group, UserGroup
        from sqlalchemy import select, delete
        
        async with get_session() as session:
            result = await session.execute(select(Group))
            groups = result.scalars().all()
            bot_me = await bot.me()
            
            logging.info(f"🔄 Начинаем восстановление {len(groups)} групп...")
            
            for group in groups:
                # БАГ #4 ФИКС: пропускаем служебную запись группы с chat_id=0
                if group.chat_id == 0:
                    logging.info("ℹ️ Пропуск служебной записи группы с chat_id=0 при восстановлении")
                    continue
                try:
                    # Проверяем, что бот всё ещё в группе
                    try:
                        member = await bot.get_chat_member(group.chat_id, bot_me.id)
                        if member.status in ("member", "administrator", "creator"):
                            logging.info(f"✅ Бот восстановлен в группе {group.title} (ID: {group.chat_id})")
                            
                            # Обновляем информацию о группе (title может измениться)
                            try:
                                chat = await bot.get_chat(group.chat_id)
                                group.title = chat.title
                                await session.flush()
                            except Exception as e:
                                logging.warning(f"⚠️ Не удалось обновить название группы {group.chat_id}: {e}")
                            
                            # Восстанавливаем права админов в группе
                            try:
                                admins = await bot.get_chat_administrators(group.chat_id)
                                for admin_member in admins:
                                    if admin_member.status in ("administrator", "creator"):
                                        admin_user_id = admin_member.user.id
                                        # Проверяем, есть ли связь в БД
                                        ug_result = await session.execute(
                                            select(UserGroup).where(
                                                UserGroup.user_id == admin_user_id,
                                                UserGroup.group_id == group.chat_id,
                                            )
                                        )
                                        if not ug_result.scalar_one_or_none():
                                            # Создаем связь если её нет
                                            session.add(UserGroup(user_id=admin_user_id, group_id=group.chat_id))
                                            logging.info(f"✅ Восстановлена связь админа {admin_user_id} с группой {group.chat_id}")
                                await session.flush()
                            except Exception as e:
                                logging.warning(f"⚠️ Не удалось восстановить права админов для группы {group.chat_id}: {e}")
                        else:
                            logging.warning(f"⚠️ Бот не является участником группы {group.title} (ID: {group.chat_id})")
                    except Exception as e:
                        # Бот не в группе или группа удалена - чистим связи
                        error_str = str(e).lower()
                        if "chat not found" in error_str or "user not found" in error_str:
                            logging.warning(f"⚠️ Группа {group.chat_id} не найдена, удаляем связи")
                            await session.execute(
                                delete(UserGroup).where(UserGroup.group_id == group.chat_id)
                            )
                            await session.flush()
                        else:
                            logging.warning(f"⚠️ Не удалось проверить группу {group.chat_id}: {e}")
                except Exception as e:
                    logging.error(f"❌ Ошибка при обработке группы {group.chat_id}: {e}")
            
            await session.commit()
            logging.info(f"✅ Восстановление групп завершено")
    except Exception as e:
        logging.error(f"❌ Ошибка при восстановлении групп: {e}")
        import traceback
        logging.error(traceback.format_exc())
    
    # ✅ Выбираем режим запуска: webhook или polling
    if USE_WEBHOOK:
        logging.info("🌐 Запуск в режиме webhook...")
        logging.info(f"📋 WEBHOOK_URL из конфига: {WEBHOOK_URL}")
        
        if not WEBHOOK_URL:
            logging.error("❌ WEBHOOK_URL не установлен в конфигурации! Проверьте .env файл.")
            raise ValueError("WEBHOOK_URL не установлен")
        
        try:
            # Удаляем старый webhook
            logging.info("🔄 Удаление старого webhook...")
            deleted = await bot.delete_webhook(drop_pending_updates=True)
            logging.info(f"✅ Старый webhook удален: {deleted}")
            
            # Устанавливаем новый webhook
            logging.info(f"🔧 Установка webhook: {WEBHOOK_URL}")
            set_result = await bot.set_webhook(
                WEBHOOK_URL,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "chat_member", "my_chat_member", "chat_join_request"]
            )
            logging.info(f"📤 Результат set_webhook: {set_result}")
            
            # Проверяем статус webhook через API
            logging.info("🔍 Проверка статуса webhook через get_webhook_info...")
            webhook_info = await bot.get_webhook_info()
            logging.info(f"📊 Информация о webhook:")
            logging.info(f"   - URL: {webhook_info.url}")
            logging.info(f"   - Pending updates: {webhook_info.pending_update_count}")
            logging.info(f"   - Has custom cert: {webhook_info.has_custom_certificate}")
            logging.info(f"   - Max connections: {webhook_info.max_connections}")
            
            if webhook_info.url == WEBHOOK_URL:
                logging.info(f"✅ Webhook успешно установлен и проверен: {WEBHOOK_URL}")
            else:
                logging.warning(f"⚠️ Webhook установлен, но URL не совпадает!")
                logging.warning(f"   Ожидалось: {WEBHOOK_URL}")
                logging.warning(f"   Получено: {webhook_info.url}")
            
            if webhook_info.last_error_date:
                logging.warning(f"⚠️ Последняя ошибка webhook:")
                logging.warning(f"   - Дата: {webhook_info.last_error_date}")
                logging.warning(f"   - Сообщение: {webhook_info.last_error_message}")
            else:
                logging.info("✅ Ошибок webhook не обнаружено")
                
        except Exception as e:
            logging.error(f"❌ Ошибка при установке Webhook: {e}")
            import traceback
            logging.error(f"📋 Трассировка ошибки:")
            logging.error(traceback.format_exc())
            raise

        # Импортируем и запускаем webhook
        # Передаем bot и dp чтобы использовать уже подключенные handlers
        from bot.webhook import run_webhook
        logging.info("🚀 Запуск webhook сервера...")
        await run_webhook(bot=bot, dp=dp)
    else:
        logging.info("🔄 Запуск в режиме polling...")
        # Удаление вебхука перед запуском поллинга
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
