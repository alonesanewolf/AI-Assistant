@echo off
chcp 65001 >nul 2>&1
title Deploy CSS Fix
cd /d "%~dp0"
python deploy_css_fix.py
pause
