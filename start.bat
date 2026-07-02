@echo off
chcp 65001 >nul 2>&1
title AI Assistant - Launcher Menu

cd /d "%~dp0"

echo ============================================
echo   AI Assistant - Launcher Menu
echo ============================================
echo.
echo   [1] Local Web Assistant (Recommended)
echo       http://localhost:8080
echo       Ollama + DeepSeek dual-model
echo       Connect to cloud Brain for remote control
echo.
echo   [2] CLI Assistant
echo       Chat with DeepSeek in terminal
echo       PC control, search, scheduled tasks
echo.
echo   [3] Agent Client
echo       Connect to cloud Brain, wait for commands
echo.
echo   [4] WeCom Bot Assistant
echo       WeCom group bot messaging
echo       AI chat + remote PC control
echo.
echo   [5] Cloud Brain Service (needs public server)
echo       Multi-channel: QQ/WeChat/Telegram
echo.
echo   [0] Exit
echo.
echo ============================================
set /p choice="Select [0-5]: "

if "%choice%"=="1" goto local
if "%choice%"=="2" goto cli
if "%choice%"=="3" goto agent
if "%choice%"=="4" goto wechat
if "%choice%"=="5" goto brain
if "%choice%"=="0" goto end

echo Invalid choice
pause
goto end

:local
echo.
echo Starting Local Web Assistant...
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    call "%~dp0load_env.bat"
    if "%ROUTER_MODE%"=="" set ROUTER_MODE=local_first
    if "%ENABLE_BRAIN_AGENT%"=="" set ENABLE_BRAIN_AGENT=true
    "%VENV_PYTHON%" local_assistant.py
) else (
    call "%~dp0load_env.bat"
    if "%ROUTER_MODE%"=="" set ROUTER_MODE=local_first
    if "%ENABLE_BRAIN_AGENT%"=="" set ENABLE_BRAIN_AGENT=true
    python local_assistant.py
)
pause
goto end

:cli
echo.
echo Starting CLI Assistant...
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" assistant.py
) else (
    python assistant.py
)
pause
goto end

:agent
echo.
echo Starting Agent Client...
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" agent_client.py
) else (
    python agent_client.py
)
pause
goto end

:wechat
echo.
echo Starting WeCom Bot...
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" wechat_assistant.py
) else (
    python wechat_assistant.py
)
pause
goto end

:brain
echo.
echo Starting Cloud Brain Service...
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
call "%~dp0load_env.bat"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" brain.py
) else (
    python brain.py
)
pause
goto end

:end
