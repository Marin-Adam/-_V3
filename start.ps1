# ═══════════════════════════════════════════════════════════════════════
# V3.0 Windows PowerShell 启动脚本
# ═══════════════════════════════════════════════════════════════════════
param(
    [string]$Action = "all"
)

$ProjectDir = $PSScriptRoot
$BackendDir = "$ProjectDir\backend"
$FrontendDir = "$ProjectDir\frontend"

function Start-Infra {
    Write-Host "[INFO] Starting Docker infrastructure..." -ForegroundColor Cyan
    docker compose up -d postgres redis
    Start-Sleep -Seconds 3
    Write-Host "[OK] Infrastructure ready (PostgreSQL:5432, Redis:6379)" -ForegroundColor Green
}

function Start-Backend {
    Write-Host "[INFO] Starting FastAPI backend on port 8001..." -ForegroundColor Cyan
    Set-Location $BackendDir
    if (-not (Test-Path ".env")) {
        @"
DEBUG=true
APP_NAME=ECom AI Dashboard
APP_VERSION=3.0.0
DATABASE_URL=postgresql+asyncpg://ecom:ecom2024@localhost:5432/ecom_dashboard
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-key-change
DATA_SOURCE=auto
MCP_SERVER_ENABLED=true
A2A_ENABLED=true
"@ | Out-File -FilePath .env -Encoding utf8
        Write-Host "[OK] .env created" -ForegroundColor Green
    }
    Start-Process -NoNewWindow -FilePath "uvicorn" -ArgumentList "app.main:app --host 0.0.0.0 --port 8001 --reload"
    Write-Host "[OK] Backend starting on http://localhost:8001" -ForegroundColor Green
    Write-Host "[INFO] API docs: http://localhost:8001/docs" -ForegroundColor Cyan
}

function Start-Frontend {
    Write-Host "[INFO] Starting Vue 3 frontend on port 5173..." -ForegroundColor Cyan
    Set-Location $FrontendDir
    if (-not (Test-Path "node_modules")) {
        Write-Host "[INFO] Installing npm dependencies..." -ForegroundColor Cyan
        npm install
    }
    Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run dev"
    Write-Host "[OK] Frontend starting on http://localhost:5173" -ForegroundColor Green
}

switch ($Action) {
    "backend" {
        Start-Infra
        Start-Backend
    }
    "frontend" { Start-Frontend }
    "all" {
        Start-Infra
        Start-Backend
        Start-Frontend
        Write-Host ""
        Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
        Write-Host "  V3.0 服务启动中..." -ForegroundColor Green
        Write-Host "  Frontend : http://localhost:5173" -ForegroundColor Cyan
        Write-Host "  Backend  : http://localhost:8001" -ForegroundColor Cyan
        Write-Host "  API Docs : http://localhost:8001/docs" -ForegroundColor Cyan
        Write-Host "  Insights : http://localhost:5173/insights" -ForegroundColor Cyan
        Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
    }
    default {
        Write-Host "Usage: .\start.ps1 [backend|frontend|all]"
    }
}
