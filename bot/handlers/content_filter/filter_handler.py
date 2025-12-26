# ============================================================
# FILTER HANDLER - ОБРАБОТКА СООБЩЕНИЙ В ГРУППАХ
# ============================================================
# Этот хендлер перехватывает сообщения в группах и проверяет их
# через FilterManager на наличие запрещённого контента.
#
# Порядок проверки:
# 1. Проверка что это группа/супергруппа
# 2. Проверка что автор не админ (админы не фильтруются)
# 3. Передача в FilterManager для проверки
# 4. Применение действия при срабатывании
# ============================================================

# Импортируем Router для создания группы хендлеров
from aiogram import Router, F
# Импортируем типы сообщений и клавиатуры
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError
# Импортируем логгер
import logging
# Импортируем html для экранирования спецсимволов
import html
# Импортируем datetime для работы со временем
from datetime import datetime, timedelta, timezone
# Импортируем time для Unix timestamp
import time
# Импортируем asyncio для задержек удаления
import asyncio

# Импортируем типы SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем FilterManager для проверки сообщений
from bot.services.content_filter import FilterManager

# Импортируем функцию отправки в журнал группы
from bot.services.group_journal_service import send_journal_event

# Импортируем сервис сохранения ограничений в БД
from bot.services.restriction_service import save_restriction

# Импортируем Redis клиент для FloodDetector
from bot.services.redis_conn import redis

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для обработки сообщений
filter_handler_router = Router(name='content_filter_handler')

# Создаём глобальный экземпляр FilterManager
# Передаём Redis для работы FloodDetector
_filter_manager = FilterManager(redis=redis)


# ============================================================
# ОСНОВНОЙ ФИЛЬТР СООБЩЕНИЙ
# ============================================================

@filter_handler_router.message(
    # Фильтр: только группы и супергруппы
    F.chat.type.in_({"group", "supergroup"})
)
async def content_filter_message_handler(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Основной обработчик сообщений для фильтрации контента.

    Этот хендлер:
    1. Проверяет что сообщение из группы
    2. Проверяет что автор не админ
    3. Передаёт сообщение в FilterManager
    4. Применяет действие при срабатывании (delete, warn, mute, ban)
    5. Логирует нарушение в БД

    Args:
        message: Входящее сообщение
        session: Сессия БД (инжектится middleware)
    """
    # ─────────────────────────────────────────────────────────
    # DEBUG: Логируем что хендлер вызван (INFO для видимости на проде)
    # ─────────────────────────────────────────────────────────
    logger.info(
        f"[ContentFilter] 📥 Получено сообщение: chat={message.chat.id}, "
        f"user={message.from_user.id if message.from_user else 'N/A'}, "
        f"text={message.text[:50] if message.text else 'N/A'}..."
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 1: Есть ли автор сообщения
    # ─────────────────────────────────────────────────────────
    # Сообщения от каналов или системные могут не иметь автора
    if not message.from_user:
        # Пропускаем сообщения без автора
        return

    # Получаем ID группы и пользователя
    chat_id = message.chat.id
    user_id = message.from_user.id

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 2: Автор - админ?
    # ─────────────────────────────────────────────────────────
    # Админы не подвергаются фильтрации (правило из DEVELOPER_RULES)
    is_admin = False
    try:
        # Получаем информацию о пользователе в чате
        member = await message.bot.get_chat_member(chat_id, user_id)
        # Проверяем статус: creator или administrator
        if member.status in ('creator', 'administrator'):
            is_admin = True
    except TelegramAPIError as e:
        # Ошибка API - логируем и продолжаем (лучше проверить чем пропустить)
        logger.warning(
            f"[ContentFilter] Ошибка проверки админа: {e}, "
            f"chat={chat_id}, user={user_id}"
        )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 2.1: Удаление команд от пользователей
    # ─────────────────────────────────────────────────────────
    # Получаем настройки для проверки delete_user_commands
    cleanup_settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Проверяем, является ли сообщение командой (начинается с /)
    text = message.text or message.caption or ''
    is_command = text.strip().startswith('/')

    if cleanup_settings.delete_user_commands and is_command:
        # Удаляем команды от обычных пользователей
        # Для админов тоже удаляем, но не прерываем обработку (чтобы команда выполнилась)
        try:
            await message.delete()
            logger.info(
                f"[ContentFilter] 🗑️ Удалена команда: chat={chat_id}, "
                f"user={user_id}, is_admin={is_admin}, cmd={text[:30]}"
            )
        except TelegramAPIError as e:
            logger.warning(f"[ContentFilter] Ошибка удаления команды: {e}")

        # Для обычных пользователей - прерываем обработку (команда не должна выполниться)
        if not is_admin:
            return

    # Если это админ - пропускаем фильтрацию контента
    if is_admin:
        return

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 3: Фильтрация через FilterManager
    # ─────────────────────────────────────────────────────────
    try:
        # Проверяем сообщение всеми фильтрами
        result = await _filter_manager.check_message(message, session)

        # Логируем результат проверки
        logger.info(
            f"[ContentFilter] 🔍 Результат проверки: chat={chat_id}, "
            f"should_act={result.should_act}, detector={result.detector_type}, "
            f"trigger={result.trigger}"
        )

        # Если фильтр не сработал - ничего не делаем
        if not result.should_act:
            return

        # ─────────────────────────────────────────────────────
        # ФИЛЬТР СРАБОТАЛ - применяем действие
        # ─────────────────────────────────────────────────────
        logger.info(
            f"[ContentFilter] Срабатывание: chat={chat_id}, user={user_id}, "
            f"detector={result.detector_type}, trigger={result.trigger}, "
            f"action={result.action}"
        )

        # ─────────────────────────────────────────────────────
        # Получаем настройки для применения кастомных действий
        # ─────────────────────────────────────────────────────
        settings = await _filter_manager.get_or_create_settings(chat_id, session)

        # Применяем действие в зависимости от типа
        await _apply_action(message, result, settings, session)

        # Логируем нарушение в БД
        await _filter_manager.log_violation(message, result, session)

        # ─────────────────────────────────────────────────────
        # Отправляем событие в журнал группы (если включено)
        # ─────────────────────────────────────────────────────
        if settings.log_violations:
            await _send_journal_log(message, result, session)

    except Exception as e:
        # Логируем неожиданную ошибку, но не падаем
        logger.exception(
            f"[ContentFilter] Ошибка обработки: {e}, "
            f"chat={chat_id}, user={user_id}"
        )


# ============================================================
# ПРИМЕНЕНИЕ ДЕЙСТВИЙ
# ============================================================

async def _apply_action(
    message: Message,
    result,
    settings,
    session: AsyncSession
) -> None:
    """
    Применяет действие к нарушителю.

    Действия:
    - delete: только удалить сообщение
    - warn: удалить + отправить предупреждение
    - mute: удалить + замутить пользователя
    - kick: удалить + выгнать пользователя
    - ban: удалить + забанить пользователя

    Args:
        message: Сообщение-нарушитель
        result: Результат проверки с действием
        settings: Настройки фильтра группы
        session: Сессия БД
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    action = result.action

    # ─────────────────────────────────────────────────────────
    # Получаем настройки задержек и кастомных текстов
    # ─────────────────────────────────────────────────────────
    delete_delay = None
    notification_delay = None
    custom_mute_text = None
    custom_ban_text = None
    custom_warn_text = None

    # Маппинг категории слова на префиксы полей БД
    category_prefix_map = {
        'simple': 'simple_words',
        'harmful': 'harmful_words',
        'obfuscated': 'obfuscated_words'
    }

    # Если это word_filter и есть категория - получаем настройки категории
    if result.detector_type == 'word_filter' and result.word_category:
        prefix = category_prefix_map.get(result.word_category)
        if prefix:
            # Задержка удаления сообщения нарушителя (в секундах)
            delete_delay = getattr(settings, f'{prefix}_delete_delay', None)
            # Задержка автоудаления уведомления бота (в секундах)
            notification_delay = getattr(settings, f'{prefix}_notification_delete_delay', None)
            # Кастомный текст при муте
            custom_mute_text = getattr(settings, f'{prefix}_mute_text', None)
            # Кастомный текст при бане
            custom_ban_text = getattr(settings, f'{prefix}_ban_text', None)

    # Если это flood - получаем настройки флуда
    elif result.detector_type == 'flood':
        # Задержка удаления сообщения нарушителя (в секундах)
        delete_delay = getattr(settings, 'flood_delete_delay', None)
        # Задержка автоудаления уведомления бота (в секундах) - ЭТО БЫЛО ЗАБЫТО!
        notification_delay = getattr(settings, 'flood_notification_delete_delay', None)
        # Кастомный текст при муте за флуд
        custom_mute_text = getattr(settings, 'flood_mute_text', None)
        # Кастомный текст при бане за флуд
        custom_ban_text = getattr(settings, 'flood_ban_text', None)
        # Кастомный текст при предупреждении за флуд
        custom_warn_text = getattr(settings, 'flood_warn_text', None)

    # Если это custom_section - получаем настройки из result (переданы из FilterResult)
    elif result.detector_type == 'custom_section':
        # Задержка удаления сообщения нарушителя (в секундах)
        delete_delay = result.custom_delete_delay
        # Задержка автоудаления уведомления бота (в секундах)
        notification_delay = result.custom_notification_delay
        # Кастомный текст при муте
        custom_mute_text = result.custom_mute_text
        # Кастомный текст при бане
        custom_ban_text = result.custom_ban_text

    # ─────────────────────────────────────────────────────────
    # ШАГ 1: Удаляем сообщение(я) (для всех действий)
    # ─────────────────────────────────────────────────────────
    # Для флуда - удаляем ВСЕ сообщения из списка (без задержки)
    if result.flood_message_ids:
        deleted_count = 0
        for msg_id in result.flood_message_ids:
            try:
                await message.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                deleted_count += 1
            except TelegramAPIError:
                # Некоторые сообщения могут быть уже удалены
                pass
        logger.info(f"[ContentFilter] Удалено {deleted_count}/{len(result.flood_message_ids)} флуд-сообщений")
    else:
        # Для остальных детекторов - удаляем с опциональной задержкой
        if delete_delay and delete_delay > 0:
            # Удаляем с задержкой в фоне
            asyncio.create_task(_delayed_delete(message, delete_delay))
            logger.info(f"[ContentFilter] ⏰ Отложено удаление msg={message.message_id} на {delete_delay} сек")
        else:
            # Удаляем сразу
            try:
                await message.delete()
                logger.info(f"[ContentFilter] 🗑️ Удалено сообщение msg={message.message_id}")
            except TelegramAPIError as e:
                # Не смогли удалить - логируем, но продолжаем
                logger.warning(f"[ContentFilter] Не удалось удалить сообщение: {e}")

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: Применяем дополнительное действие
    # ─────────────────────────────────────────────────────────

    # Флаг нужно ли пересылать в канал (для custom_section)
    should_forward = False
    forward_channel_id = getattr(result, 'forward_channel_id', None)

    if action == 'delete':
        # Только удаление - уже сделано выше
        # Проверяем нужно ли пересылать при delete
        should_forward = getattr(result, 'forward_on_delete', False) and forward_channel_id
        pass

    elif action == 'warn':
        # Отправляем предупреждение
        await _send_warning(message, result, custom_warn_text, notification_delay)

    elif action == 'mute':
        # Мутим пользователя
        duration_minutes = result.action_duration or 1440  # 24 часа по умолчанию
        await _mute_user(message, duration_minutes, result, custom_mute_text, notification_delay, session)
        # Проверяем нужно ли пересылать при mute
        should_forward = getattr(result, 'forward_on_mute', False) and forward_channel_id

    elif action == 'kick':
        # Кикаем пользователя
        await _kick_user(message, result, notification_delay)

    elif action == 'ban':
        # Баним пользователя
        await _ban_user(message, result, custom_ban_text, notification_delay, session)
        # Проверяем нужно ли пересылать при ban
        should_forward = getattr(result, 'forward_on_ban', False) and forward_channel_id

    elif action == 'forward_delete':
        # Устаревшее действие: пересылаем в канал и удаляем
        # Оставлено для обратной совместимости
        if forward_channel_id:
            await _forward_and_delete(message, forward_channel_id, result, notification_delay)
        else:
            logger.warning("[ContentFilter] forward_delete без forward_channel_id, только удаляем")

    else:
        # Неизвестное действие - логируем
        logger.warning(f"[ContentFilter] Неизвестное действие: {action}")

    # ─────────────────────────────────────────────────────────
    # ШАГ 3: Пересылка в канал (если включена для данного действия)
    # ─────────────────────────────────────────────────────────
    if should_forward and forward_channel_id:
        try:
            # Пересылаем копию сообщения в канал (оригинал уже удалён)
            await _forward_to_channel(message, forward_channel_id, result)
            logger.info(
                f"[ContentFilter] 📤 Переслано в канал {forward_channel_id} "
                f"(action={action}, section={getattr(result, 'section_name', 'N/A')})"
            )
        except Exception as e:
            logger.warning(f"[ContentFilter] Ошибка пересылки в канал: {e}")


async def _delayed_delete(message: Message, delay_seconds: int) -> None:
    """
    Удаляет сообщение с задержкой.

    Args:
        message: Сообщение для удаления
        delay_seconds: Задержка в секундах
    """
    try:
        await asyncio.sleep(delay_seconds)
        await message.delete()
        logger.info(f"[ContentFilter] 🗑️ Удалено msg={message.message_id} после задержки {delay_seconds} сек")
    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось удалить сообщение с задержкой: {e}")
    except asyncio.CancelledError:
        pass


async def _schedule_notification_delete(bot, chat_id: int, message_id: int, delay_seconds: int) -> None:
    """
    Планирует автоудаление уведомления бота через заданное время.

    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        message_id: ID сообщения для удаления
        delay_seconds: Задержка в секундах
    """
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"[ContentFilter] 🔔 Автоудалено уведомление msg={message_id} через {delay_seconds} сек")
    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось автоудалить уведомление: {e}")
    except asyncio.CancelledError:
        pass


async def _send_warning(
    message: Message,
    result,
    custom_text: str = None,
    notification_delay: int = None
) -> None:
    """
    Отправляет предупреждение пользователю в группу.

    Args:
        message: Исходное сообщение
        result: Результат проверки
        custom_text: Кастомный текст предупреждения (с %user% плейсхолдером) или None
        notification_delay: Задержка автоудаления уведомления (сек) или None
    """
    try:
        # Формируем текст предупреждения
        user_mention = message.from_user.mention_html()

        # Если есть кастомный текст - используем его с заменой %user%
        if custom_text:
            warning_text = custom_text.replace('%user%', user_mention)
        else:
            # Дефолтный текст
            warning_text = (
                f"⚠️ {user_mention}, ваше сообщение удалено.\n"
                f"Причина: обнаружен запрещённый контент"
            )

            # Если известен триггер - добавляем
            if result.trigger:
                warning_text += f" ({result.detector_type})"

        # Отправляем предупреждение
        sent_msg = await message.answer(warning_text, parse_mode="HTML")

        # Планируем автоудаление уведомления если задана задержка
        if notification_delay and notification_delay > 0:
            asyncio.create_task(_schedule_notification_delete(
                message.bot, message.chat.id, sent_msg.message_id, notification_delay
            ))

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось отправить предупреждение: {e}")


async def _mute_user(
    message: Message,
    duration_minutes: int,
    result,
    custom_text: str = None,
    notification_delay: int = None,
    session: AsyncSession = None
) -> None:
    """
    Мутит пользователя на указанное время.

    Args:
        message: Исходное сообщение
        duration_minutes: Длительность мута в минутах
        result: Результат проверки
        custom_text: Кастомный текст уведомления (с %user% плейсхолдером) или None
        notification_delay: Задержка автоудаления уведомления (сек) или None
        session: Сессия БД для сохранения ограничения
    """
    try:
        # ─────────────────────────────────────────────────────────
        # Вычисляем время окончания мута как Unix timestamp
        # ВАЖНО: Telegram API требует Unix timestamp в секундах.
        # datetime.utcnow() без timezone вызывает проблемы!
        # ─────────────────────────────────────────────────────────
        until_timestamp = int(time.time()) + (duration_minutes * 60)

        # Применяем ограничение с Unix timestamp
        await message.chat.restrict(
            user_id=message.from_user.id,
            # Запрещаем отправку сообщений
            permissions={
                'can_send_messages': False,
                'can_send_media_messages': False,
                'can_send_other_messages': False,
                'can_add_web_page_previews': False
            },
            until_date=until_timestamp
        )

        # Сохраняем ограничение в БД для восстановления после повторного входа
        if session:
            until_datetime = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
            bot_info = await message.bot.me()
            await save_restriction(
                session=session,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                restriction_type="mute",
                reason="content_filter",
                restricted_by=bot_info.id,
                until_date=until_datetime,
            )

        # Формируем текст уведомления
        user_mention = message.from_user.mention_html()
        hours = duration_minutes // 60
        minutes = duration_minutes % 60

        if hours > 0:
            duration_text = f"{hours}ч"
            if minutes > 0:
                duration_text += f" {minutes}мин"
        else:
            duration_text = f"{minutes}мин"

        # Если есть кастомный текст - используем его с заменой %user%
        if custom_text:
            mute_text = custom_text.replace('%user%', user_mention)
        else:
            # Стандартный текст
            mute_text = (
                f"🔇 {user_mention} получил мут на {duration_text}.\n"
                f"Причина: запрещённый контент ({result.detector_type})"
            )

        # Отправляем уведомление
        sent_msg = await message.answer(mute_text, parse_mode="HTML")

        # Планируем автоудаление уведомления если задана задержка
        if notification_delay and notification_delay > 0:
            asyncio.create_task(_schedule_notification_delete(
                message.bot, message.chat.id, sent_msg.message_id, notification_delay
            ))

        logger.info(
            f"[ContentFilter] Мут применён: user={message.from_user.id}, "
            f"duration={duration_minutes}min"
        )

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось замутить: {e}")


async def _kick_user(
    message: Message,
    result,
    notification_delay: int = None
) -> None:
    """
    Кикает пользователя из группы.

    Args:
        message: Исходное сообщение
        result: Результат проверки
        notification_delay: Задержка автоудаления уведомления (сек) или None
    """
    try:
        # Баним и сразу разбаниваем (эффект кика)
        await message.chat.ban(user_id=message.from_user.id)
        await message.chat.unban(user_id=message.from_user.id)

        # Уведомление
        user_mention = message.from_user.mention_html()
        kick_text = (
            f"👢 {user_mention} исключён из группы.\n"
            f"Причина: запрещённый контент ({result.detector_type})"
        )
        sent_msg = await message.answer(kick_text, parse_mode="HTML")

        # Планируем автоудаление уведомления если задана задержка
        if notification_delay and notification_delay > 0:
            asyncio.create_task(_schedule_notification_delete(
                message.bot, message.chat.id, sent_msg.message_id, notification_delay
            ))

        logger.info(f"[ContentFilter] Кик применён: user={message.from_user.id}")

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось кикнуть: {e}")


async def _ban_user(
    message: Message,
    result,
    custom_text: str = None,
    notification_delay: int = None,
    session: AsyncSession = None
) -> None:
    """
    Банит пользователя в группе.

    Args:
        message: Исходное сообщение
        result: Результат проверки
        custom_text: Кастомный текст уведомления (с %user% плейсхолдером) или None
        notification_delay: Задержка автоудаления уведомления (сек) или None
        session: Сессия БД для сохранения ограничения
    """
    try:
        # Баним навсегда
        await message.chat.ban(user_id=message.from_user.id)

        # Сохраняем бан в БД для восстановления после повторного входа
        if session:
            bot_info = await message.bot.me()
            await save_restriction(
                session=session,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                restriction_type="ban",
                reason="content_filter",
                restricted_by=bot_info.id,
                until_date=None,  # Бан навсегда
            )

        # Уведомление
        user_mention = message.from_user.mention_html()

        # Если есть кастомный текст - используем его с заменой %user%
        if custom_text:
            ban_text = custom_text.replace('%user%', user_mention)
        else:
            # Стандартный текст
            ban_text = (
                f"🚫 {user_mention} заблокирован.\n"
                f"Причина: запрещённый контент ({result.detector_type})"
            )

        sent_msg = await message.answer(ban_text, parse_mode="HTML")

        # Планируем автоудаление уведомления если задана задержка
        if notification_delay and notification_delay > 0:
            asyncio.create_task(_schedule_notification_delete(
                message.bot, message.chat.id, sent_msg.message_id, notification_delay
            ))

        logger.info(f"[ContentFilter] Бан применён: user={message.from_user.id}")

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось забанить: {e}")


async def _forward_and_delete(
    message: Message,
    forward_channel_id: int,
    result,
    notification_delay: int = None
) -> None:
    """
    Пересылает сообщение в указанный канал и удаляет оригинал.

    Используется для действия forward_delete в кастомных разделах.
    Позволяет админам просматривать удалённые сообщения в отдельном канале.

    Args:
        message: Исходное сообщение (уже может быть удалено)
        forward_channel_id: ID канала для пересылки
        result: Результат проверки
        notification_delay: Задержка автоудаления уведомления (сек) или None
    """
    try:
        # Формируем информацию о сообщении и отправителе
        user = message.from_user
        user_mention = user.mention_html() if user else "Unknown"
        user_id = user.id if user else 0
        chat_title = message.chat.title or "Группа"
        chat_id = message.chat.id

        # Получаем текст сообщения
        original_text = message.text or message.caption or ""
        if len(original_text) > 500:
            original_text = original_text[:500] + "..."
        original_safe = html.escape(original_text)

        # Определяем название раздела если есть
        section_name = getattr(result, 'section_name', None) or result.detector_type
        trigger = getattr(result, 'trigger', None) or ""
        trigger_safe = html.escape(trigger[:100]) if trigger else ""

        # Текущее время (МСК = UTC+3)
        now = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # Формируем сообщение для канала
        forward_text = (
            f"🔴 <b>Удалённое сообщение</b>\n\n"
            f"📂 <b>Раздел:</b> {section_name}\n"
            f"🔎 <b>Триггер:</b> <code>{trigger_safe}</code>\n\n"
            f"👤 <b>Пользователь:</b> {user_mention}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"💬 <b>Группа:</b> {html.escape(chat_title)}\n"
            f"🔗 <b>Chat ID:</b> <code>{chat_id}</code>\n\n"
            f"📝 <b>Текст сообщения:</b>\n"
            f"<i>{original_safe}</i>\n\n"
            f"🕐 {time_str}"
        )

        # Отправляем в канал
        await message.bot.send_message(
            chat_id=forward_channel_id,
            text=forward_text,
            parse_mode="HTML"
        )

        logger.info(
            f"[ContentFilter] Сообщение переслано в канал {forward_channel_id}: "
            f"user={user_id}, section={section_name}"
        )

        # Отправляем уведомление в группу (опционально)
        if notification_delay is not None:
            notif_text = (
                f"📤 Сообщение от {user_mention} удалено и сохранено для проверки.\n"
                f"Причина: {section_name}"
            )
            sent_msg = await message.answer(notif_text, parse_mode="HTML")

            # Планируем автоудаление уведомления
            if notification_delay > 0:
                asyncio.create_task(_schedule_notification_delete(
                    message.bot, message.chat.id, sent_msg.message_id, notification_delay
                ))

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось переслать в канал: {e}")
    except Exception as e:
        logger.error(f"[ContentFilter] Ошибка forward_and_delete: {e}")


async def _forward_to_channel(
    message: Message,
    forward_channel_id: int,
    result
) -> None:
    """
    Пересылает информацию о нарушении в указанный канал.

    Используется для опций forward_on_delete, forward_on_mute, forward_on_ban
    в кастомных разделах. Позволяет админам видеть все нарушения в одном месте.

    Args:
        message: Исходное сообщение (может быть уже удалено)
        forward_channel_id: ID канала для пересылки
        result: Результат проверки с информацией о нарушении
    """
    try:
        # Формируем информацию о сообщении и отправителе
        user = message.from_user
        user_mention = user.mention_html() if user else "Unknown"
        user_id = user.id if user else 0
        chat_title = message.chat.title or "Группа"
        chat_id = message.chat.id

        # Получаем текст сообщения
        original_text = message.text or message.caption or ""
        if len(original_text) > 500:
            original_text = original_text[:500] + "..."
        original_safe = html.escape(original_text)

        # Определяем название раздела и триггер
        section_name = getattr(result, 'section_name', None) or result.detector_type
        trigger = getattr(result, 'trigger', None) or ""
        trigger_safe = html.escape(trigger[:100]) if trigger else ""

        # Определяем эмодзи и текст действия
        action = result.action
        action_info = {
            'delete': ('🗑️', 'Удалено'),
            'mute': ('🔇', 'Мут'),
            'ban': ('🚫', 'Бан'),
            'warn': ('⚠️', 'Предупреждение'),
            'kick': ('👢', 'Кик')
        }
        action_emoji, action_text = action_info.get(action, ('❓', action))

        # Текущее время (МСК = UTC+3)
        now = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # Формируем сообщение для канала
        forward_text = (
            f"{action_emoji} <b>Нарушение: {action_text}</b>\n\n"
            f"📂 <b>Раздел:</b> {section_name}\n"
            f"🔎 <b>Триггер:</b> <code>{trigger_safe}</code>\n\n"
            f"👤 <b>Пользователь:</b> {user_mention}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"💬 <b>Группа:</b> {html.escape(chat_title)}\n"
            f"🔗 <b>Chat ID:</b> <code>{chat_id}</code>\n\n"
            f"📝 <b>Текст сообщения:</b>\n"
            f"<i>{original_safe}</i>\n\n"
            f"🕐 {time_str}"
        )

        # Отправляем в канал
        await message.bot.send_message(
            chat_id=forward_channel_id,
            text=forward_text,
            parse_mode="HTML"
        )

        logger.info(
            f"[ContentFilter] 📤 Переслано в канал {forward_channel_id}: "
            f"user={user_id}, action={action}, section={section_name}"
        )

    except TelegramAPIError as e:
        logger.warning(f"[ContentFilter] Не удалось переслать в канал: {e}")
    except Exception as e:
        logger.error(f"[ContentFilter] Ошибка _forward_to_channel: {e}")


# ============================================================
# ОТПРАВКА В ЖУРНАЛ ГРУППЫ
# ============================================================

async def _send_journal_log(
    message: Message,
    result,
    session: AsyncSession
) -> None:
    """
    Отправляет лог о срабатывании фильтра в журнал группы.

    Args:
        message: Исходное сообщение (уже удалено к этому моменту)
        result: Результат проверки фильтра
        session: Сессия БД
    """
    # Получаем данные для лога
    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id

    # Формируем кликабельную ссылку на пользователя
    user_name = user.full_name or user.username or str(user_id)
    user_name_safe = html.escape(user_name)
    user_link = f'<a href="tg://user?id={user_id}">{user_name_safe}</a>'

    # Текущее время (МСК = UTC+3)
    now = datetime.now(timezone.utc) + timedelta(hours=3)
    time_str = now.strftime("%H:%M:%S")

    # Клавиатура для действий (по умолчанию None)
    # Будет заполнена для scam detector
    keyboard = None

    # ─────────────────────────────────────────────────────────
    # WORD FILTER - расширенное логирование
    # ─────────────────────────────────────────────────────────
    if result.detector_type == 'word_filter':
        # Категории слов с эмодзи
        category_names = {
            'simple': ('📝', 'Простые'),
            'harmful': ('💊', 'Вредные'),
            'obfuscated': ('🔀', 'Обфускация')
        }
        cat_emoji, cat_name = category_names.get(
            result.word_category,
            ('🔤', 'Без категории')
        )

        # Текст действия
        action_names = {
            'delete': '🗑️ Удалено',
            'warn': '⚠️ Предупреждение',
            'mute': '🔇 Мут',
            'kick': '👢 Кик',
            'ban': '🚫 Бан'
        }
        action_text = action_names.get(result.action, result.action)

        # Длительность мута/бана
        duration_text = ""
        if result.action in ('mute', 'ban') and result.action_duration:
            hours = result.action_duration // 60
            minutes = result.action_duration % 60
            if hours > 0:
                duration_text = f" {hours}ч"
                if minutes > 0:
                    duration_text += f" {minutes}мин"
            else:
                duration_text = f" {minutes}мин"

        # Триггер (слово)
        trigger_safe = html.escape(result.trigger[:50] if result.trigger else 'N/A')

        # Оригинальный текст сообщения (обрезаем до 150 символов)
        original_text = message.text or message.caption or ''
        if len(original_text) > 150:
            original_text = original_text[:150] + '...'
        original_safe = html.escape(original_text)

        # Формируем сообщение для журнала
        journal_text = (
            f"🔤 <b>Фильтр слов: {cat_emoji} {cat_name}</b>\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔎 Слово: <code>{trigger_safe}</code>\n"
            f"💬 Текст: <i>{original_safe}</i>\n"
            f"⚡ {action_text}{duration_text}\n"
            f"🕐 {time_str}"
        )

    # ─────────────────────────────────────────────────────────
    # SCAM DETECTOR
    # ─────────────────────────────────────────────────────────
    elif result.detector_type == 'scam':
        # Экранируем триггер (сигналы которые сработали)
        trigger_safe = html.escape(result.trigger[:100] if result.trigger else 'N/A')
        # Формируем текст с баллами
        score_text = f" (score: {result.scam_score})" if result.scam_score else ""

        # Полный текст сообщения (до 500 символов для читаемости)
        original_text = message.text or message.caption or ''
        # Обрезаем если слишком длинный
        if len(original_text) > 500:
            original_text = original_text[:500] + '...'
        # Экранируем HTML спецсимволы
        original_safe = html.escape(original_text)

        # Формируем текст для журнала с полной информацией
        journal_text = (
            f"💰 <b>Антискам</b>{score_text}\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔎 Сигналы: <code>{trigger_safe}</code>\n"
            f"💬 <b>Текст:</b>\n<i>{original_safe}</i>\n\n"
            f"⚡ {result.action or 'delete'}\n"
            f"🕐 {time_str}"
        )

        # Создаём клавиатуру с кнопками действий (Mute/Ban)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                # Кнопка мута пользователя
                InlineKeyboardButton(
                    text="🔇 Мут",
                    callback_data=f"mute_user_{user_id}_{chat_id}"
                ),
                # Кнопка бана пользователя
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"ban_user_{user_id}_{chat_id}"
                )
            ]
        ])

    # ─────────────────────────────────────────────────────────
    # FLOOD DETECTOR
    # ─────────────────────────────────────────────────────────
    elif result.detector_type == 'flood':
        deleted_count = len(result.flood_message_ids) if result.flood_message_ids else 0

        journal_text = (
            f"📢 <b>Антифлуд</b>\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔁 Повторов: {result.trigger}\n"
            f"🗑️ Удалено сообщений: {deleted_count}\n"
            f"🕐 {time_str}"
        )

    # ─────────────────────────────────────────────────────────
    # CUSTOM SECTION (кастомные разделы спама)
    # ─────────────────────────────────────────────────────────
    elif result.detector_type == 'custom_section':
        # Название раздела
        section_name = result.section_name or 'Раздел'
        # Триггеры (паттерны которые сработали)
        trigger_safe = html.escape(result.trigger[:100] if result.trigger else 'N/A')
        # Скор
        score_text = f" (score: {result.scam_score})" if result.scam_score else ""

        # Полный текст сообщения
        original_text = message.text or message.caption or ''
        if len(original_text) > 500:
            original_text = original_text[:500] + '...'
        original_safe = html.escape(original_text)

        # Действие
        action_names = {
            'delete': '🗑️ Удалено',
            'mute': '🔇 Мут',
            'ban': '🚫 Бан',
            'forward_delete': '📤 Переслано'
        }
        action_text = action_names.get(result.action, result.action)

        # Формируем текст для журнала
        journal_text = (
            f"📂 <b>Раздел: {html.escape(section_name)}</b>{score_text}\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔎 Паттерны: <code>{trigger_safe}</code>\n"
            f"💬 <b>Текст:</b>\n<i>{original_safe}</i>\n\n"
            f"⚡ {action_text}\n"
            f"🕐 {time_str}"
        )

        # Кнопки модерации
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔇 Мут",
                    callback_data=f"mute_user_{user_id}_{chat_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"ban_user_{user_id}_{chat_id}"
                )
            ]
        ])

    # ─────────────────────────────────────────────────────────
    # FALLBACK - другие детекторы
    # ─────────────────────────────────────────────────────────
    else:
        trigger_safe = html.escape(result.trigger[:100] if result.trigger else 'N/A')

        journal_text = (
            f"🔍 <b>Фильтр контента</b>\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔎 Триггер: <code>{trigger_safe}</code>\n"
            f"⚡ {result.action or 'N/A'}\n"
            f"🕐 {time_str}"
        )

    # Отправляем в журнал (с клавиатурой если есть)
    try:
        await send_journal_event(
            bot=message.bot,
            session=session,
            group_id=chat_id,
            message_text=journal_text,
            reply_markup=keyboard  # Клавиатура с кнопками (для scam detector)
        )
        logger.info(f"[ContentFilter] 📝 Отправлен лог в журнал группы {chat_id}")
    except Exception as e:
        # Не падаем если журнал недоступен
        logger.warning(f"[ContentFilter] Не удалось отправить в журнал: {e}")



# ============================================================
# ХЕНДЛЕР СИСТЕМНЫХ СООБЩЕНИЙ
# ============================================================

@filter_handler_router.message(
    # Фильтр: только группы и супергруппы
    F.chat.type.in_({"group", "supergroup"}),
    # Фильтр: системные сообщения (new_chat_members, left_chat_member, pinned_message и т.д.)
    F.content_type.in_({
        "new_chat_members",
        "left_chat_member",
        "pinned_message",
        "new_chat_title",
        "new_chat_photo",
        "delete_chat_photo",
        "group_chat_created",
        "supergroup_chat_created",
        "migrate_to_chat_id",
        "migrate_from_chat_id"
    })
)
async def system_message_cleanup_handler(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Обработчик системных сообщений для удаления.

    Удаляет системные сообщения если настройка delete_system_messages включена:
    - Вход/выход участников
    - Закреплённые сообщения
    - Изменение названия/фото группы
    - И другие системные сообщения

    Args:
        message: Системное сообщение
        session: Сессия БД
    """
    chat_id = message.chat.id

    # Получаем настройки
    settings = await _filter_manager.get_or_create_settings(chat_id, session)

    # Если удаление системных сообщений выключено - пропускаем
    if not settings.delete_system_messages:
        return

    # Удаляем системное сообщение
    try:
        await message.delete()
        logger.info(
            f"[ContentFilter] 🗑️ Удалено системное сообщение: chat={chat_id}, "
            f"type={message.content_type}"
        )
    except TelegramAPIError as e:
        logger.warning(
            f"[ContentFilter] Ошибка удаления системного сообщения: {e}, "
            f"chat={chat_id}"
        )
