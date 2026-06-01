@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   DeepSeek AI 助手 - 启动中...
echo ========================================
echo.

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 运行程序
python assistant.py

REM 程序退出后暂停，方便查看输出
echo.
echo 程序已退出。
pause
