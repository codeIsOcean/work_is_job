# Финальная настройка GitHub Secrets для CI/CD
# Запусти после: gh auth login

Write-Host "🔐 Настройка GitHub Secrets для CI/CD" -ForegroundColor Cyan
Write-Host ""

# Проверка авторизации
$authCheck = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ GitHub CLI не авторизован!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Авторизуйся:" -ForegroundColor Yellow
    Write-Host "  gh auth login" -ForegroundColor White
    Write-Host ""
    Write-Host "Выбери: GitHub.com → HTTPS → авторизуйся в браузере" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ GitHub CLI авторизован" -ForegroundColor Green
Write-Host ""

# Получение SSH ключа с сервера
Write-Host "📥 Получение SSH ключа с тестового сервера..." -ForegroundColor Yellow
$sshKey = ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Ошибка при получении SSH ключа!" -ForegroundColor Red
    Write-Host "Убедись что SSH ключ существует на сервере" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ SSH ключ получен" -ForegroundColor Green
Write-Host ""

# Настройка secrets для тестового окружения
Write-Host "🔧 Настройка тестовых secrets..." -ForegroundColor Yellow

Write-Host "  → TEST_SERVER_HOST = 88.210.35.183" -ForegroundColor Gray
gh secret set TEST_SERVER_HOST --body "88.210.35.183" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✅ Установлен" -ForegroundColor Green
} else {
    Write-Host "    ❌ Ошибка" -ForegroundColor Red
}

Write-Host "  → TEST_SERVER_USER = root" -ForegroundColor Gray
gh secret set TEST_SERVER_USER --body "root" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✅ Установлен" -ForegroundColor Green
} else {
    Write-Host "    ❌ Ошибка" -ForegroundColor Red
}

Write-Host "  → TEST_SERVER_SSH_KEY" -ForegroundColor Gray
$sshKey | gh secret set TEST_SERVER_SSH_KEY 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✅ Установлен" -ForegroundColor Green
} else {
    Write-Host "    ❌ Ошибка" -ForegroundColor Red
}

Write-Host ""
Write-Host "✅ Все тестовые secrets настроены!" -ForegroundColor Green
Write-Host ""

# Проверка secrets
Write-Host "📋 Настроенные secrets:" -ForegroundColor Cyan
gh secret list

Write-Host ""
Write-Host "🎉 Готово! CI/CD настроен для тестового окружения!" -ForegroundColor Green
Write-Host ""
Write-Host "Для продакшна добавь:" -ForegroundColor Yellow
Write-Host "  gh secret set PROD_SERVER_HOST --body IP_продакшн_сервера" -ForegroundColor White
Write-Host "  gh secret set PROD_SERVER_USER --body root" -ForegroundColor White
Write-Host "  Получи SSH ключ с продакшн сервера и выполни:" -ForegroundColor White
Write-Host "  gh secret set PROD_SERVER_SSH_KEY --body SSH_KEY_ЗДЕСЬ" -ForegroundColor White

