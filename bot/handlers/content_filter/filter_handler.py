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
# Импортируем типы сообщений
from aiogram.types import Message
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
    try:
        # Получаем информацию о пользователе в чате
        member = await message.bot.get_chat_member(chat_id, user_id)
        # Проверяем статус: creator или administrator
        if member.status in ('creator', 'administrator'):
            # Админ - пропускаем без фильтрации
            return
    except TelegramAPIError as e:
        # Ошибка API - логируем и продолжаем (лучше проверить чем пропустить)
        logger.warning(
            f"[ContentFilter] Ошибка проверки админа: {e}, "
            f"chat={chat_id}, user={user_id}"
        )

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
        await _apply_action(message, result, settings)

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
    settings
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
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    action = result.action

    # ─────────────────────────────────────────────────────────
    # Получаем настройки задержек для категории (если word_filter)
    # ─────────────────────────────────────────────────────────
    delete_delay = None
    notification_delay = None
    custom_mute_text = None
    custom_ban_text = None

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

    if action == 'delete':
        # Только удаление - уже сделано выше
        pass

    elif action == 'warn':
        # Отправляем предупреждение
        await _send_warning(message, result, notification_delay)

    elif action == 'mute':
        # Мутим пользователя
        duration_minutes = result.action_duration or 1440  # 24 часа по умолчанию
        await _mute_user(message, duration_minutes, result, custom_mute_text, notification_delay)

    elif action == 'kick':
        # Кикаем пользователя
        await _kick_user(message, result, notification_delay)

    elif action == 'ban':
        # Баним пользователя
        await _ban_user(message, result, custom_ban_text, notification_delay)

    else:
        # Неизвестное действие - логируем
        logger.warning(f"[ContentFilter] Неизвестное действие: {action}")


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
    notification_delay: int = None
) -> None:
    """
    Отправляет предупреждение пользователю в группу.

    Args:
        message: Исходное сообщение
        result: Результат проверки
        notification_delay: Задержка автоудаления уведомления (сек) или None
    """
    try:
        # Формируем текст предупреждения
        user_mention = message.from_user.mention_html()
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
    notification_delay: int = None
) -> None:
    """
    Мутит пользователя на указанное время.

    Args:
        message: Исходное сообщение
        duration_minutes: Длительность мута в минутах
        result: Результат проверки
        custom_text: Кастомный текст уведомления (с %user% плейсхолдером) или None
        notification_delay: Задержка автоудаления уведомления (сек) или None
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
    notification_delay: int = None
) -> None:
    """
    Банит пользователя в группе.

    Args:
        message: Исходное сообщение
        result: Результат проверки
        custom_text: Кастомный текст уведомления (с %user% плейсхолдером) или None
        notification_delay: Задержка автоудаления уведомления (сек) или None
    """
    try:
        # Баним навсегда
        await message.chat.ban(user_id=message.from_user.id)

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
        trigger_safe = html.escape(result.trigger[:80] if result.trigger else 'N/A')
        score_text = f" (score: {result.scam_score})" if result.scam_score else ""

        journal_text = (
            f"💰 <b>Антискам</b>{score_text}\n\n"
            f"👤 {user_link} [<code>{user_id}</code>]\n"
            f"🔎 Сигналы: <code>{trigger_safe}</code>\n"
            f"⚡ {result.action or 'delete'}\n"
            f"🕐 {time_str}"
        )

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

    # Отправляем в журнал
    try:
        await send_journal_event(
            bot=message.bot,
            session=session,
            group_id=chat_id,
            message_text=journal_text
        )
        logger.info(f"[ContentFilter] 📝 Отправлен лог в журнал группы {chat_id}")
    except Exception as e:
        # Не падаем если журнал недоступен
        logger.warning(f"[ContentFilter] Не удалось отправить в журнал: {e}")
