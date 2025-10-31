# 🏗️ Руководство по реализации Multi-Tenant архитектуры для Telegram бота

## 📋 Проблемы текущей реализации

### 1. **Все группы видны главному админу**
- Сейчас нет разграничения по пользователям
- Группы не фильтруются по реальным правам

### 2. **Группы не удаляются при удалении бота**
- Нет обработчика события `my_chat_member` когда бот удаляется из группы
- Группы остаются в БД даже после удаления бота

### 3. **Нет проверки прав через Telegram API**
- Только проверка через таблицу `UserGroup`
- Не проверяется, является ли пользователь админом СЕЙЧАС

---

## 🎯 Как делается в популярных ботах (Rose, ChatKeeper, GroupHelp)

### Принципы:
1. **Каждый пользователь видит только свои группы** - где он реально является администратором
2. **Права проверяются в реальном времени** через Telegram API
3. **При удалении бота** - группа автоматически скрывается/удаляется из списка
4. **Проверка что бот еще в группе** перед отображением настроек

---

## 🔧 Реализация: Пошаговая инструкция

### ШАГ 1: Добавить обработчик удаления бота из группы

**Файл**: `bot/handlers/bot_activity_handlers/group_events.py`

**Код для добавления после функции `bot_added_to_group`:**

```python
@group_events_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER >> IS_NOT_MEMBER))
async def bot_removed_from_group(event: types.ChatMemberUpdated, session: AsyncSession):
    """
    Обработчик удаления бота из группы.
    Удаляет группу из списка доступных или помечает как неактивную.
    """
    chat = event.chat
    user = event.from_user
    
    logger.info(f"🗑️ Бот удален из группы {chat.title} (ID: {chat.id}) пользователем {user.full_name}")
    
    try:
        # 1. Находим группу в БД
        result = await session.execute(select(Group).where(Group.chat_id == chat.id))
        group = result.scalar_one_or_none()
        
        if not group:
            logger.warning(f"Группа {chat.id} не найдена в БД")
            return
        
        # 2. УДАЛЯЕМ все связи пользователей с этой группой из UserGroup
        # Это важно: пользователи больше не должны видеть эту группу
        await session.execute(
            delete(UserGroup).where(UserGroup.group_id == chat.id)
        )
        logger.info(f"Удалены все связи UserGroup для группы {chat.id}")
        
        # 3. УДАЛЯЕМ группу из таблицы Group
        await session.delete(group)
        logger.info(f"Группа {chat.id} удалена из БД")
        
        # 4. Очищаем связанные данные из Redis
        from bot.services.redis_conn import redis
        await redis.delete(f"visual_captcha_enabled:{chat.id}")
        await redis.delete(f"group:{chat.id}:mute_new_members")
        await redis.delete(f"group_link:private_{chat.id}")
        logger.info(f"Очищены данные Redis для группы {chat.id}")
        
        await session.commit()
        logger.info(f"✅ Группа {chat.title} полностью удалена из системы")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении группы: {e}")
        await session.rollback()
```

**ВАЖНО**: Нужно добавить импорт:
```python
from sqlalchemy import delete
```

---

### ШАГ 2: Улучшить функцию `get_admin_groups` - проверка реальных прав

**Файл**: `bot/services/groups_settings_in_private_logic.py`

**ЗАМЕНИТЬ текущую функцию `get_admin_groups` на эту:**

```python
async def get_admin_groups(user_id: int, session: AsyncSession, bot: Bot = None) -> List[Group]:
    """
    Получает группы где пользователь является администратором.
    ВАЖНО: Проверяет права через Telegram API в реальном времени!
    """
    try:
        # 1. Получаем все группы из UserGroup
        user_groups_query = select(UserGroup).where(UserGroup.user_id == user_id)
        user_groups_result = await session.execute(user_groups_query)
        user_groups = user_groups_result.scalars().all()
        
        logger.info(f"Найдено {len(user_groups)} записей UserGroup для пользователя {user_id}")
        
        if not user_groups:
            return []
        
        # 2. Получаем информацию о группах
        group_ids = [ug.group_id for ug in user_groups]
        groups_query = select(Group).where(Group.chat_id.in_(group_ids))
        groups_result = await session.execute(groups_query)
        groups = groups_result.scalars().all()
        
        if not bot:
            # Если бот не передан, возвращаем все группы (старое поведение)
            logger.warning("⚠️ Бот не передан в get_admin_groups, возвращаются все группы без проверки прав")
            return list(groups)
        
        # 3. ПРОВЕРЯЕМ реальные права через Telegram API и что бот еще в группе
        valid_groups = []
        
        for group in groups:
            try:
                # 3.1. Проверяем что бот еще в группе
                try:
                    member = await bot.get_chat_member(group.chat_id, bot.id)
                    if member.status not in ["member", "administrator", "creator"]:
                        # Бот не в группе - пропускаем
                        logger.info(f"⛔ Бот не в группе {group.chat_id}, пропускаем")
                        continue
                except Exception as e:
                    # Бот не может получить информацию - возможно удален из группы
                    logger.warning(f"⚠️ Не удалось проверить статус бота в группе {group.chat_id}: {e}")
                    # УДАЛЯЕМ группу из UserGroup
                    await session.execute(
                        delete(UserGroup).where(
                            UserGroup.user_id == user_id,
                            UserGroup.group_id == group.chat_id
                        )
                    )
                    continue
                
                # 3.2. Проверяем что пользователь СЕЙЧАС является админом
                try:
                    user_member = await bot.get_chat_member(group.chat_id, user_id)
                    if user_member.status not in ["administrator", "creator"]:
                        # Пользователь больше не админ - удаляем из UserGroup
                        logger.info(f"⛔ Пользователь {user_id} больше не админ в группе {group.chat_id}")
                        await session.execute(
                            delete(UserGroup).where(
                                UserGroup.user_id == user_id,
                                UserGroup.group_id == group.chat_id
                            )
                        )
                        continue
                    
                    # Пользователь админ - группа валидна
                    valid_groups.append(group)
                    logger.info(f"✅ Пользователь {user_id} имеет права админа в группе {group.title}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при проверке прав пользователя {user_id} в группе {group.chat_id}: {e}")
                    # Не удалось проверить - пропускаем группу
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при обработке группы {group.chat_id}: {e}")
                continue
        
        await session.commit()
        
        logger.info(f"Найдено {len(valid_groups)} валидных групп для пользователя {user_id}")
        return valid_groups
        
    except Exception as e:
        logger.error(f"❌ Ошибка при получении групп пользователя {user_id}: {e}")
        await session.rollback()
        return []
```

**ВАЖНО**: Нужно добавить импорты:
```python
from typing import List
from sqlalchemy import delete
from aiogram import Bot
```

---

### ШАГ 3: Обновить вызовы `get_admin_groups` - передавать `bot`

**Файл**: `bot/handlers/group_settings_handler/groups_settings_in_private_handler.py`

**НАЙТИ все места где вызывается:**
```python
user_groups = await get_admin_groups(user_id, session)
```

**ЗАМЕНИТЬ на:**
```python
user_groups = await get_admin_groups(user_id, session, bot=message.bot)  # или callback.bot, или event.bot
```

**Примеры в файле:**
1. В функции `show_groups_list` (строка ~45):
   ```python
   # БЫЛО:
   user_groups = await get_admin_groups(user_id, session)
   
   # ДОЛЖНО БЫТЬ:
   user_groups = await get_admin_groups(user_id, session, bot=message.bot)
   ```

2. В функции `refresh_groups_list` (строка ~377):
   ```python
   # БЫЛО:
   user_groups = await get_admin_groups(user_id, session)
   
   # ДОЛЖНО БЫТЬ:
   user_groups = await get_admin_groups(user_id, session, bot=callback.bot)
   ```

---

### ШАГ 4: Обновить синхронизацию админов - обновлять UserGroup динамически

**Файл**: `bot/services/bot_added_handler_logic.py`

**НАЙТИ функцию `sync_group_and_admins`** и убедиться что она:
1. Удаляет админов, которые больше не админы
2. Добавляет новых админов
3. Проверяет статус бота в группе

**Добавить логику (пример):**

```python
async def sync_group_and_admins(chat_id: int, title: str, bot_id: int, bot: Bot):
    """
    Синхронизирует список администраторов группы.
    УДАЛЯЕТ админов которые больше не админы.
    ДОБАВЛЯЕТ новых админов.
    """
    async with AsyncSession(engine) as session:
        try:
            # 1. Получаем текущих админов из Telegram
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = {admin.user.id for admin in admins}
            
            # 2. Получаем админов из БД
            result = await session.execute(
                select(UserGroup).where(UserGroup.group_id == chat_id)
            )
            db_admin_relations = result.scalars().all()
            db_admin_ids = {rel.user_id for rel in db_admin_relations}
            
            # 3. УДАЛЯЕМ админов которые больше не админы
            admins_to_remove = db_admin_ids - admin_ids
            if admins_to_remove:
                await session.execute(
                    delete(UserGroup).where(
                        UserGroup.group_id == chat_id,
                        UserGroup.user_id.in_(admins_to_remove)
                    )
                )
                logger.info(f"Удалены {len(admins_to_remove)} админов из группы {chat_id}")
            
            # 4. ДОБАВЛЯЕМ новых админов
            admins_to_add = admin_ids - db_admin_ids
            for admin_id in admins_to_add:
                # Проверяем что запись не существует
                existing = await session.execute(
                    select(UserGroup).where(
                        UserGroup.group_id == chat_id,
                        UserGroup.user_id == admin_id
                    )
                )
                if not existing.scalar_one_or_none():
                    session.add(UserGroup(
                        user_id=admin_id,
                        group_id=chat_id
                    ))
                    logger.info(f"Добавлен новый админ {admin_id} в группу {chat_id}")
            
            await session.commit()
            logger.info(f"✅ Синхронизация админов завершена для группы {chat_id}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации админов: {e}")
            await session.rollback()
```

---

### ШАГ 5: Добавить периодическую проверку групп

**Файл**: Создать новый `bot/services/group_sync_service.py`

```python
"""
Сервис для периодической синхронизации групп и прав администраторов.
Запускается как фоновая задача.
"""
import asyncio
import logging
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from bot.database.session import engine
from bot.database.models import Group, UserGroup

logger = logging.getLogger(__name__)


async def sync_all_groups_periodically(bot: Bot, interval_minutes: int = 60):
    """
    Периодически проверяет все группы и синхронизирует права.
    Удаляет группы где бот больше не присутствует.
    """
    while True:
        try:
            await asyncio.sleep(interval_minutes * 60)  # Интервал в секундах
            
            async with AsyncSession(engine) as session:
                # Получаем все группы
                result = await session.execute(select(Group))
                groups = result.scalars().all()
                
                logger.info(f"🔄 Синхронизация {len(groups)} групп...")
                
                for group in groups:
                    try:
                        # Проверяем что бот в группе
                        member = await bot.get_chat_member(group.chat_id, bot.id)
                        if member.status not in ["member", "administrator", "creator"]:
                            # Бот удален - удаляем группу
                            logger.info(f"🗑️ Бот удален из группы {group.chat_id}, удаляем группу")
                            await session.execute(
                                delete(UserGroup).where(UserGroup.group_id == group.chat_id)
                            )
                            await session.delete(group)
                            await session.commit()
                            continue
                        
                        # Синхронизируем админов
                        await sync_group_admins(session, group.chat_id, bot)
                        
                    except Exception as e:
                        logger.error(f"Ошибка при синхронизации группы {group.chat_id}: {e}")
                        continue
                
                logger.info("✅ Синхронизация завершена")
                
        except Exception as e:
            logger.error(f"❌ Ошибка в периодической синхронизации: {e}")


async def sync_group_admins(session: AsyncSession, chat_id: int, bot: Bot):
    """Синхронизирует админов одной группы"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = {admin.user.id for admin in admins}
        
        result = await session.execute(
            select(UserGroup).where(UserGroup.group_id == chat_id)
        )
        db_relations = result.scalars().all()
        db_admin_ids = {rel.user_id for rel in db_relations}
        
        # Удаляем устаревших
        to_remove = db_admin_ids - admin_ids
        if to_remove:
            await session.execute(
                delete(UserGroup).where(
                    UserGroup.group_id == chat_id,
                    UserGroup.user_id.in_(to_remove)
                )
            )
        
        # Добавляем новых
        to_add = admin_ids - db_admin_ids
        for admin_id in to_add:
            existing = await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == chat_id,
                    UserGroup.user_id == admin_id
                )
            )
            if not existing.scalar_one_or_none():
                session.add(UserGroup(user_id=admin_id, group_id=chat_id))
        
        await session.commit()
    except Exception as e:
        logger.error(f"Ошибка синхронизации админов группы {chat_id}: {e}")
        await session.rollback()
```

**Добавить запуск в `bot/bot.py`:**

```python
# После создания bot и dp
async def main():
    # ... существующий код ...
    
    if USE_WEBHOOK:
        # Запускаем периодическую синхронизацию
        from bot.services.group_sync_service import sync_all_groups_periodically
        asyncio.create_task(sync_all_groups_periodically(bot, interval_minutes=60))
        
        await run_webhook(bot=bot, dp=dp)
    else:
        # Для polling тоже можно запустить
        from bot.services.group_sync_service import sync_all_groups_periodically
        asyncio.create_task(sync_all_groups_periodically(bot, interval_minutes=60))
        
        await dp.start_polling(bot)
```

---

## ✅ Чеклист реализации

- [ ] **ШАГ 1**: Добавить обработчик `bot_removed_from_group`
- [ ] **ШАГ 2**: Обновить `get_admin_groups` с проверкой прав через API
- [ ] **ШАГ 3**: Обновить все вызовы `get_admin_groups` - добавить параметр `bot`
- [ ] **ШАГ 4**: Улучшить `sync_group_and_admins` - удалять устаревших админов
- [ ] **ШАГ 5**: Добавить периодическую синхронизацию (опционально, но рекомендуется)

---

## 🔍 Тестирование

### Проверка 1: Каждый видит только свои группы
1. Пользователь A добавляет бота в свою группу
2. Пользователь B добавляет бота в свою группу
3. Пользователь A открывает настройки - видит только свою группу ✅
4. Пользователь B открывает настройки - видит только свою группу ✅

### Проверка 2: Удаление бота удаляет группу
1. Добавить бота в группу
2. Удалить бота из группы
3. Открыть настройки - группа не должна быть в списке ✅

### Проверка 3: Удаление прав админа
1. Пользователь админ в группе - видит группу в настройках
2. Удалить пользователя из админов
3. Обновить список групп - группа должна исчезнуть ✅

---

## 📝 Дополнительные рекомендации

1. **Кэширование**: Можно кэшировать результаты проверки прав на 5-10 минут в Redis
2. **Логирование**: Все операции синхронизации должны логироваться
3. **Обработка ошибок**: Все проверки через API должны быть в try-except

---

## 🎓 Принципы архитектуры

1. **Multi-Tenant**: Каждый пользователь изолирован, видит только свои данные
2. **Real-time проверка**: Права проверяются через Telegram API, не только из БД
3. **Автоматическая очистка**: Устаревшие данные автоматически удаляются
4. **Синхронизация**: Периодическая проверка актуальности данных

---

## 📚 Справочник изменений

### Измененные файлы:
1. `bot/handlers/bot_activity_handlers/group_events.py` - добавлен обработчик удаления
2. `bot/services/groups_settings_in_private_logic.py` - обновлен `get_admin_groups`
3. `bot/handlers/group_settings_handler/groups_settings_in_private_handler.py` - обновлены вызовы
4. `bot/services/bot_added_handler_logic.py` - улучшена синхронизация
5. `bot/services/group_sync_service.py` - новый файл для периодической синхронизации
6. `bot/bot.py` - запуск фоновой задачи синхронизации

---

**Готово! Следуйте инструкциям по порядку, тестируйте после каждого шага.**

