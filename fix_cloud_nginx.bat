@echo off
chcp 65001 >nul 2>&1
title Fix Cloud Server Nginx & Brain
cd /d "%~dp0"

echo.
echo ========================================================
echo    Fix Cloud Server: Nginx + Brain + NetSec
echo    Server: 122.51.97.86
echo ========================================================
echo.

set SERVER=root@122.51.97.86

echo [1/4] Checking server connection...
ssh -o ConnectTimeout=5 %SERVER% "echo [OK] Connected" 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Cannot connect to %SERVER%
    echo        Check network or add SSH key
    pause
    exit /b 1
)

echo.
echo [2/4] Uploading Nginx config (ai_assistant.conf)...
scp deploy\nginx\conf\ai_assistant.conf %SERVER%:/etc/nginx/conf.d/ai_assistant.conf
if %errorlevel% neq 0 (
    echo [!] SCP failed, trying alternate path...
    scp deploy\nginx\conf\ai_assistant.conf %SERVER%:/tmp/ai_assistant.conf
    ssh %SERVER% "sudo cp /tmp/ai_assistant.conf /etc/nginx/conf.d/"
)
echo   [OK] Config uploaded

echo.
echo [3/4] Fixing Brain upstream port (5000-^>5200)...
ssh %SERVER% "sed -i 's/server 127.0.0.1:5000/server 127.0.0.1:5200/' /etc/nginx/conf.d/ai_assistant.conf"
echo   [OK] Brain port updated to 5200

echo.
echo [4/4] Testing Nginx config and restarting...
ssh %SERVER% "nginx -t 2>&1 && systemctl restart nginx && systemctl restart brain && echo [OK] Restarted"
echo.

echo ========================================================
echo   Checking services status...
echo ========================================================
echo.
ssh %SERVER% "systemctl is-active nginx brain netsec 2>&1; echo ---; ss -tlnp | grep -E '5200|5100|5000|80' | head -10"
echo.

echo ========================================================
echo   [DONE] Please test:
echo     http://122.51.97.86/netsec/
echo     http://122.51.97.86/brain/
echo ========================================================
pause
