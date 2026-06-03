@echo off
chcp 65001 >nul
title AI_Assistant 开机自启配置

echo ============================================
echo   AI_Assistant 开机自启配置工具
echo ============================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 建议以管理员身份运行以获得最佳效果
    echo.
)

:: 创建 Startup 快捷方式
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%~dp0startup_silent.bat"

echo 创建开机自启快捷方式...
echo   目标: %TARGET%
echo   位置: %STARTUP_DIR%

:: 使用 PowerShell 创建快捷方式
powershell -Command ^
    "$WshShell = New-Object -ComObject WScript.Shell; ^
     $Shortcut = $WshShell.CreateShortcut('%STARTUP_DIR%\AI_Assistant.lnk'); ^
     $Shortcut.TargetPath = '%TARGET%'; ^
     $Shortcut.WorkingDirectory = '%~dp0'; ^
     $Shortcut.WindowStyle = 7; ^
     $Shortcut.Description = 'AI_Assistant 开机自启'; ^
     $Shortcut.Save()"

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   配置成功！
    echo ============================================
    echo.
    echo   AI_Assistant 将在下次开机时自动启动
    echo   如需取消，删除以下文件即可:
    echo     %STARTUP_DIR%\AI_Assistant.lnk
) else (
    echo.
    echo [错误] 创建快捷方式失败
    echo 请手动将 startup_silent.bat 的快捷方式复制到:
    echo   %STARTUP_DIR%
)

echo.
pause
