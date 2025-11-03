# Automatic GitHub Secrets Setup using Personal Access Token
# This script will automatically add all secrets to GitHub

param(
    [string]$GITHUB_TOKEN = $env:GITHUB_TOKEN
)

Write-Host "Automatic GitHub Secrets Setup" -ForegroundColor Cyan
Write-Host ""

if ([string]::IsNullOrWhiteSpace($GITHUB_TOKEN)) {
    Write-Host "GitHub Personal Access Token required!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Quick setup (2 minutes):" -ForegroundColor Yellow
    Write-Host "1. Create token: https://github.com/settings/tokens/new" -ForegroundColor White
    Write-Host "   - Name: CI/CD Setup" -ForegroundColor Gray
    Write-Host "   - Expiration: 90 days (or No expiration)" -ForegroundColor Gray
    Write-Host "   - Scopes: repo (Full control of private repositories)" -ForegroundColor Gray
    Write-Host "   - Click 'Generate token'" -ForegroundColor Gray
    Write-Host ""
    Write-Host "2. Copy the token and run:" -ForegroundColor Yellow
    Write-Host "   `$env:GITHUB_TOKEN='your_token_here'" -ForegroundColor White
    Write-Host "   .\scripts\setup_github_secrets_with_token.ps1" -ForegroundColor White
    Write-Host ""
    Write-Host "OR set environment variable:" -ForegroundColor Yellow
    Write-Host "   [System.Environment]::SetEnvironmentVariable('GITHUB_TOKEN', 'your_token_here', 'User')" -ForegroundColor White
    exit 1
}

Write-Host "GitHub token found. Setting up secrets..." -ForegroundColor Green
Write-Host ""

# Get repository info
$repoOwner = "codeIsOcean"
$repoName = "work_is_job"

Write-Host "Repository: $repoOwner/$repoName" -ForegroundColor Green
Write-Host ""

# Get SSH key from server
Write-Host "Getting SSH key from server..." -ForegroundColor Cyan
try {
    $sshKey = ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" 2>&1
    
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sshKey)) {
        Write-Host "Failed to get SSH key from server" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "SSH key retrieved" -ForegroundColor Green
} catch {
    Write-Host "Error getting SSH key: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Get public key for encryption
Write-Host "Getting repository public key..." -ForegroundColor Cyan
try {
    $headers = @{
        "Accept" = "application/vnd.github.v3+json"
        "Authorization" = "token $GITHUB_TOKEN"
    }
    
    $response = Invoke-RestMethod -Uri "https://api.github.com/repos/$repoOwner/$repoName/actions/secrets/public-key" -Headers $headers -Method Get
    
    $publicKey = $response.key
    $keyId = $response.key_id
    
    Write-Host "Public key retrieved (key_id: $keyId)" -ForegroundColor Green
} catch {
    Write-Host "Error getting public key: $_" -ForegroundColor Red
    Write-Host "Check that token has 'repo' scope" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Encrypt secrets using libsodium (PyNaCl)
Write-Host "Encrypting secrets..." -ForegroundColor Cyan

# Install PyNaCl if needed
try {
    python -c "import nacl" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing PyNaCl..." -ForegroundColor Yellow
        pip install PyNaCl 2>&1 | Out-Null
    }
} catch {
    Write-Host "Installing PyNaCl..." -ForegroundColor Yellow
    pip install PyNaCl 2>&1 | Out-Null
}

# Encrypt secrets using Python
$pythonScript = @"
import base64
import sys
from nacl import encoding, public

def encrypt_secret(public_key_str, secret_value):
    public_key = public.PublicKey(public_key_str.encode('utf-8'), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')

public_key = sys.argv[1]
secret_value = sys.argv[2]
print(encrypt_secret(public_key, secret_value))
"@

$pythonScriptFile = "$env:TEMP\encrypt_secret.py"
$pythonScript | Out-File -FilePath $pythonScriptFile -Encoding UTF8

$secrets = @{
    "TEST_SERVER_HOST" = "88.210.35.183"
    "TEST_SERVER_USER" = "root"
    "TEST_SERVER_SSH_KEY" = $sshKey
}

Write-Host ""
Write-Host "Adding secrets to GitHub..." -ForegroundColor Cyan
Write-Host ""

$successCount = 0
foreach ($secretName in $secrets.Keys) {
    Write-Host "Adding '$secretName'..." -ForegroundColor Cyan
    
    try {
        # Encrypt secret
        $encryptedValue = python $pythonScriptFile $publicKey $secrets[$secretName] 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   Error encrypting $secretName" -ForegroundColor Red
            continue
        }
        
        # Add secret to GitHub
        $body = @{
            encrypted_value = $encryptedValue
            key_id = $keyId
        } | ConvertTo-Json
        
        $uri = "https://api.github.com/repos/$repoOwner/$repoName/actions/secrets/$secretName"
        
        $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Put -Body $body -ContentType "application/json"
        
        Write-Host "   $secretName added" -ForegroundColor Green
        $successCount++
    } catch {
        Write-Host "   Error adding $secretName : $_" -ForegroundColor Red
    }
}

# Cleanup
Remove-Item $pythonScriptFile -ErrorAction SilentlyContinue

Write-Host ""
if ($successCount -eq $secrets.Count) {
    Write-Host "Done! All $successCount secrets added to GitHub" -ForegroundColor Green
    Write-Host ""
    Write-Host "CI/CD is ready to use!" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Test it:" -ForegroundColor Yellow
    Write-Host "  git checkout test" -ForegroundColor Gray
    Write-Host "  git add ." -ForegroundColor Gray
    Write-Host "  git commit -m 'Test CI/CD'" -ForegroundColor Gray
    Write-Host "  git push origin test" -ForegroundColor Gray
} else {
    Write-Host "Warning: Added $successCount of $($secrets.Count) secrets" -ForegroundColor Yellow
}

