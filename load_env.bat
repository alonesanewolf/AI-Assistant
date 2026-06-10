@echo off
REM 从 .env 加载环境变量（供其他 bat 脚本调用）
if not exist "%~dp0.env" exit /b 0
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0.env") do (
    if not "%%a"=="" if not "%%b"=="" set "%%a=%%b"
)
