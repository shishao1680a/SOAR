param (
    [Parameter(Mandatory=$false)]
    [ValidateSet("staging", "production")]
    [string]$Env = "staging"
)

# Railway Multi-Environment Deployment Script (Align with 第一金人壽 BR)

Write-Host "--- Starting Railway Deployment ($Env) ---" -ForegroundColor Cyan

# 1. Check if railway.exe exists
if (-not (Test-Path ".\railway.exe") -and -not (Get-Command "railway" -ErrorAction SilentlyContinue)) {
    Write-Host "Notice: railway CLI not found locally. You can also deploy via GitHub Push (main -> Production, staging -> Staging)." -ForegroundColor Yellow
}

# 2. Execution via Railway CLI
if (Test-Path ".\railway.exe") {
    Write-Host "[1/2] Uploading and deploying to Railway environment: $Env..." -ForegroundColor Yellow
    .\railway.exe up -e $Env
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[2/2] Deployment request sent successfully to $Env!" -ForegroundColor Green
    }
} else {
    Write-Host "Git Push Trigger: Push your commit to branch '$Env' or 'main' to trigger GitHub Railway CI/CD." -ForegroundColor Green
}
