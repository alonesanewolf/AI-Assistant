@echo off
chcp 65001 >nul 2>&1
title AI_Assistant - AutoStart

cd /d "%~dp0"

set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    pythonw local_assistant.py
) else (
    start "" /MIN "%VENV_PYTHON%" local_assistant.py
)

if exist "deploy\netsec\run.py" (
    cd deploy\netsec
    if exist "..\..\venv\Scripts\python.exe" (
        start "" /MIN "..\..\venv\Scripts\python.exe" run.py
    ) else (
        start "" /MIN pythonw run.py
    )
    cd ..\..
)

echo AI_Assistant started (background)
