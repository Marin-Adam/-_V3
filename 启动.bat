@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "ROOT=%cd%"

echo.
echo ═══════════════════════════════════════════════
echo   ECom AI Dashboard V3.0
echo ═══════════════════════════════════════════════
echo.

:: ── Step 1: Check Python ──────────────────────────────────────
set PYTHON=
for %%p in (python python3) do (
    where %%p >nul 2>&1
    if !errorlevel! equ 0 (
        %%p --version >nul 2>&1
        if !errorlevel! equ 0 set PYTHON=%%p
    )
)
if "%PYTHON%"=="" (
    echo [ERROR] Python 3.10+ not found!
    echo          Install from https://python.org
    echo          Make sure to check "Add Python to PATH" during install
    pause
    exit /b 1
)
%PYTHON% --version 2>&1 | findstr /V ""
echo [OK] Python ready

:: ── Step 2: Check Node.js ─────────────────────────────────────
set HAS_NODE=0
where node >nul 2>&1
if !errorlevel! equ 0 (
    node --version >nul 2>&1
    if !errorlevel! equ 0 set HAS_NODE=1
)
if "%HAS_NODE%"=="1" (
    echo [OK] Node.js ready
) else (
    echo [WARN] Node.js not found - frontend won't start
    echo        Install from https://nodejs.org
)

:: ── Step 3: Install Python dependencies ───────────────────────
echo.
echo [INFO] Checking Python dependencies...
cd backend

:: Quick check if deps are installed
%PYTHON% -c "import fastapi,uvicorn,httpx" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing Python packages (first time setup)...
    %PYTHON% -m pip install fastapi uvicorn pydantic-settings loguru openai httpx sse-starlette pyyaml sqlalchemy -q 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install Python dependencies
        pause
        exit /b 1
    )
    echo [OK] Python packages installed
) else (
    echo [OK] Python packages already installed
)
cd ..

:: ── Step 4: Install frontend dependencies ─────────────────────
if "%HAS_NODE%"=="1" (
    echo.
    echo [INFO] Checking frontend dependencies...
    cd frontend
    if not exist "node_modules" (
        echo [INFO] Installing npm packages (first time, may take 2-3 minutes)...
        call npm install
        if !errorlevel! neq 0 (
            echo [WARN] npm install failed, trying again...
            call npm install --legacy-peer-deps
        )
        echo [OK] npm packages installed
    ) else (
        echo [OK] node_modules already exists
    )
    cd ..
)

:: ── Step 5: Stop any running services ─────────────────────────
echo.
echo [INFO] Stopping old services...
for %%p in (DataAgent AnalyzeAgent SentimentAgent ReportAgent Backend Frontend) do (
    taskkill /FI "WINDOWTITLE eq %%p*" /F 2>nul
)
timeout /t 2 /nobreak >nul

:: ── Step 6: Start microservices ───────────────────────────────
echo.
echo [INFO] Starting services...
set "PYTHONPATH=%ROOT%\backend"

echo [1/6] DataAgent :8010
start "DataAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.data-agent.main:app --host 0.0.0.0 --port 8010"
timeout /t 2 /nobreak >nul

echo [2/6] AnalyzeAgent :8011
start "AnalyzeAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.analyze-agent.main:app --host 0.0.0.0 --port 8011"
timeout /t 2 /nobreak >nul

echo [3/6] SentimentAgent :8012
start "SentimentAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.sentiment-agent.main:app --host 0.0.0.0 --port 8012"
timeout /t 2 /nobreak >nul

echo [4/6] ReportAgent :8013
start "ReportAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.report-agent.main:app --host 0.0.0.0 --port 8013"
timeout /t 2 /nobreak >nul

echo [5/6] Backend :8001
cd backend
start "Backend" cmd /c "cd /d %ROOT%\backend && %PYTHON% -m uvicorn app.main:app --host 0.0.0.0 --port 8001"
cd ..
timeout /t 3 /nobreak >nul

if "%HAS_NODE%"=="1" (
    echo [6/6] Frontend :5173
    cd frontend
    start "Frontend" cmd /c "cd /d %ROOT%\frontend && npm run dev"
    cd ..
)

:: ── Step 7: Health check ──────────────────────────────────────
echo.
echo [INFO] Waiting for backend to be ready...
set TRIES=0
:check_loop
set /a TRIES=TRIES+1
timeout /t 1 /nobreak >nul

curl -s http://localhost:8001/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Backend is ready!
    goto done
)
if %TRIES% lss 25 (
    echo [WAIT] Still waiting... (%TRIES%s)
    goto check_loop
)
echo [WARN] Backend may not be ready, check the Backend window for errors

:done
echo.
echo ═══════════════════════════════════════════════
echo   ALL SERVICES STARTED
echo.
echo   Frontend : http://localhost:5173
echo   Backend  : http://localhost:8001
echo   API Docs : http://localhost:8001/docs
echo.
echo   Keep this window open while using the app.
echo   Press any key to open browser...
echo ═══════════════════════════════════════════════
pause >nul
start http://localhost:5173
pause
