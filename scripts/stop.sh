#!/bin/bash
# Скрипт для остановки всех окружений

echo "🛑 Остановка всех окружений..."

# Останавливаем все контейнеры
docker-compose -f docker-compose.dev.yml down
docker-compose -f docker-compose.test.yml down
docker-compose -f docker-compose.prod.yml down

echo "✅ Все окружения остановлены"
