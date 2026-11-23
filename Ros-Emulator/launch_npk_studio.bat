@echo off
title RoS NeoX NPK Studio ^& Extractor
cd /d "%~dp0"
echo Starting RoS NeoX NPK Studio...
python tools\npk_gui.py
if errorlevel 1 (
    echo.
    echo An error occurred while starting NPK Studio.
    pause
)
