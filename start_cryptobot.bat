@echo off
REM ============================================================
REM  CryptoBot Launcher
REM  Double-click this file to start the trading bot AND the
REM  dashboard at the same time, each in its own window.
REM ============================================================

REM --- EDIT THESE TWO PATHS IF YOUR FOLDERS ARE DIFFERENT -----
set PROJECT_DIR=C:\Users\Admin\Downloads\crypto-trading-bot
set VENV_DIR=C:\Users\Admin\venv
REM --------------------------------------------------------------

echo ============================================================
echo   Starting CryptoBot...
echo   Project: %PROJECT_DIR%
echo   Venv:    %VENV_DIR%
echo ============================================================

REM Start the trading bot in its own window
start "CryptoBot - Trading Engine" cmd /k "cd /d "%PROJECT_DIR%" && call "%VENV_DIR%\Scripts\activate.bat" && python bot.py"

REM Give the bot a couple seconds head start before the dashboard
timeout /t 3 /nobreak >nul

REM Start the dashboard in its own window
start "CryptoBot - Dashboard" cmd /k "cd /d "%PROJECT_DIR%" && call "%VENV_DIR%\Scripts\activate.bat" && python dashboard.py"

REM Give the dashboard a moment to spin up, then open it in the browser
timeout /t 3 /nobreak >nul
start http://localhost:5000

echo.
echo Both windows are launching. You can close this one.
timeout /t 5
exit
