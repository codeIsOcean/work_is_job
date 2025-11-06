# Настройка GitHub Secrets через GitHub API
# Использование: .\scripts\setup_secrets_api.ps1 -Token "your_github_token"

param(
    [Parameter(Mandatory=$true)]
    [string]$Token
)

$repo = "codeIsOcean/work_is_job"
$baseUrl = "https://api.github.com/repos/$repo/actions/secrets"

$headers = @{
    "Accept" = "application/vnd.github.v3+json"
    "Authorization" = "token $Token"
}

# Получение публичного ключа для шифрования
Write-Host "Получение публичного ключа репозитория..." -ForegroundColor Yellow
$publicKeyResponse = Invoke-RestMethod -Uri "$baseUrl/public-key" -Headers $headers -Method Get
$publicKey = $publicKeyResponse.key
$keyId = $publicKeyResponse.key_id

Write-Host "Публичный ключ получен" -ForegroundColor Green

# Функция для шифрования secret
function Encrypt-Secret {
    param([string]$Secret, [string]$PublicKey)
    
    # Устанавливаем ключ для шифрования
    $keyBytes = [System.Convert]::FromBase64String($PublicKey)
    
    # Используем libsodium для шифрования (требует установки)
    # Упрощенный подход - используем GitHub CLI если доступен
    return $Secret
}

# SSH ключ
$sshKey = @"
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40AAAAJgxelFNMXpR
TQAAAAtzc2gtZWQyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40A
AAAEDbo3lGqkb+SfD1zdg0lnK5Kjim8a1xKWLnynL6T1pI0RzJ78ggo+cEbEkWnq6kQISg
HBaKyCbXldMEf4o3xPjQAAAAFWdpdGh1Yi1hY3Rpb25zLWRlcGxveQ==
-----END OPENSSH PRIVATE KEY-----
"@

# Настройка secrets через GitHub CLI (проще и надежнее)
Write-Host "Настройка secrets через GitHub CLI..." -ForegroundColor Yellow

# Проверяем авторизацию
$authStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub CLI не авторизован. Используем токен..." -ForegroundColor Yellow
    $env:GH_TOKEN = $Token
    $env:GITHUB_TOKEN = $Token
}

Write-Host "Установка TEST_SERVER_HOST..." -ForegroundColor Gray
gh secret set TEST_SERVER_HOST --body "88.210.35.183" --repo $repo 2>&1 | Out-Null

Write-Host "Установка TEST_SERVER_USER..." -ForegroundColor Gray
gh secret set TEST_SERVER_USER --body "root" --repo $repo 2>&1 | Out-Null

Write-Host "Установка TEST_SERVER_SSH_KEY..." -ForegroundColor Gray
echo $sshKey | gh secret set TEST_SERVER_SSH_KEY --repo $repo 2>&1 | Out-Null

Write-Host ""
Write-Host "Проверка secrets:" -ForegroundColor Cyan
gh secret list --repo $repo

Write-Host ""
Write-Host "Готово!" -ForegroundColor Green

