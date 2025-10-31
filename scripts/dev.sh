#!/bin/bash
# Скрипт для запуска dev окружения

echo "🚀 Запуск dev окружения..."

# Копируем .env файл если его нет
if [ ! -f ".env.dev" ]; then
    echo "📋 Копируем env.dev.example в .env.dev..."
    cp env.dev.example .env.dev
    echo "⚠️  Не забудьте заполнить .env.dev реальными значениями!"
fi

# Запускаем dev окружение
export ENVIRONMENT=development
docker-compose -f docker-compose.dev.yml up --build
