# Быстрая настройка secrets одной командой
# Использование: просто скопируй и выполни эти команды в PowerShell

Write-Host "🔐 Настройка GitHub Secrets..." -ForegroundColor Cyan
Write-Host ""

# Проверка авторизации
$auth = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ Сначала авторизуйся:" -ForegroundColor Yellow
    Write-Host "gh auth login" -ForegroundColor White
    Write-Host ""
    exit 1
}

Write-Host "✅ GitHub CLI авторизован" -ForegroundColor Green
Write-Host ""

# Получение SSH ключа
Write-Host "📥 Получение SSH ключа..." -ForegroundColor Yellow
$sshKey = ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy"

Write-Host "🔧 Настройка secrets..." -ForegroundColor Yellow

gh secret set TEST_SERVER_HOST --body "88.210.35.183"
gh secret set TEST_SERVER_USER --body "root"
echo $sshKey | gh secret set TEST_SERVER_SSH_KEY

Write-Host ""
Write-Host "✅ Готово! Secrets настроены!" -ForegroundColor Green
gh secret list

