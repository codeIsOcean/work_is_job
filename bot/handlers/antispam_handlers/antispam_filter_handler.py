# Импорт модуля логирования для записи информации о работе фильтра
import logging
# Импорт asyncio для отложенных задач
import asyncio
# Импорт datetime для работы с временем ограничений
from datetime import datetime, timedelta, timezone
# Импорт Router для создания отдельного роутера антиспам фильтра
from aiogram import Router, F
# Импорт типов aiogram для работы с сообщениями и чатами
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
# Импорт исключений aiogram для обработки ошибок API
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
# Импорт AsyncSession для работы с базой данных
from sqlalchemy.ext.asyncio import AsyncSession
# Импорт select для запросов к БД
from sqlalchemy import select

# Импорт основной функции проверки сообщений на спам
from bot.services.antispam import check_message_for_spam, AntiSpamDecision
# Импорт типов действий для определения что делать со спамом
from bot.database.models_antispam import ActionType
# Импорт модели настроек чата для получения TTL
from bot.database.models import ChatSettings
# Импорт функции логирования в журнал группы
from bot.services.group_journal_service import send_journal_event
# Импорт сервиса сохранения ограничений в БД
from bot.services.restriction_service import save_restriction

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

# ID бота Telegram для анонимных администраторов группы
# Когда админ пишет анонимно, сообщение приходит от этого бота
GROUP_ANONYMOUS_BOT_ID = 1087968824

# Создаем отдельный роутер для фильтрации сообщений
antispam_filter_router = Router()


# Хелпер-функция для отложенного удаления сообщения
async def schedule_message_deletion(message: Message, delay_seconds: int) -> None:
    """
    Запланировать удаление сообщения через указанное время.

    Args:
        message: Сообщение для удаления
        delay_seconds: Задержка в секундах перед удалением
    """
    if delay_seconds <= 0:
        return

    async def delete_after_delay():
        try:
            await asyncio.sleep(delay_seconds)
            await message.delete()
            logger.debug(
                f"[ANTISPAM_FILTER] Авто-удалено предупреждение "
                f"(message_id={message.message_id}) через {delay_seconds} сек"
            )
        except TelegramBadRequest as e:
            # Сообщение уже удалено
            logger.debug(f"[ANTISPAM_FILTER] Не удалось авто-удалить сообщение: {e}")
        except Exception as e:
            logger.error(f"[ANTISPAM_FILTER] Ошибка авто-удаления: {e}")

    # Запускаем задачу в фоне (не ждём завершения)
    asyncio.create_task(delete_after_delay())


# Хелпер-функция для получения TTL предупреждений
async def get_warning_ttl(session: AsyncSession, chat_id: int) -> int:
    """
    Получить время жизни предупреждений антиспам для чата.

    Args:
        session: Сессия БД
        chat_id: ID чата

    Returns:
        TTL в секундах (0 = не удалять)
    """
    try:
        result = await session.execute(
            select(ChatSettings.antispam_warning_ttl_seconds)
            .where(ChatSettings.chat_id == chat_id)
        )
        ttl = result.scalar_one_or_none()
        return ttl if ttl is not None else 0
    except Exception as e:
        logger.error(f"[ANTISPAM_FILTER] Ошибка получения TTL: {e}")
        return 0


# Хелпер-функция для проверки прав администратора
async def is_user_admin(bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором в чате

    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        user_id: ID пользователя

    Returns:
        bool: True если пользователь администратор, иначе False
    """
    try:
        # Получаем информацию о члене чата через API Telegram
        member = await bot.get_chat_member(chat_id, user_id)
        # Проверяем статус: creator (создатель) или administrator (админ)
        return member.status in ["creator", "administrator"]
    except Exception as e:
        # Если произошла ошибка при проверке, логируем ее
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        # В случае ошибки считаем что пользователь не админ (безопасный подход)
        return False


def create_journal_action_keyboard(
    user_id: int,
    chat_id: int,
    restrict_minutes: int = None
) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопками действий для журнала антиспам.

    Кнопки:
    - Мут (с временем из настроек правила)
    - Бан (навсегда)
    - Анмут (снять ограничения)

    Args:
        user_id: ID пользователя для действия
        chat_id: ID чата (группы)
        restrict_minutes: Длительность мута в минутах из настроек (None = навсегда)

    Returns:
        InlineKeyboardMarkup с кнопками действий
    """
    # Формируем текст кнопки мута с временем
    if restrict_minutes and restrict_minutes > 0:
        # Если есть настроенное время мута
        mute_text = f"🔇 Мут ({restrict_minutes} мин)"
    else:
        # Если мут навсегда
        mute_text = "🔇 Мут (навсегда)"

    # Создаём кнопки действий
    # Формат callback_data: aslog:{action}:{user_id}:{chat_id}:{restrict_minutes}
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                # Кнопка мута
                InlineKeyboardButton(
                    text=mute_text,
                    callback_data=f"aslog:mute:{user_id}:{chat_id}:{restrict_minutes or 0}"
                ),
                # Кнопка бана
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"aslog:ban:{user_id}:{chat_id}"
                ),
            ],
            [
                # Кнопка снятия ограничений
                InlineKeyboardButton(
                    text="🔊 Снять ограничения",
                    callback_data=f"aslog:unmute:{user_id}:{chat_id}"
                ),
            ],
        ]
    )
    return keyboard


# Основной обработчик сообщений в группах для антиспам фильтрации
@antispam_filter_router.message(
    # Фильтр: обрабатываем только сообщения в группах и супергруппах
    F.chat.type.in_({"group", "supergroup"})
)
async def filter_message_for_spam(message: Message, session: AsyncSession):
    """
    Проверяет каждое сообщение в группе на спам и применяет правила антиспам

    Args:
        message: Объект сообщения от aiogram
        session: Сессия базы данных для получения правил
    """
    # Логируем начало проверки сообщения
    logger.info(
        f"[ANTISPAM_FILTER] Проверка сообщения от пользователя "
        f"{message.from_user.id} в чате {message.chat.id}"
    )

    try:
        # Проверяем что у сообщения есть отправитель
        if not message.from_user:
            # Если отправителя нет (системное сообщение), пропускаем проверку
            logger.debug("[ANTISPAM_FILTER] Сообщение без from_user, пропускаем")
            return

        # Получаем ID чата и пользователя для дальнейших проверок
        chat_id = message.chat.id
        # Получаем ID пользователя
        user_id = message.from_user.id

        # ============================================================
        # ПРОВЕРКА: Анонимный администратор группы
        # Когда админ пишет анонимно, from_user.id = GROUP_ANONYMOUS_BOT_ID
        # ============================================================
        if user_id == GROUP_ANONYMOUS_BOT_ID:
            # Анонимные админы не подвергаются проверке на спам
            logger.debug(
                f"[ANTISPAM_FILTER] Анонимный администратор (user_id={user_id}), пропускаем"
            )
            return

        # ============================================================
        # ПРОВЕРКА: Сообщение от имени канала (sender_chat)
        # Когда канал привязан к группе и постит от своего имени
        # ============================================================
        if message.sender_chat:
            # Сообщения от каналов/групп не подвергаются проверке на спам
            # sender_chat.id - это ID канала который отправил сообщение
            logger.debug(
                f"[ANTISPAM_FILTER] Сообщение от канала/группы "
                f"(sender_chat.id={message.sender_chat.id}), пропускаем"
            )
            return

        # ============================================================
        # ПРОВЕРКА: Обычный администратор или бот-администратор
        # ============================================================
        if await is_user_admin(message.bot, chat_id, user_id):
            # Администраторы не подвергаются проверке на спам
            logger.debug(
                f"[ANTISPAM_FILTER] Пользователь {user_id} - администратор, пропускаем"
            )
            return

        # Вызываем основную функцию проверки на спам из сервисного слоя
        decision: AntiSpamDecision = await check_message_for_spam(message, session)

        # Если сообщение не является спамом, ничего не делаем
        if not decision.is_spam:
            # Логируем что сообщение прошло проверку
            logger.debug("[ANTISPAM_FILTER] Сообщение не является спамом")
            return

        # Если сообщение определено как спам, логируем детали
        logger.warning(
            f"[ANTISPAM_FILTER] Обнаружен спам! Правило: {decision.triggered_rule_type}, "
            f"Действие: {decision.action}, Причина: {decision.reason}"
        )

        # Получаем TTL для предупреждений (для авто-удаления)
        warning_ttl = await get_warning_ttl(session, chat_id)

        # Удаляем сообщение если это указано в правиле ИЛИ если действие DELETE
        # DELETE всегда удаляет сообщение - это его основная функция
        should_delete = decision.delete_message or decision.action == ActionType.DELETE
        if should_delete:
            try:
                # Пытаемся удалить сообщение через API
                await message.delete()
                # Логируем успешное удаление
                logger.info(f"[ANTISPAM_FILTER] Сообщение удалено (message_id={message.message_id})")
            except TelegramBadRequest as e:
                # Если не удалось удалить (например, сообщение уже удалено)
                logger.error(f"[ANTISPAM_FILTER] Не удалось удалить сообщение: {e}")
            except TelegramForbiddenError:
                # Если у бота нет прав на удаление сообщений
                logger.error("[ANTISPAM_FILTER] У бота нет прав на удаление сообщений")

        # Применяем действие в зависимости от типа наказания
        if decision.action == ActionType.DELETE:
            # Действие: DELETE - только удалить сообщение, без наказания
            # Сообщение уже удалено выше (всегда для DELETE)
            logger.info(f"[ANTISPAM_FILTER] Действие DELETE для пользователя {user_id}")
            # Логируем в журнал группы с кнопками действий
            await send_journal_event(
                bot=message.bot,
                session=session,
                group_id=chat_id,
                message_text=(
                    f"🗑️ <b>Антиспам: Удаление</b>\n\n"
                    f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
                    f"[<code>{user_id}</code>]\n"
                    f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                    f"💬 Причина: {decision.reason}\n"
                    f"🗑️ Сообщение удалено: Да"
                ),
                reply_markup=create_journal_action_keyboard(
                    user_id=user_id,
                    chat_id=chat_id,
                    restrict_minutes=decision.restrict_minutes
                )
            )

        elif decision.action == ActionType.WARN:
            # Действие: WARN - отправляем предупреждение пользователю
            try:
                # Формируем текст предупреждения с указанием причины
                warning_text = (
                    f"⚠️ <b>Предупреждение</b>\n\n"
                    f"Пользователь {message.from_user.mention_html()}, "
                    f"ваше сообщение нарушает правила:\n"
                    f"<i>{decision.reason}</i>"
                )
                # Отправляем предупреждение в чат
                sent_msg = await message.answer(warning_text, parse_mode="HTML")
                # Логируем отправку предупреждения
                logger.info(f"[ANTISPAM_FILTER] Отправлено предупреждение пользователю {user_id}")
                # Планируем авто-удаление если настроен TTL
                if warning_ttl > 0:
                    await schedule_message_deletion(sent_msg, warning_ttl)
                # Логируем в журнал группы с кнопками действий
                await send_journal_event(
                    bot=message.bot,
                    session=session,
                    group_id=chat_id,
                    message_text=(
                        f"⚠️ <b>Антиспам: Предупреждение</b>\n\n"
                        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
                        f"[<code>{user_id}</code>]\n"
                        f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                        f"💬 Причина: {decision.reason}\n"
                        f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                    ),
                    reply_markup=create_journal_action_keyboard(
                        user_id=user_id,
                        chat_id=chat_id,
                        restrict_minutes=decision.restrict_minutes
                    )
                )
            except Exception as e:
                # Если не удалось отправить предупреждение, логируем ошибку
                logger.error(f"[ANTISPAM_FILTER] Ошибка при отправке предупреждения: {e}")

        elif decision.action == ActionType.KICK:
            # Действие: KICK - исключаем пользователя из чата
            try:
                # Баним пользователя через API
                await message.bot.ban_chat_member(chat_id, user_id)
                # Сразу разбаниваем чтобы пользователь мог вернуться по ссылке
                await message.bot.unban_chat_member(chat_id, user_id)
                # Логируем успешный кик
                logger.info(f"[ANTISPAM_FILTER] Пользователь {user_id} исключен из чата")

                # Отправляем уведомление в чат о кике
                try:
                    # Формируем текст уведомления
                    kick_text = (
                        f"👢 Пользователь {message.from_user.mention_html()} "
                        f"исключен из чата.\n"
                        f"<i>Причина: {decision.reason}</i>"
                    )
                    # Отправляем уведомление
                    sent_msg = await message.answer(kick_text, parse_mode="HTML")
                    # Планируем авто-удаление если настроен TTL
                    if warning_ttl > 0:
                        await schedule_message_deletion(sent_msg, warning_ttl)
                except Exception:
                    # Игнорируем ошибки отправки уведомления (не критично)
                    pass

                # Логируем в журнал группы с кнопками действий
                await send_journal_event(
                    bot=message.bot,
                    session=session,
                    group_id=chat_id,
                    message_text=(
                        f"👢 <b>Антиспам: Исключение</b>\n\n"
                        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
                        f"[<code>{user_id}</code>]\n"
                        f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                        f"💬 Причина: {decision.reason}\n"
                        f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                    ),
                    reply_markup=create_journal_action_keyboard(
                        user_id=user_id,
                        chat_id=chat_id,
                        restrict_minutes=decision.restrict_minutes
                    )
                )

            except TelegramBadRequest as e:
                # Если не удалось кикнуть (например, пользователь уже вышел)
                logger.error(f"[ANTISPAM_FILTER] Не удалось кикнуть пользователя: {e}")
            except TelegramForbiddenError:
                # Если у бота нет прав на исключение участников
                logger.error("[ANTISPAM_FILTER] У бота нет прав на исключение участников")

        elif decision.action == ActionType.RESTRICT:
            # Действие: RESTRICT - ограничиваем права пользователя (мут)
            try:
                # Создаем объект с пустыми правами (полный мут)
                permissions = ChatPermissions(
                    # Запрещаем отправку сообщений
                    can_send_messages=False,
                    # Запрещаем отправку медиа
                    can_send_media_messages=False,
                    # Запрещаем отправку опросов
                    can_send_polls=False,
                    # Запрещаем отправку других сообщений (стикеры, гифки)
                    can_send_other_messages=False,
                    # Запрещаем добавление превью веб-страниц
                    can_add_web_page_previews=False,
                    # Запрещаем изменение информации о чате
                    can_change_info=False,
                    # Запрещаем приглашение пользователей
                    can_invite_users=False,
                    # Запрещаем закрепление сообщений
                    can_pin_messages=False,
                )

                # Определяем время ограничения (если указано)
                until_date = None
                # Если в решении указана длительность мута в минутах
                if decision.restrict_minutes and decision.restrict_minutes > 0:
                    # Вычисляем время окончания мута
                    until_date = timedelta(minutes=decision.restrict_minutes)

                # Применяем ограничения через API
                await message.bot.restrict_chat_member(
                    # ID чата
                    chat_id,
                    # ID пользователя
                    user_id,
                    # Ограничения
                    permissions=permissions,
                    # Время до снятия ограничений (None = навсегда)
                    until_date=until_date
                )

                # Вычисляем дату окончания для сохранения в БД
                until_datetime = None
                if decision.restrict_minutes and decision.restrict_minutes > 0:
                    until_datetime = datetime.now(timezone.utc) + timedelta(minutes=decision.restrict_minutes)

                # Сохраняем ограничение в БД для восстановления после повторного входа
                bot_info = await message.bot.me()
                await save_restriction(
                    session=session,
                    chat_id=chat_id,
                    user_id=user_id,
                    restriction_type="mute",
                    reason="antispam",
                    restricted_by=bot_info.id,
                    until_date=until_datetime,
                )

                # Логируем успешное применение мута
                logger.info(
                    f"[ANTISPAM_FILTER] Пользователь {user_id} ограничен "
                    f"({'навсегда' if not decision.restrict_minutes else f'{decision.restrict_minutes} минут'})"
                )

                # Отправляем уведомление в чат о муте
                try:
                    # Формируем текст уведомления с длительностью
                    if decision.restrict_minutes:
                        # Если указано время мута
                        mute_text = (
                            f"🔇 Пользователь {message.from_user.mention_html()} "
                            f"ограничен на {decision.restrict_minutes} минут.\n"
                            f"<i>Причина: {decision.reason}</i>"
                        )
                    else:
                        # Если мут навсегда
                        mute_text = (
                            f"🔇 Пользователь {message.from_user.mention_html()} "
                            f"ограничен навсегда.\n"
                            f"<i>Причина: {decision.reason}</i>"
                        )
                    # Отправляем уведомление
                    sent_msg = await message.answer(mute_text, parse_mode="HTML")
                    # Планируем авто-удаление если настроен TTL
                    if warning_ttl > 0:
                        await schedule_message_deletion(sent_msg, warning_ttl)
                except Exception:
                    # Игнорируем ошибки отправки уведомления (не критично)
                    pass

                # Формируем строку длительности для журнала
                duration_str = f"{decision.restrict_minutes} мин." if decision.restrict_minutes else "навсегда"
                # Логируем в журнал группы с кнопками действий
                await send_journal_event(
                    bot=message.bot,
                    session=session,
                    group_id=chat_id,
                    message_text=(
                        f"🔇 <b>Антиспам: Ограничение (мут)</b>\n\n"
                        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
                        f"[<code>{user_id}</code>]\n"
                        f"⏱️ Длительность: {duration_str}\n"
                        f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                        f"💬 Причина: {decision.reason}\n"
                        f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                    ),
                    reply_markup=create_journal_action_keyboard(
                        user_id=user_id,
                        chat_id=chat_id,
                        restrict_minutes=decision.restrict_minutes
                    )
                )

            except TelegramBadRequest as e:
                # Если не удалось применить ограничения
                logger.error(f"[ANTISPAM_FILTER] Не удалось ограничить пользователя: {e}")
            except TelegramForbiddenError:
                # Если у бота нет прав на ограничение участников
                logger.error("[ANTISPAM_FILTER] У бота нет прав на ограничение участников")

        elif decision.action == ActionType.BAN:
            # Действие: BAN - блокируем пользователя навсегда
            try:
                # Баним пользователя через API (без автоматического разбана)
                await message.bot.ban_chat_member(chat_id, user_id)

                # Сохраняем бан в БД для восстановления после повторного входа
                bot_info = await message.bot.me()
                await save_restriction(
                    session=session,
                    chat_id=chat_id,
                    user_id=user_id,
                    restriction_type="ban",
                    reason="antispam",
                    restricted_by=bot_info.id,
                    until_date=None,  # Бан навсегда
                )

                # Логируем успешный бан
                logger.info(f"[ANTISPAM_FILTER] Пользователь {user_id} заблокирован навсегда")

                # Отправляем уведомление в чат о бане
                try:
                    # Формируем текст уведомления
                    ban_text = (
                        f"🚫 Пользователь {message.from_user.mention_html()} "
                        f"заблокирован навсегда.\n"
                        f"<i>Причина: {decision.reason}</i>"
                    )
                    # Отправляем уведомление
                    sent_msg = await message.answer(ban_text, parse_mode="HTML")
                    # Планируем авто-удаление если настроен TTL
                    if warning_ttl > 0:
                        await schedule_message_deletion(sent_msg, warning_ttl)
                except Exception:
                    # Игнорируем ошибки отправки уведомления (не критично)
                    pass

                # Логируем в журнал группы с кнопками действий
                await send_journal_event(
                    bot=message.bot,
                    session=session,
                    group_id=chat_id,
                    message_text=(
                        f"🚫 <b>Антиспам: Бан</b>\n\n"
                        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
                        f"[<code>{user_id}</code>]\n"
                        f"📋 Правило: {decision.triggered_rule_type.value if decision.triggered_rule_type else 'N/A'}\n"
                        f"💬 Причина: {decision.reason}\n"
                        f"🗑️ Сообщение удалено: {'Да' if decision.delete_message else 'Нет'}"
                    ),
                    reply_markup=create_journal_action_keyboard(
                        user_id=user_id,
                        chat_id=chat_id,
                        restrict_minutes=decision.restrict_minutes
                    )
                )

            except TelegramBadRequest as e:
                # Если не удалось забанить (например, пользователь уже в бане)
                logger.error(f"[ANTISPAM_FILTER] Не удалось забанить пользователя: {e}")
            except TelegramForbiddenError:
                # Если у бота нет прав на блокировку участников
                logger.error("[ANTISPAM_FILTER] У бота нет прав на блокировку участников")

    except Exception as e:
        # Ловим все неожиданные ошибки чтобы не упал весь бот
        logger.error(f"[ANTISPAM_FILTER] Неожиданная ошибка при обработке сообщения: {e}", exc_info=True)
        # Не прерываем обработку других handlers
        return
