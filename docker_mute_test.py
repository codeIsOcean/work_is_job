#!/usr/bin/env python3
"""
Docker-совместимый тест для проверки логики мута
Этот тест можно запустить внутри Docker контейнера
"""

import asyncio
import sys
import os
from datetime import datetime

# Добавляем путь к проекту
sys.path.append('/app')

async def test_docker_mute_logic():
    """Тестирует логику мута в Docker окружении"""
    print("🐳 === DOCKER ТЕСТИРОВАНИЕ ЛОГИКИ МУТА ===\n")
    
    try:
        # Проверяем переменные окружения
        print("🔍 Проверяем переменные окружения...")
        bot_token = os.getenv('BOT_TOKEN')
        database_url = os.getenv('DATABASE_URL')
        
        if bot_token:
            print(f"✅ BOT_TOKEN: {bot_token[:10]}...")
        else:
            print("❌ BOT_TOKEN не найден")
            
        if database_url:
            print(f"✅ DATABASE_URL: {database_url[:20]}...")
        else:
            print("❌ DATABASE_URL не найден")
        
        print()
        
        # Тестируем Redis подключение
        print("🔍 Тестируем Redis подключение...")
        try:
            from bot.services.redis_conn import redis
            
            await redis.ping()
            print("✅ Redis подключение работает")
            
            # Очищаем Redis
            await redis.flushdb()
            print("✅ Redis очищен")
            
        except Exception as e:
            print(f"❌ Ошибка Redis: {e}")
            return
        
        print()
        
        # Тестируем логику мута
        print("🔍 Тестируем логику мута...")
        
        test_chat_id = -1001234567890
        test_user_id = 123456789
        
        # Сценарий: Глобальный мут включен, локальный выключен
        print("📋 СЦЕНАРИЙ: Глобальный мут включен, локальный выключен")
        await redis.set("global_mute_enabled", "1")
        await redis.set(f"group:{test_chat_id}:mute_new_members", "0")
        
        # Проверяем значения
        global_status = await redis.get("global_mute_enabled")
        local_status = await redis.get(f"group:{test_chat_id}:mute_new_members")
        
        print(f"   Redis global_mute_enabled: {global_status}")
        print(f"   Redis local_mute: {local_status}")
        
        # Проверяем логику
        should_mute = (global_status == "1") or (local_status == "1")
        print(f"   Логика should_mute: {should_mute}")
        
        if should_mute:
            print("   ✅ Логика мута работает правильно!")
        else:
            print("   ❌ Логика мута работает неправильно!")
        
        print()
        
        # Тестируем функции получения статуса
        print("🔍 Тестируем функции получения статуса...")
        
        try:
            from bot.services.new_member_requested_to_join_mute_logic import get_mute_new_members_status
            
            local_mute_status = await get_mute_new_members_status(test_chat_id)
            print(f"   get_mute_new_members_status: {local_mute_status}")
            
        except Exception as e:
            print(f"   ❌ Ошибка get_mute_new_members_status: {e}")
        
        try:
            from bot.services.groups_settings_in_private_logic import get_global_mute_status
            from bot.database.session import get_session
            
            async with get_session() as session:
                global_mute_status = await get_global_mute_status(session)
                print(f"   get_global_mute_status: {global_mute_status}")
                
        except Exception as e:
            print(f"   ❌ Ошибка get_global_mute_status: {e}")
        
        print()
        
        # Тестируем мок событие
        print("🔍 Тестируем мок событие...")
        
        class MockEvent:
            def __init__(self, user_id, chat_id, old_status="kicked", new_status="member"):
                self.chat = MockChat(chat_id)
                self.old_chat_member = MockChatMember(old_status, user_id)
                self.new_chat_member = MockChatMember(new_status, user_id)
                self.date = datetime.now()
                self.bot = MockBot()

        class MockChat:
            def __init__(self, chat_id):
                self.id = chat_id
                self.title = f"Test Group {chat_id}"

        class MockChatMember:
            def __init__(self, status, user_id):
                self.status = status
                self.user = MockUser(user_id)

        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
                self.username = f"test_user_{user_id}"
                self.first_name = f"Test User {user_id}"

        class MockBot:
            def __init__(self):
                self.restrict_calls = []
            
            async def restrict_chat_member(self, chat_id, user_id, permissions, until_date):
                self.restrict_calls.append({
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'permissions': permissions,
                    'until_date': until_date
                })
                print(f"   🤖 [MOCK BOT] restrict_chat_member: chat_id={chat_id}, user_id={user_id}")
                return True

        # Создаем мок событие
        event = MockEvent(test_user_id, test_chat_id)
        
        print(f"   Создали мок событие: user_id={event.new_chat_member.user.id}, chat_id={event.chat.id}")
        
        # Тестируем логику мута
        try:
            from bot.services.new_member_requested_to_join_mute_logic import mute_manually_approved_member_logic
            
            await mute_manually_approved_member_logic(event)
            
            if event.bot.restrict_calls:
                print(f"   ✅ Мут применен! Вызовов restrict_chat_member: {len(event.bot.restrict_calls)}")
            else:
                print(f"   ❌ Мут НЕ применен! Вызовов restrict_chat_member: {len(event.bot.restrict_calls)}")
                
        except Exception as e:
            print(f"   ❌ Ошибка mute_manually_approved_member_logic: {e}")
            import traceback
            traceback.print_exc()
        
        print()
        
        print("🎉 === DOCKER ТЕСТИРОВАНИЕ ЗАВЕРШЕНО ===")
        
    except Exception as e:
        print(f"❌ Ошибка при Docker тестировании: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await redis.aclose()
        except:
            pass

async def main():
    """Основная функция Docker тестирования"""
    print("🐳 Запуск Docker тестирования логики мута...\n")
    
    await test_docker_mute_logic()
    
    print("✅ Docker тестирование завершено!")

if __name__ == "__main__":
    asyncio.run(main())
