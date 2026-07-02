@echo off
chcp 65001 >nul 2>&1
title AI_Assistant - All-in-One Launcher

echo ============================================
echo   AI_Assistant All-in-One Launcher
echo ============================================
echo.

REM --- Go to project root ---
cd /d "%~dp0"

REM --- Set Python paths ---
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
set "VENV_PIP=%~dp0venv\Scripts\pip.exe"

REM --- Check venv Python ---
"%VENV_PYTHON%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Virtualenv Python not found at %VENV_PYTHON%
    echo Please run: python -m venv venv
    pause
    exit /b 1
)

REM --- Install dependencies ---
echo [1/3] Checking Python dependencies...
"%VENV_PIP%" install -r requirements.txt >nul 2>&1
echo       Dependencies OK

REM --- Create logs dir ---
if not exist "logs" mkdir logs

REM --- Start AI Assistant (:8080) ---
echo [2/3] Starting AI Assistant (port 8080)...
start "AI_Assistant" /MIN "%VENV_PYTHON%" local_assistant.py
echo       AI Assistant started

REM --- Start NetSec Assistant (:5100) ---
echo [3/3] Starting NetSec Assistant (port 5100)...
if exist "deploy\netsec\run.py" (
    cd deploy\netsec
    "%VENV_PIP%" install -r requirements.txt >nul 2>&1
    start "NetSec_Assistant" /MIN "%VENV_PYTHON%" run.py
    cd ..\..
    echo       NetSec Assistant started
) else (
    echo       [SKIP] deploy\netsec\run.py not found
)

echo.
echo ============================================
echo   All services started!
echo ============================================
echo.
echo   AI Assistant:    http://localhost:8080
echo   NetSec Platform: http://localhost:5100
echo.
echo   Press any key to close this window
echo   (services will keep running in background)
pause >nul
