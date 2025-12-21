# ============================================================
# ХЕНДЛЕРЫ ЭКСПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль обрабатывает:
# - Команду /export_settings
# - Callback кнопки экспорта из UI настроек
#
# Экспорт доступен только владельцу или админу со всеми правами
# Файл отправляется в ЛС пользователя
# ============================================================

# Импортируем стандартные библиотеки
import logging
from datetime import datetime
from io import BytesIO

# Импортируем aiogram классы и функции
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы экспорта и проверки прав
from bot.services.settings_export.export_service import (
    export_group_settings,
    serialize_settings_to_json,
)
from bot.services.settings_export.permissions import can_export_import_settings

# Импортируем сервис получения групп пользователя
from bot.services.groups_settings_in_private_logic import get_admin_groups

# Импортируем клавиатуры
from bot.keyboards.settings_export_kb import (
    create_export_groups_keyboard,
    create_export_confirm_keyboard,
)

# Создаём логгер для отслеживания экспорта
logger = logging.getLogger(__name__)

# Создаём роутер для хендлеров экспорта
export_router = Router(name="export_handlers")


# ============================================================
# КОМАНДА /export_settings
# ============================================================

@export_router.message(Command("export_settings"))
async def cmd_export_settings(
    message: Message,
    session: AsyncSession,
) -> None:
    """
    Обрабатывает команду /export_settings.

    Показывает список групп где пользователь является владельцем или
    админом со всеми правами. При выборе группы - экспортирует настройки.

    Команда работает ТОЛЬКО в ЛС бота. В группах - удаляется.

    Args:
        message: Входящее сообщение с командой
        session: Сессия БД (инжектится middleware)
    """
    # Получаем данные пользователя
    user_id = message.from_user.id

    # Логируем получение команды
    logger.info(f"📤 [EXPORT] Команда /export_settings от user_id={user_id}")

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

        # Если нет групп - сообщаем об этом
        if not user_groups:
            await message.answer(
                "❌ <b>Нет доступных групп</b>\n\n"
                "Вы не являетесь администратором ни в одной группе "
                "где есть этот бот.",
                parse_mode="HTML"
            )
            return

        # Фильтруем группы: оставляем только те где пользователь владелец или полный админ
        exportable_groups = []
        for group in user_groups:
            # Проверяем права на экспорт
            can_export, reason = await can_export_import_settings(
                bot=message.bot,
                chat_id=group.chat_id,
                user_id=user_id,
            )
            if can_export:
                exportable_groups.append(group)

        # Если нет групп с правами на экспорт
        if not exportable_groups:
            await message.answer(
                "⚠️ <b>Недостаточно прав</b>\n\n"
                "Для экспорта настроек нужно быть:\n"
                "• Владельцем группы, или\n"
                "• Администратором со <b>всеми</b> правами\n\n"
                "У вас нет таких групп.",
                parse_mode="HTML"
            )
            return

        # Создаём клавиатуру со списком групп
        keyboard = create_export_groups_keyboard(exportable_groups)

        # Отправляем сообщение с выбором группы
        await message.answer(
            "📤 <b>Экспорт настроек</b>\n\n"
            "Выберите группу для экспорта настроек:\n\n"
            "<i>Будут экспортированы: запрещённые слова, паттерны, "
            "правила антиспама, настройки фильтров и т.д.</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        # Логируем ошибку
        logger.error(f"❌ [EXPORT] Ошибка в cmd_export_settings: {e}")
        await message.answer(
            "❌ Произошла ошибка при получении списка групп.\n"
            "Попробуйте позже."
        )


# ============================================================
# CALLBACK: ВЫБОР ГРУППЫ ДЛЯ ЭКСПОРТА
# ============================================================

@export_router.callback_query(F.data.regexp(r"^export_select:-?\d+$"))
async def callback_export_select_group(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Обрабатывает выбор группы для экспорта.

    При нажатии на группу показывает подтверждение экспорта.

    Args:
        callback: Callback запрос с данными группы
        session: Сессия БД (инжектится middleware)
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Логируем выбор группы
    logger.info(f"📤 [EXPORT] Выбрана группа chat_id={chat_id} user_id={user_id}")

    try:
        # Повторно проверяем права (безопасность)
        can_export, reason = await can_export_import_settings(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        if not can_export:
            # Права изменились - отклоняем
            await callback.answer(f"❌ {reason}", show_alert=True)
            return

        # Получаем информацию о группе
        chat = await callback.bot.get_chat(chat_id)
        chat_title = chat.title or f"Группа {chat_id}"

        # Создаём клавиатуру подтверждения
        keyboard = create_export_confirm_keyboard(chat_id)

        # Редактируем сообщение с подтверждением
        await callback.message.edit_text(
            f"📤 <b>Экспорт настроек</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n"
            f"ID: <code>{chat_id}</code>\n\n"
            f"Нажмите <b>Экспортировать</b> для создания файла настроек.\n\n"
            f"<i>Файл будет отправлен в этот чат.</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # Отвечаем на callback
        await callback.answer()

    except Exception as e:
        logger.error(f"❌ [EXPORT] Ошибка выбора группы: {e}")
        await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)


# ============================================================
# CALLBACK: ПОДТВЕРЖДЕНИЕ ЭКСПОРТА
# ============================================================

@export_router.callback_query(F.data.regexp(r"^export_confirm:-?\d+$"))
async def callback_export_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Выполняет экспорт настроек и отправляет файл.

    Args:
        callback: Callback запрос с подтверждением
        session: Сессия БД (инжектится middleware)
    """
    # Извлекаем chat_id из callback_data
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Логируем подтверждение экспорта
    logger.info(f"📤 [EXPORT] Подтверждение экспорта chat_id={chat_id} user_id={user_id}")

    try:
        # Повторно проверяем права (безопасность)
        can_export, reason = await can_export_import_settings(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=user_id,
        )

        if not can_export:
            await callback.answer(f"❌ {reason}", show_alert=True)
            return

        # Показываем индикатор загрузки
        await callback.message.edit_text(
            "⏳ <b>Экспорт настроек...</b>\n\n"
            "Пожалуйста, подождите. Собираем данные...",
            parse_mode="HTML"
        )

        # Выполняем экспорт
        export_data = await export_group_settings(session, chat_id)

        # Сериализуем в JSON
        json_content = serialize_settings_to_json(export_data)

        # Получаем название группы для имени файла
        chat = await callback.bot.get_chat(chat_id)
        chat_title = chat.title or "group"

        # Формируем имя файла (безопасное)
        safe_title = "".join(c for c in chat_title if c.isalnum() or c in (' ', '-', '_'))[:30]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"settings_{safe_title}_{timestamp}.json"

        # Создаём файл для отправки
        file_bytes = json_content.encode('utf-8')
        input_file = BufferedInputFile(file_bytes, filename=filename)

        # Формируем статистику экспорта
        data_stats = export_data.get('data', {})
        stats_lines = []
        for key, value in data_stats.items():
            if value:
                # Считаем количество записей
                if isinstance(value, list):
                    count = len(value)
                    if count > 0:
                        stats_lines.append(f"  • {key}: {count} записей")
                else:
                    stats_lines.append(f"  • {key}: ✓")

        stats_text = "\n".join(stats_lines) if stats_lines else "  (нет данных)"

        # Редактируем сообщение с результатом
        await callback.message.edit_text(
            f"✅ <b>Экспорт завершён</b>\n\n"
            f"Группа: <b>{chat_title}</b>\n\n"
            f"<b>Экспортировано:</b>\n{stats_text}\n\n"
            f"<i>Файл отправлен ниже.</i>",
            parse_mode="HTML"
        )

        # Отправляем файл
        await callback.message.answer_document(
            document=input_file,
            caption=(
                f"📁 Настройки группы: {chat_title}\n"
                f"📅 Экспортировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            ),
        )

        # Логируем успешный экспорт
        logger.info(f"✅ [EXPORT] Экспорт успешен chat_id={chat_id} файл={filename}")

        # Отвечаем на callback
        await callback.answer("✅ Экспорт завершён!")

    except Exception as e:
        logger.error(f"❌ [EXPORT] Ошибка экспорта: {e}")
        await callback.message.edit_text(
            "❌ <b>Ошибка экспорта</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            "Попробуйте позже.",
            parse_mode="HTML"
        )
        await callback.answer("❌ Ошибка экспорта", show_alert=True)


# ============================================================
# CALLBACK: ОТМЕНА ЭКСПОРТА
# ============================================================

@export_router.callback_query(F.data == "export_cancel")
async def callback_export_cancel(callback: CallbackQuery) -> None:
    """
    Отменяет процесс экспорта.

    Args:
        callback: Callback запрос отмены
    """
    # Редактируем сообщение
    await callback.message.edit_text(
        "❌ <b>Экспорт отменён</b>\n\n"
        "Используйте /export_settings чтобы начать заново.",
        parse_mode="HTML"
    )

    # Отвечаем на callback
    await callback.answer("Отменено")


# ============================================================
# CALLBACK: ВОЗВРАТ К НАСТРОЙКАМ ГРУППЫ
# ============================================================

@export_router.callback_query(F.data.regexp(r"^export_back:-?\d+$"))
async def callback_export_back(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """
    Возвращает к меню настроек группы из экспорта.

    Args:
        callback: Callback запрос
        session: Сессия БД
    """
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
        logger.error(f"❌ [EXPORT] Ошибка возврата к настройкам: {e}")
        await callback.answer("❌ Ошибка. Используйте /settings", show_alert=True)
