# bot/handlers/cross_group/settings_handler.py
"""
Хендлеры настроек кросс-групповой детекции.

Обрабатывает callback запросы для UI настроек модуля:
- Главное меню настроек
- Переключение включён/выключен
- Настройка интервалов
- Настройка действия при детекции
- Управление исключениями
"""

# Импортируем логгер для записи событий
import logging

# Импортируем типы aiogram
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем AsyncSession для работы с БД
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем сервисы настроек
from bot.services.cross_group.settings_service import (
    get_cross_group_settings,
    update_cross_group_settings,
    toggle_cross_group_detection,
    add_excluded_group,
    remove_excluded_group,
    format_seconds_to_human,
)

# Импортируем клавиатуры
from bot.keyboards.cross_group_kb import (
    create_cross_group_main_keyboard,
    create_interval_selection_keyboard,
    create_min_groups_keyboard,
    create_action_selection_keyboard,
    create_exclusions_keyboard,
    create_add_exclusion_keyboard,
    create_back_to_main_keyboard,
)

# Импортируем модели
from bot.database.models_cross_group import CrossGroupActionType

# Импортируем config для проверки прав суперадмина
from bot.config import ADMIN_IDS


# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)

# Создаём роутер для хендлеров настроек
router = Router(name="cross_group_settings")


# ============================================================
# FSM СОСТОЯНИЯ ДЛЯ ВВОДА ЗНАЧЕНИЙ
# ============================================================
class CrossGroupSettingsStates(StatesGroup):
    """Состояния FSM для ввода пользовательских значений."""
    # Ожидание ввода значения интервала
    waiting_interval_input = State()


# ============================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================
@router.callback_query(F.data == "cg:main")
async def cross_group_settings_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настроек кросс-групповой детекции.

    Показывает главное меню настроек модуля.
    Доступно только суперадминам бота.
    """
    try:
        # Получаем ID пользователя
        user_id = callback.from_user.id

        # Проверяем права: только суперадмины
        if user_id not in ADMIN_IDS:
            # Отправляем уведомление об отсутствии прав
            await callback.answer(
                "Недостаточно прав! Только суперадмины могут изменять эти настройки.",
                show_alert=True
            )
            return

        # Получаем текущие настройки
        settings = await get_cross_group_settings(session)

        # Формируем текст меню
        status_text = "Включена" if settings.enabled else "Выключена"
        text = (
            f"<b>Кросс-групповые действия</b>\n\n"
            f"Статус: {status_text}\n\n"
            f"<b>Критерии детекции:</b>\n"
            f"1. Вход в {settings.min_groups}+ групп за "
            f"{format_seconds_to_human(settings.join_interval_seconds)}\n"
            f"2. Смена профиля за "
            f"{format_seconds_to_human(settings.profile_change_window_seconds)}\n"
            f"3. Сообщения в {settings.min_groups}+ группах за "
            f"{format_seconds_to_human(settings.message_interval_seconds)}\n\n"
            f"<i>Детекция срабатывает когда ВСЕ критерии выполнены.</i>\n\n"
            f"⚠️ <b>Важно:</b> Для отслеживания смены профиля "
            f"включите «Мониторинг профилей» в настройках групп."
        )

        # Создаём клавиатуру
        keyboard = create_cross_group_main_keyboard(settings)

        # Обновляем сообщение
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # Отвечаем на callback
        await callback.answer()

    except Exception as e:
        # Логируем ошибку
        logger.error(f"Ошибка при открытии настроек кросс-групповой детекции: {e}")
        # Отправляем уведомление об ошибке
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# ПЕРЕКЛЮЧЕНИЕ ВКЛЮЧЁН/ВЫКЛЮЧЕН
# ============================================================
@router.callback_query(F.data == "cg:toggle")
async def toggle_cross_group_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик переключения статуса модуля.

    Включает или выключает кросс-групповую детекцию.
    """
    try:
        # Получаем ID пользователя
        user_id = callback.from_user.id

        # Проверяем права
        if user_id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Переключаем статус
        new_status = await toggle_cross_group_detection(session)

        # Формируем текст уведомления
        if new_status:
            answer_text = "Кросс-групповая детекция включена"
        else:
            answer_text = "Кросс-групповая детекция выключена"

        # Отправляем уведомление
        await callback.answer(answer_text, show_alert=True)

        # Получаем обновлённые настройки
        settings = await get_cross_group_settings(session)

        # Формируем текст меню
        status_text = "Включена" if settings.enabled else "Выключена"
        text = (
            f"<b>Кросс-групповые действия</b>\n\n"
            f"Статус: {status_text}\n\n"
            f"<b>Критерии детекции:</b>\n"
            f"1. Вход в {settings.min_groups}+ групп за "
            f"{format_seconds_to_human(settings.join_interval_seconds)}\n"
            f"2. Смена профиля за "
            f"{format_seconds_to_human(settings.profile_change_window_seconds)}\n"
            f"3. Сообщения в {settings.min_groups}+ группах за "
            f"{format_seconds_to_human(settings.message_interval_seconds)}\n\n"
            f"<i>Детекция срабатывает когда ВСЕ критерии выполнены.</i>\n\n"
            f"⚠️ <b>Важно:</b> Для отслеживания смены профиля "
            f"включите «Мониторинг профилей» в настройках групп."
        )

        # Обновляем клавиатуру
        keyboard = create_cross_group_main_keyboard(settings)

        # Обновляем сообщение
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при переключении статуса: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# НАСТРОЙКА ИНТЕРВАЛОВ
# ============================================================
@router.callback_query(F.data == "cg:set:join_interval")
async def set_join_interval_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настройки интервала входов.

    Показывает клавиатуру выбора интервала.
    """
    try:
        # Проверяем права
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Формируем текст
        text = (
            "<b>Интервал входов в группы</b>\n\n"
            "За какой период учитывать входы пользователя в группы.\n\n"
            "<i>Пример: если установлено 24 часа, то учитываются "
            "входы в группы за последние 24 часа.</i>"
        )

        # Создаём клавиатуру
        keyboard = create_interval_selection_keyboard("join_interval")

        # Обновляем сообщение
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии настройки интервала входов: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data == "cg:set:profile_window")
async def set_profile_window_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настройки окна смены профиля.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        text = (
            "<b>Окно смены профиля</b>\n\n"
            "В течение какого времени после входа учитывается смена профиля.\n\n"
            "<i>Пример: если установлено 12 часов, то смена имени/фото "
            "учитывается только если произошла в течение 12 часов после входа.</i>"
        )

        keyboard = create_interval_selection_keyboard("profile_window")

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии настройки окна смены профиля: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data == "cg:set:message_interval")
async def set_message_interval_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настройки интервала сообщений.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        text = (
            "<b>Интервал сообщений</b>\n\n"
            "За какой период учитывать сообщения в разных группах.\n\n"
            "<i>Пример: если установлен 1 час, то учитываются "
            "сообщения в группах за последний час.</i>"
        )

        keyboard = create_interval_selection_keyboard("message_interval")

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии настройки интервала сообщений: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# НАСТРОЙКА МИНИМАЛЬНОГО КОЛИЧЕСТВА ГРУПП
# ============================================================
@router.callback_query(F.data == "cg:set:min_groups")
async def set_min_groups_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настройки минимального количества групп.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        text = (
            "<b>Минимальное количество групп</b>\n\n"
            "Сколько групп должно быть затронуто для срабатывания детекции.\n\n"
            "<i>Рекомендуется 2 — минимум для кросс-групповой детекции.</i>"
        )

        keyboard = create_min_groups_keyboard()

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии настройки мин. групп: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# НАСТРОЙКА ДЕЙСТВИЯ ПРИ ДЕТЕКЦИИ
# ============================================================
@router.callback_query(F.data == "cg:set:action")
async def set_action_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия настройки действия при детекции.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Получаем текущие настройки
        settings = await get_cross_group_settings(session)

        text = (
            "<b>Действие при детекции</b>\n\n"
            "Какое действие применить к обнаруженному скамеру.\n\n"
            "<i>Действие применяется во всех затронутых группах.</i>"
        )

        keyboard = create_action_selection_keyboard(settings.action_type)

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии настройки действия: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# УСТАНОВКА ЗНАЧЕНИЙ
# ============================================================
@router.callback_query(F.data.startswith("cg:set_value:"))
async def set_value_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик установки значения настройки.

    Формат callback_data: cg:set_value:{setting}:{value}
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Парсим callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректные данные", show_alert=True)
            return

        setting = parts[2]
        value = parts[3]

        # Обновляем настройку в зависимости от типа
        if setting == "join_interval":
            await update_cross_group_settings(
                session,
                join_interval_seconds=int(value)
            )
            answer_text = f"Интервал входов: {format_seconds_to_human(int(value))}"

        elif setting == "profile_window":
            await update_cross_group_settings(
                session,
                profile_change_window_seconds=int(value)
            )
            answer_text = f"Окно смены профиля: {format_seconds_to_human(int(value))}"

        elif setting == "message_interval":
            await update_cross_group_settings(
                session,
                message_interval_seconds=int(value)
            )
            answer_text = f"Интервал сообщений: {format_seconds_to_human(int(value))}"

        elif setting == "min_groups":
            await update_cross_group_settings(
                session,
                min_groups=int(value)
            )
            answer_text = f"Минимум групп: {value}"

        elif setting == "action":
            # Конвертируем строку в enum
            action_map = {
                "mute": CrossGroupActionType.mute,
                "ban": CrossGroupActionType.ban,
                "kick": CrossGroupActionType.kick,
                "delete": CrossGroupActionType.delete,
            }
            action_type = action_map.get(value)
            if action_type:
                await update_cross_group_settings(
                    session,
                    action_type=action_type
                )
                action_names = {
                    "mute": "Мут",
                    "ban": "Бан",
                    "kick": "Кик",
                    "delete": "Удаление",
                }
                answer_text = f"Действие: {action_names.get(value, value)}"
            else:
                await callback.answer("Некорректное действие", show_alert=True)
                return

        else:
            await callback.answer("Неизвестная настройка", show_alert=True)
            return

        # Отправляем уведомление
        await callback.answer(answer_text)

        # Возвращаемся к главному меню
        settings = await get_cross_group_settings(session)

        status_text = "Включена" if settings.enabled else "Выключена"
        text = (
            f"<b>Кросс-групповые действия</b>\n\n"
            f"Статус: {status_text}\n\n"
            f"<b>Критерии детекции:</b>\n"
            f"1. Вход в {settings.min_groups}+ групп за "
            f"{format_seconds_to_human(settings.join_interval_seconds)}\n"
            f"2. Смена профиля за "
            f"{format_seconds_to_human(settings.profile_change_window_seconds)}\n"
            f"3. Сообщения в {settings.min_groups}+ группах за "
            f"{format_seconds_to_human(settings.message_interval_seconds)}\n\n"
            f"<i>Детекция срабатывает когда ВСЕ критерии выполнены.</i>\n\n"
            f"⚠️ <b>Важно:</b> Для отслеживания смены профиля "
            f"включите «Мониторинг профилей» в настройках групп."
        )

        keyboard = create_cross_group_main_keyboard(settings)

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при установке значения: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# ВОЗВРАТ К ГЛАВНОМУ МЕНЮ
# ============================================================
@router.callback_query(F.data == "cg:back_to_main")
async def back_to_main_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext
):
    """
    Обработчик возврата к главному меню настроек.

    Очищает FSM состояние при возврате.
    """
    try:
        # Очищаем FSM состояние (если было)
        await state.clear()

        # Получаем настройки
        settings = await get_cross_group_settings(session)

        # Формируем текст
        status_text = "Включена" if settings.enabled else "Выключена"
        text = (
            f"<b>Кросс-групповые действия</b>\n\n"
            f"Статус: {status_text}\n\n"
            f"<b>Критерии детекции:</b>\n"
            f"1. Вход в {settings.min_groups}+ групп за "
            f"{format_seconds_to_human(settings.join_interval_seconds)}\n"
            f"2. Смена профиля за "
            f"{format_seconds_to_human(settings.profile_change_window_seconds)}\n"
            f"3. Сообщения в {settings.min_groups}+ группах за "
            f"{format_seconds_to_human(settings.message_interval_seconds)}\n\n"
            f"<i>Детекция срабатывает когда ВСЕ критерии выполнены.</i>\n\n"
            f"⚠️ <b>Важно:</b> Для отслеживания смены профиля "
            f"включите «Мониторинг профилей» в настройках групп."
        )

        # Создаём клавиатуру
        keyboard = create_cross_group_main_keyboard(settings)

        # Обновляем сообщение
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при возврате к главному меню: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ============================================================
# УПРАВЛЕНИЕ ИСКЛЮЧЕНИЯМИ
# ============================================================
@router.callback_query(F.data == "cg:exclusions")
async def exclusions_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик открытия списка исключений.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Получаем настройки
        settings = await get_cross_group_settings(session)

        # Получаем информацию о группах
        # TODO: получить названия групп из БД
        groups_info = {}

        text = (
            "<b>Исключённые группы</b>\n\n"
            "Группы из этого списка игнорируются при детекции.\n\n"
            "<i>Нажмите на группу чтобы удалить из исключений.</i>"
        )

        keyboard = create_exclusions_keyboard(
            settings.excluded_groups or [],
            groups_info
        )

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при открытии исключений: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("cg:remove_exclusion:"))
async def remove_exclusion_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик удаления группы из исключений.
    """
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Парсим chat_id
        chat_id = int(callback.data.split(":")[-1])

        # Удаляем из исключений
        removed = await remove_excluded_group(session, chat_id)

        if removed:
            await callback.answer("Группа удалена из исключений")
        else:
            await callback.answer("Группа не найдена в исключениях")

        # Обновляем список
        settings = await get_cross_group_settings(session)
        groups_info = {}

        text = (
            "<b>Исключённые группы</b>\n\n"
            "Группы из этого списка игнорируются при детекции.\n\n"
            "<i>Нажмите на группу чтобы удалить из исключений.</i>"
        )

        keyboard = create_exclusions_keyboard(
            settings.excluded_groups or [],
            groups_info
        )

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при удалении исключения: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data == "cg:noop")
async def noop_callback(callback: CallbackQuery):
    """
    Пустой обработчик для информационных кнопок.
    """
    await callback.answer()


# ============================================================
# РУЧНОЙ ВВОД ЗНАЧЕНИЙ (FSM)
# ============================================================
@router.callback_query(F.data.startswith("cg:input:"))
async def input_value_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """
    Обработчик начала ручного ввода значения.

    Формат callback_data: cg:input:{setting_name}
    Устанавливает FSM состояние для ожидания ввода.
    """
    try:
        # Проверяем права
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Парсим название настройки
        setting_name = callback.data.split(":")[-1]

        # Определяем текст подсказки в зависимости от настройки
        hints = {
            "join_interval": (
                "<b>Введите интервал входов</b>\n\n"
                "Введите значение в секундах или в формате:\n"
                "• <code>1h</code> — 1 час\n"
                "• <code>30m</code> — 30 минут\n"
                "• <code>1d</code> — 1 день\n\n"
                "Пример: <code>12h</code> для 12 часов"
            ),
            "profile_window": (
                "<b>Введите окно смены профиля</b>\n\n"
                "Введите значение в секундах или в формате:\n"
                "• <code>1h</code> — 1 час\n"
                "• <code>30m</code> — 30 минут\n"
                "• <code>1d</code> — 1 день\n\n"
                "Пример: <code>6h</code> для 6 часов"
            ),
            "message_interval": (
                "<b>Введите интервал сообщений</b>\n\n"
                "Введите значение в секундах или в формате:\n"
                "• <code>1h</code> — 1 час\n"
                "• <code>30m</code> — 30 минут\n\n"
                "Пример: <code>2h</code> для 2 часов"
            ),
        }

        # Получаем текст подсказки
        hint_text = hints.get(setting_name, "Введите значение:")

        # Сохраняем название настройки в FSM
        await state.update_data(setting_name=setting_name)

        # Устанавливаем FSM состояние
        await state.set_state(CrossGroupSettingsStates.waiting_interval_input)

        # Создаём клавиатуру с кнопкой Назад
        keyboard = create_back_to_main_keyboard()

        # Обновляем сообщение
        await callback.message.edit_text(
            text=hint_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при начале ручного ввода: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.message(CrossGroupSettingsStates.waiting_interval_input)
async def process_interval_input(
    message,
    state: FSMContext,
    session: AsyncSession
):
    """
    Обработчик ручного ввода значения интервала.

    Принимает значение в секундах или в формате 1h/30m/1d.
    """
    try:
        # Проверяем права
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Недостаточно прав!")
            return

        # Получаем название настройки из FSM
        data = await state.get_data()
        setting_name = data.get("setting_name")

        if not setting_name:
            await message.answer("Ошибка: настройка не определена")
            await state.clear()
            return

        # Парсим введённое значение
        input_text = message.text.strip().lower()
        seconds = None

        # Пробуем распарсить как число (секунды)
        if input_text.isdigit():
            seconds = int(input_text)
        # Пробуем распарсить как формат с суффиксом
        elif input_text.endswith('m'):
            # Минуты
            try:
                minutes = int(input_text[:-1])
                seconds = minutes * 60
            except ValueError:
                pass
        elif input_text.endswith('h'):
            # Часы
            try:
                hours = int(input_text[:-1])
                seconds = hours * 3600
            except ValueError:
                pass
        elif input_text.endswith('d'):
            # Дни
            try:
                days = int(input_text[:-1])
                seconds = days * 86400
            except ValueError:
                pass

        # Проверяем что удалось распарсить
        if seconds is None or seconds <= 0:
            await message.answer(
                "Некорректное значение. Введите число секунд или формат:\n"
                "• <code>30m</code> — 30 минут\n"
                "• <code>1h</code> — 1 час\n"
                "• <code>1d</code> — 1 день",
                parse_mode="HTML"
            )
            return

        # Ограничиваем максимальное значение (30 дней)
        if seconds > 2592000:
            seconds = 2592000

        # Обновляем настройку в БД
        if setting_name == "join_interval":
            await update_cross_group_settings(
                session,
                join_interval_seconds=seconds
            )
        elif setting_name == "profile_window":
            await update_cross_group_settings(
                session,
                profile_change_window_seconds=seconds
            )
        elif setting_name == "message_interval":
            await update_cross_group_settings(
                session,
                message_interval_seconds=seconds
            )

        # Очищаем FSM состояние
        await state.clear()

        # Отправляем подтверждение
        await message.answer(
            f"Установлено: {format_seconds_to_human(seconds)}"
        )

        # Получаем обновлённые настройки и показываем главное меню
        settings = await get_cross_group_settings(session)

        status_text = "Включена" if settings.enabled else "Выключена"
        text = (
            f"<b>Кросс-групповые действия</b>\n\n"
            f"Статус: {status_text}\n\n"
            f"<b>Критерии детекции:</b>\n"
            f"1. Вход в {settings.min_groups}+ групп за "
            f"{format_seconds_to_human(settings.join_interval_seconds)}\n"
            f"2. Смена профиля за "
            f"{format_seconds_to_human(settings.profile_change_window_seconds)}\n"
            f"3. Сообщения в {settings.min_groups}+ группах за "
            f"{format_seconds_to_human(settings.message_interval_seconds)}\n\n"
            f"<i>Детекция срабатывает когда ВСЕ критерии выполнены.</i>\n\n"
            f"⚠️ <b>Важно:</b> Для отслеживания смены профиля "
            f"включите «Мониторинг профилей» в настройках групп."
        )

        keyboard = create_cross_group_main_keyboard(settings)

        await message.answer(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке ручного ввода: {e}")
        await message.answer("Произошла ошибка")
        await state.clear()


# ============================================================
# ДОБАВЛЕНИЕ ИСКЛЮЧЕНИЙ
# ============================================================
@router.callback_query(F.data == "cg:add_exclusion")
async def add_exclusion_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик показа списка доступных групп для добавления в исключения.
    """
    try:
        # Проверяем права
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Получаем текущие настройки
        settings = await get_cross_group_settings(session)
        excluded = settings.excluded_groups or []

        # Получаем список групп бота из БД
        # Импортируем модель здесь чтобы избежать circular import
        from bot.database.models import ChatSettings
        from sqlalchemy import select

        # Запрашиваем все группы
        result = await session.execute(
            select(ChatSettings.chat_id, ChatSettings.title)
            .where(ChatSettings.chat_id < 0)  # Только группы (отрицательные ID)
        )
        all_groups = result.all()

        # Фильтруем — оставляем только те которые ещё не исключены
        available_groups = [
            {"chat_id": chat_id, "title": title or f"ID: {chat_id}"}
            for chat_id, title in all_groups
            if chat_id not in excluded
        ]

        text = (
            "<b>Добавить группу в исключения</b>\n\n"
            "Выберите группу которую нужно исключить из детекции.\n\n"
            "<i>Исключённые группы не учитываются при кросс-групповой детекции.</i>"
        )

        keyboard = create_add_exclusion_keyboard(available_groups)

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при показе списка групп для исключения: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("cg:add_exclusion:"))
async def add_specific_exclusion_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """
    Обработчик добавления конкретной группы в исключения.

    Формат callback_data: cg:add_exclusion:{chat_id}
    """
    try:
        # Проверяем права
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Недостаточно прав!", show_alert=True)
            return

        # Парсим chat_id (учитываем отрицательные ID групп)
        parts = callback.data.split(":")
        chat_id = int(parts[-1])

        # Добавляем в исключения
        added = await add_excluded_group(session, chat_id)

        if added:
            await callback.answer("Группа добавлена в исключения")
        else:
            await callback.answer("Группа уже в исключениях")

        # Возвращаемся к списку исключений
        settings = await get_cross_group_settings(session)
        groups_info = {}

        text = (
            "<b>Исключённые группы</b>\n\n"
            "Группы из этого списка игнорируются при детекции.\n\n"
            "<i>Нажмите на группу чтобы удалить из исключений.</i>"
        )

        keyboard = create_exclusions_keyboard(
            settings.excluded_groups or [],
            groups_info
        )

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при добавлении группы в исключения: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
