# ═══════════════════════════════════════════════════════════════════════════
#  ECom AI Dashboard V3.0 — 一键部署脚本 (Windows PowerShell)
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   .\deploy.ps1 setup      # 首次运行：安装依赖 + 配置
#   .\deploy.ps1 start      # 启动全部服务
#   .\deploy.ps1 stop       # 停止全部服务
#   .\deploy.ps1 status     # 查看服务状态
#
# What it does:
#   1. Auto-detects Python / Node.js / Docker
#   2. Creates venv, installs pip + npm dependencies
#   3. Generates .env config if missing
#   4. Starts Docker infra (optional) + 4 A2A microservices + backend + frontend
#   5. Shows service status dashboard
# ═══════════════════════════════════════════════════════════════════════════

param(
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = $ScriptDir
$BackendDir = "$ProjectDir\backend"
$FrontendDir = "$ProjectDir\frontend"
$VenDir = "$ProjectDir\.venv"
$LogDir = "$ProjectDir\logs"
$PidDir = "$ProjectDir\.pids"

New-Item -ItemType Directory -Force -Path $LogDir, $PidDir | Out-Null

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-OK    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERR]   $args" -ForegroundColor Red }
function Write-Title { Write-Host "`n$args`n" -ForegroundColor Blue }

# ═══════════════════════════════════════════════════════════════════════════
# Environment Detection
# ═══════════════════════════════════════════════════════════════════════════

function Check-Prerequisites {
    Write-Title "Checking Prerequisites..."

    $global:PythonCmd = $null
    foreach ($cmd in @("python3", "python")) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver) {
                $global:PythonCmd = $cmd
                Write-OK "Python $ver ($cmd)"
                break
            }
        } catch {}
    }
    if (-not $global:PythonCmd) {
        Write-Err "Python 3.10+ not found. Install from https://python.org"
        exit 1
    }

    # Node.js
    try {
        $nodeVer = node -v
        Write-OK "Node.js $nodeVer"
        $global:HasNode = $true
    } catch {
        Write-Warn "Node.js not found — frontend won't start"
        $global:HasNode = $false
    }

    # Docker
    try {
        docker info 2>$null | Out-Null
        Write-OK "Docker available (PostgreSQL + Redis optional)"
        $global:HasDocker = $true
    } catch {
        Write-Warn "Docker not available — app runs with built-in DataGenerator"
        $global:HasDocker = $false
    }

    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════

function Invoke-Setup {
    Check-Prerequisites

    Write-Title "Setting up Python Virtual Environment..."
    if (-not (Test-Path $VenDir)) {
        & $PythonCmd -m venv $VenDir
        Write-OK "Virtual environment created: $VenDir"
    } else {
        Write-OK "Virtual environment already exists"
    }

    # Activate
    $activateScript = "$VenDir\Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        . $activateScript
    }

    Write-Title "Installing Python Dependencies..."
    Set-Location $BackendDir
    pip install --upgrade pip -q

    $deps = @("fastapi", "uvicorn", "pydantic-settings", "loguru", "openai",
              "httpx", "sse-starlette", "pyyaml", "sqlalchemy")
    foreach ($dep in $deps) {
        pip install $dep -q 2>$null
    }

    # Optional deps
    pip install redis -q 2>$null
    if ($?) { Write-OK "redis-py installed" } else { Write-Warn "redis-py skipped (Redis optional)" }

    pip install asyncpg -q 2>$null
    if ($?) { Write-OK "asyncpg installed" } else { Write-Warn "asyncpg skipped (PG optional)" }

    Write-OK "Python dependencies installed"

    # Generate .env
    $envFile = "$BackendDir\.env"
    if (-not (Test-Path $envFile)) {
        Write-Title "Generating default .env configuration..."
        @"
# ECom AI Dashboard V3.0 Configuration
DEBUG=true
APP_NAME=ECom AI Dashboard
APP_VERSION=3.0.0
DATABASE_URL=postgresql+asyncpg://ecom:ecom2024@localhost:5432/ecom_dashboard
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-key-$(Get-Date -Format 'yyyyMMddHHmmss')
DATA_SOURCE=auto
QWEN_API_KEY=
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MCP_SERVER_ENABLED=true
A2A_ENABLED=true
A2A_TIMEOUT=3.0
DATA_AGENT_URL=http://localhost:8010
ANALYZE_AGENT_URL=http://localhost:8011
SENTIMENT_AGENT_URL=http://localhost:8012
REPORT_AGENT_URL=http://localhost:8013
GUARDRAILS_ENABLED=true
MAX_AUTO_BUDGET_ADJUST_PCT=20.0
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]
"@ | Out-File -FilePath $envFile -Encoding utf8
        Write-OK ".env created at $envFile"
    } else {
        Write-OK ".env already exists"
    }

    # Frontend
    if ($global:HasNode) {
        Write-Title "Installing Frontend Dependencies..."
        Set-Location $FrontendDir
        if (-not (Test-Path "node_modules")) {
            npm install --silent
            Write-OK "npm dependencies installed"
        } else {
            Write-OK "node_modules already exists"
        }
    }

    Set-Location $ProjectDir
    Write-Title "Setup Complete!"
    Write-Host "  Next step:  .\deploy.ps1 start"
    Write-Host "  Then open:  http://localhost:5173"
}

# ═══════════════════════════════════════════════════════════════════════════
# Start
# ═══════════════════════════════════════════════════════════════════════════

function Invoke-Start {
    Check-Prerequisites

    # Activate venv if exists
    $activateScript = "$VenDir\Scripts\Activate.ps1"
    if (Test-Path $activateScript) { . $activateScript }

    Write-Title "Starting ECom AI Dashboard V3.0..."

    # Docker (optional)
    if ($global:HasDocker) {
        Write-Info "Starting Docker infrastructure..."
        Set-Location $ProjectDir
        docker compose up -d postgres redis 2>$null
        Start-Sleep -Seconds 2
    }

    Set-Location $ProjectDir
    $env:PYTHONPATH = "$BackendDir;$env:PYTHONPATH"

    # ── A2A Microservices ─────────────────────────────────────────
    Write-Info "Starting A2A Agent microservices..."

    $agents = @(
        @{Name="data-agent";      Port=8010; Module="microservices.data-agent.main:app"},
        @{Name="analyze-agent";   Port=8011; Module="microservices.analyze-agent.main:app"},
        @{Name="sentiment-agent"; Port=8012; Module="microservices.sentiment-agent.main:app"},
        @{Name="report-agent";    Port=8013; Module="microservices.report-agent.main:app"}
    )

    foreach ($agent in $agents) {
        $logFile = "$LogDir\$($agent.Name).log"
        $pidFile = "$PidDir\$($agent.Name).pid"

        $proc = Start-Process -FilePath "uvicorn" `
            -ArgumentList $agent.Module, "--host", "0.0.0.0", "--port", $agent.Port `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput $logFile -RedirectStandardError $logFile

        $proc.Id | Out-File -FilePath $pidFile
        Write-OK "$($agent.Name) starting on port $($agent.Port)"
        Start-Sleep -Seconds 1
    }

    Start-Sleep -Seconds 2
    Write-OK "Microservices started on ports 8010-8013"

    # ── Main Backend ──────────────────────────────────────────────
    Write-Info "Starting main backend..."
    Set-Location $BackendDir
    $proc = Start-Process -FilePath "uvicorn" `
        -ArgumentList "app.main:app", "--host", "0.0.0.0", "--port", "8001" `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput "$LogDir\backend.log" -RedirectStandardError "$LogDir\backend.log"
    $proc.Id | Out-File -FilePath "$PidDir\backend.pid"
    Start-Sleep -Seconds 3
    Write-OK "Backend starting on port 8001"

    # ── Frontend ──────────────────────────────────────────────────
    if ($global:HasNode) {
        Write-Info "Starting frontend..."
        Set-Location $FrontendDir
        $proc = Start-Process -FilePath "npm" `
            -ArgumentList "run", "dev" `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput "$LogDir\frontend.log" -RedirectStandardError "$LogDir\frontend.log"
        $proc.Id | Out-File -FilePath "$PidDir\frontend.pid"
        Start-Sleep -Seconds 2
        Write-OK "Frontend starting on port 5173"
    }

    Start-Sleep -Seconds 3
    Invoke-Status

    Write-Host ""
    Write-Host "  Frontend :  http://localhost:5173" -ForegroundColor Green
    Write-Host "  Backend  :  http://localhost:8001" -ForegroundColor Green
    Write-Host "  API Docs :  http://localhost:8001/docs" -ForegroundColor Green
    Write-Host "  Insights :  http://localhost:5173/insights" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Stop:      .\deploy.ps1 stop" -ForegroundColor Yellow
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════════════
# Stop
# ═══════════════════════════════════════════════════════════════════════════

function Invoke-Stop {
    Write-Title "Stopping all services..."

    $names = @("frontend", "backend", "data-agent", "analyze-agent", "sentiment-agent", "report-agent")
    foreach ($name in $names) {
        $pidFile = "$PidDir\$name.pid"
        if (Test-Path $pidFile) {
            $pid = Get-Content $pidFile
            try {
                Stop-Process -Id $pid -Force -ErrorAction Stop
                Write-OK "Stopped $name (PID $pid)"
            } catch {
                Write-Warn "$name not running"
            }
            Remove-Item $pidFile -Force
        }
    }

    # Force kill any remaining uvicorn
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Stop-Process -Force 2>$null
    Write-OK "All services stopped"
}

# ═══════════════════════════════════════════════════════════════════════════
# Status
# ═══════════════════════════════════════════════════════════════════════════

function Invoke-Status {
    Write-Title "Service Status"

    function Test-Port {
        param($Port, $Name)
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$Port/health" `
                -TimeoutSec 2 -UseBasicParsing 2>$null
            if ($response.StatusCode -eq 200) {
                $body = ($response.Content | ConvertFrom-Json)
                Write-Host "  [OK]  $Name (:$Port) — $($body.status) $($body.agent)" -ForegroundColor Green
            }
        } catch {
            Write-Host "  [OFF] $Name (:$Port) — not running" -ForegroundColor Red
        }
    }

    Test-Port 8001 "Backend       "
    Test-Port 8010 "DataAgent     "
    Test-Port 8011 "AnalyzeAgent  "
    Test-Port 8012 "SentimentAgent"
    Test-Port 8013 "ReportAgent   "

    try {
        Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 2 -UseBasicParsing 2>$null | Out-Null
        Write-Host "  [OK]  Frontend      (:5173) — Vue 3 Dev Server" -ForegroundColor Green
    } catch {
        Write-Host "  [OFF] Frontend      (:5173) — not running" -ForegroundColor Yellow
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# Dispatch
# ═══════════════════════════════════════════════════════════════════════════

switch ($Action) {
    "setup"    { Invoke-Setup }
    "start"    { Invoke-Start }
    "stop"     { Invoke-Stop }
    "status"   { Invoke-Status }
    "restart"  { Invoke-Stop; Start-Sleep 2; Invoke-Start }
    default {
        Write-Host @"

ECom AI Dashboard V3.0 — Deployment Script

Usage: .\deploy.ps1 {setup|start|stop|restart|status}

  setup    — First run: install dependencies + create .env
  start    — Start all services (microservices + backend + frontend)
  stop     — Stop all services
  restart  — Stop then start
  status   — Show service health dashboard

After starting, open: http://localhost:5173

"@
    }
}
