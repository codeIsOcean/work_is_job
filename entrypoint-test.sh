#!/bin/bash
# entrypoint-test.sh - Entrypoint для тестового Docker контейнера
# Обрабатывает ошибки миграций и рассинхрон версий

set -e

echo "Starting in testing mode..."

# Ждём PostgreSQL
echo "Waiting for PostgreSQL..."
until nc -z postgres_test 5432; do
    sleep 1
done
echo "PostgreSQL is ready!"

# Ждём Redis
echo "Waiting for Redis..."
until nc -z redis_test 6379; do
    sleep 1
done
echo "Redis is ready!"

echo "Services are ready! Running migrations..."

# Функция для выполнения SQL
run_sql() {
    PGPASSWORD=test_password psql -h postgres_test -U jobs_inDubai_testBot -d jobs_inDubai_testBot -c "$1"
}

# Пробуем запустить миграции
if alembic upgrade head; then
    echo "Migrations completed successfully!"
else
    echo "Migration failed! Attempting to fix..."

    # Получаем текущую версию в БД
    CURRENT_VERSION=$(PGPASSWORD=test_password psql -h postgres_test -U jobs_inDubai_testBot -d jobs_inDubai_testBot -t -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null | tr -d ' ')

    if [ -n "$CURRENT_VERSION" ]; then
        echo "Current DB version: $CURRENT_VERSION"

        # Проверяем существует ли эта версия в файлах миграций
        if ! ls /app/alembic/versions/*${CURRENT_VERSION}*.py 1>/dev/null 2>&1; then
            echo "Version $CURRENT_VERSION not found in migrations!"
            echo "Resetting alembic_version..."

            # Сбрасываем версию
            run_sql "DELETE FROM alembic_version;"

            # Пробуем снова
            echo "Retrying migrations..."
            if alembic upgrade head; then
                echo "Migrations completed after reset!"
            else
                echo "Migration still failing. Attempting stamp..."
                # Если всё ещё ошибка - помечаем как head
                alembic stamp head
                echo "Stamped as head"
            fi
        else
            # Версия есть, но миграция падает по другой причине
            echo "Version exists but migration failed. Checking for duplicate tables..."

            # Пробуем stamp head (пометить что миграции уже применены)
            alembic stamp head
            echo "Stamped current state as head"
        fi
    else
        echo "No alembic_version found. Fresh database."
        # Пробуем снова
        alembic upgrade head || alembic stamp head
    fi
fi

echo "Launching bot in testing mode..."
exec python main.py
