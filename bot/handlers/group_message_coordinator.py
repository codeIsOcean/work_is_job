# ============================================================
# GROUP MESSAGE COORDINATOR - ЕДИНАЯ ТОЧКА ВХОДА
# ============================================================
# Этот координатор решает проблему конфликта хендлеров в aiogram 3.x:
# когда несколько хендлеров имеют одинаковый фильтр (message + group),
# только первый выполняется. Координатор объединяет их в один.
#
# Порядок проверки сообщений:
# 1. ContentFilter (слова, скам, флуд) - если сработал, Antispam не нужен
# 2. Antispam (ссылки, пересылки, цитаты) - проверяется только если CF пропустил
#
# Это паттерн "Single Entry Point" / "Message Coordinator"
# ============================================================

# Импортируем Router для создания единого роутера
from aiogram import Router, F
# Импортируем типы сообщений
from aiogram.types import Message
# Импортируем исключения Telegram API
from aiogram.exceptions import TelegramAPIError
# Импортируем логгер
import logging

# Импортируем типы SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# ============================================================
# ИМПОРТ ЛОГИКИ ИЗ СУЩЕСТВУЮЩИХ МОДУЛЕЙ
# ============================================================

# ContentFilter - импортируем FilterManager и функции применения действий
from bot.services.content_filter import FilterManager
# Импортируем функции применения действий из filter_handler
from bot.handlers.content_filter.filter_handler import (
    _apply_action as content_filter_apply_action,
    _send_journal_log as content_filter_send_journal_log,
    _filter_manager
)

# Antispam - импортируем функцию проверки и типы
from bot.services.antispam import check_message_for_spam, AntiSpamDecision
# Импортируем типы действий
from bot.database.models_antispam import ActionType
# Импортируем вспомогательные функции из antispam_filter_handler
from bot.handlers.antispam_handlers.antispam_filter_handler import (
    schedule_message_deletion,
    get_warning_ttl,
    is_user_admin
)
# Импортируем функцию логирования в журнал группы
from bot.services.group_journal_service import send_journal_event

# MessageManagement - импортируем функции фильтрации
from bot.handlers.message_management.filter_handler import (
    process_command_message,
    process_system_message,
    process_pin_event,
    is_system_message,
    is_command_message
)

# Импорт для ограничения прав (мут)
from aiogram.types import ChatPermissions
# Импорт для работы со временем
from datetime import timedelta
# Импорт исключений
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер координатора
# Этот роутер заменит content_filter_router и antispam_filter_router
group_message_coordinator_router = Router(name='group_message_coordinator')


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def _is_admin(bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором.

    Эта проверка вынесена в отдельную функцию чтобы выполняться
    только один раз для обоих фильтров (оптимизация).

    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        bool: True если админ, False если нет
    """
    try:
        # Получаем информацию о пользователе в чате
        member = await bot.get_chat_member(chat_id, user_id)
        # Проверяем статус: creator или administrator
        return member.status in ('creator', 'administrator')
    except TelegramAPIError as e:
        # Ошибка API - логируем и считаем что не админ (безопасный подход)
        logger.warning(
            f"[COORDINATOR] Ошибка проверки админа: {e}, "
            f"chat={chat_id}, user={user_id}"
        )
        return False


# ============================================================
# ОСНОВНОЙ КООРДИНАТОР
# ============================================================

@group_message_coordinator_router.message(
    # Фильтр: только группы и супергруппы
    F.chat.type.in_({"group", "supergroup"})
)
async def group_message_handler(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Единый обработчик сообщений в группах.

    Координирует работу всех фильтров:
    1. ContentFilter (слова, скам, флуд)
    2. Antispam (ссылки, пересылки, цитаты)

    Если ContentFilter срабатывает - Antispam пропускается.
    Это логично: если сообщение уже обработано (удалено/наказан),
    нет смысла проверять его повторно.

    Args:
        message: Входящее сообщение
        session: Сессия БД (инжектится middleware)
    """
    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА: Есть ли автор сообщения
    # ─────────────────────────────────────────────────────────
    # Сообщения от каналов или системные могут не иметь автора
    if not message.from_user:
        # Пропускаем сообщения без автора
        return

    # Получаем ID группы и пользователя
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Логируем что координатор получил сообщение
    logger.info(
        f"[COORDINATOR] 📥 Сообщение: chat={chat_id}, user={user_id}, "
        f"text={message.text[:50] if message.text else 'N/A'}..."
    )

    # ─────────────────────────────────────────────────────────
    # ШАГ 0: MESSAGE MANAGEMENT - системные сообщения и репин
    # ─────────────────────────────────────────────────────────
    # Системные сообщения обрабатываются ДО проверки админа,
    # т.к. они могут удаляться независимо от автора

    # Проверяем репин (автозакреп) - срабатывает на событие закрепления
    if is_system_message(message):
        # Проверяем закреп для репина
        await process_pin_event(message, session)

        # Проверяем нужно ли удалить системное сообщение
        if await process_system_message(message, session):
            logger.info(f"[COORDINATOR] Системное сообщение удалено MessageManagement")
            return

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА: Автор - админ? (выполняем ОДИН раз для всех фильтров)
    # ─────────────────────────────────────────────────────────
    # Админы не подвергаются фильтрации ContentFilter и Antispam
    # Но удаление команд админов зависит от настройки delete_admin_commands
    is_admin = await _is_admin(message.bot, chat_id, user_id)

    # ─────────────────────────────────────────────────────────
    # ШАГ 0.5: MESSAGE MANAGEMENT - удаление команд
    # ─────────────────────────────────────────────────────────
    # Удаление команд работает И для админов (если включено delete_admin_commands)
    if is_command_message(message):
        if await process_command_message(message, session):
            logger.info(f"[COORDINATOR] Команда удалена MessageManagement")
            return

    # Админы пропускаются для ContentFilter и Antispam
    if is_admin:
        logger.debug(f"[COORDINATOR] Пользователь {user_id} - админ, пропускаем CF/AS")
        return

    # ─────────────────────────────────────────────────────────
    # ШАГ 1: CONTENT FILTER (слова, скам, флуд)
    # ─────────────────────────────────────────────────────────
    # Проверяем сообщение через ContentFilter
    content_filter_triggered = await _process_content_filter(message, session)

    # Если ContentFilter сработал - Antispam пропускаем
    # Сообщение уже обработано (удалено/наказан)
    if content_filter_triggered:
        logger.info(f"[COORDINATOR] ContentFilter сработал, пропускаем Antispam")
        return

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: ANTISPAM (ссылки, пересылки, цитаты)
    # ─────────────────────────────────────────────────────────
    # ContentFilter не сработал - проверяем Antispam
    await _process_antispam(message, session)


# ============================================================
# ОБРАБОТКА CONTENT FILTER
# ============================================================

async def _process_content_filter(
    message: Message,
    session: AsyncSession
) -> bool:
    """
    Обрабатывает сообщение через ContentFilter.

    Логика извлечена из filter_handler.py с минимальными изменениями.

    Args:
        message: Входящее сообщение
        session: Сессия БД

    Returns:
        bool: True если фильтр сработал, False если пропущен
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        # Проверяем сообщение всеми фильтрами ContentFilter
        result = await _filter_manager.check_message(message, session)

        # Логируем результат проверки
        logger.info(
            f"[COORDINATOR/CF] 🔍 Результат: chat={chat_id}, "
            f"should_act={result.should_act}, detector={result.detector_type}, "
            f"trigger={result.trigger}"
        )

        # Если фильтр не сработал - возвращаем False
        if not result.should_act:
            return False

        # ─────────────────────────────────────────────────────
        # ФИЛЬТР СРАБОТАЛ - применяем действие
        # ─────────────────────────────────────────────────────
        logger.info(
            f"[COORDINATOR/CF] ⚡ Срабатывание: chat={chat_id}, user={user_id}, "
            f"detector={result.detector_type}, trigger={result.trigger}, "
            f"action={result.action}"
        )

        # Получаем настройки для применения кастомных действий
        settings = await _filter_manager.get_or_create_settings(chat_id, session)

        # Применяем действие (delete, warn, mute, ban)
        await content_filter_apply_action(message, result, settings, session)

        # Логируем нарушение в БД
        await _filter_manager.log_violation(message, result, session)

        # Отправляем событие в журнал группы (если включено)
        if settings.log_violations:
            await content_filter_send_journal_log(message, result, session)

        # Фильтр сработал
        return True

    except Exception as e:
        # Логируем ошибку, но не падаем
        logger.exception(
            f"[COORDINATOR/CF] Ошибка обработки: {e}, "
            f"chat={chat_id}, user={user_id}"
        )
        # При ошибке считаем что фильтр не сработал
        return False


# ============================================================
# ОБРАБОТКА ANTISPAM
# ============================================================

async def _process_antispam(
    message: Message,
    session: AsyncSession
) -> bool:
    """
    Обрабатывает сообщение через Antispam.

    Логика извлечена из antispam_filter_handler.py с минимальными изменениями.
    Проверка админа уже выполнена в координаторе - здесь не дублируем.

    Args:
        message: Входящее сообщение
        session: Сессия БД

    Returns:
        bool: True если спам обнаружен и обработан, False если нет
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        # Вызываем основную функцию проверки на спам
        decision: AntiSpamDecision = await check_message_for_spam(message, session)

        # Если сообщение не является спамом - возвращаем False
        if not decision.is_spam:
            logger.debug(f"[COORDINATOR/AS] Сообщение не является спамом")
            return False

        # ─────────────────────────────────────────────────────
        # СПАМ ОБНАРУЖЕН - применяем действие
        # ─────────────────────────────────────────────────────
        logger.warning(
            f"[COORDINATOR/AS] ⚠️ Обнаружен спам! Правило: {decision.triggered_rule_type}, "
            f"Действие: {decision.action}, Причина: {decision.reason}"
        )

        # Получаем TTL для предупреждений (для авто-удаления)
        warning_ttl = await get_warning_ttl(session, chat_id)

        # Удаляем сообщение если это указано в правиле ИЛИ если действие DELETE
        should_delete = decision.delete_message or decision.action == ActionType.DELETE
        if should_delete:
            try:
                await message.delete()
                logger.info(f"[COORDINATOR/AS] 🗑️ Сообщение удалено (message_id={message.message_id})")
            except TelegramBadRequest as e:
                logger.error(f"[COORDINATOR/AS] Не удалось удалить сообщение: {e}")
            except TelegramForbiddenError:
                logger.error("[COORDINATOR/AS] У бота нет прав на удаление сообщений")

        # ─────────────────────────────────────────────────────
        # ПРИМЕНЯЕМ ДЕЙСТВИЕ
        # ─────────────────────────────────────────────────────
        await _apply_antispam_action(message, session, decision, warning_ttl)

        # Спам обнаружен и обработан
        return True

    except Exception as e:
        # Ловим все неожиданные ошибки чтобы не упал весь бот
        logger.error(
            f"[COORDINATOR/AS] Неожиданная ошибка: {e}",
            exc_info=True
        )
        return False


async def _apply_antispam_action(
    message: Message,
    session: AsyncSession,
    decision: AntiSpamDecision,
    warning_ttl: int
) -> None:
    """
    Применяет действие антиспама к нарушителю.

    Логика извлечена из antispam_filter_handler.py.

    Args:
        message: Сообщение-нарушитель
        session: Сессия БД
        decision: Решение антиспама
        warning_ttl: TTL для автоудаления предупреждений
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: DELETE - только удалить сообщение
    # ─────────────────────────────────────────────────────────
    if decision.action == ActionType.DELETE:
        logger.info(f"[COORDINATOR/AS] Действие DELETE для пользователя {user_id}")
        # Логируем в журнал группы
        await send_journal_event(
            bot=message.bot,
            session=session,
            group_id=chat_id,
            message_text=(
                f"🗑️ <b>Антиспам: Удаление</b>\n\n"
                f"👤 Пользователь: {message.from_user.mention_html()} "
                f"[<code>{user_id}</code>]\n"
                f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                f"💬 Причина: {decision.reason}\n"
                f"🗑️ Сообщение удалено: Да"
            )
        )

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: WARN - предупреждение
    # ─────────────────────────────────────────────────────────
    elif decision.action == ActionType.WARN:
        try:
            # Формируем текст предупреждения
            warning_text = (
                f"⚠️ <b>Предупреждение</b>\n\n"
                f"Пользователь {message.from_user.mention_html()}, "
                f"ваше сообщение нарушает правила:\n"
                f"<i>{decision.reason}</i>"
            )
            # Отправляем предупреждение
            sent_msg = await message.answer(warning_text, parse_mode="HTML")
            logger.info(f"[COORDINATOR/AS] Отправлено предупреждение пользователю {user_id}")

            # Планируем авто-удаление если настроен TTL
            if warning_ttl > 0:
                await schedule_message_deletion(sent_msg, warning_ttl)

            # Логируем в журнал группы
            await send_journal_event(
                bot=message.bot,
                session=session,
                group_id=chat_id,
                message_text=(
                    f"⚠️ <b>Антиспам: Предупреждение</b>\n\n"
                    f"👤 Пользователь: {message.from_user.mention_html()} "
                    f"[<code>{user_id}</code>]\n"
                    f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                    f"💬 Причина: {decision.reason}\n"
                    f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                )
            )
        except Exception as e:
            logger.error(f"[COORDINATOR/AS] Ошибка при отправке предупреждения: {e}")

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: KICK - исключение из чата
    # ─────────────────────────────────────────────────────────
    elif decision.action == ActionType.KICK:
        try:
            # Баним и сразу разбаниваем (эффект кика)
            await message.bot.ban_chat_member(chat_id, user_id)
            await message.bot.unban_chat_member(chat_id, user_id)
            logger.info(f"[COORDINATOR/AS] Пользователь {user_id} исключен из чата")

            # Отправляем уведомление
            try:
                kick_text = (
                    f"👢 Пользователь {message.from_user.mention_html()} "
                    f"исключен из чата.\n"
                    f"<i>Причина: {decision.reason}</i>"
                )
                sent_msg = await message.answer(kick_text, parse_mode="HTML")
                if warning_ttl > 0:
                    await schedule_message_deletion(sent_msg, warning_ttl)
            except Exception:
                pass

            # Логируем в журнал группы
            await send_journal_event(
                bot=message.bot,
                session=session,
                group_id=chat_id,
                message_text=(
                    f"👢 <b>Антиспам: Исключение</b>\n\n"
                    f"👤 Пользователь: {message.from_user.mention_html()} "
                    f"[<code>{user_id}</code>]\n"
                    f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                    f"💬 Причина: {decision.reason}\n"
                    f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                )
            )

        except TelegramBadRequest as e:
            logger.error(f"[COORDINATOR/AS] Не удалось кикнуть пользователя: {e}")
        except TelegramForbiddenError:
            logger.error("[COORDINATOR/AS] У бота нет прав на исключение участников")

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: RESTRICT - мут
    # ─────────────────────────────────────────────────────────
    elif decision.action == ActionType.RESTRICT:
        try:
            # Создаем объект с пустыми правами (полный мут)
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
            )

            # Определяем время ограничения
            until_date = None
            if decision.restrict_minutes and decision.restrict_minutes > 0:
                until_date = timedelta(minutes=decision.restrict_minutes)

            # Применяем ограничения
            await message.bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=permissions,
                until_date=until_date
            )

            logger.info(
                f"[COORDINATOR/AS] Пользователь {user_id} ограничен "
                f"({'навсегда' if not decision.restrict_minutes else f'{decision.restrict_minutes} минут'})"
            )

            # Отправляем уведомление
            try:
                if decision.restrict_minutes:
                    mute_text = (
                        f"🔇 Пользователь {message.from_user.mention_html()} "
                        f"ограничен на {decision.restrict_minutes} минут.\n"
                        f"<i>Причина: {decision.reason}</i>"
                    )
                else:
                    mute_text = (
                        f"🔇 Пользователь {message.from_user.mention_html()} "
                        f"ограничен навсегда.\n"
                        f"<i>Причина: {decision.reason}</i>"
                    )
                sent_msg = await message.answer(mute_text, parse_mode="HTML")
                if warning_ttl > 0:
                    await schedule_message_deletion(sent_msg, warning_ttl)
            except Exception:
                pass

            # Логируем в журнал группы
            duration_str = f"{decision.restrict_minutes} мин." if decision.restrict_minutes else "навсегда"
            await send_journal_event(
                bot=message.bot,
                session=session,
                group_id=chat_id,
                message_text=(
                    f"🔇 <b>Антиспам: Ограничение (мут)</b>\n\n"
                    f"👤 Пользователь: {message.from_user.mention_html()} "
                    f"[<code>{user_id}</code>]\n"
                    f"⏱️ Длительность: {duration_str}\n"
                    f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                    f"💬 Причина: {decision.reason}\n"
                    f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                )
            )

        except TelegramBadRequest as e:
            logger.error(f"[COORDINATOR/AS] Не удалось ограничить пользователя: {e}")
        except TelegramForbiddenError:
            logger.error("[COORDINATOR/AS] У бота нет прав на ограничение участников")

    # ─────────────────────────────────────────────────────────
    # ДЕЙСТВИЕ: BAN - блокировка навсегда
    # ─────────────────────────────────────────────────────────
    elif decision.action == ActionType.BAN:
        try:
            # Баним пользователя навсегда
            await message.bot.ban_chat_member(chat_id, user_id)
            logger.info(f"[COORDINATOR/AS] Пользователь {user_id} заблокирован навсегда")

            # Отправляем уведомление
            try:
                ban_text = (
                    f"🚫 Пользователь {message.from_user.mention_html()} "
                    f"заблокирован навсегда.\n"
                    f"<i>Причина: {decision.reason}</i>"
                )
                sent_msg = await message.answer(ban_text, parse_mode="HTML")
                if warning_ttl > 0:
                    await schedule_message_deletion(sent_msg, warning_ttl)
            except Exception:
                pass

            # Логируем в журнал группы
            await send_journal_event(
                bot=message.bot,
                session=session,
                group_id=chat_id,
                message_text=(
                    f"🚫 <b>Антиспам: Бан</b>\n\n"
                    f"👤 Пользователь: {message.from_user.mention_html()} "
                    f"[<code>{user_id}</code>]\n"
                    f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                    f"💬 Причина: {decision.reason}\n"
                    f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                )
            )

        except TelegramBadRequest as e:
            logger.error(f"[COORDINATOR/AS] Не удалось забанить пользователя: {e}")
        except TelegramForbiddenError:
            logger.error("[COORDINATOR/AS] У бота нет прав на блокировку участников")
