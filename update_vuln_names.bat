@echo off
chcp 65001 >nul 2>&1
title Update All 14 Vulnerability Names
cd /d "%~dp0"
python update_vuln_names.py
pause
