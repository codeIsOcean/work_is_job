"""
Handler для команды /unscam - снятие метки скаммера с пользователя

ВАЖНО: Команда работает ТОЛЬКО в ЛС (private chat)
"""

import logging
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from sqlalchemy import select

from bot.database.session import get_session
from bot.services.spammer_registry import delete_spammer_record, get_spammer_record
from bot.database.models import UserGroup

logger = logging.getLogger(__name__)

unscam_router = Router()


def _build_unmute_permissions() -> ChatPermissions:
    """Полные права для размута"""
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_pin_messages=False,  # Это право обычно не даётся обычным участникам
    )


@unscam_router.message(Command("unscam"))
async def unscam_command(message: Message, bot: Bot):
    """
    Команда /unscam для снятия метки скаммера с пользователя

    Использование:
    /unscam <user_id>

    ВАЖНО: Работает ТОЛЬКО в ЛС (private chat)
    """
    # Проверка: команда только в ЛС
    if message.chat.type != "private":
        await message.answer("⚠️ Команда /unscam работает только в личных сообщениях бота")
        return

    # Парсинг аргументов
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(
                "❌ Неверный формат команды\n\n"
                "Использование: /unscam <user_id>\n"
                "Пример: /unscam 123456789"
            )
            return

        user_id = int(args[1])

    except ValueError:
        await message.answer("❌ Неверный формат user_id. Должно быть число.")
        return

    await message.answer(f"🔍 Проверяю пользователя {user_id}...")

    async with get_session() as session:
        # Проверяем, есть ли пользователь в списке скаммеров
        spammer_record = await get_spammer_record(session, user_id)

        if not spammer_record:
            await message.answer(
                f"ℹ️ Пользователь {user_id} не найден в списке скаммеров.\n"
                f"Возможно, он уже был удалён или никогда не был замучен."
            )
            return

        # Получаем информацию о записи
        risk_score = spammer_record.risk_score
        reason = spammer_record.reason
        incidents = spammer_record.incidents
        last_incident = spammer_record.last_incident_at

        # Удаляем из БД
        deleted = await delete_spammer_record(session, user_id)
        await session.commit()

        if not deleted:
            await message.answer(f"❌ Не удалось удалить запись о пользователе {user_id}")
            return

        await message.answer(
            f"✅ Запись удалена из БД\n\n"
            f"📊 Информация:\n"
            f"• User ID: {user_id}\n"
            f"• Risk Score: {risk_score}\n"
            f"• Причина: {reason}\n"
            f"• Инцидентов: {incidents}\n"
            f"• Последний инцидент: {last_incident}\n\n"
            f"🔓 Размучиваю пользователя во всех группах..."
        )

        # Размучиваем пользователя во всех группах где есть бот
        unmuted_groups = []
        failed_groups = []
        permissions = _build_unmute_permissions()

        # Получаем все группы где есть бот
        result = await session.execute(
            select(UserGroup.group_id).distinct()
        )
        all_group_ids = {row[0] for row in result.fetchall()}

        for group_id in all_group_ids:
            try:
                # Проверяем права бота
                bot_member = await bot.get_chat_member(group_id, bot.id)
                if getattr(bot_member, "status", None) not in ("administrator", "creator"):
                    continue
                if not getattr(bot_member, "can_restrict_members", False):
                    continue

                # Размучиваем
                await bot.restrict_chat_member(
                    chat_id=group_id,
                    user_id=user_id,
                    permissions=permissions,
                )
                unmuted_groups.append(group_id)
                logger.info(f"Размучен пользователь {user_id} в группе {group_id}")

            except Exception as e:
                failed_groups.append((group_id, str(e)))
                logger.warning(f"Не удалось размутить пользователя {user_id} в группе {group_id}: {e}")

        # Итоговый отчёт
        report = f"✅ Пользователь {user_id} снят со списка скаммеров\n\n"
        report += f"📊 Статистика размута:\n"
        report += f"• Размучен в группах: {len(unmuted_groups)}\n"
        report += f"• Не удалось размутить: {len(failed_groups)}\n"

        if unmuted_groups:
            report += f"\n✅ Размучен в группах:\n"
            for gid in unmuted_groups[:5]:  # Показываем первые 5
                report += f"  • {gid}\n"
            if len(unmuted_groups) > 5:
                report += f"  • ... и ещё {len(unmuted_groups) - 5}\n"

        if failed_groups:
            report += f"\n⚠️ Не удалось размутить:\n"
            for gid, reason in failed_groups[:3]:  # Показываем первые 3
                report += f"  • {gid}: {reason[:50]}\n"

        await message.answer(report)