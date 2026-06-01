@echo off
chcp 65001 >nul
title 本地 AI 智能助手

echo ====================================
echo   本地 AI 智能助手
echo ====================================
echo.

:: 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] 虚拟环境已激活
) else (
    echo [!] 未找到虚拟环境，使用系统 Python
)

echo [启动] 正在启动本地 AI 助手...
echo.

:: 设置环境变量
if "%BRAIN_URL%"=="" set BRAIN_URL=http://localhost:5000
set ENABLE_BRAIN_AGENT=true

:: 启动
python local_assistant.py

pause
