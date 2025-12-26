"""
Сервис защиты данных групп от случайной потери.

Этот сервис решает проблему, когда группы исчезают из БД после перезапуска бота.
Механизмы защиты:
1. Бэкап групп в Redis при каждом старте
2. Бэкап групп в ФАЙЛ на хосте (защита от удаления Redis volume!)
3. Логирование любых попыток удаления Group записей
4. Автоматическое восстановление групп из бэкапа при обнаружении потери

Использование:
- Вызвать backup_groups_to_redis() при старте бота
- Вызвать restore_groups_from_backup() если обнаружено 0 групп в БД

ВАЖНО: При reset-test-env.sh или docker-compose down -v удаляются volumes!
Файловый бэкап сохраняется на хосте и НЕ удаляется вместе с volumes.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from sqlalchemy import select, event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bot.database.models import Group, UserGroup, ChatSettings, CaptchaSettings
from bot.services.redis_conn import redis

logger = logging.getLogger(__name__)

# Redis ключи для бэкапов
GROUPS_BACKUP_KEY = "groups_backup:data"
GROUPS_BACKUP_TIMESTAMP_KEY = "groups_backup:timestamp"
GROUPS_BACKUP_COUNT_KEY = "groups_backup:count"

# TTL для бэкапов (7 дней)
BACKUP_TTL_SECONDS = 7 * 24 * 60 * 60

# Путь к файловому бэкапу (на хосте через volume mount)
# Используем папку backup в корне проекта
FILE_BACKUP_DIR = Path("/app/backup") if os.path.exists("/app") else Path("backup")
FILE_BACKUP_PATH = FILE_BACKUP_DIR / "groups_backup.json"

# Фейковые тестовые chat_id которые НЕ должны бэкапиться/восстанавливаться
# Это ID используемые в юнит-тестах
FAKE_TEST_CHAT_IDS = {
    -1001234567890,  # Стандартный тестовый ID
    -1001234567891,  # Альтернативный тестовый ID
    -1000,           # Тестовый ID из conftest.py
}


def is_fake_test_group(chat_id: int) -> bool:
    """
    Проверяет, является ли chat_id фейковой тестовой группой.

    Такие группы не должны попадать в бэкап и восстанавливаться.
    """
    return chat_id in FAKE_TEST_CHAT_IDS


async def backup_groups_to_redis(session: AsyncSession) -> int:
    """
    Создает бэкап всех групп в Redis.

    Сохраняет:
    - Основные данные группы (chat_id, title, creator, added_by)
    - Связи UserGroup (админы)
    - ChatSettings и CaptchaSettings

    Returns:
        Количество сохраненных групп
    """
    try:
        # Получаем все группы
        result = await session.execute(select(Group).where(Group.chat_id != 0))
        groups = result.scalars().all()

        if not groups:
            logger.warning("⚠️ [GROUP_PROTECTION] Нет групп для бэкапа")
            return 0

        backup_data = []

        for group in groups:
            # Пропускаем фейковые тестовые группы
            if is_fake_test_group(group.chat_id):
                logger.warning(
                    f"⚠️ [GROUP_PROTECTION] Пропускаем фейковую тестовую группу: "
                    f"{group.chat_id} ({group.title})"
                )
                continue

            # Получаем связанные данные
            ug_result = await session.execute(
                select(UserGroup).where(UserGroup.group_id == group.chat_id)
            )
            user_groups = ug_result.scalars().all()

            cs_result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == group.chat_id)
            )
            chat_settings = cs_result.scalar_one_or_none()

            cap_result = await session.execute(
                select(CaptchaSettings).where(CaptchaSettings.group_id == group.chat_id)
            )
            captcha_settings = cap_result.scalar_one_or_none()

            group_data = {
                "chat_id": group.chat_id,
                "title": group.title,
                "creator_user_id": group.creator_user_id,
                "added_by_user_id": group.added_by_user_id,
                "bot_id": group.bot_id,
                "admin_user_ids": [ug.user_id for ug in user_groups],
                "chat_settings": {
                    "username": chat_settings.username if chat_settings else None,
                } if chat_settings else None,
                "captcha_settings": {
                    "is_enabled": captcha_settings.is_enabled if captcha_settings else False,
                    "is_visual_enabled": captcha_settings.is_visual_enabled if captcha_settings else False,
                } if captcha_settings else None,
            }
            backup_data.append(group_data)

        # Сохраняем в Redis
        backup_json = json.dumps(backup_data, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).isoformat()

        await redis.setex(GROUPS_BACKUP_KEY, BACKUP_TTL_SECONDS, backup_json)
        await redis.setex(GROUPS_BACKUP_TIMESTAMP_KEY, BACKUP_TTL_SECONDS, timestamp)
        await redis.setex(GROUPS_BACKUP_COUNT_KEY, BACKUP_TTL_SECONDS, str(len(groups)))

        logger.info(f"✅ [GROUP_PROTECTION] Бэкап создан: {len(groups)} групп сохранено в Redis")

        # ТАКЖЕ сохраняем в файл (защита от удаления Redis volume!)
        save_backup_to_file(backup_data, timestamp)
        return len(groups)

    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка создания бэкапа: {e}")
        return 0


async def get_backup_info() -> Optional[Dict[str, Any]]:
    """
    Возвращает информацию о последнем бэкапе.

    Returns:
        Dict с timestamp и count, или None если бэкапа нет
    """
    try:
        timestamp = await redis.get(GROUPS_BACKUP_TIMESTAMP_KEY)
        count = await redis.get(GROUPS_BACKUP_COUNT_KEY)

        if not timestamp or not count:
            return None

        return {
            "timestamp": timestamp.decode() if isinstance(timestamp, bytes) else timestamp,
            "count": int(count.decode() if isinstance(count, bytes) else count),
        }
    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка чтения инфо бэкапа: {e}")
        return None


async def restore_groups_from_backup(session: AsyncSession) -> int:
    """
    Восстанавливает группы из Redis бэкапа.

    ВАЖНО: Вызывать только если groups таблица пустая!

    Returns:
        Количество восстановленных групп
    """
    try:
        # Получаем бэкап
        backup_json = await redis.get(GROUPS_BACKUP_KEY)
        if not backup_json:
            logger.warning("⚠️ [GROUP_PROTECTION] Бэкап не найден в Redis")
            return 0

        backup_data = json.loads(backup_json.decode() if isinstance(backup_json, bytes) else backup_json)

        if not backup_data:
            logger.warning("⚠️ [GROUP_PROTECTION] Бэкап пустой")
            return 0

        restored_count = 0

        for group_data in backup_data:
            chat_id = group_data["chat_id"]

            # Пропускаем фейковые тестовые группы
            if is_fake_test_group(chat_id):
                logger.warning(
                    f"⚠️ [GROUP_PROTECTION] Пропускаем восстановление фейковой тестовой группы: "
                    f"{chat_id} ({group_data.get('title', 'Unknown')})"
                )
                continue

            # Проверяем, нет ли уже этой группы
            existing = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            if existing.scalar_one_or_none():
                logger.info(f"ℹ️ [GROUP_PROTECTION] Группа {chat_id} уже существует, пропускаем")
                continue

            # Создаем группу
            group = Group(
                chat_id=chat_id,
                title=group_data["title"],
                creator_user_id=group_data.get("creator_user_id"),
                added_by_user_id=group_data.get("added_by_user_id"),
                bot_id=group_data.get("bot_id"),
            )
            session.add(group)
            await session.flush()

            # ПРОПУСКАЕМ восстановление UserGroup - админы восстановятся через auto_sync
            admin_count = len(group_data.get("admin_user_ids", []))
            if admin_count > 0:
                logger.info(f"ℹ️ [GROUP_PROTECTION] {admin_count} админов восстановятся через auto_sync")

            # Восстанавливаем ChatSettings
            if group_data.get("chat_settings"):
                cs_existing = await session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                if not cs_existing.scalar_one_or_none():
                    session.add(ChatSettings(
                        chat_id=chat_id,
                        username=group_data["chat_settings"].get("username"),
                    ))

            # Восстанавливаем CaptchaSettings
            if group_data.get("captcha_settings"):
                cap_existing = await session.execute(
                    select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
                )
                if not cap_existing.scalar_one_or_none():
                    session.add(CaptchaSettings(
                        group_id=chat_id,
                        is_enabled=group_data["captcha_settings"].get("is_enabled", False),
                        is_visual_enabled=group_data["captcha_settings"].get("is_visual_enabled", False),
                    ))

            restored_count += 1
            logger.info(f"✅ [GROUP_PROTECTION] Восстановлена группа {chat_id}: {group_data['title']}")

        await session.commit()
        logger.info(f"✅ [GROUP_PROTECTION] Восстановлено {restored_count} групп из бэкапа")
        return restored_count

    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка восстановления из бэкапа: {e}")
        await session.rollback()
        return 0


async def check_and_protect_groups(session: AsyncSession) -> bool:
    """
    Проверяет состояние групп и автоматически восстанавливает при необходимости.

    Логика:
    1. Считает текущее количество групп в БД
    2. Если 0 групп, но есть бэкап - восстанавливает
    3. Если есть группы - создает новый бэкап

    Returns:
        True если всё ОК или успешно восстановлено, False при ошибке
    """
    try:
        # Считаем группы в БД
        result = await session.execute(select(Group).where(Group.chat_id != 0))
        current_groups = result.scalars().all()
        current_count = len(current_groups)

        # Получаем инфо о бэкапе
        backup_info = await get_backup_info()

        logger.info(f"🔍 [GROUP_PROTECTION] Текущее состояние: {current_count} групп в БД")
        if backup_info:
            logger.info(f"🔍 [GROUP_PROTECTION] Последний бэкап: {backup_info['count']} групп от {backup_info['timestamp']}")

        if current_count == 0:
            # Критическая ситуация - нет групп!
            logger.warning("⚠️ [GROUP_PROTECTION] ВНИМАНИЕ: 0 групп в БД!")

            # Сначала пробуем Redis бэкап
            if backup_info and backup_info["count"] > 0:
                logger.info("🔄 [GROUP_PROTECTION] Обнаружен Redis бэкап, начинаем восстановление...")
                restored = await restore_groups_from_backup(session)

                if restored > 0:
                    logger.info(f"✅ [GROUP_PROTECTION] Успешно восстановлено {restored} групп из Redis!")
                    return True

            # Redis бэкап не помог - пробуем файловый бэкап
            file_backup = load_backup_from_file()
            if file_backup and file_backup.get("count", 0) > 0:
                logger.info("🔄 [GROUP_PROTECTION] Пробуем ФАЙЛОВЫЙ бэкап...")
                restored = await restore_from_file_backup(session)

                if restored > 0:
                    logger.info(f"✅ [GROUP_PROTECTION] Восстановлено {restored} групп из ФАЙЛА!")
                    return True

            # Ни один бэкап не помог
            logger.error("❌ [GROUP_PROTECTION] Бэкапы отсутствуют или пусты, восстановление невозможно")
            return False
        else:
            # Есть группы - создаем бэкап
            backup_count = await backup_groups_to_redis(session)

            if backup_info and current_count < backup_info["count"]:
                # Групп стало меньше чем было в бэкапе
                logger.warning(
                    f"⚠️ [GROUP_PROTECTION] Количество групп уменьшилось: "
                    f"было {backup_info['count']}, стало {current_count}"
                )

            return True

    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка проверки групп: {e}")
        return False


# =============================================================================
# SQLAlchemy Event Listeners для отслеживания удаления групп
# =============================================================================

def setup_group_delete_listeners():
    """
    Настраивает SQLAlchemy event listeners для отслеживания удаления Group записей.

    ВАЖНО: Вызывать один раз при инициализации приложения.
    """
    @event.listens_for(Group, "before_delete")
    def log_group_deletion(mapper, connection, target):
        """
        Логирует попытку удаления группы.
        Позволяет отследить, откуда происходит удаление.
        """
        import traceback
        stack = "".join(traceback.format_stack())

        logger.warning(
            f"🚨 [GROUP_PROTECTION] ВНИМАНИЕ: Попытка удаления Group!\n"
            f"   chat_id: {target.chat_id}\n"
            f"   title: {target.title}\n"
            f"   Stack trace:\n{stack}"
        )

    logger.info("✅ [GROUP_PROTECTION] Event listeners для Group настроены")


# =============================================================================
# ФАЙЛОВЫЙ БЭКАП (защита от удаления Redis volume)
# =============================================================================

def _ensure_backup_dir():
    """Создаёт папку для бэкапов если её нет."""
    try:
        FILE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Не удалось создать папку бэкапов: {e}")
        return False


def save_backup_to_file(backup_data: List[Dict], timestamp: str) -> bool:
    """
    Сохраняет бэкап групп в файл на хосте.

    ВАЖНО: Этот файл НЕ удаляется при docker-compose down -v
    потому что папка backup монтируется с хоста.
    """
    if not _ensure_backup_dir():
        return False

    try:
        file_data = {
            "timestamp": timestamp,
            "count": len(backup_data),
            "groups": backup_data
        }

        with open(FILE_BACKUP_PATH, 'w', encoding='utf-8') as f:
            json.dump(file_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ [GROUP_PROTECTION] Файловый бэкап сохранён: {FILE_BACKUP_PATH}")
        return True
    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка сохранения файлового бэкапа: {e}")
        return False


def load_backup_from_file() -> Optional[Dict[str, Any]]:
    """
    Загружает бэкап групп из файла.

    Returns:
        Dict с timestamp, count, groups или None если файл не найден
    """
    try:
        if not FILE_BACKUP_PATH.exists():
            logger.info(f"ℹ️ [GROUP_PROTECTION] Файловый бэкап не найден: {FILE_BACKUP_PATH}")
            return None

        with open(FILE_BACKUP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        logger.info(
            f"✅ [GROUP_PROTECTION] Загружен файловый бэкап: "
            f"{data.get('count', 0)} групп от {data.get('timestamp', 'unknown')}"
        )
        return data
    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка чтения файлового бэкапа: {e}")
        return None


async def restore_from_file_backup(session: AsyncSession) -> int:
    """
    Восстанавливает группы из файлового бэкапа.

    Используется когда Redis бэкап недоступен (например после удаления volume).

    Returns:
        Количество восстановленных групп
    """
    file_data = load_backup_from_file()
    if not file_data or not file_data.get("groups"):
        logger.warning("⚠️ [GROUP_PROTECTION] Файловый бэкап пуст или не найден")
        return 0

    try:
        backup_data = file_data["groups"]
        restored_count = 0

        for group_data in backup_data:
            chat_id = group_data["chat_id"]

            # Пропускаем фейковые тестовые группы
            if is_fake_test_group(chat_id):
                logger.warning(
                    f"⚠️ [GROUP_PROTECTION] Пропускаем восстановление фейковой тестовой группы из файла: "
                    f"{chat_id} ({group_data.get('title', 'Unknown')})"
                )
                continue

            # Проверяем, нет ли уже этой группы
            existing = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            if existing.scalar_one_or_none():
                logger.info(f"ℹ️ [GROUP_PROTECTION] Группа {chat_id} уже существует, пропускаем")
                continue

            # Создаем группу
            group = Group(
                chat_id=chat_id,
                title=group_data["title"],
                creator_user_id=group_data.get("creator_user_id"),
                added_by_user_id=group_data.get("added_by_user_id"),
                bot_id=group_data.get("bot_id"),
            )
            session.add(group)
            await session.flush()

            # ПРОПУСКАЕМ восстановление UserGroup - админы восстановятся через auto_sync
            # при первом сообщении в группу. Это надёжнее чем создавать User записи.
            admin_count = len(group_data.get("admin_user_ids", []))
            if admin_count > 0:
                logger.info(f"ℹ️ [GROUP_PROTECTION] {admin_count} админов восстановятся через auto_sync")

            # Восстанавливаем ChatSettings
            if group_data.get("chat_settings"):
                cs_existing = await session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                if not cs_existing.scalar_one_or_none():
                    session.add(ChatSettings(
                        chat_id=chat_id,
                        username=group_data["chat_settings"].get("username"),
                    ))

            # Восстанавливаем CaptchaSettings
            if group_data.get("captcha_settings"):
                cap_existing = await session.execute(
                    select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
                )
                if not cap_existing.scalar_one_or_none():
                    session.add(CaptchaSettings(
                        group_id=chat_id,
                        is_enabled=group_data["captcha_settings"].get("is_enabled", False),
                        is_visual_enabled=group_data["captcha_settings"].get("is_visual_enabled", False),
                    ))

            restored_count += 1
            logger.info(f"✅ [GROUP_PROTECTION] Восстановлена группа {chat_id}: {group_data['title']}")

        await session.commit()
        logger.info(f"✅ [GROUP_PROTECTION] Восстановлено {restored_count} групп из ФАЙЛОВОГО бэкапа!")
        return restored_count

    except Exception as e:
        logger.error(f"❌ [GROUP_PROTECTION] Ошибка восстановления из файла: {e}")
        await session.rollback()
        return 0
