@echo off
chcp 65001 >nul
title OpenClaw 安装 & 配置向导
cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║     OpenClaw 智能网关 - 安装配置向导         ║
echo ╚══════════════════════════════════════════════╝
echo.
echo OpenClaw 是什么？
echo - 开源 AI Agent 网关，打通 20+ 聊天平台
echo - 支持 Telegram/Discord/WhatsApp/Slack/iMessage 等
echo - 本地运行，数据不上传
echo.

REM ---- 检查 Node.js ----
echo [1/4] 检查 Node.js...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Node.js 未安装
    echo   → 正在打开下载页面...
    start https://nodejs.org/
    echo   → 请安装 Node.js v22 LTS 后重新运行本脚本
    pause
    exit /b 1
)
for /f "tokens=1 delims=v" %%v in ('node --version 2^>^&1') do set NODE_VER=%%v
echo   ✓ Node.js v%NODE_VER%

REM 检查 Node 版本 >= 22
for /f "tokens=1 delims=." %%a in ("%NODE_VER%") do set NODE_MAJOR=%%a
if %NODE_MAJOR% LSS 22 (
    echo   ⚠ Node.js 版本过低 (需要 v22+)，可能不兼容
)

REM ---- 安装 OpenClaw ----
echo [2/4] 安装 OpenClaw...
where openclaw >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('openclaw --version 2^>^&1') do echo   ✓ 已安装: %%v
) else (
    echo   ! 正在安装 (npm install -g openclaw@latest)...
    call npm install -g openclaw@latest
    if %errorlevel% neq 0 (
        echo   ✗ 安装失败
        pause
        exit /b 1
    )
    echo   ✓ 安装成功
)

REM ---- 初始化 OpenClaw ----
echo [3/4] 初始化 OpenClaw...
if exist "%USERPROFILE%\.openclaw\openclaw.json" (
    echo   ✓ 已初始化
) else (
    echo   ! 首次运行初始化向导...
    echo.
    echo   ╔══════════════════════════════════════════╗
    echo   ║  OpenClaw 初始化向导                      ║
    echo   ║  请在新窗口中回答问题...                  ║
    echo   ╚══════════════════════════════════════════╝
    echo.
    openclaw onboard --install-daemon
    if %errorlevel% equ 0 (
        echo   ✓ 初始化完成
    ) else (
        echo   ⚠ 初始化可能已跳过（手动配置）
    )
)

REM ---- 配置 DeepSeek API ----
echo [4/4] 配置 AI 提供商...
set CONFIG_FILE=%USERPROFILE%\.openclaw\openclaw.json
if exist "%CONFIG_FILE%" (
    echo   ✓ 配置文件: %CONFIG_FILE%
    echo.
    echo ─────────────────────────────────────────────
    echo  手动配置步骤:
    echo.
    echo 1. 打开配置文件:
    echo    notepad %CONFIG_FILE%
    echo.
    echo 2. 在 "providers" 部分添加 DeepSeek:
    echo    { 
    echo      "providers": {
    echo        "deepseek": {
    echo          "api_key": "从 .env 中复制 DEEPSEEK_API_KEY",
    echo          "base_url": "https://api.deepseek.com"
    echo        }
    echo      }
    echo    }
    echo.
    echo 3. 配置聊天渠道 (Telegram/Discord/WhatsApp等)
    echo    详见: https://docs.openclaw.ai/
    echo ─────────────────────────────────────────────
    echo.
    start notepad "%CONFIG_FILE%"
) else (
    echo   ⚠ 配置文件未找到，请先运行 openclaw onboard
)

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  OpenClaw 安装完成！                          ║
echo ║                                              ║
echo ║  仪表盘: http://localhost:18789              ║
echo ║  配置文件: %CONFIG_FILE%                      ║
echo ║                                              ║
echo ║  启动命令: openclaw run                      ║
echo ║  停止命令: openclaw stop                     ║
echo ╚══════════════════════════════════════════════╝
echo.
pause
