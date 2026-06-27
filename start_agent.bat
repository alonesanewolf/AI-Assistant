@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 加载 .env 环境变量
call "%~dp0load_env.bat"

echo ========================================
echo   本地 Agent 客户端 - 启动中...
echo ========================================
echo.
echo   连接地址: %BRAIN_URL%
echo.

REM 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [!] 未找到虚拟环境，使用系统 Python
)

REM 设置环境变量并启动
if "%BRAIN_URL%"=="" set BRAIN_URL=http://localhost:5000
python agent_client.py

echo.
echo Agent 已退出。
pause
