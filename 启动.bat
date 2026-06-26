@echo off
chcp 65001 >nul
title ECom AI Dashboard Launcher
cd /d "%~dp0"
set "ROOT=%cd%"

echo.
echo ===============================================
echo   ECom AI Dashboard V3.0
echo ===============================================
echo.

:: ── Check Python ───────────────────────────────────────────────
set "PYTHON="
python --version >nul 2>&1 && set "PYTHON=python"
if "%PYTHON%"=="" (
    python3 --version >nul 2>&1 && set "PYTHON=python3"
)
if "%PYTHON%"=="" (
    echo [FAIL] Python not found. Install from https://python.org
    pause
    exit /b
)
echo [OK] Python found

:: ── Check Node ─────────────────────────────────────────────────
set HAS_NODE=0
node --version >nul 2>&1 && set HAS_NODE=1
if %HAS_NODE%==1 (echo [OK] Node.js found) else (echo [WARN] Node.js not found, no frontend)

:: ── Check .env ─────────────────────────────────────────────────
if not exist "backend\.env" (
    echo.
    echo [WARN] backend\.env not found!
    echo        Copy backend\.env.example to backend\.env:
    echo        copy backend\.env.example backend\.env
    echo        Then edit it to add your API key ^(optional^)
    echo.
    echo        The app will use defaults for now...
    echo.
)

:: ── Stop old services ──────────────────────────────────────────
echo.
echo [STOP] Killing old processes...
taskkill /f /im python.exe /fi "WINDOWTITLE eq DataAgent*" 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Backend*" 2>nul
taskkill /f /im node.exe   /fi "WINDOWTITLE eq Frontend*" 2>nul
timeout /t 2 /nobreak >nul

:: ── Install Python deps ─────────────────────────────────────────
echo.
echo [DEPS] Checking Python packages...
cd backend
%PYTHON% -c "import fastapi,uvicorn,httpx" 2>nul
if %errorlevel% neq 0 (
    echo [DEPS] Installing (first time, ~30s)...
    %PYTHON% -m pip install fastapi uvicorn pydantic-settings loguru openai httpx sse-starlette pyyaml sqlalchemy -q
)
echo [DEPS] Python ready
cd ..

:: ── Install Node deps ───────────────────────────────────────────
if %HAS_NODE%==1 (
    cd frontend
    if not exist "node_modules" (
        echo [DEPS] Installing npm packages (first time, ~2min)...
        call npm install
    )
    echo [DEPS] Frontend ready
    cd ..
)

:: ── Start services ──────────────────────────────────────────────
echo.
echo [START] Launching 6 services...
set "PYTHONPATH=%ROOT%\backend"

start "DataAgent"      cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.data-agent.main:app --host 0.0.0.0 --port 8010   > nul 2>&1"
start "AnalyzeAgent"   cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.analyze-agent.main:app --host 0.0.0.0 --port 8011  > nul 2>&1"
start "SentimentAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.sentiment-agent.main:app --host 0.0.0.0 --port 8012 > nul 2>&1"
start "ReportAgent"    cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && %PYTHON% -m uvicorn microservices.report-agent.main:app --host 0.0.0.0 --port 8013 > nul 2>&1"

timeout /t 2 /nobreak >nul

start "Backend" cmd /c "cd /d %ROOT%\backend && %PYTHON% -m uvicorn app.main:app --host 0.0.0.0 --port 8001"

timeout /t 3 /nobreak >nul

if %HAS_NODE%==1 (
    start "Frontend" cmd /c "cd /d %ROOT%\frontend && npm run dev"
)

:: ── Wait for backend ────────────────────────────────────────────
echo.
set TRIES=0
:loop
timeout /t 1 /nobreak >nul
set /a TRIES+=1
curl -s http://localhost:8001/health >nul 2>&1
if %errorlevel% equ 0 goto ready
if %TRIES% lss 30 (
    echo [WAIT] Waiting for backend... %TRIES%s
    goto loop
)
echo [WARN] Backend not responding after 30s
goto done

:ready
echo [OK] Backend is online!
echo.

:done
echo ===============================================
echo   Frontend : http://localhost:5173
echo   Backend  : http://localhost:8001
echo ===============================================
echo.
echo   Keep this window open. Press any key to open browser.
pause >nul
start http://localhost:5173
echo.
echo   Press any key to stop all services and exit.
pause >nul
taskkill /f /fi "WINDOWTITLE eq DataAgent*" 2>nul
taskkill /f /fi "WINDOWTITLE eq AnalyzeAgent*" 2>nul
taskkill /f /fi "WINDOWTITLE eq SentimentAgent*" 2>nul
taskkill /f /fi "WINDOWTITLE eq ReportAgent*" 2>nul
taskkill /f /fi "WINDOWTITLE eq Backend*" 2>nul
taskkill /f /fi "WINDOWTITLE eq Frontend*" 2>nul
echo Bye.
