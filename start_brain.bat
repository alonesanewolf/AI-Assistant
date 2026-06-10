@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   云端大脑 Brain - 启动中...
echo ========================================
echo.
echo   Web 控制台: http://localhost:5000
echo   移动端:     http://localhost:5000/mobile
echo   DeepSeek:   已配置
echo.

REM 激活虚拟环境
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

REM 从 .env 加载配置
call "%~dp0load_env.bat"

if "%DEEPSEEK_API_KEY%"=="" (
    echo [警告] 未设置 DEEPSEEK_API_KEY，请编辑 .env 文件
)

if "%ROUTER_MODE%"=="" set ROUTER_MODE=local_first

REM 启动云端大脑
python brain.py

echo.
echo Brain 已退出。
pause
