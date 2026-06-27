@echo off
chcp 65001 >nul 2>&1
title Quick Fix: Nginx + NetSec Restart
cd /d "%~dp0"

echo.
echo ========================================================
echo    Quick Fix: Upload Fixed Nginx Config + Restart
echo ========================================================
echo.

set SERVER=root@122.51.97.86

echo [1/3] Uploading fixed Nginx config (removed more_clear_headers)...
scp deploy\nginx\conf\ai_assistant.conf %SERVER%:/etc/nginx/conf.d/ai_assistant.conf
if %errorlevel% neq 0 (
    scp deploy\nginx\conf\ai_assistant.conf %SERVER%:/tmp/ai_assistant.conf
    ssh %SERVER% "mv /tmp/ai_assistant.conf /etc/nginx/conf.d/ai_assistant.conf"
)
echo   [OK] Config uploaded

echo.
echo [2/3] Testing Nginx config...
ssh %SERVER% "nginx -t"
if %errorlevel% neq 0 (
    echo [FAIL] Nginx config error!
    pause
    exit /b 1
)
echo   [OK] Config valid

echo.
echo [3/3] Restarting Nginx + NetSec...
ssh %SERVER% "systemctl restart nginx && echo '  nginx: OK' || echo '  nginx: FAIL'; systemctl restart netsec_assistant 2>&1 && echo '  netsec: OK' || echo '  netsec: not active'"
echo.
echo ========================================================
echo   Verify: http://122.51.97.86/netsec/scan/security-scan
echo ========================================================
pause
