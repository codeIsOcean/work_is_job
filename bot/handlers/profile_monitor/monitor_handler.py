# bot/handlers/profile_monitor/monitor_handler.py
"""
Обработчик мониторинга профилей в группах.

Вызывается из group_message_coordinator при каждом сообщении.
Проверяет изменения профиля и применяет автомут при необходимости.

НЕ ЯВЛЯЕТСЯ САМОСТОЯТЕЛЬНЫМ ХЕНДЛЕРОМ - вызывается только из координатора!
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot
from aiogram.types import Message, User
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models_profile_monitor import (
    ProfileMonitorSettings,
    ProfileSnapshot,
)
from bot.services.profile_monitor.profile_monitor_service import (
    get_profile_monitor_settings,
    get_profile_snapshot,
    create_profile_snapshot,
    update_profile_snapshot,
    check_profile_changes,
    log_profile_change,
    check_auto_mute_criteria,
    apply_auto_mute,
    delete_user_messages,
    get_user_profile_data,
    has_recent_name_change,
    has_recent_photo_change,
    get_user_change_history,
)
from bot.services.profile_monitor.content_checker import (
    check_name_and_bio_content,
    apply_content_filter_action,
)
from bot.services.group_journal_service import send_journal_event
from bot.keyboards.profile_monitor_kb import (
    get_journal_action_kb,
    get_auto_mute_kb,
    get_criterion6_kb,
)
# Импорт для проверки фото профиля через Scam Media Filter
from bot.services.scam_media import (
    compute_image_hash,
    compare_hashes,
    BannedHashService,
    SettingsService as ScamMediaSettingsService,
)
from bot.services.pyrogram_client import pyrogram_service
# Импортируем функции кросс-групповой детекции для отслеживания смены профиля
from bot.services.cross_group.detection_service import (
    track_profile_change,
    check_cross_group_detection,
)
# Импортируем функцию применения действия при детекции кросс-группового скамера
from bot.services.cross_group.action_service import apply_cross_group_action
# Импортируем типы изменений профиля
from bot.database.models_cross_group import ProfileChangeType

# Логгер модуля
logger = logging.getLogger(__name__)

# ПРИМЕЧАНИЕ: Этот файл НЕ содержит роутер с @router.message() хендлерами!
# Функция process_message_profile_check() вызывается напрямую из
# group_message_coordinator.py для избежания конфликта хендлеров в aiogram 3.x


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА ПРОФИЛЯ ПРИ СООБЩЕНИИ (ГЛАВНАЯ)
# ============================================================
async def process_message_profile_check(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> Optional[Dict[str, Any]]:
    """
    Проверяет профиль пользователя при отправке сообщения.

    Эта функция вызывается из group_message_coordinator для каждого сообщения.

    Логика:
    1. Получить настройки модуля для группы
    2. Если модуль выключен - выход
    3. Получить или создать снимок профиля
    4. Проверить изменения профиля
    5. Проверить критерии автомута
    6. Применить действия если нужно

    Args:
        message: Сообщение из группы
        session: AsyncSession для БД
        bot: Bot instance

    Returns:
        Dict с результатом или None если модуль выключен
        {
            "action_taken": "auto_mute" | "logged" | None,
            "reason": str | None,
            "changes": list | None,
        }
    """
    # Проверяем что сообщение из группы
    if not message.chat or message.chat.type not in ("group", "supergroup"):
        return None

    # Проверяем что есть отправитель
    if not message.from_user:
        return None

    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id

    # ─────────────────────────────────────────────────────────
    # ШАГ 1: Получаем настройки модуля
    # ─────────────────────────────────────────────────────────
    settings = await get_profile_monitor_settings(session, chat_id)

    # Если настроек нет или модуль выключен - выход
    if not settings or not settings.enabled:
        return None

    logger.debug(f"[PROFILE_MONITOR] Checking user={user_id} in chat={chat_id}")

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: Получаем снимок профиля
    # ─────────────────────────────────────────────────────────
    snapshot = await get_profile_snapshot(session, chat_id, user_id)

    # Если снимка нет - создаём новый (пользователь пишет первый раз)
    if not snapshot:
        return await _handle_first_message(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            user=user,
        )

    # ─────────────────────────────────────────────────────────
    # ШАГ 3: Обновляем время первого сообщения (если не установлено)
    # ─────────────────────────────────────────────────────────
    is_first_message = snapshot.first_message_at is None
    if is_first_message:
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        snapshot = await update_profile_snapshot(
            session=session,
            snapshot=snapshot,
            first_message_at=now,
        )
        logger.info(
            f"[PROFILE_MONITOR] First message recorded: user={user_id} chat={chat_id}"
        )

    # ─────────────────────────────────────────────────────────
    # ШАГ 3.1: ПРОВЕРКА ФОТО ПРИ ПЕРВОМ СООБЩЕНИИ
    # Если снапшот был создан при JOIN и это первое сообщение - проверяем фото
    # ─────────────────────────────────────────────────────────
    if is_first_message and snapshot.has_photo and settings.check_profile_photo_filter:
        logger.info(
            f"[PHOTO_FILTER] First message (snapshot exists), checking profile photo: "
            f"user={user_id} chat={chat_id}"
        )
        # Проверяем фото профиля
        match_result = await check_profile_photo_scam(
            session=session,
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        # Если найдено совпадение - применяем действие (мут + удаление сообщений)
        if match_result and match_result.get("matched"):
            return await apply_photo_filter_action(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user_id=user_id,
                user=user,
                match_result=match_result,
                settings=settings,
            )

    # ─────────────────────────────────────────────────────────
    # ШАГ 4: Получаем текущие данные профиля
    # ─────────────────────────────────────────────────────────
    # Проверяем фото через Pyrogram (если доступен)
    profile_data = await get_user_profile_data(user_id)
    current_has_photo = profile_data.get("has_photo", False)
    # Получаем ID текущего фото (для определения смены фото)
    current_photo_id = profile_data.get("photo_id")
    # Получаем возраст текущего фото (для критериев 4 и 5)
    current_photo_age_days = profile_data.get("photo_age_days")

    # Используем данные из сообщения для имени/username
    current_first_name = user.first_name
    current_last_name = user.last_name
    current_username = user.username
    current_full_name = " ".join(filter(None, [current_first_name, current_last_name]))

    # ─────────────────────────────────────────────────────────
    # ШАГ 4.1: КРИТЕРИЙ 6 - Запрещённый контент в имени/bio
    # Проверяем СРАЗУ, не ждём сообщения!
    # ─────────────────────────────────────────────────────────
    if settings.auto_mute_forbidden_content:
        # Получаем bio через Bot API (если возможно)
        bio = None
        try:
            user_chat = await bot.get_chat(user_id)
            bio = getattr(user_chat, "bio", None)
        except Exception as e:
            logger.debug(f"[PROFILE_MONITOR] Cannot get bio: user={user_id} error={e}")

        # Проверяем имя и bio на запрещённый контент
        content_result = await check_name_and_bio_content(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            full_name=current_full_name,
            bio=bio,
        )

        if content_result.should_act:
            logger.warning(
                f"[PROFILE_MONITOR] CRITERION_6 triggered: user={user_id} chat={chat_id} "
                f"reason={content_result.reason}"
            )
            # Применяем действие из ContentFilter
            action_applied = await apply_content_filter_action(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                action=content_result.action,
                duration=content_result.action_duration,
                reason=content_result.reason,
            )
            if action_applied:
                # Удаляем сообщения если настроено
                if settings.auto_mute_delete_messages:
                    await delete_user_messages(bot, chat_id, user_id)

                # ─── ОТПРАВКА В ЖУРНАЛ ДЛЯ CRITERION_6 ───
                # Отправляем уведомление в журнал группы если настройка включена
                if settings.send_to_journal:
                    await _send_criterion6_to_journal(
                        bot=bot,
                        session=session,
                        chat_id=chat_id,
                        user=user,
                        reason=content_result.reason,
                        action=content_result.action,
                        matched_word=content_result.matched_word or "",
                    )

                return {
                    "action_taken": f"criterion_6_{content_result.action}",
                    "reason": content_result.reason,
                    "changes": None,
                }

    # ─────────────────────────────────────────────────────────
    # ШАГ 5: Проверяем изменения профиля
    # ─────────────────────────────────────────────────────────
    changes = await check_profile_changes(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        current_first_name=current_first_name,
        current_last_name=current_last_name,
        current_username=current_username,
        current_has_photo=current_has_photo,
        current_photo_id=current_photo_id,
    )

    # ─────────────────────────────────────────────────────────
    # ШАГ 6: Обрабатываем изменения
    # ─────────────────────────────────────────────────────────
    if changes:
        return await _handle_profile_changes(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            snapshot=snapshot,
            changes=changes,
            current_has_photo=current_has_photo,
            # Передаём ID фото для обновления снапшота
            current_photo_id=current_photo_id,
            # Передаём возраст фото для критериев 4 и 5
            current_photo_age_days=current_photo_age_days,
        )

    return {"action_taken": None, "reason": None, "changes": None}


# ============================================================
# ФУНКЦИЯ: ОБРАБОТКА ПЕРВОГО СООБЩЕНИЯ (FALLBACK)
# ============================================================
async def _handle_first_message(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    user: User,
) -> Dict[str, Any]:
    """
    FALLBACK: Обрабатывает первое сообщение пользователя в группе.

    ВАЖНО: Эта функция вызывается только если снапшот НЕ существует.
    С версии 2024-12: снапшот создаётся при JOIN (в visual_captcha_handler),
    поэтому эта функция - FALLBACK для:
    1. Пользователей, вступивших ДО включения модуля
    2. Пользователей, вступивших через способы без chat_member_updated
    3. Ошибок при создании снапшота при JOIN

    ВНИМАНИЕ: joined_at будет установлен как время первого сообщения,
    а не реальное время входа. Это некорректно для расчёта minutes_since_join,
    но приемлемо для fallback-случаев.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        user: Пользователь

    Returns:
        Dict с результатом обработки
    """
    chat_id = message.chat.id
    user_id = user.id

    logger.info(
        f"[PROFILE_MONITOR] FALLBACK: Creating snapshot on first message "
        f"(no snapshot from JOIN): user={user_id} chat={chat_id}"
    )

    # Получаем данные профиля через Pyrogram
    profile_data = await get_user_profile_data(user_id)
    has_photo = profile_data.get("has_photo", False)
    photo_id = profile_data.get("photo_id")
    account_age_days = profile_data.get("account_age_days")

    # Создаём снимок профиля
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    snapshot = await create_profile_snapshot(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        has_photo=has_photo,
        photo_id=photo_id,
        account_age_days=account_age_days,
        is_premium=user.is_premium or False,
    )

    # Устанавливаем время первого сообщения
    snapshot = await update_profile_snapshot(
        session=session,
        snapshot=snapshot,
        first_message_at=now,
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА ФОТО ПРОФИЛЯ ПРИ ПЕРВОМ СООБЩЕНИИ
    # Если у пользователя есть фото и включена проверка - проверяем
    # ─────────────────────────────────────────────────────────
    if has_photo and settings.check_profile_photo_filter:
        logger.info(
            f"[PHOTO_FILTER] First message, checking profile photo: "
            f"user={user_id} chat={chat_id}"
        )
        # Проверяем фото профиля
        match_result = await check_profile_photo_scam(
            session=session,
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        # Если найдено совпадение - применяем действие (мут + удаление сообщений)
        if match_result and match_result.get("matched"):
            return await apply_photo_filter_action(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user_id=user_id,
                user=user,
                match_result=match_result,
                settings=settings,
            )

    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 6: Запрещённый контент в имени/bio (ПРОВЕРЯЕМ ПЕРВЫМ!)
    # ─────────────────────────────────────────────────────────
    if settings.auto_mute_forbidden_content:
        full_name = " ".join(filter(None, [user.first_name, user.last_name]))
        bio = None
        try:
            user_chat = await bot.get_chat(user_id)
            bio = getattr(user_chat, "bio", None)
        except Exception:
            pass

        content_result = await check_name_and_bio_content(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            full_name=full_name,
            bio=bio,
        )

        if content_result.should_act:
            logger.warning(
                f"[PROFILE_MONITOR] CRITERION_6 (first message): user={user_id} "
                f"chat={chat_id} reason={content_result.reason}"
            )
            action_applied = await apply_content_filter_action(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                action=content_result.action,
                duration=content_result.action_duration,
                reason=content_result.reason,
            )
            if action_applied:
                if settings.auto_mute_delete_messages:
                    await delete_user_messages(bot, chat_id, user_id)

                # ─── ОТПРАВКА В ЖУРНАЛ ДЛЯ CRITERION_6 (first message) ───
                # Отправляем уведомление в журнал группы если настройка включена
                if settings.send_to_journal:
                    await _send_criterion6_to_journal(
                        bot=bot,
                        session=session,
                        chat_id=chat_id,
                        user=user,
                        reason=content_result.reason,
                        action=content_result.action,
                        matched_word=content_result.matched_word or "",
                    )

                return {
                    "action_taken": f"criterion_6_{content_result.action}",
                    "reason": content_result.reason,
                    "changes": None,
                }

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА КРИТЕРИЯ 1: Нет фото + молодой аккаунт
    # ─────────────────────────────────────────────────────────
    should_mute, reason = await check_auto_mute_criteria(
        session=session,
        settings=settings,
        snapshot=snapshot,
        has_recent_name_change=False,  # Первое сообщение - смены имени ещё не было
    )

    if should_mute:
        return await _apply_auto_mute_action(
            message=message,
            session=session,
            bot=bot,
            settings=settings,
            snapshot=snapshot,
            reason=reason,
        )

    return {"action_taken": None, "reason": None, "changes": None}


# ============================================================
# ФУНКЦИЯ: ОБРАБОТКА ИЗМЕНЕНИЙ ПРОФИЛЯ
# ============================================================
async def _handle_profile_changes(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    snapshot: ProfileSnapshot,
    changes: list,
    current_has_photo: bool,
    current_photo_id: Optional[str] = None,
    current_photo_age_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Обрабатывает обнаруженные изменения профиля.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        snapshot: Снимок профиля
        changes: Список изменений
        current_has_photo: Есть ли фото сейчас
        current_photo_age_days: Возраст текущего фото в днях (для критериев 4,5)

    Returns:
        Dict с результатом обработки
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user

    logger.info(
        f"[PROFILE_MONITOR] Profile changes detected: user={user_id} "
        f"chat={chat_id} changes={changes}"
    )

    # Проверяем есть ли смена имени среди изменений
    name_changed = any(c["type"] == "name" for c in changes)

    # Вычисляем время с момента входа
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    time_diff = now - snapshot.joined_at
    minutes_since_join = int(time_diff.total_seconds() / 60)

    # Логируем каждое изменение
    log_entries = []
    for change in changes:
        # ─────────────────────────────────────────────────────────
        # Пропускаем внутренние изменения (например обновление формата photo_id)
        # Они нужны только для обновления snapshot, не для логирования
        # ─────────────────────────────────────────────────────────
        if change["type"].startswith("_internal"):
            continue

        # Проверяем настройки логирования
        if change["type"] == "name" and not settings.log_name_changes:
            continue
        if change["type"] == "username" and not settings.log_username_changes:
            continue
        if change["type"].startswith("photo") and not settings.log_photo_changes:
            continue

        entry = await log_profile_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            change_type=change["type"],
            old_value=change["old"],
            new_value=change["new"],
            minutes_since_join=minutes_since_join,
            message_id=message.message_id,
        )
        log_entries.append(entry)

    # Обновляем снимок профиля (включая photo_id для определения смены фото)
    current_full_name = " ".join(filter(None, [user.first_name, user.last_name]))
    await update_profile_snapshot(
        session=session,
        snapshot=snapshot,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=current_full_name,
        username=user.username,
        has_photo=current_has_photo,
        photo_id=current_photo_id,
    )

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА КРИТЕРИЕВ АВТОМУТА
    # ─────────────────────────────────────────────────────────
    # КРИТЕРИЙ 1: Смена имени + смена фото + сообщение в течение 20 мин
    # КРИТЕРИЙ 2: Смена имени + сообщение в течение 20 мин

    # Проверяем есть ли смена фото среди изменений
    photo_changed = any(c["type"].startswith("photo") for c in changes)

    # ─────────────────────────────────────────────────────────
    # КРОСС-ГРУППОВАЯ ДЕТЕКЦИЯ: трекинг смены профиля
    # Работает независимо от Profile Monitor автомута
    # ─────────────────────────────────────────────────────────
    if name_changed or photo_changed:
        try:
            # Определяем тип изменения для трекинга
            if name_changed and photo_changed:
                # Оба изменения — логируем как both
                change_type = ProfileChangeType.both
            elif name_changed:
                # Только смена имени
                change_type = ProfileChangeType.name
            else:
                # Только смена фото
                change_type = ProfileChangeType.photo

            # Записываем факт изменения профиля
            await track_profile_change(
                session=session,
                user_id=user_id,
                chat_id=chat_id,
                change_type=change_type,
            )
            # Логируем трекинг
            logger.debug(
                f"[CROSS_GROUP] Tracked profile change: user={user_id} "
                f"chat={chat_id} type={change_type.value}"
            )
            # Проверяем детекцию (срабатывает если выполнены все условия)
            detection_result = await check_cross_group_detection(
                session=session,
                user_id=user_id,
            )
            # Если детекция сработала — применяем действие
            if detection_result:
                # Логируем детекцию скамера
                logger.warning(
                    f"[CROSS_GROUP] DETECTED SCAMMER on PROFILE CHANGE: "
                    f"user={user_id} groups={detection_result.get('groups', [])}"
                )
                # Применяем действие во всех затронутых группах
                await apply_cross_group_action(
                    session=session,
                    bot=bot,
                    user_id=user_id,
                    detection_data=detection_result,
                )
        except Exception as e:
            # Ошибки кросс-групповой детекции не должны ломать основной флоу
            logger.error(f"[CROSS_GROUP] Error in profile change tracking: {e}")

    # ─────────────────────────────────────────────────────────
    # ПРОВЕРКА ФОТО ПРОФИЛЯ ЧЕРЕЗ SCAM MEDIA FILTER
    # Срабатывает при ИЗМЕНЕНИИ фото если настройка включена
    # ─────────────────────────────────────────────────────────
    if photo_changed and settings.check_profile_photo_filter:
        logger.info(
            f"[PHOTO_FILTER] Photo changed, checking against scam filter: "
            f"user={user_id} chat={chat_id}"
        )
        # Проверяем фото профиля
        match_result = await check_profile_photo_scam(
            session=session,
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        # Если найдено совпадение - применяем действие (мут + удаление сообщений)
        if match_result and match_result.get("matched"):
            return await apply_photo_filter_action(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user_id=user_id,
                user=user,
                match_result=match_result,
                settings=settings,
            )

    # Если была смена имени ИЛИ смена фото - проверяем критерии автомута
    if name_changed or photo_changed:
        # Проверяем была ли смена имени в окне времени (24 часа)
        recent_name_change = await has_recent_name_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            window_hours=settings.name_change_window_hours,
        )

        # Проверяем была ли смена фото в окне времени (24 часа)
        recent_photo_change = await has_recent_photo_change(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            window_hours=settings.name_change_window_hours,
        )

        # Логируем для отладки
        logger.info(
            f"[PROFILE_MONITOR] Auto-mute pre-check: chat={chat_id} user={user_id} "
            f"name_changed={name_changed} photo_changed={photo_changed} "
            f"recent_name={recent_name_change} recent_photo={recent_photo_change} "
            f"minutes_since_join={minutes_since_join}"
        )

        # Вызываем проверку критериев автомута
        # Передаём current_photo_age_days для критериев 4 и 5
        should_mute, reason = await check_auto_mute_criteria(
            session=session,
            settings=settings,
            snapshot=snapshot,
            has_recent_name_change=recent_name_change,
            has_recent_photo_change=recent_photo_change,
            minutes_since_change=float(minutes_since_join),
            current_photo_age_days=current_photo_age_days,
        )

        # Если критерий сработал - применяем автомут
        if should_mute:
            return await _apply_auto_mute_action(
                message=message,
                session=session,
                bot=bot,
                settings=settings,
                snapshot=snapshot,
                reason=reason,
            )

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА В ЖУРНАЛ (если настроено)
    # ─────────────────────────────────────────────────────────
    # Логируем входные данные для отладки
    logger.info(
        f"[PROFILE_MONITOR] Journal check: chat={chat_id} user={user_id} "
        f"send_to_journal={settings.send_to_journal} "
        f"log_entries={len(log_entries)} min_changes={settings.min_changes_for_journal}"
    )

    # Проверяем условие отправки в журнал
    if settings.send_to_journal and log_entries:
        # Проверяем достаточно ли изменений для отправки
        if len(log_entries) >= settings.min_changes_for_journal:
            # Логируем что отправляем в журнал
            logger.info(f"[PROFILE_MONITOR] Sending to journal: chat={chat_id} user={user_id}")
            # Отправляем уведомление в журнал группы
            await _send_changes_to_journal(
                bot=bot,
                session=session,
                chat_id=chat_id,
                user=user,
                changes=changes,
                log_entry=log_entries[0],
                minutes_since_join=minutes_since_join,
            )
        else:
            # Логируем причину пропуска - недостаточно изменений
            logger.info(
                f"[PROFILE_MONITOR] Skip journal: not enough changes "
                f"({len(log_entries)} < {settings.min_changes_for_journal})"
            )
    else:
        # Логируем причину пропуска - отключено или нет записей
        if not settings.send_to_journal:
            logger.info(f"[PROFILE_MONITOR] Skip journal: send_to_journal=False")
        elif not log_entries:
            logger.info(f"[PROFILE_MONITOR] Skip journal: no log entries")

    # ─────────────────────────────────────────────────────────
    # ОТПРАВКА В ГРУППУ (если настроено)
    # ─────────────────────────────────────────────────────────
    # Проверяем настройку отправки в группу
    if settings.send_to_group and name_changed:
        # Логируем что отправляем в группу
        logger.info(f"[PROFILE_MONITOR] Sending to group: chat={chat_id} user={user_id}")

        # Получаем историю изменений имен для отображения
        history = await get_user_change_history(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            limit=10,
        )

        # Отправляем простое уведомление в группу
        await _send_changes_to_group(
            bot=bot,
            chat_id=chat_id,
            user=user,
            changes=changes,
            history=history,
        )
    elif not settings.send_to_group:
        # Логируем причину пропуска
        logger.debug(f"[PROFILE_MONITOR] Skip group: send_to_group=False")

    # Возвращаем результат обработки
    return {
        "action_taken": "logged",
        "reason": None,
        "changes": changes,
    }


# ============================================================
# ФУНКЦИЯ: ПРИМЕНЕНИЕ АВТОМУТА
# ============================================================
async def _apply_auto_mute_action(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    settings: ProfileMonitorSettings,
    snapshot: ProfileSnapshot,
    reason: str,
) -> Dict[str, Any]:
    """
    Применяет автоматический мут и сопутствующие действия.

    Args:
        message: Сообщение
        session: AsyncSession
        bot: Bot instance
        settings: Настройки модуля
        snapshot: Снимок профиля
        reason: Причина мута

    Returns:
        Dict с результатом
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user

    logger.warning(
        f"[PROFILE_MONITOR] Applying auto-mute: user={user_id} "
        f"chat={chat_id} reason={reason}"
    )

    # Применяем мут
    mute_success = await apply_auto_mute(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        reason=reason,
    )

    # Удаляем сообщения если настроено
    deleted_count = 0
    if mute_success and settings.auto_mute_delete_messages:
        deleted_count = await delete_user_messages(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

    # Логируем действие
    log_entry = await log_profile_change(
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        change_type="auto_mute",
        old_value=None,
        new_value=reason,
        action_taken="auto_mute",
    )

    # Отправляем уведомление в журнал
    if settings.send_to_journal:
        await _send_auto_mute_to_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user=user,
            reason=reason,
            deleted_count=deleted_count,
            log_entry=log_entry,
        )

    return {
        "action_taken": "auto_mute",
        "reason": reason,
        "changes": None,
    }


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА ИЗМЕНЕНИЙ В ЖУРНАЛ
# ============================================================
async def _send_changes_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    changes: list,
    log_entry,
    minutes_since_join: int,
) -> None:
    """
    Отправляет уведомление об изменениях профиля в журнал группы.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user: Пользователь
        changes: Список изменений
        log_entry: Запись в журнале
        minutes_since_join: Минут с момента входа
    """
    # Формируем имя пользователя для отображения
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    username_str = f" (@{user.username})" if user.username else ""

    # Формируем текст изменений
    changes_text = []
    for change in changes:
        if change["type"] == "name":
            changes_text.append(f"Имя: {change['old']} → {change['new']}")
        elif change["type"] == "username":
            changes_text.append(f"Username: {change['old']} → {change['new']}")
        elif change["type"] == "photo_added":
            changes_text.append("Добавлено фото профиля")
        elif change["type"] == "photo_removed":
            changes_text.append("Удалено фото профиля")
        elif change["type"] == "photo_changed":
            changes_text.append("Изменено фото профиля")

    changes_list = "\n".join(f"  • {c}" for c in changes_text)

    # Формируем сообщение
    text = (
        f"🔄 <b>Изменение профиля</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"⏱ Через {minutes_since_join} мин после входа\n\n"
        f"<b>Изменения:</b>\n"
        f"{changes_list}"
    )

    # Отправляем в журнал с кнопками
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_journal_action_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=log_entry.id if log_entry else 0,
        ),
    )


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА АВТОМУТА В ЖУРНАЛ
# ============================================================
async def _send_auto_mute_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    reason: str,
    deleted_count: int,
    log_entry,
) -> None:
    """
    Отправляет уведомление об автомуте в журнал группы.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user: Пользователь
        reason: Причина мута
        deleted_count: Количество удалённых сообщений
        log_entry: Запись в журнале
    """
    # Формируем имя пользователя для отображения
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    username_str = f" (@{user.username})" if user.username else ""

    # Формируем сообщение
    text = (
        f"🔇 <b>Автоматический мут</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"<b>Причина:</b>\n"
        f"{reason}\n\n"
        f"<b>Действия:</b>\n"
        f"  • Мут навсегда\n"
    )

    if deleted_count > 0:
        text += f"  • Удалено {deleted_count} сообщений"

    # Отправляем в журнал с кнопками
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_auto_mute_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=log_entry.id if log_entry else 0,
        ),
    )


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА ИЗМЕНЕНИЙ В ГРУППУ (для всех участников)
# ============================================================
async def _send_changes_to_group(
    bot: Bot,
    chat_id: int,
    user: User,
    changes: list,
    history: list,
) -> None:
    """
    Отправляет простое уведомление об изменениях профиля прямо в группу.

    Это сообщение видят все участники группы (не только админы).
    Формат простой и информативный:
    - Кто сменил имя
    - Было / Стало
    - История всех имен с датами

    Args:
        bot: Bot instance для отправки сообщений
        chat_id: ID группы куда отправлять
        user: Пользователь который изменил профиль
        changes: Список обнаруженных изменений
        history: История изменений профиля из БД
    """
    # Формируем имя пользователя для отображения (кликабельная ссылка)
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    # Добавляем @username если есть
    username_str = f" (@{user.username})" if user.username else ""

    # Ищем изменение имени среди изменений
    name_change = None
    for change in changes:
        if change["type"] == "name":
            name_change = change
            break

    # Если нет изменения имени - ничего не отправляем в группу
    if not name_change:
        return

    # Формируем основной текст сообщения
    text = (
        f"📝 <b>Пользователь сменил имя</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"<b>Было:</b> {name_change['old']}\n"
        f"<b>Стало:</b> {name_change['new']}\n"
    )

    # Добавляем историю имен если есть записи
    if history:
        text += "\n<b>История имен:</b>\n"
        # Перебираем историю изменений (от новых к старым)
        for entry in history[:5]:  # Показываем последние 5 записей
            # Форматируем дату
            entry_date = entry.created_at.strftime("%d.%m.%Y %H:%M")
            # Добавляем строку с именем и датой
            if entry.change_type == "name":
                text += f"  • {entry.new_value} — {entry_date}\n"

    # Отправляем сообщение в группу
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )
        # Логируем успешную отправку
        logger.info(f"[PROFILE_MONITOR] Sent to group: chat={chat_id} user={user.id}")
    except Exception as e:
        # Логируем ошибку но не падаем
        logger.error(f"[PROFILE_MONITOR] Failed to send to group: {e}")


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА CRITERION_6 В ЖУРНАЛ
# ============================================================
async def _send_criterion6_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    reason: str,
    action: str,
    matched_word: str,
) -> None:
    """
    Отправляет уведомление о срабатывании CRITERION_6 в журнал группы.

    CRITERION_6 срабатывает когда в имени или bio пользователя
    обнаружено запрещённое слово из категорий harmful/obfuscated.

    Args:
        bot: Bot instance для отправки сообщений
        session: AsyncSession для работы с БД
        chat_id: ID группы где сработал критерий
        user: Пользователь с запрещённым контентом
        reason: Причина срабатывания (например "Запрещённое слово в имени: кокс")
        action: Применённое действие (mute/ban/kick)
        matched_word: Какое слово сработало
    """
    # ─────────────────────────────────────────────────────────
    # Формируем кликабельную ссылку на пользователя
    # ─────────────────────────────────────────────────────────
    # Имя пользователя для отображения
    user_full_name = user.full_name or "Без имени"
    # Создаём ссылку вида tg://user?id=123 которая откроет профиль при клике
    user_link = f'<a href="tg://user?id={user.id}">{user_full_name}</a>'
    # Добавляем @username если есть
    username_str = f" (@{user.username})" if user.username else ""

    # ─────────────────────────────────────────────────────────
    # Формируем кликабельную ссылку на группу
    # ─────────────────────────────────────────────────────────
    try:
        # Получаем информацию о группе
        chat = await bot.get_chat(chat_id)
        # Название группы для отображения
        group_title = chat.title or f"Группа {chat_id}"
        # Формируем ссылку на группу
        if chat.username:
            # Публичная группа — ссылка через @username
            group_link = f'<a href="https://t.me/{chat.username}">{group_title}</a>'
        else:
            # Приватная группа — ссылка через tg://openmessage
            # Убираем -100 префикс для формирования ссылки
            clean_chat_id = str(chat_id).replace("-100", "")
            group_link = f'<a href="tg://openmessage?chat_id={clean_chat_id}">{group_title}</a>'
    except Exception as e:
        # Если не удалось получить информацию о группе — используем ID
        logger.warning(f"[CRITERION_6] Cannot get chat info: {e}")
        group_link = f"Группа {chat_id}"

    # ─────────────────────────────────────────────────────────
    # Форматируем текст действия
    # ─────────────────────────────────────────────────────────
    # Словарь для перевода действий в читаемый формат
    action_map = {
        "mute": "Мут навсегда",
        "ban": "Бан",
        "kick": "Кик",
        "warn": "Предупреждение",
    }
    # Получаем читаемое название действия
    action_text = action_map.get(action, action)

    # ─────────────────────────────────────────────────────────
    # Формируем сообщение для журнала
    # ─────────────────────────────────────────────────────────
    text = (
        f"🚫 <b>Запрещённый контент в профиле</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"🏢 Группа: {group_link}\n\n"
        f"<b>Причина:</b>\n"
        f"{reason}\n\n"
        f"<b>Действие:</b>\n"
        f"  • {action_text}\n\n"
        f"#criterion6 #profile_filter"
    )

    # ─────────────────────────────────────────────────────────
    # Отправляем в журнал группы с кнопками
    # ─────────────────────────────────────────────────────────
    # log_id = 0 т.к. для CRITERION_6 не создаём запись в profile_changes
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_criterion6_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=0,  # Нет записи в журнале изменений профиля
        ),
    )

    # Логируем успешную отправку
    logger.info(
        f"[CRITERION_6] Sent to journal: chat={chat_id} user={user.id} "
        f"word={matched_word} action={action}"
    )


# ============================================================
# ФУНКЦИЯ: ПРОВЕРКА ФОТО ПРОФИЛЯ ЧЕРЕЗ SCAM MEDIA FILTER
# ============================================================
async def check_profile_photo_scam(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Проверяет фото профиля пользователя на совпадение с banned хешами.

    Логика:
    1. Получаем фото профиля через Pyrogram
    2. Скачиваем фото в байты
    3. Вычисляем perceptual hash
    4. Сравниваем с banned хешами в БД
    5. Возвращаем результат совпадения

    Args:
        session: AsyncSession для БД
        bot: Bot instance
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        Dict с результатом или None если не найдено совпадение
        {
            "matched": True,
            "hash_id": int,
            "distance": int,
            "description": str | None,
        }
    """
    # ─────────────────────────────────────────────────────────
    # ШАГ 1: Проверяем доступность Pyrogram
    # ─────────────────────────────────────────────────────────
    if not pyrogram_service.is_available():
        logger.debug("[PHOTO_FILTER] Pyrogram not available, skip photo check")
        return None

    # ─────────────────────────────────────────────────────────
    # ШАГ 2: Получаем фото профиля через Pyrogram
    # ─────────────────────────────────────────────────────────
    try:
        photos = await pyrogram_service.get_profile_photos_dates(user_id)
        if not photos:
            logger.debug(f"[PHOTO_FILTER] No profile photos for user={user_id}")
            return None

        # Берём первое (текущее) фото
        current_photo = photos[0]
        file_id = current_photo.get("file_id")
        if not file_id:
            logger.debug(f"[PHOTO_FILTER] No file_id for user={user_id}")
            return None

    except Exception as e:
        logger.warning(f"[PHOTO_FILTER] Error getting photos for user={user_id}: {e}")
        return None

    # ─────────────────────────────────────────────────────────
    # ШАГ 3: Скачиваем фото через Pyrogram
    # ─────────────────────────────────────────────────────────
    try:
        # Скачиваем фото в память - in_memory=True возвращает BytesIO объект
        buffer = await pyrogram_service.client.download_media(
            file_id,
            in_memory=True,
        )

        if buffer is None:
            logger.warning(f"[PHOTO_FILTER] download_media returned None for user={user_id}")
            return None

        image_data = buffer.getvalue()

        if not image_data or len(image_data) < 100:
            logger.warning(f"[PHOTO_FILTER] Empty or too small photo for user={user_id}")
            return None

        logger.info(f"[PHOTO_FILTER] Downloaded photo for user={user_id}, size={len(image_data)}")

    except Exception as e:
        logger.warning(f"[PHOTO_FILTER] Error downloading photo for user={user_id}: {e}")
        return None

    # ─────────────────────────────────────────────────────────
    # ШАГ 4: Вычисляем хеш изображения
    # ─────────────────────────────────────────────────────────
    image_hashes = compute_image_hash(image_data)
    if image_hashes is None:
        logger.warning(f"[PHOTO_FILTER] Failed to compute hash for user={user_id}")
        return None

    logger.debug(
        f"[PHOTO_FILTER] Computed hash for user={user_id}: "
        f"phash={image_hashes.phash}, dhash={image_hashes.dhash}"
    )

    # ─────────────────────────────────────────────────────────
    # ШАГ 5: Получаем настройки Scam Media Filter для порога
    # ─────────────────────────────────────────────────────────
    scam_settings = await ScamMediaSettingsService.get_settings(session, chat_id)
    # Если настроек нет - используем дефолтный порог 10
    threshold = scam_settings.threshold if scam_settings else 10
    include_global = scam_settings.use_global_hashes if scam_settings else True

    # ─────────────────────────────────────────────────────────
    # ШАГ 6: Получаем banned хеши для сравнения
    # ─────────────────────────────────────────────────────────
    banned_hashes = await BannedHashService.get_hashes_for_group(
        session, chat_id, include_global
    )

    if not banned_hashes:
        logger.debug(f"[PHOTO_FILTER] No banned hashes for chat={chat_id}")
        return None

    logger.debug(f"[PHOTO_FILTER] Checking against {len(banned_hashes)} banned hashes")

    # ─────────────────────────────────────────────────────────
    # ШАГ 7: Сравниваем с каждым banned хешем
    # ─────────────────────────────────────────────────────────
    best_match = None
    best_distance = 64  # Максимальное расстояние

    for banned_hash in banned_hashes:
        # Сравниваем pHash
        distance = compare_hashes(image_hashes.phash, banned_hash.phash)

        if distance < best_distance:
            best_distance = distance
            if distance <= threshold:
                best_match = banned_hash

    # ─────────────────────────────────────────────────────────
    # ШАГ 8: Возвращаем результат
    # ─────────────────────────────────────────────────────────
    if best_match:
        logger.warning(
            f"[PHOTO_FILTER] MATCH FOUND! user={user_id} chat={chat_id} "
            f"hash_id={best_match.id} distance={best_distance} "
            f"description={best_match.description}"
        )
        return {
            "matched": True,
            "hash_id": best_match.id,
            "distance": best_distance,
            "description": best_match.description,
        }

    logger.debug(
        f"[PHOTO_FILTER] No match for user={user_id}, best_distance={best_distance}"
    )
    return None


# ============================================================
# ФУНКЦИЯ: ПРИМЕНЕНИЕ ДЕЙСТВИЯ ПРИ СОВПАДЕНИИ ФОТО ПРОФИЛЯ
# ============================================================
async def apply_photo_filter_action(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    user: User,
    match_result: Dict[str, Any],
    settings: ProfileMonitorSettings,
) -> Dict[str, Any]:
    """
    Применяет действие при совпадении фото профиля с banned хешем.

    Действия: мут навсегда + удаление всех сообщений скаммера.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user_id: ID пользователя
        user: User объект
        match_result: Результат проверки из check_profile_photo_scam()
        settings: Настройки Profile Monitor

    Returns:
        Dict с результатом применения действия
    """
    reason = (
        f"Фото профиля совпало с запрещённым изображением "
        f"(distance={match_result['distance']})"
    )
    if match_result.get("description"):
        reason += f": {match_result['description']}"

    logger.warning(
        f"[PHOTO_FILTER] Applying action: user={user_id} chat={chat_id} "
        f"reason={reason}"
    )

    # ─────────────────────────────────────────────────────────
    # Применяем мут навсегда
    # ─────────────────────────────────────────────────────────
    mute_success = await apply_auto_mute(
        bot=bot,
        session=session,
        chat_id=chat_id,
        user_id=user_id,
        reason=reason,
    )

    # ─────────────────────────────────────────────────────────
    # Удаляем все сообщения скаммера
    # ─────────────────────────────────────────────────────────
    deleted_count = 0
    if mute_success:
        deleted_count = await delete_user_messages(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
        )

    # ─────────────────────────────────────────────────────────
    # Увеличиваем счётчик срабатываний хеша
    # ─────────────────────────────────────────────────────────
    await BannedHashService.increment_match_count(session, match_result["hash_id"])

    # ─────────────────────────────────────────────────────────
    # Отправляем в журнал если настроено
    # ─────────────────────────────────────────────────────────
    if settings.send_to_journal:
        await _send_photo_filter_to_journal(
            bot=bot,
            session=session,
            chat_id=chat_id,
            user=user,
            reason=reason,
            deleted_count=deleted_count,
            match_result=match_result,
        )

    return {
        "action_taken": "photo_filter_mute",
        "reason": reason,
        "changes": None,
    }


# ============================================================
# ФУНКЦИЯ: ОТПРАВКА PHOTO FILTER В ЖУРНАЛ
# ============================================================
async def _send_photo_filter_to_journal(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user: User,
    reason: str,
    deleted_count: int,
    match_result: Dict[str, Any],
) -> None:
    """
    Отправляет уведомление о срабатывании Photo Filter в журнал.

    Args:
        bot: Bot instance
        session: AsyncSession
        chat_id: ID группы
        user: Пользователь
        reason: Причина
        deleted_count: Количество удалённых сообщений
        match_result: Результат совпадения
    """
    # Формируем ссылку на пользователя
    user_full_name = user.full_name or "Без имени"
    user_link = f'<a href="tg://user?id={user.id}">{user_full_name}</a>'
    username_str = f" (@{user.username})" if user.username else ""

    # Формируем ссылку на группу
    try:
        chat = await bot.get_chat(chat_id)
        group_title = chat.title or f"Группа {chat_id}"
        if chat.username:
            group_link = f'<a href="https://t.me/{chat.username}">{group_title}</a>'
        else:
            clean_chat_id = str(chat_id).replace("-100", "")
            group_link = f'<a href="tg://openmessage?chat_id={clean_chat_id}">{group_title}</a>'
    except Exception:
        group_link = f"Группа {chat_id}"

    # Получаем hash_id для возможности удаления
    hash_id = match_result.get("hash_id", "?")
    distance = match_result.get("distance", "?")
    description = match_result.get("description", "")

    # Формируем текст
    text = (
        f"🖼 <b>Запрещённое фото профиля</b>\n\n"
        f"👤 {user_link}{username_str}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"🏢 Группа: {group_link}\n\n"
        f"<b>Причина:</b>\n"
        f"{reason}\n\n"
        f"<b>Совпавший хеш:</b>\n"
        f"  • ID: <code>{hash_id}</code>\n"
        f"  • Distance: {distance}\n"
    )
    if description:
        text += f"  • Описание: {description}\n"

    text += (
        f"\n<b>Действие:</b>\n"
        f"  • Мут навсегда\n"
    )

    if deleted_count > 0:
        text += f"  • Удалено {deleted_count} сообщений\n"

    text += f"\n#photo_filter #scam_media #hash_{hash_id}"

    # Отправляем в журнал с кнопками
    await send_journal_event(
        bot=bot,
        session=session,
        group_id=chat_id,
        message_text=text,
        reply_markup=get_criterion6_kb(
            chat_id=chat_id,
            user_id=user.id,
            log_id=0,
        ),
    )
