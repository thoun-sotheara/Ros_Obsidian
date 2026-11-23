@echo off
title Rules of Survival - Emulator Server
cd /d "%~dp0"

REM --- Auto-elevate to Administrator (needed for ports 80/443) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs" >nul 2>&1
    exit /b
)

python run_server.py
pause
