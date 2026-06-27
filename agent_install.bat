@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI 助手 - Agent 客户端

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║     AI 助手云端大脑 - Agent 客户端                    ║
echo  ║     通过 QQ/微信/Telegram 远程控制你的电脑            ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ========== 检查配置 ==========
set BRAIN_URL=http://122.51.97.86/brain
set AGENT_NAME=%COMPUTERNAME%

if not "%1"=="" set BRAIN_URL=%1
if not "%2"=="" set AGENT_NAME=%2

echo  [配置] 大脑地址:  %BRAIN_URL%
echo  [配置] 设备名称:  %AGENT_NAME%
echo.

:: ========== 安装依赖 ==========
echo  [1/3] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo  [错误] 未找到 Python，请先安装 Python 3.8+
    echo  下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  [2/3] 安装必要依赖...
pip install python-socketio[client] pyautogui pyperclip psutil -q 2>&1 | findstr /V "already satisfied" | findstr /V "Requirement" | findstr /V "WARNING"

echo  [3/3] 启动 Agent...
echo.
echo  ==========================================================
echo    Agent 已启动！等待云端大脑指令...
echo    在手机 QQ/微信/Telegram 发送消息即可控制本电脑
echo  ==========================================================
echo.

:: ========== 设置环境变量并启动 ==========
set PYTHONIOENCODING=utf-8
python agent_client.py %BRAIN_URL% "%AGENT_NAME%"

echo.
echo Agent 已退出。
pause
