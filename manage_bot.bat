@echo off
chcp 65001 >nul
echo ========================================
echo           BOT MANAGEMENT SCRIPT
echo ========================================
echo.

:menu
echo Choose an option:
echo 1. Stop all Python processes
echo 2. Reset bot webhook
echo 3. Start bot
echo 4. Check running processes
echo 5. Exit
echo.
set /p choice="Enter your choice (1-5): "

if "%choice%"=="1" goto stop_all
if "%choice%"=="2" goto reset_webhook
if "%choice%"=="3" goto start_bot
if "%choice%"=="4" goto check_processes
if "%choice%"=="5" goto exit
echo Invalid choice. Please try again.
goto menu

:stop_all
echo.
echo Stopping all Python processes...
taskkill /F /IM python.exe 2>nul
echo All Python processes stopped.
echo.
goto menu

:reset_webhook
echo.
echo Resetting bot webhook...
python reset_bot_simple.py
echo.
goto menu

:start_bot
echo.
echo Starting bot...
python start_bot.py
goto menu

:check_processes
echo.
echo Checking running Python processes:
tasklist | findstr python
echo.
goto menu

:exit
echo Goodbye!
pause


