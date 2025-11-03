# PowerShell скрипт для автоматической настройки GitHub Secrets через GitHub CLI

Write-Host "🔧 Настройка GitHub Secrets для CI/CD" -ForegroundColor Cyan
Write-Host ""

# Проверяем наличие GitHub CLI
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "❌ GitHub CLI (gh) не установлен!" -ForegroundColor Red
    Write-Host ""
    Write-Host "📋 Установка GitHub CLI:" -ForegroundColor Yellow
    Write-Host "   winget install GitHub.cli"
    Write-Host "   или скачай с https://cli.github.com/"
    Write-Host ""
    Write-Host "После установки выполните: gh auth login"
    exit 1
}

# Проверяем авторизацию
try {
    gh auth status 2>&1 | Out-Null
} catch {
    Write-Host "❌ GitHub CLI не авторизован!" -ForegroundColor Red
    Write-Host "   Выполните: gh auth login"
    exit 1
}

# Получаем информацию о репозитории
$repoOwner = gh repo view --json owner -q .owner.login
$repoName = gh repo view --json name -q .name

Write-Host "📋 Репозиторий: $repoOwner/$repoName" -ForegroundColor Green
Write-Host ""

# Получаем SSH ключ с сервера
Write-Host "🔑 Получение SSH ключа с сервера..." -ForegroundColor Cyan
try {
    $sshKey = ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" 2>&1
    
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sshKey)) {
        Write-Host "❌ Не удалось получить SSH ключ с сервера" -ForegroundColor Red
        Write-Host "   Проверьте SSH подключение к серверу"
        exit 1
    }
    
    Write-Host "✅ SSH ключ получен" -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "❌ Ошибка получения SSH ключа: $_" -ForegroundColor Red
    exit 1
}

# Добавляем secrets
Write-Host "📝 Добавление secrets в GitHub..." -ForegroundColor Cyan
Write-Host ""

gh secret set TEST_SERVER_HOST --body "88.210.35.183" --repo "$repoOwner/$repoName"
Write-Host "✅ TEST_SERVER_HOST добавлен" -ForegroundColor Green

gh secret set TEST_SERVER_USER --body "root" --repo "$repoOwner/$repoName"
Write-Host "✅ TEST_SERVER_USER добавлен" -ForegroundColor Green

gh secret set TEST_SERVER_SSH_KEY --body "$sshKey" --repo "$repoOwner/$repoName"
Write-Host "✅ TEST_SERVER_SSH_KEY добавлен" -ForegroundColor Green

Write-Host ""
Write-Host "✅ Готово! Все secrets добавлены в GitHub" -ForegroundColor Green
Write-Host ""
Write-Host "🎉 Теперь можно использовать CI/CD!" -ForegroundColor Cyan
Write-Host "   Сделай push в ветку 'test' чтобы проверить деплой" -ForegroundColor Yellow
