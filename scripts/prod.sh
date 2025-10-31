#!/bin/bash
# Скрипт для запуска prod окружения

echo "🚀 Запуск prod окружения..."

# Проверяем наличие .env файла
if [ ! -f ".env.prod" ]; then
    echo "❌ Файл .env.prod не найден!"
    echo "📋 Создайте .env.prod на основе env.prod.example"
    exit 1
fi

# Запускаем prod окружение
export ENVIRONMENT=production
docker-compose -f docker-compose.prod.yml up --build -d
