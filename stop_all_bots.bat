@echo off
echo 🔍 Поиск всех запущенных экземпляров бота...

:: Поиск всех процессов Python, которые запускают start_bot.py
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr /v "PID" ^| findstr /v "INFO:"') do (
    echo Найден процесс Python с PID: %%i
)

echo.
echo 🛑 Остановка всех процессов Python...

:: Остановка всех процессов python.exe
taskkill /F /IM python.exe 2>nul

echo.
echo ✅ Все процессы Python остановлены!
echo.
echo 🚀 Теперь можно запустить бота командой: python start_bot.py
pause
