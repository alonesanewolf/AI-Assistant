@echo off
chcp 65001 >nul
title Create Desktop Shortcut
cd /d "%~dp0"

echo.
echo ========================================
echo   Create AI Smart Assistant Shortcut
echo ========================================
echo.

set "DESKTOP=%USERPROFILE%\Desktop"
set "TARGET=%~dp0start.bat"
set "SHORTCUT=%DESKTOP%\AI_Assistant.lnk"

if not exist "%TARGET%" (
    echo [FAIL] Launcher not found: %TARGET%
    echo        Make sure start.bat is in the same folder
    pause
    exit /b 1
)

echo Target  : %TARGET%
echo Shortcut: %SHORTCUT%
echo.

if exist "%SHORTCUT%" del "%SHORTCUT%" 2>nul

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=1; $s.IconLocation='shell32.dll,13'; $s.Description='AI Smart Assistant'; $s.Save()"

if exist "%SHORTCUT%" (
    echo [OK] Desktop shortcut created!
    echo.
    echo   Double-click "AI_Assistant" on your desktop to start.
) else (
    echo [FAIL] Could not create shortcut.
    echo.
    echo   Manual: Right-click Desktop -^> New -^> Shortcut
    echo   Location: %TARGET%
)

echo.
pause
