@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 检查 load_env.bat 是否存在
if not exist load_env.bat (
    echo [警告] load_env.bat 不存在，将使用当前环境变量
    echo.
) else (
    call load_env.bat
    if errorlevel 1 (
        echo [警告] load_env.bat 执行失败，继续使用当前环境变量
        echo.
    )
)

echo ================================
echo   配置自动备份
echo ================================
echo.
echo  1. 立即备份一次
echo  2. 启动定时备份（每小时）
echo.
choice /c 12 /n /m "请选择 [1/2]: "
if errorlevel 2 goto schedule
if errorlevel 1 goto once

:once
python backup_config.py
if errorlevel 1 (
    echo [错误] 备份执行失败！
    pause
)
goto end

:schedule
echo.
echo 启动定时备份（每小时备份，保留7天）...
echo 按 Ctrl+C 停止
echo.
python backup_config.py --schedule
goto end

:end

