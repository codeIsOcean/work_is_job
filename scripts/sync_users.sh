#!/bin/bash
# ============================================================
# СКРИПТ СИНХРОНИЗАЦИИ ПОЛЬЗОВАТЕЛЕЙ
# Синхронизирует пользователей из postgres_prod в april_test_db
# Использование: ./sync_users.sh
# ============================================================

set -e

echo "=============================================="
echo "  СИНХРОНИЗАЦИЯ ПОЛЬЗОВАТЕЛЕЙ prod → april"
echo "=============================================="

# Проверяем что контейнеры запущены
if ! docker ps | grep -q postgres_prod; then
    echo "❌ Контейнер postgres_prod не запущен!"
    exit 1
fi

if ! docker ps | grep -q april_test_db; then
    echo "❌ Контейнер april_test_db не запущен!"
    exit 1
fi

# Считаем пользователей ДО синхронизации
USERS_BEFORE=$(docker exec april_test_db psql -U april_test_bot -d april_test_db -t -c "SELECT COUNT(*) FROM users;" | tr -d ' ')
echo "📊 Пользователей в april_test_db ДО: $USERS_BEFORE"

USERS_IN_PROD=$(docker exec postgres_prod psql -U postgres -d bot_prod -t -c "SELECT COUNT(*) FROM users;" | tr -d ' ')
echo "📊 Пользователей в postgres_prod: $USERS_IN_PROD"

# Генерируем INSERT запросы с ON CONFLICT DO NOTHING
echo "🔄 Синхронизация пользователей..."

docker exec postgres_prod psql -U postgres -d bot_prod -t -A -c "
SELECT 'INSERT INTO users (user_id, username, full_name, first_name, last_name, language_code, is_bot, is_premium, added_to_attachment_menu, can_join_groups, can_read_all_group_messages, supports_inline_queries, can_connect_to_business, has_main_web_app, created_at, updated_at) VALUES ('
    || user_id || ', '
    || COALESCE('''' || REPLACE(username, '''', '''''') || '''', 'NULL') || ', '
    || COALESCE('''' || REPLACE(full_name, '''', '''''') || '''', 'NULL') || ', '
    || COALESCE('''' || REPLACE(first_name, '''', '''''') || '''', 'NULL') || ', '
    || COALESCE('''' || REPLACE(last_name, '''', '''''') || '''', 'NULL') || ', '
    || COALESCE('''' || language_code || '''', 'NULL') || ', '
    || is_bot || ', '
    || is_premium || ', '
    || added_to_attachment_menu || ', '
    || can_join_groups || ', '
    || can_read_all_group_messages || ', '
    || supports_inline_queries || ', '
    || can_connect_to_business || ', '
    || has_main_web_app || ', '''
    || created_at || ''', '''
    || updated_at || ''') ON CONFLICT (user_id) DO NOTHING;'
FROM users;
" | docker exec -i april_test_db psql -U april_test_bot -d april_test_db > /dev/null 2>&1

# Считаем пользователей ПОСЛЕ синхронизации
USERS_AFTER=$(docker exec april_test_db psql -U april_test_bot -d april_test_db -t -c "SELECT COUNT(*) FROM users;" | tr -d ' ')
echo "📊 Пользователей в april_test_db ПОСЛЕ: $USERS_AFTER"

# Вычисляем сколько добавлено
ADDED=$((USERS_AFTER - USERS_BEFORE))
echo ""
echo "=============================================="
echo "  РЕЗУЛЬТАТ СИНХРОНИЗАЦИИ"
echo "=============================================="
echo "✅ Добавлено новых пользователей: $ADDED"
echo "📊 Всего пользователей в april: $USERS_AFTER"
echo "=============================================="
