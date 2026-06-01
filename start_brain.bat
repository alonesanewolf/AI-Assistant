@echo off
chcp 65001 >nul
title 云端大脑 Brain (增强版)

cd /d "%~dp0"
call venv\Scripts\activate.bat

echo.
echo ============================================
echo   云端大脑 Brain - 启动中
echo ============================================
echo   访问: http://localhost:5000
echo   API:  http://localhost:5000/api/health
echo   QQ:   设置环境变量 QQ_BOT_ENABLED=true
echo   微信: 设置环境变量 WECHAT_ENABLED=true
echo ============================================
echo.

python brain.py
pause
