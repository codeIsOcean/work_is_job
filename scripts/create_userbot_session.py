"""
Скрипт для создания Pyrogram session string.

Запуск:
    python scripts/create_userbot_session.py

После запуска:
1. Введи номер телефона (+44 73 4251 9594)
2. Telegram пришлёт код — введи его
3. Скрипт выведет SESSION_STRING — скопируй его в .env.test
"""

import asyncio
from pyrogram import Client

# API credentials из .env.test
API_ID = 33300908
API_HASH = "7eba0c742bb797bbf8ed977e686a8972"


async def main():
    print("=" * 50)
    print("Создание Pyrogram Session String")
    print("=" * 50)
    print()

    # Создаём клиент в памяти (без файла сессии)
    app = Client(
        name="test_userbot",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True  # Не создаёт файл .session
    )

    async with app:
        # Получаем session string
        session_string = await app.export_session_string()

        print()
        print("=" * 50)
        print("SESSION STRING (скопируй в .env.test):")
        print("=" * 50)
        print()
        print(f"TEST_USERBOT_SESSION={session_string}")
        print()
        print("=" * 50)

        # Проверяем что работает
        me = await app.get_me()
        print(f"Авторизован как: {me.first_name} (@{me.username})")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
