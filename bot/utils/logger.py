import os
import aiohttp
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


# ==== СПЕЦИАЛЬНЫЕ ФОРМАТИРОВАННЫЕ ЛОГИ ДЛЯ TELEGRAM ====

async def send_formatted_log(message):
    """Отправляет отформатированное сообщение в канал логов в Telegram"""
    if not BOT_TOKEN or not LOG_CHANNEL_ID:
        print("❗ BOT_TOKEN или LOG_CHANNEL_ID не установлены")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": LOG_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(url, data=payload)
            if resp.status != 200:
                text = await resp.text()
                print(f"❌ Telegram API Error: {resp.status} — {text}")
        except Exception as e:
            print(f"❌ Ошибка при отправке лога в Telegram: {e}")


def log_new_user(username, user_id, chat_name, chat_id, message_id=None):
    """Отправляет лог о новом пользователе с хэштегами"""
    # Проверяем, является ли username строкой (защита от None)
    user_display = f"<a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a>"

    msg = (
        f"➕ #НОВЫЙ_ПОЛЬЗОВАТЕЛЬ 🟢\n"
        f"• Кто: {user_display} [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
    )

    if message_id:
        msg += f"• 👀 Посмотреть сообщения (http://t.me/c/{str(chat_id).replace('-100', '')}/{message_id})\n"

    msg += f"#id{user_id}"

    # Выводим в консоль для информации
    print(f"📱 Логируем нового пользователя: {username} в группе {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_captcha_solved(username, user_id, chat_name, chat_id, method="Кнопка"):
    """Отправляет лог об успешном решении капчи"""
    msg = (
        f"✅ #КАПЧА_РЕШЕНА 🟢\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"• Метод: {method}\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Капча решена пользователем: {username} в группе {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_user_banned(username, user_id, chat_name, chat_id, reason="Спам"):
    """Отправляет лог о бане пользователя"""
    msg = (
        f"🚫 #ПОЛЬЗОВАТЕЛЬ_ЗАБАНЕН 🔴\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"• Причина: {reason}\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Пользователь {username} забанен в группе {chat_name}: {reason}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_join_request(username, user_id, chat_name, chat_id):
    """Отправляет лог о запросе на вступление в группу"""
    msg = (
        f"📬 #ЗАПРОС_НА_ВСТУПЛЕНИЕ 🔵\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Запрос на вступление от {username} в группу {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_captcha_failed(username, user_id, chat_name, chat_id, method="Кнопка"):
    """Отправляет лог о неудачной попытке решения капчи"""
    msg = (
        f"📬 #ЗАПРОС_НА_ВСТУПЛЕНИЕ 🔴 #капчанерешена\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id} #КАПЧА_НЕ_УДАЛАСЬ #{method}"
    )

    # Выводим в консоль для информации
    print(f"📱 Капча не решена пользователем: {username} в группе {chat_name}, метод: {method}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))

def log_captcha_sent(username, user_id, chat_name, chat_id):
    """Отправляет лог об отправке капчи пользователю"""
    msg = (
        f"📢 #КАПЧА_ОТПРАВЛЕНА 🟡\n"
        f"• Кому: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Отправлена капча пользователю: {username} для входа в группу {chat_id}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_telegram_error(error_message, module_name="Не указан"):
    """Отправляет лог об ошибке Telegram API"""
    msg = (
        f"❌ #ОШИБКА_TELEGRAM 🔴\n"
        f"• Модуль: {module_name}\n"
        f"• Описание: {error_message}\n"
        f"#error #telegram_api"
    )

    # Выводим в консоль для информации
    print(f"📱 Ошибка Telegram API: {error_message}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_captcha_attempt_with_buttons(username, user_id, chat_name, chat_id, risk_score, risk_factors, method="Капча"):
    """Отправляет лог о попытке прохождения капчи с кнопками управления"""
    user_display = f"<a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a>"
    
    # Определяем уровень риска
    if risk_score >= 80:
        risk_level = "🚨 ВЫСОКИЙ"
        risk_color = "🔴"
    elif risk_score >= 50:
        risk_level = "⚠️ СРЕДНИЙ"
        risk_color = "🟡"
    elif risk_score >= 30:
        risk_level = "ℹ️ УМЕРЕННЫЙ"
        risk_color = "🟠"
    else:
        risk_level = "✅ НИЗКИЙ"
        risk_color = "🟢"
    
    # Формируем факторы риска (максимум 3)
    factors_text = ", ".join(risk_factors[:3])
    if len(risk_factors) > 3:
        factors_text += f" и еще {len(risk_factors) - 3}"
    
    # Безопасное создание ссылки на группу
    if chat_id < 0:
        # Для групп убираем -100 и создаем ссылку
        group_link_id = str(chat_id).replace('-100', '')
        group_link = f"https://t.me/c/{group_link_id}"
    else:
        # Для каналов и других чатов
        group_link = f"https://t.me/c/{chat_id}"
    
    msg = (
        f"🧩 #ПОПЫТКА_КАПЧИ {risk_color}\n"
        f"• Кто: {user_display} [{user_id}]\n"
        f"• Группа: <a href='{group_link}'>{chat_name}</a> [{chat_id}]\n"
        f"• Уровень риска: {risk_level} ({risk_score}/100)\n"
        f"• Факторы: {factors_text}\n"
        f"• Метод: {method}\n"
        f"#id{user_id} #капча #риск{risk_score}"
    )

    # Выводим в консоль для информации
    print(f"📱 Попытка капчи от {username} в группе {chat_name}, риск: {risk_score}/100")
    # Создаем задачу для асинхронной отправки в Telegram с кнопками
    asyncio.create_task(send_captcha_attempt_log_with_buttons(msg, user_id, chat_id, risk_score))


async def send_captcha_attempt_log_with_buttons(message: str, user_id: int, chat_id: int, risk_score: int):
    """Отправляет лог о попытке капчи с кнопками управления"""
    if not BOT_TOKEN or not LOG_CHANNEL_ID:
        print("❗ BOT_TOKEN или LOG_CHANNEL_ID не установлены")
        return

    # Проверяем валидность параметров
    if not user_id or not chat_id:
        print(f"❗ Некорректные параметры: user_id={user_id}, chat_id={chat_id}")
        return

    import aiohttp
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    # Создаем кнопки управления с проверкой параметров
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Разрешить доступ",
                    callback_data=f"admin_allow:{int(user_id)}:{int(chat_id)}"
                ),
                InlineKeyboardButton(
                    text="🔇 Замутить навсегда",
                    callback_data=f"admin_mute:{int(user_id)}:{int(chat_id)}"
                )
            ]
        ])
    except (ValueError, TypeError) as e:
        print(f"❗ Ошибка создания кнопок: {e}")
        return
    
    # Убираем кнопку блокировки - теперь только автомут

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": LOG_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": keyboard.model_dump(exclude_none=True)  # ФИКС: exclude_none=True чтобы исключить url: null
    }

    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(url, json=payload)
            if resp.status != 200:
                text = await resp.text()
                print(f"❌ Telegram API Error: {resp.status} — {text}")
        except Exception as e:
            print(f"❌ Ошибка при отправке лога с кнопками в Telegram: {e}")