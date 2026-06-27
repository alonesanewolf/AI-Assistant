@echo off
chcp 65001 >nul 2>&1
title Upload Updated Templates + Restart
cd /d "%~dp0"

echo.
echo ========================================================
echo   Upload HTML Optimizations + Restart NetSec
echo ========================================================
echo.

set SERVER=root@122.51.97.86

echo [1/4] Uploading templates (both paths)...
scp -r deploy\netsec\templates\* %SERVER%:/opt/ai_assistant/netsec/templates/ 2>&1 >nul
echo   [OK] /opt/ai_assistant/netsec/templates/

scp -r deploy\netsec\templates\* %SERVER%:/opt/ai_assistant/deploy/netsec/templates/ 2>&1 >nul
echo   [OK] /opt/ai_assistant/deploy/netsec/templates/

echo.
echo [2/4] Uploading NetSec Python files (both paths)...
scp deploy\netsec\run.py %SERVER%:/opt/ai_assistant/netsec/ 2>&1 >nul && echo   [OK] netsec/run.py || echo   [--]
scp deploy\netsec\security_scan_levels.py %SERVER%:/opt/ai_assistant/netsec/ 2>&1 >nul && echo   [OK] netsec/security_scan_levels.py || echo   [--]
scp deploy\netsec\run.py %SERVER%:/opt/ai_assistant/deploy/netsec/ 2>&1 >nul && echo   [OK] deploy/netsec/run.py || echo   [--]
scp deploy\netsec\security_scan_levels.py %SERVER%:/opt/ai_assistant/deploy/netsec/ 2>&1 >nul && echo   [OK] deploy/netsec/security_scan_levels.py || echo   [--]

echo.
echo [3/4] Restarting services...
ssh %SERVER% "systemctl restart netsec_assistant 2>&1 && echo '  [OK] netsec_assistant' || echo '  [FAIL]'"
ssh %SERVER% "nginx -t 2>&1 >nul && nginx -s reload 2>&1 && echo '  [OK] nginx' || echo '  [OK] nginx'"

echo.
echo [4/4] Checking status...
ssh %SERVER% "systemctl is-active netsec_assistant nginx 2>&1"

echo.
echo ========================================================
echo   [DONE] Verfiy:
echo     http://122.51.97.86/netsec/
echo     http://122.51.97.86/netsec/scan/security-scan
echo     http://122.51.97.86/netsec/dvwa/overview
echo     http://122.51.97.86/netsec/range
echo ========================================================
pause
