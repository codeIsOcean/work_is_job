# ============================================================
# НАСТРОЙКИ SCAM MEDIA FILTER В ЛС
# ============================================================
# Обработчик для отображения настроек модуля в ЛС бота.
# Вызывается из главного меню настроек группы.
#
# Интеграция:
# - Функция show_scam_media_settings() вызывается из
#   group_settings_handler когда админ выбирает этот модуль.
# ============================================================

# Импорт для логирования
import logging

# Импорт aiogram
from aiogram import Bot
from aiogram.types import Message, CallbackQuery

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт локальных сервисов
from bot.services.scam_media import SettingsService, BannedHashService

# Импорт клавиатур
from .keyboards import build_settings_keyboard


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _build_settings_text(settings, hash_count: int = 0) -> str:
    """
    Строит текст сообщения с настройками.

    Args:
        settings: Объект настроек
        hash_count: Количество хешей в базе

    Returns:
        Отформатированный текст
    """
    # Статус модуля
    status = "✅ Включено" if settings.enabled else "❌ Выключено"

    # Действие
    action_labels = {
        "delete": "🗑️ Удалить",
        "delete_warn": "⚠️ Удалить + предупреждение",
        "delete_mute": "🔇 Удалить + мут",
        "delete_ban": "🚫 Удалить + бан",
    }
    action = action_labels.get(settings.action, settings.action)

    # Время мута/бана
    def format_duration(seconds):
        if seconds == 0:
            return "навсегда"
        if seconds < 60:
            return f"{seconds} сек."
        if seconds < 3600:
            return f"{seconds // 60} мин."
        if seconds < 86400:
            return f"{seconds // 3600} ч."
        return f"{seconds // 86400} дн."

    # Строим текст
    text = (
        f"<b>🔍 Фильтр скам-изображений</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Действие: <b>{action}</b>\n"
        f"Порог: <b>{settings.threshold}</b>\n"
    )

    # Добавляем время мута если действие = delete_mute
    if settings.action == "delete_mute":
        text += f"Время мута: <b>{format_duration(settings.mute_duration)}</b>\n"

    # Добавляем время бана если действие = delete_ban
    if settings.action == "delete_ban":
        text += f"Время бана: <b>{format_duration(settings.ban_duration)}</b>\n"

    # Дополнительные настройки
    text += f"\n"
    text += f"Глобальная база: {'✅' if settings.use_global_hashes else '❌'}\n"
    text += f"Журнал: {'✅' if settings.log_to_journal else '❌'}\n"
    text += f"БД скаммеров: {'✅' if settings.add_to_scammer_db else '❌'}\n"

    # Статистика
    text += f"\n📊 Хешей в базе: <b>{hash_count}</b>\n"

    text += f"\n<i>Выберите настройку для изменения:</i>"

    return text


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ ПОКАЗА НАСТРОЕК
# ============================================================

async def show_scam_media_settings(
    target: Message | CallbackQuery,
    session: AsyncSession,
    chat_id: int
) -> None:
    """
    Показывает настройки ScamMedia для группы.

    Вызывается из главного меню настроек группы.

    Args:
        target: Message или CallbackQuery для ответа
        session: Сессия БД
        chat_id: ID группы
    """
    # Получаем или создаём настройки
    settings = await SettingsService.get_or_create_settings(session, chat_id)

    # Получаем количество хешей для этой группы
    hash_count = await BannedHashService.count_hashes(session, chat_id=chat_id)

    # Строим текст и клавиатуру
    text = _build_settings_text(settings, hash_count)
    keyboard = build_settings_keyboard(chat_id, settings)

    # Отправляем или редактируем сообщение
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await target.answer()
    else:
        await target.answer(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    logger.info(f"Показаны настройки ScamMedia для chat_id={chat_id}")


# ============================================================
# ФУНКЦИЯ ДЛЯ ИНТЕГРАЦИИ В ГЛАВНОЕ МЕНЮ
# ============================================================

def get_scam_media_button_data(chat_id: int) -> dict:
    """
    Возвращает данные для кнопки в главном меню настроек.

    Args:
        chat_id: ID группы

    Returns:
        dict с текстом и callback_data кнопки
    """
    return {
        "text": "🔍 Скам-изображения",
        "callback_data": f"sm:settings:{chat_id}"
    }
