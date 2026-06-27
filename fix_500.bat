@echo off
chcp 65001 >nul 2>&1
title Fix 500 Error - Correct Template Path
cd /d "%~dp0"

echo.
echo ========================================================
echo   诊断 500 错误并修复模板路径
echo ========================================================
echo.

set SERVER=root@122.51.97.86

echo [1] 查找 NetSec 实际运行目录...
ssh %SERVER% "echo '  ===== 候选位置 ====='; for d in /opt/ai_assistant/netsec /opt/ai_assistant/deploy/netsec /opt/AI_Assistant/netsec /opt/AI_Assistant/deploy/netsec; do if [ -f \"\$d/run.py\" ]; then echo \"  [找到] \$d/run.py\"; fi; done; echo ''; echo '  ===== 实际进程 ====='; ps aux | grep -E 'run.py|netsec' | grep -v grep"

echo.
echo [2] 上传到两个可能的位置（确保覆盖）...
scp -q deploy\netsec\templates\security_scan.html %SERVER%:/opt/ai_assistant/netsec/templates/ 2>&1 >nul && echo   [OK] /opt/ai_assistant/netsec/templates/ || echo   [--] Skipped
scp -q deploy\netsec\templates\security_scan.html %SERVER%:/opt/ai_assistant/deploy/netsec/templates/ 2>&1 >nul && echo   [OK] /opt/ai_assistant/deploy/netsec/templates/ || echo   [--] Skipped
scp -q deploy\netsec\templates\index.html %SERVER%:/opt/ai_assistant/netsec/templates/ 2>&1 >nul && echo   [OK] index.html:/opt/ai_assistant/netsec/ || echo   [--] Skipped
scp -q deploy\netsec\templates\index.html %SERVER%:/opt/ai_assistant/deploy/netsec/templates/ 2>&1 >nul && echo   [OK] index.html:/opt/ai_assistant/deploy/netsec/ || echo   [--] Skipped
scp -q deploy\netsec\security_scan_levels.py %SERVER%:/opt/ai_assistant/netsec/ 2>&1 >nul && echo   [OK] sec_levels:/opt/ai_assistant/netsec/ || echo   [--] Skipped
scp -q deploy\netsec\security_scan_levels.py %SERVER%:/opt/ai_assistant/deploy/netsec/ 2>&1 >nul && echo   [OK] sec_levels:/opt/ai_assistant/deploy/netsec/ || echo   [--] Skipped
scp -q deploy\netsec\run.py %SERVER%:/opt/ai_assistant/netsec/ 2>&1 >nul && echo   [OK] run.py:/opt/ai_assistant/netsec/ || echo   [--] Skipped
scp -q deploy\netsec\run.py %SERVER%:/opt/ai_assistant/deploy/netsec/ 2>&1 >nul && echo   [OK] run.py:/opt/ai_assistant/deploy/netsec/ || echo   [--] Skipped

echo.
echo [3] 重启 NetSec 服务...
ssh %SERVER% "systemctl restart netsec_assistant 2>&1 && echo '  [OK] netsec_assistant' || echo '  [FAIL] netsec_assistant'"

echo.
echo [4] 检查服务日志（最近 5 行错误）...
ssh %SERVER% "journalctl -u netsec_assistant -n 20 --no-pager 2>&1 | tail -20"

echo.
echo ========================================================
echo   验证: http://122.51.97.86/netsec/scan/security-scan
echo ========================================================
pause
