# ============================================================
# ХЕНДЛЕР КОМАНДЫ /stat - СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ
# ============================================================
# Команда для просмотра статистики пользователя в группе.
# Доступна только администраторам и создателю группы.
#
# Использование:
#   /stat           - по реплаю на сообщение пользователя
#   /stat @username - по юзернейму
#   /stat 123456789 - по ID пользователя
#
# Статистика отправляется в ЛС админу для приватности.
# В группе показывается только уведомление (удаляется через 5 сек).
# ============================================================

# Импортируем logging для логирования действий
import logging

# Импортируем asyncio для отложенного удаления сообщений
import asyncio

# Импортируем datetime для работы с датами
from datetime import datetime, timezone

# Импортируем Optional для опциональных типов
from typing import Optional

# Импортируем Router, Bot, F для регистрации хендлеров
from aiogram import Router, Bot, F

# Импортируем типы сообщений
from aiogram.types import Message

# Импортируем типы клавиатур
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импортируем фильтр команд
from aiogram.filters import Command

# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модели из проекта
from bot.database.models_user_stats import UserStatistics
from bot.database.models_profile_monitor import ProfileSnapshot
from bot.database.models_content_filter import FilterViolation


# ============================================================
# НАСТРОЙКА ЛОГГЕРА
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# СОЗДАНИЕ РОУТЕРА
# ============================================================
# Router группирует хендлеры для последующей регистрации в dispatcher
router = Router()

# Устанавливаем имя роутера для отладки
router.name = "user_stats_router"


# ============================================================
# КОНСТАНТЫ
# ============================================================
# Время в секундах, через которое удаляется уведомление в группе
NOTIFICATION_DELETE_DELAY = 5

# ID бота GroupAnonymousBot (используется когда админ пишет анонимно)
GROUP_ANONYMOUS_BOT_ID = 1087968824


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _utcnow_naive() -> datetime:
    """
    Возвращает текущее UTC время без timezone info.
    Используется для совместимости с БД (naive datetime).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_date(dt: Optional[datetime]) -> str:
    """
    Форматирует дату в читаемый вид.

    Args:
        dt: Объект datetime или None

    Returns:
        Строка вида "2025-12-18" или "—" если дата отсутствует
    """
    # Проверяем что дата не None
    if dt is None:
        return "—"

    # Форматируем в ISO формат (только дату)
    return dt.strftime("%Y-%m-%d")


def _format_datetime(dt: Optional[datetime]) -> str:
    """
    Форматирует дату и время в читаемый вид.

    Args:
        dt: Объект datetime или None

    Returns:
        Строка вида "2025-12-18 14:30" или "—" если дата отсутствует
    """
    # Проверяем что дата не None
    if dt is None:
        return "—"

    # Форматируем дату и время
    return dt.strftime("%Y-%m-%d %H:%M")


def _calculate_days_since(dt: Optional[datetime]) -> str:
    """
    Вычисляет количество дней с указанной даты.

    Args:
        dt: Объект datetime или None

    Returns:
        Строка вида "(123 дн.)" или пустая строка если дата отсутствует
    """
    # Проверяем что дата не None
    if dt is None:
        return ""

    # Вычисляем разницу в днях
    now = _utcnow_naive()
    delta = now - dt
    days = delta.days

    # Возвращаем форматированную строку
    return f"({days} дн.)"


def _create_start_bot_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой для перехода в ЛС бота.

    Args:
        bot_username: Username бота (без @)

    Returns:
        InlineKeyboardMarkup с кнопкой перехода в ЛС
    """
    # Создаём кнопку с URL ссылкой на бота
    button = InlineKeyboardButton(
        text="Начать диалог с ботом",
        url=f"https://t.me/{bot_username}"
    )

    # Возвращаем клавиатуру с одной кнопкой
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def _delete_message_later(message: Message, delay: int) -> None:
    """
    Удаляет сообщение через указанное время.

    Args:
        message: Сообщение для удаления
        delay: Задержка в секундах
    """
    # Ждём указанное время
    await asyncio.sleep(delay)

    # Пытаемся удалить сообщение
    try:
        await message.delete()
    except TelegramAPIError as e:
        # Игнорируем ошибки удаления (сообщение могло быть уже удалено)
        logger.debug(f"[STAT] Не удалось удалить уведомление: {e}")


async def _get_user_id_from_username(
    bot: Bot,
    username: str,
    chat_id: int
) -> Optional[int]:
    """
    Получает user_id по username через поиск в участниках чата.

    ВАЖНО: Telegram не предоставляет прямой API для получения user_id по username.
    Этот метод работает только если пользователь есть в чате.

    Args:
        bot: Экземпляр бота
        username: Username пользователя (с или без @)
        chat_id: ID чата для поиска

    Returns:
        user_id если найден, иначе None
    """
    # Убираем @ из начала username если есть
    username = username.lstrip("@").lower()

    # К сожалению, Telegram Bot API не позволяет искать по username
    # Можно только получить информацию о конкретном user_id
    # Поэтому возвращаем None - пользователь должен указать ID
    logger.debug(f"[STAT] Поиск по username не поддерживается API: @{username}")

    return None


async def _check_is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором группы.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        True если пользователь - админ или создатель, иначе False
    """
    # Анонимный админ - только админы могут писать анонимно
    if user_id == GROUP_ANONYMOUS_BOT_ID:
        logger.debug(f"[STAT] Анонимный админ в чате {chat_id}")
        return True

    try:
        # Получаем информацию о пользователе в чате
        member = await bot.get_chat_member(chat_id, user_id)

        # Проверяем статус: creator или administrator
        if member.status in ('creator', 'administrator'):
            return True

        return False

    except TelegramAPIError as e:
        # Ошибка API - логируем и возвращаем False (безопасно)
        logger.warning(
            f"[STAT] Ошибка проверки админа: {e}, "
            f"chat={chat_id}, user={user_id}"
        )
        return False


async def _get_user_statistics(
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> Optional[UserStatistics]:
    """
    Получает статистику пользователя из таблицы user_statistics.

    Args:
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        UserStatistics или None если записи нет
    """
    # Формируем запрос на получение статистики
    query = select(UserStatistics).where(
        UserStatistics.chat_id == chat_id,
        UserStatistics.user_id == user_id
    )

    # Выполняем запрос
    result = await session.execute(query)

    # Возвращаем первую запись или None
    return result.scalar_one_or_none()


async def _get_profile_snapshot(
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> Optional[ProfileSnapshot]:
    """
    Получает снимок профиля пользователя из таблицы profile_snapshots.

    ВАЖНО: Мы только ЧИТАЕМ из profile_snapshots, не модифицируем!

    Args:
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        ProfileSnapshot или None если записи нет
    """
    # Формируем запрос на получение снимка
    query = select(ProfileSnapshot).where(
        ProfileSnapshot.chat_id == chat_id,
        ProfileSnapshot.user_id == user_id
    )

    # Выполняем запрос
    result = await session.execute(query)

    # Возвращаем первую запись или None
    return result.scalar_one_or_none()


async def _get_violations_count(
    session: AsyncSession,
    chat_id: int,
    user_id: int
) -> int:
    """
    Подсчитывает количество нарушений пользователя в группе.

    Args:
        session: Сессия БД
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        Количество нарушений (0 если записей нет)
    """
    # Формируем запрос на подсчёт нарушений
    query = select(func.count(FilterViolation.id)).where(
        FilterViolation.chat_id == chat_id,
        FilterViolation.user_id == user_id
    )

    # Выполняем запрос
    result = await session.execute(query)

    # Возвращаем количество
    return result.scalar() or 0


def _build_stat_message(
    user_id: int,
    full_name: Optional[str],
    username: Optional[str],
    snapshot: Optional[ProfileSnapshot],
    stats: Optional[UserStatistics],
    violations_count: int
) -> str:
    """
    Формирует текст сообщения со статистикой пользователя.

    Args:
        user_id: ID пользователя
        full_name: Полное имя пользователя
        username: Username пользователя
        snapshot: Снимок профиля из profile_snapshots
        stats: Статистика из user_statistics
        violations_count: Количество нарушений

    Returns:
        Отформатированный текст статистики
    """
    # Формируем заголовок с именем пользователя
    name_display = full_name or "Неизвестно"

    # Добавляем username если есть
    username_display = f"@{username}" if username else ""

    # Начинаем формировать сообщение
    lines = [
        f"<b>Статус</b> {username_display} #user{user_id}",
        f"<b>Имя:</b> {name_display}",
        "",
    ]

    # ─────────────────────────────────────────────────────────
    # ДАННЫЕ ИЗ PROFILE_SNAPSHOT (если есть)
    # ─────────────────────────────────────────────────────────
    if snapshot:
        # Дата первого входа
        joined_date = _format_date(snapshot.joined_at)
        joined_days = _calculate_days_since(snapshot.joined_at)
        lines.append(f"<b>Первый вход:</b> {joined_date} {joined_days}")

        # Возраст аккаунта (если есть)
        if snapshot.account_age_days is not None:
            lines.append(f"<b>Возраст аккаунта:</b> {snapshot.account_age_days} дн.")

        # Premium статус
        premium_status = "Да" if snapshot.is_premium else "Нет"
        lines.append(f"<b>Premium:</b> {premium_status}")

        # Фото профиля
        photo_status = "Есть" if snapshot.has_photo else "Нет"
        lines.append(f"<b>Фото профиля:</b> {photo_status}")

        lines.append("")
    else:
        # Нет снимка профиля
        lines.append("<i>Нет данных о профиле</i>")
        lines.append("")

    # ─────────────────────────────────────────────────────────
    # ДАННЫЕ ИЗ USER_STATISTICS (если есть)
    # ─────────────────────────────────────────────────────────
    if stats:
        # Количество сообщений
        lines.append(f"<b>Сообщений:</b> {stats.message_count}")

        # Дней активности
        lines.append(f"<b>Дней активности:</b> {stats.active_days}")

        # Последнее сообщение
        last_msg = _format_datetime(stats.last_message_at)
        lines.append(f"<b>Последнее сообщение:</b> {last_msg}")

        lines.append("")
    else:
        # Нет статистики сообщений
        lines.append("<b>Сообщений:</b> 0")
        lines.append("<b>Дней активности:</b> 0")
        lines.append("")

    # ─────────────────────────────────────────────────────────
    # НАРУШЕНИЯ
    # ─────────────────────────────────────────────────────────
    lines.append(f"<b>Нарушений:</b> {violations_count}")

    # Объединяем все строки
    return "\n".join(lines)


# ============================================================
# ОСНОВНОЙ ХЕНДЛЕР КОМАНДЫ /stat
# ============================================================


@router.message(Command("stat"), F.chat.type.in_({"group", "supergroup"}))
async def stat_command_handler(
    message: Message,
    session: AsyncSession,
    bot: Bot
) -> None:
    """
    Обработчик команды /stat В ГРУППАХ.

    Показывает статистику пользователя в группе.
    Доступна только администраторам и создателю группы.

    Использование:
        /stat           - по реплаю на сообщение пользователя
        /stat 123456789 - по ID пользователя

    Args:
        message: Входящее сообщение с командой
        session: Сессия БД (инжектируется middleware)
        bot: Экземпляр бота (инжектируется middleware)
    """
    # Получаем ID группы и пользователя-админа
    chat_id = message.chat.id
    admin_user_id = message.from_user.id

    # Логируем вызов команды
    logger.info(
        f"[STAT] Вызов команды: chat={chat_id}, admin={admin_user_id}"
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 2: Проверка прав администратора
    # ─────────────────────────────────────────────────────────
    # Только админы и создатель могут использовать эту команду
    is_admin = await _check_is_admin(bot, chat_id, admin_user_id)

    if not is_admin:
        # Пользователь не админ - отказываем
        reply = await message.reply("Эта команда доступна только администраторам.")

        # Удаляем сообщение через 5 секунд
        asyncio.create_task(_delete_message_later(reply, NOTIFICATION_DELETE_DELAY))

        # Удаляем команду пользователя тоже
        try:
            await message.delete()
        except TelegramAPIError:
            pass

        return

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА 3: Получаем ID пользователя для статистики
    # ─────────────────────────────────────────────────────────
    target_user_id: Optional[int] = None
    target_full_name: Optional[str] = None
    target_username: Optional[str] = None

    # Вариант 1: По реплаю на сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        # Берём данные из сообщения на которое ответили
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_full_name = target_user.full_name
        target_username = target_user.username

        logger.info(
            f"[STAT] Получен user_id из реплая: {target_user_id}"
        )

    else:
        # Вариант 2: Из аргументов команды
        # Парсим текст команды для извлечения аргумента
        command_text = message.text or ""
        parts = command_text.split(maxsplit=1)

        if len(parts) > 1:
            # Есть аргумент после /stat
            arg = parts[1].strip()

            # Проверяем: это ID (число) или username?
            if arg.isdigit():
                # Это числовой ID
                target_user_id = int(arg)
                logger.info(f"[STAT] Получен user_id из аргумента: {target_user_id}")

            elif arg.startswith("@"):
                # Это username - пробуем найти
                # К сожалению, Bot API не позволяет искать по username напрямую
                reply = await message.reply(
                    "Поиск по @username не поддерживается Telegram API.\n"
                    "Используйте /stat по реплаю или укажите числовой ID."
                )
                asyncio.create_task(
                    _delete_message_later(reply, NOTIFICATION_DELETE_DELAY)
                )
                return

            else:
                # Неизвестный формат
                reply = await message.reply(
                    "Неверный формат. Используйте:\n"
                    "/stat - по реплаю\n"
                    "/stat 123456789 - по ID"
                )
                asyncio.create_task(
                    _delete_message_later(reply, NOTIFICATION_DELETE_DELAY)
                )
                return

    # Если не удалось получить user_id
    if target_user_id is None:
        reply = await message.reply(
            "Укажите пользователя:\n"
            "• Ответьте на сообщение пользователя командой /stat\n"
            "• Или укажите ID: /stat 123456789"
        )
        asyncio.create_task(_delete_message_later(reply, NOTIFICATION_DELETE_DELAY))
        return

    # ─────────────────────────────────────────────────────────
    # СБОР ДАННЫХ О ПОЛЬЗОВАТЕЛЕ
    # ─────────────────────────────────────────────────────────
    # Получаем данные из разных таблиц

    # 1. Снимок профиля (только чтение!)
    snapshot = await _get_profile_snapshot(session, chat_id, target_user_id)

    # Если есть снимок - берём имя и username оттуда (если не получили из реплая)
    if snapshot and not target_full_name:
        target_full_name = snapshot.full_name
        target_username = snapshot.username

    # 2. Статистика сообщений
    stats = await _get_user_statistics(session, chat_id, target_user_id)

    # 3. Количество нарушений
    violations_count = await _get_violations_count(session, chat_id, target_user_id)

    # ─────────────────────────────────────────────────────────
    # ФОРМИРОВАНИЕ СООБЩЕНИЯ СО СТАТИСТИКОЙ
    # ─────────────────────────────────────────────────────────
    stat_text = _build_stat_message(
        user_id=target_user_id,
        full_name=target_full_name,
        username=target_username,
        snapshot=snapshot,
        stats=stats,
        violations_count=violations_count
    )

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА СТАТИСТИКИ
    # ─────────────────────────────────────────────────────────
    # Удаляем команду пользователя сразу
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    # Анонимный админ - показываем статистику в группе
    if admin_user_id == GROUP_ANONYMOUS_BOT_ID:
        logger.info(
            f"[STAT] Анонимный админ - показываем в группе: "
            f"target={target_user_id}, chat={chat_id}"
        )

        # Отправляем статистику в группу
        notification = await bot.send_message(
            chat_id=chat_id,
            text=stat_text,
            parse_mode="HTML"
        )

        # Удаляем через 30 секунд (больше времени чтобы прочитать)
        asyncio.create_task(_delete_message_later(notification, 30))
        return

    # Обычный админ - отправляем в ЛС
    try:
        # Пытаемся отправить статистику в ЛС админу
        await bot.send_message(
            chat_id=admin_user_id,
            text=stat_text,
            parse_mode="HTML"
        )

        # Успешно отправили - уведомляем в группе
        notification = await message.answer("Статистика отправлена в личные сообщения.")

        # Удаляем уведомление через 5 секунд
        asyncio.create_task(
            _delete_message_later(notification, NOTIFICATION_DELETE_DELAY)
        )

        # Логируем успешную отправку
        logger.info(
            f"[STAT] Статистика отправлена в ЛС: "
            f"admin={admin_user_id}, target={target_user_id}, chat={chat_id}"
        )

    except TelegramAPIError as e:
        # Ошибка отправки в ЛС
        error_msg = str(e).lower()

        # Получаем username бота для кнопки
        bot_info = await bot.me()
        bot_username = bot_info.username

        # ─────────────────────────────────────────────────────
        # Случай: Админ не начал диалог с ботом
        # ─────────────────────────────────────────────────────
        if "can't initiate" in error_msg or "bot was blocked" in error_msg:
            # Админ не начал диалог с ботом
            logger.warning(
                f"[STAT] Админ не начал диалог с ботом: admin={admin_user_id}"
            )

            # Формируем сообщение с кнопкой
            notification = await message.answer(
                "Не могу отправить статистику в ЛС.\n"
                "Пожалуйста, начните диалог с ботом и повторите команду.",
                reply_markup=_create_start_bot_keyboard(bot_username)
            )

            # Удаляем уведомление через 10 секунд (даём время нажать кнопку)
            asyncio.create_task(_delete_message_later(notification, 10))

        else:
            # Другая ошибка - логируем
            logger.error(
                f"[STAT] Ошибка отправки в ЛС: {e}, admin={admin_user_id}"
            )

            # Показываем общую ошибку
            notification = await message.answer(
                f"Ошибка отправки статистики: {e}"
            )

            # Удаляем через 5 секунд
            asyncio.create_task(
                _delete_message_later(notification, NOTIFICATION_DELETE_DELAY)
            )


# ============================================================
# ХЕНДЛЕР КОМАНДЫ /stat В ЛС БОТА
# ============================================================


@router.message(Command("stat"), F.chat.type == "private")
async def stat_dm_command_handler(
    message: Message,
    session: AsyncSession,
    bot: Bot
) -> None:
    """
    Обработчик команды /stat в личных сообщениях бота.

    Позволяет получить статистику пользователя из любой группы,
    если вызывающий является администратором этой группы.

    Использование:
        /stat <group_id> <user_id>

    Args:
        message: Входящее сообщение с командой
        session: Сессия БД (инжектируется middleware)
        bot: Экземпляр бота (инжектируется middleware)
    """
    # Получаем ID пользователя
    user_id = message.from_user.id

    # Парсим аргументы команды
    command_text = message.text or ""
    parts = command_text.split()

    # Проверяем формат: /stat <group_id> <user_id>
    if len(parts) != 3:
        await message.reply(
            "<b>Использование команды /stat в ЛС:</b>\n\n"
            "<code>/stat &lt;group_id&gt; &lt;user_id&gt;</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/stat -1001234567890 123456789</code>\n\n"
            "<b>Как узнать ID группы:</b>\n"
            "• Перешлите любое сообщение из группы боту @userinfobot\n"
            "• Или используйте команду в группе: /stat (по реплаю)",
            parse_mode="HTML"
        )
        return

    # Парсим group_id и target_user_id
    try:
        group_id = int(parts[1])
        target_user_id = int(parts[2])
    except ValueError:
        await message.reply(
            "Неверный формат. ID должны быть числами.\n\n"
            "Пример: <code>/stat -1001234567890 123456789</code>",
            parse_mode="HTML"
        )
        return

    # Логируем вызов
    logger.info(
        f"[STAT-DM] Вызов команды: user={user_id}, group={group_id}, target={target_user_id}"
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА ПРАВ: пользователь должен быть админом группы
    # ─────────────────────────────────────────────────────────
    is_admin = await _check_is_admin(bot, group_id, user_id)

    if not is_admin:
        await message.reply(
            "Вы не являетесь администратором указанной группы.\n"
            "Команда /stat доступна только администраторам."
        )
        return

    # ─────────────────────────────────────────────────────────
    # СБОР ДАННЫХ О ПОЛЬЗОВАТЕЛЕ
    # ─────────────────────────────────────────────────────────
    # 1. Снимок профиля (только чтение!)
    snapshot = await _get_profile_snapshot(session, group_id, target_user_id)

    # Берём имя и username из снимка
    target_full_name = snapshot.full_name if snapshot else None
    target_username = snapshot.username if snapshot else None

    # 2. Статистика сообщений
    stats = await _get_user_statistics(session, group_id, target_user_id)

    # 3. Количество нарушений
    violations_count = await _get_violations_count(session, group_id, target_user_id)

    # ─────────────────────────────────────────────────────────
    # ФОРМИРОВАНИЕ И ОТПРАВКА СТАТИСТИКИ
    # ─────────────────────────────────────────────────────────
    stat_text = _build_stat_message(
        user_id=target_user_id,
        full_name=target_full_name,
        username=target_username,
        snapshot=snapshot,
        stats=stats,
        violations_count=violations_count
    )

    # Добавляем информацию о группе
    try:
        chat_info = await bot.get_chat(group_id)
        group_name = chat_info.title or f"ID: {group_id}"
    except TelegramAPIError:
        group_name = f"ID: {group_id}"

    stat_text = f"<b>Группа:</b> {group_name}\n\n" + stat_text

    # Отправляем статистику
    await message.reply(stat_text, parse_mode="HTML")

    logger.info(
        f"[STAT-DM] Статистика отправлена: user={user_id}, group={group_id}, target={target_user_id}"
    )
