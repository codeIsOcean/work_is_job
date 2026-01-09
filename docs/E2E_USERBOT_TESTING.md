# E2E Testing with Userbots (Pyrogram)

> **ВАЖНО:** Этот документ описывает правила написания e2e тестов с использованием Pyrogram юзерботов.
> Следуй этим правилам чтобы избежать типичных ошибок.

---

## 🗄️ Тестовые базы данных

**⛔ КРИТИЧЕСКИ ВАЖНО:** Перед запуском тестов убедись что используешь правильную БД!

| Тип тестов | БД | Порт | Команда запуска |
|------------|-----|------|-----------------|
| Unit-тесты (pytest) | `postgres_unit_tests` | 5434 | `docker-compose -f docker-compose.test.yml up -d postgres_unit_tests` |
| E2E тесты | Используют `bot_test` | 5433 | Бот уже запущен с `postgres_test` |

**Запуск тестовой БД для pytest:**
```bash
docker-compose -f docker-compose.test.yml up -d postgres_unit_tests
```

> **Подробнее:** см. раздел 5.5 в `docs/DEVELOPER_RULES.md`

---

## ⛔ ГЛАВНОЕ ПРАВИЛО (MUST!!!) — ТЕСТИРОВАТЬ ЧЕРЕЗ UI

**E2E тесты ОБЯЗАНЫ проходить РЕАЛЬНЫЙ USER FLOW через UI бота!**

### ЗАПРЕЩЕНО:
- ❌ Создавать данные напрямую в БД, минуя UI
- ❌ Обходить handlers и вызывать сервисы напрямую
- ❌ "Короткий путь" — это НЕ тестирование!
- ❌ Тестировать только backend без проверки UI

### ОБЯЗАТЕЛЬНО:
- ✅ Юзербот отправляет команды боту (`/settings`)
- ✅ Юзербот нажимает кнопки (inline keyboards)
- ✅ Юзербот проходит весь flow как реальный пользователь
- ✅ Проверять что UI работает, а не только backend

### Пример НЕПРАВИЛЬНОГО теста:
```python
# ❌ ПЛОХО: обходим UI, создаём данные напрямую в БД
async def test_spam_detection():
    section_id = await service.create_section(chat_id, "Такси")  # БД напрямую!
    await service.add_pattern(section_id, "такси")  # БД напрямую!

    msg = await victim.send_message(chat_id, "такси недорого")
    # Backend работает, но UI не проверен — кнопок может не быть!
```

### Пример ПРАВИЛЬНОГО теста:
```python
# ✅ ХОРОШО: полный user flow через UI бота
async def test_spam_detection_via_ui():
    # 1. Админ открывает настройки через бота
    settings_msg = await admin.send_message(bot_id, "/settings")

    # 2. Админ нажимает кнопки в меню
    await settings_msg.click("Фильтр контента")
    await asyncio.sleep(1)
    await click_latest_button(admin, "Кастомные разделы")
    await click_latest_button(admin, "Создать раздел")

    # 3. Админ вводит название (FSM диалог)
    await admin.send_message(bot_id, "Такси")

    # 4. Админ добавляет паттерн через UI
    await click_latest_button(admin, "Добавить паттерн")
    await admin.send_message(bot_id, "такси недорого")

    # 5. Жертва отправляет спам в группу
    msg = await victim.send_message(chat_id, "Такси недорого по городу!")

    # 6. Проверяем результат — теперь проверен и UI и backend!
    await asyncio.sleep(3)
    assert not await check_message_exists(victim, chat_id, msg.id)
```

### Почему это критически важно:
| "Короткий путь" (БД напрямую) | Правильный путь (через UI) |
|-------------------------------|----------------------------|
| Backend работает | Backend работает |
| UI не проверен | UI проверен |
| Кнопки могут отсутствовать | Кнопки точно работают |
| Handlers не тестируются | Handlers тестируются |
| Баги в UI не найдены | Баги в UI найдены |
| Ложная уверенность | Реальная уверенность |

---

## Зачем юзерботы?

Юзерботы позволяют тестировать функции, недоступные через Bot API:
- Отправка реакций на сообщения
- Симуляция действий обычных пользователей
- Проверка ограничений (mute, ban) с точки зрения пользователя
- Тестирование join requests и капчи

---

## Критические правила

### 1. Загрузка .env.test ПЕРВЫМ

**Проблема:** `bot/config.py` загружает `.env.dev` при импорте. Если импортировать что-то из `bot/` до загрузки `.env.test`, переменные окружения будут неправильными.

**Решение:** Загружать `.env.test` В САМОМ НАЧАЛЕ файла, ДО любых импортов:

```python
# tests/e2e/test_example.py
import os
from pathlib import Path
from dotenv import load_dotenv

# КРИТИЧЕСКИ ВАЖНО: загружаем .env.test ДО ВСЕХ других импортов
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

# Теперь можно импортировать остальное
import asyncio
import pytest
from pyrogram import Client
from aiogram import Bot
# from bot.services.xxx import yyy  # Теперь безопасно
```

### 2. Fixtures в тестовом файле, НЕ в conftest.py

**Проблема:** Fixtures в `conftest.py` загружаются pytest'ом до выполнения кода в тестовом файле. Это приводит к конфликтам с загрузкой `.env.test`.

**Решение:** Определять fixtures прямо в тестовом файле:

```python
# Конфигурация - читаем ПОСЛЕ load_dotenv
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH")

USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "user1"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "user2"},
]

@pytest.fixture
async def userbot():
    """Первый юзербот."""
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="test_userbot_1",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()
```

### 3. Windows whitelist для e2e тестов

**Проблема:** `tests/conftest.py` содержит `pytest_collection_modifyitems` который пропускает e2e тесты на Windows, кроме файлов в whitelist.

**Решение:** Добавить новый тестовый файл в `allowed_on_windows`:

```python
# tests/conftest.py
def pytest_collection_modifyitems(config, items):
    if sys.platform.startswith("win"):
        # Файлы которые НЕ пропускаем на Windows
        allowed_on_windows = {
            "test_userbot_flows.py",
            "test_telegram_html.py",
            "test_mute_by_reaction_e2e.py",  # <-- Добавить сюда!
        }
```

### 4. Резолв chat_id через invite_link

**Проблема:** Pyrogram не может отправить сообщение по `chat_id` если чат не закэширован в сессии. Ошибка: `ValueError: Peer id invalid: -100xxx`

**Решение:** Использовать `invite_link` для резолва чата:

```python
async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Убедиться что юзербот в группе и Pyrogram знает о чате."""
    # Пытаемся войти по инвайт-ссылке
    if invite_link:
        try:
            await userbot.join_chat(invite_link)
        except UserAlreadyParticipant:
            pass

    # ОБЯЗАТЕЛЬНО: резолвим чат через invite_link чтобы закэшировать peer
    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)  # <-- Ключевой момент!
            print(f"Resolved chat: {chat.title}")
        else:
            await userbot.get_chat(chat_id)
    except Exception as e:
        print(f"get_chat error: {e}")
```

### 5. Windows encoding (эмодзи в print)

**Проблема:** Windows console использует cp1251 кодировку, которая не поддерживает эмодзи. `UnicodeEncodeError: 'charmap' codec can't encode character`

**Решение:** Использовать ASCII текст вместо эмодзи в print statements:

```python
# ПЛОХО - упадёт на Windows
print(f"[4] ✅ Message deleted")
print(f"[4] ❌ Message NOT deleted")

# ХОРОШО - работает везде
print(f"[4] OK: Message deleted")
print(f"[4] FAIL: Message NOT deleted")
```

### 6. Telegram FloodWait (rate limiting)

**Проблема:** Много тестов подряд → Telegram rate limiting → `FloodWait` exceptions

**Решение:**
- Запускать тесты по одному при отладке
- Добавлять `asyncio.sleep()` между операциями
- Использовать `pytest.skip()` при FloodWait вместо падения

```python
from pyrogram.errors import FloodWait

try:
    await userbot.send_reaction(chat_id, message_id, emoji="👍")
except FloodWait as e:
    pytest.skip(f"FloodWait: {e.value} seconds")
except Exception as e:
    print(f"[ERROR] Cannot send reaction: {e}")
    pytest.skip(f"Cannot send reaction: {e}")
```

---

## Шаблон e2e теста

```python
# tests/e2e/test_feature_e2e.py
"""
E2E тесты для [название функции].

Запуск:
    pytest tests/e2e/test_feature_e2e.py -v -s

Требования:
    - .env.test с TEST_USERBOT_SESSION, TEST_BOT_TOKEN, TEST_CHAT_ID
    - Тестовая группа где бот админ
    - Юзерботы должны быть участниками группы
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ПЕРВЫМ ДЕЛОМ загружаем .env.test
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from aiogram import Bot

# Конфигурация
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_CHAT_INVITE_LINK = os.getenv("TEST_CHAT_INVITE_LINK")
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH")

USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "user1"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "user2"},
]


def skip_if_no_credentials():
    """Пропуск теста если нет credentials."""
    if not TEST_BOT_TOKEN:
        pytest.skip("TEST_BOT_TOKEN not set")
    if not TEST_CHAT_ID:
        pytest.skip("TEST_CHAT_ID not set")
    if not any(s["session"] for s in USERBOT_SESSIONS):
        pytest.skip("No TEST_USERBOT_SESSION set")


def get_available_session(index: int = 0):
    """Получить доступную сессию юзербота."""
    available = [s for s in USERBOT_SESSIONS if s["session"]]
    return available[index] if index < len(available) else None


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def userbot():
    """Первый юзербот."""
    skip_if_no_credentials()
    session_info = get_available_session(0)
    if not session_info:
        pytest.skip("No userbot session available")
    client = Client(
        name="test_userbot_1",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def userbot2():
    """Второй юзербот."""
    skip_if_no_credentials()
    session_info = get_available_session(1)
    if not session_info:
        pytest.skip("Userbot 2 not available")
    client = Client(
        name="test_userbot_2",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=session_info["session"],
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def bot():
    """Aiogram Bot."""
    skip_if_no_credentials()
    bot_instance = Bot(token=TEST_BOT_TOKEN)
    yield bot_instance
    await bot_instance.session.close()


@pytest.fixture
def chat_id():
    return int(TEST_CHAT_ID)


@pytest.fixture
def invite_link():
    return TEST_CHAT_INVITE_LINK


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def ensure_user_in_chat(userbot: Client, chat_id: int, invite_link: str = None):
    """Убедиться что юзербот в группе."""
    if invite_link:
        try:
            await userbot.join_chat(invite_link)
            await asyncio.sleep(1)
        except UserAlreadyParticipant:
            pass
        except FloodWait as e:
            pytest.skip(f"FloodWait: {e.value} seconds")

    # Резолвим чат
    try:
        if invite_link:
            chat = await userbot.get_chat(invite_link)
            print(f"Resolved chat: {chat.title}")
    except Exception as e:
        print(f"get_chat error: {e}")


async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    """Размутить пользователя."""
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions={"can_send_messages": True}
        )
    except Exception:
        pass


# ============================================================
# TESTS
# ============================================================

class TestFeatureE2E:
    """E2E тесты для функции."""

    @pytest.mark.asyncio
    async def test_basic_flow(
        self, userbot: Client, userbot2: Client, bot: Bot, chat_id: int, invite_link: str
    ):
        """Базовый тест."""
        # Подготовка
        await ensure_user_in_chat(userbot, chat_id, invite_link=invite_link)
        await ensure_user_in_chat(userbot2, chat_id, invite_link=invite_link)

        me = await userbot.get_me()
        print(f"Testing with user: @{me.username}")

        # Тест
        msg = await userbot2.send_message(
            chat_id=chat_id,
            text=f"[TEST] {datetime.now().isoformat()}"
        )
        print(f"Sent message: {msg.id}")

        await asyncio.sleep(2)

        # Проверки
        # ...

        # Очистка
        try:
            await msg.delete()
        except Exception:
            pass
```

---

## Checklist для нового e2e теста

- [ ] `.env.test` загружается ПЕРВЫМ (до любых импортов из `bot/`)
- [ ] Fixtures определены в тестовом файле (не в conftest.py)
- [ ] Файл добавлен в `allowed_on_windows` в `tests/conftest.py`
- [ ] `ensure_user_in_chat` использует `invite_link` для резолва
- [ ] Print statements используют ASCII (без эмодзи)
- [ ] FloodWait обрабатывается через `pytest.skip()`
- [ ] Cleanup в конце каждого теста (удаление сообщений, unmute)

---

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `TEST_BOT_TOKEN not set` | `.env.test` не загружен | Загрузить `.env.test` первым |
| `ValueError: Peer id invalid` | Чат не закэширован в Pyrogram | Использовать `get_chat(invite_link)` |
| `UnicodeEncodeError: charmap` | Эмодзи в print на Windows | Использовать ASCII текст |
| `FloodWait: X seconds` | Rate limiting | Добавить delays, skip тест |
| Тест пропускается без причины | Не в whitelist Windows | Добавить в `allowed_on_windows` |
| Fixtures не находятся | conftest.py конфликт | Определить fixtures в файле |

---

---

## Дополнительные правила (2025-12)

### 7. Изолированные сессии БД (NullPool)

**Проблема:** E2E тесты используют другой event loop чем conftest.py fixtures. Shared database connections вызывают ошибки: `Event loop is closed`, `Future attached to a different loop`.

**Решение:** Создавать изолированные сессии с NullPool:

```python
async def get_test_session():
    """Создаёт свежую сессию БД для E2E тестов."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool

    # ВАЖНО: Хардкодим локальный адрес, НЕ используем DATABASE_URL из env!
    # Docker hostname (postgres_test) недоступен с хоста Windows
    database_url = "postgresql+asyncpg://user:pass@127.0.0.1:5433/dbname"

    engine = create_async_engine(database_url, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()
```

**Использование:**
```python
async def create_test_data():
    async for session in get_test_session():
        # работа с сессией
        await session.commit()
```

### 8. Cleanup в finally блоке

**Проблема:** Мут/бан остаётся между тестами если cleanup не выполнился.

**Решение:** Всегда unmute в finally:

```python
async def test_something(self, userbot, bot, chat_id):
    victim = await userbot.get_me()
    try:
        # тест который может замутить пользователя
        ...
    finally:
        # ВСЕГДА размучиваем в конце
        await unmute_user(bot, chat_id, victim.id)
```

### 9. Увеличенные задержки для webhook

**Проблема:** Webhook обрабатывает сообщения с задержкой 1-3 секунды.

**Решение:** После отправки сообщения ждать минимум 3 секунды:

```python
msg = await userbot.send_message(chat_id, text)
await asyncio.sleep(3)  # Ждём обработки webhook'ом
exists = await check_message_exists(userbot, chat_id, msg.id)
```

---

## FloodWait: причины и решения

### Почему возникает FloodWait?

Telegram лимитирует количество запросов от одного аккаунта. Юзерботы в тестах делают много действий за секунду:
- `join_chat` - тяжёлая операция
- `send_message` - лимит ~30 сообщений/минуту
- `get_chat_history` - лимитировано

Человек физически не может так быстро нажимать кнопки, поэтому не получает FloodWait.

### Решения FloodWait

#### 1. Задержки между операциями

```python
await userbot.join_chat(invite_link)
await asyncio.sleep(2)  # Пауза после join

await userbot.send_message(chat_id, text)
await asyncio.sleep(1)  # Пауза после отправки
```

#### 2. Ротация юзерботов

```python
USERBOT_SESSIONS = [
    {"session": os.getenv("TEST_USERBOT_SESSION"), "username": "user1"},
    {"session": os.getenv("TEST_USERBOT2_SESSION"), "username": "user2"},
    {"session": os.getenv("TEST_USERBOT3_SESSION"), "username": "user3"},
]

# Разные юзерботы для разных ролей
admin_userbot = get_available_session(0)
victim_userbot = get_available_session(1)
```

#### 3. Обработка FloodWait с продолжением (не skip)

```python
async def ensure_user_in_chat(userbot, chat_id, invite_link):
    try:
        await userbot.join_chat(invite_link)
    except UserAlreadyParticipant:
        pass
    except FloodWait as e:
        if e.value < 60:
            # Ждём если меньше минуты
            print(f"FloodWait {e.value}s - waiting...")
            await asyncio.sleep(e.value + 5)
        else:
            # Продолжаем без skip - возможно уже в чате
            print(f"FloodWait {e.value}s - continuing anyway")

    # Всё равно резолвим чат
    await userbot.get_chat(invite_link)
```

#### 4. Экспоненциальный backoff

```python
async def send_with_retry(userbot, chat_id, text, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await userbot.send_message(chat_id, text)
        except FloodWait as e:
            if attempt < max_retries - 1 and e.value < 30:
                wait_time = e.value + (attempt * 5)
                await asyncio.sleep(wait_time)
            else:
                raise
```

#### 5. Кэширование peer

```python
# В начале теста - один раз резолвим
chat = await userbot.get_chat(invite_link)

# Потом используем chat.id (уже закэширован)
await userbot.send_message(chat.id, text)
```

---

## Правила Unit тестов

### 1. Регистрация моделей в Base.metadata

**Проблема:** Таблицы не создаются если модели не импортированы.

**Решение:** В `tests/conftest.py` добавить импорты ВСЕХ моделей:

```python
# tests/conftest.py
from bot.database.models import Base

# Импортируем все модели чтобы они зарегистрировались
import bot.database.models_content_filter  # noqa: F401
import bot.database.models_antispam  # noqa: F401
import bot.database.mute_models  # noqa: F401
# Добавлять сюда новые модели!
```

### 2. CASCADE drop для PostgreSQL

**Проблема:** `Base.metadata.drop_all()` падает на foreign keys.

**Решение:** Использовать SQL с CASCADE:

```python
async with engine.begin() as conn:
    await conn.execute(text("""
        DO $$ DECLARE r RECORD;
        BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
        END $$;
    """))
    await conn.run_sync(Base.metadata.create_all)
```

### 3. Проверка полей модели в фикстурах

**Проблема:** Фикстура создаёт объект с несуществующим полем.

```python
# ПЛОХО - chat_type не существует в Group модели
Group(chat_id=-1000, title="Test", chat_type="supergroup")

# ХОРОШО - только существующие поля
Group(chat_id=-1000, title="Test")
```

**Решение:** Перед созданием фикстуры проверить модель:
```python
from bot.database.models import Group
print(Group.__table__.columns.keys())  # Список полей
```

---

## Расширенный Checklist

### Для e2e теста:
- [ ] `.env.test` загружается ПЕРВЫМ
- [ ] Fixtures определены в тестовом файле
- [ ] Файл добавлен в `allowed_on_windows`
- [ ] `ensure_user_in_chat` использует `invite_link`
- [ ] Print без эмодзи (ASCII only)
- [ ] `safe_str()` для печати текста кнопок/сообщений от Telegram
- [ ] FloodWait обрабатывается без pytest.skip()
- [ ] Cleanup в finally блоке (unmute, delete)
- [ ] `get_test_session()` с NullPool для DB
- [ ] Хардкод `127.0.0.1:5433` вместо DATABASE_URL
- [ ] `asyncio.sleep(3)` после отправки сообщения
- [ ] Проверены реальные callback patterns перед написанием assertions
- [ ] Bot fixture закрывает сессию в finally

### Для unit теста:
- [ ] Все модели импортированы в conftest.py
- [ ] CASCADE drop для PostgreSQL
- [ ] Проверены поля модели перед фикстурой
- [ ] Rollback в finally

---

## Дополнительные ошибки и решения

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Event loop is closed` | Shared DB connection | `get_test_session()` с NullPool |
| `socket.gaierror` hostname | Docker hostname в DATABASE_URL | Хардкодить `127.0.0.1:5433` |
| `DuplicateTableError` | Рассинхрон миграций | Пересобрать Docker образ |
| `chat_type` not found | Несуществующее поле | Проверить `Model.__table__.columns.keys()` |
| `ForeignKey violation` | drop_all без CASCADE | SQL с CASCADE |
| User still muted | Нет cleanup в finally | Добавить `unmute_user()` в finally |
| `UnicodeEncodeError` на button.text | Эмодзи в тексте кнопки | Использовать `safe_str(button.text)` |
| `AssertionError: cf:wfc: not found` | Неверный callback pattern | Проверить реальные patterns (правило 11) |
| `ResourceWarning: unclosed SSLSocket` | Сессия бота не закрыта | `await bot.session.close()` в finally |

---

### 10. safe_str() для Windows encoding (emoji в кнопках)

**Проблема:** Telegram кнопки содержат эмодзи (`✅`, `📝`, `🔒`). При печати в Windows console возникает `UnicodeEncodeError`.

**Решение:** Использовать функцию `safe_str()` для всех print с текстом кнопок:

```python
def safe_str(text: str) -> str:
    """Convert string to ASCII-safe version for Windows console."""
    if not text:
        return text
    return text.encode('ascii', 'replace').decode('ascii')

# Использование
for button in buttons:
    print(f"Button: {safe_str(button.text)}")  # Безопасно для Windows
```

**ВАЖНО:** Это отличается от правила 5 (ASCII в собственных print). Правило 10 применяется когда вы печатаете текст ОТ TELEGRAM (кнопки, сообщения бота), который содержит эмодзи.

### 11. Проверяйте реальные callback patterns перед написанием тестов

**Проблема:** Тесты падают потому что ожидаемые callback patterns (`cf:wfc:`, `cf:flr:`) отличаются от реальных (`cf:swl:`, `cf:fladv:`).

**Решение:** ПЕРЕД написанием теста запустите простой тест для проверки реальных patterns:

```python
async def test_check_real_patterns(self, admin: Client, bot_id: int):
    """Проверить реальные callback patterns в меню."""
    await admin.send_message(bot_id, "/settings")
    await asyncio.sleep(2)

    msg = await get_latest_bot_message(admin, bot_id)

    # Напечатать ВСЕ callback_data
    for row in msg.reply_markup.inline_keyboard:
        for button in row:
            print(f"Button: {safe_str(button.text)} -> {button.callback_data}")

    # Теперь вы знаете реальные patterns!
```

**Лучше потратить 5 минут на проверку patterns, чем 30 минут на отладку падающих тестов.**

### 12. Минимизация FloodWait между тестами

**Проблема:** Каждый тест делает `/settings` и навигацию → много запросов → FloodWait.

**Решение:**
1. Группируйте связанные тесты в один класс
2. Используйте `@pytest.mark.incremental` для последовательных тестов
3. Добавляйте задержки между тестами:

```python
class TestContentFilterUI:
    """Тесты UI фильтра контента."""

    async def test_01_main_menu(self, admin, bot_id):
        await admin.send_message(bot_id, "/settings")
        # ...
        await asyncio.sleep(2)  # Пауза перед следующим тестом

    async def test_02_word_filter_menu(self, admin, bot_id):
        # Продолжаем с предыдущего состояния
        await click_latest_button(admin, bot_id, "Запрещённые слова")
        # ...
```

### 13. Bot fixture: корректное закрытие сессии

**Проблема:** `ResourceWarning: unclosed <ssl.SSLSocket>` если сессия бота не закрыта.

**Решение:** Использовать `aiohttp_session=False` или закрывать явно:

```python
@pytest.fixture
async def bot():
    """Aiogram Bot fixture с корректным cleanup."""
    skip_if_no_credentials()
    bot_instance = Bot(token=TEST_BOT_TOKEN)
    try:
        yield bot_instance
    finally:
        # ВАЖНО: закрываем сессию!
        if bot_instance.session:
            await bot_instance.session.close()
```

---

---

## ⚠️ КРИТИЧЕСКИЕ ПРАВИЛА ПОЛНОТЫ ТЕСТИРОВАНИЯ (2025-12-26)

> **УРОК:** E2E тесты с неправильными паттернами и soft-failures дают ЛОЖНУЮ УВЕРЕННОСТЬ.
> Тесты прошли, но кнопки не работали в production!

### 14. СТРОГИЕ ASSERTIONS — НИКАКИХ SOFT-FAILURES!

**Проблема:** Тесты используют `print("WARN: ...")` и продолжают. Баг не обнаруживается.

```python
# ❌ ПЛОХО — soft failure, тест проходит даже если кнопка сломана
if not button_clicked:
    print("WARN: Button not found, continuing...")
    await click_by_text(...)  # fallback

# ✅ ХОРОШО — strict assertion, тест падает если что-то не так
button_clicked = await click_button(userbot, bot_chat_id, pattern)
assert button_clicked, f"FAIL: Button with pattern '{pattern}' not found! Available: {buttons}"
```

**Правило:** Каждое действие должно иметь ASSERTION. Если кнопка не найдена — тест ДОЛЖЕН УПАСТЬ.

### 15. ТОЧНОЕ СООТВЕТСТВИЕ CALLBACK PATTERNS

**Проблема:** Тест ожидает `cf:bsigw:{chat_id}:{signal}`, а хендлер использует `cf:bsigw:{signal}:{chat_id}`.

**Решение:** ПЕРЕД написанием теста выгрузи ВСЕ паттерны из хендлеров:

```bash
# Выгрузить все callback patterns из модуля
grep -rE "F\.data\.regexp\(r\"" bot/handlers/content_filter/ | grep -oE "r\"[^\"]+\""
```

**Пример маппинга (content_filter):**
```python
# Паттерн в хендлере → Пример callback_data
# ^cf:bsig:-?\d+$     → cf:bsig:-1001234567
# ^cf:bsigt:\w+:-?\d+$ → cf:bsigt:money_amount:-1001234567
# ^cf:bsigw:\w+:-?\d+$ → cf:bsigw:money_amount:-1001234567
# ^cf:bsigr:-?\d+$    → cf:bsigr:-1001234567

# ВАЖНО: signal_key ПЕРВЫМ, chat_id ПОСЛЕДНИМ!
```

### 16. ПРОВЕРКА ИЗМЕНЕНИЯ СОСТОЯНИЯ

**Проблема:** Тест кликает на toggle, но не проверяет что состояние изменилось.

```python
# ❌ ПЛОХО — кликнули и всё
await click_button(userbot, bot_id, "cf:bsigt:money_amount:-1000")
print("OK: Clicked toggle")

# ✅ ХОРОШО — проверяем что состояние изменилось
# Шаг 1: Запомнить состояние ДО
buttons_before = await list_buttons(userbot, bot_id)
status_before = get_toggle_status(buttons_before, "money_amount")  # ✅ или ❌

# Шаг 2: Кликнуть
await click_button(userbot, bot_id, f"cf:bsigt:money_amount:{chat_id}")
await asyncio.sleep(2)

# Шаг 3: Проверить состояние ПОСЛЕ
buttons_after = await list_buttons(userbot, bot_id)
status_after = get_toggle_status(buttons_after, "money_amount")

# Шаг 4: ASSERT что изменилось
assert status_before != status_after, f"Toggle did not change! Before: {status_before}, After: {status_after}"
```

### 17. ТЕСТИРОВАНИЕ ВСЕХ УРОВНЕЙ МЕНЮ

**Проблема:** Тесты проверяют только верхний уровень навигации. Глубокие меню не тестируются.

**Решение:** Для каждого модуля создать ПОЛНЫЙ ПУТЬ тестирования:

```
/settings
  └── Группа
      └── cf:m:{chat_id}  (Фильтр контента)
          ├── cf:t:sc:{chat_id} (Toggle Антискам)
          ├── cf:scs:{chat_id} (Настройки антискам)
          │   ├── cf:scact:{chat_id} (Действие)
          │   │   ├── cf:scact:delete:{chat_id}
          │   │   ├── cf:scact:mute:{chat_id}
          │   │   └── cf:scact:ban:{chat_id}
          │   ├── cf:bsig:{chat_id} (Базовые сигналы) ← БАГ БЫЛ ЗДЕСЬ!
          │   │   ├── cf:bsigt:{signal}:{chat_id} (Toggle сигнала)
          │   │   ├── cf:bsigw:{signal}:{chat_id} (Вес сигнала)
          │   │   └── cf:bsigr:{chat_id} (Сброс)
          │   ├── cf:scadv:{chat_id} (Дополнительно) ← И ЗДЕСЬ!
          │   │   ├── cf:scmt:{chat_id} (Текст мута)
          │   │   ├── cf:scbt:{chat_id} (Текст бана)
          │   │   └── cf:scnd:{chat_id} (Задержка уведомлений)
          │   └── cf:scp:{chat_id} (Паттерны)
          ...
```

**Каждый callback в дереве должен иметь тест!**

### 18. CROSS-REFERENCE: HANDLER ↔ TEST

**Правило:** Для каждого модуля создать таблицу соответствия:

```python
# tests/e2e/test_content_filter_comprehensive.py

HANDLER_TEST_MAPPING = {
    # Handler pattern              → Test method
    "cf:bsig:-?\\d+$":             "test_base_signals_menu_opens",
    "cf:bsigt:\\w+:-?\\d+$":       "test_base_signals_toggle",
    "cf:bsigw:\\w+:-?\\d+$":       "test_base_signals_weight_fsm",
    "cf:bsigr:-?\\d+$":            "test_base_signals_reset",
    "cf:scadv:-?\\d+$":            "test_scam_advanced_menu_opens",
    "cf:scmt:-?\\d+$":             "test_scam_mute_text_fsm",
    "cf:scbt:-?\\d+$":             "test_scam_ban_text_fsm",
    "cf:scnd:-?\\d+$":             "test_scam_notification_delay_menu",
    # ... ВСЕ паттерны!
}

def test_all_handlers_have_tests():
    """Мета-тест: проверяет что все хендлеры покрыты тестами."""
    for pattern, test_name in HANDLER_TEST_MAPPING.items():
        assert hasattr(TestContentFilterE2E, test_name), f"Missing test for {pattern}"
```

### 19. FSM FLOW — ПОЛНОЕ ТЕСТИРОВАНИЕ

**Проблема:** FSM тесты проверяют только happy path.

**Решение:** Для каждого FSM тестировать:
1. **Valid input** — правильный ввод обрабатывается
2. **Invalid input** — неправильный ввод отклоняется с сообщением об ошибке
3. **Cancel** — отмена возвращает в предыдущее меню
4. **State persistence** — состояние сохраняется в БД

```python
async def test_weight_fsm_complete(self, admin, bot_id, chat_id):
    """Полный тест FSM ввода веса."""
    # Navigate to weight input
    await navigate_to(admin, bot_id, f"cf:bsigw:money_amount:{chat_id}")
    await asyncio.sleep(2)

    # TEST 1: Invalid input (text)
    await admin.send_message(bot_id, "not_a_number")
    await asyncio.sleep(2)
    msg = await get_last_message(admin, bot_id)
    assert "положительное число" in msg.text.lower(), "Invalid input not rejected"

    # TEST 2: Invalid input (negative)
    await admin.send_message(bot_id, "-50")
    await asyncio.sleep(2)
    msg = await get_last_message(admin, bot_id)
    assert "положительное" in msg.text.lower(), "Negative input not rejected"

    # TEST 3: Valid input
    await admin.send_message(bot_id, "150")
    await asyncio.sleep(2)
    msg = await get_last_message(admin, bot_id)
    assert "установлен" in msg.text.lower() or "сохранён" in msg.text.lower()

    # TEST 4: Verify state persisted
    await navigate_to(admin, bot_id, f"cf:bsig:{chat_id}")
    await asyncio.sleep(2)
    buttons = await list_buttons(admin, bot_id)
    assert any("150" in str(b) or "(150)" in str(b) for b in buttons), "Weight not shown in menu"
```

### 20. ОБЯЗАТЕЛЬНЫЙ ЧЕКЛИСТ ПЕРЕД PR

Перед созданием PR с E2E тестами проверь:

- [ ] **Все callback patterns выгружены** из хендлеров (`grep -rE "F\.data\.regexp"`)
- [ ] **Patterns в тестах ТОЧНО совпадают** с хендлерами (порядок параметров!)
- [ ] **Каждый callback имеет тест** (таблица HANDLER_TEST_MAPPING)
- [ ] **Все assertions строгие** (assert, не print/warn)
- [ ] **Toggle тесты проверяют изменение состояния** (before != after)
- [ ] **FSM тесты покрывают все ветки** (valid, invalid, cancel)
- [ ] **Тесты запущены локально** и ВСЕ прошли
- [ ] **Тесты запущены с реальным ботом** (не только mock)

---

## Пример комплексного теста (Content Filter)

```python
class TestContentFilterComprehensive:
    """
    Комплексный тест Content Filter.

    Покрывает ВСЕ callbacks из:
    - bot/handlers/content_filter/scam/base_signals.py
    - bot/handlers/content_filter/scam/settings.py
    - bot/handlers/content_filter/scam/patterns.py
    """

    # Mapping всех patterns → тестов
    REQUIRED_TESTS = [
        ("cf:bsig:-?\\d+$", "test_01_base_signals_menu"),
        ("cf:bsigt:\\w+:-?\\d+$", "test_02_base_signals_toggle"),
        ("cf:bsigw:\\w+:-?\\d+$", "test_03_base_signals_weight"),
        ("cf:bsigr:-?\\d+$", "test_04_base_signals_reset"),
        ("cf:scadv:-?\\d+$", "test_05_scam_advanced_menu"),
        ("cf:scmt:-?\\d+$", "test_06_scam_mute_text"),
        ("cf:scbt:-?\\d+$", "test_07_scam_ban_text"),
        ("cf:scnd:-?\\d+$", "test_08_notification_delay"),
    ]

    @pytest.mark.asyncio
    async def test_00_verify_all_tests_exist(self):
        """Мета-тест: все хендлеры имеют тесты."""
        for pattern, test_name in self.REQUIRED_TESTS:
            assert hasattr(self, test_name), f"MISSING TEST: {test_name} for pattern {pattern}"

    @pytest.mark.asyncio
    async def test_01_base_signals_menu(self, admin, bot_id, chat_id):
        """Тест: меню базовых сигналов открывается."""
        # Navigate
        await navigate_to_content_filter(admin, bot_id, chat_id)
        await click_button(admin, bot_id, f"cf:scs:{chat_id}")  # Антискам
        await asyncio.sleep(2)

        # Click base signals
        clicked = await click_button(admin, bot_id, f"cf:bsig:{chat_id}")
        assert clicked, "Failed to click cf:bsig button"
        await asyncio.sleep(2)

        # VERIFY: Menu opened with signal buttons
        buttons = await list_buttons(admin, bot_id)
        signal_buttons = [b for b in buttons if "bsigt:" in str(b.callback_data)]
        assert len(signal_buttons) >= 5, f"Expected 5+ signal buttons, got {len(signal_buttons)}"

    @pytest.mark.asyncio
    async def test_02_base_signals_toggle(self, admin, bot_id, chat_id):
        """Тест: toggle сигнала меняет состояние."""
        await navigate_to_base_signals(admin, bot_id, chat_id)

        # Get status BEFORE
        buttons = await list_buttons(admin, bot_id)
        money_btn = find_button(buttons, "money")
        status_before = "✅" in money_btn.text

        # Toggle
        await click_button(admin, bot_id, f"cf:bsigt:money_amount:{chat_id}")
        await asyncio.sleep(2)

        # Get status AFTER
        buttons = await list_buttons(admin, bot_id)
        money_btn = find_button(buttons, "money")
        status_after = "✅" in money_btn.text

        # STRICT ASSERTION
        assert status_before != status_after, \
            f"Toggle FAILED! Before: {status_before}, After: {status_after}"
```

---

## ⚠️ КРИТИЧЕСКИЕ ПРАВИЛА ВЕРИФИКАЦИИ (2025-12-27)

> **УРОК:** Тесты показывали "24 passed", но кнопки не работали!
> Причина: тесты проверяли "бот ответил", но НЕ проверяли "ответ без ошибок".

### 21. МОНИТОРИНГ DOCKER ЛОГОВ ВО ВРЕМЯ ТЕСТОВ

**Проблема:** Тест кликает кнопку → бот отвечает → тест считает успехом.
Но в логах бота: `AttributeError: 'Service' object has no attribute 'method_name'`.

**Решение:** Запускать логи Docker ПАРАЛЛЕЛЬНО с тестами:

```bash
# Терминал 1: Логи бота (следим за ошибками в реальном времени)
docker logs -f bot_test 2>&1 | grep -E "ERROR|Exception|AttributeError|TypeError|KeyError"

# Терминал 2: Запуск тестов
pytest tests/e2e/test_module.py -v
```

**Автоматизация в тестах:**

```python
import subprocess
import threading

class TestWithLogMonitoring:
    """Тест с мониторингом логов."""

    @pytest.fixture(autouse=True)
    def monitor_logs(self):
        """Запускает мониторинг логов Docker перед каждым тестом."""
        self.errors_found = []

        def log_monitor():
            process = subprocess.Popen(
                ["docker", "logs", "-f", "bot_test"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            for line in process.stdout:
                if any(err in line for err in ["ERROR", "Exception", "AttributeError", "TypeError"]):
                    self.errors_found.append(line.strip())

        self.log_thread = threading.Thread(target=log_monitor, daemon=True)
        self.log_thread.start()

        yield

        # ПОСЛЕ теста проверяем что ошибок не было
        assert not self.errors_found, f"ERRORS in Docker logs:\n" + "\n".join(self.errors_found)
```

### 22. ПРОВЕРКА РЕАЛЬНОГО ОТВЕТА, А НЕ ФАКТА ОТВЕТА

**Проблема:**

```python
# ❌ ПЛОХО — проверяем только что бот ответил
await click_button(userbot, bot_id, f"cf:scpe:{chat_id}")
await asyncio.sleep(2)
msg = await get_last_message(userbot, bot_id)
assert msg is not None  # Бот ответил? ДА! Тест прошёл!
# Но ответ может быть "Произошла ошибка" или вообще старое сообщение!
```

**Решение:**

```python
# ✅ ХОРОШО — проверяем СОДЕРЖИМОЕ ответа
await click_button(userbot, bot_id, f"cf:scpe:{chat_id}")
await asyncio.sleep(2)
msg = await get_last_message(userbot, bot_id)

# 1. Проверяем что это НОВОЕ сообщение (не старое)
assert msg.date > test_start_time, "No new message received"

# 2. Проверяем что ответ НЕ содержит ошибку
assert "ошибка" not in msg.text.lower(), f"Error in response: {msg.text}"
assert "error" not in msg.text.lower(), f"Error in response: {msg.text}"

# 3. Проверяем ОЖИДАЕМОЕ содержимое
assert "экспорт" in msg.text.lower() or "паттерн" in msg.text.lower(), \
    f"Unexpected response: {msg.text[:100]}"
```

### 23. FAST ITERATION: VOLUME MOUNT ДЛЯ КОДА

**Проблема:** Каждое изменение кода требует `docker build` (30-60 секунд).

**Решение:** В `docker-compose.test.yml` добавлен volume mount:

```yaml
volumes:
  - ./bot:/app/bot:ro  # Код бота - изменения применяются после restart!
```

**Теперь workflow:**

```bash
# 1. Изменил код
# 2. Рестарт контейнера (2-3 секунды вместо 60)
docker-compose -f docker-compose.test.yml restart bot_test

# 3. Запуск теста
pytest tests/e2e/test_module.py -v
```

**ВАЖНО:** Volume mount НЕ затрагивает БД и Redis — группы НЕ отвалятся!

### 24. ЧЕКЛИСТ: ЧТО ПРОВЕРЯЕТ ТЕСТ

Для КАЖДОГО теста ответь на вопросы:

| Вопрос | ❌ Плохо | ✅ Хорошо |
|--------|----------|-----------|
| Кнопка нажалась? | `await click()` | `assert await click(), "Button not found"` |
| Бот ответил? | `msg = await get_msg()` | `assert msg.date > start, "No response"` |
| Ответ корректный? | (не проверяется) | `assert "ошибка" not in msg.text` |
| Состояние изменилось? | (не проверяется) | `assert before != after` |
| Логи без ошибок? | (не проверяется) | Мониторинг Docker logs |
| Данные в БД? | (не проверяется) | `assert await db.get(...) == expected` |

### 25. ОБНОВЛЁННЫЙ ЧЕКЛИСТ ПЕРЕД PR

- [ ] **Docker logs мониторились** во время тестов (правило 21)
- [ ] **Ответы проверены на содержимое**, не только факт (правило 22)
- [ ] **Volume mount настроен** для быстрой итерации (правило 23)
- [ ] Все callback patterns выгружены из хендлеров
- [ ] Patterns в тестах ТОЧНО совпадают с хендлерами
- [ ] Каждый callback имеет тест (HANDLER_TEST_MAPPING)
- [ ] Все assertions строгие (assert, не print/warn)
- [ ] Toggle тесты проверяют изменение состояния
- [ ] FSM тесты покрывают все ветки
- [ ] **Тесты запущены с мониторингом логов** — 0 ошибок в Docker logs

---

---

## ⛔ КРИТИЧЕСКОЕ ПРАВИЛО 26: ТЕСТИРОВАТЬ ВСЕ УРОВНИ МЕНЮ ВГЛУБЬ (2025-12-27)

> **УРОК:** Тесты проверяли "меню открылось, кнопки есть", но НЕ кликали на КАЖДУЮ кнопку.
> Результат: 14 тестов PASSED, но 3 кнопки упали с TypeError в production!

### Реальные примеры пропущенных багов:

| Проблема | Почему тесты не поймали |
|----------|-------------------------|
| `create_category_words_list_menu()` — TypeError: 4 args вместо 5 | Тесты не кликали на `cf:swl:`, `cf:hwl:`, `cf:owl:` (списки слов категории) |
| `cf:secimp` vs `cf:secpi` — handler не найден | Тесты не кликали на кнопку "📥 Импорт" в разделах |
| `base_signals_menu()` — frozen CallbackQuery | Тесты не кликали на toggle сигналов `cf:bsigt:` |

**Вывод:** Если тест проверяет только "открылось меню", он пропустит ВСЕ баги во вложенных кнопках!

### Проблема:

```python
# ❌ ПЛОХО — проверяем только первый уровень
async def test_word_filter_menu(self, admin, bot_id, chat_id):
    await click_button(admin, bot_id, f"cf:wfs:{chat_id}")  # Открыть меню
    buttons = await list_buttons(admin, bot_id)
    assert len(buttons) > 0  # Есть кнопки? Да! PASSED!
    # НО: кнопки cf:swl:, cf:hwl:, cf:owl: НЕ кликались!
```

### Решение — ОБЯЗАТЕЛЬНО кликать КАЖДУЮ кнопку:

```python
# ✅ ХОРОШО — проверяем ВСЕ кнопки вглубь
async def test_word_filter_menu_complete(self, admin, bot_id, chat_id):
    await click_button(admin, bot_id, f"cf:wfs:{chat_id}")
    await asyncio.sleep(2)

    # 1. Кликаем на КАЖДУЮ категорию
    for category in ["sw", "hw", "ow"]:
        clicked = await click_button(admin, bot_id, f"cf:{category}l:{chat_id}:0")
        assert clicked, f"Button cf:{category}l not found"

        # 2. Проверяем ответ без ошибок
        ok, text = await verify_no_error(admin, bot_id)
        assert ok, f"Error in {category} list: {text}"

        # 3. Возвращаемся назад
        await click_button(admin, bot_id, f"cf:wfs:{chat_id}")
        await asyncio.sleep(1)
```

### Правило:

**Если меню содержит N кнопок, тест должен кликнуть на ВСЕ N кнопок и проверить каждый ответ!**

| Что тест проверял | Что нужно проверять |
|-------------------|---------------------|
| "Меню открылось" | "Меню открылось + КАЖДАЯ кнопка работает" |
| 1 клик + assert buttons | N кликов + N assertions |
| Поверхностно | В глубину |

---

## ТИПЫ ТЕСТОВ: UI vs ЛОГИКА (РАЗДЕЛЕНИЕ)

### Два разных типа тестов:

| Тип | Что проверяет | Файл |
|-----|---------------|------|
| **E2E UI тесты** | Кнопки работают, FSM диалоги работают | `test_*_e2e.py` |
| **Тесты логики детекции** | Спам детектируется, легитимное НЕ блокируется | `test_*_detection_e2e.py` |

### E2E UI тест (кнопки):

```python
# tests/e2e/test_content_filter_ui_e2e.py
async def test_scam_patterns_menu_works(self, admin, bot_id):
    """Проверяет что UI меню паттернов работает."""
    await click_button(admin, bot_id, f"cf:scp:{chat_id}")
    # Проверяем что меню открылось без ошибок
```

### Тест логики детекции (ОТДЕЛЬНЫЙ ФАЙЛ):

```python
# tests/e2e/test_content_filter_detection_e2e.py
class TestSpamDetection:
    """Тесты ЛОГИКИ детекции спама - отправляем сообщения и проверяем действия."""

    async def test_spam_message_deleted(self, admin, victim, bot, chat_id):
        """Спам-сообщение должно быть удалено."""
        # 1. Админ настраивает фильтр через UI
        await navigate_to_scam_settings(admin, bot_id, chat_id)
        await enable_scam_detection(admin, bot_id, chat_id)

        # 2. Жертва отправляет СПАМ в группу
        spam_msg = await victim.send_message(
            chat_id,
            "Заработок 100к в день! Пиши в ЛС!"
        )
        await asyncio.sleep(5)  # Ждём обработки

        # 3. Проверяем что сообщение УДАЛЕНО
        exists = await check_message_exists(victim, chat_id, spam_msg.id)
        assert not exists, "SPAM message was NOT deleted!"

    async def test_legitimate_message_not_blocked(self, admin, victim, chat_id):
        """Легитимное сообщение НЕ должно блокироваться."""
        # 1. Жертва отправляет ЛЕГИТИМНОЕ сообщение
        normal_msg = await victim.send_message(chat_id, "Привет, как дела?")
        await asyncio.sleep(5)

        # 2. Проверяем что сообщение НЕ удалено
        exists = await check_message_exists(victim, chat_id, normal_msg.id)
        assert exists, "Legitimate message was DELETED by mistake!"

    async def test_word_filter_blocks_forbidden_word(self, admin, victim, chat_id):
        """Запрещённое слово должно блокироваться."""
        # 1. Админ добавляет слово через UI
        await add_word_via_ui(admin, bot_id, chat_id, category="sw", word="тестспам")

        # 2. Жертва отправляет сообщение с этим словом
        msg = await victim.send_message(chat_id, "Продаю тестспам дёшево!")
        await asyncio.sleep(5)

        # 3. Проверяем действие
        exists = await check_message_exists(victim, chat_id, msg.id)
        assert not exists, "Forbidden word was NOT filtered!"
```

### Checklist для полного тестирования модуля:

- [ ] **UI тесты** — каждая кнопка кликнута и проверена
- [ ] **FSM тесты** — каждый FSM диалог пройден (valid + invalid input)
- [ ] **Тесты логики** — спам блокируется, легитимное НЕ блокируется
- [ ] **Edge cases** — граничные случаи (пустые списки, максимальные значения)

---

---

## ⛔ КРИТИЧЕСКИЕ ПРАВИЛА НАПИСАНИЯ ТЕСТОВ (2025-12-27)

> **УРОК:** Тесты с `print()` вместо `assert` давали ложную уверенность.
> Тесты с `MagicMock` не тестировали реальную логику бота!

### 27. ASSERT ВМЕСТО PRINT — ВСЕГДА!

**Проблема:** Тесты используют `if/else` с `print()` вместо `assert`. Тест ВСЕГДА проходит!

```python
# ❌ ПЛОХО — тест НИКОГДА не упадёт
async def test_spam_deleted(self, userbot, chat_id):
    msg = await userbot.send_message(chat_id, "spam text")
    await asyncio.sleep(3)
    exists = await check_message_exists(userbot, chat_id, msg.id)

    if not exists:
        print("[OK] Message deleted!")
    else:
        print("[FAIL] Message NOT deleted")  # Тест пройдёт с FAIL в логах!
```

**Решение:**

```python
# ✅ ХОРОШО — тест упадёт если условие не выполнено
async def test_spam_deleted(self, userbot, chat_id):
    msg = await userbot.send_message(chat_id, "spam text")
    await asyncio.sleep(3)
    exists = await check_message_exists(userbot, chat_id, msg.id)

    assert not exists, "FAIL: Spam message was NOT deleted!"
    print("[OK] Message deleted!")  # Печатаем только при успехе
```

**Правило:** Каждая проверка = `assert`. `print()` — только для логирования ПОСЛЕ assert.

### 28. НЕ ИСПОЛЬЗОВАТЬ MagicMock В E2E ТЕСТАХ!

**Проблема:** Тесты в папке `tests/e2e/` используют `MagicMock` вместо реальных взаимодействий.

```python
# ❌ ПЛОХО — это НЕ E2E тест!
from unittest.mock import MagicMock, AsyncMock

async def test_antispam_blocks_links():
    message = MagicMock()
    message.text = "t.me/spam_channel"
    message.delete = AsyncMock()

    await antispam_filter(message)  # Вызываем напрямую
    message.delete.assert_called_once()  # Проверяем mock
```

**Что не так:**
- Mock не проверяет реальную логику бота
- Хендлеры не регистрируются в aiogram
- Middleware не применяется
- База данных не используется

**Решение — НАСТОЯЩИЙ E2E с юзерботами:**

```python
# ✅ ХОРОШО — реальный E2E тест
async def test_antispam_blocks_links(self, userbot, bot, chat_id):
    """Проверяем что бот РЕАЛЬНО удаляет ссылки."""
    # 1. Включаем антиспам через БД (setup)
    await enable_antispam_rule(chat_id, "telegram_links", action="delete")

    # 2. Юзербот отправляет сообщение со ссылкой
    msg = await userbot.send_message(chat_id, "Заходи t.me/spam_group")
    await asyncio.sleep(3)

    # 3. Проверяем что сообщение РЕАЛЬНО удалено
    exists = await check_message_exists(userbot, chat_id, msg.id)
    assert not exists, "FAIL: Link message was NOT deleted by bot!"
```

**Правило:** В папке `tests/e2e/` — ТОЛЬКО реальные юзерботы + реальный бот. Mock = unit тесты!

### 29. SRP — ОДИН ТЕСТ = ОДНА ПРОВЕРКА

**Проблема:** Тест проверяет 5 вещей сразу. При падении непонятно что сломалось.

```python
# ❌ ПЛОХО — слишком много в одном тесте
async def test_antispam_full_flow():
    # Проверка 1: telegram links
    # Проверка 2: external links
    # Проверка 3: whitelist
    # Проверка 4: mute action
    # Проверка 5: delete action
    # 200 строк кода...
```

**Решение — Single Responsibility Principle:**

```python
# ✅ ХОРОШО — каждый тест проверяет ОДНО
class TestAntispamTelegramLinks:
    async def test_telegram_link_detected_and_deleted(self):
        """Telegram ссылка детектируется и удаляется."""
        ...

    async def test_telegram_link_whitelisted_allowed(self):
        """Ссылка из whitelist НЕ удаляется."""
        ...

    async def test_clean_text_allowed(self):
        """Текст без ссылок НЕ блокируется."""
        ...

class TestAntispamMuteAction:
    async def test_telegram_link_triggers_mute(self):
        """При action=mute пользователь мутится."""
        ...
```

**Преимущества SRP:**
- При падении сразу видно ЧТО сломалось
- Легче дебажить
- Легче понять что тестирует тест
- Можно запускать тесты по одному

### 30. HELPER-ФУНКЦИИ ДЛЯ ПОВТОРЯЮЩИХСЯ ДЕЙСТВИЙ

**Проблема:** Каждый тест копипастит 20 строк навигации.

```python
# ❌ ПЛОХО — дублирование кода
async def test_1():
    await admin.send_message(bot_id, "/settings")
    await asyncio.sleep(2)
    await click_button(admin, bot_id, "Фильтр контента")
    await asyncio.sleep(2)
    await click_button(admin, bot_id, "Антискам")
    await asyncio.sleep(2)
    await click_button(admin, bot_id, "Паттерны")
    # ... и так в каждом тесте
```

**Решение — helper-функции в начале файла:**

```python
# ✅ ХОРОШО — переиспользуемые helpers
# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def navigate_to_patterns_menu(userbot, bot_chat_id, chat_id) -> bool:
    """Navigate: /settings -> Группа -> Фильтр контента -> Антискам -> Паттерны."""
    await userbot.send_message(bot_chat_id, "/settings")
    await asyncio.sleep(2)

    clicked = await click_button_by_callback(userbot, bot_chat_id, f"gs:{chat_id}")
    if not clicked:
        return False
    await asyncio.sleep(1)

    clicked = await click_button_by_callback(userbot, bot_chat_id, f"cf:m:{chat_id}")
    if not clicked:
        return False
    # ...
    return True


async def add_test_pattern(userbot, bot_chat_id, chat_id, pattern_text=None) -> str:
    """Добавить тестовый паттерн через UI. Возвращает текст паттерна."""
    await navigate_to_patterns_menu(userbot, bot_chat_id, chat_id)
    await click_button_by_callback(userbot, bot_chat_id, f"cf:scpn:{chat_id}")

    pattern = pattern_text or f"test_pattern_{int(time.time())}"
    await userbot.send_message(bot_chat_id, pattern)
    return pattern


# Теперь тесты короткие и понятные
async def test_add_pattern(self, userbot, bot_chat_id, chat_id):
    pattern = await add_test_pattern(userbot, bot_chat_id, chat_id, "спам слово")
    assert await verify_message_contains(userbot, bot_chat_id, pattern)
```

### 31. SETUP ЧЕРЕЗ БД — КОГДА ДОПУСТИМО

**Главное правило:** UI тесты через UI, но для SETUP логики можно использовать БД напрямую.

```python
# ✅ ДОПУСТИМО — setup через БД для тестов ЛОГИКИ детекции
async def enable_antispam_telegram_links(chat_id: int, action: str = "delete"):
    """Включить правило антиспама для telegram ссылок (через БД)."""
    async for session in get_test_session():
        from bot.database.models_antispam import AntiSpamRule

        rule = await session.execute(
            select(AntiSpamRule).where(
                AntiSpamRule.chat_id == chat_id,
                AntiSpamRule.rule_type == AntiSpamRuleType.TELEGRAM_LINKS
            )
        )
        rule = rule.scalar_one_or_none()

        if rule:
            rule.is_enabled = True
            rule.action = action
        else:
            rule = AntiSpamRule(
                chat_id=chat_id,
                rule_type=AntiSpamRuleType.TELEGRAM_LINKS,
                is_enabled=True,
                action=action
            )
            session.add(rule)

        await session.commit()


# Использование в тесте логики детекции
async def test_telegram_link_detected(self, userbot, chat_id):
    """Тест ЛОГИКИ: telegram ссылка удаляется."""
    # SETUP через БД — это БЫСТРЕЕ и не зависит от UI
    await enable_antispam_telegram_links(chat_id, action="delete")

    # ДЕЙСТВИЕ — реальное сообщение через юзербота
    msg = await userbot.send_message(chat_id, "t.me/spam_channel")
    await asyncio.sleep(3)

    # ПРОВЕРКА — реальная проверка существования
    assert not await check_message_exists(userbot, chat_id, msg.id)
```

**Когда использовать БД напрямую:**
| Сценарий | БД | UI |
|----------|----|----|
| Тест UI меню настроек | ❌ | ✅ |
| Тест FSM диалогов | ❌ | ✅ |
| Тест детекции спама (нужен быстрый setup) | ✅ | ❌ |
| Тест whitelist/blacklist логики | ✅ | ❌ |
| Интеграционный тест полного flow | ✅ setup | ✅ действия |

### 32. CLEANUP — ВСЕГДА ВОССТАНАВЛИВАТЬ ИСХОДНОЕ СОСТОЯНИЕ

**Проблема:** Тест изменил настройки, следующий тест упал из-за этого.

```python
# ❌ ПЛОХО — нет cleanup
async def test_enable_antispam():
    await enable_antispam_rule(chat_id, "telegram_links")
    # ... тест ...
    # Правило осталось включённым! Следующие тесты могут упасть
```

**Решение — finally блок:**

```python
# ✅ ХОРОШО — cleanup в finally
async def test_enable_antispam(self, userbot, chat_id):
    try:
        # SETUP
        await enable_antispam_telegram_links(chat_id, action="delete")

        # TEST
        msg = await userbot.send_message(chat_id, "t.me/spam")
        await asyncio.sleep(3)
        assert not await check_message_exists(userbot, chat_id, msg.id)

    finally:
        # CLEANUP — ВСЕГДА выполнится
        await disable_antispam_telegram_links(chat_id)
        await clear_whitelist(chat_id)
```

---

## Полный пример правильного E2E теста (2025-12-27)

```python
"""
E2E тесты для Antispam модуля.

Запуск: pytest tests/e2e/test_antispam_flow.py -v -s

ВАЖНО: Это РЕАЛЬНЫЕ E2E тесты с юзерботами, НЕ unit тесты с MagicMock!
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# КРИТИЧЕСКИ ВАЖНО: загружаем .env.test ДО ВСЕХ других импортов
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import asyncio
import pytest
from datetime import datetime
from pyrogram import Client
from aiogram import Bot
from sqlalchemy import select

# ============================================================
# CONFIGURATION
# ============================================================

TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = int(os.getenv("TEST_CHAT_ID", "0"))
PYROGRAM_API_ID = os.getenv("PYROGRAM_API_ID")
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH")
TEST_USERBOT_SESSION = os.getenv("TEST_USERBOT_SESSION")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def get_test_session():
    """Изолированная сессия БД для E2E тестов."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool

    database_url = "postgresql+asyncpg://user:pass@127.0.0.1:5433/db"
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def enable_antispam_telegram_links(chat_id: int, action: str = "delete"):
    """Включить правило антиспама через БД."""
    async for session in get_test_session():
        from bot.database.models_antispam import AntiSpamRule, AntiSpamRuleType

        rule = await session.execute(
            select(AntiSpamRule).where(
                AntiSpamRule.chat_id == chat_id,
                AntiSpamRule.rule_type == AntiSpamRuleType.TELEGRAM_LINKS
            )
        )
        rule = rule.scalar_one_or_none()

        if rule:
            rule.is_enabled = True
            rule.action = action
        else:
            rule = AntiSpamRule(
                chat_id=chat_id,
                rule_type=AntiSpamRuleType.TELEGRAM_LINKS,
                is_enabled=True,
                action=action
            )
            session.add(rule)

        await session.commit()


async def disable_antispam_telegram_links(chat_id: int):
    """Отключить правило антиспама."""
    async for session in get_test_session():
        from bot.database.models_antispam import AntiSpamRule, AntiSpamRuleType

        result = await session.execute(
            select(AntiSpamRule).where(
                AntiSpamRule.chat_id == chat_id,
                AntiSpamRule.rule_type == AntiSpamRuleType.TELEGRAM_LINKS
            )
        )
        rule = result.scalar_one_or_none()
        if rule:
            rule.is_enabled = False
            await session.commit()


async def check_message_exists(client: Client, chat_id: int, message_id: int) -> bool:
    """Проверить существует ли сообщение."""
    try:
        messages = await client.get_messages(chat_id, message_id)
        return messages and not messages.empty
    except Exception:
        return False


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
async def userbot():
    """Pyrogram юзербот."""
    if not TEST_USERBOT_SESSION:
        pytest.skip("No userbot session")

    client = Client(
        name="test_userbot",
        api_id=int(PYROGRAM_API_ID),
        api_hash=PYROGRAM_API_HASH,
        session_string=TEST_USERBOT_SESSION,
        in_memory=True
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
async def bot():
    """Aiogram Bot."""
    bot_instance = Bot(token=TEST_BOT_TOKEN)
    try:
        yield bot_instance
    finally:
        await bot_instance.session.close()


@pytest.fixture
def chat_id():
    return TEST_CHAT_ID


# ============================================================
# TESTS — SRP: один тест = одна проверка
# ============================================================

class TestAntispamTelegramLinks:
    """Тесты детекции telegram ссылок."""

    @pytest.mark.asyncio
    async def test_telegram_link_detected_and_deleted(self, userbot, chat_id):
        """Telegram ссылка должна быть удалена."""
        try:
            # SETUP
            await enable_antispam_telegram_links(chat_id, action="delete")

            # ACTION
            msg = await userbot.send_message(
                chat_id,
                f"[TEST] Check spam link t.me/test_spam_{datetime.now().timestamp()}"
            )
            await asyncio.sleep(4)

            # ASSERT — строгая проверка!
            exists = await check_message_exists(userbot, chat_id, msg.id)
            assert not exists, "FAIL: Telegram link message was NOT deleted!"
            print("[OK] Telegram link message was deleted by antispam")

        finally:
            # CLEANUP
            await disable_antispam_telegram_links(chat_id)

    @pytest.mark.asyncio
    async def test_clean_text_allowed(self, userbot, chat_id):
        """Текст без ссылок НЕ должен блокироваться."""
        try:
            await enable_antispam_telegram_links(chat_id, action="delete")

            msg = await userbot.send_message(
                chat_id,
                f"[TEST] Clean text without links {datetime.now().timestamp()}"
            )
            await asyncio.sleep(4)

            # ASSERT — сообщение должно остаться
            exists = await check_message_exists(userbot, chat_id, msg.id)
            assert exists, "FAIL: Clean message was deleted by mistake!"
            print("[OK] Clean text was NOT deleted")

            # Cleanup сообщения
            try:
                await msg.delete()
            except Exception:
                pass

        finally:
            await disable_antispam_telegram_links(chat_id)
```

---

### 33. ТЕСТИРОВАТЬ ПРИМЕНЕНИЕ НАСТРОЕК, НЕ ТОЛЬКО UI!

**Проблема:** Тесты проверяют только что UI работает (кнопки нажимаются, настройки сохраняются), но НЕ проверяют что настройки РЕАЛЬНО применяются при срабатывании бота.

**Пример бага:** Админ устанавливает кастомный текст мута "Замучен за скам!", но бот продолжает использовать стандартный текст "🔇 получил мут на 24ч". UI тест проходит, баг не обнаружен!

```python
# ❌ ПЛОХО — тест проверяет только UI, НЕ применение!
async def test_custom_mute_text():
    # Админ открывает настройки
    await admin.send_message(bot_id, "/settings")
    await click_button(admin, "Антискам")
    await click_button(admin, "Текст мута")

    # Админ вводит кастомный текст
    await admin.send_message(bot_id, "Замучен за скам!")

    # ❌ Проверяем только что текст сохранился в UI
    msg = await get_last_message(admin, bot_id)
    assert "Замучен за скам" in msg.text  # UI показывает текст

    # НО! Мы НЕ проверили что бот РЕАЛЬНО использует этот текст при муте!
```

**Решение — два типа тестов:**

1. **UI тесты** — проверяют навигацию, кнопки, FSM диалоги
2. **Тесты применения** — проверяют что настройки РЕАЛЬНО работают

```python
# ✅ ХОРОШО — тест проверяет ПРИМЕНЕНИЕ настроек

class TestScamSettingsApplied:
    """Тесты ПРИМЕНЕНИЯ настроек антискама."""

    @pytest.mark.asyncio
    async def test_custom_mute_text_applied(self, admin_userbot, bot, chat_id):
        """Кастомный текст мута РЕАЛЬНО применяется при срабатывании."""
        custom_text = "ТЕСТ: %user% замучен за скам!"

        try:
            # SETUP: настраиваем через БД (допустимо для тестов логики!)
            await setup_scam_settings_for_test(
                chat_id=chat_id,
                action="mute",
                mute_duration=1,
                mute_text=custom_text
            )

            # ACTION: юзербот отправляет скам (вызывает срабатывание)
            await admin_userbot.send_message(
                chat_id,
                "Зарабатывай 5000$ в неделю! @scammer"
            )
            await asyncio.sleep(5)

            # VERIFY: бот использует КАСТОМНЫЙ текст, а не стандартный!
            found_custom = False
            async for msg in admin_userbot.get_chat_history(chat_id, limit=5):
                if msg.from_user and msg.from_user.is_bot:
                    if "ТЕСТ:" in msg.text and "замучен за скам" in msg.text:
                        found_custom = True
                        break

            assert found_custom, \
                "FAIL: Бот использовал стандартный текст вместо кастомного!"

        finally:
            await cleanup_scam_settings(chat_id)
            await unmute_user(bot, chat_id, user_id)
```

**Когда нужны тесты применения:**

| Настройка | Нужен тест применения? |
|-----------|------------------------|
| Кастомный текст мута | ✅ ДА — проверить что текст реально используется |
| Время мута | ✅ ДА — проверить что время в уведомлении правильное |
| Действие (delete/mute/ban) | ✅ ДА — проверить что действие реально выполняется |
| Задержка уведомления | ✅ ДА — проверить автоудаление |
| Навигация UI | ❌ НЕТ — достаточно UI теста |
| Сохранение в БД | ❌ НЕТ — покрыто UI тестом |

### 34. РАЗДЕЛЯТЬ UI ТЕСТЫ И ТЕСТЫ ЛОГИКИ

**Структура тестового файла:**

```python
# ============================================================
# UI ТЕСТЫ — проверяют навигацию и FSM
# ============================================================

class TestScamSettingsUI:
    """UI тесты настроек антискама."""

    async def test_scam_settings_menu(self):
        """UI: меню настроек открывается."""
        ...

    async def test_scam_mute_text_fsm(self):
        """UI: FSM ввода текста работает."""
        ...


# ============================================================
# ТЕСТЫ ПРИМЕНЕНИЯ — проверяют реальную работу
# ============================================================

class TestScamSettingsApplied:
    """Тесты ПРИМЕНЕНИЯ настроек (логика)."""

    async def test_custom_mute_text_applied(self):
        """ЛОГИКА: кастомный текст реально используется."""
        ...

    async def test_custom_mute_duration_applied(self):
        """ЛОГИКА: время мута реально применяется."""
        ...
```

**Правило:** Если настройка влияет на ПОВЕДЕНИЕ бота (текст, время, действие), обязательно добавь тест применения!

---

---

## ⛔ КРИТИЧЕСКИЕ ПРАВИЛА ИЗ SCAM MEDIA ТЕСТОВ (2025-12-28)

> **УРОК:** При написании E2E тестов для ScamMedia модуля было допущено несколько критических ошибок.
> Эти правила предотвращают повторение подобных проблем.

### 35. ALEMBIC МИГРАЦИИ — УНИКАЛЬНЫЕ REVISION ID!

**Проблема:** Два файла миграций имели одинаковый `revision = "a1b2c3d4e5f6"`. Alembic создал цикл ревизий, бот не запускался.

**Решение:**

```python
# ❌ ПЛОХО — копипаста revision из другого файла
# alembic/versions/a1b2c3d4e5f6_add_antispam_tables.py
revision = "a1b2c3d4e5f6"

# alembic/versions/a1b2c3d4e5f6_add_scam_media_tables.py  # ДРУГОЙ ФАЙЛ!
revision = "a1b2c3d4e5f6"  # ТОТ ЖЕ ID! → ЦИКЛ!

# ✅ ХОРОШО — уникальный ID для каждой миграции
# alembic/versions/a1b2c3d4e5f6_add_antispam_tables.py
revision = "a1b2c3d4e5f6"

# alembic/versions/sm01a2b3c4d5_add_scam_media_tables.py
revision = "sm01a2b3c4d5"  # Уникальный ID с префиксом модуля
```

**Рекомендация:** Использовать префикс модуля в revision ID: `sm01...` для scam_media, `as01...` для antispam, и т.д.

### 36. DATABASE URL ДЛЯ E2E — ВСЕГДА 127.0.0.1 + ПОРТ!

**Проблема:** E2E тесты запускаются на хост-машине, но используют Docker-internal hostname `postgres_test:5432`.

```python
# ❌ ПЛОХО — Docker hostname недоступен с хоста
database_url = os.getenv("DATABASE_URL")
# → "postgresql+asyncpg://...@postgres_test:5432/..."
# → socket.gaierror: Name or service not known

# ✅ ХОРОШО — хардкодим проброшенный порт
host = os.getenv("POSTGRES_HOST", "127.0.0.1")
port = os.getenv("POSTGRES_PORT", "5433")  # Проброшен из Docker!
database_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
```

**Правило:** В E2E тестах ВСЕГДА использовать `127.0.0.1` + проброшенный порт (5433), а НЕ переменную DATABASE_URL.

### 37. FLOODWAIT — ЖДАТЬ, НЕ ПРОПУСКАТЬ!

**Проблема:** При FloodWait тест делал `pytest.skip()`, пропуская важные проверки.

```python
# ❌ ПЛОХО — тест пропускается, баги не найдены
except FloodWait as e:
    pytest.skip(f"FloodWait: {e.value}s")

# ✅ ХОРОШО — ждём и повторяем попытку
except FloodWait as e:
    wait_time = e.value + 5  # +5 секунд запаса
    print(f"[FloodWait] Waiting {wait_time} seconds...")
    await asyncio.sleep(wait_time)
    # Повторяем попытку
    try:
        await userbot.join_chat(invite_link)
    except UserAlreadyParticipant:
        pass
```

**Правило:** `pytest.skip()` только если FloodWait > 60 секунд. Иначе — ждать и повторять.

### 38. API СЕРВИСОВ — ПРОВЕРЯТЬ СИГНАТУРУ МЕТОДА!

**Проблема:** Тест вызывал несуществующий статический метод `HashService.compute_phash()`.

```python
# ❌ ПЛОХО — метод не существует!
phash = HashService.compute_phash(image_bytes)
# → AttributeError: type object 'HashService' has no attribute 'compute_phash'

# ✅ ХОРОШО — проверить реальный API сервиса
from bot.services.scam_media import HashService
service = HashService()  # Создаём экземпляр
result = service.compute_hash(image_bytes)  # Вызываем метод экземпляра
phash, dhash = result.phash, result.dhash  # Получаем результат
```

**Правило:** ПЕРЕД написанием теста открыть файл сервиса и проверить:
1. Это статический метод или метод экземпляра?
2. Какие аргументы принимает?
3. Что возвращает?

### 39. ТЕСТОВЫЕ ДАННЫЕ — ИСПОЛЬЗОВАТЬ РЕАЛЬНЫЕ!

**Проблема:** Тесты генерировали синтетические изображения вместо реальных скам-фото.

```python
# ❌ ПЛОХО — синтетические данные
from PIL import Image
test_image = Image.new('RGB', (100, 100), color='red')

# ✅ ХОРОШО — реальные скам-изображения из docs/
SCAM_IMAGES_DIR = Path(__file__).parent.parent.parent / "docs" / "image_filter"
SCAM_IMAGES = {
    "vip_kazashki": SCAM_IMAGES_DIR / "scam_vip_kazashki.jpg",
    "narcotics": SCAM_IMAGES_DIR / "scam_narcotics.jpg",
    "tiktok": SCAM_IMAGES_DIR / "scam_tiktok.jpg",
}

# В тесте
scam_image_path = SCAM_IMAGES["vip_kazashki"]
assert scam_image_path.exists(), f"Scam image not found: {scam_image_path}"
```

**Правило:** Для тестов детекции (спам, скам-фото, запрещённые слова) ВСЕГДА использовать реальные примеры из production.

### 40. TELEGRAM API — ПРОВЕРКА МУТА ЧЕРЕЗ can_send_messages!

**Проблема:** Проверка `member.status == "restricted"` возвращает `True` даже после unmute!

```python
# ❌ ПЛОХО — status "restricted" сохраняется после unmute!
member = await bot.get_chat_member(chat_id, user_id)
is_muted = member.status == "restricted"
# → Всегда True если пользователь хоть раз был ограничен!

# ✅ ХОРОШО — проверяем реальную возможность писать
member = await bot.get_chat_member(chat_id, user_id)
can_send = True
if hasattr(member, 'can_send_messages'):
    can_send = member.can_send_messages if member.can_send_messages is not None else True

is_muted = not can_send  # True только если НЕ МОЖЕТ писать
```

**Объяснение:** Telegram сохраняет `status = "restricted"` даже когда все права выданы. Это особенность API. Проверять нужно конкретные права (`can_send_messages`), а не статус.

### 41. ИЗОЛЯЦИЯ ТЕСТОВ — ДВОЙНОЙ UNMUTE + ПРОВЕРКА!

**Проблема:** Жертва оставалась замученной от предыдущего теста, следующий тест падал.

```python
# ❌ ПЛОХО — один unmute может не сработать
await unmute_user(bot, chat_id, victim.id)
# → Пользователь всё ещё замучен!

# ✅ ХОРОШО — двойной unmute с задержками + проверка
await unmute_user(bot, chat_id, victim.id)
await asyncio.sleep(2)
await unmute_user(bot, chat_id, victim.id)  # Второй раз для надёжности
await asyncio.sleep(2)

# ОБЯЗАТЕЛЬНО: проверка перед тестом
initial_state = await get_user_restrictions(bot, chat_id, victim.id)
assert not initial_state.get("is_restricted"), \
    f"SETUP FAIL: Victim still muted! State: {initial_state}"
```

**Правило:** В тестах где проверяется мут/unmute:
1. Двойной unmute с задержками
2. Assert перед тестом что пользователь НЕ замучен
3. Cleanup в finally блоке

---

## Обновлённый Checklist (2025-12-28)

### Для E2E теста:
- [ ] `.env.test` загружается ПЕРВЫМ
- [ ] Fixtures определены в тестовом файле
- [ ] Файл добавлен в `allowed_on_windows`
- [ ] **Database URL хардкодит 127.0.0.1:5433** (правило 36)
- [ ] `ensure_user_in_chat` использует `invite_link`
- [ ] Print без эмодзи (ASCII only)
- [ ] **FloodWait — ждать, не skip** (правило 37)
- [ ] **API сервисов проверен перед использованием** (правило 38)
- [ ] **Реальные тестовые данные** (правило 39)
- [ ] **Проверка мута через can_send_messages** (правило 40)
- [ ] **Двойной unmute + assert перед тестом** (правило 41)
- [ ] Cleanup в finally блоке

### Для Alembic миграций:
- [ ] **Revision ID уникален** (правило 35)
- [ ] Revision ID имеет префикс модуля (sm01, as01, cf01)
- [ ] down_revision указывает на правильную предыдущую миграцию

---

*Последнее обновление: 2025-12-28* (добавлены правила 35-41: Alembic ID, database URL, FloodWait, API сигнатуры, реальные данные, проверка мута, изоляция тестов)
