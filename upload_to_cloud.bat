@echo off
chcp 65001 >nul 2>&1
title Upload All to Cloud Server
cd /d "%~dp0"

echo.
echo ========================================================
echo    Upload All Files to Cloud Server
echo    Server: 122.51.97.86
echo ========================================================
echo.

set SERVER=root@122.51.97.86
set REMOTE_DIR=/opt/ai_assistant

echo [1/10] Checking server connection...
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no %SERVER% "echo [OK] Connected" 2>&1 >nul
if %errorlevel% neq 0 (
    echo [FAIL] Cannot connect to %SERVER%
    pause
    exit /b 1
)
echo   [OK] Connected

echo.
echo [2/10] Creating remote directories...
ssh %SERVER% "mkdir -p %REMOTE_DIR%/deploy/netsec/templates %REMOTE_DIR%/deploy/netsec/templates/vulnerabilities %REMOTE_DIR%/deploy/scripts %REMOTE_DIR%/deploy/nginx/conf %REMOTE_DIR%/deploy/nginx/html"
echo   [OK] Directories ready

echo.
echo [3/10] Uploading HTML templates (to both possible paths)...
REM 同时上传到两个可能的 NetSec 目录
scp -q deploy\netsec\templates\*.html %SERVER%:%REMOTE_DIR%/deploy/netsec/templates/ 2>&1 >nul && echo   [OK] deploy/netsec/templates/ || (for %%f in (deploy\netsec\templates\*.html) do scp -q "%%f" %SERVER%:%REMOTE_DIR%/deploy/netsec/templates/ 2>&1 >nul)
scp -q deploy\netsec\templates\*.html %SERVER%:%REMOTE_DIR%/netsec/templates/ 2>&1 >nul && echo   [OK] netsec/templates/ || (for %%f in (deploy\netsec\templates\*.html) do scp -q "%%f" %SERVER%:%REMOTE_DIR%/netsec/templates/ 2>&1 >nul)

echo.
echo [4/10] Uploading vulnerability sub-templates...
scp -q deploy\netsec\templates\vulnerabilities\*.html %SERVER%:%REMOTE_DIR%/deploy/netsec/templates/vulnerabilities/ 2>&1 >nul
scp -q deploy\netsec\templates\vulnerabilities\*.html %SERVER%:%REMOTE_DIR%/netsec/templates/vulnerabilities/ 2>&1 >nul
echo   [OK] Done

echo.
echo [5/10] Uploading NetSec Python files (to both paths)...
for %%f in (run.py security_scan_levels.py NetSecAssistant.py network_scan.py) do (
    scp -q deploy\netsec\%%f %SERVER%:%REMOTE_DIR%/deploy/netsec/ 2>&1 >nul && echo   [OK] deploy/netsec/%%f || echo   [--] deploy/netsec/%%f
    scp -q deploy\netsec\%%f %SERVER%:%REMOTE_DIR%/netsec/ 2>&1 >nul && echo   [OK] netsec/%%f || echo   [--] netsec/%%f
)

echo.
echo [6/10] Uploading root Python files (modified)...
for %%f in (actions.py agent_client.py assistant.py brain.py config.py local_assistant.py memory.py model_router.py qq_bot.py qq_wechat_hub.py scheduler.py search.py wechat_assistant.py) do (
    scp -q "%%f" %SERVER%:%REMOTE_DIR%/ 2>&1 >nul && echo   [OK] %%f || echo   [FAIL] %%f
)

echo.
echo [7/10] Uploading new files (audit, backup)...
scp -q audit.py %SERVER%:%REMOTE_DIR%/ 2>&1 >nul && echo   [OK] audit.py || echo   [FAIL] audit.py
scp -q backup_config.py %SERVER%:%REMOTE_DIR%/ 2>&1 >nul && echo   [OK] backup_config.py || echo   [FAIL] backup_config.py

echo.
echo [8/10] Uploading deploy scripts...
scp -q deploy\scripts\deploy.sh %SERVER%:%REMOTE_DIR%/deploy/scripts/ 2>&1 && echo   [OK] deploy.sh || echo   [FAIL] deploy.sh
scp -q deploy\scripts\manage.sh %SERVER%:%REMOTE_DIR%/deploy/scripts/ 2>&1 && echo   [OK] manage.sh || echo   [FAIL] manage.sh
scp -q deploy\scripts\validate.sh %SERVER%:%REMOTE_DIR%/deploy/scripts/ 2>&1 && echo   [OK] validate.sh || echo   [FAIL] validate.sh
scp -q deploy\nginx\conf\ai_assistant.conf %SERVER%:%REMOTE_DIR%/deploy/nginx/conf/ 2>&1 && echo   [OK] ai_assistant.conf || echo   [FAIL] ai_assistant.conf
scp -q deploy\nginx\html\index.html %SERVER%:%REMOTE_DIR%/deploy/nginx/html/ 2>&1 && echo   [OK] nginx index.html || echo   [FAIL] nginx index.html

echo.
echo [9/10] Copying Nginx config to /etc/nginx/conf.d/...
ssh %SERVER% "cp %REMOTE_DIR%/deploy/nginx/conf/ai_assistant.conf /etc/nginx/conf.d/ai_assistant.conf && echo '  [OK] Nginx config copied' || echo '  [FAIL] Copy failed'"

echo.
echo [10/10] Restarting services...
ssh %SERVER% "nginx -t 2>&1 && echo '  [OK] Nginx config valid'; systemctl restart nginx 2>&1; systemctl restart netsec_assistant 2>&1 || true; systemctl restart ai_assistant 2>&1 || true"
echo   [OK] Services restarted

echo.
echo ========================================================
echo   [DONE] Upload complete!
echo ========================================================
echo.
echo   Verify in browser:
echo     http://122.51.97.86/netsec/
echo     http://122.51.97.86/netsec/scan/security-scan
echo     http://122.51.97.86/health
echo.
pause
