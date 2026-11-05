<#
Stops the demo: every billing container stops (nothing is deleted; the data
stays for next time) and stays stopped until scripts\demo-up.ps1.

  Double-click scripts\demo-down.cmd, or:
  powershell -ExecutionPolicy Bypass -File scripts\demo-down.ps1 [-QuitDocker]

-QuitDocker also closes Docker Desktop, which hands all its memory back to
Windows (other projects' containers stop too).
#>
param([switch]$QuitDocker)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot

cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running: nothing to stop." -ForegroundColor Yellow
    exit 0
}

Push-Location $Root
Write-Host "-> Stopping the billing services" -ForegroundColor Cyan
docker compose --profile app --profile scan stop
Pop-Location

if ($QuitDocker) {
    Write-Host "-> Closing Docker Desktop" -ForegroundColor Cyan
    cmd /c "docker desktop stop >nul 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
    }
}
Write-Host "Stopped. Start again with scripts\demo-up.cmd" -ForegroundColor Green
