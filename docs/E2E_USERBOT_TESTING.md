# E2E Testing with Userbots (Pyrogram)

> **ВАЖНО:** Этот документ описывает правила написания e2e тестов с использованием Pyrogram юзерботов.
> Следуй этим правилам чтобы избежать типичных ошибок.

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

*Последнее обновление: 2025-12-26* (добавлены safe_str, callback patterns, FloodWait минимизация, bot fixture cleanup)
