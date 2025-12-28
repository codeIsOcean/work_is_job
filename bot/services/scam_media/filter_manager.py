# ============================================================
# МЕНЕДЖЕР ФИЛЬТРАЦИИ SCAM MEDIA
# ============================================================
# Этот файл координирует логику фильтрации скам-изображений:
# 1. Проверяет включён ли модуль для группы
# 2. Вычисляет хеш входящего изображения
# 3. Сравнивает с базой запрещённых хешей
# 4. Применяет действие (delete, warn, mute, ban)
# 5. Логирует нарушение
# 6. Добавляет в БД скаммеров (опционально)
# ============================================================

# Импорт для работы с датами
from datetime import datetime, timezone, timedelta
# Импорт для аннотации типов
from typing import Optional, NamedTuple, List
# Импорт для логирования
import logging

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт aiogram для работы с Telegram
from aiogram import Bot
from aiogram.types import Message, ChatPermissions

# Импорт локальных сервисов
from .hash_service import HashService, ImageHashes, compute_image_hash, compute_logo_hash
from .db_service import SettingsService, BannedHashService, ViolationService
from bot.database.models_scam_media import ScamMediaSettings, BannedImageHash


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ТИПЫ ДАННЫХ
# ============================================================
class MatchResult(NamedTuple):
    """
    Результат проверки изображения на совпадение.

    Attributes:
        matched: True если найдено совпадение
        hash_entry: Сработавший хеш (или None)
        distance: Расстояние Хэмминга
    """
    matched: bool
    hash_entry: Optional[BannedImageHash]
    distance: int


class FilterResult(NamedTuple):
    """
    Результат фильтрации сообщения.

    Attributes:
        filtered: True если сообщение отфильтровано
        action: Применённое действие (delete/delete_warn/delete_mute/delete_ban)
        hash_id: ID сработавшего хеша
        distance: Расстояние Хэмминга
    """
    filtered: bool
    action: Optional[str]
    hash_id: Optional[int]
    distance: Optional[int]


# ============================================================
# МЕНЕДЖЕР ФИЛЬТРАЦИИ
# ============================================================
class ScamMediaFilterManager:
    """
    Менеджер для фильтрации скам-изображений.

    Координирует весь процесс фильтрации:
    - Проверка настроек
    - Вычисление хеша
    - Сравнение с базой
    - Применение действий
    - Логирование
    """

    def __init__(self, bot: Bot):
        """
        Инициализация менеджера.

        Args:
            bot: Экземпляр aiogram Bot для выполнения действий
        """
        # Сохраняем ссылку на бота
        self._bot = bot
        # Создаём экземпляр сервиса хеширования
        self._hash_service = HashService()

    async def check_image(
        self,
        session: AsyncSession,
        chat_id: int,
        image_data: bytes
    ) -> MatchResult:
        """
        Проверяет изображение на совпадение с базой.

        Args:
            session: Сессия SQLAlchemy
            chat_id: ID группы
            image_data: Байты изображения

        Returns:
            MatchResult с результатом проверки
        """
        # Получаем настройки группы
        settings = await SettingsService.get_settings(session, chat_id)
        # Если настроек нет или модуль выключен - не фильтруем
        if settings is None or not settings.enabled:
            return MatchResult(matched=False, hash_entry=None, distance=64)

        # Вычисляем хеш изображения
        image_hashes = compute_image_hash(image_data)
        if image_hashes is None:
            # Не удалось вычислить хеш - пропускаем
            return MatchResult(matched=False, hash_entry=None, distance=64)

        # Получаем все хеши для сравнения
        include_global = settings.use_global_hashes
        stored_hashes = await BannedHashService.get_hashes_for_group(
            session, chat_id, include_global
        )

        # Порог срабатывания из настроек
        threshold = settings.threshold

        # Ищем совпадения
        best_match: Optional[BannedImageHash] = None
        best_distance: int = 64

        for stored_hash in stored_hashes:
            # Проверяем тип хеша (полный или лого)
            if stored_hash.logo_region:
                # Это хеш области лого - вычисляем хеш той же области
                logo_hashes = compute_logo_hash(image_data, stored_hash.logo_region)
                if logo_hashes is None:
                    continue
                # Сравниваем
                is_similar, distance = self._hash_service.is_similar(
                    logo_hashes.phash, logo_hashes.dhash,
                    stored_hash.phash, stored_hash.dhash,
                    threshold
                )
            else:
                # Обычный хеш всего изображения
                is_similar, distance = self._hash_service.is_similar(
                    image_hashes.phash, image_hashes.dhash,
                    stored_hash.phash, stored_hash.dhash,
                    threshold
                )

            # Запоминаем лучшее совпадение
            if is_similar and distance < best_distance:
                best_match = stored_hash
                best_distance = distance

        # Возвращаем результат
        if best_match is not None:
            return MatchResult(matched=True, hash_entry=best_match, distance=best_distance)
        return MatchResult(matched=False, hash_entry=None, distance=64)

    async def filter_message(
        self,
        session: AsyncSession,
        message: Message,
        image_data: bytes
    ) -> FilterResult:
        """
        Фильтрует сообщение с изображением.

        Выполняет полный цикл фильтрации:
        1. Проверяет изображение
        2. Применяет действие если есть совпадение
        3. Логирует нарушение
        4. Отправляет уведомление

        Args:
            session: Сессия SQLAlchemy
            message: Сообщение Telegram
            image_data: Байты изображения

        Returns:
            FilterResult с результатом фильтрации
        """
        chat_id = message.chat.id
        user = message.from_user

        # Проверяем изображение
        match_result = await self.check_image(session, chat_id, image_data)

        if not match_result.matched:
            return FilterResult(filtered=False, action=None, hash_id=None, distance=None)

        # Получаем настройки для действия
        settings = await SettingsService.get_settings(session, chat_id)
        if settings is None:
            return FilterResult(filtered=False, action=None, hash_id=None, distance=None)

        # Применяем действие
        action = settings.action
        await self._apply_action(message, settings)

        # Обновляем статистику хеша
        await BannedHashService.increment_match_count(session, match_result.hash_entry.id)

        # Логируем нарушение
        await ViolationService.log_violation(
            session=session,
            hash_id=match_result.hash_entry.id,
            chat_id=chat_id,
            user_id=user.id,
            hamming_distance=match_result.distance,
            action_taken=action,
            username=user.username,
            full_name=user.full_name,
            message_id=message.message_id,
        )

        # Добавляем в БД скаммеров если включено
        if settings.add_to_scammer_db:
            await self._add_to_scammer_db(session, user.id, user.username, chat_id)

        # Отправляем в журнал если включено
        if settings.log_to_journal:
            await self._log_to_journal(session, message, match_result, settings)

        return FilterResult(
            filtered=True,
            action=action,
            hash_id=match_result.hash_entry.id,
            distance=match_result.distance
        )

    async def _apply_action(
        self,
        message: Message,
        settings: ScamMediaSettings
    ) -> None:
        """
        Применяет действие к нарушителю.

        Args:
            message: Сообщение для обработки
            settings: Настройки модуля
        """
        action = settings.action
        user = message.from_user
        chat_id = message.chat.id

        # Всегда удаляем сообщение
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Применяем дополнительное действие
        if action == "delete":
            # Только удаление - уже сделали
            pass

        elif action == "delete_warn":
            # Удаление + предупреждение
            await self._send_warning(message, settings)

        elif action == "delete_mute":
            # Удаление + мут
            await self._apply_mute(message, settings)

        elif action == "delete_ban":
            # Удаление + бан
            await self._apply_ban(message, settings)

    async def _send_warning(
        self,
        message: Message,
        settings: ScamMediaSettings
    ) -> None:
        """
        Отправляет предупреждение нарушителю.

        Args:
            message: Исходное сообщение
            settings: Настройки модуля
        """
        user = message.from_user
        # Получаем текст предупреждения
        text = settings.warn_text or self._get_default_warn_text()
        # Заменяем плейсхолдеры
        text = text.replace("%user%", self._format_user_mention(user))

        try:
            sent = await self._bot.send_message(message.chat.id, text)
            # Удаляем уведомление через delay если настроено
            if settings.notification_delete_delay:
                await self._schedule_message_deletion(
                    sent.chat.id, sent.message_id, settings.notification_delete_delay
                )
        except Exception as e:
            logger.warning(f"Не удалось отправить предупреждение: {e}")

    async def _apply_mute(
        self,
        message: Message,
        settings: ScamMediaSettings
    ) -> None:
        """
        Применяет мут к нарушителю.

        Args:
            message: Исходное сообщение
            settings: Настройки модуля
        """
        user = message.from_user
        chat_id = message.chat.id
        duration = settings.mute_duration

        # Вычисляем время окончания мута
        if duration == 0:
            # Перманентный мут - используем далёкую дату
            until_date = datetime.now(timezone.utc) + timedelta(days=366)
        else:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=duration)

        try:
            # Ограничиваем пользователя
            await self._bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
                until_date=until_date
            )

            # Отправляем уведомление
            text = settings.mute_text or self._get_default_mute_text()
            text = text.replace("%user%", self._format_user_mention(user))
            text = text.replace("%duration%", self._format_duration(duration))

            sent = await self._bot.send_message(chat_id, text)
            if settings.notification_delete_delay:
                await self._schedule_message_deletion(
                    sent.chat.id, sent.message_id, settings.notification_delete_delay
                )

        except Exception as e:
            logger.warning(f"Не удалось замутить пользователя: {e}")

    async def _apply_ban(
        self,
        message: Message,
        settings: ScamMediaSettings
    ) -> None:
        """
        Применяет бан к нарушителю.

        Args:
            message: Исходное сообщение
            settings: Настройки модуля
        """
        user = message.from_user
        chat_id = message.chat.id
        duration = settings.ban_duration

        # Вычисляем время окончания бана
        if duration == 0:
            # Перманентный бан
            until_date = None
        else:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=duration)

        try:
            # Баним пользователя
            await self._bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                until_date=until_date
            )

            # Отправляем уведомление
            text = settings.ban_text or self._get_default_ban_text()
            text = text.replace("%user%", self._format_user_mention(user))
            text = text.replace("%duration%", self._format_duration(duration))

            sent = await self._bot.send_message(chat_id, text)
            if settings.notification_delete_delay:
                await self._schedule_message_deletion(
                    sent.chat.id, sent.message_id, settings.notification_delete_delay
                )

        except Exception as e:
            logger.warning(f"Не удалось забанить пользователя: {e}")

    async def _add_to_scammer_db(
        self,
        session: AsyncSession,
        user_id: int,
        username: Optional[str],
        chat_id: int
    ) -> None:
        """
        Добавляет пользователя в глобальную БД скаммеров.

        Args:
            session: Сессия SQLAlchemy
            user_id: ID пользователя
            username: Username пользователя
            chat_id: ID группы где сработал фильтр
        """
        # TODO: Интеграция с spammer_registry.py
        # Пока просто логируем
        logger.info(f"Добавляем в БД скаммеров: user_id={user_id}, username={username}")

    async def _log_to_journal(
        self,
        session: AsyncSession,
        message: Message,
        match_result: MatchResult,
        settings: ScamMediaSettings
    ) -> None:
        """
        Отправляет запись в журнал группы.

        Args:
            session: Сессия SQLAlchemy
            message: Исходное сообщение
            match_result: Результат проверки
            settings: Настройки модуля
        """
        # TODO: Интеграция с журналом группы
        # Пока просто логируем
        logger.info(
            f"Журнал: chat_id={message.chat.id}, "
            f"user_id={message.from_user.id}, "
            f"hash_id={match_result.hash_entry.id}, "
            f"distance={match_result.distance}"
        )

    async def _schedule_message_deletion(
        self,
        chat_id: int,
        message_id: int,
        delay: int
    ) -> None:
        """
        Планирует удаление сообщения через N секунд.

        Args:
            chat_id: ID чата
            message_id: ID сообщения
            delay: Задержка в секундах
        """
        import asyncio
        # Создаём задачу для отложенного удаления
        async def delete_later():
            await asyncio.sleep(delay)
            try:
                await self._bot.delete_message(chat_id, message_id)
            except Exception:
                pass  # Игнорируем ошибки удаления
        # Запускаем в фоне
        asyncio.create_task(delete_later())

    @staticmethod
    def _format_user_mention(user) -> str:
        """
        Форматирует упоминание пользователя.

        Args:
            user: Объект User

        Returns:
            HTML-форматированная ссылка на пользователя
        """
        if user.username:
            return f"@{user.username}"
        return f'<a href="tg://user?id={user.id}">{user.full_name}</a>'

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """
        Форматирует длительность в человекочитаемый формат.

        Args:
            seconds: Длительность в секундах

        Returns:
            Строка вида "24 часа", "7 дней", "навсегда"
        """
        if seconds == 0:
            return "навсегда"
        if seconds < 60:
            return f"{seconds} сек."
        if seconds < 3600:
            return f"{seconds // 60} мин."
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} ч."
        days = seconds // 86400
        return f"{days} дн."

    @staticmethod
    def _get_default_warn_text() -> str:
        """Возвращает текст предупреждения по умолчанию."""
        return "⚠️ %user%, ваше сообщение удалено за скам-контент."

    @staticmethod
    def _get_default_mute_text() -> str:
        """Возвращает текст мута по умолчанию."""
        return "🔇 %user% замучен на %duration% за скам-контент."

    @staticmethod
    def _get_default_ban_text() -> str:
        """Возвращает текст бана по умолчанию."""
        return "🚫 %user% забанен на %duration% за скам-контент."
