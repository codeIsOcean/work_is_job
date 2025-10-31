from calendar import error

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from bot.services.groups_settings_in_private_logic import (
    get_admin_groups,
    check_admin_rights,
    check_granular_permissions,
    get_group_by_chat_id,
    get_visual_captcha_status,
    toggle_visual_captcha,
    get_mute_new_members_status
)
from bot.middleware.access_control import (
    ACCESS_CONTROL_ENABLED,
    enable_access_control,
    disable_access_control,
    ALLOWED_USER_IDS,
    ALLOWED_USERNAMES,
)
from bot.services.bot_activity_journal.bot_activity_journal_logic import log_visual_captcha_toggle, log_mute_settings_toggle
from bot.services.new_member_requested_to_join_mute_logic import (
    create_mute_settings_keyboard,
    get_mute_settings_text
)
import logging

logger = logging.getLogger(__name__)
group_settings_router = Router()


@group_settings_router.message(Command("settings"))
async def settings_command(message: types.Message, session: AsyncSession):
    """Обработчик команды /settings"""
    user_id = message.from_user.id
    logger.info(f"Получена команда /settings от пользователя {user_id}")

    # Проверяем разрешение: по ID или username из единого списка доступа
    username_norm = (message.from_user.username or "").lstrip("@").lower()
    if (user_id not in ALLOWED_USER_IDS) and (username_norm not in ALLOWED_USERNAMES):
        await message.answer(
            "🚫 <b>Доступ запрещен</b>\n\n"
            "Вы не разработчик, пока не можем вам дать права.\n"
            "Обратитесь к @texas_dev для получения доступа.",
            parse_mode="HTML"
        )
        return

    try:
        # Получаем группы пользователя через сервис
        user_groups = await get_admin_groups(user_id, session, bot=message.bot)

        if not user_groups:
            await message.answer("❌ У вас нет прав администратора ни в одной группе где есть бот.")
            return

        # Формируем клавиатуру со списком групп
        keyboard = create_groups_keyboard(user_groups)

        text = "🏠 **Ваши группы:**\n\nВыберите группу для настройки:"

        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при обработке команды /settings: {e}")
        await message.answer("❌ Произошла ошибка при получении ваших групп.")


@group_settings_router.message(Command("bot_access"))
async def bot_access_command(message: types.Message):
    """Обработчик команды /bot_access - настройки доступа к боту"""
    user_id = message.from_user.id
    logger.info(f"Получена команда /bot_access от пользователя {user_id}")

    # Проверяем, что это разрешенный пользователь
    if user_id != 619924982:
        await message.answer("❌ У вас нет прав для изменения настроек доступа к боту.")
        return

    try:
        # Создаем клавиатуру для управления доступом
        keyboard = create_access_control_keyboard()
        
        # Формируем текст с текущим статусом
        from bot.middleware.access_control import ACCESS_CONTROL_ENABLED
        status_text = "🔒 <b>Ограничен</b> (только для разработчика)" if ACCESS_CONTROL_ENABLED else "🔓 <b>Открыт</b> (для всех пользователей)"
        
        text = (
            f"🤖 <b>Настройки доступа к боту</b>\n\n"
            f"Текущий режим: {status_text}\n\n"
            f"Выберите режим работы бота:"
        )

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка при обработке команды /bot_access: {e}")
        await message.answer("❌ Произошла ошибка при получении настроек доступа.")


# Команда /start убрана - обрабатывается в visual_captcha_handler для deep links


@group_settings_router.message(Command("help"))
async def help_command(message: types.Message):
    """Обработчик команды /help - список доступных команд"""
    user_id = message.from_user.id
    
    # Базовые команды для всех пользователей
    text = (
        "🤖 <b>Доступные команды:</b>\n\n"
        "📋 <b>Основные команды:</b>\n"
        "• /settings - Настройки групп\n"
        "• /help - Показать это сообщение\n\n"
    )
    
    # Дополнительные команды только для разработчика
    if user_id == 619924982:
        text += (
            "🔧 <b>Команды разработчика:</b>\n"
            "• /bot_access - Настройки доступа к боту\n\n"
        )
    
    text += (
        "ℹ️ <b>Информация:</b>\n"
        "Этот бот помогает управлять группами с функциями:\n"
        "• Визуальная капча для новых участников\n"
        "• Антиспам защита\n"
        "• Настройки мута\n"
        "• Рассылки\n\n"
        "Для настройки бота используйте команду /settings"
    )
    
    await message.answer(text, parse_mode="HTML")


@group_settings_router.callback_query(F.data.startswith("manage_group_"))
async def manage_group_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Обработка управления конкретной группой"""
    logger.info(f"🔍 [GROUP_SETTINGS] ===== CALLBACK ОБРАБОТЧИК ВЫЗВАН =====")
    logger.info(f"🔍 [GROUP_SETTINGS] Callback data: {callback.data}")
    logger.info(f"🔍 [GROUP_SETTINGS] User ID: {callback.from_user.id}")
    logger.info(f"🔍 [GROUP_SETTINGS] User: @{callback.from_user.username or callback.from_user.first_name}")
    
    try:
        chat_id = int(callback.data.split("_")[-1])
        user_id = callback.from_user.id
        logger.info(f"🔍 [GROUP_SETTINGS] Parsed chat_id: {chat_id}, user_id: {user_id}")

        # Проверяем права администратора через сервис (правильный порядок параметров)
        if not await check_admin_rights(session, user_id, chat_id):
            await callback.answer("❌ У вас нет прав администратора в этой группе", show_alert=True)
            return

        # Получаем информацию о группе
        group = await get_group_by_chat_id(session, chat_id)
        if not group:
            await callback.answer("❌ Группа не найдена", show_alert=True)
            return

        # Отправляем меню управления группой
        await send_group_management_menu(callback.message, session, group)
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при обработке управления группой: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки при ответе на callback


# Обработчики настроек мута находятся в new_member_requested_to_join_mute_handlers.py


@group_settings_router.callback_query(F.data.startswith("toggle_visual_captcha_"))
async def toggle_visual_captcha_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Переключение визуальной капчи"""
    try:
        chat_id = int(callback.data.split("_")[-1])
        user_id = callback.from_user.id

        # Проверяем гранулярные права: изменение настроек бота требует can_change_info
        if not await check_granular_permissions(callback.bot, user_id, chat_id, 'change_info', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Изменять информацию о группе'", show_alert=True)
            return

        # Переключаем статус через сервис
        new_status = await toggle_visual_captcha(session, chat_id)
        status_text = "включена" if new_status else "выключена"

        # Логируем изменение настроек в журнал действий
        try:
            # Получаем информацию о группе из Telegram API
            chat_info = await callback.bot.get_chat(chat_id)
            await log_visual_captcha_toggle(
                bot=callback.bot,
                user=callback.from_user,
                chat=chat_info,
                enabled=new_status
            )
        except Exception as log_error:
            logger.error(f"Ошибка при логировании изменения визуальной капчи: {log_error}")

        # Обновляем меню
        group = await get_group_by_chat_id(session, chat_id)
        keyboard = await create_group_management_keyboard(session, chat_id)

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer(f"✅ Визуальная капча {status_text}", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при переключении визуальной капчи: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data.startswith("mute_new_members_settings_"))
async def mute_new_members_settings_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Обработчик настроек мута новых участников"""
    try:
        chat_id = int(callback.data.split("_")[-1])
        user_id = callback.from_user.id

        # Проверяем гранулярные права: мут участников требует can_restrict_members
        if not await check_granular_permissions(callback.bot, user_id, chat_id, 'restrict_members', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Ограничивать участников'", show_alert=True)
            return

        # Получаем данные для клавиатуры
        keyboard_data = await create_mute_settings_keyboard(chat_id, session)
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in keyboard_data["buttons"]
        ])
        
        # Формируем текст сообщения с учетом глобального мута
        from bot.services.groups_settings_in_private_logic import get_global_mute_status
        global_mute_status = await get_global_mute_status(session)
        message_text = await get_mute_settings_text(status=keyboard_data["status"], global_mute=global_mute_status)
        
        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при обработке настроек мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data.startswith("mute_new_members:enable:"))
async def enable_mute_new_members_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Включение мута новых участников"""
    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        # Проверяем гранулярные права: мут участников требует can_restrict_members
        if not await check_granular_permissions(callback.bot, user_id, chat_id, 'restrict_members', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Ограничивать участников'", show_alert=True)
            return

        # Включаем мут через сервис
        from bot.services.new_member_requested_to_join_mute_logic import set_mute_new_members_status
        success = await set_mute_new_members_status(chat_id, True, session)
        
        if success:
            await callback.answer("✅ Функция включена")

            # Логируем изменение настроек мута в журнал действий
            try:
                # Получаем информацию о группе из Telegram API
                chat_info = await callback.bot.get_chat(chat_id)
                await log_mute_settings_toggle(
                    bot=callback.bot,
                    user=callback.from_user,
                    chat=chat_info,
                    enabled=True
                )
            except Exception as log_error:
                logger.error(f"Ошибка при логировании изменения настроек мута: {log_error}")

            # 🔄 Перерисовываем экран настроек
            keyboard_data = await create_mute_settings_keyboard(chat_id, session)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                    for btn in row
                ]
                for row in keyboard_data["buttons"]
            ])

            message_text = await get_mute_settings_text(status=keyboard_data["status"])

            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )


        else:
            await callback.answer("❌ Ошибка при включении функции", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при включении мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data.startswith("mute_new_members:disable:"))
async def disable_mute_new_members_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Выключение мута новых участников"""
    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id

        # Проверяем гранулярные права: мут участников требует can_restrict_members
        if not await check_granular_permissions(callback.bot, user_id, chat_id, 'restrict_members', session):
            await callback.answer("❌ Недостаточно прав! Нужно право 'Ограничивать участников'", show_alert=True)
            return

        # Выключаем мут через сервис
        from bot.services.new_member_requested_to_join_mute_logic import set_mute_new_members_status
        success = await set_mute_new_members_status(chat_id, False, session)
        
        if success:
            await callback.answer("❌ Функция выключена")

            # Логируем изменение настроек мута в журнал действий
            try:
                # Получаем информацию о группе из Telegram API
                chat_info = await callback.bot.get_chat(chat_id)
                await log_mute_settings_toggle(
                    bot=callback.bot,
                    user=callback.from_user,
                    chat=chat_info,
                    enabled=False
                )
            except Exception as log_error:
                logger.error(f"Ошибка при логировании изменения настроек мута: {log_error}")

            # 🔄 Перерисовываем экран настроек
            keyboard_data = await create_mute_settings_keyboard(chat_id, session)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                    for btn in row
                ]
                for row in keyboard_data["buttons"]
            ])

            message_text = await get_mute_settings_text(status=keyboard_data["status"])

            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await callback.answer("❌ Ошибка при выключении функции", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при выключении мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data == "back_to_groups")
async def back_to_groups_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Возврат к списку групп"""
    user_id = callback.from_user.id
    logger.info(f"Возврат к списку групп от пользователя {user_id}")

    try:
        # получаем группы пользователя через сервис
        user_groups = await get_admin_groups(user_id, session, bot=callback.bot)

        if not user_groups:
            await callback.message.edit_text(" ❌ У вас нет прав администратора ни в одной группе где есть бот")
            return
        # формируем клавиатуру со списком групп
        keyboard = create_groups_keyboard(user_groups)

        text = "🏠 ** Ваши группы: **\n\nВыберите группы для настройки:"

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при возврате к списку групп: {e}")
        await callback.message.edit_text("❌ Произошла ошибка при получений ваших групп.")
    await callback.answer()


    # # Повторно вызываем команду settings
    # await settings_command(callback.message, session)
    # await callback.answer()


def create_groups_keyboard(groups):
    """Создает клавиатуру со списком групп с callback кнопками"""
    logger.info(f"🔍 [GROUP_SETTINGS] ===== СОЗДАНИЕ КЛАВИАТУРЫ =====")
    logger.info(f"🔍 [GROUP_SETTINGS] Количество групп: {len(groups)}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    # Добавляем кнопку глобального мута в начало
    global_mute_button = InlineKeyboardButton(
        text="🌍 Глобальный мут новых участников",
        callback_data="global_mute_settings"
    )
    keyboard.inline_keyboard.append([global_mute_button])
    logger.info(f"🔍 [GROUP_SETTINGS] Создана кнопка глобального мута")

    for group in groups:
        callback_data = f"manage_group_{group.chat_id}"
        button = InlineKeyboardButton(
            text=f"⚙️ {group.title}",
            callback_data=callback_data
        )
        keyboard.inline_keyboard.append([button])
        logger.info(f"🔍 [GROUP_SETTINGS] Создана кнопка: '{group.title}' -> '{callback_data}'")

    logger.info(f"🔍 [GROUP_SETTINGS] Клавиатура создана с {len(keyboard.inline_keyboard)} кнопками")
    return keyboard


async def send_group_management_menu(message: types.Message, session: AsyncSession, group):
    """Отправляет меню управления группой"""
    # Сохраняем привязку пользователя к группе в Redis
    from bot.services.redis_conn import redis
    user_id = message.from_user.id
    group_id = str(group.chat_id)
    
    logger.info(f"🔍 [GROUP_SETTINGS] Сохранение привязки пользователя {user_id} к группе {group_id}")
    
    await redis.hset(f"user:{user_id}", "group_id", group_id)
    # TTL на всякий случай (30 минут)
    await redis.expire(f"user:{user_id}", 30 * 60)
    
    # Проверяем что сохранилось
    saved_group_id = await redis.hget(f"user:{user_id}", "group_id")
    logger.info(f"🔍 [GROUP_SETTINGS] Проверка сохранения: user:{user_id} -> group_id: {saved_group_id}")
    
    if saved_group_id != group_id:
        logger.error(f"❌ [GROUP_SETTINGS] ОШИБКА: Не удалось сохранить group_id для пользователя {user_id}")
    else:
        logger.info(f"✅ [GROUP_SETTINGS] Успешно сохранена привязка пользователя {user_id} к группе {group_id}")
    
    text = f"**Управление группой**\n\n"
    text += f"**Название:** {group.title}\n"
    text += f"**ID:** `{group.chat_id}`\n\n"
    text += "**Доступные функции:**"

    keyboard = await create_group_management_keyboard(session, group.chat_id)

    await message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def create_group_management_keyboard(session: AsyncSession, chat_id: int):
    """Создает клавиатуру управления группой"""
    # Получаем статус визуальной капчи через сервис
    visual_captcha_status = await get_visual_captcha_status(session, chat_id)
    visual_captcha_text = "🔴 Выключить визуальную капчу" if visual_captcha_status else "🟢 Включить визуальную капчу"
    
    # Получаем статус мута новых участников (локальный)
    mute_status = await get_mute_new_members_status(session, chat_id)
    
    # Получаем статус глобального мута
    from bot.services.groups_settings_in_private_logic import get_global_mute_status
    global_mute_status = await get_global_mute_status(session)
    
    # Определяем общий статус мута (глобальный ИЛИ локальный)
    overall_mute_status = global_mute_status or mute_status
    
    # Формируем текст с учетом глобального мута
    if global_mute_status:
        mute_text = "🔇 Настройки мута новых участников 🌍 (глобально включен)"
    elif mute_status:
        mute_text = "🔇 Настройки мута новых участников ✅ (локально включен)"
    else:
        mute_text = "🔇 Настройки мута новых участников ❌ (выключен)"
    
    # Получаем статус автомута скаммеров
    from bot.services.auto_mute_scammers_logic import get_auto_mute_scammers_status
    auto_mute_status = await get_auto_mute_scammers_status(chat_id, session)
    auto_mute_text = "🤖 Настройки автомута скаммеров"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=visual_captcha_text,
            callback_data=f"toggle_visual_captcha_{chat_id}"
        )],
        [InlineKeyboardButton(
            text=mute_text,
            callback_data=f"new_member_requested_handler_settings:{chat_id}"
        )],
        [InlineKeyboardButton(
            text=auto_mute_text,
            callback_data=f"auto_mute_scammers_settings:{chat_id}"
        )],
        [InlineKeyboardButton(
            text="📢 Рассылки",
            callback_data="broadcast_settings"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад к списку групп",
            callback_data="back_to_groups"
        )]
    ])

    return keyboard


def create_access_control_keyboard():
    """Создает клавиатуру для управления доступом к боту"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔒 Только для разработчика",
                    callback_data="access_control_restricted"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔓 Для всех пользователей",
                    callback_data="access_control_open"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Текущий статус",
                    callback_data="access_control_status"
                )
            ]
        ]
    )
    return keyboard


@group_settings_router.callback_query(F.data.startswith("access_control_"))
async def access_control_callback(callback: types.CallbackQuery):
    """Обработчик callback'ов для управления доступом к боту"""
    user_id = callback.from_user.id
    
    # Проверяем права
    if user_id != 619924982:
        await callback.answer("❌ У вас нет прав для изменения настроек доступа", show_alert=True)
        return
    
    try:
        action = callback.data.split("_")[-1]
        
        if action == "restricted":
            enable_access_control()
            status_text = "🔒 <b>Ограничен</b> (только для разработчика)"
            await callback.answer("✅ Доступ ограничен только для разработчика", show_alert=True)
            
        elif action == "open":
            disable_access_control()
            status_text = "🔓 <b>Открыт</b> (для всех пользователей)"
            await callback.answer("✅ Доступ открыт для всех пользователей", show_alert=True)
            
        elif action == "status":
            # Импортируем актуальное значение
            from bot.middleware.access_control import ACCESS_CONTROL_ENABLED
            current_status = "🔒 <b>Ограничен</b> (только для разработчика)" if ACCESS_CONTROL_ENABLED else "🔓 <b>Открыт</b> (для всех пользователей)"
            await callback.answer(f"Текущий статус: {current_status}", show_alert=True)
            return
        
        # Обновляем сообщение с новым статусом
        text = (
            f"🤖 <b>Настройки доступа к боту</b>\n\n"
            f"Текущий режим: {status_text}\n\n"
            f"Выберите режим работы бота:"
        )
        
        keyboard = create_access_control_keyboard()
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback доступа: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data == "global_mute_settings")
async def global_mute_settings_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Обработчик настроек глобального мута"""
    try:
        user_id = callback.from_user.id
        
        # Проверяем права: только суперадмины могут изменять глобальные настройки
        from bot.config import ADMIN_IDS
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ У вас нет прав для изменения глобальных настроек. Только суперадмины могут изменять глобальные настройки.", show_alert=True)
            return
        
        # Получаем текущий статус глобального мута
        from bot.services.groups_settings_in_private_logic import get_global_mute_status
        current_status = await get_global_mute_status(session)
        
        # Создаем клавиатуру для управления глобальным мутом
        keyboard = create_global_mute_keyboard(current_status)
        
        status_text = "🟢 Включен" if current_status else "🔴 Выключен"
        text = (
            f"🌍 <b>Глобальный мут новых участников</b>\n\n"
            f"Текущий статус: {status_text}\n\n"
            f"Эта настройка влияет на все группы где находится бот.\n"
            f"При включении все новые участники будут автоматически замьючены во всех группах."
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке настроек глобального мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@group_settings_router.callback_query(F.data.startswith("toggle_global_mute_"))
async def toggle_global_mute_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Обработчик переключения глобального мута"""
    try:
        user_id = callback.from_user.id
        
        # Проверяем права: только суперадмины могут изменять глобальные настройки
        from bot.config import ADMIN_IDS
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ У вас нет прав для изменения глобальных настроек. Только суперадмины могут изменять глобальные настройки.", show_alert=True)
            return
        
        # Переключаем статус глобального мута
        from bot.services.groups_settings_in_private_logic import toggle_global_mute
        new_status = await toggle_global_mute(session)
        
        # Обновляем клавиатуру
        keyboard = create_global_mute_keyboard(new_status)
        
        status_text = "🟢 Включен" if new_status else "🔴 Выключен"
        text = (
            f"🌍 <b>Глобальный мут новых участников</b>\n\n"
            f"Текущий статус: {status_text}\n\n"
            f"Эта настройка влияет на все группы где находится бот.\n"
            f"При включении все новые участники будут автоматически замьючены во всех группах."
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
        action_text = "включен" if new_status else "выключен"
        await callback.answer(f"✅ Глобальный мут {action_text}", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при переключении глобального мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


def create_global_mute_keyboard(current_status: bool):
    """Создает клавиатуру для управления глобальным мутом"""
    toggle_text = "🔴 Выключить глобальный мут" if current_status else "🟢 Включить глобальный мут"
    toggle_action = "off" if current_status else "on"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"toggle_global_mute_{toggle_action}"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад к списку групп",
            callback_data="back_to_groups"
        )]
    ])
    
    return keyboard
