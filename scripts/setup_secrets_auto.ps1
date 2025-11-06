# Автоматическая настройка GitHub Secrets
# Этот скрипт настраивает все необходимые secrets для CI/CD

param(
    [string]$GitHubToken = $env:GITHUB_TOKEN
)

$repo = "codeIsOcean/work_is_job"
$sshKey = @"
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40AAAAJgxelFNMXpR
TQAAAAtzc2gtZWQyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40A
AAAEDbo3lGqkb+SfD1zdg0lnK5Kjim8a1xKWLnynL6T1pI0RzJ78ggo+cEbEkWnq6kQISg
HBaKyCbXldMEf4o3xPjQAAAAFWdpdGh1Yi1hY3Rpb25zLWRlcGxveQ==
-----END OPENSSH PRIVATE KEY-----
"@

Write-Host "🔐 Настройка GitHub Secrets для CI/CD" -ForegroundColor Cyan
Write-Host ""

# Проверка GitHub CLI
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "❌ GitHub CLI не установлен!" -ForegroundColor Red
    Write-Host "Установи: https://cli.github.com/" -ForegroundColor Yellow
    exit 1
}

# Проверка авторизации
Write-Host "📋 Проверка авторизации GitHub CLI..." -ForegroundColor Yellow
$authCheck = gh auth status 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ GitHub CLI не авторизован!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Авторизуйся в GitHub CLI:" -ForegroundColor Cyan
    Write-Host "  gh auth login" -ForegroundColor White
    Write-Host ""
    Write-Host "Или используй токен:" -ForegroundColor Cyan
    Write-Host "  gh auth login --with-token" -ForegroundColor White
    Write-Host ""
    
    # Пробуем авторизоваться автоматически
    Write-Host "Попытка авторизации через браузер..." -ForegroundColor Yellow
    gh auth login --web --hostname github.com 2>&1 | Out-Null
    
    Start-Sleep -Seconds 3
    
    $authCheck = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Авторизация не завершена. Заверши авторизацию в браузере и запусти скрипт снова." -ForegroundColor Red
        exit 1
    }
}

Write-Host "✅ GitHub CLI авторизован" -ForegroundColor Green
Write-Host ""

# Настройка secrets
Write-Host "🔧 Настройка secrets..." -ForegroundColor Yellow

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
gh secret set TEST_SERVER_SSH_KEY --body $sshKey 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✅ Установлен" -ForegroundColor Green
} else {
    Write-Host "    ❌ Ошибка" -ForegroundColor Red
}

Write-Host ""
Write-Host "✅ Все secrets настроены!" -ForegroundColor Green
Write-Host ""

# Проверка secrets
Write-Host "📋 Проверка настроенных secrets:" -ForegroundColor Cyan
gh secret list

Write-Host ""
Write-Host "🎉 Готово! Теперь CI/CD должен работать при push в ветку test или main" -ForegroundColor Green

