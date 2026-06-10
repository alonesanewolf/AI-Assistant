@echo off
chcp 65001 >nul
title AI 智能助手 - 启动菜单

cd /d "%~dp0"

echo ============================================
echo   AI 智能助手 - 启动菜单
echo ============================================
echo.
echo   [1] 启动本地 Web 助手 (推荐)
echo       - 浏览器打开 http://localhost:8080
echo       - 支持 Ollama + DeepSeek 双模型
echo       - 同时连接云端 Brain 保持手机遥控
echo.
echo   [2] 启动命令行助手
echo       - 终端内与 DeepSeek 对话
echo       - 支持电脑操作、搜索、定时任务
echo.
echo   [3] 启动 Agent 客户端
echo       - 连接云端 Brain 等待远程指令
echo       - 适用于纯执行代理模式
echo.
echo   [4] 启动企业微信 AI 助手
echo       - 企业微信群机器人收发消息
echo       - 无需内网穿透，添加机器人即可
echo       - AI 对话 + 电脑远程操控
echo.
echo   [5] 启动云端 Brain 服务 (需要公网服务器)
echo       - 部署在云端服务器上
echo       - 支持 QQ/微信/Telegram 多渠道接入
echo.
echo   [0] 退出
echo.
echo ============================================
set /p choice="请选择 [0-5]: "

if "%choice%"=="1" goto local
if "%choice%"=="2" goto cli
if "%choice%"=="3" goto agent
if "%choice%"=="4" goto wechat
if "%choice%"=="5" goto brain
if "%choice%"=="0" goto end

echo 无效选择，请重试
pause
goto end

:local
echo.
echo 启动本地 Web 助手...
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
call "%~dp0load_env.bat"
if "%ROUTER_MODE%"=="" set ROUTER_MODE=local_first
if "%ENABLE_BRAIN_AGENT%"=="" set ENABLE_BRAIN_AGENT=true
python local_assistant.py
pause
goto end

:cli
echo.
echo 启动命令行助手...
call venv\Scripts\activate.bat
python assistant.py
pause
goto end

:agent
echo.
echo 启动 Agent 客户端...
call venv\Scripts\activate.bat
python agent_client.py
pause
goto end

:wechat
echo.
echo 启动微信 AI 助手...
call venv\Scripts\activate.bat
python wechat_assistant.py
pause
goto end

:brain
echo.
echo 启动云端 Brain 服务...
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
call "%~dp0load_env.bat"
python brain.py
pause
goto end

:end
