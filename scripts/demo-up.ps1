<#
Starts the demo on this PC and opens it: http://localhost:5173

  - starts Docker Desktop if it is not running and waits for it;
  - stops other projects' containers listed in $StopOthers (stopped only,
    never deleted), so they do not compete for memory;
  - builds the web app if it changed since the last build;
  - starts the billing services in Docker (database, storage, Mailpit, API,
    worker, web) and brings the database up to date;
  - waits until the API and the web app answer, then opens the browser.

Everything runs in Docker with "restart: unless-stopped", so after a PC or
Docker restart it comes back by itself; scripts\demo-down.ps1 stops it.

  Double-click scripts\demo-up.cmd, or:
  powershell -ExecutionPolicy Bypass -File scripts\demo-up.ps1 [-Rebuild] [-NoBrowser]
#>
param(
    [switch]$Rebuild,   # build the web app even if nothing changed
    [switch]$NoBrowser  # do not open the browser at the end
)

$ErrorActionPreference = "Continue"  # native tools report through exit codes
$Root = Split-Path -Parent $PSScriptRoot
$StopOthers = @("_printpulse")  # container names containing these are stopped
$DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$Url = "http://localhost:5173"

function Step([string]$Text) { Write-Host "-> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { Write-Host "!! $Text" -ForegroundColor Red; exit 1 }

function Test-Docker {
    cmd /c "docker info >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

function Wait-Url([string]$Address, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Address -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

# 1. Docker Desktop
if (-not (Test-Docker)) {
    Step "Starting Docker Desktop"
    if (-not (Test-Path $DockerDesktop)) { Fail "Docker Desktop is not installed at $DockerDesktop" }
    Start-Process $DockerDesktop
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-Docker)) {
        if ((Get-Date) -gt $deadline) { Fail "Docker did not start within 4 minutes. Open Docker Desktop and try again." }
        Start-Sleep -Seconds 3
    }
}
Step "Docker is running"

# 2. Other projects' containers: stop them (they keep their data)
foreach ($name in $StopOthers) {
    $ids = docker ps -q --filter "name=$name"
    if ($ids) {
        Step "Stopping other project's containers ($name) to free memory"
        docker stop $ids | Out-Null
    }
}

# 3. The web app: build it when it changed (the web container serves web\dist)
$web = Join-Path $Root "web"
$built = Join-Path $web "dist\index.html"
$needBuild = $Rebuild -or -not (Test-Path $built)
if (-not $needBuild) {
    $builtAt = (Get-Item $built).LastWriteTime
    $sources = @(Get-ChildItem -Path (Join-Path $web "src") -Recurse -File) +
        @(Get-Item (Join-Path $web "index.html"), (Join-Path $web "package.json"), (Join-Path $web "vite.config.ts"))
    $needBuild = [bool]($sources | Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1)
}
if ($needBuild) {
    Step "Building the web app (about a minute)"
    Push-Location $web
    if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund }
    npm run build
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "The web app did not build (see above)." }
}

# 4. The billing services
Push-Location $Root
Step "Starting the billing services"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "The database and storage did not start (see above)." }
docker compose --profile app up -d --build api worker web
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "The API, worker or web app did not start (see above)." }

if (-not (Wait-Url "http://127.0.0.1:8000/healthz" 120)) { Pop-Location; Fail "The API did not answer. Logs: docker compose logs api" }
Step "Bringing the database up to date"
docker compose exec -T api python manage.py migrate --database=owner | Out-Null
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Database update failed. Logs: docker compose logs api" }
Pop-Location

if (-not (Wait-Url "http://127.0.0.1:5173/" 60)) { Fail "The web app did not answer. Logs: docker compose logs web" }

Write-Host ""
Write-Host "Demo ready:  $Url" -ForegroundColor Green
Write-Host "Emails:      http://127.0.0.1:8025 (Mailpit)"
Write-Host "Stop it:     scripts\demo-down.cmd"
if (-not $NoBrowser) { Start-Process $Url }
