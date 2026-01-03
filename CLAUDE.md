# KVD Moder Bot - AI Context

> **ВАЖНО:** Этот файл читается Claude Code автоматически при старте каждой сессии.
> Обязательно прочти `docs/DEVELOPER_RULES.md` перед любыми изменениями!

## Quick Overview

**Проект:** Telegram бот для модерации групп с капчей, антиспамом и системой мутов.

**Стек:**
- Python 3.11+
- aiogram 3.x (Telegram Bot API)
- SQLAlchemy 2.x (async) + PostgreSQL
- Redis (кэш, состояния FSM)
- Alembic (миграции)
- Pyrogram (MTProto для расширенного анализа)
- Docker + CI/CD

**Деплой:** Сервер 88.210.35.183, Docker Compose

---

## Project Structure

```
D:\test_kvdModerBotProd\
├── CLAUDE.md                    # <- Ты здесь (AI контекст)
├── bot/
│   ├── bot.py                   # Точка входа, инициализация
│   ├── config.py                # Конфигурация из .env
│   ├── webhook.py               # Webhook сервер
│   ├── database/
│   │   ├── models.py            # Основные SQLAlchemy модели
│   │   ├── models_antispam.py   # Модели антиспам (enum, правила)
│   │   ├── models_content_filter.py # Модели фильтра контента
│   │   ├── mute_models.py       # Модели мутов
│   │   ├── session.py           # AsyncSession factory
│   │   └── queries.py           # SQL запросы
│   ├── handlers/                # Все обработчики событий
│   │   ├── __init__.py          # Главный роутер (handlers_router)
│   │   ├── captcha/             # Капча (coordinator, callbacks, FSM)
│   │   ├── antispam_handlers/   # Антиспам (настройки + фильтр)
│   │   ├── content_filter/      # Фильтр контента (слова, скам, флуд)
│   │   ├── group_settings_handler/  # /settings в ЛС
│   │   ├── bot_moderation_handlers/ # Муты новых участников
│   │   ├── mute_by_reaction/    # Мут по реакции
│   │   └── ...
│   ├── services/                # Бизнес-логика
│   │   ├── captcha/             # Модуль капчи (settings, flow, verification)
│   │   ├── antispam/            # Антиспам сервис
│   │   ├── content_filter/      # Фильтр контента (нормализация, слова)
│   │   ├── risk_gate.py         # Оценка риска пользователя
│   │   ├── group_auto_sync.py   # Автосинхронизация групп
│   │   ├── spammer_registry.py  # Реестр спаммеров
│   │   └── ...
│   ├── middleware/              # Middleware для Dispatcher
│   │   ├── db_session.py        # Инъекция AsyncSession
│   │   ├── group_auto_sync_middleware.py
│   │   └── structured_logging.py
│   └── keyboards/               # Inline клавиатуры
├── alembic/                     # Миграции БД
│   └── versions/
├── docs/                        # Документация
│   ├── DEVELOPER_RULES.md       # Жёсткие правила разработки
│   ├── ARCHITECTURE.md          # Архитектура
│   ├── DATABASE.md              # Схема БД
│   ├── HANDLERS.md              # Карта хендлеров
│   ├── MODULES.md               # Описание модулей
│   └── USAGE.md                 # Гайд по использованию
├── tests/                       # Тесты
├── docker-compose.yml
└── .env                         # Секреты (НЕ коммитить!)
```

---

## Critical Files & Logic

### Капча (РЕДИЗАЙН 2025-12)
| Файл | Назначение |
|------|------------|
| `bot/handlers/captcha/captcha_coordinator.py` | **ЕДИНАЯ ТОЧКА ВХОДА** (chat_join_request, new_chat_members) |
| `bot/handlers/captcha/captcha_callbacks.py` | Callback обработчики (verify, настройки диалогов) |
| `bot/handlers/captcha/captcha_fsm_handler.py` | FSM для deep link (/start) и ручного ввода ответа |
| `bot/handlers/captcha/captcha_keyboards.py` | Клавиатуры (2 кнопки в ряд) |
| `bot/services/captcha/settings_service.py` | CaptchaSettings, get/update настроек |
| `bot/services/captcha/flow_service.py` | determine_captcha_mode, send_captcha, process_success/failure |
| `bot/services/captcha/dm_flow_service.py` | Логика ЛС капчи, deep links, Redis операции |

### Group Message Coordinator (ВАЖНО!)
| Файл | Назначение |
|------|------------|
| `bot/handlers/group_message_coordinator.py` | **ЕДИНАЯ ТОЧКА ВХОДА** для сообщений в группах |

**ВАЖНО:** ContentFilter и Antispam теперь вызываются через координатор, а НЕ напрямую.
Это решает проблему конфликта хендлеров в aiogram 3.x. Подробнее: `docs/ARCHITECTURE.md`

### Антиспам
| Файл | Назначение |
|------|------------|
| `bot/handlers/antispam_handlers/antispam_filter_handler.py` | Логика фильтрации (вызывается из координатора) |
| `bot/handlers/antispam_handlers/antispam_settings_handler.py` | UI настроек антиспам |
| `bot/services/antispam/antispam_service.py` | Проверка правил, применение действий |
| `bot/database/models_antispam.py` | Модели AntiSpamRule, AntiSpamWhitelist |

### Content Filter (Фильтр контента)
| Файл | Назначение |
|------|------------|
| `bot/handlers/content_filter/filter_handler.py` | Логика фильтрации (вызывается из координатора) |
| `bot/handlers/content_filter/settings_handler.py` | UI настроек фильтра |
| `bot/services/content_filter/text_normalizer.py` | Нормализация текста (l33tspeak → кириллица) |
| `bot/services/content_filter/word_filter.py` | Проверка на запрещённые слова |
| `bot/services/content_filter/filter_manager.py` | Координация всех фильтров |
| `bot/database/models_content_filter.py` | Модели FilterWord, ContentFilterSettings |

### Муты
| Файл | Назначение |
|------|------------|
| `bot/handlers/mute_by_reaction/mute_by_reaction_handler.py` | Мут по реакции на сообщение |
| `bot/handlers/bot_moderation_handlers/new_member_requested_to_join_mute_handlers.py` | Мут новых участников |
| `bot/services/risk_gate.py` | Оценка риска (фото, возраст аккаунта) |

### Настройки
| Файл | Назначение |
|------|------------|
| `bot/handlers/group_settings_handler/groups_settings_in_private_handler.py` | /settings в ЛС бота |
| `bot/services/groups_settings_in_private_logic.py` | Логика настроек, проверка прав |

---

## Key Patterns

### 1. aiogram 3.x Routers
```python
from aiogram import Router
router = Router()

@router.message(Command("start"))
async def handler(message: Message, session: AsyncSession):
    ...
```

### 2. SQLAlchemy Async Session
```python
from bot.database.session import get_session

async with get_session() as session:
    result = await session.execute(select(Model))
```

### 3. Redis Keys
```python
# Капча
f"captcha:{user_id}"
f"join_request:{user_id}:{group_id}"

# Кэш синхронизации
f"group_synced:{chat_id}"

# Антифлуд
f"invite_counter:{initiator_id}:{chat_id}"
```

### 4. Alembic Migrations (PostgreSQL)
```python
# Для ENUM используй postgresql.ENUM с create_type=False
from sqlalchemy.dialects import postgresql

rule_type_enum = postgresql.ENUM('A', 'B', name='my_enum', create_type=False)

# Создание enum идемпотентно:
connection.execute(sa.text("""
    DO $$ BEGIN
        CREATE TYPE my_enum AS ENUM ('A', 'B');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;
"""))
```

---

## ⛔ КРИТИЧЕСКИ ВАЖНО — НЕ МЕНЯТЬ ПОВЕДЕНИЕ БЕЗ СОГЛАСИЯ

**Этот косяк уже был — бот месяц отклонял заявки вместо того чтобы оставлять их висеть.
Пользователи терялись, админ заметил только через месяц. ЭТО НЕДОПУСТИМО!**

### ❌ ЗАПРЕЩЕНО:
- Добавлять функционал который НЕ просили
- Менять логику "потому что так лучше"
- Додумывать за пользователя
- "Улучшать" код попутно с основной задачей
- Менять поведение бота без явного согласия

### ✅ ОБЯЗАТЕЛЬНО:
- Делать РОВНО то что просят, не больше
- Если кажется что нужно изменить поведение — **СПРОСИТЬ СНАЧАЛА**
- Просят изменить текст — меняй **ТОЛЬКО** текст
- Просят исправить баг — исправляй **ТОЛЬКО** баг
- Перед изменением логики: "Сейчас будет сделано X, это ок?"

### Реальный пример косяка (ноябрь 2025):
```
Задача: исправить что-то в капче
Что сделал Claude: добавил auto-decline join requests при провале капчи
Результат: месяц бот отклонял заявки, пользователи терялись
Админ заметил: только через месяц, когда упала статистика
```

### Реальный пример косяка (январь 2026):
```
Задача: изменить кнопку "Назад" чтобы возвращала к вводу паттерна
Что сделал Claude: переделал весь флоу — убрал ввод веса, добавил кнопку подтверждения
Результат: сломал существующую логику ввода веса
Причина: "решил упростить", "додумал за пользователя"
```

### ⚠️ ПРАВИЛО: НЕ ДЕЛАТЬ "УЛУЧШЕНИЯ" ПО ХОДУ
- Пользователь просит изменить кнопку → меняй **ТОЛЬКО** кнопку
- Пользователь просит исправить текст → меняй **ТОЛЬКО** текст
- **НЕ** переделывать логику "заодно"
- **НЕ** упрощать/улучшать то, что не просили
- Перед изменением спроси себя: "Пользователь ЭТО просил?" — если нет, **НЕ ТРОГАЙ**

**НИКОГДА ТАК НЕ ДЕЛАТЬ!**

---

## Workflow

1. **Все изменения только локально** → git push → CI/CD деплоит на сервер
2. **НЕ делать изменения напрямую на сервере** (только читать логи)
3. **Проверять миграции локально** перед пушем: `alembic upgrade head`
4. **Тестировать изменения** перед коммитом
5. **НИКОГДА не использовать имя "Claude" в коммитах** - без Co-Authored-By, без упоминаний AI

---

## Server Commands (только для чтения логов)

```bash
# Логи бота
ssh root@88.210.35.183 "docker logs bot_prod --tail 100"

# Статус контейнеров
ssh root@88.210.35.183 "docker ps"

# Alembic версия на сервере
ssh root@88.210.35.183 "docker exec postgres_prod psql -U postgres -d bot_prod -c 'SELECT version_num FROM alembic_version;'"
```

---

## Large File Handling

Если файл превышает 20,000 токенов:
1. **НЕ пытаться** прочитать его целиком
2. Читать файл чанками по 10,000 токенов используя `offset`/`limit`
3. Или спросить пользователя нужно ли разбить файл на части
4. Никогда не падать с ошибкой "content exceeds maximum allowed tokens"

```python
# Пример: чтение большого файла чанками
Read(file_path="...", offset=0, limit=500)      # строки 1-500
Read(file_path="...", offset=500, limit=500)    # строки 501-1000
```

---

## Documentation Links

- **Правила разработки:** `docs/DEVELOPER_RULES.md` (ОБЯЗАТЕЛЬНО!)
- **E2E тесты с юзерботами:** `docs/E2E_USERBOT_TESTING.md` (ВАЖНО для тестов!)
- **Архитектура:** `docs/ARCHITECTURE.md`
- **База данных:** `docs/DATABASE.md`
- **Хендлеры:** `docs/HANDLERS.md`
- **Модули:** `docs/MODULES.md`
- **Использование:** `docs/USAGE.md`

---

*Последнее обновление: 2025-12-30* (Добавлено критическое правило — не менять поведение без согласия)