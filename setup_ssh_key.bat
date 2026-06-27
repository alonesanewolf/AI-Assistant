@echo off
chcp 65001 >nul 2>&1
title Setup SSH Key Authentication
cd /d "%~dp0"

echo.
echo ========================================================
echo   SSH 免密登录配置
echo ========================================================
echo.

set SERVER=root@122.51.97.86

echo [1/3] 检查本地 SSH 密钥...
if exist "%USERPROFILE%\.ssh\id_rsa.pub" (
    echo   [OK] 已有密钥: %USERPROFILE%\.ssh\id_rsa.pub
) else if exist "%USERPROFILE%\.ssh\id_ed25519.pub" (
    echo   [OK] 已有密钥: %USERPROFILE%\.ssh\id_ed25519.pub
) else (
    echo   [--] 未找到密钥，正在生成...
    ssh-keygen -t ed25519 -f "%USERPROFILE%\.ssh\id_ed25519" -N "" -C "ai_assistant_deploy"
    if %errorlevel% neq 0 (
        echo   [!] ed25519 不支持，改用 RSA...
        ssh-keygen -t rsa -b 4096 -f "%USERPROFILE%\.ssh\id_rsa" -N "" -C "ai_assistant_deploy"
    )
    echo   [OK] 密钥已生成
)

echo.
echo [2/3] 上传公钥到服务器...
type "%USERPROFILE%\.ssh\id_*.pub" 2>nul > "%TEMP%\authorized_keys_temp"
scp "%TEMP%\authorized_keys_temp" %SERVER%:/tmp/my_key.pub
if %errorlevel% neq 0 (
    echo   [FAIL] 上传失败，请检查网络
    pause
    exit /b 1
)
ssh %SERVER% "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat /tmp/my_key.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && rm /tmp/my_key.pub && echo '  [OK] 公钥已添加'"
del "%TEMP%\authorized_keys_temp" 2>nul

echo.
echo [3/3] 测试免密登录...
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o PasswordAuthentication=no %SERVER% "echo '  [OK] 免密登录成功！' && hostname && uptime -p"
if %errorlevel% neq 0 (
    echo   [FAIL] 免密登录失败，可能是服务器禁用了密钥认证
) else (
    echo.
    echo ========================================================
    echo   [DONE] 以后运行脚本不再需要输入密码
    echo ========================================================
)
pause
