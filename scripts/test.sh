#!/bin/bash
# Скрипт для запуска test окружения

echo "🧪 Запуск test окружения..."

# Копируем .env файл если его нет
if [ ! -f ".env.test" ]; then
    echo "📋 Копируем env.test.example в .env.test..."
    cp env.test.example .env.test
    echo "⚠️  Не забудьте заполнить .env.test реальными значениями!"
fi

# Запускаем test окружение
export ENVIRONMENT=testing
docker-compose -f docker-compose.test.yml up --build
