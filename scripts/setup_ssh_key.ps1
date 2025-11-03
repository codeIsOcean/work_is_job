# Setup SSH key for vdsina.ru server
# Usage: .\scripts\setup_ssh_key.ps1 -ServerUser root -ServerHost your-server-ip

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerUser,
    
    [Parameter(Mandatory=$true)]
    [string]$ServerHost,
    
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_rsa.pub"
)

Write-Host "SSH Key Setup for vdsina.ru server" -ForegroundColor Cyan
Write-Host ""

# Check if key exists
if (-not (Test-Path $KeyPath)) {
    Write-Host "Error: SSH key not found at: $KeyPath" -ForegroundColor Red
    Write-Host "Create key with: ssh-keygen -t rsa -b 4096" -ForegroundColor Yellow
    exit 1
}

Write-Host "Found SSH key: $KeyPath" -ForegroundColor Green

# Read public key
$publicKey = Get-Content $KeyPath -Raw
$publicKey = $publicKey.Trim()

Write-Host ""
Write-Host "Public key:" -ForegroundColor Cyan
Write-Host $publicKey
Write-Host ""

# Server address
$serverAddress = "$ServerUser@$ServerHost"
Write-Host "Copying key to server: $serverAddress" -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: You will need to enter root password once" -ForegroundColor Yellow
Write-Host ""

try {
    # Create temporary file with key
    $tempKeyFile = "$env:TEMP\ssh_key_temp.pub"
    $publicKey | Out-File -FilePath $tempKeyFile -Encoding utf8 -NoNewline
    
    # Create remote commands
    $commands = @(
        "mkdir -p ~/.ssh",
        "chmod 700 ~/.ssh",
        "echo '$publicKey' >> ~/.ssh/authorized_keys",
        "chmod 600 ~/.ssh/authorized_keys",
        "echo 'Key added successfully'"
    )
    
    Write-Host "Connecting to server..." -ForegroundColor Cyan
    Write-Host "(Enter root password when prompted)" -ForegroundColor Yellow
    Write-Host ""
    
    # Execute commands on server
    $commandString = $commands -join " && "
    ssh $serverAddress $commandString
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "SSH key successfully added to server!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Testing connection without password..." -ForegroundColor Cyan
        
        # Test connection
        $testResult = ssh -o BatchMode=yes -o ConnectTimeout=5 $serverAddress "echo 'Connection test successful'" 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Connection without password works!" -ForegroundColor Green
            Write-Host ""
            Write-Host "Setup completed successfully!" -ForegroundColor Green
            Write-Host ""
            Write-Host "You can now connect with:" -ForegroundColor Cyan
            Write-Host "  ssh $serverAddress" -ForegroundColor Yellow
        } else {
            Write-Host "Key added, but automatic connection may not work" -ForegroundColor Yellow
            Write-Host "Try connecting manually: ssh $serverAddress" -ForegroundColor Yellow
        }
    } else {
        Write-Host ""
        Write-Host "Error adding key" -ForegroundColor Red
        Write-Host ""
        Write-Host "Manual setup:" -ForegroundColor Yellow
        Write-Host "1. Connect to server: ssh $serverAddress" -ForegroundColor Cyan
        Write-Host "2. Run commands:" -ForegroundColor Cyan
        Write-Host "   mkdir -p ~/.ssh" -ForegroundColor White
        Write-Host "   chmod 700 ~/.ssh" -ForegroundColor White
        Write-Host "   nano ~/.ssh/authorized_keys" -ForegroundColor White
        Write-Host "3. Paste this line:" -ForegroundColor Cyan
        Write-Host $publicKey -ForegroundColor White
        Write-Host "4. Save file (Ctrl+X, Y, Enter)" -ForegroundColor Cyan
        Write-Host "5. Run: chmod 600 ~/.ssh/authorized_keys" -ForegroundColor White
    }
    
    # Clean up
    if (Test-Path $tempKeyFile) {
        Remove-Item $tempKeyFile -Force
    }
    
} catch {
    Write-Host ""
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Try manual setup (see instructions above)" -ForegroundColor Yellow
}

Write-Host ""
