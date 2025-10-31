@echo off
chcp 65001 >nul
echo ========================================
echo         SAFE BOT START SCRIPT
echo ========================================
echo.

echo 1. Stopping all Python processes...
taskkill /F /IM python.exe 2>nul
echo    All Python processes stopped.

echo.
echo 2. Resetting bot webhook...
python reset_bot_simple.py

echo.
echo 3. Waiting 5 seconds for Telegram API to clear state...
timeout /t 5 /nobreak >nul

echo.
echo 4. Starting bot...
echo    Bot will start now. Press Ctrl+C to stop.
echo.
python start_bot.py

echo.
echo Bot stopped.
pause
