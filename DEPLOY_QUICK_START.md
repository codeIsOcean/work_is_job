# ⚡ Быстрая шпаргалка по деплою

## 🚀 Первый деплой (если сервер уже настроен)

### Вариант 1: Автоматический деплой через CI/CD (рекомендуется)

1. Настройте Secrets в GitHub (см. `DEPLOY_INSTRUCTION.md` Шаг 4)
2. Сделайте push в ветку `main`
3. GitHub Actions автоматически задеплоит

### Вариант 2: Ручной деплой через скрипт

```bash
# Linux/Mac
chmod +x scripts/deploy.sh
./scripts/deploy.sh user@server-ip

# Windows PowerShell
.\scripts\deploy.ps1 user@server-ip
```

---

## 🔧 Основные команды на сервере

### Подключение к серверу
```bash
ssh user@server-ip
cd /opt/telegram-bot
```

### Просмотр логов
```bash
docker compose -f docker-compose.prod.yml logs -f bot_prod
```

### Перезапуск бота
```bash
docker compose -f docker-compose.prod.yml restart bot_prod
```

### Остановка
```bash
docker compose -f docker-compose.prod.yml down
```

### Запуск
```bash
docker compose -f docker-compose.prod.yml up -d
```

### Обновление вручную (без CI/CD)
```bash
cd /opt/telegram-bot
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### Проверка статуса
```bash
docker compose -f docker-compose.prod.yml ps
```

---

## 📝 Настройка Secrets в GitHub

1. Перейдите: https://github.com/codeIsOcean/work_is_job/settings/secrets/actions
2. Добавьте Secrets:
   - `PROD_SERVER_HOST` - IP адрес сервера
   - `PROD_SERVER_USER` - имя пользователя SSH
   - `PROD_SERVER_SSH_KEY` - приватный SSH ключ

---

## ✅ Проверка работы

1. Проверьте логи: `docker compose logs -f bot_prod`
2. Проверьте health endpoint: `curl https://ваш-домен.com/health`
3. Проверьте webhook в логах (должно быть: "✅ Webhook установлен")

---

## ❗ Частые проблемы

**Проблема:** Бот не запускается
**Решение:** Проверьте `.env.prod` - все ли переменные заполнены

**Проблема:** CI/CD не подключается
**Решение:** Проверьте SSH ключ в GitHub Secrets и на сервере

**Проблема:** Webhook не устанавливается
**Решение:** Проверьте, что `WEBHOOK_URL` правильный и домен доступен

---

📚 **Подробная инструкция:** См. `DEPLOY_INSTRUCTION.md`

