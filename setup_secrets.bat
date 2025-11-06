@echo off
echo ========================================
echo  Автоматическая настройка GitHub Secrets
echo ========================================
echo.

echo Шаг 1: Проверка авторизации GitHub CLI...
gh auth status >nul 2>&1
if errorlevel 1 (
    echo GitHub CLI не авторизован!
    echo.
    echo Авторизуйся в браузере:
    gh auth login --web
    echo.
    echo После авторизации запусти этот скрипт снова.
    pause
    exit /b 1
)

echo GitHub CLI авторизован
echo.

echo Шаг 2: Получение SSH ключа с сервера...
ssh root@88.210.35.183 "cat ~/.ssh/github_actions_deploy" > ssh_key_temp.txt 2>nul
if errorlevel 1 (
    echo Ошибка при получении SSH ключа!
    pause
    exit /b 1
)
echo SSH ключ получен
echo.

echo Шаг 3: Настройка secrets...
echo.

echo Установка TEST_SERVER_HOST...
gh secret set TEST_SERVER_HOST --body "88.210.35.183"
if errorlevel 1 (
    echo Ошибка при установке TEST_SERVER_HOST
) else (
    echo [OK] TEST_SERVER_HOST установлен
)

echo Установка TEST_SERVER_USER...
gh secret set TEST_SERVER_USER --body "root"
if errorlevel 1 (
    echo Ошибка при установке TEST_SERVER_USER
) else (
    echo [OK] TEST_SERVER_USER установлен
)

echo Установка TEST_SERVER_SSH_KEY...
type ssh_key_temp.txt | gh secret set TEST_SERVER_SSH_KEY
if errorlevel 1 (
    echo Ошибка при установке TEST_SERVER_SSH_KEY
) else (
    echo [OK] TEST_SERVER_SSH_KEY установлен
)

del ssh_key_temp.txt >nul 2>&1

echo.
echo Шаг 4: Проверка secrets...
gh secret list

echo.
echo ========================================
echo  Готово! Secrets настроены!
echo ========================================
echo.
echo Теперь CI/CD будет работать автоматически!
pause

