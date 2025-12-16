"""
Сервис защиты данных групп от случайной потери.

Этот сервис решает проблему, когда группы исчезают из БД после перезапуска бота.
Механизмы защиты:
1. Бэкап групп в Redis при каждом старте
2. Логирование любых попыток удаления Group записей
3. Автоматическое восстановление групп из бэкапа при обнаружении потери

Использование:
- Вызвать backup_groups_to_redis() при старте бота
- Вызвать restore_groups_from_backup() если обнаружено 0 групп в БД
"""
import json
import logging
from datetime import datetime, timezone
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

            # Восстанавливаем связи UserGroup
            for admin_user_id in group_data.get("admin_user_ids", []):
                # Проверяем, нет ли уже связи
                existing_ug = await session.execute(
                    select(UserGroup).where(
                        UserGroup.user_id == admin_user_id,
                        UserGroup.group_id == chat_id
                    )
                )
                if not existing_ug.scalar_one_or_none():
                    session.add(UserGroup(user_id=admin_user_id, group_id=chat_id))

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

            if backup_info and backup_info["count"] > 0:
                # Есть бэкап - восстанавливаем
                logger.info("🔄 [GROUP_PROTECTION] Обнаружен бэкап, начинаем восстановление...")
                restored = await restore_groups_from_backup(session)

                if restored > 0:
                    logger.info(f"✅ [GROUP_PROTECTION] Успешно восстановлено {restored} групп!")
                    return True
                else:
                    logger.error("❌ [GROUP_PROTECTION] Не удалось восстановить группы из бэкапа")
                    return False
            else:
                logger.warning("⚠️ [GROUP_PROTECTION] Бэкап отсутствует, восстановление невозможно")
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
