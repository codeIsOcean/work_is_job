#!/bin/bash
# Скрипт для автоматической настройки GitHub Secrets через GitHub CLI

set -e

echo "🔧 Настройка GitHub Secrets для CI/CD"
echo ""

# Проверяем наличие GitHub CLI
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) не установлен!"
    echo ""
    echo "📋 Установка GitHub CLI:"
    echo "   Windows: winget install GitHub.cli"
    echo "   macOS: brew install gh"
    echo "   Linux: sudo apt install gh"
    echo ""
    echo "После установки выполните: gh auth login"
    exit 1
fi

# Проверяем авторизацию
if ! gh auth status &> /dev/null; then
    echo "❌ GitHub CLI не авторизован!"
    echo "   Выполните: gh auth login"
    exit 1
fi

# Получаем информацию о репозитории
REPO_OWNER=$(gh repo view --json owner -q .owner.login)
REPO_NAME=$(gh repo view --json name -q .name)

echo "📋 Репозиторий: $REPO_OWNER/$REPO_NAME"
echo ""

# Получаем SSH ключ с сервера
echo "🔑 Получение SSH ключа с сервера..."
SSH_KEY=$(ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" 2>/dev/null || echo "")

if [ -z "$SSH_KEY" ]; then
    echo "❌ Не удалось получить SSH ключ с сервера"
    echo "   Проверьте SSH подключение к серверу"
    exit 1
fi

echo "✅ SSH ключ получен"
echo ""

# Добавляем secrets
echo "📝 Добавление secrets в GitHub..."
echo ""

gh secret set TEST_SERVER_HOST --body "88.210.35.183" --repo "$REPO_OWNER/$REPO_NAME"
echo "✅ TEST_SERVER_HOST добавлен"

gh secret set TEST_SERVER_USER --body "root" --repo "$REPO_OWNER/$REPO_NAME"
echo "✅ TEST_SERVER_USER добавлен"

gh secret set TEST_SERVER_SSH_KEY --body "$SSH_KEY" --repo "$REPO_OWNER/$REPO_NAME"
echo "✅ TEST_SERVER_SSH_KEY добавлен"

echo ""
echo "✅ Готово! Все secrets добавлены в GitHub"
echo ""
echo "🎉 Теперь можно использовать CI/CD!"
echo "   Сделай push в ветку 'test' чтобы проверить деплой"
