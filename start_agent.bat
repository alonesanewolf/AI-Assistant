@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   本地 Agent 客户端 - 启动中...
echo ========================================
echo.
echo   连接地址: %BRAIN_URL%
echo.

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 设置环境变量并启动
if "%BRAIN_URL%"=="" set BRAIN_URL=http://localhost:5000
python agent_client.py

echo.
echo Agent 已退出。
pause
