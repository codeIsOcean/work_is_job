# 📋 Пошаговая инструкция по деплою бота на сервер

## ⚡ Быстрый старт

**Если у вас уже настроен сервер и вы хотите быстро задеплоить:**

```bash
# Linux/Mac
./scripts/deploy.sh user@server-ip

# Windows PowerShell
.\scripts\deploy.ps1 user@server-ip
```

**Если настраиваете всё с нуля - читайте инструкцию ниже 👇**

---

## 🎯 Что вам понадобится

1. **Сервер** (Linux, Ubuntu/Debian) с доступом по SSH
2. **Домен** (опционально, для webhook с HTTPS)
3. **GitHub аккаунт** (уже есть)
4. **Telegram Bot Token** (от @BotFather)

---

## 📝 Шаг 1: Подготовка сервера

### 1.1 Подключитесь к серверу по SSH

```bash
ssh user@your-server-ip
```

### 1.2 Установите Docker и Docker Compose

```bash
# Обновляем пакеты
sudo apt update && sudo apt upgrade -y

# Устанавливаем Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Добавляем пользователя в группу docker
sudo usermod -aG docker $USER

# Устанавливаем Docker Compose
sudo apt install docker-compose-plugin -y

# Перезагружаем сессию (или выйдите и зайдите заново)
newgrp docker

# Проверяем установку
docker --version
docker compose version
```

### 1.3 Создайте директорию для проекта

```bash
sudo mkdir -p /opt/telegram-bot
sudo chown $USER:$USER /opt/telegram-bot
cd /opt/telegram-bot
```

### 1.4 Скопируйте файлы на сервер

Есть два способа:

**Вариант A: Клонировать репозиторий (рекомендуется)**

```bash
git clone https://github.com/codeIsOcean/work_is_job.git .
```

**Вариант B: Скопировать через SCP (с вашего компьютера)**

```bash
# С вашего компьютера
scp -r docker-compose.prod.yml Dockerfile.prod nginx/ env.prod.example user@your-server-ip:/opt/telegram-bot/
```

---

## 📝 Шаг 2: Настройка переменных окружения

### 2.1 Создайте файл `.env.prod` на сервере

```bash
cd /opt/telegram-bot
cp env.prod.example .env.prod
nano .env.prod
```

### 2.2 Заполните файл `.env.prod`:

```env
# Bot Configuration
BOT_TOKEN=ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER
LOG_CHANNEL_ID=ВАШ_ID_КАНАЛА_ДЛЯ_ЛОГОВ
ADMIN_IDS=ВАШ_TELEGRAM_ID

# Database Configuration
DATABASE_URL=postgresql://postgres:ПРИДУМАЙТЕ_ПАРОЛЬ@postgres_prod:5432/bot_prod
POSTGRES_PASSWORD=ПРИДУМАЙТЕ_СИЛЬНЫЙ_ПАРОЛЬ

# Redis Configuration
REDIS_URL=redis://redis_prod:6379/0
REDIS_HOST=redis_prod
REDIS_PORT=6379

# Environment
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

# Webhook Configuration
USE_WEBHOOK=true
WEBHOOK_URL=https://ваш-домен.com/webhook
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8080

# Security
SECRET_KEY=СГЕНЕРИРУЙТЕ_СЛУЧАЙНУЮ_СТРОКУ_32_СИМВОЛА
ALLOWED_HOSTS=ваш-домен.com

# Database Pool
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
```

**Важно:**
- Замените все `ВАШ_*` на реальные значения
- Для `SECRET_KEY` сгенерируйте случайную строку: `openssl rand -hex 32`
- Если нет домена, используйте IP сервера (но HTTPS не будет работать)

### 2.3 Сохраните файл и ограничьте доступ

```bash
chmod 600 .env.prod
```

---

## 📝 Шаг 3: Настройка Nginx (если есть домен)

### 3.1 Обновите `nginx/nginx.prod.conf`

Замените `your-domain.com` на ваш реальный домен:

```bash
nano nginx/nginx.prod.conf
# Замените все вхождения your-domain.com на ваш домен
```

### 3.2 Установите SSL сертификаты (Let's Encrypt)

```bash
# Установите Certbot
sudo apt install certbot -y

# Получите сертификат (замените ваш-домен.com)
sudo certbot certonly --standalone -d ваш-домен.com

# Скопируйте сертификаты в директорию проекта
sudo mkdir -p /opt/telegram-bot/ssl
sudo cp /etc/letsencrypt/live/ваш-домен.com/fullchain.pem /opt/telegram-bot/ssl/cert.pem
sudo cp /etc/letsencrypt/live/ваш-домен.com/privkey.pem /opt/telegram-bot/ssl/key.pem
sudo chown $USER:$USER /opt/telegram-bot/ssl/*
```

---

## 📝 Шаг 4: Настройка GitHub Secrets для CI/CD

### 4.1 Перейдите в настройки репозитория GitHub

1. Откройте: https://github.com/codeIsOcean/work_is_job
2. Settings → Secrets and variables → Actions
3. Нажмите "New repository secret"

### 4.2 Добавьте следующие Secrets:

| Secret Name | Значение | Описание |
|------------|----------|----------|
| `PROD_SERVER_HOST` | IP адрес вашего сервера | IP сервера для SSH |
| `PROD_SERVER_USER` | Имя пользователя для SSH | Обычно `root` или имя пользователя |
| `PROD_SERVER_SSH_KEY` | Приватный SSH ключ | См. шаг 4.3 |
| `TEST_BOT_TOKEN` | Токен тестового бота | Опционально, для тестов |

### 4.3 Создание SSH ключа для CI/CD

**На вашем компьютере (Windows PowerShell):**

```powershell
# Сгенерируйте SSH ключ (если еще нет)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy

# Скопируйте ПРИВАТНЫЙ ключ (для GitHub Secret)
Get-Content ~/.ssh/github_actions_deploy | Set-Clipboard

# Скопируйте ПУБЛИЧНЫЙ ключ на сервер
type ~/.ssh/github_actions_deploy.pub | ssh user@your-server-ip "cat >> ~/.ssh/authorized_keys"
```

**На сервере:**

```bash
# Убедитесь, что SSH ключ добавлен
cat ~/.ssh/authorized_keys
```

---

## 📝 Шаг 5: Первый запуск на сервере (вручную)

### 5.1 Запустите бота

```bash
cd /opt/telegram-bot

# Запустите контейнеры
docker compose -f docker-compose.prod.yml up -d --build

# Проверьте логи
docker compose -f docker-compose.prod.yml logs -f bot_prod
```

### 5.2 Проверьте, что всё работает

```bash
# Проверьте статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Проверьте health endpoint (если есть домен)
curl https://ваш-домен.com/health
# Должен вернуть: {"status":"ok","service":"telegram_bot"}

# Проверьте логи
docker compose -f docker-compose.prod.yml logs bot_prod
```

### 5.3 Проверьте, что webhook установлен

В логах должно быть сообщение:
```
✅ Webhook установлен: https://ваш-домен.com/webhook
```

---

## 📝 Шаг 6: Настройка автоматического деплоя (CI/CD)

### 6.1 Выберите workflow

У вас есть два варианта:

**Вариант A: Полный workflow** (`.github/workflows/deploy.yml`)
- С тестами и тестовым окружением
- Подходит для проектов с тестами

**Вариант B: Упрощенный workflow** (`.github/workflows/deploy-simple.yml`)
- Без тестов, только деплой
- Проще настроить

**Рекомендация:** Для начала используйте упрощенный вариант.

### 6.2 Если хотите использовать упрощенный workflow

```bash
# На вашем компьютере
mv .github/workflows/deploy.yml .github/workflows/deploy-full.yml.backup
mv .github/workflows/deploy-simple.yml .github/workflows/deploy.yml
git add .github/workflows/deploy.yml
git commit -m "Switch to simple deployment workflow"
git push
```

### 6.3 Обновите путь к проекту (если нужно)

В файле `.github/workflows/deploy.yml` путь к проекту:
- По умолчанию: `/opt/telegram-bot`
- Если у вас другой путь, измените в строке с `cd /opt/telegram-bot`

### 6.4 Первый автоматический деплой

После пуша в ветку `main`, GitHub Actions автоматически:
1. Соберет Docker образ
2. Задеплоит на сервер

Проверить можно здесь: https://github.com/codeIsOcean/work_is_job/actions

**Важно:** Убедитесь, что все Secrets настроены в GitHub (см. Шаг 4)!

---

## 🔧 Управление ботом на сервере

### Просмотр логов
```bash
docker compose -f docker-compose.prod.yml logs -f bot_prod
```

### Перезапуск
```bash
docker compose -f docker-compose.prod.yml restart bot_prod
```

### Остановка
```bash
docker compose -f docker-compose.prod.yml down
```

### Обновление вручную (без CI/CD)
```bash
cd /opt/telegram-bot
git pull  # Если клонировали репозиторий
docker compose -f docker-compose.prod.yml up -d --build
```

---

## ❗ Возможные проблемы и решения

### Проблема: Webhook не устанавливается

**Решение:**
1. Проверьте, что `WEBHOOK_URL` правильный и доступен извне
2. Проверьте, что SSL сертификат валиден
3. Проверьте firewall: `sudo ufw allow 443/tcp`

### Проблема: Бот не запускается

**Решение:**
1. Проверьте `.env.prod` - все ли переменные заполнены
2. Проверьте логи: `docker compose -f docker-compose.prod.yml logs bot_prod`
3. Проверьте, что PostgreSQL и Redis запущены

### Проблема: CI/CD не подключается к серверу

**Решение:**
1. Проверьте SSH ключ в GitHub Secrets
2. Проверьте, что ключ добавлен в `authorized_keys` на сервере
3. Проверьте, что сервер доступен из интернета

---

## 📞 Дополнительная помощь

Если возникнут проблемы:
1. Проверьте логи: `docker compose logs -f`
2. Проверьте статус контейнеров: `docker compose ps`
3. Проверьте логи GitHub Actions на вкладке Actions в репозитории

