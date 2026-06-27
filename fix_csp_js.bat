@echo off
chcp 65001 >nul 2>&1
title Fix CSP & JS Vulnerabilities
cd /d "%~dp0"
python fix_csp_js.py
pause
