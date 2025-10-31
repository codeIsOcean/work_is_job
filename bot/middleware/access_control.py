# middleware/access_control.py
import logging
import os
from typing import Callable, Dict, Any, Awaitable, Set
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
try:
    # Предпочитаем общую конфигурацию проекта (если доступна)
    from bot.config import ADMIN_IDS as CONFIG_ADMIN_IDS  # type: ignore
except Exception:
    CONFIG_ADMIN_IDS = []

logger = logging.getLogger(__name__)

# ID разрешенного пользователя по умолчанию (разработчик)
ALLOWED_USER_ID = 619924982

# Дополнительные разрешенные пользователи:
# 1) из переменной окружения ADMIN_IDS (через запятую)
# 2) из общей конфигурации проекта (bot.config.ADMIN_IDS)
# 3) по username из ADMIN_USERNAMES (через запятую)

def _load_allowed_ids() -> Set[int]:
    ids: Set[int] = set()
    ids.add(ALLOWED_USER_ID)
    # Явно разрешаем пользователя по ID (запрос клиента)
    ids.add(5289489605)
    # Из bot.config
    try:
        ids.update(int(i) for i in CONFIG_ADMIN_IDS or [])
    except Exception:
        pass
    # Из ENV
    raw = os.getenv("ADMIN_IDS", "").strip()
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
    return ids

def _load_allowed_usernames() -> Set[str]:
    names: Set[str] = set()
    raw = os.getenv("ADMIN_USERNAMES", "")
    if raw:
        for part in raw.split(","):
            name = part.strip().lstrip("@").lower()
            if name:
                names.add(name)
    # Специально разрешаем пользователя @zetabeta90 по запросу
    names.add("zetabeta90")
    return names

ALLOWED_USER_IDS: Set[int] = _load_allowed_ids()
ALLOWED_USERNAMES: Set[str] = _load_allowed_usernames()

# Флаг для временного отключения ограничения доступа
ACCESS_CONTROL_ENABLED = True

class AccessControlMiddleware(BaseMiddleware):
    """Middleware для ограничения доступа к боту только для определенного пользователя"""
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery | ChatMemberUpdated,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем user_id в зависимости от типа события
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        elif isinstance(event, ChatMemberUpdated):
            user_id = event.from_user.id
        
        # Если не удалось получить user_id, пропускаем
        if user_id is None:
            logger.warning("Не удалось получить user_id для проверки доступа")
            return await handler(event, data)
        
        # Если контроль доступа отключен, пропускаем проверку
        if not ACCESS_CONTROL_ENABLED:
            logger.info(f"🔓 Контроль доступа отключен, разрешаем доступ для пользователя {user_id}")
            return await handler(event, data)
        
        # Исключения для системных событий (добавление бота в группу и т.д.)
        if isinstance(event, ChatMemberUpdated):
            # Разрешаем события изменения статуса бота в группах
            # Проверяем, что это событие касается самого бота
            try:
                bot_info = await event.bot.me()
                if event.new_chat_member.user.id == bot_info.id:
                    logger.info(f"✅ Системное событие: изменение статуса бота в группе {event.chat.id}")
                    return await handler(event, data)
            except Exception as e:
                logger.warning(f"Ошибка при получении информации о боте: {e}")
                # Если не можем получить информацию о боте, пропускаем проверку
                pass
        
        # Проверяем доступ (по ID или username)
        username = None
        first_name = None
        if isinstance(event, Message):
            username = event.from_user.username
            first_name = event.from_user.first_name
        elif isinstance(event, CallbackQuery):
            username = event.from_user.username
            first_name = event.from_user.first_name
        elif isinstance(event, ChatMemberUpdated):
            username = event.from_user.username
            first_name = event.from_user.first_name

        username_norm = (username or "").lstrip("@").lower()

        if (user_id not in ALLOWED_USER_IDS) and (username_norm not in ALLOWED_USERNAMES):
            # Получаем информацию о пользователе для логирования
            username = username or "no_username"
            first_name = first_name or "no_name"
            
            logger.warning(f"🚫 Доступ запрещен для пользователя {user_id} (@{username}, {first_name})")
            
            # Отправляем сообщение об отказе в доступе
            if isinstance(event, Message):
                await event.answer(
                    "🚫 <b>Доступ запрещен</b>\n\n"
                    "Этот бот находится в режиме разработки и доступен только для разработчика.\n"
                    "Обратитесь к @texas_dev для получения доступа.",
                    parse_mode="HTML"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "🚫 Доступ запрещен. Обратитесь к @texas_dev",
                    show_alert=True
                )
            
            return  # Блокируем выполнение хэндлера
        
        # Если доступ разрешен, продолжаем выполнение
        logger.debug(f"✅ Доступ разрешен для пользователя {user_id}")
        return await handler(event, data)


def enable_access_control():
    """Включает контроль доступа"""
    global ACCESS_CONTROL_ENABLED
    ACCESS_CONTROL_ENABLED = True
    logger.info("🔒 Контроль доступа включен")


def disable_access_control():
    """Отключает контроль доступа"""
    global ACCESS_CONTROL_ENABLED
    ACCESS_CONTROL_ENABLED = False
    logger.info("🔓 Контроль доступа отключен")


def add_allowed_user(user_id: int):
    """Добавляет пользователя в список разрешенных (для будущего расширения)"""
    # Пока что у нас только один разрешенный пользователь
    logger.info(f"📝 Попытка добавить пользователя {user_id} в список разрешенных")
    logger.info("ℹ️ В текущей версии поддерживается только один разрешенный пользователь")
