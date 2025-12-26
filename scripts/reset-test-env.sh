#!/bin/bash
# reset-test-env.sh - Полный сброс тестового окружения Docker
# Используй когда миграции рассинхронились или нужен чистый старт
#
# ВАЖНО: Папка backup/ НЕ удаляется! Там хранится бэкап групп.
# Бот восстановит группы из бэкапа после перезапуска.

echo "=== Resetting Test Environment ==="

# Проверяем что бэкап сохранён
if [ -f "backup/groups_backup.json" ]; then
    echo "✅ Бэкап групп найден: backup/groups_backup.json"
    echo "   Группы будут восстановлены после перезапуска"
else
    echo "⚠️ ВНИМАНИЕ: Бэкап групп НЕ найден!"
    echo "   Группы НЕ будут восстановлены!"
    read -p "Продолжить? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Остановить контейнеры
echo "[1/5] Stopping containers..."
docker-compose -f docker-compose.test.yml down

# Удалить volumes (ВНИМАНИЕ: удаляет БД и Redis, НО НЕ бэкап!)
echo "[2/5] Removing volumes (backup/ сохраняется!)..."
docker volume rm test_kvdmoderbotprod_postgres_test_data 2>/dev/null || true
docker volume rm test_kvdmoderbotprod_redis_test_data 2>/dev/null || true

# Пересобрать образ бота
echo "[3/5] Rebuilding bot image..."
docker-compose -f docker-compose.test.yml build bot_test

# Запустить всё
echo "[4/5] Starting services..."
docker-compose -f docker-compose.test.yml up -d

# Подождать запуска
echo "[5/5] Waiting for services to start..."
sleep 15

# Показать логи
echo ""
echo "=== Bot Logs ==="
docker logs bot_test --tail 30

echo ""
echo "=== Done! ==="
echo "Test environment has been reset."
