@echo off
title UsChats - WeChat Export Tool
color 0B

echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║           UsChats by RTB Ruhan            ║
echo  ║      Simple WeChat Chat Exporter          ║
echo  ╚═══════════════════════════════════════════╝
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

REM Check if dependencies are installed
echo [*] Checking dependencies...
pip show flask >nul 2>&1
if errorlevel 1 (
    echo [*] Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
)

echo.
echo [*] Starting UsChats...
echo [*] Your browser will open automatically
echo [*] If not, go to: http://127.0.0.1:5555
echo.
echo ──────────────────────────────────────────────
echo  Press Ctrl+C to stop the server
echo ──────────────────────────────────────────────
echo.

python app.py

pause

