# 🚀 Руководство по развертыванию Telegram бота

## 📋 Обзор

Проект поддерживает три окружения:
- **Development** — локальная разработка, запуск напрямую из Python.
- **Testing** — тестовый сервер или локальный Docker Compose.
- **Production** — продакшн сервер c Docker Compose и CI/CD.

## 🏗️ Структура проекта

```
├── .env.dev.example        # Пример конфигурации для разработки
├── .env.test.example       # Пример конфигурации для тестирования
├── .env.prod.example       # Пример конфигурации для продакшна
├── Dockerfile.test         # Образ для тестового окружения
├── Dockerfile.prod         # Образ для продакшна
├── docker-compose.test.yml # Docker Compose для теста
├── docker-compose.prod.yml # Docker Compose для продакшна
├── scripts/                # Скрипты развёртывания и утилиты
├── .github/workflows/      # CI/CD пайплайны
└── start_bot.py            # Универсальный локальный запуск
```

## 🔧 Настройка окружений

### 1. Development (локально)

1. Скопируй `env.dev.example` в `.env.dev` и заполни токены.
2. Установи зависимости: `pip install -r requirements.txt`.
3. Запускай через `python start_bot.py` (скрипт сам подхватит `.env.dev`).

### 2. Testing (Docker Compose)

#### Локально
```bash
cp env.test.example .env.test  # если файла еще нет
docker compose -f docker-compose.test.yml up --build
```
Контейнер `bot_test` собирается по `Dockerfile.test`, база и Redis разворачиваются автоматически.

#### На сервере
1. Размести проект в `/opt/jobs_inDubai_testBot`.
2. Создай `.env.test` на основе примера.
3. Запусти:
   ```bash
   cd /opt/jobs_inDubai_testBot
   docker compose -f docker-compose.test.yml up -d --build
   ```

### 3. Production

1. Размести проект в `/opt/jobs_inDubai_prod`.
2. Создай `.env.prod` из `env.prod.example`.
3. Запусти:
   ```bash
   cd /opt/jobs_inDubai_prod
   docker compose -f docker-compose.prod.yml up -d --build
   ```

## 🌐 Webhook настройка

- Установи `USE_WEBHOOK=true` в нужном `.env`.
- Заполни `WEBHOOK_URL`, `WEBHOOK_PATH`, `WEBHOOK_PORT`.
- Пропиши SSL сертификаты в `ssl/` и смонтируй их в `docker-compose.*.yml`.
- При необходимости подними nginx (см. конфиги в `nginx/`).

## 🔄 CI/CD Pipeline

CI/CD находится в `.github/workflows/` (`deploy-test.yml`, `deploy-prod.yml`, `deploy.yml`). Пайплайн:

1. `test` job (по pull request) ставит зависимости и проверяет импорт бота. Для него нужны секреты `TEST_BOT_TOKEN`, `TEST_LOG_CHANNEL_ID`, `TEST_ADMIN_IDS`.
2. Push в ветку `test` → синхронизация проекта на тестовом сервере + `docker compose up -d --build`.
3. Push в ветку `main` → те же шаги для продакшна.

### GitHub Secrets

Обязательные переменные (Settings → Secrets and variables → Actions):

| Назначение | Секрет |
|------------|--------|
| Test SSH   | `TEST_SERVER_HOST`, `TEST_SERVER_USER`, `TEST_SERVER_SSH_KEY` |
| Prod SSH   | `PROD_SERVER_HOST`, `PROD_SERVER_USER`, `PROD_SERVER_SSH_KEY` |
| CI тесты   | `TEST_BOT_TOKEN`, `TEST_LOG_CHANNEL_ID`, `TEST_ADMIN_IDS` |

SSH ключ можно получить на сервере:  
`ssh root@SERVER "cat ~/.ssh/github_actions_deploy"`

## 📊 Мониторинг

Просмотр логов:
```bash
docker logs -f bot_test
docker logs -f bot_prod
docker logs -f postgres_test
docker logs -f postgres_prod
docker logs -f redis_test
docker logs -f redis_prod
```

Проверка состояния:
```bash
docker compose -f docker-compose.test.yml ps
docker compose -f docker-compose.prod.yml ps
```

## 🔧 Управление контейнерами

```bash
# Перезапуск бота
docker compose -f docker-compose.prod.yml restart bot_prod

# Остановка
docker compose -f docker-compose.prod.yml down

# Обновление (пересборка)
docker compose -f docker-compose.prod.yml up -d --build
```

## 🗄️ Работа с БД

```bash
# Новая миграция
alembic revision --autogenerate -m "Описание изменений"

# Применение
alembic upgrade head

# Откат
alembic downgrade -1
```

## 🔒 Безопасность

- Храни `.env.*` только на серверах.
- Папка `ssl/` должна содержать актуальные сертификаты (`cert.pem`, `key.pem`).
- Открой только нужные порты: 22 (SSH), 80/443 (HTTP/HTTPS), 8080 (webhook).

## 🚨 Troubleshooting

```bash
# PostgreSQL
docker exec -it postgres_prod pg_isready -U postgres
docker exec -it postgres_prod psql -U postgres -d bot_prod

# Redis
docker exec -it redis_prod redis-cli ping

# Логи бота
docker logs bot_prod --tail 100
```

Если деплой через GitHub Actions не сработал — проверь вкладку `Actions`, затем логи на сервере (`docker compose ... ps`, `docker logs bot_prod`).

## 📞 Поддержка

1. Проверь логи контейнеров.
2. Убедись, что `.env.test` / `.env.prod` заполнены.
3. Проверь доступность внешних сервисов (Telegram API, БД, Redis).
4. Создай issue или обратись к команде.
