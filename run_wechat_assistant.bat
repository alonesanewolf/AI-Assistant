@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   企业微信 AI 助手 - 启动
echo ========================================
echo.

REM 检查虚拟环境
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM 如果未配置 Webhook，显示帮助
if "%WECOM_WEBHOOK%"=="" (
    if "%WECOM_CORP_ID%"=="" (
        echo ============================================
        echo   【首次使用】配置步骤
        echo ============================================
        echo.
        echo   方式一：群机器人（推荐，超简单）
        echo   1. 打开企业微信 → 进入一个群聊
        echo   2. 右上角 ... → 群机器人 → 添加机器人
        echo   3. 复制 Webhook 地址
        echo   4. 在此窗口输入:
        echo      set WECOM_WEBHOOK=你的webhook地址
        echo      run_wechat_assistant.bat
        echo.
        echo   方式二：自建应用（更强大）
        echo   1. 登录企业微信管理后台 work.weixin.qq.com
        echo   2. 应用管理 → 创建应用
        echo   3. 获取 CorpID 和 Secret
        echo   4. 设置环境变量:
        echo      set WECOM_CORP_ID=xxx
        echo      set WECOM_AGENT_SECRET=xxx
        echo      set WECOM_TOKEN=xxx
        echo      set WECOM_ENCODING_AES_KEY=xxx
        echo.
        echo ============================================
        echo.
    )
)

echo 启动企业微信 AI 助手服务...
echo.
echo 状态页面: http://localhost:5050/
echo 按 Ctrl+C 停止服务
echo ============================================
echo.

%PYTHON% wechat_assistant.py

pause
