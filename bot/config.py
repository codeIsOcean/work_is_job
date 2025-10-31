import os
from dotenv import load_dotenv
from typing import List, Optional

# Всегда ищем .env относительно корня проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Определяем окружение
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Получаем путь до .env файла в зависимости от окружения
if ENVIRONMENT == "production":
    env_file = ".env.prod"
elif ENVIRONMENT == "testing":
    env_file = ".env.test"
else:
    env_file = ".env.dev"

# Проверяем, есть ли переменная ENV_PATH (для Docker)
env_path = os.getenv("ENV_PATH")
if not env_path:
    env_path = os.path.join(BASE_DIR, env_file)

print(f"🔧 Окружение: {ENVIRONMENT}")
print(f"📁 Загрузка env из: {env_path}")
print(f"📁 Абсолютный путь: {os.path.abspath(env_path)}")
print(f"📁 Текущая рабочая директория: {os.getcwd()}")

# Загружаем .env файл
load_dotenv(dotenv_path=env_path)

# Основные настройки бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
raw_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]

# Redis настройки
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Webhook настройки
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

# Настройки базы данных
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

# Настройки логирования
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Настройки безопасности
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost").split(",")

# Rate limiting
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# Мониторинг
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "false").lower() == "true"
METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))

# SSL настройки
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "")

# Backup настройки
BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "false").lower() == "true"
BACKUP_SCHEDULE = os.getenv("BACKUP_SCHEDULE", "0 2 * * *")
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))

# Валидация обязательных параметров
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не установлен!")

# Выводим информацию о конфигурации (без секретных данных)
print(f"✅ BOT_TOKEN: {'*' * (len(BOT_TOKEN) - 4) + BOT_TOKEN[-4:] if BOT_TOKEN else 'НЕ УСТАНОВЛЕН'}")
print(f"✅ DATABASE_URL: {DATABASE_URL[:20]}..." if DATABASE_URL else "НЕ УСТАНОВЛЕН")
print(f"✅ LOG_CHANNEL_ID: {LOG_CHANNEL_ID}")
print(f"✅ ADMIN_IDS: {ADMIN_IDS}")
print(f"✅ USE_WEBHOOK: {USE_WEBHOOK}")
print(f"✅ ENVIRONMENT: {ENVIRONMENT}")
print(f"✅ DEBUG: {DEBUG}")
print(f"✅ LOG_LEVEL: {LOG_LEVEL}")

