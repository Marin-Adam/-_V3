@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ═══════════════════════════════════════════════
echo   ECom AI Dashboard V3.0
echo ═══════════════════════════════════════════════
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)
echo [OK] Python found

:: Check Node
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Node.js not found, frontend skipped
    set HAS_NODE=0
) else (
    echo [OK] Node.js found
    set HAS_NODE=1
)

echo.
echo [INFO] Installing dependencies...
cd backend
pip install fastapi uvicorn pydantic-settings loguru openai httpx sse-starlette pyyaml sqlalchemy -q 2>nul
cd ..

set "ROOT=%cd%"
set "PYTHONPATH=%ROOT%\backend"

echo.
echo [INFO] Starting services...
echo.

echo [1/6] DataAgent :8010
start "DataAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && uvicorn microservices.data-agent.main:app --host 0.0.0.0 --port 8010"
timeout /t 1 /nobreak >nul

echo [2/6] AnalyzeAgent :8011
start "AnalyzeAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && uvicorn microservices.analyze-agent.main:app --host 0.0.0.0 --port 8011"
timeout /t 1 /nobreak >nul

echo [3/6] SentimentAgent :8012
start "SentimentAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && uvicorn microservices.sentiment-agent.main:app --host 0.0.0.0 --port 8012"
timeout /t 1 /nobreak >nul

echo [4/6] ReportAgent :8013
start "ReportAgent" cmd /c "cd /d %ROOT% && set PYTHONPATH=%ROOT%\backend && uvicorn microservices.report-agent.main:app --host 0.0.0.0 --port 8013"
timeout /t 2 /nobreak >nul

echo [5/6] Backend :8001
start "Backend" cmd /c "cd /d %ROOT%\backend && uvicorn app.main:app --host 0.0.0.0 --port 8001"
timeout /t 3 /nobreak >nul

if "%HAS_NODE%"=="1" (
    echo [6/6] Frontend :5173
    cd frontend
    if not exist "node_modules" (
        echo [INFO] Installing npm packages...
        call npm install
    )
    start "Frontend" cmd /c "cd /d %ROOT%\frontend && npm run dev"
    cd ..
)

echo.
echo [INFO] Waiting for services to be ready...
echo.

:: Health check loop
set TRIES=0
:check_loop
set /a TRIES=%TRIES%+1
timeout /t 1 /nobreak >nul

curl -s http://localhost:8001/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Backend is ready!
    goto done
)

if %TRIES% lss 20 (
    echo [WAIT] Waiting... (%TRIES%s)
    goto check_loop
)

echo [WARN] Backend not ready after 20s, opening anyway...

:done
echo.
echo ═══════════════════════════════════════════════
echo   Frontend : http://localhost:5173
echo   Backend  : http://localhost:8001
echo   API Docs : http://localhost:8001/docs
echo ═══════════════════════════════════════════════
echo.
echo   Close this window to stop all services.
echo   (Minimize it to keep services running)
echo.
start http://localhost:5173
pause
