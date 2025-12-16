# bot/services/captcha/dm_flow_service.py
"""
Сервис логики капчи в ЛС (Direct Message).

Отвечает за:
- Создание deep link для перехода в ЛС бота
- Отправку капчи в ЛС пользователю
- Сообщение успеха с кнопкой перехода в группу
- Работу с Redis для хранения состояния join request

Перенесено из visual_captcha_logic.py и visual_captcha_handler.py
"""

import asyncio
import logging
import random
from io import BytesIO
from typing import Optional, Tuple, Dict, Any

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    Chat,
    User,
    Message,
)
from aiogram.utils.deep_linking import create_start_link
from aiogram.fsm.context import FSMContext
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.redis_conn import redis
from bot.handlers.captcha.captcha_messages import (
    CAPTCHA_DM_TITLE,
    CAPTCHA_SOLVE_BUTTON,
    send_success_message,
)


# Логгер для отслеживания работы сервиса
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ REDIS КЛЮЧЕЙ
# ═══════════════════════════════════════════════════════════════════════════════

# Ключ для хранения данных join request
# Формат: join_request:{user_id}:{chat_id}
JOIN_REQUEST_KEY = "join_request:{user_id}:{chat_id}"

# Ключ для хранения данных капчи пользователя
# ВАЖНО: Формат должен совпадать с cleanup_service.py!
# Формат: captcha:data:{user_id}:{chat_id}
CAPTCHA_DATA_KEY = "captcha:data:{user_id}:{chat_id}"

# Ключ для хранения ID сообщений капчи (для последующего удаления)
# Формат: captcha_messages:{user_id}
CAPTCHA_MESSAGES_KEY = "captcha_messages:{user_id}"

# TTL для данных капчи (10 минут)
CAPTCHA_DATA_TTL = 600

# TTL для join request (10 минут)
JOIN_REQUEST_TTL = 600


# ═══════════════════════════════════════════════════════════════════════════════
# КЭШИРОВАНИЕ ШРИФТОВ
# ═══════════════════════════════════════════════════════════════════════════════

# Глобальный кэш шрифтов для генерации капчи
_FONT_CACHE = None


def _load_fonts_cached():
    """
    Загружает шрифты один раз и кэширует результат.

    Оптимизировано для Windows (первым проверяется Windows путь).

    Returns:
        Список шрифтов разных размеров
    """
    global _FONT_CACHE

    # Если шрифты уже загружены - возвращаем из кэша
    if _FONT_CACHE is not None:
        return _FONT_CACHE

    # Пути к шрифтам в порядке приоритета
    font_paths = [
        # Windows первым (бот работает на Windows)
        "C:\\Windows\\Fonts\\arial.ttf",
        # Linux шрифты
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Arial.ttf",
        # Относительные пути
        "arial.ttf",
        "Arial.ttf",
    ]

    # Пробуем загрузить шрифты из каждого пути
    for path in font_paths:
        try:
            # Загружаем шрифты разных размеров для вариативности
            fonts = [ImageFont.truetype(path, size) for size in (120, 130, 140, 150)]
            logger.info(f"✅ [FONT] Загружен шрифт: {path}")
            _FONT_CACHE = fonts
            return fonts
        except (IOError, OSError):
            # Шрифт не найден - пробуем следующий
            continue

    # Fallback на стандартный шрифт PIL
    logger.warning("⚠️ [FONT] Системные шрифты не найдены, используем стандартный")
    default_font = ImageFont.load_default()
    _FONT_CACHE = [default_font] * 4
    return _FONT_CACHE


# ═══════════════════════════════════════════════════════════════════════════════
# DEEP LINK ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════════

async def create_captcha_deep_link(
    bot: Bot,
    chat_id: int,
    user_id: int,
    chat_username: Optional[str] = None,
) -> str:
    """
    Создаёт deep link для перехода в ЛС бота для прохождения капчи.

    Формат deep link: t.me/bot_username?start=captcha_{user_id}_{chat_id}

    ВАЖНО: user_id включён в deep link для защиты от чужих пользователей!
    В FSM handler проверяется что from_user.id совпадает с user_id из deep link.

    Args:
        bot: Экземпляр бота
        chat_id: ID группы (числовой)
        user_id: ID пользователя для которого капча
        chat_username: Username группы (не используется в новом формате)

    Returns:
        URL deep link для перехода в ЛС бота
    """
    # Создаём deep link через утилиту aiogram
    # Формат: captcha_{user_id}_{chat_id}
    # user_id нужен для проверки владельца
    # chat_id нужен для получения настроек и сохранения данных
    deep_link = await create_start_link(
        bot=bot,
        payload=f"captcha_{user_id}_{chat_id}",
    )

    # Логируем создание
    logger.debug(
        f"🔗 [DEEP_LINK] Создан: user_id={user_id}, chat_id={chat_id}, link={deep_link}"
    )

    return deep_link


def build_solve_captcha_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой "Решить капчу" для сообщения в группе.

    Кнопка ведёт на deep link в ЛС бота.

    Args:
        deep_link: URL для перехода в ЛС

    Returns:
        InlineKeyboardMarkup с одной URL кнопкой
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            # Текст кнопки из констант
            text=CAPTCHA_SOLVE_BUTTON,
            # URL кнопка - открывает deep link
            url=deep_link,
        )]
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS ФУНКЦИИ - JOIN REQUEST
# ═══════════════════════════════════════════════════════════════════════════════

async def save_join_request(
    user_id: int,
    chat_id: int,
    group_id: str,
) -> None:
    """
    Сохраняет данные join request в Redis.

    Используется для последующего approve после прохождения капчи.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
        group_id: Идентификатор группы (username или private_{id})
    """
    # Формируем ключ Redis
    key = JOIN_REQUEST_KEY.format(user_id=user_id, chat_id=chat_id)

    # Сохраняем с TTL
    await redis.setex(
        key,
        JOIN_REQUEST_TTL,
        group_id,
    )

    # Логируем сохранение
    logger.debug(
        f"💾 [JOIN_REQUEST] Сохранён: user_id={user_id}, chat_id={chat_id}"
    )


async def get_join_request(
    user_id: int,
    chat_id: int,
) -> Optional[str]:
    """
    Получает данные join request из Redis.

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        group_id если найден, None если нет или истёк
    """
    # Формируем ключ Redis
    key = JOIN_REQUEST_KEY.format(user_id=user_id, chat_id=chat_id)

    # Получаем значение
    result = await redis.get(key)

    return result


async def delete_join_request(
    user_id: int,
    chat_id: int,
) -> None:
    """
    Удаляет данные join request из Redis.

    Вызывается после approve/decline или по таймауту.

    Args:
        user_id: ID пользователя
        chat_id: ID группы
    """
    # Формируем ключ Redis
    key = JOIN_REQUEST_KEY.format(user_id=user_id, chat_id=chat_id)

    # Удаляем ключ
    await redis.delete(key)

    # Логируем удаление
    logger.debug(
        f"🗑️ [JOIN_REQUEST] Удалён: user_id={user_id}, chat_id={chat_id}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS ФУНКЦИИ - CAPTCHA DATA
# ═══════════════════════════════════════════════════════════════════════════════

async def save_captcha_data(
    user_id: int,
    correct_answer: str,
    group_id: str,
    chat_id: int,
    attempts_left: int,
    mode: str = "visual_dm",
    options: list = None,
) -> None:
    """
    Сохраняет данные активной капчи в Redis.

    ВАЖНО: Формат ключа должен совпадать с cleanup_service.py!
    Ключ: captcha:data:{user_id}:{chat_id}

    Args:
        user_id: ID пользователя
        correct_answer: Правильный ответ на капчу
        group_id: Идентификатор группы
        chat_id: Числовой ID группы
        attempts_left: Оставшиеся попытки
        mode: Режим капчи (visual_dm, join_group, invite_group)
        options: Список опций с хэшами [{text, hash, is_correct}]
    """
    import json
    import hashlib

    # Формируем ключ Redis - ОБЯЗАТЕЛЬНО включаем chat_id!
    key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)

    # Определяем правильный хэш
    # ВАЖНО: Используем хэш из options (как в кнопках) если есть,
    # иначе вычисляем напрямую (без .lower() для чисел)
    if options:
        # Находим правильную опцию
        correct_option = next(
            (opt for opt in options if opt.get("is_correct")),
            None
        )
        if correct_option:
            correct_hash = correct_option["hash"]
        else:
            # Fallback: вычисляем хэш напрямую как в generate_visual_captcha
            correct_hash = hashlib.md5(str(correct_answer).encode()).hexdigest()[:8]
    else:
        # Для обратной совместимости: вычисляем хэш напрямую
        correct_hash = hashlib.md5(str(correct_answer).encode()).hexdigest()[:8]

    # Данные для сохранения
    data = {
        # Правильный ответ (для FSM текстового ввода)
        "correct_answer": correct_answer,
        # Хэш ответа (для callback кнопок)
        "correct_hash": correct_hash,
        # Идентификатор группы (username или private_{id})
        "group_id": group_id,
        # Числовой ID группы
        "chat_id": chat_id,
        # Оставшиеся попытки
        "attempts_left": attempts_left,
        # Режим капчи
        "mode": mode,
    }

    # Сохраняем как JSON с TTL
    await redis.setex(
        key,
        CAPTCHA_DATA_TTL,
        json.dumps(data),
    )

    # Логируем с хэшем для отладки
    logger.info(
        f"💾 [CAPTCHA_DATA] Сохранены данные: "
        f"user_id={user_id}, chat_id={chat_id}, mode={mode}, "
        f"correct_hash={correct_hash}"
    )


async def get_captcha_data(user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает данные активной капчи из Redis.

    ВАЖНО: Требуется и user_id и chat_id для формирования ключа!
    Ключ: captcha:data:{user_id}:{chat_id}

    Args:
        user_id: ID пользователя
        chat_id: ID группы

    Returns:
        Словарь с данными капчи или None если нет/истекла
    """
    import json

    # Формируем ключ Redis - ОБЯЗАТЕЛЬНО включаем chat_id!
    key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)

    # Получаем значение
    result = await redis.get(key)

    # Если нет данных - возвращаем None
    if not result:
        logger.debug(
            f"🔍 [CAPTCHA_DATA] Данные не найдены: user_id={user_id}, chat_id={chat_id}"
        )
        return None

    # Парсим JSON
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        logger.warning(
            f"⚠️ [CAPTCHA_DATA] Ошибка парсинга JSON: "
            f"user_id={user_id}, chat_id={chat_id}"
        )
        return None


async def update_captcha_attempts(
    user_id: int,
    chat_id: int,
    attempts_left: int,
) -> None:
    """
    Обновляет количество оставшихся попыток.

    Args:
        user_id: ID пользователя
        chat_id: ID группы (нужен для формирования ключа)
        attempts_left: Новое количество попыток
    """
    # Получаем текущие данные
    data = await get_captcha_data(user_id, chat_id)

    if data:
        # Обновляем попытки
        data["attempts_left"] = attempts_left

        # Сохраняем обратно
        import json
        # Формируем ключ с chat_id
        key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)
        # Получаем TTL текущего ключа чтобы не сбросить его
        ttl = await redis.ttl(key)
        if ttl > 0:
            await redis.setex(key, ttl, json.dumps(data))


async def delete_captcha_data(user_id: int, chat_id: int) -> None:
    """
    Удаляет данные капчи из Redis.

    Вызывается после успешного прохождения или провала.

    Args:
        user_id: ID пользователя
        chat_id: ID группы (нужен для формирования ключа)
    """
    # Формируем ключ Redis с chat_id
    key = CAPTCHA_DATA_KEY.format(user_id=user_id, chat_id=chat_id)

    # Удаляем ключ
    await redis.delete(key)

    # Логируем
    logger.debug(
        f"🗑️ [CAPTCHA_DATA] Удалены данные: user_id={user_id}, chat_id={chat_id}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS ФУНКЦИИ - CAPTCHA MESSAGES
# ═══════════════════════════════════════════════════════════════════════════════

async def save_captcha_message_id(
    user_id: int,
    message_id: int,
) -> None:
    """
    Добавляет ID сообщения капчи в список для последующего удаления.

    Args:
        user_id: ID пользователя
        message_id: ID сообщения
    """
    # Формируем ключ Redis
    key = CAPTCHA_MESSAGES_KEY.format(user_id=user_id)

    # Добавляем ID в список (RPUSH)
    await redis.rpush(key, str(message_id))

    # Устанавливаем TTL если ключ новый
    await redis.expire(key, CAPTCHA_DATA_TTL)


async def get_captcha_message_ids(user_id: int) -> list[int]:
    """
    Получает список ID сообщений капчи.

    Args:
        user_id: ID пользователя

    Returns:
        Список ID сообщений
    """
    # Формируем ключ Redis
    key = CAPTCHA_MESSAGES_KEY.format(user_id=user_id)

    # Получаем все элементы списка
    result = await redis.lrange(key, 0, -1)

    # Конвертируем в int
    return [int(mid) for mid in result if mid]


async def delete_captcha_message_ids(user_id: int) -> None:
    """
    Удаляет список ID сообщений капчи.

    Args:
        user_id: ID пользователя
    """
    # Формируем ключ Redis
    key = CAPTCHA_MESSAGES_KEY.format(user_id=user_id)

    # Удаляем ключ
    await redis.delete(key)


# ═══════════════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КАПЧИ
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_visual_captcha(
    button_count: int = 6,
) -> Tuple[str, BufferedInputFile, list[dict]]:
    """
    Генерирует визуальную капчу с изображением и вариантами ответов.

    Args:
        button_count: Количество вариантов ответов (4, 6, 9)

    Returns:
        Tuple из:
        - correct_answer: Правильный ответ (строка)
        - captcha_image: Изображение капчи (BufferedInputFile)
        - options: Список вариантов [{text, hash, is_correct}]
    """
    # Размеры изображения
    width, height = 1200, 500
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    # Загружаем кэшированные шрифты
    try:
        fonts = _load_fonts_cached()
    except Exception as e:
        logger.error(f"❌ [CAPTCHA] Ошибка загрузки шрифтов: {e}")
        fonts = [ImageFont.load_default()]

    # Генерируем тип капчи (числа или простая математика)
    captcha_type = random.choices(
        ["simple_number", "simple_math"],
        weights=[50, 50],  # 50% числа, 50% математика
    )[0]

    if captcha_type == "simple_number":
        # Простые числа от 1 до 20
        answer = random.randint(1, 20)
        text_to_draw = str(answer)
        correct_answer = str(answer)
    else:
        # Простая математика: сложение/вычитание
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        op = random.choice(["+", "-"])
        if op == "+":
            answer = a + b
            text_to_draw = f"{a} + {b}"
        else:
            # Для вычитания - результат положительный
            if a < b:
                a, b = b, a
            answer = a - b
            text_to_draw = f"{a} - {b}"
        correct_answer = str(answer)

    # ═══════════════════════════════════════════════════════════════════════
    # Рисуем фон с градиентом
    # ═══════════════════════════════════════════════════════════════════════
    for y in range(height):
        for x in range(width):
            intensity = int(255 - (y / height) * 20)
            img.putpixel((x, y), (intensity, intensity, intensity))

    # Добавляем горизонтальные полосы
    for _ in range(8):
        y = random.randint(0, height - 1)
        color = (
            random.randint(200, 240),
            random.randint(200, 240),
            random.randint(200, 240),
        )
        d.line([(0, y), (width, y)], fill=color, width=random.randint(2, 5))

    # Добавляем линии шума
    for _ in range(25):
        x1, y1 = random.randint(0, width - 1), random.randint(0, height - 1)
        x2, y2 = random.randint(0, width - 1), random.randint(0, height - 1)
        color = (
            random.randint(120, 200),
            random.randint(120, 200),
            random.randint(120, 200),
        )
        d.line([(x1, y1), (x2, y2)], fill=color, width=random.randint(1, 4))

    # Добавляем точечный шум
    for _ in range(1500):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = (
            random.randint(200, 255),
            random.randint(200, 255),
            random.randint(200, 255),
        )
        img.putpixel((x, y), color)

    # ═══════════════════════════════════════════════════════════════════════
    # Рисуем текст капчи
    # ═══════════════════════════════════════════════════════════════════════
    spacing = width // (len(text_to_draw) + 2)
    x_offset = spacing

    for ch in text_to_draw:
        # Угол поворота ±30 градусов
        angle = random.randint(-30, 30)

        # Выбираем случайный шрифт
        font = random.choice(fonts) if fonts else ImageFont.load_default()

        # Создаём временное изображение для символа
        char_size = 200
        char_img = Image.new("RGBA", (char_size, char_size), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_img)

        # Рисуем символ чёрным цветом
        char_draw.text(
            (char_size // 4, char_size // 4),
            ch,
            font=font,
            fill=(0, 0, 0, 255),
        )

        # Поворачиваем
        char_img = char_img.rotate(angle, expand=True, fillcolor=(255, 255, 255, 0))

        # Вставляем на основное изображение
        y_offset = (height - char_img.height) // 2
        img.paste(char_img, (x_offset, y_offset), char_img)

        x_offset += spacing

    # ═══════════════════════════════════════════════════════════════════════
    # Конвертируем в BufferedInputFile
    # ═══════════════════════════════════════════════════════════════════════
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    captcha_image = BufferedInputFile(
        file=buffer.read(),
        filename="captcha.png",
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Генерируем варианты ответов для кнопок
    # ═══════════════════════════════════════════════════════════════════════
    import hashlib

    # Правильный ответ как число
    correct_int = int(correct_answer)

    # Генерируем неправильные варианты
    wrong_answers = set()
    while len(wrong_answers) < button_count - 1:
        # Генерируем числа в диапазоне ±10 от правильного
        wrong = correct_int + random.randint(-10, 10)
        # Не допускаем отрицательные и дубликаты
        if wrong > 0 and wrong != correct_int and wrong not in wrong_answers:
            wrong_answers.add(wrong)

    # Собираем все варианты
    all_answers = [correct_int] + list(wrong_answers)
    random.shuffle(all_answers)

    # Формируем список опций с хэшами
    options = []
    for ans in all_answers:
        # Создаём хэш для callback_data
        ans_hash = hashlib.md5(str(ans).encode()).hexdigest()[:8]
        options.append({
            "text": str(ans),
            "hash": ans_hash,
            "is_correct": ans == correct_int,
        })

    # Логируем генерацию (без ответа!)
    logger.info(
        f"🎨 [CAPTCHA] Сгенерирована капча: type={captcha_type}, "
        f"options={button_count}"
    )

    return correct_answer, captcha_image, options


# ═══════════════════════════════════════════════════════════════════════════════
# ПОЛУЧЕНИЕ ССЫЛКИ НА ГРУППУ
# ═══════════════════════════════════════════════════════════════════════════════

async def get_group_link(
    bot: Bot,
    chat_id: int,
    chat_username: Optional[str] = None,
) -> Optional[str]:
    """
    Получает ссылку на группу для кнопки "Войти в группу".

    Приоритет:
    1. Если есть username → t.me/username
    2. Иначе создаём invite link

    Args:
        bot: Экземпляр бота
        chat_id: ID группы
        chat_username: Username группы (если публичная)

    Returns:
        URL ссылки на группу или None при ошибке
    """
    # Если есть username - формируем прямую ссылку
    if chat_username:
        return f"https://t.me/{chat_username}"

    # Иначе пробуем создать invite link
    try:
        # Создаём одноразовую ссылку
        invite_link = await bot.create_chat_invite_link(
            chat_id=chat_id,
            # Ссылка для одного использования
            member_limit=1,
        )
        return invite_link.invite_link
    except Exception as e:
        logger.warning(
            f"⚠️ [GROUP_LINK] Не удалось создать invite link: "
            f"chat_id={chat_id}, error={e}"
        )
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ОЧИСТКА СОСТОЯНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

async def clear_captcha_state(
    bot: Bot,
    user_id: int,
    chat_id: int,
    state: Optional[FSMContext] = None,
) -> None:
    """
    Полностью очищает состояние капчи.

    Удаляет:
    - Данные капчи из Redis
    - Данные join request из Redis
    - ID сообщений из Redis
    - FSM состояние (если передан)

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        chat_id: ID группы
        state: FSM контекст (опционально)
    """
    # Получаем ID сообщений для удаления
    message_ids = await get_captcha_message_ids(user_id)

    # Пытаемся удалить сообщения
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            # Сообщение уже удалено или недоступно
            pass

    # Удаляем данные из Redis (с chat_id для правильного ключа)
    await delete_captcha_data(user_id, chat_id)
    await delete_join_request(user_id, chat_id)
    await delete_captcha_message_ids(user_id)

    # Очищаем FSM если передан
    if state:
        await state.clear()

    # Логируем очистку
    logger.info(
        f"🧹 [CLEANUP] Очищено состояние капчи: "
        f"user_id={user_id}, chat_id={chat_id}"
    )
