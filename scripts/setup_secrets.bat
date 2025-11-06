@echo off
echo ========================================
echo  Настройка GitHub Secrets для CI/CD
echo ========================================
echo.

echo Шаг 1: Авторизация в GitHub CLI
echo Откройте браузер и авторизуйтесь
gh auth login --web
echo.

echo Шаг 2: Настройка secrets...
echo.

echo Установка TEST_SERVER_HOST...
gh secret set TEST_SERVER_HOST --body "88.210.35.183"
if %errorlevel% equ 0 (
    echo [OK] TEST_SERVER_HOST установлен
) else (
    echo [ERROR] Не удалось установить TEST_SERVER_HOST
)
echo.

echo Установка TEST_SERVER_USER...
gh secret set TEST_SERVER_USER --body "root"
if %errorlevel% equ 0 (
    echo [OK] TEST_SERVER_USER установлен
) else (
    echo [ERROR] Не удалось установить TEST_SERVER_USER
)
echo.

echo Установка TEST_SERVER_SSH_KEY...
(
echo -----BEGIN OPENSSH PRIVATE KEY-----
echo b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
echo QyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40AAAAJgxelFNMXpR
echo TQAAAAtzc2gtZWQyNTUxOQAAACAcye/IIKPnBGxJFp6upECEoBwWisgm15XTBH+KN8T40A
echo AAAEDbo3lGqkb+SfD1zdg0lnK5Kjim8a1xKWLnynL6T1pI0RzJ78ggo+cEbEkWnq6kQISg
echo HBaKyCbXldMEf4o3xPjQAAAAFWdpdGh1Yi1hY3Rpb25zLWRlcGxveQ==
echo -----END OPENSSH PRIVATE KEY-----
) | gh secret set TEST_SERVER_SSH_KEY
if %errorlevel% equ 0 (
    echo [OK] TEST_SERVER_SSH_KEY установлен
) else (
    echo [ERROR] Не удалось установить TEST_SERVER_SSH_KEY
)
echo.

echo Шаг 3: Проверка secrets...
gh secret list
echo.

echo ========================================
echo  Готово! Все secrets настроены.
echo ========================================
echo.
echo Теперь CI/CD должен работать при push в ветку test или main!
pause

