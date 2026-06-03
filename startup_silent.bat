@echo off
:: ============================================
:: AI_Assistant 开机自启 - 快捷方式
:: 将此文件的快捷方式放到 shell:startup 目录即可开机自动启动
:: 或者运行: setup_autostart.bat 自动配置
:: ============================================
chcp 65001 >nul
cd /d "%~dp0.."
start "" /MIN pythonw local_assistant.py
if exist "deploy\netsec\run.py" (
    cd deploy\netsec
    start "" /MIN pythonw run.py
)
echo AI_Assistant 已启动（后台运行）
