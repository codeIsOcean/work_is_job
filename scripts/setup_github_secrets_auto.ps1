# Automatic GitHub Secrets Setup Script
# Fully automatic setup of CI/CD secrets

Write-Host "Setting up GitHub Secrets for CI/CD" -ForegroundColor Cyan
Write-Host ""

# Check GitHub CLI installation
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "GitHub CLI (gh) not installed!" -ForegroundColor Red
    Write-Host "Installing GitHub CLI..." -ForegroundColor Yellow
    winget install --id GitHub.cli --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    Start-Sleep -Seconds 3
    
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Host "Failed to install GitHub CLI. Install manually: winget install GitHub.cli" -ForegroundColor Red
        exit 1
    }
    Write-Host "GitHub CLI installed" -ForegroundColor Green
}

# Check authorization
Write-Host "Checking GitHub CLI authorization..." -ForegroundColor Cyan
$authStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub CLI not authorized" -ForegroundColor Yellow
    Write-Host "Starting authorization..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Follow instructions on screen:" -ForegroundColor Cyan
    Write-Host "   1. Select GitHub.com" -ForegroundColor Yellow
    Write-Host "   2. Select HTTPS" -ForegroundColor Yellow
    Write-Host "   3. Authorize through browser" -ForegroundColor Yellow
    Write-Host ""
    
    gh auth login --web
    if ($LASTEXITCODE -ne 0) {
        Write-Host "GitHub CLI authorization failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "Authorization successful" -ForegroundColor Green
} else {
    Write-Host "GitHub CLI already authorized" -ForegroundColor Green
}

Write-Host ""

# Get repository information
Write-Host "Getting repository information..." -ForegroundColor Cyan
try {
    $repoOwner = gh repo view --json owner -q .owner.login
    $repoName = gh repo view --json name -q .name
    
    if ([string]::IsNullOrWhiteSpace($repoOwner) -or [string]::IsNullOrWhiteSpace($repoName)) {
        Write-Host "Failed to determine repository" -ForegroundColor Red
        Write-Host "Make sure you are in repository directory" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "Repository: $repoOwner/$repoName" -ForegroundColor Green
} catch {
    Write-Host "Error getting repository info: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Get SSH key from server
Write-Host "Getting SSH key from server..." -ForegroundColor Cyan
try {
    $sshKey = ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" 2>&1
    
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sshKey)) {
        Write-Host "Failed to get SSH key from server" -ForegroundColor Red
        Write-Host "Check SSH connection to server" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "SSH key retrieved" -ForegroundColor Green
} catch {
    Write-Host "Error getting SSH key: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Add secrets
Write-Host "Adding secrets to GitHub..." -ForegroundColor Cyan
Write-Host ""

$secrets = @{
    "TEST_SERVER_HOST" = "88.210.35.183"
    "TEST_SERVER_USER" = "root"
    "TEST_SERVER_SSH_KEY" = $sshKey
}

$successCount = 0
foreach ($secretName in $secrets.Keys) {
    Write-Host "Adding '$secretName'..." -ForegroundColor Cyan
    try {
        gh secret set $secretName --body $secrets[$secretName] --repo "$repoOwner/$repoName" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   $secretName added" -ForegroundColor Green
            $successCount++
        } else {
            Write-Host "   Error adding $secretName" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "   Error adding $secretName : $_" -ForegroundColor Red
    }
}

Write-Host ""
if ($successCount -eq $secrets.Count) {
    Write-Host "Done! All $successCount secrets added to GitHub" -ForegroundColor Green
    Write-Host ""
    Write-Host "CI/CD is ready to use!" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "   1. Push to 'test' branch for test deployment" -ForegroundColor White
    Write-Host "   2. Check status in GitHub Actions" -ForegroundColor White
    Write-Host ""
    Write-Host "   git checkout test" -ForegroundColor Gray
    Write-Host "   git add ." -ForegroundColor Gray
    Write-Host "   git commit -m 'Test CI/CD'" -ForegroundColor Gray
    Write-Host "   git push origin test" -ForegroundColor Gray
} else {
    Write-Host "Warning: Added $successCount of $($secrets.Count) secrets" -ForegroundColor Yellow
    Write-Host "   Check errors above" -ForegroundColor Yellow
}
