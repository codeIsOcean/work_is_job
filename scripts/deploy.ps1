# Скрипт для быстрого деплоя на сервер (Windows PowerShell)
# Использование: .\scripts\deploy.ps1 user@server-ip

param(
    [Parameter(Mandatory=$true)]
    [string]$Server
)

$ServerPath = "/opt/telegram-bot"

Write-Host "🚀 Начинаю деплой на сервер $Server..." -ForegroundColor Green

# Копируем необходимые файлы на сервер
Write-Host "📦 Копирование файлов..." -ForegroundColor Yellow
scp docker-compose.prod.yml "${Server}:${ServerPath}/"
scp Dockerfile.prod "${Server}:${ServerPath}/"

Write-Host "🔧 Запуск на сервере..." -ForegroundColor Yellow

# Подключаемся к серверу и запускаем деплой
ssh $Server @"
cd $ServerPath

# Проверяем, что .env.prod существует
if [ ! -f .env.prod ]; then
    echo "❌ Файл .env.prod не найден!"
    echo "Создайте его из env.prod.example и заполните все переменные"
    exit 1
fi

# Останавливаем старые контейнеры
echo "🛑 Остановка старых контейнеров..."
docker compose -f docker-compose.prod.yml down || docker-compose -f docker-compose.prod.yml down || true

# Запускаем новые контейнеры
echo "🚀 Запуск новых контейнеров..."
docker compose -f docker-compose.prod.yml up -d --build || docker-compose -f docker-compose.prod.yml up -d --build

# Показываем статус
echo "📊 Статус контейнеров:"
docker compose -f docker-compose.prod.yml ps || docker-compose -f docker-compose.prod.yml ps

echo "✅ Деплой завершен!"
echo "📝 Просмотр логов: docker compose -f docker-compose.prod.yml logs -f bot_prod"
"@

Write-Host "✅ Готово!" -ForegroundColor Green

