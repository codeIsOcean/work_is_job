# bot/handlers/captcha/captcha_messages.py
"""
Тексты сообщений для капчи.

Централизованное хранение всех текстов:
- Сообщения для пользователей (капча, успех, провал)
- Напоминания
- Системные уведомления

Все тексты на русском языке.
"""

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message


# Логгер для отслеживания отправки сообщений
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕКСТЫ КАПЧИ - сообщения при решении капчи
# ═══════════════════════════════════════════════════════════════════════════════

# Заголовок сообщения с капчей в ЛС
# {group_name} - название группы
CAPTCHA_DM_TITLE = """
🔐 <b>Подтвердите, что вы не бот</b>

Для входа в группу «<b>{group_name}</b>» решите капчу.

Выберите правильный ответ из вариантов ниже или введите его текстом.
"""

# Приглашение пройти капчу через deep link (отправляется в ЛС при join request)
# {group_name} - название группы
CAPTCHA_DEEP_LINK_INVITE = """
🔐 <b>Проверка для входа в группу</b>

Для входа в «<b>{group_name}</b>» нужно пройти капчу.

Нажмите кнопку ниже чтобы начать.
"""

# Кнопка "Пройти капчу" (deep link в ЛС)
CAPTCHA_START_BUTTON = "🔓 Пройти капчу"

# Заголовок сообщения с капчей в группе (для Join Captcha)
# {user_mention} - упоминание пользователя
CAPTCHA_GROUP_TITLE = """
🔐 <b>{user_mention}, подтвердите что вы не бот</b>

Нажмите кнопку ниже чтобы пройти проверку.
"""

# Сообщение в группе с deep link (для Join Captcha в открытых группах)
# {user_mention} - упоминание пользователя
CAPTCHA_GROUP_DEEP_LINK = """
🔐 {user_mention}, для участия в группе пройдите проверку.

Нажмите кнопку ниже чтобы начать.
"""

# Кнопка "Решить капчу" в группе
# Ведёт на deep link в ЛС бота
CAPTCHA_SOLVE_BUTTON = "🔐 Решить капчу"

# Инструкция под кнопками капчи
# {timeout} - время в секундах
# {attempts} - оставшиеся попытки
CAPTCHA_INSTRUCTION = """
⏱ Время: <b>{timeout}</b> сек
🔄 Попыток осталось: <b>{attempts}</b>
"""

# Инструкция с ручным вводом
CAPTCHA_INSTRUCTION_WITH_INPUT = """
⏱ Время: <b>{timeout}</b> сек
🔄 Попыток осталось: <b>{attempts}</b>

💡 <i>Можно также ввести ответ текстом</i>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕКСТЫ УСПЕХА - когда капча пройдена
# ═══════════════════════════════════════════════════════════════════════════════

# Успешное прохождение капчи
# {group_name} - название группы
CAPTCHA_SUCCESS = """
✅ <b>Капча пройдена!</b>

Добро пожаловать в группу «<b>{group_name}</b>».
Нажмите кнопку ниже чтобы перейти в группу.
"""

# Успешное прохождение (без кнопки, если нет ссылки)
CAPTCHA_SUCCESS_NO_LINK = """
✅ <b>Капча пройдена!</b>

Вы можете войти в группу «<b>{group_name}</b>».
"""

# Кнопка перехода в группу
# {group_name} - название группы
GROUP_ENTER_BUTTON = "➡️ Войти в {group_name}"


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕКСТЫ ПРОВАЛА - когда капча не пройдена
# ═══════════════════════════════════════════════════════════════════════════════

# Неверный ответ (есть ещё попытки)
# {attempts} - оставшиеся попытки
CAPTCHA_WRONG_ANSWER = """
❌ <b>Неверный ответ</b>

Попробуйте ещё раз.
Осталось попыток: <b>{attempts}</b>
"""

# Попытки закончились
CAPTCHA_NO_ATTEMPTS = """
❌ <b>Попытки закончились</b>

Капча не пройдена. Вы не можете войти в группу.
"""

# Время вышло
# {group_name} - название группы (ссылка)
CAPTCHA_TIMEOUT = """
⏰ <b>Время вышло</b>

Капча не пройдена. Вы не можете войти в группу.

Если хотите зайти в {group_name} — перейдите в неё и подайте заявку заново.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# НАПОМИНАНИЯ - сообщения перед таймаутом
# ═══════════════════════════════════════════════════════════════════════════════

# Напоминание о капче
# {seconds_left} - оставшееся время
CAPTCHA_REMINDER = """
⏰ <b>Напоминание!</b>

Решите капчу в течение <b>{seconds_left}</b> сек, иначе время выйдет.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# СИСТЕМНЫЕ СООБЩЕНИЯ - для группы
# ═══════════════════════════════════════════════════════════════════════════════

# Пользователь прошёл капчу (анонс в группу)
# {user_mention} - упоминание пользователя
SYSTEM_CAPTCHA_PASSED = """
✅ {user_mention} прошёл проверку
"""

# Пользователь не прошёл капчу (анонс в группу)
# {user_mention} - упоминание пользователя
SYSTEM_CAPTCHA_FAILED = """
❌ {user_mention} не прошёл проверку
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ФУНКЦИИ ОТПРАВКИ СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════════

async def send_success_message(
    bot: Bot,
    user_id: int,
    group_name: str,
    group_link: Optional[str] = None,
) -> Optional[Message]:
    """
    Отправляет сообщение об успешном прохождении капчи.

    Если есть ссылка на группу - добавляет кнопку для перехода.

    Args:
        bot: Экземпляр бота для отправки
        user_id: ID пользователя которому отправить
        group_name: Название группы для отображения
        group_link: Ссылка на группу (опционально)

    Returns:
        Message если отправлено успешно, None при ошибке
    """
    try:
        # Если есть ссылка - показываем кнопку для перехода
        if group_link:
            # Формируем текст с приглашением нажать кнопку
            text = CAPTCHA_SUCCESS.format(group_name=group_name)

            # Создаём клавиатуру с кнопкой перехода в группу
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    # Текст кнопки с названием группы
                    text=GROUP_ENTER_BUTTON.format(group_name=group_name[:20]),
                    # URL кнопка - открывает ссылку на группу
                    url=group_link,
                )]
            ])
        else:
            # Нет ссылки - просто текст без кнопки
            text = CAPTCHA_SUCCESS_NO_LINK.format(group_name=group_name)
            keyboard = None

        # Отправляем сообщение пользователю в ЛС
        message = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        # Логируем успешную отправку
        logger.info(
            f"✅ [CAPTCHA_MSG] Отправлено сообщение успеха: "
            f"user_id={user_id}, group={group_name}"
        )

        return message

    except Exception as e:
        # Логируем ошибку но не падаем
        logger.error(
            f"❌ [CAPTCHA_MSG] Ошибка отправки сообщения успеха: "
            f"user_id={user_id}, error={e}"
        )
        return None


async def send_failure_message(
    bot: Bot,
    user_id: int,
    reason: str = "timeout",
    group_name: Optional[str] = None,
    group_link: Optional[str] = None,
) -> Optional[Message]:
    """
    Отправляет сообщение о провале капчи.

    Args:
        bot: Экземпляр бота для отправки
        user_id: ID пользователя
        reason: Причина провала ("timeout" или "no_attempts")
        group_name: Название группы (для timeout сообщения)
        group_link: Ссылка на группу (опционально)

    Returns:
        Message если отправлено успешно, None при ошибке
    """
    try:
        # Выбираем текст в зависимости от причины
        if reason == "timeout":
            # Формируем ссылку на группу
            if group_link and group_name:
                group_display = f"<a href='{group_link}'>{group_name}</a>"
            elif group_name:
                group_display = f"<b>{group_name}</b>"
            else:
                group_display = "группу"
            text = CAPTCHA_TIMEOUT.format(group_name=group_display)
        else:
            text = CAPTCHA_NO_ATTEMPTS

        # Отправляем сообщение
        message = await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        # Логируем отправку
        logger.info(
            f"❌ [CAPTCHA_MSG] Отправлено сообщение провала: "
            f"user_id={user_id}, reason={reason}"
        )

        return message

    except Exception as e:
        # Логируем ошибку
        logger.error(
            f"❌ [CAPTCHA_MSG] Ошибка отправки сообщения провала: "
            f"user_id={user_id}, error={e}"
        )
        return None


async def send_wrong_answer_message(
    bot: Bot,
    user_id: int,
    attempts_left: int,
) -> Optional[Message]:
    """
    Отправляет сообщение о неверном ответе.

    Args:
        bot: Экземпляр бота для отправки
        user_id: ID пользователя
        attempts_left: Сколько попыток осталось

    Returns:
        Message если отправлено успешно, None при ошибке
    """
    try:
        # Формируем текст с количеством оставшихся попыток
        text = CAPTCHA_WRONG_ANSWER.format(attempts=attempts_left)

        # Отправляем сообщение
        message = await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
        )

        # Логируем
        logger.debug(
            f"⚠️ [CAPTCHA_MSG] Неверный ответ: "
            f"user_id={user_id}, attempts_left={attempts_left}"
        )

        return message

    except Exception as e:
        logger.error(
            f"❌ [CAPTCHA_MSG] Ошибка отправки сообщения о неверном ответе: "
            f"user_id={user_id}, error={e}"
        )
        return None


async def send_reminder_message(
    bot: Bot,
    user_id: int,
    seconds_left: int,
) -> Optional[Message]:
    """
    Отправляет напоминание о необходимости решить капчу.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        seconds_left: Сколько секунд осталось

    Returns:
        Message если отправлено успешно, None при ошибке
    """
    try:
        # Формируем текст напоминания
        text = CAPTCHA_REMINDER.format(seconds_left=seconds_left)

        # Отправляем
        message = await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
        )

        # Логируем
        logger.info(
            f"🔔 [CAPTCHA_MSG] Отправлено напоминание: "
            f"user_id={user_id}, seconds_left={seconds_left}"
        )

        return message

    except Exception as e:
        logger.error(
            f"❌ [CAPTCHA_MSG] Ошибка отправки напоминания: "
            f"user_id={user_id}, error={e}"
        )
        return None


def format_captcha_instruction(
    timeout: int,
    attempts: int,
    manual_input_enabled: bool = True,
) -> str:
    """
    Форматирует инструкцию под кнопками капчи.

    Args:
        timeout: Таймаут в секундах
        attempts: Оставшиеся попытки
        manual_input_enabled: Включён ли ручной ввод

    Returns:
        Отформатированная строка инструкции
    """
    # Выбираем шаблон в зависимости от настроек
    if manual_input_enabled:
        # С подсказкой про ручной ввод
        return CAPTCHA_INSTRUCTION_WITH_INPUT.format(
            timeout=timeout,
            attempts=attempts,
        )
    else:
        # Только кнопки
        return CAPTCHA_INSTRUCTION.format(
            timeout=timeout,
            attempts=attempts,
        )


async def send_deep_link_invite(
    bot: Bot,
    user_id: int,
    group_name: str,
    deep_link: str,
) -> Optional[Message]:
    """
    Отправляет приглашение пройти капчу через deep link.

    Используется для Visual Captcha в закрытых группах.
    Пользователь должен нажать кнопку чтобы начать капчу.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        group_name: Название группы
        deep_link: URL deep link для запуска капчи

    Returns:
        Message если отправлено успешно, None при ошибке
    """
    try:
        # Формируем текст приглашения
        text = CAPTCHA_DEEP_LINK_INVITE.format(group_name=group_name)

        # Создаём клавиатуру с кнопкой deep link
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=CAPTCHA_START_BUTTON,
                url=deep_link,
            )]
        ])

        # Отправляем сообщение
        message = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        logger.info(
            f"🔗 [CAPTCHA_MSG] Отправлен deep link invite: "
            f"user_id={user_id}, group={group_name}"
        )

        return message

    except Exception as e:
        logger.error(
            f"❌ [CAPTCHA_MSG] Ошибка отправки deep link invite: "
            f"user_id={user_id}, error={e}"
        )
        return None
