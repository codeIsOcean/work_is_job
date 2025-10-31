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

#from bot.handlers import handlers_router
from bot.services.redis_conn import test_connection

from bot.config import BOT_TOKEN, USE_WEBHOOK
from bot.database.session import engine, async_session
from bot.database.models import Base
from bot.middleware.db_session import DbSessionMiddleware  # Добавляем импорт DbSessionMiddleware
from bot.handlers import handlers_router

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

# Настройка логгеров aiogram - только консоль
for logger_name in ("aiogram", "aiogram.dispatcher", "aiogram.event"):
    log = logging.getLogger(logger_name)
    log.addHandler(console_handler)
    log.propagate = False

# определяем, где мы запускаемся
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)  # Добавляем поддержку пароля


# главная асинхронная функция, запускающая бота
async def main():
    logging.info("🤖 Бот успешно запущен и готов к работе.")

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
    # ✅ Создание бота по токену из .env
    session = AiohttpSession(timeout=60.0)
    bot = Bot(token=BOT_TOKEN, session=session)
    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=storage)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(handlers_router)
    print(f"Подключен: {handlers_router}")
    
    # ✅ Выбираем режим запуска: webhook или polling
    if USE_WEBHOOK:
        logging.info("🌐 Запуск в режиме webhook...")
        # Удаление старого webhook перед запуском
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Импортируем и запускаем webhook
        # Передаем bot и dp чтобы использовать уже подключенные handlers
        from bot.webhook import run_webhook
        await run_webhook(bot=bot, dp=dp)
    else:
        logging.info("🔄 Запуск в режиме polling...")
        # Удаление вебхука перед запуском поллинга
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

