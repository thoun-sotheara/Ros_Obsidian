@echo off
title Rules of Survival - Launcher ^& Account Manager

REM Auto-elevate to Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "D:\Server\ROS"
python launch_client.py
