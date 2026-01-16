# bot/services/cross_group/action_service.py
"""
Сервис применения действий при кросс-групповой детекции.

Содержит функции для:
- Применения мута/бана/кика во всех затронутых группах
- Удаления сообщений скамера
- Отправки уведомлений в журналы групп
"""

# Импортируем логгер для записи событий
import logging
# Импортируем datetime для работы со временем
from datetime import datetime, timedelta
# Импортируем типы для аннотаций
from typing import Optional, Dict, Any, List
# Импортируем asyncio для асинхронных операций
import asyncio

# Импортируем типы aiogram
from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramAPIError

# Импортируем AsyncSession для асинхронной работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем модели кросс-групповой детекции
from bot.database.models_cross_group import (
    CrossGroupScammerSettings,
    CrossGroupDetectionLog,
    CrossGroupActionType,
)

# Импортируем сервис настроек
from bot.services.cross_group.settings_service import get_cross_group_settings
# Импортируем сервис детекции
from bot.services.cross_group.detection_service import mark_action_taken


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


async def apply_cross_group_action(
    bot: Bot,
    session: AsyncSession,
    user_id: int,
    detection_data: Dict[str, Any],
    user_name: Optional[str] = None,
    username: Optional[str] = None
) -> Dict[str, Any]:
    """
    Применяет действие во всех затронутых группах.

    На основе настроек модуля применяет мут/бан/кик
    и удаляет сообщения скамера во всех группах.

    Args:
        bot: Объект бота aiogram
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя для действия
        detection_data: Данные детекции (groups_involved, profile_changes)
        user_name: Имя пользователя (для лога)
        username: Username пользователя (для лога)

    Returns:
        dict: Результат применения действий:
            {
                "success_groups": [chat_id, ...],
                "failed_groups": {chat_id: error, ...},
                "action_type": str,
                "log_id": int
            }
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Получаем список затронутых групп
    groups_involved = detection_data.get("groups_involved", {})

    # Списки для результатов
    success_groups = []
    failed_groups = {}

    # Логируем начало применения действий
    logger.info(
        f"Применяем действие {settings.action_type.value} "
        f"к пользователю {user_id} в {len(groups_involved)} группах"
    )

    # ═══════════════════════════════════════════════════════════
    # ПРИМЕНЯЕМ ДЕЙСТВИЕ В КАЖДОЙ ГРУППЕ
    # ═══════════════════════════════════════════════════════════
    for chat_id_str, group_data in groups_involved.items():
        # Конвертируем chat_id в int
        chat_id = int(chat_id_str)

        try:
            # Выбираем действие на основе настроек
            if settings.action_type == CrossGroupActionType.mute:
                # Применяем мут
                await _apply_mute(
                    bot=bot,
                    chat_id=chat_id,
                    user_id=user_id,
                    duration_minutes=settings.mute_duration_minutes
                )
            elif settings.action_type == CrossGroupActionType.ban:
                # Применяем бан
                await _apply_ban(
                    bot=bot,
                    chat_id=chat_id,
                    user_id=user_id
                )
            elif settings.action_type == CrossGroupActionType.kick:
                # Применяем кик
                await _apply_kick(
                    bot=bot,
                    chat_id=chat_id,
                    user_id=user_id
                )

            # Добавляем в список успешных
            success_groups.append(chat_id)

            # Логируем успех
            logger.info(
                f"Действие {settings.action_type.value} применено "
                f"к пользователю {user_id} в группе {chat_id}"
            )

        except TelegramAPIError as e:
            # Добавляем в список ошибок
            failed_groups[chat_id] = str(e)

            # Логируем ошибку
            logger.error(
                f"Ошибка при применении действия к пользователю {user_id} "
                f"в группе {chat_id}: {e}"
            )

    # ═══════════════════════════════════════════════════════════
    # УДАЛЯЕМ СООБЩЕНИЯ (если настроено)
    # ═══════════════════════════════════════════════════════════
    deleted_messages = {}  # {chat_id: count}

    if settings.action_type in [CrossGroupActionType.delete, CrossGroupActionType.mute, CrossGroupActionType.ban]:
        for chat_id_str, group_data in groups_involved.items():
            chat_id = int(chat_id_str)
            message_ids = group_data.get("message_ids", [])

            if not message_ids:
                continue

            try:
                # Удаляем сообщения пользователя в группе
                deleted_count = await _delete_messages(
                    bot=bot,
                    chat_id=chat_id,
                    message_ids=message_ids
                )
                deleted_messages[chat_id] = deleted_count

                logger.info(
                    f"Удалено {deleted_count} сообщений пользователя {user_id} "
                    f"в группе {chat_id}"
                )

            except Exception as e:
                # Логируем ошибку но не прерываем выполнение
                logger.warning(
                    f"Не удалось удалить сообщения пользователя {user_id} "
                    f"в группе {chat_id}: {e}"
                )

    # ═══════════════════════════════════════════════════════════
    # ПОМЕЧАЕМ ЧТО ДЕЙСТВИЕ ПРИМЕНЕНО
    # ═══════════════════════════════════════════════════════════
    await mark_action_taken(session, user_id, success_groups)

    # ═══════════════════════════════════════════════════════════
    # СОЗДАЁМ ЗАПИСЬ В ЛОГЕ ДЕТЕКЦИЙ
    # ═══════════════════════════════════════════════════════════
    log_entry = CrossGroupDetectionLog(
        user_id=user_id,
        groups_involved=groups_involved,
        profile_changes=detection_data.get("profile_changes"),
        action_type=settings.action_type,
        user_name=user_name,
        username=username,
    )

    # Добавляем в сессию
    session.add(log_entry)
    # Сохраняем в БД
    await session.commit()
    # Обновляем объект из БД чтобы получить ID
    await session.refresh(log_entry)

    # Логируем результат
    logger.info(
        f"Действия применены к пользователю {user_id}: "
        f"успешно в {len(success_groups)} группах, "
        f"ошибки в {len(failed_groups)} группах"
    )

    # Результат для возврата
    result = {
        "success_groups": success_groups,
        "failed_groups": failed_groups,
        "action_type": settings.action_type.value,
        "log_id": log_entry.id,
        "deleted_messages": deleted_messages,
    }

    # ═══════════════════════════════════════════════════════════
    # ОТПРАВЛЯЕМ УВЕДОМЛЕНИЯ В ЖУРНАЛЫ ВСЕХ ЗАТРОНУТЫХ ГРУПП
    # ═══════════════════════════════════════════════════════════
    if settings.send_to_journal and success_groups:
        try:
            await send_journal_notification(
                bot=bot,
                session=session,
                user_id=user_id,
                detection_data=detection_data,
                action_result=result,
                user_name=user_name,
                username=username,
            )
        except Exception as e:
            # Ошибка отправки в журнал не должна ломать основной флоу
            logger.error(f"Ошибка отправки в журнал: {e}")

    return result


async def _apply_mute(
    bot: Bot,
    chat_id: int,
    user_id: int,
    duration_minutes: int
) -> None:
    """
    Применяет мут к пользователю в группе.

    Args:
        bot: Объект бота aiogram
        chat_id: ID группы
        user_id: ID пользователя
        duration_minutes: Длительность мута в минутах (0 = навсегда)
    """
    # Создаём объект ограничений (нельзя ничего)
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

    # Определяем время окончания мута
    if duration_minutes > 0:
        # Мут на определённое время
        until_date = datetime.utcnow() + timedelta(minutes=duration_minutes)
    else:
        # Мут навсегда (366 дней — максимум Telegram)
        until_date = datetime.utcnow() + timedelta(days=366)

    # Применяем ограничения
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=permissions,
        until_date=until_date,
    )


async def _apply_ban(
    bot: Bot,
    chat_id: int,
    user_id: int
) -> None:
    """
    Применяет бан к пользователю в группе.

    Args:
        bot: Объект бота aiogram
        chat_id: ID группы
        user_id: ID пользователя
    """
    # Баним пользователя
    await bot.ban_chat_member(
        chat_id=chat_id,
        user_id=user_id,
    )


async def _apply_kick(
    bot: Bot,
    chat_id: int,
    user_id: int
) -> None:
    """
    Кикает пользователя из группы.

    Args:
        bot: Объект бота aiogram
        chat_id: ID группы
        user_id: ID пользователя
    """
    # Баним и сразу разбаниваем (кик)
    await bot.ban_chat_member(
        chat_id=chat_id,
        user_id=user_id,
    )
    # Разбаниваем чтобы мог вернуться
    await bot.unban_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        only_if_banned=True,
    )


async def _delete_messages(
    bot: Bot,
    chat_id: int,
    message_ids: List[int]
) -> int:
    """
    Удаляет сообщения пользователя в группе.

    Использует Bot API delete_messages (до 100 за раз).

    Args:
        bot: Объект бота aiogram
        chat_id: ID группы
        message_ids: Список ID сообщений для удаления

    Returns:
        int: Количество успешно удалённых сообщений
    """
    if not message_ids:
        return 0

    deleted_count = 0

    # Bot API позволяет удалять до 100 сообщений за раз
    # Разбиваем на чанки по 100
    for i in range(0, len(message_ids), 100):
        chunk = message_ids[i:i + 100]

        try:
            # Используем delete_messages (Bot API 6.5+)
            await bot.delete_messages(
                chat_id=chat_id,
                message_ids=chunk
            )
            deleted_count += len(chunk)

        except TelegramAPIError as e:
            # Если delete_messages не сработал — удаляем по одному
            logger.warning(
                f"delete_messages не удалось ({e}), удаляем по одному"
            )

            for msg_id in chunk:
                try:
                    await bot.delete_message(
                        chat_id=chat_id,
                        message_id=msg_id
                    )
                    deleted_count += 1
                except TelegramAPIError:
                    # Сообщение уже удалено или недоступно
                    pass

        # Небольшая задержка чтобы не упереться в лимиты
        await asyncio.sleep(0.1)

    return deleted_count


async def send_journal_notification(
    bot: Bot,
    session: AsyncSession,
    user_id: int,
    detection_data: Dict[str, Any],
    action_result: Dict[str, Any],
    user_name: Optional[str] = None,
    username: Optional[str] = None
) -> Dict[int, int]:
    """
    Отправляет уведомления в журналы всех затронутых групп.

    Args:
        bot: Объект бота aiogram
        session: Асинхронная сессия SQLAlchemy
        user_id: ID пользователя
        detection_data: Данные детекции
        action_result: Результат применения действий
        user_name: Имя пользователя
        username: Username пользователя

    Returns:
        Dict[int, int]: Словарь {chat_id: message_id} отправленных сообщений
    """
    # Получаем настройки модуля
    settings = await get_cross_group_settings(session)

    # Если уведомления отключены — выходим
    if not settings.send_to_journal:
        return {}

    # Формируем текст уведомления
    text = await _format_journal_message(
        user_id=user_id,
        user_name=user_name,
        username=username,
        detection_data=detection_data,
        action_result=action_result,
    )

    # Импортируем функцию получения журнала
    from bot.services.bot_activity_journal.bot_activity_journal_logic import (
        get_journal_channel_for_group,
    )

    # Словарь для результатов
    journal_messages = {}

    # Отправляем в журнал каждой группы
    groups_involved = detection_data.get("groups_involved", {})

    for chat_id_str in groups_involved.keys():
        chat_id = int(chat_id_str)

        try:
            # Получаем ID журнала для группы
            journal_id = await get_journal_channel_for_group(session, chat_id)

            # Если журнал не привязан — пропускаем
            if journal_id is None:
                continue

            # Создаём клавиатуру с действиями
            keyboard = _create_journal_keyboard(user_id, chat_id)

            # Отправляем сообщение в журнал
            message = await bot.send_message(
                chat_id=journal_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            # Сохраняем ID сообщения
            journal_messages[chat_id] = message.message_id

            # Логируем успех
            logger.info(
                f"Уведомление отправлено в журнал группы {chat_id}"
            )

        except TelegramAPIError as e:
            # Логируем ошибку
            logger.error(
                f"Ошибка отправки уведомления в журнал группы {chat_id}: {e}"
            )

    # Обновляем запись лога с ID сообщений в журналах
    if journal_messages and action_result.get("log_id"):
        from sqlalchemy import select
        query = select(CrossGroupDetectionLog).where(
            CrossGroupDetectionLog.id == action_result["log_id"]
        )
        result = await session.execute(query)
        log_entry = result.scalar_one_or_none()

        if log_entry:
            log_entry.journal_message_ids = journal_messages
            await session.commit()

    return journal_messages


async def _format_journal_message(
    user_id: int,
    user_name: Optional[str],
    username: Optional[str],
    detection_data: Dict[str, Any],
    action_result: Dict[str, Any]
) -> str:
    """
    Форматирует полное детальное сообщение для журнала.

    Включает:
    - Когда вступил в каждую группу
    - С каким интервалом между вступлениями
    - Когда поменял имя (было/стало)
    - Через какое время начал писать в каждой группе
    - Сколько сообщений удалено
    - Какое действие применено

    Args:
        user_id: ID пользователя
        user_name: Имя пользователя
        username: Username пользователя
        detection_data: Данные детекции
        action_result: Результат применения действий

    Returns:
        str: Отформатированный текст сообщения
    """
    # Формируем ссылку на пользователя
    if user_name:
        user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'
    else:
        user_link = f'<a href="tg://user?id={user_id}">Пользователь</a>'

    # Получаем данные
    groups_involved = detection_data.get("groups_involved", {})
    profile_changes = detection_data.get("profile_changes")
    deleted_messages = action_result.get("deleted_messages", {})

    # ═══════════════════════════════════════════════════════════
    # ФОРМИРУЕМ ДЕТАЛЬНЫЙ ЛОГ ПО ГРУППАМ
    # ═══════════════════════════════════════════════════════════
    groups_list = []
    join_times = []  # Для расчёта интервалов

    for chat_id_str, data in groups_involved.items():
        group_title = data.get("group_title", "Неизвестно")
        joined_at_str = data.get("joined_at")
        first_msg_str = data.get("first_message_at")
        last_msg_str = data.get("last_message_at")
        msg_count = data.get("message_count", 0)

        # Парсим время вступления
        joined_at = None
        joined_at_formatted = "?"
        if joined_at_str:
            try:
                joined_at = datetime.fromisoformat(joined_at_str)
                joined_at_formatted = joined_at.strftime("%d.%m %H:%M")
                join_times.append(joined_at)
            except (ValueError, TypeError):
                pass

        # Рассчитываем через сколько начал писать
        time_to_first_msg = ""
        if joined_at and first_msg_str:
            try:
                first_msg = datetime.fromisoformat(first_msg_str)
                delta = first_msg - joined_at
                minutes = int(delta.total_seconds() // 60)
                if minutes < 1:
                    time_to_first_msg = f" (через {int(delta.total_seconds())} сек)"
                elif minutes < 60:
                    time_to_first_msg = f" (через {minutes} мин)"
                else:
                    hours = minutes // 60
                    time_to_first_msg = f" (через {hours} ч {minutes % 60} мин)"
            except (ValueError, TypeError):
                pass

        # Количество удалённых сообщений в этой группе
        chat_id = int(chat_id_str)
        deleted_in_group = deleted_messages.get(chat_id, 0)
        deleted_text = f", удалено: {deleted_in_group}" if deleted_in_group > 0 else ""

        # Формируем строку для группы
        group_line = (
            f"  <b>{group_title}</b>\n"
            f"    Вступил: {joined_at_formatted}{time_to_first_msg}\n"
            f"    Сообщений: {msg_count}{deleted_text}"
        )
        groups_list.append(group_line)

    # Рассчитываем интервал между вступлениями
    interval_text = ""
    if len(join_times) >= 2:
        join_times.sort()
        total_interval = join_times[-1] - join_times[0]
        minutes = int(total_interval.total_seconds() // 60)
        if minutes < 60:
            interval_text = f"\nИнтервал вступлений: {minutes} мин"
        else:
            hours = minutes // 60
            interval_text = f"\nИнтервал вступлений: {hours} ч {minutes % 60} мин"

    groups_text = "\n".join(groups_list)

    # ═══════════════════════════════════════════════════════════
    # ФОРМИРУЕМ ИНФОРМАЦИЮ О СМЕНЕ ПРОФИЛЯ
    # ═══════════════════════════════════════════════════════════
    profile_text = ""
    if profile_changes:
        change_type = profile_changes.get("change_type", "unknown")
        original_name = profile_changes.get("original_name")
        changed_at_str = profile_changes.get("changed_at")

        # Форматируем время смены
        changed_at_formatted = ""
        if changed_at_str:
            try:
                changed_at = datetime.fromisoformat(changed_at_str)
                changed_at_formatted = f" в {changed_at.strftime('%H:%M')}"
            except (ValueError, TypeError):
                pass

        if change_type == "name":
            profile_text = f"\n\n<b>Смена имени</b>{changed_at_formatted}"
            if original_name:
                profile_text += f"\n  Было: {original_name}"
                profile_text += f"\n  Стало: {user_name or '?'}"
        elif change_type == "photo":
            profile_text = f"\n\n<b>Смена фото</b>{changed_at_formatted}"
        elif change_type == "both":
            profile_text = f"\n\n<b>Смена имени и фото</b>{changed_at_formatted}"
            if original_name:
                profile_text += f"\n  Было: {original_name}"
                profile_text += f"\n  Стало: {user_name or '?'}"

    # ═══════════════════════════════════════════════════════════
    # ФОРМИРУЕМ ИНФОРМАЦИЮ О ДЕЙСТВИИ
    # ═══════════════════════════════════════════════════════════
    action_type = action_result.get("action_type", "unknown")
    action_names = {
        "mute": "Мут навсегда",
        "ban": "Бан",
        "kick": "Кик",
        "delete": "Только удаление",
    }
    action_text = action_names.get(action_type, action_type)

    success_count = len(action_result.get("success_groups", []))
    failed_count = len(action_result.get("failed_groups", {}))

    # Общее количество удалённых сообщений
    total_deleted = sum(deleted_messages.values())
    deleted_summary = f"\nУдалено сообщений: {total_deleted}" if total_deleted > 0 else ""

    # ═══════════════════════════════════════════════════════════
    # СОБИРАЕМ ПОЛНОЕ СООБЩЕНИЕ
    # ═══════════════════════════════════════════════════════════
    text = f"#КРОСС_ГРУППОВОЙ_СКАММЕР\n\n"

    # Заголовок
    text += f"<b>Пользователь:</b> {user_link}\n"
    text += f"<b>ID:</b> <code>{user_id}</code>"
    if username:
        text += f"\n<b>Username:</b> @{username}"

    # Группы
    text += f"\n\n<b>Затронуто групп:</b> {len(groups_involved)}{interval_text}\n"
    text += groups_text

    # Смена профиля
    text += profile_text

    # Результат
    text += f"\n\n<b>Результат:</b>"
    text += f"\n  Действие: {action_text}"
    text += f"\n  Групп обработано: {success_count}"
    if failed_count > 0:
        text += f"\n  Ошибок: {failed_count}"
    text += deleted_summary

    # Хэштеги
    text += f"\n\n#cross_group #scammer #id{user_id}"

    return text


def _create_journal_keyboard(user_id: int, chat_id: int):
    """
    Создаёт клавиатуру с действиями для сообщения в журнале.

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками действий
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    # Создаём кнопки действий
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            # Кнопка размута
            InlineKeyboardButton(
                text="Размут",
                callback_data=f"cg:unmute:{user_id}:{chat_id}"
            ),
            # Кнопка мута на 7 дней
            InlineKeyboardButton(
                text="Мут 7д",
                callback_data=f"cg:mute7d:{user_id}:{chat_id}"
            ),
        ],
        [
            # Кнопка бана
            InlineKeyboardButton(
                text="Бан",
                callback_data=f"cg:ban:{user_id}:{chat_id}"
            ),
            # Кнопка удаления сообщений
            InlineKeyboardButton(
                text="Удалить сообщения",
                callback_data=f"cg:delete:{user_id}:{chat_id}"
            ),
        ],
        [
            # Кнопка OK (закрыть)
            InlineKeyboardButton(
                text="OK",
                callback_data=f"cg:ok:{user_id}:{chat_id}"
            ),
        ],
    ])

    return keyboard
