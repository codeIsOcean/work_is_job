#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой скрипт для сброса webhook бота
"""

import asyncio
import aiohttp
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv('.env.dev')
BOT_TOKEN = os.getenv('BOT_TOKEN')

async def reset_bot_webhook():
    """Сбрасывает webhook и очищает состояние бота"""
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not found in environment variables")
        return
    
    print(f"Bot token: {BOT_TOKEN[:10]}...")
    
    async with aiohttp.ClientSession() as session:
        try:
            # 1. Удаляем webhook
            print("1. Deleting webhook...")
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook") as resp:
                result = await resp.json()
                if result.get('ok'):
                    print("SUCCESS: Webhook deleted")
                else:
                    print(f"WARNING: {result}")
            
            # 2. Получаем информацию о webhook
            print("2. Checking webhook status...")
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo") as resp:
                result = await resp.json()
                if result.get('ok'):
                    webhook_info = result.get('result', {})
                    print(f"Webhook URL: {webhook_info.get('url', 'Not set')}")
                    print(f"Pending updates: {webhook_info.get('pending_update_count', 0)}")
                else:
                    print(f"WARNING: {result}")
            
            # 3. Получаем информацию о боте
            print("3. Checking bot info...")
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as resp:
                result = await resp.json()
                if result.get('ok'):
                    bot_info = result.get('result', {})
                    print(f"Bot: @{bot_info.get('username', 'Unknown')} ({bot_info.get('first_name', 'Unknown')})")
                    print(f"ID: {bot_info.get('id', 'Unknown')}")
                else:
                    print(f"ERROR: {result}")
            
            print("\nSUCCESS: Webhook reset completed!")
            print("Now you can start the bot: python start_bot.py")
            
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(reset_bot_webhook())

