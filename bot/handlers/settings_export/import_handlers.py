# ============================================================
# ХЕНДЛЕРЫ ИМПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль обрабатывает:
# - Команду /import_settings
# - Callback кнопки импорта из UI настроек
# - FSM для процесса импорта (загрузка файла)
#
# Импорт доступен только владельцу или админу со всеми правами
# Процесс: выбор группы → загрузка файла → подтверждение → импорт
# ============================================================

# Импортируем стандартные библиотеки
import logging
from typing import Optional

# Импортируем aiogram классы и функции
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы экспорта и проверки прав
from bot.services.settings_export.export_service import (
    import_group_settings,
    deserialize_settings_from_json,
    validate_import_data,
)
from bot.services.settings_export.permissions import can_export_import_settings

# Импортируем сервис получения групп пользователя
from bot.services.groups_settings_in_private_logic import get_admin_groups

# Импортируем клавиатуры
from bot.keyboards.settings_export_kb import (
    create_import_groups_keyboard,
    create_import_confirm_keyboard,
    create_cancel_keyboard,
)

# Создаём логгер для отслеживания импорта
logger = logging.getLogger(__name__)

# Создаём роутер для хендлеров импорта
import_router = Router(name="import_handlers")


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ ИМПОРТА
# ============================================================
# Минимальный и чистый FSM - только необходимые состояния

class ImportSettingsStates(StatesGroup):
    """
    Состояния FSM для процесса импорта настроек.

    Процесс:
    1. waiting_for_file - ожидание загрузки JSON файла
    """
    # Ожидание файла от пользователя
    waiting_for_file = State()


# ============================================================
# КОМАНДА /import_settings
# ============================================================

@import_router.message(Command("import_settings"))
async def cmd_import_settings(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает команду /import_settings.

    Показывает список групп где пользователь может импортировать настройки.
    Команда работает ТОЛЬКО в ЛС бота. В группах - удаляется.

    Args:
        message: Входящее сообщение с командой
        session: Сессия БД (инжектится middleware)
        state: Контекст FSM
    """
    # Очищаем предыдущее состояние (чистота FSM)
    await state.clear()

    # Получаем данные пользователя
    user_id = message.from_user.id

    # Логируем получение команды
    logger.info(f"📥 [IMPORT] Команда /import_settings от user_id={user_id}")

    # Если команда в группе - удаляем её и выходим
    if message.chat.type != "private":
        try:
            await message.delete()
        except Exception:
            pass  # Не удалось удалить - игнорируем
        return

    try:
        # Получаем группы где пользователь админ
        user_groups = await get_admin_groups(user_id, session, bot=message.bot)

        # Если нет групп
        if not user_groups:
            await message.answer(
                "❌ <b>Нет доступных групп</b>\n\n"
                "Вы не являетесь администратором ни в одной группе.",
                parse_mode="HTML"
            )
            return

        # Фильтруем группы где можно импортировать
        importable_groups = []
        for group in user_groups:
            can_import, reason = await can_export_import_settings(
                bot=message.bot,
                chat_id=group.chat_id,
                user_id=user_id,
            )
            if can_import:
                importable_groups.append(group)

        # Если нет групп с правами
        if not importable_groups:
            await message.answer(
                "⚠️ <b>Недостаточно прав</b>\n\n"
                "Для импорта настроек нужно быть:\n"
                "• Владельцем группы, или\n"
                "• Администратором со <b>всеми</b> правами\n\n"
                "У вас нет таких групп.",
                parse_mode="HTML"
            )
            return

        # Создаём клавиатуру со списком групп
        keyboard = create_import_groups_keyboard(importable_groups)

        # Отправляем сообщение с выбором группы
        await message.answer(
            "📥 <b>Импорт настроек</b>\n\n"
            "Выберите группу для импорта настроек:\n\n"
            "⚠️ <b>Внимание:</b> существующие настройки будут заменены!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка в cmd_import_settings: {e}")
        await message.answer(
            "❌ Произошла ошибка при получении списка групп.\n"
            "Попробуйте позже."
        )


# ============================================================
# CALLBACK: ВЫБОР ГРУППЫ ДЛЯ ИМПОРТА
# ============================================================

@import_router.callback_query(F.data.regexp(r"^import_select:-?\d+$"))
async def callback_import_select_group(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает выбор группы для импорта.

    При выборе группы переходит в состояние ожидания файла.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Логируем выбор группы
    logger.info(f"📥 [IMPORT] Выбрана группа chat_id={chat_id} user_id={user_id}")

    try:
        # Проверяем права
        can_import, reason = await can_export_import_settings(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        if not can_import:
            await callback.answer(f"❌ {reason}", show_alert=True)
            return

        # Получаем информацию о группе
        chat = await callback.bot.get_chat(chat_id)
        chat_title = chat.title or f"Группа {chat_id}"

        # Сохраняем chat_id в состояние FSM
        await state.update_data(import_chat_id=chat_id, chat_title=chat_title)

        # Переходим в состояние ожидания файла
        await state.set_state(ImportSettingsStates.waiting_for_file)

        # Создаём клавиатуру с кнопкой возврата к настройкам
        keyboard = create_cancel_keyboard(chat_id)

        # Редактируем сообщение
        await callback.message.edit_text(
            f"📥 <b>Импорт настроек</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n"
            f"ID: <code>{chat_id}</code>\n\n"
            f"Отправьте JSON файл с настройками.\n"
            f"<i>Файл должен быть получен через /export_settings</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка выбора группы: {e}")
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


# ============================================================
# ХЕНДЛЕР: ПОЛУЧЕНИЕ ФАЙЛА
# ============================================================

@import_router.message(
    ImportSettingsStates.waiting_for_file,
    F.document,
)
async def handle_import_file(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает загруженный JSON файл с настройками.

    Проверяет файл и показывает подтверждение импорта.

    Args:
        message: Сообщение с документом
        session: Сессия БД
        state: Контекст FSM
    """
    # Получаем документ
    document = message.document

    # Проверяем что это JSON файл
    if not document.file_name.endswith('.json'):
        await message.answer(
            "❌ <b>Неверный формат файла</b>\n\n"
            "Пожалуйста, отправьте JSON файл (.json).",
            parse_mode="HTML"
        )
        return

    # Проверяем размер файла (максимум 1 МБ)
    if document.file_size > 1024 * 1024:
        await message.answer(
            "❌ <b>Файл слишком большой</b>\n\n"
            "Максимальный размер: 1 МБ.",
            parse_mode="HTML"
        )
        return

    try:
        # Скачиваем файл
        file = await message.bot.get_file(document.file_id)
        file_content = await message.bot.download_file(file.file_path)

        # Читаем содержимое как строку
        json_content = file_content.read().decode('utf-8')

        # Парсим JSON
        import_data = deserialize_settings_from_json(json_content)

        # Валидируем данные
        errors = validate_import_data(import_data)
        if errors:
            error_text = "\n".join(f"• {e}" for e in errors)
            await message.answer(
                f"❌ <b>Ошибка валидации файла</b>\n\n{error_text}",
                parse_mode="HTML"
            )
            return

        # Получаем данные из состояния
        state_data = await state.get_data()
        chat_id = state_data.get('import_chat_id')
        chat_title = state_data.get('chat_title', 'Группа')

        # Сохраняем данные для импорта в состояние
        await state.update_data(import_data=import_data)

        # Формируем статистику
        data_stats = import_data.get('data', {})
        stats_lines = []
        for key, value in data_stats.items():
            if value:
                if isinstance(value, list):
                    count = len(value)
                    if count > 0:
                        stats_lines.append(f"  • {key}: {count} записей")
                else:
                    stats_lines.append(f"  • {key}: ✓")

        stats_text = "\n".join(stats_lines) if stats_lines else "  (нет данных)"

        # Информация об источнике
        source_chat_id = import_data.get('source_chat_id', 'неизвестно')
        exported_at = import_data.get('exported_at', 'неизвестно')

        # Создаём клавиатуру подтверждения
        keyboard = create_import_confirm_keyboard(chat_id)

        # Отправляем подтверждение
        await message.answer(
            f"📥 <b>Подтверждение импорта</b>\n\n"
            f"<b>Целевая группа:</b> {chat_title}\n"
            f"<b>Источник:</b> {source_chat_id}\n"
            f"<b>Экспортировано:</b> {exported_at}\n\n"
            f"<b>Данные для импорта:</b>\n{stats_text}\n\n"
            f"⚠️ <b>Внимание:</b> существующие настройки будут заменены!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except ValueError as e:
        logger.warning(f"⚠️ [IMPORT] Ошибка парсинга JSON: {e}")
        await message.answer(
            f"❌ <b>Ошибка чтения файла</b>\n\n{str(e)}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка обработки файла: {e}")
        await message.answer(
            "❌ <b>Ошибка обработки файла</b>\n\n"
            "Попробуйте загрузить файл снова.",
            parse_mode="HTML"
        )


# ============================================================
# CALLBACK: ПОДТВЕРЖДЕНИЕ ИМПОРТА
# ============================================================

@import_router.callback_query(F.data.regexp(r"^import_confirm:-?\d+$"))
async def callback_import_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Выполняет импорт настроек после подтверждения.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    # Извлекаем chat_id
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    logger.info(f"📥 [IMPORT] Подтверждение импорта chat_id={chat_id} user_id={user_id}")

    try:
        # Проверяем права
        can_import, reason = await can_export_import_settings(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        if not can_import:
            await callback.answer(f"❌ {reason}", show_alert=True)
            await state.clear()
            return

        # Получаем данные из состояния
        state_data = await state.get_data()
        import_data = state_data.get('import_data')
        chat_title = state_data.get('chat_title', 'Группа')

        if not import_data:
            await callback.answer("❌ Данные для импорта не найдены", show_alert=True)
            await state.clear()
            return

        # Показываем индикатор загрузки
        await callback.message.edit_text(
            "⏳ <b>Импорт настроек...</b>\n\n"
            "Пожалуйста, подождите. Применяем настройки...",
            parse_mode="HTML"
        )

        # Выполняем импорт
        stats = await import_group_settings(
            session=session,
            chat_id=chat_id,
            data=import_data,
            user_id=user_id,
            merge=False,
        )

        # Формируем статистику
        stats_lines = []
        for key, count in stats.items():
            if count > 0:
                stats_lines.append(f"  • {key}: {count} записей")

        stats_text = "\n".join(stats_lines) if stats_lines else "  (нет данных)"

        # Очищаем FSM
        await state.clear()

        # Редактируем сообщение с результатом
        await callback.message.edit_text(
            f"✅ <b>Импорт завершён</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n\n"
            f"<b>Импортировано:</b>\n{stats_text}",
            parse_mode="HTML"
        )

        # Логируем успех
        logger.info(f"✅ [IMPORT] Импорт успешен chat_id={chat_id} stats={stats}")

        await callback.answer("✅ Импорт завершён!")

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка импорта: {e}")
        await state.clear()
        await callback.message.edit_text(
            f"❌ <b>Ошибка импорта</b>\n\n{str(e)}",
            parse_mode="HTML"
        )
        await callback.answer("❌ Ошибка импорта", show_alert=True)


# ============================================================
# CALLBACK: ОТМЕНА ИМПОРТА
# ============================================================

@import_router.callback_query(F.data == "import_cancel")
async def callback_import_cancel(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Отменяет процесс импорта и очищает FSM.

    Args:
        callback: Callback запрос
        state: Контекст FSM
    """
    # Очищаем состояние FSM
    await state.clear()

    # Редактируем сообщение
    await callback.message.edit_text(
        "❌ <b>Импорт отменён</b>\n\n"
        "Используйте /import_settings чтобы начать заново.",
        parse_mode="HTML"
    )

    await callback.answer("Отменено")


# ============================================================
# CALLBACK: ВОЗВРАТ К НАСТРОЙКАМ (ОЧИСТКА FSM)
# ============================================================

@import_router.callback_query(F.data.regexp(r"^import_back:-?\d+$"))
async def callback_back_to_settings_from_import(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Очищает FSM и возвращает к меню настроек группы.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    # Очищаем состояние FSM
    await state.clear()

    # Извлекаем chat_id
    chat_id = int(callback.data.split(":")[1])

    try:
        # Импортируем функции для отображения меню настроек
        from bot.handlers.group_settings_handler.groups_settings_in_private_handler import (
            send_group_management_menu,
        )
        from bot.services.groups_settings_in_private_logic import get_group_by_chat_id

        # Получаем информацию о группе
        group = await get_group_by_chat_id(session, chat_id)

        if group:
            # Возвращаемся к меню настроек
            await send_group_management_menu(
                callback.message,
                session,
                group,
                user_id=callback.from_user.id,
                bot=callback.bot,
            )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка возврата к настройкам: {e}")
        await callback.answer("❌ Ошибка. Используйте /settings", show_alert=True)


# ============================================================
# ХЕНДЛЕР: НЕВЕРНЫЙ ВВОД В СОСТОЯНИИ ОЖИДАНИЯ ФАЙЛА
# ============================================================

@import_router.message(
    ImportSettingsStates.waiting_for_file,
    ~F.document,
)
async def handle_invalid_input_waiting_file(
    message: Message,
    state: FSMContext,
) -> None:
    """
    Обрабатывает некорректный ввод когда ожидается файл.

    Args:
        message: Входящее сообщение (не документ)
        state: Контекст FSM
    """
    # Проверяем не команда ли это
    if message.text and message.text.startswith('/'):
        # Если это команда - очищаем состояние и пропускаем
        await state.clear()
        return

    # Получаем chat_id из состояния для кнопки "назад"
    state_data = await state.get_data()
    chat_id = state_data.get('import_chat_id')

    # Напоминаем что нужен файл
    keyboard = create_cancel_keyboard(chat_id)

    await message.answer(
        "⚠️ <b>Ожидается файл</b>\n\n"
        "Пожалуйста, отправьте JSON файл с настройками.\n"
        "<i>Файл должен быть получен через /export_settings</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
