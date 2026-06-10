@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 从 .env 加载配置（可在 .env 中设置 BRAIN_URL）
call "%~dp0load_env.bat"
if "%BRAIN_URL%"=="" set BRAIN_URL=http://localhost:5200

echo ========================================
echo   本地 Agent 客户端 - 连接云服务器
echo ========================================
echo.
echo   大脑地址: %BRAIN_URL%
echo.

REM 激活虚拟环境
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

python agent_client.py

echo.
echo Agent 已退出。
pause
