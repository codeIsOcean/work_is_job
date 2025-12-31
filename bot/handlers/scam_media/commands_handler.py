# ============================================================
# КОМАНДЫ SCAM MEDIA FILTER
# ============================================================
# Команды для управления базой скам-изображений:
# - /mutein: Добавить фото в базу (действие: delete_mute)
# - /banin: Добавить фото в базу (действие: delete_ban)
# - /scamrm: Удалить фото из базы
#
# Использование:
#   /mutein   - реплаем на сообщение с фото
#   /banin    - реплаем на сообщение с фото
#   /scamrm   - реплаем на сообщение с фото или по ID хеша
#
# Команды доступны только администраторам группы.
# ============================================================

# Импорт для логирования
import logging
# Импорт для работы с асинхронностью
import asyncio
# Импорт для аннотации типов
from typing import Optional
# Импорт для работы с байтами изображения
from io import BytesIO
# Импорт для работы с датой/временем (расчёт времени мута/бана)
from datetime import datetime, timezone, timedelta

# Импорт aiogram
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт локальных сервисов
from bot.services.scam_media import (
    compute_image_hash,
    compute_logo_hash,
    BannedHashService,
    SettingsService,
    LOGO_REGIONS,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# СОЗДАНИЕ РОУТЕРА
# ============================================================
# Router группирует хендлеры для регистрации в dispatcher
router = Router()
# Устанавливаем имя для отладки
router.name = "scam_media_commands_router"


# ============================================================
# КОНСТАНТЫ
# ============================================================
# Время удаления уведомлений в секундах
NOTIFICATION_DELETE_DELAY = 10

# ID бота GroupAnonymousBot (анонимные админы)
GROUP_ANONYMOUS_BOT_ID = 1087968824


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором.

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
        # Ошибка API - считаем что не админ
        logger.warning(f"Ошибка проверки админа: {e}")
        return False


async def _extract_image_from_reply(
    message: Message,
    bot: Bot
) -> Optional[bytes]:
    """
    Извлекает изображение из реплая.

    Args:
        message: Сообщение-команда
        bot: Экземпляр бота

    Returns:
        Байты изображения или None
    """
    # Проверяем есть ли реплай
    reply = message.reply_to_message
    if reply is None:
        return None

    # Получаем file_id из разных типов медиа
    file_id: Optional[str] = None

    # Фото (берём наибольший размер)
    if reply.photo:
        file_id = reply.photo[-1].file_id

    # Документ-изображение
    elif reply.document:
        mime_type = reply.document.mime_type or ""
        if mime_type.startswith("image/"):
            file_id = reply.document.file_id

    # Стикер (thumbnail)
    elif reply.sticker and reply.sticker.thumbnail:
        file_id = reply.sticker.thumbnail.file_id

    # Видео (thumbnail)
    elif reply.video and reply.video.thumbnail:
        file_id = reply.video.thumbnail.file_id

    if file_id is None:
        return None

    # Скачиваем файл
    try:
        file = await bot.get_file(file_id)
        if file.file_path is None:
            return None
        buffer = BytesIO()
        await bot.download_file(file.file_path, buffer)
        return buffer.getvalue()
    except Exception as e:
        logger.warning(f"Не удалось скачать файл: {e}")
        return None


async def _delete_after_delay(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    """
    Удаляет сообщение после задержки.

    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        message_id: ID сообщения
        delay: Задержка в секундах
    """
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# ============================================================
# КОМАНДА /mutein - ДОБАВИТЬ ФОТО С ДЕЙСТВИЕМ МУТ
# ============================================================

@router.message(
    Command("mutein"),
    F.chat.type.in_({"group", "supergroup"})
)
async def cmd_mutein(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Добавляет фото из реплая в базу скам-изображений.
    При совпадении применяется delete_mute.

    Args:
        message: Сообщение с командой
        session: Сессия БД
    """
    await _process_add_command(
        message=message,
        session=session,
        command_name="mutein",
        description="Добавлено через /mutein (действие: мут)",
        apply_action="mute"  # Применить мут к автору реплая
    )


# ============================================================
# КОМАНДА /banin - ДОБАВИТЬ ФОТО С ДЕЙСТВИЕМ БАН
# ============================================================

@router.message(
    Command("banin"),
    F.chat.type.in_({"group", "supergroup"})
)
async def cmd_banin(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Добавляет фото из реплая в базу скам-изображений.
    При совпадении применяется delete_ban.

    Args:
        message: Сообщение с командой
        session: Сессия БД
    """
    await _process_add_command(
        message=message,
        session=session,
        command_name="banin",
        description="Добавлено через /banin (действие: бан)",
        apply_action="ban"  # Применить бан к автору реплая
    )


# ============================================================
# ОБЩАЯ ЛОГИКА ДОБАВЛЕНИЯ
# ============================================================

async def _process_add_command(
    message: Message,
    session: AsyncSession,
    command_name: str,
    description: str,
    apply_action: Optional[str] = None
) -> None:
    """
    Обрабатывает команду добавления фото в базу.

    После добавления хеша применяет действие к автору реплая:
    - Удаляет сообщение-реплай (скам-фото)
    - Применяет mute/ban к автору

    Args:
        message: Сообщение с командой
        session: Сессия БД
        command_name: Имя команды для логов
        description: Описание для записи в БД
        apply_action: Действие к автору: "mute" или "ban" (None = только добавить)
    """
    bot = message.bot
    chat_id = message.chat.id
    user = message.from_user

    # Проверяем наличие автора сообщения
    if not user:
        return

    # Проверяем анонимного админа
    is_anonymous_admin = (
        message.sender_chat is not None
        and message.sender_chat.id == chat_id
    )

    # Проверяем права администратора
    if not is_anonymous_admin:
        if not await _is_admin(bot, chat_id, user.id):
            # Не админ - молча игнорируем
            return

    # Проверяем наличие реплая
    if message.reply_to_message is None:
        sent = await message.reply(
            f"⚠️ Используйте /{command_name} в ответ на сообщение с фото."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Извлекаем изображение
    image_data = await _extract_image_from_reply(message, bot)
    if image_data is None:
        sent = await message.reply(
            f"⚠️ В сообщении нет изображения для добавления в базу."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Вычисляем хеш изображения
    image_hashes = compute_image_hash(image_data)
    if image_hashes is None:
        sent = await message.reply(
            "❌ Не удалось вычислить хеш изображения."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Проверяем есть ли уже такой хеш в базе (защита от дубликатов)
    existing_hash = await BannedHashService.find_by_phash(
        session=session,
        phash=image_hashes.phash,
        chat_id=chat_id
    )
    # Если хеш уже существует — сообщаем и выходим
    if existing_hash is not None:
        sent = await message.reply(
            f"⚠️ Такое фото уже в базе (ID: {existing_hash.id})"
        )
        # Удаляем уведомление и команду через задержку
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Добавляем хеш в базу (дубликата нет)
    try:
        hash_entry = await BannedHashService.add_hash(
            session=session,
            phash=image_hashes.phash,
            dhash=image_hashes.dhash,
            added_by_user_id=user.id,
            added_by_username=user.username,
            chat_id=chat_id,
            is_global=False,
            description=description,
        )

        # Убеждаемся что модуль включён
        await SettingsService.get_or_create_settings(session, chat_id)

        # В группе отправляем короткое подтверждение (безопасность)
        sent = await message.reply("✅ Готово")
        # Удаляем подтверждение и команду через задержку
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )

        # В ЛС админа отправляем подробную информацию
        try:
            await bot.send_message(
                chat_id=user.id,
                text=(
                    f"✅ Фото добавлено в базу скам-изображений.\n\n"
                    f"📝 ID: <code>{hash_entry.id}</code>\n"
                    f"🔢 pHash: <code>{image_hashes.phash}</code>\n"
                    f"🔢 dHash: <code>{image_hashes.dhash or 'N/A'}</code>\n\n"
                    f"📌 Команда: /{command_name}\n"
                    f"👥 Группа: {message.chat.title}"
                ),
                parse_mode="HTML"
            )
        except TelegramAPIError as e:
            # Если не удалось отправить в ЛС — логируем, не падаем
            logger.warning(f"Не удалось отправить подробности в ЛС админа {user.id}: {e}")

        # ─────────────────────────────────────────────────────────
        # ПРИМЕНЯЕМ ДЕЙСТВИЕ К АВТОРУ РЕПЛАЯ (если указано)
        # ─────────────────────────────────────────────────────────
        if apply_action is not None:
            # Получаем сообщение-реплай и его автора
            reply_msg = message.reply_to_message
            violator = reply_msg.from_user if reply_msg else None

            # Проверяем что есть автор (не анонимный канал и т.п.)
            if violator and not violator.is_bot:
                # Получаем настройки группы для времени мута/бана
                settings = await SettingsService.get_or_create_settings(session, chat_id)

                # Удаляем сообщение со скам-фото
                try:
                    await reply_msg.delete()
                    logger.info(f"[{command_name.upper()}] Удалено скам-фото: msg_id={reply_msg.message_id}")
                except TelegramAPIError as e:
                    logger.warning(f"Не удалось удалить скам-фото: {e}")

                # Применяем мут
                if apply_action == "mute":
                    try:
                        # Время мута из настроек группы
                        mute_seconds = settings.mute_duration
                        # Вычисляем дату окончания мута
                        if mute_seconds == 0:
                            # Перманентный мут — далёкая дата
                            until_date = datetime.now(timezone.utc) + timedelta(days=366)
                        else:
                            until_date = datetime.now(timezone.utc) + timedelta(seconds=mute_seconds)
                        # Ограничиваем права пользователя
                        await bot.restrict_chat_member(
                            chat_id=chat_id,
                            user_id=violator.id,
                            permissions=ChatPermissions(
                                can_send_messages=False,
                                can_send_media_messages=False,
                                can_send_other_messages=False,
                                can_add_web_page_previews=False,
                            ),
                            until_date=until_date
                        )
                        logger.info(
                            f"[{command_name.upper()}] Замучен: user_id={violator.id}, "
                            f"duration={mute_seconds}s"
                        )
                    except TelegramAPIError as e:
                        logger.warning(f"Не удалось замутить пользователя {violator.id}: {e}")

                # Применяем бан
                elif apply_action == "ban":
                    try:
                        # Время бана из настроек группы
                        ban_seconds = settings.ban_duration
                        # Вычисляем дату окончания бана
                        if ban_seconds == 0:
                            # Перманентный бан
                            until_date = None
                        else:
                            until_date = datetime.now(timezone.utc) + timedelta(seconds=ban_seconds)
                        # Баним пользователя
                        await bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=violator.id,
                            until_date=until_date
                        )
                        logger.info(
                            f"[{command_name.upper()}] Забанен: user_id={violator.id}, "
                            f"duration={ban_seconds}s (0=навсегда)"
                        )
                    except TelegramAPIError as e:
                        logger.warning(f"Не удалось забанить пользователя {violator.id}: {e}")

        logger.info(
            f"[{command_name.upper()}] Добавлен хеш: id={hash_entry.id}, "
            f"chat={chat_id}, admin={user.id}"
        )

    except Exception as e:
        logger.exception(f"Ошибка добавления хеша: {e}")
        sent = await message.reply(
            "❌ Ошибка при добавлении в базу."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )


# ============================================================
# КОМАНДА /scamrm - УДАЛИТЬ ФОТО ИЗ БАЗЫ
# ============================================================

@router.message(
    Command("scamrm"),
    F.chat.type.in_({"group", "supergroup"})
)
async def cmd_scamrm(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Удаляет фото из базы скам-изображений.

    Варианты использования:
    - /scamrm (реплаем на фото) - удалить по хешу
    - /scamrm 123 - удалить по ID хеша

    Args:
        message: Сообщение с командой
        session: Сессия БД
    """
    bot = message.bot
    chat_id = message.chat.id
    user = message.from_user

    # Проверяем наличие автора сообщения
    if not user:
        return

    # Проверяем анонимного админа
    is_anonymous_admin = (
        message.sender_chat is not None
        and message.sender_chat.id == chat_id
    )

    # Проверяем права администратора
    if not is_anonymous_admin:
        if not await _is_admin(bot, chat_id, user.id):
            return

    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []

    # Вариант 1: Удаление по ID
    if args:
        try:
            hash_id = int(args[0])
            # Удаляем по ID
            deleted = await BannedHashService.delete_hash(session, hash_id)
            if deleted:
                sent = await message.reply(
                    f"✅ Хеш ID={hash_id} удалён из базы."
                )
            else:
                sent = await message.reply(
                    f"⚠️ Хеш ID={hash_id} не найден."
                )
            asyncio.create_task(
                _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
            )
            asyncio.create_task(
                _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
            )
            return
        except ValueError:
            pass

    # Вариант 2: Удаление по реплаю
    if message.reply_to_message is None:
        sent = await message.reply(
            "⚠️ Используйте /scamrm в ответ на сообщение с фото\n"
            "или укажите ID хеша: /scamrm 123"
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Извлекаем изображение из реплая
    image_data = await _extract_image_from_reply(message, bot)
    if image_data is None:
        sent = await message.reply(
            "⚠️ В сообщении нет изображения."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Вычисляем хеш
    image_hashes = compute_image_hash(image_data)
    if image_hashes is None:
        sent = await message.reply(
            "❌ Не удалось вычислить хеш изображения."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Удаляем по pHash
    deleted_count = await BannedHashService.delete_hash_by_phash(
        session=session,
        phash=image_hashes.phash,
        chat_id=chat_id
    )

    if deleted_count > 0:
        sent = await message.reply(
            f"✅ Удалено {deleted_count} хеш(ей) из базы.\n"
            f"🔢 pHash: <code>{image_hashes.phash}</code>",
            parse_mode="HTML"
        )
    else:
        sent = await message.reply(
            f"⚠️ Хеш не найден в базе.\n"
            f"🔢 pHash: <code>{image_hashes.phash}</code>",
            parse_mode="HTML"
        )

    asyncio.create_task(
        _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
    )
    asyncio.create_task(
        _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
    )

    logger.info(
        f"[SCAMRM] Удалено {deleted_count} хешей: "
        f"phash={image_hashes.phash}, chat={chat_id}, admin={user.id}"
    )


# ============================================================
# КОМАНДА /scamlogo - ДОБАВИТЬ ЛОГО-ОБЛАСТЬ
# ============================================================

@router.message(
    Command("scamlogo"),
    F.chat.type.in_({"group", "supergroup"})
)
async def cmd_scamlogo(
    message: Message,
    session: AsyncSession
) -> None:
    """
    Добавляет хеш области логотипа из реплая.

    Использование:
    - /scamlogo top_left    - верхний левый угол
    - /scamlogo top_right   - верхний правый угол
    - /scamlogo bottom_left - нижний левый угол
    - и т.д.

    Args:
        message: Сообщение с командой
        session: Сессия БД
    """
    bot = message.bot
    chat_id = message.chat.id
    user = message.from_user

    # Проверяем наличие автора сообщения
    if not user:
        return

    # Проверяем анонимного админа
    is_anonymous_admin = (
        message.sender_chat is not None
        and message.sender_chat.id == chat_id
    )

    # Проверяем права администратора
    if not is_anonymous_admin:
        if not await _is_admin(bot, chat_id, user.id):
            return

    # Парсим аргументы
    args = message.text.split()[1:] if message.text else []

    # Проверяем указан ли регион
    if not args:
        # Показываем список доступных регионов
        regions_list = "\n".join([f"  • <code>{r}</code>" for r in LOGO_REGIONS.keys()])
        sent = await message.reply(
            f"⚠️ Укажите область логотипа:\n\n"
            f"/scamlogo &lt;region&gt;\n\n"
            f"Доступные регионы:\n{regions_list}",
            parse_mode="HTML"
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Проверяем валидность региона
    region = args[0].lower()
    if region not in LOGO_REGIONS:
        regions_list = ", ".join(LOGO_REGIONS.keys())
        sent = await message.reply(
            f"❌ Неизвестный регион: {region}\n"
            f"Доступные: {regions_list}"
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Проверяем наличие реплая
    if message.reply_to_message is None:
        sent = await message.reply(
            f"⚠️ Используйте /scamlogo {region} в ответ на сообщение с фото."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Извлекаем изображение
    image_data = await _extract_image_from_reply(message, bot)
    if image_data is None:
        sent = await message.reply(
            "⚠️ В сообщении нет изображения."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Вычисляем хеш области
    logo_hashes = compute_logo_hash(image_data, region)
    if logo_hashes is None:
        sent = await message.reply(
            "❌ Не удалось вычислить хеш области."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )
        return

    # Добавляем хеш в базу
    try:
        hash_entry = await BannedHashService.add_hash(
            session=session,
            phash=logo_hashes.phash,
            dhash=logo_hashes.dhash,
            added_by_user_id=user.id,
            added_by_username=user.username,
            chat_id=chat_id,
            is_global=False,
            description=f"Логотип ({region}) через /scamlogo",
            logo_region=region,
        )

        # Убеждаемся что модуль включён
        await SettingsService.get_or_create_settings(session, chat_id)

        sent = await message.reply(
            f"✅ Хеш области <b>{region}</b> добавлен.\n"
            f"📝 ID: <code>{hash_entry.id}</code>\n"
            f"🔢 pHash: <code>{logo_hashes.phash}</code>",
            parse_mode="HTML"
        )

        asyncio.create_task(
            _delete_after_delay(bot, chat_id, message.message_id, NOTIFICATION_DELETE_DELAY)
        )

        logger.info(
            f"[SCAMLOGO] Добавлен хеш области: id={hash_entry.id}, "
            f"region={region}, chat={chat_id}, admin={user.id}"
        )

    except Exception as e:
        logger.exception(f"Ошибка добавления хеша области: {e}")
        sent = await message.reply(
            "❌ Ошибка при добавлении в базу."
        )
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id, NOTIFICATION_DELETE_DELAY)
        )
