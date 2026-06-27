@echo off
chcp 65001 >nul 2>&1
title ClawBot

echo ============================================
echo   WeChat ClawBot - AI Assistant
echo ============================================
echo.
echo   Step 1: Make sure ClawBot plugin is ON
echo   Step 2: Scan the QR code with WeChat
echo   Step 3: Send message in WeChat, AI auto-reply
echo ============================================
echo.

set CLAWBOT_ENABLED=true
set BRAIN_API=http://122.51.97.86/brain/api/chat
set PYTHONUNBUFFERED=1
set NO_PROXY=*

python -c "print('[ClawBot] Starting...')"
python clawbot.py --login
if %errorlevel% neq 0 (
    echo.
    echo Login failed. Check:
    echo 1. ClawBot plugin is ON in WeChat
    echo 2. Network is working
    echo 3. QR code was scanned and confirmed
    pause
    exit /b 1
)

echo.
echo Login OK. Running in background...
echo Press Ctrl+C to stop
echo.

python clawbot.py
pause
