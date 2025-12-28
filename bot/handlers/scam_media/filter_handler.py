# ============================================================
# ОБРАБОТЧИК ФИЛЬТРАЦИИ SCAM MEDIA
# ============================================================
# Этот файл содержит функцию для проверки входящих сообщений
# с фото на наличие скам-контента.
#
# Вызывается из group_message_coordinator.py
# НЕ регистрируется как отдельный handler - интеграция через координатор
# ============================================================

# Импорт для аннотации типов
from typing import Optional
# Импорт для логирования
import logging

# Импорт aiogram
from aiogram import Bot
from aiogram.types import Message

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт локальных сервисов
from bot.services.scam_media import (
    ScamMediaFilterManager,
    FilterResult,
    SettingsService,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# КЭШИРОВАНИЕ МЕНЕДЖЕРА ФИЛЬТРАЦИИ
# ============================================================
# Глобальный экземпляр менеджера (создаётся при первом использовании)
_filter_manager: Optional[ScamMediaFilterManager] = None


def _get_filter_manager(bot: Bot) -> ScamMediaFilterManager:
    """
    Получает или создаёт экземпляр менеджера фильтрации.

    Args:
        bot: Экземпляр aiogram Bot

    Returns:
        ScamMediaFilterManager
    """
    global _filter_manager
    if _filter_manager is None:
        _filter_manager = ScamMediaFilterManager(bot)
    return _filter_manager


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ ПРОВЕРКИ
# ============================================================
async def check_message_for_scam_media(
    message: Message,
    bot: Bot,
    session: AsyncSession
) -> FilterResult:
    """
    Проверяет сообщение на наличие скам-изображения.

    Эта функция вызывается из group_message_coordinator.py
    для каждого сообщения с фото/видео в группе.

    Порядок проверки:
    1. Проверяет включён ли модуль для группы
    2. Извлекает фото из сообщения
    3. Скачивает изображение
    4. Проверяет хеш против базы
    5. Применяет действие если есть совпадение

    Args:
        message: Сообщение Telegram
        bot: Экземпляр aiogram Bot
        session: Сессия SQLAlchemy

    Returns:
        FilterResult с результатом фильтрации
    """
    chat_id = message.chat.id

    # Проверяем включён ли модуль
    if not await SettingsService.is_enabled(session, chat_id):
        return FilterResult(filtered=False, action=None, hash_id=None, distance=None)

    # Получаем менеджер фильтрации
    manager = _get_filter_manager(bot)

    # Извлекаем изображение из сообщения
    image_data = await _extract_image_from_message(message, bot)
    if image_data is None:
        return FilterResult(filtered=False, action=None, hash_id=None, distance=None)

    # Проверяем изображение
    result = await manager.filter_message(session, message, image_data)

    # Логируем результат
    if result.filtered:
        logger.info(
            f"Scam media detected: chat_id={chat_id}, "
            f"user_id={message.from_user.id}, "
            f"action={result.action}, "
            f"distance={result.distance}"
        )

    return result


async def _extract_image_from_message(
    message: Message,
    bot: Bot
) -> Optional[bytes]:
    """
    Извлекает изображение из сообщения.

    Поддерживает:
    - Фото (message.photo)
    - Документы-изображения (message.document с MIME image/*)
    - Превью видео (message.video.thumbnail)

    Args:
        message: Сообщение Telegram
        bot: Экземпляр aiogram Bot

    Returns:
        Байты изображения или None
    """
    file_id: Optional[str] = None

    # Проверяем наличие фото
    if message.photo:
        # Берём фото наибольшего размера (последнее в списке)
        file_id = message.photo[-1].file_id

    # Проверяем документ (может быть изображение)
    elif message.document:
        mime_type = message.document.mime_type or ""
        if mime_type.startswith("image/"):
            file_id = message.document.file_id

    # Проверяем превью видео (если включено в настройках)
    elif message.video and message.video.thumbnail:
        file_id = message.video.thumbnail.file_id

    # Проверяем стикер (может быть скам)
    elif message.sticker and message.sticker.thumbnail:
        # Стикеры тоже могут содержать скам-изображения
        file_id = message.sticker.thumbnail.file_id

    if file_id is None:
        return None

    # Скачиваем файл
    try:
        file = await bot.get_file(file_id)
        if file.file_path is None:
            return None
        # Скачиваем в байты
        from io import BytesIO
        buffer = BytesIO()
        await bot.download_file(file.file_path, buffer)
        return buffer.getvalue()
    except Exception as e:
        logger.warning(f"Не удалось скачать файл: {e}")
        return None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
async def has_media(message: Message) -> bool:
    """
    Проверяет содержит ли сообщение медиа для проверки.

    Args:
        message: Сообщение Telegram

    Returns:
        True если есть фото/видео/документ-изображение
    """
    # Проверяем фото
    if message.photo:
        return True

    # Проверяем документ-изображение
    if message.document:
        mime_type = message.document.mime_type or ""
        if mime_type.startswith("image/"):
            return True

    # Проверяем видео с превью
    if message.video and message.video.thumbnail:
        return True

    # Проверяем стикер
    if message.sticker and message.sticker.thumbnail:
        return True

    return False
