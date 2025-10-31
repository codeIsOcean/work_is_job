# 🚀 Руководство по развертыванию Telegram бота

## 📋 Обзор

Проект настроен для работы в трех окружениях:
- **Development** - локальная разработка
- **Testing** - тестовое окружение
- **Production** - продакшн окружение

## 🏗️ Структура проекта

```
├── .env.dev.example          # Пример конфигурации для разработки
├── .env.test.example         # Пример конфигурации для тестирования
├── .env.prod.example         # Пример конфигурации для продакшна
├── Dockerfile.dev            # Docker образ для разработки
├── Dockerfile.test           # Docker образ для тестирования
├── Dockerfile.prod           # Docker образ для продакшна
├── docker-compose.dev.yml    # Docker Compose для разработки
├── docker-compose.test.yml   # Docker Compose для тестирования
├── docker-compose.prod.yml   # Docker Compose для продакшна
├── nginx/                    # Nginx конфигурации
├── scripts/                  # Скрипты для управления
└── .github/workflows/        # CI/CD пайплайны
```

## 🔧 Настройка окружений

### 1. Development (Локальная разработка)

#### В PyCharm:
1. Скопируйте `env.dev.example` в `.env.dev`
2. Заполните реальными значениями:
   ```env
   BOT_TOKEN=your_dev_bot_token
   DATABASE_URL=postgresql://postgres:password@localhost:5432/bot_dev
   LOG_CHANNEL_ID=your_dev_log_channel
   ADMIN_IDS=your_admin_id
   ```
3. Установите `ENVIRONMENT=development` в переменных окружения PyCharm
4. Запустите `main.py`

#### В Docker:
```bash
# Запуск dev окружения
./scripts/dev.sh

# Или вручную
export ENVIRONMENT=development
docker-compose -f docker-compose.dev.yml up --build
```

### 2. Testing (Тестовое окружение)

#### Локально:
```bash
# Запуск test окружения
./scripts/test.sh

# Или вручную
export ENVIRONMENT=testing
docker-compose -f docker-compose.test.yml up --build
```

#### На сервере:
1. Скопируйте `env.test.example` в `.env.test`
2. Заполните реальными значениями
3. Запустите:
   ```bash
   export ENVIRONMENT=testing
   docker-compose -f docker-compose.test.yml up --build -d
   ```

### 3. Production (Продакшн)

#### На сервере:
1. Скопируйте `env.prod.example` в `.env.prod`
2. Заполните реальными значениями
3. Запустите:
   ```bash
   export ENVIRONMENT=production
   docker-compose -f docker-compose.prod.yml up --build -d
   ```

## 🌐 Webhook настройка

### Для тестового окружения:
1. Убедитесь, что `USE_WEBHOOK=true` в `.env.test`
2. Настройте `WEBHOOK_URL=https://your-domain.com/webhook`
3. Запустите nginx для проксирования

### Для продакшна:
1. Убедитесь, что `USE_WEBHOOK=true` в `.env.prod`
2. Настройте SSL сертификаты в папке `ssl/`
3. Обновите nginx конфигурацию с вашим доменом
4. Запустите nginx с SSL

## 🔄 CI/CD Pipeline

### Настройка GitHub Secrets:

#### Для тестового сервера:
- `TEST_SERVER_HOST` - IP адрес тестового сервера
- `TEST_SERVER_USER` - пользователь для SSH
- `TEST_SERVER_SSH_KEY` - приватный SSH ключ
- `TEST_BOT_TOKEN` - токен тестового бота
- `TEST_LOG_CHANNEL_ID` - ID канала для логов
- `TEST_ADMIN_IDS` - ID администраторов

#### Для продакшн сервера:
- `PROD_SERVER_HOST` - IP адрес продакшн сервера
- `PROD_SERVER_USER` - пользователь для SSH
- `PROD_SERVER_SSH_KEY` - приватный SSH ключ
- `PROD_BOT_TOKEN` - токен продакшн бота
- `PROD_LOG_CHANNEL_ID` - ID канала для логов
- `PROD_ADMIN_IDS` - ID администраторов

#### Общие:
- `POSTGRES_PASSWORD` - пароль для PostgreSQL
- `SLACK_WEBHOOK` - webhook для уведомлений в Slack

### Workflow:
1. **Pull Request** → запускает тесты
2. **Push to test branch** → деплой на тестовый сервер
3. **Push to main branch** → деплой на продакшн сервер

## 📊 Мониторинг

### Health Checks:
- `http://your-domain.com/health` - проверка состояния бота
- `http://your-domain.com/nginx_status` - статус nginx
- `http://your-domain.com/metrics` - метрики (только для продакшна)

### Логи:
```bash
# Логи бота
docker logs bot_dev
docker logs bot_test
docker logs bot_prod

# Логи nginx
docker logs nginx_test
docker logs nginx_prod

# Логи базы данных
docker logs postgres_dev
docker logs postgres_test
docker logs postgres_prod
```

## 🔧 Управление

### Полезные команды:

```bash
# Запуск окружений
./scripts/dev.sh      # Development
./scripts/test.sh     # Testing
./scripts/prod.sh     # Production

# Остановка всех окружений
./scripts/stop.sh

# Просмотр логов
docker-compose -f docker-compose.dev.yml logs -f
docker-compose -f docker-compose.test.yml logs -f
docker-compose -f docker-compose.prod.yml logs -f

# Перезапуск сервисов
docker-compose -f docker-compose.prod.yml restart bot_prod

# Обновление образов
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

## 🗄️ База данных

### Миграции:
```bash
# Создание новой миграции
alembic revision --autogenerate -m "Описание изменений"

# Применение миграций
alembic upgrade head

# Откат миграций
alembic downgrade -1
```

### Backup (только для продакшна):
Автоматический backup настроен в `docker-compose.prod.yml`:
- Создается каждый день в 2:00
- Хранится 30 дней
- Файлы сохраняются в папке `backups/`

## 🔒 Безопасность

### SSL сертификаты:
1. Поместите сертификаты в папку `ssl/`:
   - `ssl/cert.pem` - SSL сертификат
   - `ssl/private/key.pem` - приватный ключ

### Firewall:
Убедитесь, что открыты порты:
- 80 (HTTP)
- 443 (HTTPS)
- 22 (SSH)

## 🚨 Troubleshooting

### Проблемы с подключением к базе данных:
```bash
# Проверка статуса PostgreSQL
docker exec -it postgres_dev pg_isready -U postgres

# Подключение к базе данных
docker exec -it postgres_dev psql -U postgres -d bot_dev
```

### Проблемы с Redis:
```bash
# Проверка статуса Redis
docker exec -it redis_dev redis-cli ping

# Подключение к Redis
docker exec -it redis_dev redis-cli
```

### Проблемы с webhook:
```bash
# Проверка webhook
curl -X POST https://your-domain.com/webhook -d '{"test": "data"}'

# Проверка логов nginx
docker logs nginx_prod
```

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи всех сервисов
2. Убедитесь, что все переменные окружения настроены
3. Проверьте доступность внешних сервисов (Telegram API, база данных)
4. Обратитесь к документации или создайте issue в репозитории
