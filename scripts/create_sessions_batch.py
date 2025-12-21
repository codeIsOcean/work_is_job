#!/usr/bin/env python3
"""
Создание session strings для нескольких юзерботов.

Запуск:
    python scripts/create_sessions_batch.py

После создания всех сессий, добавьте их в .env.test
"""

import asyncio
from pyrogram import Client

API_ID = 33300908
API_HASH = "7eba0c742bb797bbf8ed977e686a8972"

# Аккаунты для создания сессий
ACCOUNTS = [
    {
        "name": "userbot2",
        "phone": "+447342439392",
        "password": "7777",
        "username": "s1adkaya2292",
    },
    {
        "name": "userbot3",
        "phone": "+447309951848",
        "password": "9697vahfs9c0",
        "username": "Ffffggggyincd1ncf",
    },
    {
        "name": "userbot4",
        "phone": "+447342387146",
        "password": "8tk9t",
        "username": "Fqwer1t",
    },
]


async def create_session(account: dict) -> str | None:
    """Создаёт session string для одного аккаунта."""
    print(f"\n{'='*50}")
    print(f"Аккаунт: @{account['username']} ({account['phone']})")
    print(f"{'='*50}")

    client = Client(
        name=account["name"],
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=account["phone"],
        password=account["password"],
        in_memory=True,
    )

    try:
        await client.start()
        session_string = await client.export_session_string()
        me = await client.get_me()
        print(f"\n[OK] Успех: {me.first_name} (@{me.username})")
        await client.stop()
        return session_string
    except Exception as e:
        print(f"\n[ERROR] Ошибка: {e}")
        try:
            await client.stop()
        except:
            pass
        return None


async def main():
    print("=" * 50)
    print("Создание session strings для юзерботов")
    print("=" * 50)
    print("\nКод подтверждения придёт в Telegram.")
    print("2FA пароль будет использован автоматически.\n")

    sessions = {}

    for i, account in enumerate(ACCOUNTS, 1):
        print(f"\n[{i}/{len(ACCOUNTS)}] Обрабатываю @{account['username']}...")

        session = await create_session(account)
        if session:
            sessions[account["name"]] = {
                "username": account["username"],
                "session": session,
            }

    # Выводим результаты
    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 50)

    if sessions:
        print("\nДобавьте в .env.test:\n")
        for name, data in sessions.items():
            var_name = name.upper() + "_SESSION"
            print(f"# @{data['username']}")
            print(f"TEST_{var_name}={data['session']}")
            print()
    else:
        print("\nНе удалось создать ни одной сессии.")


if __name__ == "__main__":
    asyncio.run(main())
