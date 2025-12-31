# ============================================================
# ОБРАБОТЧИКИ CALLBACK-ЗАПРОСОВ SCAM MEDIA FILTER
# ============================================================
# Обработка нажатий на кнопки настроек модуля.
#
# Все callback_data начинаются с префикса "sm:" для изоляции.
# ============================================================

# Импорт для логирования
import logging
# Импорт для аннотации типов
from typing import Optional

# Импорт aiogram
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импорт SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт локальных сервисов
from bot.services.scam_media import SettingsService

# Импорт клавиатур
from .keyboards import (
    build_settings_keyboard,
    build_action_keyboard,
    build_threshold_keyboard,
    build_mute_time_keyboard,
    build_ban_time_keyboard,
    build_notification_keyboard,
    build_fsm_cancel_keyboard,
    PREFIX,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# СОЗДАНИЕ РОУТЕРА
# ============================================================
# Router группирует хендлеры для регистрации
router = Router()
# Устанавливаем имя для отладки
router.name = "scam_media_callbacks_router"


# ============================================================
# FSM ДЛЯ РУЧНОГО ВВОДА ВРЕМЕНИ
# ============================================================
class ScamMediaFSM(StatesGroup):
    """
    Состояния FSM для ручного ввода настроек.
    """
    # Ожидание ввода времени мута
    waiting_mute_time = State()
    # Ожидание ввода времени бана
    waiting_ban_time = State()
    # Ожидание ввода времени авто-удаления
    waiting_notification_delay = State()
    # Ожидание ввода текста мута
    waiting_mute_text = State()
    # Ожидание ввода текста бана
    waiting_ban_text = State()
    # Ожидание ввода текста предупреждения
    waiting_warn_text = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def _check_admin(callback: CallbackQuery, chat_id: int) -> bool:
    """
    Проверяет является ли пользователь администратором.

    Args:
        callback: Callback-запрос
        chat_id: ID чата

    Returns:
        bool: True если админ, False если нет
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

    Args:
        settings: Объект настроек

    Returns:
        Отформатированный текст
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
# TOGGLE - ВКЛЮЧЕНИЕ/ВЫКЛЮЧЕНИЕ МОДУЛЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:toggle:"))
async def cb_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает состояние модуля (вкл/выкл).

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    # Извлекаем chat_id из callback_data
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Проверяем права админа
    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы могут менять настройки", show_alert=True)
        return

    # Получаем текущие настройки
    settings = await SettingsService.get_or_create_settings(session, chat_id)

    # Переключаем состояние
    new_enabled = not settings.enabled
    await SettingsService.update_settings(session, chat_id, enabled=new_enabled)

    # Обновляем настройки в памяти
    settings = await SettingsService.get_settings(session, chat_id)

    # Обновляем сообщение
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    status = "включён" if new_enabled else "выключён"
    await callback.answer(f"✅ Модуль {status}")


# ============================================================
# ACTION - МЕНЮ ВЫБОРА ДЕЙСТВИЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:action:"))
async def cb_action_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора действия при срабатывании.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)

    await callback.message.edit_text(
        text=(
            "<b>⚡ Выбор действия</b>\n\n"
            "Что делать при обнаружении скам-изображения?"
        ),
        reply_markup=build_action_keyboard(chat_id, settings.action),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# ACTION_SET - УСТАНОВКА ДЕЙСТВИЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:action_set:"))
async def cb_action_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает выбранное действие.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    action = parts[3]

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Обновляем настройку
    await SettingsService.update_settings(session, chat_id, action=action)

    # Возвращаемся в главное меню
    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    await callback.answer(f"✅ Действие обновлено")


# ============================================================
# THRESHOLD - МЕНЮ ВЫБОРА ПОРОГА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:threshold:"))
async def cb_threshold_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора порога срабатывания.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)

    await callback.message.edit_text(
        text=(
            "<b>📊 Порог срабатывания</b>\n\n"
            "Максимальное расстояние Хэмминга для срабатывания.\n"
            "Меньше = строже (меньше false positive).\n"
            "Больше = мягче (больше совпадений)."
        ),
        reply_markup=build_threshold_keyboard(chat_id, settings.threshold),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# THRESHOLD_SET - УСТАНОВКА ПОРОГА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:threshold_set:"))
async def cb_threshold_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает выбранный порог.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    threshold = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    await SettingsService.update_settings(session, chat_id, threshold=threshold)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    await callback.answer(f"✅ Порог установлен: {threshold}")


# ============================================================
# MUTE_TIME - МЕНЮ ВЫБОРА ВРЕМЕНИ МУТА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:mute_time:"))
async def cb_mute_time_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора времени мута.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)

    await callback.message.edit_text(
        text=(
            "<b>🔇 Время мута</b>\n\n"
            "На сколько замутить нарушителя?"
        ),
        reply_markup=build_mute_time_keyboard(chat_id, settings.mute_duration),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# MUTE_TIME_SET - УСТАНОВКА ВРЕМЕНИ МУТА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:mute_time_set:"))
async def cb_mute_time_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает выбранное время мута.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    duration = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    await SettingsService.update_settings(session, chat_id, mute_duration=duration)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    await callback.answer("✅ Время мута обновлено")


# ============================================================
# BAN_TIME - МЕНЮ ВЫБОРА ВРЕМЕНИ БАНА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:ban_time:"))
async def cb_ban_time_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора времени бана.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)

    await callback.message.edit_text(
        text=(
            "<b>🚫 Время бана</b>\n\n"
            "На сколько забанить нарушителя?"
        ),
        reply_markup=build_ban_time_keyboard(chat_id, settings.ban_duration),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# BAN_TIME_SET - УСТАНОВКА ВРЕМЕНИ БАНА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:ban_time_set:"))
async def cb_ban_time_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает выбранное время бана.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    duration = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    await SettingsService.update_settings(session, chat_id, ban_duration=duration)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    await callback.answer("✅ Время бана обновлено")


# ============================================================
# CUSTOM_TIME - РУЧНОЙ ВВОД ВРЕМЕНИ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:custom_time:"))
async def cb_custom_time(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ручного ввода времени.

    Args:
        callback: Callback-запрос
        state: FSM контекст
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    time_type = parts[3]  # "mute" или "ban"

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # Сохраняем chat_id в state для последующего использования
    await state.update_data(chat_id=chat_id, time_type=time_type)

    if time_type == "mute":
        await state.set_state(ScamMediaFSM.waiting_mute_time)
        await callback.message.edit_text(
            text=(
                "<b>✏️ Ввод времени мута</b>\n\n"
                "Введите время в формате:\n"
                "• <code>30m</code> - 30 минут\n"
                "• <code>2h</code> - 2 часа\n"
                "• <code>7d</code> - 7 дней\n"
                "• <code>0</code> - навсегда\n\n"
                "Или отправьте число секунд."
            ),
            parse_mode="HTML"
        )
    else:
        await state.set_state(ScamMediaFSM.waiting_ban_time)
        await callback.message.edit_text(
            text=(
                "<b>✏️ Ввод времени бана</b>\n\n"
                "Введите время в формате:\n"
                "• <code>1d</code> - 1 день\n"
                "• <code>7d</code> - 7 дней\n"
                "• <code>30d</code> - 30 дней\n"
                "• <code>0</code> - навсегда\n\n"
                "Или отправьте число секунд."
            ),
            parse_mode="HTML"
        )

    await callback.answer()


# ============================================================
# GLOBAL - ПЕРЕКЛЮЧЕНИЕ ГЛОБАЛЬНОЙ БАЗЫ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:global:"))
async def cb_global_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает использование глобальной базы хешей.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    new_value = not settings.use_global_hashes

    await SettingsService.update_settings(session, chat_id, use_global_hashes=new_value)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    status = "включена" if new_value else "выключена"
    await callback.answer(f"✅ Глобальная база {status}")


# ============================================================
# JOURNAL - ПЕРЕКЛЮЧЕНИЕ ЖУРНАЛА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:journal:"))
async def cb_journal_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает логирование в журнал.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    new_value = not settings.log_to_journal

    await SettingsService.update_settings(session, chat_id, log_to_journal=new_value)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    status = "включён" if new_value else "выключён"
    await callback.answer(f"✅ Журнал {status}")


# ============================================================
# SCAMMER_DB - ПЕРЕКЛЮЧЕНИЕ ДОБАВЛЕНИЯ В БД СКАММЕРОВ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:scammer_db:"))
async def cb_scammer_db_toggle(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Переключает добавление в БД скаммеров.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    new_value = not settings.add_to_scammer_db

    await SettingsService.update_settings(session, chat_id, add_to_scammer_db=new_value)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    status = "включено" if new_value else "выключено"
    await callback.answer(f"✅ Добавление в БД скаммеров {status}")


# ============================================================
# BACK - ВОЗВРАТ В ГЛАВНОЕ МЕНЮ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:back:"))
async def cb_back(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Возвращает в главное меню настроек.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    settings = await SettingsService.get_or_create_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# CLOSE - ЗАКРЫТИЕ МЕНЮ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:close:"))
async def cb_close(
    callback: CallbackQuery
) -> None:
    """
    Закрывает меню настроек.

    Args:
        callback: Callback-запрос
    """
    await callback.message.delete()
    await callback.answer()


# ============================================================
# FSM HANDLERS - РУЧНОЙ ВВОД ВРЕМЕНИ
# ============================================================

from aiogram.types import Message


def _parse_duration(text: str) -> int | None:
    """
    Парсит строку с длительностью в секунды.

    Форматы:
    - "0" → 0 (навсегда)
    - "30m" → 1800 секунд
    - "2h" → 7200 секунд
    - "7d" → 604800 секунд
    - "123" → 123 секунд

    Args:
        text: Строка с временем

    Returns:
        Время в секундах или None при ошибке
    """
    text = text.strip().lower()

    # Навсегда
    if text == "0":
        return 0

    # Минуты
    if text.endswith("m"):
        try:
            return int(text[:-1]) * 60
        except ValueError:
            return None

    # Часы
    if text.endswith("h"):
        try:
            return int(text[:-1]) * 3600
        except ValueError:
            return None

    # Дни
    if text.endswith("d"):
        try:
            return int(text[:-1]) * 86400
        except ValueError:
            return None

    # Секунды (только число)
    try:
        return int(text)
    except ValueError:
        return None


@router.message(ScamMediaFSM.waiting_mute_time)
async def fsm_mute_time_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ручной ввод времени мута.

    Args:
        message: Сообщение с временем
        state: FSM контекст
        session: Сессия БД
    """
    # Получаем данные из state
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    # Парсим время
    duration = _parse_duration(message.text or "")

    if duration is None:
        await message.reply(
            "❌ Неверный формат времени.\n"
            "Используйте: 30m, 2h, 7d или число секунд."
        )
        return

    # Обновляем настройки
    await SettingsService.update_settings(session, chat_id, mute_duration=duration)

    # Очищаем state
    await state.clear()

    # Получаем обновлённые настройки
    settings = await SettingsService.get_settings(session, chat_id)

    # Отправляем подтверждение и меню
    from .keyboards import build_settings_keyboard
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


@router.message(ScamMediaFSM.waiting_ban_time)
async def fsm_ban_time_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ручной ввод времени бана.

    Args:
        message: Сообщение с временем
        state: FSM контекст
        session: Сессия БД
    """
    # Получаем данные из state
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    # Парсим время
    duration = _parse_duration(message.text or "")

    if duration is None:
        await message.reply(
            "❌ Неверный формат времени.\n"
            "Используйте: 1d, 7d, 30d или число секунд."
        )
        return

    # Обновляем настройки
    await SettingsService.update_settings(session, chat_id, ban_duration=duration)

    # Очищаем state
    await state.clear()

    # Получаем обновлённые настройки
    settings = await SettingsService.get_settings(session, chat_id)

    # Отправляем подтверждение и меню
    from .keyboards import build_settings_keyboard
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


# ============================================================
# SETTINGS - ОТКРЫТИЕ НАСТРОЕК ИЗ ГЛАВНОГО МЕНЮ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:settings:"))
async def cb_open_settings(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Открывает настройки ScamMedia из главного меню.

    Args:
        callback: Callback-запрос
        session: Сессия БД
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Импортируем здесь чтобы избежать циклического импорта
    from .settings_handler import show_scam_media_settings

    await show_scam_media_settings(callback, session, chat_id)
    await callback.answer()


# ============================================================
# NOTIFICATION - МЕНЮ АВТО-УДАЛЕНИЯ УВЕДОМЛЕНИЙ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:notification:"))
async def cb_notification_menu(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Показывает меню выбора времени авто-удаления.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)

    await callback.message.edit_text(
        text=(
            "<b>🗑️ Авто-удаление уведомлений</b>\n\n"
            "Через сколько секунд удалять уведомления бота о срабатывании?"
        ),
        reply_markup=build_notification_keyboard(chat_id, settings.notification_delete_delay),
        parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# NOTIFICATION_SET - УСТАНОВКА ВРЕМЕНИ АВТО-УДАЛЕНИЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:notification_set:"))
async def cb_notification_set(
    callback: CallbackQuery,
    session: AsyncSession
) -> None:
    """
    Устанавливает время авто-удаления уведомлений.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])
    delay = int(parts[3])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    # 0 означает "не удалять" — сохраняем как None
    delay_value = None if delay == 0 else delay
    await SettingsService.update_settings(session, chat_id, notification_delete_delay=delay_value)

    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )

    await callback.answer("✅ Время авто-удаления обновлено")


# ============================================================
# NOTIFICATION_CUSTOM - FSM РУЧНОЙ ВВОД ВРЕМЕНИ АВТО-УДАЛЕНИЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:notification_custom:"))
async def cb_notification_custom(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ручного ввода времени авто-удаления.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaFSM.waiting_notification_delay)

    await callback.message.edit_text(
        text=(
            "<b>✏️ Ввод времени авто-удаления</b>\n\n"
            "Введите время в секундах (например: 10, 30, 60).\n"
            "Или 0 чтобы отключить авто-удаление."
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaFSM.waiting_notification_delay)
async def fsm_notification_delay_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ручной ввод времени авто-удаления.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    # Парсим число
    try:
        delay = int(message.text.strip())
        if delay < 0:
            raise ValueError("Отрицательное значение")
    except ValueError:
        await message.reply("❌ Введите целое положительное число секунд.")
        return

    # 0 означает "не удалять"
    delay_value = None if delay == 0 else delay
    await SettingsService.update_settings(session, chat_id, notification_delete_delay=delay_value)

    await state.clear()

    settings = await SettingsService.get_settings(session, chat_id)
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


# ============================================================
# MUTE_TEXT - FSM ВВОД ТЕКСТА МУТА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:mute_text:"))
async def cb_mute_text(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ввода текста мута.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    current_text = settings.mute_text or "🔇 %user% замучен на %duration% за скам-контент."

    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaFSM.waiting_mute_text)

    await callback.message.edit_text(
        text=(
            "<b>📝 Текст мута</b>\n\n"
            f"Текущий текст:\n<code>{current_text}</code>\n\n"
            "Введите новый текст.\n"
            "Плейсхолдеры: <code>%user%</code> <code>%duration%</code>\n\n"
            "Или отправьте <code>default</code> для сброса."
        ),
        reply_markup=build_fsm_cancel_keyboard(chat_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaFSM.waiting_mute_text)
async def fsm_mute_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод текста мута.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    text = message.text.strip()
    # Если "default" — сбрасываем на NULL (используется дефолт)
    new_text = None if text.lower() == "default" else text

    await SettingsService.update_settings(session, chat_id, mute_text=new_text)
    await state.clear()

    settings = await SettingsService.get_settings(session, chat_id)
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


# ============================================================
# BAN_TEXT - FSM ВВОД ТЕКСТА БАНА
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:ban_text:"))
async def cb_ban_text(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ввода текста бана.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    current_text = settings.ban_text or "🚫 %user% забанен на %duration% за скам-контент."

    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaFSM.waiting_ban_text)

    await callback.message.edit_text(
        text=(
            "<b>📝 Текст бана</b>\n\n"
            f"Текущий текст:\n<code>{current_text}</code>\n\n"
            "Введите новый текст.\n"
            "Плейсхолдеры: <code>%user%</code> <code>%duration%</code>\n\n"
            "Или отправьте <code>default</code> для сброса."
        ),
        reply_markup=build_fsm_cancel_keyboard(chat_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaFSM.waiting_ban_text)
async def fsm_ban_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод текста бана.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    text = message.text.strip()
    new_text = None if text.lower() == "default" else text

    await SettingsService.update_settings(session, chat_id, ban_text=new_text)
    await state.clear()

    settings = await SettingsService.get_settings(session, chat_id)
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


# ============================================================
# WARN_TEXT - FSM ВВОД ТЕКСТА ПРЕДУПРЕЖДЕНИЯ
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:warn_text:"))
async def cb_warn_text(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Запускает FSM для ввода текста предупреждения.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    if not await _check_admin(callback, chat_id):
        await callback.answer("⛔ Только администраторы", show_alert=True)
        return

    settings = await SettingsService.get_settings(session, chat_id)
    current_text = settings.warn_text or "⚠️ %user%, ваше сообщение удалено за скам-контент."

    await state.update_data(chat_id=chat_id)
    await state.set_state(ScamMediaFSM.waiting_warn_text)

    await callback.message.edit_text(
        text=(
            "<b>📝 Текст предупреждения</b>\n\n"
            f"Текущий текст:\n<code>{current_text}</code>\n\n"
            "Введите новый текст.\n"
            "Плейсхолдер: <code>%user%</code>\n\n"
            "Или отправьте <code>default</code> для сброса."
        ),
        reply_markup=build_fsm_cancel_keyboard(chat_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ScamMediaFSM.waiting_warn_text)
async def fsm_warn_text_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Обрабатывает ввод текста предупреждения.
    """
    data = await state.get_data()
    chat_id = data.get("chat_id")

    if not chat_id:
        await state.clear()
        return

    text = message.text.strip()
    new_text = None if text.lower() == "default" else text

    await SettingsService.update_settings(session, chat_id, warn_text=new_text)
    await state.clear()

    settings = await SettingsService.get_settings(session, chat_id)
    await message.answer(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )


# ============================================================
# FSM_CANCEL - ОТМЕНА FSM (КНОПКА НАЗАД)
# ============================================================

@router.callback_query(F.data.startswith(f"{PREFIX}:fsm_cancel:"))
async def cb_fsm_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
) -> None:
    """
    Отменяет текущее FSM состояние и возвращает в настройки.
    """
    parts = callback.data.split(":")
    chat_id = int(parts[2])

    # Очищаем FSM
    await state.clear()

    # Возвращаем в настройки
    settings = await SettingsService.get_settings(session, chat_id)
    await callback.message.edit_text(
        text=_build_settings_text(settings),
        reply_markup=build_settings_keyboard(chat_id, settings),
        parse_mode="HTML"
    )
    await callback.answer("Отменено")
