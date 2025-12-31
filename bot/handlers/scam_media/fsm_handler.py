# ============================================================
# FSM ОБРАБОТЧИКИ SCAM MEDIA FILTER
# ============================================================
# Обработчики FSM состояний для:
# - Загрузка фото через UI
# - Удаление фото по ID
# - Ввод кастомных значений
#
# Вынесено из callbacks_handler.py для соблюдения правила
# ограничения файлов в 500 строк.
# ============================================================

# Импорт для логирования
import logging
# Импорт для работы с байтами
from io import BytesIO

# Импорт aiogram
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт локальных сервисов
from bot.services.scam_media import (
    SettingsService,
    BannedHashService,
    compute_image_hash,
)

# Импорт клавиатур
from .keyboards import (
    build_settings_keyboard,
    build_photo_list_keyboard,
    build_photo_preview_keyboard,
    build_fsm_cancel_keyboard,
    PHOTOS_PER_PAGE,
    PREFIX,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
logger = logging.getLogger(__name__)


# ============================================================
# СОЗДАНИЕ РОУТЕРА
# ============================================================
router = Router()
router.name = "scam_media_fsm_router"


# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================
class ScamMediaPhotoFSM(StatesGroup):
    """
    Состояния FSM для работы с фото.
    """
    # Ожидание загрузки фото
    waiting_photo = State()
    # Ожидание ввода ID для удаления
    waiting_delete_id = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def _check_admin(callback: CallbackQuery, chat_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором.
    """
    try:
        member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
        return member.status in ('creator', 'administrator')
    except Exception as e:
        logger.warning(f"Ошибка проверки админа: {e}")
        return False


def _build_settings_text(settings) -> str:
    """
    Строит текст сообщения с настройками.
    """
    status = "Включено" if settings.enabled else "Выключено"
    return (
        f"<b>🔍 Фильтр скам-изображений</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Действие: <b>{settings.action}</b>\n"
        f"Порог: <b>{settings.threshold}</b>\n\n"
        f"Выберите настройку для изменения:"
    )


# ============================================================
# ADD_PHOTO - ДОБАВЛЕНИЕ ФОТО ЧЕРЕЗ UI
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:add_photo:"))
async def cb_add_photo(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для добавления фото через UI.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Сохраняем chat_id в state
    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaPhotoFSM.waiting_photo)

    await callback.message.edit_text(
        text=(
            "<b>➕ Добавление фото в базу</b>\n\n"
            "Отправьте фото для добавления в базу скам-изображений.\n\n"
            "Для отмены отправьте /cancel"
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaPhotoFSM.waiting_photo, F.photo)
async def fsm_photo_upload(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает загруженное фото.
    Поддерживает media groups (несколько фото за раз).
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")
    # Счётчики для media group
    added_count = data.get("added_count", 0)
    duplicate_count = data.get("duplicate_count", 0)
    error_count = data.get("error_count", 0)
    current_media_group = data.get("media_group_id")

    if not chat_id:
        await state.clear()
        await message.reply("❌ Ошибка: потеряны данные сессии.")
        return

    # Проверяем media_group_id
    is_media_group = message.media_group_id is not None

    # Если новый media_group или первое фото — сбрасываем счётчики
    if is_media_group and message.media_group_id != current_media_group:
        added_count = 0
        duplicate_count = 0
        error_count = 0
        current_media_group = message.media_group_id

    # Скачиваем фото
    try:
        # Берём фото максимального размера
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        if file.file_path is None:
            error_count += 1
            await state.update_data(
                added_count=added_count,
                duplicate_count=duplicate_count,
                error_count=error_count,
                media_group_id=current_media_group
            )
            if not is_media_group:
                await message.reply("❌ Не удалось получить файл.")
            return

        # Скачиваем в байты
        buffer = BytesIO()
        await message.bot.download_file(file.file_path, buffer)
        image_data = buffer.getvalue()
    except Exception as e:
        logger.error(f"Ошибка скачивания фото: {e}")
        error_count += 1
        await state.update_data(
            added_count=added_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            media_group_id=current_media_group
        )
        if not is_media_group:
            await message.reply("❌ Ошибка при скачивании фото.")
        return

    # Вычисляем хеш
    image_hashes = compute_image_hash(image_data)
    if image_hashes is None:
        error_count += 1
        await state.update_data(
            added_count=added_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            media_group_id=current_media_group
        )
        if not is_media_group:
            await message.reply("❌ Не удалось вычислить хеш изображения.")
        return

    # Проверяем дубликат
    existing = await BannedHashService.find_by_phash(
        session=session,
        phash=image_hashes.phash,
        chat_id=chat_id
    )
    if existing:
        duplicate_count += 1
        await state.update_data(
            added_count=added_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            media_group_id=current_media_group
        )
        if not is_media_group:
            await state.clear()
            settings = await SettingsService.get_settings(session, chat_id)
            await message.answer(
                text=f"⚠️ Такое фото уже есть в базе (ID: {existing.id})",
                reply_markup=build_settings_keyboard(chat_id, settings),
                parse_mode="HTML"
            )
        return

    # Добавляем хеш
    await BannedHashService.add_hash(
        session=session,
        phash=image_hashes.phash,
        dhash=image_hashes.dhash,
        added_by_user_id=message.from_user.id,
        added_by_username=message.from_user.username,
        chat_id=chat_id,
        is_global=False,
        description="Добавлено через UI"
    )
    added_count += 1

    # Обновляем state
    await state.update_data(
        added_count=added_count,
        duplicate_count=duplicate_count,
        error_count=error_count,
        media_group_id=current_media_group
    )

    # Для одиночного фото — показываем результат сразу
    if not is_media_group:
        await state.clear()
        settings = await SettingsService.get_settings(session, chat_id)
        await message.answer(
            text=f"✅ Фото добавлено в базу!",
            reply_markup=build_settings_keyboard(chat_id, settings),
            parse_mode="HTML"
        )
    # Для media group — показываем промежуточный итог
    else:
        total = added_count + duplicate_count + error_count
        await message.answer(
            text=(
                f"📥 Обработано: {total} фото\n"
                f"✅ Добавлено: {added_count}\n"
                f"⚠️ Дубликатов: {duplicate_count}\n"
                f"❌ Ошибок: {error_count}\n\n"
                f"<i>Можете отправить ещё фото или /cancel для завершения.</i>"
            ),
            parse_mode="HTML"
        )


@router.message(ScamMediaPhotoFSM.waiting_photo, F.text == "/cancel")
async def fsm_photo_cancel(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Отменяет добавление фото. Показывает итог если были добавлены фото.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")
    added_count = data.get("added_count", 0)
    duplicate_count = data.get("duplicate_count", 0)
    error_count = data.get("error_count", 0)
    await state.clear()

    if chat_id:
        settings = await SettingsService.get_settings(session, chat_id)
        # Если были добавлены фото — показываем итог
        if added_count > 0 or duplicate_count > 0:
            await message.answer(
                text=(
                    f"<b>📊 Итог загрузки:</b>\n\n"
                    f"✅ Добавлено: {added_count}\n"
                    f"⚠️ Дубликатов: {duplicate_count}\n"
                    f"❌ Ошибок: {error_count}"
                ),
                reply_markup=build_settings_keyboard(chat_id, settings),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                text=_build_settings_text(settings),
                reply_markup=build_settings_keyboard(chat_id, settings),
                parse_mode="HTML"
            )
    else:
        await message.answer("Отменено.")


@router.message(ScamMediaPhotoFSM.waiting_photo)
async def fsm_photo_invalid(
    message: Message,
    state: FSMContext
) -> None:
    """
    Обрабатывает неверный ввод (не фото).
    """
    await message.reply(
        "⚠️ Пожалуйста, отправьте фото.\n"
        "Для отмены отправьте /cancel"
    )


# ============================================================
# LIST_PHOTOS - СПИСОК ФОТО С ПАГИНАЦИЕЙ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:list_photos:"))
async def cb_list_photos(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает список фото с пагинацией.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Получаем общее количество хешей
    total_count = await BannedHashService.count_hashes(session, chat_id=chat_id)

    # Получаем хеши для текущей страницы
    hashes = await BannedHashService.get_hashes_paginated(
        session=session,
        chat_id=chat_id,
        limit=PHOTOS_PER_PAGE,
        offset=page * PHOTOS_PER_PAGE
    )

    if total_count == 0:
        await callback.message.edit_text(
            text="<b>📋 Список фото</b>\n\nБаза пуста. Добавьте фото через кнопку ➕",
            reply_markup=build_photo_list_keyboard(chat_id, [], 0, 0),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            text=(
                f"<b>📋 Список фото</b>\n\n"
                f"Всего: {total_count} фото\n\n"
                f"Нажмите на фото для удаления:"
            ),
            reply_markup=build_photo_list_keyboard(chat_id, hashes, page, total_count),
            parse_mode="HTML"
        )

    await callback.answer()


# ============================================================
# PHOTO_PREVIEW - ПРЕДПРОСМОТР ФОТО ПЕРЕД УДАЛЕНИЕМ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:photo_preview:"))
async def cb_photo_preview(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает информацию о фото перед удалением.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    hash_id = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Получаем информацию о хеше
    hash_entry = await BannedHashService.get_hash_by_id(session, hash_id)

    if not hash_entry:
        await callback.answer("⚠️ Фото не найдено", show_alert=True)
        return

    # Форматируем дату добавления
    added_str = hash_entry.added_at.strftime("%d.%m.%Y %H:%M") if hash_entry.added_at else "N/A"

    # Формируем текст с информацией
    text = (
        f"<b>🖼️ Информация о фото</b>\n\n"
        f"📝 ID: <code>{hash_entry.id}</code>\n"
        f"🔢 pHash: <code>{hash_entry.phash}</code>\n"
        f"🔢 dHash: <code>{hash_entry.dhash or 'N/A'}</code>\n"
        f"📊 Совпадений: <b>{hash_entry.matches_count}</b>\n"
        f"📅 Добавлено: {added_str}\n"
        f"👤 Кем: @{hash_entry.added_by_username or 'N/A'}\n"
        f"📝 Описание: {hash_entry.description or 'N/A'}\n\n"
        f"<i>⚠️ Предпросмотр изображения невозможен,\n"
        f"т.к. хранится только хеш, а не само фото.</i>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=build_photo_preview_keyboard(chat_id, hash_id),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# DELETE_PHOTO - УДАЛЕНИЕ ФОТО ПО ID (ВВОД)
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:delete_photo:"))
async def cb_delete_photo(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ввода ID фото для удаления.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaPhotoFSM.waiting_delete_id)

    await callback.message.edit_text(
        text=(
            "<b>🗑️ Удаление фото по ID</b>\n\n"
            "Введите ID фото для удаления.\n"
            "Например: <code>30</code>"
        ),
        reply_markup=build_fsm_cancel_keyboard(chat_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaPhotoFSM.waiting_delete_id)
async def fsm_delete_id_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод ID для удаления.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    # Парсим ID
    try:
        hash_id = int(message.text.strip())
    except ValueError:
        await message.reply("❌ Введите корректный ID (число).")
        return

    # Удаляем хеш
    deleted = await BannedHashService.delete_hash(session, hash_id)

    await state.clear()

    # Возвращаем в список фото
    total_count = await BannedHashService.count_hashes(session, chat_id=chat_id)
    hashes = await BannedHashService.get_hashes_paginated(
        session=session,
        chat_id=chat_id,
        limit=PHOTOS_PER_PAGE,
        offset=0
    )

    if deleted:
        result_text = f"✅ Фото с ID {hash_id} удалено.\n\n"
    else:
        result_text = f"⚠️ Фото с ID {hash_id} не найдено.\n\n"

    if total_count == 0:
        text = result_text + "<b>📋 Список фото</b>\n\nБаза пуста."
    else:
        text = result_text + f"<b>📋 Список фото</b>\n\nВсего: {total_count} фото"

    await message.answer(
        text=text,
        reply_markup=build_photo_list_keyboard(chat_id, hashes, 0, total_count),
        parse_mode="HTML"
    )


# ============================================================
# DELETE_CONFIRM - УДАЛЕНИЕ ФОТО ИЗ СПИСКА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:delete_confirm:"))
async def cb_delete_confirm(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Удаляет фото по нажатию из списка.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    hash_id = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Удаляем хеш
    deleted = await BannedHashService.delete_hash(session, hash_id)

    if deleted:
        await callback.answer(f"✅ Фото ID:{hash_id} удалено", show_alert=True)
    else:
        await callback.answer(f"⚠️ Фото не найдено", show_alert=True)

    # Обновляем список
    total_count = await BannedHashService.count_hashes(session, chat_id=chat_id)
    hashes = await BannedHashService.get_hashes_paginated(
        session=session,
        chat_id=chat_id,
        limit=PHOTOS_PER_PAGE,
        offset=0
    )

    if total_count == 0:
        text = "<b>📋 Список фото</b>\n\nБаза пуста."
    else:
        text = f"<b>📋 Список фото</b>\n\nВсего: {total_count} фото"

    await callback.message.edit_text(
        text=text,
        reply_markup=build_photo_list_keyboard(chat_id, hashes, 0, total_count),
        parse_mode="HTML"
    )
