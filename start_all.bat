@echo off
chcp 65001 >nul
title AI_Assistant 统一平台 - 电脑端启动

echo ============================================
echo   AI_Assistant 统一平台 - 电脑端
echo ============================================
echo.

:: 进入项目目录
cd /d "%~dp0"

:: 使用虚拟环境中的 Python
set VENV_PYTHON=%~dp0venv\Scripts\python.exe
set VENV_PIP=%~dp0venv\Scripts\pip.exe

:: 检查虚拟环境 Python
%VENV_PYTHON% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到虚拟环境 Python，请先运行 setup 创建 venv
    pause
    exit /b 1
)

:: 检查依赖
echo [1/3] 检查 Python 依赖...
%VENV_PIP% install -r requirements.txt >nul 2>&1
echo   依赖检查完成

:: 创建日志目录
if not exist "logs" mkdir logs

:: 启动 AI 助手 (端口 8080)
echo [2/3] 启动 AI 智能助手 (端口 8080)...
start "AI_Assistant" /MIN %VENV_PYTHON% local_assistant.py
echo   AI 智能助手已启动

:: 启动网络安全助手 (端口 5100) - 可选
echo [3/3] 启动网络安全助手 (端口 5100)...
if exist "deploy\netsec\run.py" (
    cd deploy\netsec
    %VENV_PIP% install -r requirements.txt >nul 2>&1
    start "NetSec_Assistant" /MIN %VENV_PYTHON% run.py
    cd ..\..
    echo   网络安全助手已启动
) else (
    echo   [跳过] 未找到 NetSec 文件
)

echo.
echo ============================================
echo   启动完成！
echo ============================================
echo.
echo   AI 智能助手:   http://localhost:8080
echo   网络安全助手:   http://localhost:5100
echo.
echo   按任意键关闭此窗口（服务将继续在后台运行）
pause >nul
