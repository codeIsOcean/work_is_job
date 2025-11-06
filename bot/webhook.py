"""
Webhook система для Telegram бота
"""
import asyncio
import logging
import ssl
from aiohttp import web, web_request
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter

from bot.config import (
    BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_PORT,
    SSL_CERT_PATH, SSL_KEY_PATH, REDIS_URL, USE_WEBHOOK
)
from bot.database.session import engine, async_session
from bot.database.models import Base
from bot.middleware.db_session import DbSessionMiddleware
from bot.handlers import handlers_router, create_fresh_handlers_router
from bot.services.redis_conn import test_connection

logger = logging.getLogger(__name__)


async def create_app(bot: Bot = None, dp: Dispatcher = None) -> web.Application:
    """Создание и настройка веб-приложения для webhook"""
    
    # Создаем отказоустойчивое хранилище
    try:
        await test_connection()
        storage = RedisStorage.from_url(REDIS_URL)
        logger.info("✅ Redis подключен для webhook")
    except Exception as e:
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        logger.warning(f"⚠️ Redis недоступен для webhook: {e}")
        logger.info("ℹ️ Используется MemoryStorage для webhook")

    # Создание таблиц в БД
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Используем переданные bot и dp, или создаем новые
    if bot is None or dp is None:
        # Создание бота и диспетчера (если не переданы)
        session = AiohttpSession(timeout=60.0)
        bot = Bot(token=BOT_TOKEN, session=session)
        dp = Dispatcher(storage=storage)
        
        # Подключение middleware (только если создаем новый dispatcher)
        dp.update.middleware(DbSessionMiddleware(async_session))
        
        # Подключение структурированного логирования
        from bot.middleware.structured_logging import StructuredLoggingMiddleware
        dp.update.middleware(StructuredLoggingMiddleware())
    else:
        # Dispatcher передан из bot.py - middleware уже подключен
        logger.info("ℹ️ Используем dispatcher из bot.py с уже подключенными middleware")

    # Подключение маршрутов
    # Если bot и dp переданы из bot.py - handlers уже подключены
    # Если создаем новый dispatcher - нужно подключить handlers
    if bot is not None and dp is not None:
        # Dispatcher передан из bot.py - handlers уже подключены
        logger.info(f"✅ Используем dispatcher с уже подключенными handlers из bot.py")
    else:
        # Создаем новый dispatcher - нужно подключить handlers
        try:
            # Проверяем, подключен ли router уже к другому dispatcher
            if hasattr(handlers_router, '_parent_router') and handlers_router._parent_router is not None:
                # Router уже подключен к другому dispatcher - используем create_fresh_handlers_router
                from bot.handlers import create_fresh_handlers_router
                fresh_router = create_fresh_handlers_router()
                dp.include_router(fresh_router)
                logger.info(f"✅ Подключен новый router для webhook (router был переиспользован)")
            else:
                dp.include_router(handlers_router)
                logger.info(f"✅ Подключен router для webhook")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения router: {e}")
            # Если ошибка - продолжаем без router (только middleware)
            pass

    # Создание веб-приложения
    app = web.Application()

    # КРИТИЧНО: Отключаем встроенное логирование aiogram для апдейтов ДО регистрации handler
    # Это должно предотвратить логирование "📩 Получен апдейт от Telegram"
    for log_name in ["aiogram.dispatcher", "aiogram.event", "aiogram"]:
        lg = logging.getLogger(log_name)
        lg.setLevel(logging.ERROR)  # Только ошибки - отключаем INFO логи
    
    # Настройка webhook
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Настройка приложения
    setup_application(app, dp, bot=bot)

    # Health check endpoint
    async def health_check(request):
        return web.json_response({"status": "ok", "service": "telegram_bot"})

    app.router.add_get("/health", health_check)

    # Установка webhook
    if USE_WEBHOOK:
        await setup_webhook(bot)

    return app


async def setup_webhook(bot: Bot):
    """Настройка webhook для бота"""
    if not WEBHOOK_URL:
        logger.error("❌ WEBHOOK_URL не установлен в конфигурации! Проверьте .env файл.")
        raise ValueError("WEBHOOK_URL не установлен")

    logger.info(f"📋 WEBHOOK_URL из конфига: {WEBHOOK_URL}")

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            # Удаляем старый webhook
            logger.info("🔄 Удаление старого webhook...")
            deleted = await bot.delete_webhook(drop_pending_updates=True)
            logger.info(f"✅ Старый webhook удален: {deleted}")

            # Небольшая задержка помогает избежать лимитов Telegram при частых обновлениях
            await asyncio.sleep(1)

            # Устанавливаем новый webhook
            logger.info(f"🔧 Установка webhook: {WEBHOOK_URL}")
            set_result = await bot.set_webhook(
                url=WEBHOOK_URL,
                drop_pending_updates=True,
                secret_token=None,  # Можно добавить секретный токен для безопасности
                allowed_updates=["message", "callback_query", "chat_member", "my_chat_member", "chat_join_request"]
            )
            logger.info(f"📤 Результат set_webhook: {set_result}")

            # Проверяем статус webhook через API
            logger.info("🔍 Проверка статуса webhook через get_webhook_info...")
            webhook_info = await bot.get_webhook_info()
            logger.info(f"📊 Информация о webhook:")
            logger.info(f"   - URL: {webhook_info.url}")
            logger.info(f"   - Pending updates: {webhook_info.pending_update_count}")
            logger.info(f"   - Has custom cert: {webhook_info.has_custom_certificate}")
            logger.info(f"   - Max connections: {webhook_info.max_connections}")

            if webhook_info.url == WEBHOOK_URL:
                logger.info(f"✅ Webhook успешно установлен и проверен: {WEBHOOK_URL}")
            else:
                logger.warning(f"⚠️ Webhook установлен, но URL не совпадает!")
                logger.warning(f"   Ожидалось: {WEBHOOK_URL}")
                logger.warning(f"   Получено: {webhook_info.url}")

            if webhook_info.last_error_date:
                logger.warning(f"⚠️ Последняя ошибка webhook:")
                logger.warning(f"   - Дата: {webhook_info.last_error_date}")
                logger.warning(f"   - Сообщение: {webhook_info.last_error_message}")
            else:
                logger.info("✅ Ошибок webhook не обнаружено")

            return

        except TelegramRetryAfter as e:
            wait_seconds = max(int(getattr(e, "retry_after", 1)), 1)
            logger.warning(
                f"⚠️ Попытка {attempt}/{max_attempts} — Telegram вернул Flood control на set_webhook. "
                f"Повтор через {wait_seconds} сек."
            )
            if attempt == max_attempts:
                logger.error("❌ Достигнут лимит попыток установки webhook, прекращаем попытки.")
                raise
            await asyncio.sleep(wait_seconds)

        except Exception as e:
            logger.error(f"❌ Ошибка настройки webhook на попытке {attempt}: {e}")
            import traceback
            logger.error(f"📋 Трассировка ошибки:")
            logger.error(traceback.format_exc())
            if attempt == max_attempts:
                raise
            await asyncio.sleep(2)


async def run_webhook(bot: Bot = None, dp: Dispatcher = None):
    """Запуск webhook сервера"""
    if not USE_WEBHOOK:
        logger.info("ℹ️ Webhook отключен, запускаем polling...")
        return

    app = await create_app(bot=bot, dp=dp)
    
    # SSL обрабатывается на уровне nginx, поэтому бот работает по HTTP внутри сети
    # Настройка SSL для продакшна (если бот работает напрямую, без nginx)
    ssl_context = None
    # Отключаем SSL для работы через nginx
    # if SSL_CERT_PATH and SSL_KEY_PATH:
    #     try:
    #         ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    #         ssl_context.load_cert_chain(SSL_CERT_PATH, SSL_KEY_PATH)
    #         logger.info("✅ SSL контекст загружен")
    #     except Exception as e:
    #         logger.warning(f"⚠️ Ошибка загрузки SSL: {e}")

    # Запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(
        runner, 
        host='0.0.0.0', 
        port=WEBHOOK_PORT,
        ssl_context=ssl_context  # None - HTTP внутри сети, SSL на nginx
    )
    
    await site.start()
    logger.info(f"🚀 Webhook сервер запущен на порту {WEBHOOK_PORT}")
    
    try:
        await asyncio.Future()  # Бесконечный цикл
    except KeyboardInterrupt:
        logger.info("🛑 Остановка webhook сервера...")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_webhook())
