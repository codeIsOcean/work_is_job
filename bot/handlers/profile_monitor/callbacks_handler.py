# bot/handlers/profile_monitor/callbacks_handler.py
"""
Обработчики callback-кнопок для модуля Profile Monitor.

Обрабатывает кнопки:
- pm_mute - Замутить пользователя
- pm_ban - Забанить пользователя
- pm_kick - Кикнуть пользователя
- pm_unmute - Размутить пользователя
- pm_send_group - Отправить в группу
- pm_ok - Закрыть уведомление
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery, ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models_profile_monitor import ProfileChangeLog
from bot.services.profile_monitor.profile_monitor_service import (
    get_user_change_history,
    log_profile_change,
)
from bot.services.restriction_service import (
    save_restriction,
    deactivate_restriction,
)

# Логгер модуля
logger = logging.getLogger(__name__)

# Роутер для callback handlers
router = Router(name="profile_monitor_callbacks")


# ============================================================
# CALLBACK: ЗАМУТИТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================
@router.callback_query(F.data.startswith("pm_mute:"))
async def callback_mute_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Мут".

    Формат callback_data: pm_mute:chat_id:user_id:log_id
    """
    # Парсим данные из callback
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    logger.info(
        f"[PROFILE_MONITOR] Callback mute: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Применяем мут
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
        )

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=None,
        )

        # Сохраняем в БД
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="mute",
            reason="profile_monitor_manual",
            restricted_by=callback.from_user.id,
            until_date=None,
        )

        # Обновляем запись в журнале
        if log_id:
            await _update_log_action(session, log_id, "manual_mute")

        # Обновляем сообщение в журнале
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n✅ <b>Замучен</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Пользователь замучен")

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Mute failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: ЗАБАНИТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================
@router.callback_query(F.data.startswith("pm_ban:"))
async def callback_ban_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Бан".

    Формат callback_data: pm_ban:chat_id:user_id:log_id
    """
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    logger.info(
        f"[PROFILE_MONITOR] Callback ban: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Баним пользователя
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        # Сохраняем в БД
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="ban",
            reason="profile_monitor_manual",
            restricted_by=callback.from_user.id,
            until_date=None,
        )

        # Обновляем запись в журнале
        if log_id:
            await _update_log_action(session, log_id, "manual_ban")

        # Обновляем сообщение
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n🚫 <b>Забанен</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Пользователь забанен")

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Ban failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: КИКНУТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================
@router.callback_query(F.data.startswith("pm_kick:"))
async def callback_kick_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Кик".

    Формат callback_data: pm_kick:chat_id:user_id:log_id
    """
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    logger.info(
        f"[PROFILE_MONITOR] Callback kick: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Кикаем пользователя (бан + разбан)
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)

        # Обновляем запись в журнале
        if log_id:
            await _update_log_action(session, log_id, "manual_kick")

        # Обновляем сообщение
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n👢 <b>Кикнут</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Пользователь кикнут")

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Kick failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: РАЗМУТИТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================
@router.callback_query(F.data.startswith("pm_unmute:"))
async def callback_unmute_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Размут".

    Формат callback_data: pm_unmute:chat_id:user_id:log_id
    """
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    logger.info(
        f"[PROFILE_MONITOR] Callback unmute: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Снимаем мут (разрешаем всё)
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_invite_users=True,
        )

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
        )

        # Деактивируем в БД
        await deactivate_restriction(session, chat_id, user_id)

        # Обновляем сообщение
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n🔊 <b>Размучен</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Пользователь размучен")

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Unmute failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: ОТПРАВИТЬ В ГРУППУ
# ============================================================
@router.callback_query(F.data.startswith("pm_send_group:"))
async def callback_send_to_group(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Отправить в группу".

    Отправляет в группу уведомление с историей изменений профиля.
    Формат callback_data: pm_send_group:chat_id:user_id:log_id
    """
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    logger.info(
        f"[PROFILE_MONITOR] Callback send_to_group: chat={chat_id} user={user_id}"
    )

    try:
        # Получаем историю изменений профиля
        history = await get_user_change_history(session, chat_id, user_id, limit=10)

        if not history:
            await callback.answer("История изменений пуста")
            return

        # Формируем текст с историей
        history_lines = []
        for entry in reversed(history):  # От старых к новым
            if entry.change_type == "name":
                history_lines.append(f"  • {entry.old_value} → {entry.new_value}")
            elif entry.change_type == "auto_mute":
                history_lines.append(f"  • 🔇 Автомут: {entry.new_value}")

        if not history_lines:
            await callback.answer("Нет изменений для отображения")
            return

        # Пробуем получить информацию о пользователе
        try:
            chat_member = await bot.get_chat_member(chat_id, user_id)
            user = chat_member.user
            user_name = user.full_name
            username_str = f" (@{user.username})" if user.username else ""
        except Exception:
            user_name = f"ID: {user_id}"
            username_str = ""

        # Формируем сообщение для группы
        text = (
            f"⚠️ <b>Внимание! Изменения профиля</b>\n\n"
            f"👤 {user_name}{username_str}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            f"<b>История изменений:</b>\n"
            + "\n".join(history_lines)
        )

        # Отправляем в группу
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )

        # Обновляем запись в журнале
        if log_id:
            await _mark_sent_to_group(session, log_id)

        await callback.answer("Отправлено в группу")

    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Send to group failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: ЗАКРЫТЬ УВЕДОМЛЕНИЕ
# ============================================================
@router.callback_query(F.data.startswith("pm_ok:"))
async def callback_ok(
    callback: CallbackQuery,
) -> None:
    """
    Обработка кнопки "ОК" - удаляет клавиатуру.

    Формат callback_data: pm_ok:chat_id:user_id:log_id
    """
    try:
        # Убираем клавиатуру, оставляем текст
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Принято")
    except Exception as e:
        logger.debug(f"[PROFILE_MONITOR] OK callback error: {e}")
        await callback.answer()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
async def _update_log_action(
    session: AsyncSession,
    log_id: int,
    action: str,
) -> None:
    """Обновляет действие в записи журнала."""
    try:
        stmt = select(ProfileChangeLog).where(ProfileChangeLog.id == log_id)
        result = await session.execute(stmt)
        log_entry = result.scalar_one_or_none()

        if log_entry:
            log_entry.action_taken = action
            await session.commit()
    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Failed to update log action: {e}")


async def _mark_sent_to_group(
    session: AsyncSession,
    log_id: int,
) -> None:
    """Отмечает что запись была отправлена в группу."""
    try:
        stmt = select(ProfileChangeLog).where(ProfileChangeLog.id == log_id)
        result = await session.execute(stmt)
        log_entry = result.scalar_one_or_none()

        if log_entry:
            log_entry.sent_to_group = True
            await session.commit()
    except Exception as e:
        logger.error(f"[PROFILE_MONITOR] Failed to mark sent to group: {e}")


# ============================================================
# CALLBACK: МУТ НА 7 ДНЕЙ (для CRITERION_6)
# ============================================================
@router.callback_query(F.data.startswith("pm_mute7d:"))
async def callback_mute7d_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Мут 7д" - мут на 7 дней.

    Формат callback_data: pm_mute7d:chat_id:user_id:log_id
    Используется в клавиатуре CRITERION_6.
    """
    # Парсим данные из callback
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    # Извлекаем chat_id, user_id, log_id из callback_data
    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    # Логируем действие администратора
    logger.info(
        f"[PROFILE_MONITOR] Callback mute7d: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Импортируем datetime для вычисления until_date
        from datetime import datetime, timedelta

        # Вычисляем дату окончания мута (7 дней от текущего момента)
        until_date = datetime.now() + timedelta(days=7)

        # Создаём ограничения - запрещаем отправку сообщений
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
        )

        # Применяем мут на 7 дней
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )

        # Сохраняем ограничение в БД для отслеживания
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="mute",
            reason="criterion_6_manual_7d",
            restricted_by=callback.from_user.id,
            until_date=until_date,
        )

        # Обновляем запись в журнале если есть
        if log_id:
            await _update_log_action(session, log_id, "manual_mute_7d")

        # Обновляем сообщение в журнале — показываем кто замутил
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n🔇 <b>Мут 7 дней</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Мут на 7 дней применён")

    except Exception as e:
        # Логируем ошибку
        logger.error(f"[PROFILE_MONITOR] Mute 7d failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: МУТ НАВСЕГДА (для CRITERION_6)
# ============================================================
@router.callback_query(F.data.startswith("pm_mute_forever:"))
async def callback_mute_forever_user(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """
    Обработка кнопки "Мут ∞" - мут навсегда.

    Формат callback_data: pm_mute_forever:chat_id:user_id:log_id
    Используется в клавиатуре CRITERION_6.
    """
    # Парсим данные из callback
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка: неверный формат данных")
        return

    # Извлекаем chat_id, user_id, log_id из callback_data
    _, chat_id_str, user_id_str, log_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    log_id = int(log_id_str)

    # Логируем действие администратора
    logger.info(
        f"[PROFILE_MONITOR] Callback mute_forever: chat={chat_id} user={user_id} "
        f"by admin={callback.from_user.id}"
    )

    try:
        # Создаём ограничения - запрещаем отправку сообщений
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
        )

        # Применяем мут навсегда (until_date=None)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=None,
        )

        # Сохраняем ограничение в БД
        await save_restriction(
            session=session,
            chat_id=chat_id,
            user_id=user_id,
            restriction_type="mute",
            reason="criterion_6_manual_forever",
            restricted_by=callback.from_user.id,
            until_date=None,
        )

        # Обновляем запись в журнале
        if log_id:
            await _update_log_action(session, log_id, "manual_mute_forever")

        # Обновляем сообщение в журнале
        # ВАЖНО: используем html_text чтобы сохранить оригинальное HTML форматирование
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n🔇 <b>Мут навсегда</b> админом {callback.from_user.full_name}",
            parse_mode="HTML",
        )
        await callback.answer("Мут навсегда применён")

    except Exception as e:
        # Логируем ошибку
        logger.error(f"[PROFILE_MONITOR] Mute forever failed: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ============================================================
# CALLBACK: РАЗБАНИТЬ ПОЛЬЗОВАТЕЛЯ (ЗАГЛУШКА)
# ============================================================
@router.callback_query(F.data.startswith("pm_unban:"))
async def callback_unban_user(
    callback: CallbackQuery,
) -> None:
    """
    Обработка кнопки "Анбан" - ЗАГЛУШКА.

    Формат callback_data: pm_unban:chat_id:user_id:log_id

    TODO: Реализовать разбан пользователя.
    Сейчас просто показывает сообщение что функция не реализована.
    """
    # Логируем попытку использования
    logger.info(
        f"[PROFILE_MONITOR] Callback unban (stub): by admin={callback.from_user.id}"
    )

    # Показываем уведомление что функция ещё не реализована
    await callback.answer(
        "🚧 Разбан пока не реализован",
        show_alert=True,
    )
