#!/bin/bash
# Скрипт для быстрого деплоя на сервер
# Использование: ./scripts/deploy.sh user@server-ip

set -e

if [ -z "$1" ]; then
    echo "❌ Использование: ./scripts/deploy.sh user@server-ip"
    echo "Пример: ./scripts/deploy.sh root@192.168.1.100"
    exit 1
fi

SERVER=$1
SERVER_PATH="/opt/jobs_inDubai_prod"

echo "🚀 Начинаю деплой на сервер $SERVER..."

# Копируем необходимые файлы на сервер
echo "📦 Копирование файлов..."
scp docker-compose.prod.yml "$SERVER:$SERVER_PATH/"
scp Dockerfile.prod "$SERVER:$SERVER_PATH/"
scp -r nginx "$SERVER:$SERVER_PATH/" || echo "⚠️ Nginx уже существует"

# Подключаемся к серверу и запускаем деплой
echo "🔧 Запуск на сервере..."
ssh "$SERVER" << 'EOF'
cd /opt/jobs_inDubai_prod

# Проверяем, что .env.prod существует
if [ ! -f .env.prod ]; then
    echo "❌ Файл .env.prod не найден!"
    echo "Создайте его из env.prod.example и заполните все переменные"
    exit 1
fi

# Останавливаем старые контейнеры
echo "🛑 Остановка старых контейнеров..."
docker compose -f docker-compose.prod.yml down || docker-compose -f docker-compose.prod.yml down || true

# Запускаем новые контейнеры
echo "🚀 Запуск новых контейнеров..."
docker compose -f docker-compose.prod.yml up -d --build || docker-compose -f docker-compose.prod.yml up -d --build

# Показываем статус
echo "📊 Статус контейнеров:"
docker compose -f docker-compose.prod.yml ps || docker-compose -f docker-compose.prod.yml ps

echo "✅ Деплой завершен!"
echo "📝 Просмотр логов: docker compose -f docker-compose.prod.yml logs -f bot_prod"
EOF

echo "✅ Готово!"

