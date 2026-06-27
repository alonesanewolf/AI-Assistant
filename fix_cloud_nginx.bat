@echo off
chcp 65001 >nul 2>&1
title Fix Cloud Server Nginx & Brain
cd /d "%~dp0"

echo.
echo ========================================================
echo    Cloud Server: Full Diagnostic & Fix
echo    Server: 122.51.97.86
echo ========================================================
echo.

set SERVER=root@122.51.97.86
set UPLOAD_OK=0

echo [1/8] Checking server connection...
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no %SERVER% "echo [OK] Connected && uname -a" 2>&1 >nul
if %errorlevel% neq 0 (
    echo [FAIL] Cannot connect to %SERVER%
    echo        Check: network, firewall, SSH key
    pause
    exit /b 1
)
echo   [OK] Connected successfully

echo.
echo [2/8] Server system info...
ssh %SERVER% "echo    OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d'\"' -f2 || echo unknown); echo    Disk: $(df -h / | tail -1 | awk '{print $5 \" used of \" $2}'); echo    Memory: $(free -h | awk '/^Mem:/{print $3 \"/\" $2}'); echo    Uptime: $(uptime -p)"
echo.

echo [3/8] Uploading Nginx config...
scp -q deploy\nginx\conf\ai_assistant.conf %SERVER%:/etc/nginx/conf.d/ai_assistant.conf 2>&1
if %errorlevel% neq 0 (
    echo [!] Direct SCP failed, trying tmp upload...
    scp -q deploy\nginx\conf\ai_assistant.conf %SERVER%:/tmp/ai_assistant.conf 2>&1
    if %errorlevel% neq 0 (
        echo [FAIL] Cannot upload config file
        goto skip_nginx
    )
    ssh %SERVER% "sudo mv /tmp/ai_assistant.conf /etc/nginx/conf.d/ai_assistant.conf"
)
echo   [OK] Nginx config uploaded

echo.
echo [4/8] Fixing Brain upstream port (5000-^>5200)...
ssh %SERVER% "sed -i 's/server 127.0.0.1:5000/server 127.0.0.1:5200/' /etc/nginx/conf.d/ai_assistant.conf"
echo   [OK] Brain port updated

:skip_nginx

echo.
echo [5/8] Checking project files on server...
ssh %SERVER% "echo '  local_assistant.py:' $(test -f /opt/ai_assistant/local_assistant.py && echo 'EXISTS' || echo 'MISSING'); echo '  brain.py:' $(test -f /opt/ai_assistant/brain.py && echo 'EXISTS' || echo 'MISSING'); echo '  NetSec:' $(test -d /opt/ai_assistant/netsec && echo 'EXISTS' || echo 'MISSING'); echo '  .env:' $(test -f /opt/ai_assistant/.env && echo 'EXISTS' || echo 'MISSING')"
echo.

echo [6/8] Testing Nginx config...
ssh %SERVER% "nginx -t 2>&1"
if %errorlevel% neq 0 (
    echo [FAIL] Nginx config error - need manual fix
) else (
    echo   [OK] Nginx config valid
)

echo.
echo [7/8] Restarting services...
ssh %SERVER% "systemctl restart nginx 2>&1; echo '  nginx: '$(systemctl is-active nginx); systemctl restart ai_assistant 2>&1 || true; echo '  ai_assistant: '$(systemctl is-active ai_assistant 2>&1 || echo 'not found'); systemctl restart ai_brain 2>&1 || true; echo '  ai_brain: '$(systemctl is-active ai_brain 2>&1 || echo 'not found'); systemctl restart netsec_assistant 2>&1 || true; echo '  netsec_assistant: '$(systemctl is-active netsec_assistant 2>&1 || echo 'not found')"
echo.

echo [8/8] Port listening check...
ssh %SERVER% "echo '  Port 80 (Nginx):' && ss -tlnp | grep ':80 ' | head -1 || echo '    NOT LISTENING'; echo '  Port 5100 (NetSec):' && ss -tlnp | grep ':5100 ' | head -1 || echo '    NOT LISTENING'; echo '  Port 5200 (Brain):' && ss -tlnp | grep ':5200 ' | head -1 || echo '    NOT LISTENING'; echo '  Port 8080 (AI Assist):' && ss -tlnp | grep ':8080 ' | head -1 || echo '    NOT LISTENING'"
echo.

echo [EXTRA] HTTP health check...
ssh %SERVER% "echo '  /health:' && curl -s -o /dev/null -w 'HTTP %%{http_code}' --connect-timeout 3 http://127.0.0.1/health 2>&1 || echo '  UNREACHABLE'; echo ''; echo '  /netsec/:' && curl -s -o /dev/null -w 'HTTP %%{http_code}' --connect-timeout 3 http://127.0.0.1/netsec/ 2>&1 || echo '  UNREACHABLE'; echo ''"

echo.
echo ========================================================
echo   [DONE] Verify these URLs in browser:
echo     http://122.51.97.86/
echo     http://122.51.97.86/netsec/
echo     http://122.51.97.86/health
echo ========================================================
echo.
echo   Run validate.sh on server for full diagnostics:
echo   ssh %SERVER% "cd /opt/ai_assistant/deploy/scripts && bash validate.sh"
echo.
pause
