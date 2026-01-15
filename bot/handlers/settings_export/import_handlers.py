# ============================================================
# ХЕНДЛЕРЫ ИМПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль обрабатывает:
# - Команду /import_settings
# - Массовый импорт во все выбранные группы
# - FSM для процесса импорта (загрузка файла → выбор групп)
#
# Импорт доступен только владельцу или админу со всеми правами
# Процесс: загрузка файла → выбор групп (галочки) → импорт
# ============================================================

# Импортируем стандартные библиотеки
import html
import logging
from typing import Set, List, Any

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
    create_multi_group_select_keyboard,
    create_cancel_keyboard,
    create_import_confirm_keyboard,
    create_import_type_select_keyboard,
    create_import_result_keyboard,
)

# Создаём логгер для отслеживания импорта
logger = logging.getLogger(__name__)

# Создаём роутер для хендлеров импорта
import_router = Router(name="import_handlers")


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ ИМПОРТА
# ============================================================

class ImportSettingsStates(StatesGroup):
    """
    Состояния FSM для процесса импорта настроек.

    Два флоу:
    A) Массовый импорт (через /import_settings):
       1. waiting_for_file - ожидание загрузки JSON файла
       2. selecting_groups - выбор групп для импорта (галочки)

    B) Импорт в одну группу (через меню настроек):
       1. waiting_for_file_single - ожидание файла для конкретной группы
    """
    # Ожидание файла для массового импорта
    waiting_for_file = State()
    # Выбор групп для импорта (галочки)
    selecting_groups = State()
    # Ожидание файла для импорта в одну группу (из меню настроек)
    waiting_for_file_single = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ТИПЫ ДЛЯ СЕРИАЛИЗАЦИИ
# ============================================================

class GroupInfo:
    """Простой класс для хранения информации о группе."""
    def __init__(self, chat_id: int, title: str):
        self.chat_id = chat_id
        self.title = title

    def to_dict(self) -> dict:
        return {"chat_id": self.chat_id, "title": self.title}

    @classmethod
    def from_dict(cls, data: dict) -> "GroupInfo":
        return cls(chat_id=data["chat_id"], title=data["title"])


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

    Сразу просит загрузить JSON файл, после чего показывает
    список групп с галочками для массового импорта.

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

        # Сохраняем список групп в FSM для следующего шага
        # Преобразуем в сериализуемый формат
        groups_data = [
            GroupInfo(chat_id=g.chat_id, title=getattr(g, 'title', None) or f"Группа {g.chat_id}").to_dict()
            for g in importable_groups
        ]
        await state.update_data(importable_groups=groups_data)

        # Переходим в состояние ожидания файла
        await state.set_state(ImportSettingsStates.waiting_for_file)

        # Создаём клавиатуру с кнопкой отмены
        keyboard = create_cancel_keyboard()

        # Отправляем сообщение с инструкцией
        await message.answer(
            "📥 <b>Импорт настроек</b>\n\n"
            f"Доступно групп для импорта: <b>{len(importable_groups)}</b>\n\n"
            "Отправьте JSON файл с настройками.\n"
            "<i>Файл должен быть получен через /export_settings</i>\n\n"
            "После загрузки файла вы сможете выбрать группы для импорта.",
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

    После успешной загрузки показывает список групп с галочками.

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
        groups_data = state_data.get('importable_groups', [])

        if not groups_data:
            await message.answer(
                "❌ <b>Ошибка</b>\n\n"
                "Список групп не найден. Используйте /import_settings заново.",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Преобразуем обратно в объекты GroupInfo
        groups = [GroupInfo.from_dict(g) for g in groups_data]

        # Удаляем старое сообщение с инструкцией (если есть)
        instruction_message_id = state_data.get('instruction_message_id')
        if instruction_message_id:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id
                )
            except Exception:
                pass  # Не удалось удалить - игнорируем

        # Сохраняем данные импорта в состояние
        # По умолчанию выбираем ВСЕ группы
        all_chat_ids = {g.chat_id for g in groups}
        await state.update_data(
            import_data=import_data,
            selected_groups=list(all_chat_ids),  # set не сериализуется, храним как list
        )

        # Переходим в состояние выбора групп
        await state.set_state(ImportSettingsStates.selecting_groups)

        # Формируем статистику из файла
        data_stats = import_data.get('data', {})
        stats_lines = []
        for key, value in data_stats.items():
            if value:
                if isinstance(value, list):
                    count = len(value)
                    if count > 0:
                        stats_lines.append(f"  • {key}: {count}")
                else:
                    stats_lines.append(f"  • {key}: ✓")

        stats_text = "\n".join(stats_lines) if stats_lines else "  (нет данных)"

        # Информация об источнике
        source_chat_id = import_data.get('source_chat_id', 'неизвестно')
        exported_at = import_data.get('exported_at', 'неизвестно')

        # Получаем origin_chat_id для кнопки "Назад"
        origin_chat_id = state_data.get('mass_import_origin_chat_id')

        # Создаём клавиатуру с галочками
        keyboard = create_multi_group_select_keyboard(groups, all_chat_ids, origin_chat_id)

        # Отправляем сообщение с выбором групп
        await message.answer(
            f"📥 <b>Выберите группы для импорта</b>\n\n"
            f"<b>Источник:</b> <code>{source_chat_id}</code>\n"
            f"<b>Экспортировано:</b> {exported_at}\n\n"
            f"<b>Данные:</b>\n{stats_text}\n\n"
            f"Нажмите на группу чтобы выбрать/снять выбор:",
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
# CALLBACK: ПЕРЕКЛЮЧЕНИЕ ГАЛОЧКИ ГРУППЫ
# ============================================================

@import_router.callback_query(
    ImportSettingsStates.selecting_groups,
    F.data.regexp(r"^import_toggle:-?\d+$"),
)
async def callback_toggle_group(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Переключает галочку выбора группы.

    Args:
        callback: Callback запрос
        state: Контекст FSM
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])

    try:
        # Получаем данные из состояния
        state_data = await state.get_data()
        selected_groups = set(state_data.get('selected_groups', []))
        groups_data = state_data.get('importable_groups', [])

        if not groups_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return

        # Переключаем галочку
        if chat_id in selected_groups:
            selected_groups.remove(chat_id)
        else:
            selected_groups.add(chat_id)

        # Сохраняем обратно
        await state.update_data(selected_groups=list(selected_groups))

        # Преобразуем группы
        groups = [GroupInfo.from_dict(g) for g in groups_data]

        # Получаем origin_chat_id для кнопки "Назад"
        origin_chat_id = state_data.get('mass_import_origin_chat_id')

        # Обновляем клавиатуру
        keyboard = create_multi_group_select_keyboard(groups, selected_groups, origin_chat_id)

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка переключения галочки: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================
# CALLBACK: ВЫБРАТЬ ВСЕ ГРУППЫ
# ============================================================

@import_router.callback_query(
    ImportSettingsStates.selecting_groups,
    F.data == "import_select_all",
)
async def callback_select_all(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Выбирает все группы.

    Args:
        callback: Callback запрос
        state: Контекст FSM
    """
    try:
        # Получаем данные из состояния
        state_data = await state.get_data()
        groups_data = state_data.get('importable_groups', [])

        if not groups_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return

        # Преобразуем группы
        groups = [GroupInfo.from_dict(g) for g in groups_data]

        # Выбираем все
        all_chat_ids = {g.chat_id for g in groups}
        await state.update_data(selected_groups=list(all_chat_ids))

        # Получаем origin_chat_id для кнопки "Назад"
        origin_chat_id = state_data.get('mass_import_origin_chat_id')

        # Обновляем клавиатуру
        keyboard = create_multi_group_select_keyboard(groups, all_chat_ids, origin_chat_id)

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer("✅ Все группы выбраны")

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка выбора всех: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================
# CALLBACK: СНЯТЬ ВЫБОР СО ВСЕХ ГРУПП
# ============================================================

@import_router.callback_query(
    ImportSettingsStates.selecting_groups,
    F.data == "import_deselect_all",
)
async def callback_deselect_all(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Снимает выбор со всех групп.

    Args:
        callback: Callback запрос
        state: Контекст FSM
    """
    try:
        # Получаем данные из состояния
        state_data = await state.get_data()
        groups_data = state_data.get('importable_groups', [])

        if not groups_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return

        # Преобразуем группы
        groups = [GroupInfo.from_dict(g) for g in groups_data]

        # Снимаем выбор
        await state.update_data(selected_groups=[])

        # Получаем origin_chat_id для кнопки "Назад"
        origin_chat_id = state_data.get('mass_import_origin_chat_id')

        # Обновляем клавиатуру
        keyboard = create_multi_group_select_keyboard(groups, set(), origin_chat_id)

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer("⬜ Выбор снят")

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка снятия выбора: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================
# CALLBACK: ВЫПОЛНИТЬ ИМПОРТ
# ============================================================

@import_router.callback_query(
    ImportSettingsStates.selecting_groups,
    F.data == "import_execute",
)
async def callback_execute_import(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Выполняет импорт настроек во все выбранные группы.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    user_id = callback.from_user.id

    try:
        # Получаем данные из состояния
        state_data = await state.get_data()
        selected_groups = set(state_data.get('selected_groups', []))
        groups_data = state_data.get('importable_groups', [])
        import_data = state_data.get('import_data')
        origin_chat_id = state_data.get('mass_import_origin_chat_id')  # Для кнопки "Назад"

        if not import_data:
            await callback.answer("❌ Данные для импорта не найдены", show_alert=True)
            await state.clear()
            return

        if not selected_groups:
            await callback.answer("⚠️ Выберите хотя бы одну группу", show_alert=True)
            return

        # Преобразуем группы в dict для быстрого поиска названий
        groups_dict = {g["chat_id"]: g["title"] for g in groups_data}

        # Показываем индикатор загрузки
        await callback.message.edit_text(
            f"⏳ <b>Импорт настроек...</b>\n\n"
            f"Выбрано групп: {len(selected_groups)}\n"
            f"Пожалуйста, подождите...",
            parse_mode="HTML"
        )

        logger.info(
            f"📥 [IMPORT] Начинаем импорт в {len(selected_groups)} групп, user_id={user_id}"
        )

        # Выполняем импорт в каждую группу
        results = []
        for chat_id in selected_groups:
            group_title = groups_dict.get(chat_id, f"Группа {chat_id}")

            try:
                # Проверяем права ещё раз
                can_import, reason = await can_export_import_settings(
                    bot=callback.bot,
                    chat_id=chat_id,
                    user_id=user_id,
                )

                if not can_import:
                    results.append((group_title, "⚠️", reason))
                    continue

                # Выполняем импорт
                stats = await import_group_settings(
                    session=session,
                    chat_id=chat_id,
                    data=import_data,
                    user_id=user_id,
                    merge=False,
                )

                # Считаем общее количество импортированных записей
                total_imported = sum(stats.values())
                results.append((group_title, "✅", f"{total_imported} записей"))

                logger.info(f"✅ [IMPORT] Импорт в {chat_id} успешен: {stats}")

            except Exception as e:
                error_msg = str(e)[:50]
                results.append((group_title, "❌", error_msg))
                logger.error(f"❌ [IMPORT] Ошибка импорта в {chat_id}: {e}")

        # Очищаем FSM
        await state.clear()

        # Формируем отчёт
        success_count = sum(1 for r in results if r[1] == "✅")
        failed_count = len(results) - success_count

        report_lines = []
        for title, status, details in results:
            # Ограничиваем длину названия
            if len(title) > 20:
                title = title[:17] + "..."
            report_lines.append(f"{status} {title}: {details}")

        report_text = "\n".join(report_lines)

        # Создаём клавиатуру с кнопкой "Назад" (если есть origin_chat_id)
        result_keyboard = create_import_result_keyboard(origin_chat_id)

        # Отправляем результат
        await callback.message.edit_text(
            f"📥 <b>Импорт завершён</b>\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {failed_count}\n\n"
            f"<b>Результаты:</b>\n{report_text}",
            reply_markup=result_keyboard,
            parse_mode="HTML"
        )

        await callback.answer("✅ Импорт завершён!")

    except Exception as e:
        logger.error(f"❌ [IMPORT] Критическая ошибка импорта: {e}")
        await state.clear()
        safe_error = html.escape(str(e))[:200]
        await callback.message.edit_text(
            f"❌ <b>Ошибка импорта</b>\n\n<code>{safe_error}</code>",
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
# ФЛОУ B: ИМПОРТ ИЗ МЕНЮ НАСТРОЕК (ВЫБОР ТИПА)
# ============================================================

@import_router.callback_query(F.data.regexp(r"^import_select:-?\d+$"))
async def callback_import_select_group(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает нажатие кнопки "Импорт" из меню настроек.

    Показывает выбор: импорт в эту группу или массовый импорт.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    logger.info(f"📥 [IMPORT] Меню импорта chat_id={chat_id} user_id={user_id}")

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

        # Сохраняем chat_id в состояние FSM для использования в массовом импорте
        await state.update_data(
            single_import_chat_id=chat_id,
            single_import_chat_title=chat_title,
        )

        # Создаём клавиатуру выбора типа импорта
        keyboard = create_import_type_select_keyboard(chat_id)

        # Редактируем сообщение
        await callback.message.edit_text(
            f"📥 <b>Импорт настроек</b>\n\n"
            f"Текущая группа: <b>{chat_title}</b>\n\n"
            f"Выберите тип импорта:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка меню импорта: {e}")
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


@import_router.callback_query(F.data.regexp(r"^import_single:-?\d+$"))
async def callback_import_single_group(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает выбор импорта в одну группу.

    Переходит в состояние ожидания файла для конкретной группы.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    logger.info(f"📥 [IMPORT] Импорт в одну группу chat_id={chat_id} user_id={user_id}")

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
        await state.update_data(
            single_import_chat_id=chat_id,
            single_import_chat_title=chat_title,
        )

        # Переходим в состояние ожидания файла для одной группы
        await state.set_state(ImportSettingsStates.waiting_for_file_single)

        # Создаём клавиатуру с кнопкой возврата к настройкам
        keyboard = create_cancel_keyboard(chat_id)

        # Редактируем сообщение
        await callback.message.edit_text(
            f"📥 <b>Импорт в группу</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n\n"
            f"Отправьте JSON файл с настройками.\n"
            f"<i>Файл должен быть получен через /export_settings</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # Сохраняем ID сообщения с инструкцией для последующего удаления
        await state.update_data(instruction_message_id=callback.message.message_id)

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка выбора группы: {e}")
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


@import_router.callback_query(F.data == "import_mass")
async def callback_import_mass(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает выбор массового импорта.

    Переходит в состояние ожидания файла для массового импорта.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
    user_id = callback.from_user.id

    logger.info(f"📥 [IMPORT] Массовый импорт user_id={user_id}")

    try:
        # Получаем chat_id из FSM (сохранён при выборе import_select)
        state_data = await state.get_data()
        origin_chat_id = state_data.get('single_import_chat_id')

        # Получаем группы где пользователь админ
        user_groups = await get_admin_groups(user_id, session, bot=callback.bot)

        # Если нет групп
        if not user_groups:
            await callback.answer("❌ Нет доступных групп", show_alert=True)
            return

        # Фильтруем группы где можно импортировать
        importable_groups = []
        for group in user_groups:
            can_import, reason = await can_export_import_settings(
                bot=callback.bot,
                chat_id=group.chat_id,
                user_id=user_id,
            )
            if can_import:
                importable_groups.append(group)

        # Если нет групп с правами
        if not importable_groups:
            await callback.answer("⚠️ Нет групп с правами на импорт", show_alert=True)
            return

        # Сохраняем список групп в FSM (сохраняем origin_chat_id для возврата)
        groups_data = [
            GroupInfo(chat_id=g.chat_id, title=getattr(g, 'title', None) or f"Группа {g.chat_id}").to_dict()
            for g in importable_groups
        ]
        await state.update_data(
            importable_groups=groups_data,
            mass_import_origin_chat_id=origin_chat_id,  # Для возврата к настройкам
        )

        # Переходим в состояние ожидания файла
        await state.set_state(ImportSettingsStates.waiting_for_file)

        # Создаём клавиатуру с кнопкой назад (если есть origin_chat_id)
        keyboard = create_cancel_keyboard(origin_chat_id)

        # Редактируем сообщение и сохраняем его ID для последующего удаления
        await callback.message.edit_text(
            f"📤 <b>Массовый импорт</b>\n\n"
            f"Доступно групп: <b>{len(importable_groups)}</b>\n\n"
            f"Отправьте JSON файл с настройками.\n"
            f"<i>Файл должен быть получен через /export_settings</i>\n\n"
            f"После загрузки вы сможете выбрать группы для импорта.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # Сохраняем ID сообщения с инструкцией для последующего удаления
        await state.update_data(instruction_message_id=callback.message.message_id)

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка массового импорта: {e}")
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


@import_router.message(
    ImportSettingsStates.waiting_for_file_single,
    F.document,
)
async def handle_import_file_single(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Обрабатывает загруженный файл для импорта в одну группу.

    После загрузки показывает подтверждение и выполняет импорт.

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
        # Получаем данные из состояния
        state_data = await state.get_data()
        chat_id = state_data.get('single_import_chat_id')
        chat_title = state_data.get('single_import_chat_title', 'Группа')

        if not chat_id:
            await message.answer(
                "❌ <b>Ошибка</b>\n\n"
                "Группа не выбрана. Используйте /import_settings.",
                parse_mode="HTML"
            )
            await state.clear()
            return

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

        # Удаляем старое сообщение с инструкцией (если есть)
        instruction_message_id = state_data.get('instruction_message_id')
        if instruction_message_id:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=instruction_message_id
                )
            except Exception:
                pass  # Не удалось удалить - игнорируем

        # Сохраняем данные для импорта
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


@import_router.callback_query(F.data.regexp(r"^import_confirm:-?\d+$"))
async def callback_import_confirm_single(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """
    Выполняет импорт настроек в одну группу после подтверждения.

    Args:
        callback: Callback запрос
        session: Сессия БД
        state: Контекст FSM
    """
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
        chat_title = state_data.get('single_import_chat_title', 'Группа')

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

        # Создаём клавиатуру с кнопкой "Назад"
        result_keyboard = create_import_result_keyboard(chat_id)

        # Редактируем сообщение с результатом
        await callback.message.edit_text(
            f"✅ <b>Импорт завершён</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n\n"
            f"<b>Импортировано:</b>\n{stats_text}",
            reply_markup=result_keyboard,
            parse_mode="HTML"
        )

        logger.info(f"✅ [IMPORT] Импорт успешен chat_id={chat_id} stats={stats}")

        await callback.answer("✅ Импорт завершён!")

    except Exception as e:
        logger.error(f"❌ [IMPORT] Ошибка импорта: {e}")
        await state.clear()
        safe_error = html.escape(str(e))
        if len(safe_error) > 500:
            safe_error = safe_error[:500] + "..."
        await callback.message.edit_text(
            f"❌ <b>Ошибка импорта</b>\n\n<code>{safe_error}</code>",
            parse_mode="HTML"
        )
        await callback.answer("❌ Ошибка импорта", show_alert=True)


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
# ХЕНДЛЕРЫ: НЕВЕРНЫЙ ВВОД В СОСТОЯНИЯХ ОЖИДАНИЯ ФАЙЛА
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
    Обрабатывает некорректный ввод когда ожидается файл (массовый импорт).

    Args:
        message: Входящее сообщение (не документ)
        state: Контекст FSM
    """
    # Проверяем не команда ли это
    if message.text and message.text.startswith('/'):
        # Если это команда - очищаем состояние и пропускаем
        await state.clear()
        return

    # Получаем origin_chat_id для кнопки назад (если пришли из меню настроек)
    state_data = await state.get_data()
    origin_chat_id = state_data.get('mass_import_origin_chat_id')

    # Напоминаем что нужен файл
    keyboard = create_cancel_keyboard(origin_chat_id)

    await message.answer(
        "⚠️ <b>Ожидается файл</b>\n\n"
        "Пожалуйста, отправьте JSON файл с настройками.\n"
        "<i>Файл должен быть получен через /export_settings</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@import_router.message(
    ImportSettingsStates.waiting_for_file_single,
    ~F.document,
)
async def handle_invalid_input_waiting_file_single(
    message: Message,
    state: FSMContext,
) -> None:
    """
    Обрабатывает некорректный ввод когда ожидается файл (импорт в одну группу).

    Args:
        message: Входящее сообщение (не документ)
        state: Контекст FSM
    """
    # Проверяем не команда ли это
    if message.text and message.text.startswith('/'):
        # Если это команда - очищаем состояние и пропускаем
        await state.clear()
        return

    # Получаем chat_id для кнопки "назад"
    state_data = await state.get_data()
    chat_id = state_data.get('single_import_chat_id')

    # Напоминаем что нужен файл
    keyboard = create_cancel_keyboard(chat_id)

    await message.answer(
        "⚠️ <b>Ожидается файл</b>\n\n"
        "Пожалуйста, отправьте JSON файл с настройками.\n"
        "<i>Файл должен быть получен через /export_settings</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
