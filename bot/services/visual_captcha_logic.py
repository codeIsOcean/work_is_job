# services/visual_captcha_logic.py
import asyncio
import random
import logging
import re
from io import BytesIO
from typing import Dict, Optional, Any, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.deep_linking import create_start_link
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.redis_conn import redis
from bot.database.models import CaptchaSettings, User, ScammerTracker
from datetime import datetime, timedelta
import time
from bot.services.enhanced_profile_analyzer import enhanced_profile_analyzer

logger = logging.getLogger(__name__)


async def generate_visual_captcha() -> Tuple[str, BufferedInputFile]:
    """Генерация улучшенной визуальной капчи с защитой от ботов."""
    width, height = 1200, 500  # Увеличиваем размер для более сложных искажений
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    # Создаем крупный шрифт программно
    try:
        # Пробуем загрузить системные шрифты
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 
            "/System/Library/Fonts/Arial.ttf",  # macOS
            "C:\\Windows\\Fonts\\arial.ttf",  # Windows
            "arial.ttf",
            "Arial.ttf"
        ]
        
        fonts = []
        logger.info(f"🔍 [DEBUG] Начинаем загрузку шрифтов из {len(font_paths)} путей")
        
        for i, path in enumerate(font_paths):
            logger.info(f"🔍 [DEBUG] Попытка {i+1}/{len(font_paths)}: {path}")
            try:
                fonts = [ImageFont.truetype(path, size) for size in (120, 130, 140, 150)]  # Еще крупнее
                logger.info(f"✅ Успешно загружен шрифт: {path}, создано {len(fonts)} вариантов")
                break
            except (IOError, OSError) as e:
                logger.info(f"❌ Не удалось загрузить {path}: {e}")
                continue
        
        logger.info(f"🔍 [DEBUG] Результат загрузки: fonts={len(fonts) if fonts else 0}")
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА
        if not fonts or len(fonts) == 0:
            logger.warning("⚠️ Не удалось загрузить ни один системный шрифт")
            default_font = ImageFont.load_default()
            fonts = [default_font] * 4  # Создаем 4 копии
            logger.info(f"🔍 [DEBUG] Создан массив из стандартных шрифтов: {len(fonts)}")
        
        
            
    except Exception as e:
        logger.error(f"Ошибка создания шрифта: {e}")
        fonts = [ImageFont.load_default()]

    # Упрощаем капчу - делаем только простые и читаемые варианты
    captcha_type = random.choices(
        ["simple_number", "simple_math", "simple_text"], 
        weights=[40, 40, 20]  # 40% простые числа, 40% простая математика, 20% простой текст
    )[0]

    if captcha_type == "simple_number":
        # Простые числа от 1 до 20
        answer = str(random.randint(1, 20))
        text_to_draw = answer
    elif captcha_type == "simple_math":
        # Простая математика: только сложение и вычитание с маленькими числами
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        op = random.choice(["+", "-"])
        if op == "+":
            answer = str(a + b)
            text_to_draw = f"{a} + {b}"
        else:  # вычитание
            if a < b:
                a, b = b, a  # чтобы результат был положительным
            answer = str(a - b)
            text_to_draw = f"{a} - {b}"
    else:  # simple_text - простой текст из 3-4 символов
        # Используем только четкие символы без похожих букв
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        answer = "".join(random.choice(chars) for _ in range(3))  # только 3 символа
        text_to_draw = answer

    # Создаем сложный фон с градиентом
    for y in range(height):
        for x in range(width):
            # Создаем градиент от белого к светло-серому
            intensity = int(255 - (y / height) * 20)
            img.putpixel((x, y), (intensity, intensity, intensity))

    # Добавляем цветные полосы для усложнения
    for _ in range(8):
        y = random.randint(0, height - 1)  # Исправлено: height-1 вместо height
        d.line([(0, y), (width, y)],
               fill=(random.randint(200, 240), random.randint(200, 240), random.randint(200, 240)),
               width=random.randint(2, 5))

    # Сложные фоновые линии с разными углами
    for _ in range(25):
        x1, y1 = random.randint(0, width - 1), random.randint(0, height - 1)  # Исправлено
        x2, y2 = random.randint(0, width - 1), random.randint(0, height - 1)  # Исправлено
        # Разные цвета для линий
        color = (random.randint(120, 200), random.randint(120, 200), random.randint(120, 200))
        d.line([(x1, y1), (x2, y2)], fill=color, width=random.randint(1, 4))

    # Увеличиваем количество точечного шума
    for _ in range(1500):
        x = random.randint(0, width - 1)  # Исправлено: width-1 вместо width
        y = random.randint(0, height - 1)  # Исправлено: height-1 вместо height
        color = (random.randint(200, 255), random.randint(200, 255), random.randint(200, 255))
        img.putpixel((x, y), color)

    # Добавляем более сложные кривые линии
    for _ in range(5):
        points = []
        for i in range(8):
            x = i * width // 7
            y = random.randint(height // 3, 2 * height // 3)
            points.append((x, y))
        color = (random.randint(170, 230), random.randint(170, 230), random.randint(170, 230))
        d.line(points, fill=color, width=random.randint(1, 3))

    # Добавляем цветовые искажения
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            # Добавляем случайные цветовые сдвиги
            if random.random() < 0.1:  # 10% пикселей
                r = min(255, r + random.randint(-30, 30))
                g = min(255, g + random.randint(-30, 30))
                b = min(255, b + random.randint(-30, 30))
                pixels[x, y] = (max(0, r), max(0, g), max(0, b))

    # Посимвольный вывод с искажениями для защиты от ботов
    spacing = width // (len(text_to_draw) + 2)
    x_offset = spacing
    
    logger.info(f"🔍 [DEBUG] Начинаем отрисовку текста: '{text_to_draw}', длина={len(text_to_draw)}")
    logger.info(f"🔍 [DEBUG] Массив шрифтов: длина={len(fonts)}, содержимое={[str(f) for f in fonts[:2]]}")
    
    for i, ch in enumerate(text_to_draw):
        logger.info(f"🔍 [DEBUG] Обрабатываем символ {i+1}/{len(text_to_draw)}: '{ch}'")
        
        # Угол поворота до ±30 градусов (уменьшили для читаемости)
        angle = random.randint(-30, 30)
        
        # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА
        if not fonts or len(fonts) == 0:
            logger.error("❌ Критическая ошибка: массив шрифтов пуст!")
            default_font = ImageFont.load_default()
            fonts = [default_font] * 4
        
        # Безопасный выбор шрифта в цикле
        try:
            logger.info(f"🔍 [DEBUG] Выбираем шрифт из массива длиной {len(fonts)}")
            if fonts and len(fonts) > 0:
                font = random.choice(fonts)
                logger.info(f"🔍 [DEBUG] Выбран шрифт: {font}")
            else:
                font = ImageFont.load_default()
                logger.info(f"🔍 [DEBUG] Используем стандартный шрифт")
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка при выборе шрифта: {e}")
            font = ImageFont.load_default()

        char_img = Image.new("RGBA", (250, 300), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_img)
        
        # Используем разные цвета для символов
        if i % 2 == 0:
            color = (random.randint(10, 60), random.randint(10, 60), random.randint(10, 60))
        else:
            color = (random.randint(40, 90), random.randint(40, 90), random.randint(40, 90))

        # Рисуем текст с отступом
        char_draw.text((25, 25), ch, font=font, fill=color)
        
        # Масштабируем если нужно
        if font == ImageFont.load_default():
            char_img = char_img.resize((750, 900), Image.Resampling.LANCZOS)
        
        # Применяем поворот
        rotated = char_img.rotate(angle, expand=1, fillcolor=(255, 255, 255, 0))
        
        # Случайное позиционирование
        y_pos = random.randint(height // 4, height // 2)
        img.paste(rotated, (x_offset, y_pos), rotated)
        x_offset += spacing + random.randint(-20, 20)

    # Добавляем искажающие линии поверх текста
    for _ in range(8):
        start_y = random.randint(height // 5, 4 * height // 5)
        end_y = random.randint(height // 5, 4 * height // 5)
        # Разные цвета и толщина линий
        color = (random.randint(150, 220), random.randint(150, 220), random.randint(150, 220))
        d.line([(0, start_y), (width, end_y)], fill=color, width=random.randint(2, 4))
    
    # Добавляем волнообразные линии
    for _ in range(5):
        points = []
        for i in range(8):
            x = i * width // 7
            y = random.randint(height // 3, 2 * height // 3)
            points.append((x, y))
        color = (random.randint(170, 230), random.randint(170, 230), random.randint(170, 230))
        d.line(points, fill=color, width=random.randint(1, 3))

    # В байты
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    file = BufferedInputFile(img_byte_arr.getvalue(), filename="captcha.png")
    
    logger.info(f"✅ Капча успешно сгенерирована: тип={captcha_type}, ответ={answer}, шрифтов={len(fonts)}")
    return answer, file


async def create_group_invite_link(bot: Bot, group_name: str) -> str:
    """Создаёт start deep-link для капчи (на саму группу это НЕ ссылка)."""
    return await create_start_link(bot, f"deep_link_{group_name}")


async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: float):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        if "message to delete not found" in str(e).lower():
            return
        logger.error(f"Не удалось удалить сообщение {message_id}: {e}")


async def send_captcha_reminder(bot: Bot, chat_id: int, user_id: int, group_name: str) -> Optional[int]:
    """Отправляет напоминание о необходимости решить капчу через 2-3 минуты."""
    try:
        # Получаем информацию о группе для красивого сообщения
        group_display_name = group_name.replace("_", " ").title()
        group_link = None
        
        if group_name.startswith("private_"):
            try:
                chat_id_for_name = int(group_name.replace("private_", ""))
                chat = await bot.get_chat(chat_id_for_name)
                group_display_name = chat.title
                # Для приватных групп создаем инвайт-ссылку
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id_for_name,
                    name=f"Reminder for user {user_id}",
                    creates_join_request=False,
                )
                # Преобразуем invite.invite_link в строку явно
                group_link = str(invite.invite_link) if invite.invite_link else None
            except Exception:
                pass
        elif group_name.startswith("-") and group_name[1:].isdigit():
            try:
                chat_id_for_name = int(group_name)
                chat = await bot.get_chat(chat_id_for_name)
                group_display_name = chat.title
                if chat.username:
                    group_link = f"https://t.me/{chat.username}"
                else:
                    # Для приватных групп создаем инвайт-ссылку
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id_for_name,
                        name=f"Reminder for user {user_id}",
                        creates_join_request=False,
                    )
                    # Преобразуем invite.invite_link в строку явно  
                    group_link = str(invite.invite_link) if invite.invite_link else None
            except Exception:
                pass
        else:
            # Публичная группа по username
            group_link = f"https://t.me/{group_name}"
        
        # Формируем текст с ссылкой на группу
        if group_link:
            reminder_text = (
                f"⏰ <b>Напоминание о капче</b>\n\n"
                f"Вы не решили капчу для вступления в группу <a href='{group_link}'>{group_display_name}</a>.\n"
                f"Пожалуйста, решите капчу в течение следующих 2 минут, иначе ваш запрос будет отклонен."
            )
        else:
            reminder_text = (
                f"⏰ <b>Напоминание о капче</b>\n\n"
                f"Вы не решили капчу для вступления в группу <b>{group_display_name}</b>.\n"
                f"Пожалуйста, решите капчу в течение следующих 2 минут, иначе ваш запрос будет отклонен."
            )
        
        reminder_msg = await bot.send_message(
            chat_id=user_id,
            text=reminder_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
        # Сохраняем ID напоминания в Redis для последующего удаления
        reminder_key = f"captcha_reminder_msgs:{user_id}"
        existing_reminders = await redis.get(reminder_key)
        if existing_reminders:
            # Преобразуем из bytes в строку если нужно
            reminders_str = existing_reminders.decode('utf-8') if isinstance(existing_reminders, bytes) else str(existing_reminders)
            reminder_list = reminders_str.split(",")
            reminder_list.append(str(reminder_msg.message_id))
            await redis.setex(reminder_key, 600, ",".join(reminder_list))  # Храним 10 минут
        else:
            await redis.setex(reminder_key, 600, str(reminder_msg.message_id))
        
        # Удаляем напоминание через 2-3 минуты (150 секунд = 2.5 минуты)
        asyncio.create_task(delete_message_after_delay(bot, user_id, reminder_msg.message_id, 150))
        
        logger.info(f"📨 Отправлено напоминание о капче пользователю {user_id}")
        
        return reminder_msg.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке напоминания о капче: {e}")
        return None


async def schedule_captcha_reminder(bot: Bot, user_id: int, group_name: str, delay_minutes: int = 2, reminder_count: int = 0):
    """Планирует отправку напоминания о капче через указанное количество минут. Максимум 2 повтора."""
    await asyncio.sleep(delay_minutes * 60)  # Конвертируем минуты в секунды
    
    # Проверяем, что пользователь все еще не решил капчу
    captcha_data = await get_captcha_data(user_id)
    if captcha_data and captcha_data["group_name"] == group_name:
        # Отправляем напоминание
        reminder_msg_id = await send_captcha_reminder(bot, user_id, user_id, group_name)
        
        # Если еще можно повторить (меньше 2 повторов)
        if reminder_count < 1:  # 0 = первое напоминание, 1 = второе (итого 2)
            # Планируем следующее напоминание через 2 минуты
            asyncio.create_task(schedule_captcha_reminder(bot, user_id, group_name, 2, reminder_count + 1))
        
        return reminder_msg_id
    return None


async def save_join_request(user_id: int, chat_id: int, group_id: str) -> None:
    """Сохраняет информацию о join-request на 1 час."""
    await redis.setex(f"join_request:{user_id}:{group_id}", 3600, str(chat_id))


async def create_deeplink_for_captcha(bot: Bot, group_id: str) -> str:
    """Создаёт /start deep-link для визуальной капчи."""
    deep_link = await create_start_link(bot, f"deep_link_{group_id}")
    logger.info(f"Создан deep link: {deep_link} для группы {group_id}")
    return deep_link


async def get_captcha_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    """Кнопка «Пройти капчу» (открывает /start с deep link)."""
    # Проверяем, что deep_link валидный
    if not deep_link or not deep_link.startswith(('http://', 'https://', 'tg://')):
        # Если deep_link невалидный, используем callback_data
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🧩 Пройти капчу", callback_data="captcha_fallback")]]
        )
    
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧩 Пройти капчу", url=deep_link)]]
    )


async def get_group_settings_keyboard(group_id: str, captcha_enabled: str) -> InlineKeyboardMarkup:
    """Клавиатура для включения/выключения визуальной капчи в группе."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Включено" if captcha_enabled == "1" else "Включить",
                    callback_data=f"set_visual_captcha:{group_id}:1",
                ),
                InlineKeyboardButton(
                    text="✅ Выключено" if captcha_enabled == "0" else "Выключить",
                    callback_data=f"set_visual_captcha:{group_id}:0",
                ),
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="redirect:captcha_settings")],
        ]
    )


async def get_group_join_keyboard(group_link: Optional[str], group_display_name: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Создает кнопку для присоединения к группе.
    Использует только https://t.me/ ссылки для надежности.
    Дополнительная защита от ошибки 400.
    """
    import re
    
    title = f"Присоединиться в «{group_display_name}»" if group_display_name else "Присоединиться в группу"
    
    # Логируем входные данные для отладки
    logger.info(f"🔗 Создание кнопки группы: group_link='{group_link}' (тип: {type(group_link)}), title='{title}'")
    
    # Преобразуем group_link в строку явно (может быть bytes из Redis или объект)
    group_link_str = None
    if group_link is not None:
        try:
            # Преобразуем из bytes в строку если нужно
            if isinstance(group_link, bytes):
                group_link_str = group_link.decode('utf-8', errors='ignore').strip()
            elif isinstance(group_link, str):
                group_link_str = group_link.strip()
            else:
                # Пробуем преобразовать в строку, игнорируя ошибки
                try:
                    group_link_str = str(group_link).strip()
                except Exception:
                    logger.error(f"❌ Не удалось преобразовать group_link в строку: {type(group_link)}")
                    group_link_str = None
            
            # Строгая проверка валидности ссылки
            if group_link_str and len(group_link_str) > 0 and isinstance(group_link_str, str):
                # Дополнительная очистка от невидимых символов
                group_link_str = ''.join(char for char in group_link_str if char.isprintable())
                group_link_str = group_link_str.strip()
                
                # Проверка длины URL (Telegram API ограничение - 2048 символов)
                if len(group_link_str) > 2048:
                    logger.error(f"❌ URL слишком длинный ({len(group_link_str)} символов), максимум 2048")
                    group_link_str = None
                
                if group_link_str:
                    # Проверяем что это валидная Telegram ссылка через regex
                    telegram_link_pattern = r'^(https?://)?(t\.me/|telegram\.me/)'
                    is_valid_telegram_link = bool(re.match(telegram_link_pattern, group_link_str, re.IGNORECASE))
                    
                    # Дополнительная проверка для tg:// протокола
                    if not is_valid_telegram_link:
                        is_valid_telegram_link = group_link_str.startswith("tg://")
                    
                    if is_valid_telegram_link:
                        # Нормализуем URL - убеждаемся что используется https://
                        if group_link_str.startswith("http://"):
                            final_url = group_link_str.replace("http://", "https://", 1)
                        elif group_link_str.startswith("t.me/") or group_link_str.startswith("telegram.me/"):
                            final_url = f"https://{group_link_str}"
                        elif group_link_str.startswith("tg://"):
                            # Для tg:// оставляем как есть, но логируем
                            final_url = group_link_str
                        else:
                            final_url = group_link_str
                        
                        # Финальная проверка - убеждаемся что это строка и валидна
                        if isinstance(final_url, str) and len(final_url) > 0:
                            # Проверяем что URL не содержит недопустимых символов
                            try:
                                # Финальная валидация - пытаемся создать объект URL
                                final_url = final_url.strip()
                                
                                # Дополнительная проверка типа перед созданием кнопки
                                if not isinstance(final_url, str):
                                    raise ValueError(f"final_url не является строкой: {type(final_url)}")
                                
                                logger.info(f"✅ Используем валидную ссылку: {final_url[:100]}... (тип: {type(final_url)}, длина: {len(final_url)})")
                                
                                # Создаем кнопку с дополнительной защитой
                                try:
                                    button = InlineKeyboardButton(text=title, url=final_url)
                                    
                                    # Дополнительная проверка после создания кнопки
                                    if hasattr(button, 'url') and button.url:
                                        if not isinstance(button.url, str):
                                            raise ValueError(f"button.url не является строкой после создания: {type(button.url)}")
                                        
                                        logger.info(f"✅ Создана кнопка с URL: '{final_url[:50]}...' (тип URL в кнопке: {type(button.url)})")
                                        return InlineKeyboardMarkup(
                                            inline_keyboard=[[button]]
                                        )
                                    else:
                                        raise ValueError("Кнопка не содержит URL после создания")
                                except Exception as btn_error:
                                    logger.error(f"❌ Ошибка при создании InlineKeyboardButton: {btn_error}, url='{final_url[:100]}', type={type(final_url)}")
                                    import traceback
                                    logger.error(traceback.format_exc())
                                    
                            except Exception as validation_error:
                                logger.error(f"❌ Ошибка валидации URL: {validation_error}, url='{group_link_str[:100]}'")
                        else:
                            logger.error(f"❌ final_url не валидна: type={type(final_url)}, len={len(final_url) if final_url else 0}")
                    else:
                        logger.warning(f"⚠️ Ссылка не является валидной Telegram ссылкой: '{group_link_str[:100]}'")
                else:
                    logger.warning(f"⚠️ group_link_str пустая после очистки")
            else:
                logger.warning(f"⚠️ group_link_str не строка или пустая: '{group_link_str}' (тип: {type(group_link_str)})")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке group_link: {e}, group_link='{group_link}', type={type(group_link)}")
            import traceback
            logger.error(traceback.format_exc())
    else:
        logger.warning(f"⚠️ group_link пустой или None (тип: {type(group_link)})")
    
    # Fallback - используем callback_data вместо url
    logger.info(f"🔄 Используем fallback кнопку с callback_data из-за проблем с URL")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data="group_link_fallback")]
        ]
    )


async def save_captcha_data(user_id: int, captcha_answer: str, group_name: str, attempts: int = 0) -> None:
    """Сохраняет данные капчи (на 5 минут)."""
    await redis.setex(f"captcha:{user_id}", 300, f"{captcha_answer}:{group_name}:{attempts}")


async def get_captcha_data(user_id: int) -> Optional[Dict[str, Any]]:
    """Читает данные капчи из Redis."""
    raw = await redis.get(f"captcha:{user_id}")
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    return {"captcha_answer": parts[0], "group_name": parts[1], "attempts": int(parts[2])}


async def set_rate_limit(user_id: int, seconds: int = 180) -> None:
    """Ставит рейтлимит на повторы капчи."""
    await redis.setex(f"rate_limit:{user_id}", seconds, str(seconds))


async def check_rate_limit(user_id: int) -> bool:
    """True, если есть активный рейтлимит."""
    return bool(await redis.exists(f"rate_limit:{user_id}"))


async def get_rate_limit_time_left(user_id: int) -> int:
    """Сколько секунд осталось у рейтлимита (0, если нет)."""
    ttl = await redis.ttl(f"rate_limit:{user_id}")
    return max(0, ttl)


async def check_admin_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Проверка прав администратора в группе."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def set_visual_captcha_status(chat_id: int, enabled: bool) -> None:
    """Включает/выключает визуальную капчу (флаг в Redis)."""
    await redis.set(f"visual_captcha_enabled:{chat_id}", "1" if enabled else "0")


async def get_visual_captcha_status(chat_id: int) -> bool:
    """Статус визуальной капчи из Redis."""
    return (await redis.get(f"visual_captcha_enabled:{chat_id}")) == "1"


async def approve_chat_join_request(bot: Bot, chat_id: int, user_id: int) -> Dict[str, Any]:
    """
    Одобряет запрос на вступление. Возвращает:
    {
      "success": bool,
      "message": str,
      "group_link": Optional[str]  # ссылка, по которой можно войти без повторного apply
    }
    Для приватных чатов создаём инвайт с creates_join_request=False.
    Для публичных с username — используем https://t.me/<username>.
    """
    result: Dict[str, Any] = {"success": False, "message": "", "group_link": None}

    try:
        logger.info(f"Пытаемся одобрить запрос на вступление: chat_id={chat_id}, user_id={user_id}")
        
        # Увеличиваем задержку для избежания rate limit
        await asyncio.sleep(5.0)  # Увеличиваем до 5 секунд
        
        # Сначала получаем информацию о группе
        chat = await bot.get_chat(chat_id)
        logger.info(f"Информация о группе: title={chat.title}, username={chat.username}, type={chat.type}")
        
        # Пытаемся одобрить запрос с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
                result["success"] = True
                result["message"] = (
                    "🎉 <b>Капча пройдена успешно!</b>\n\n"
                    "✅ <b>Ваш запрос на вступление в группу одобрен</b>\n"
                    "🔗 <b>Нажмите на кнопку ниже, чтобы присоединиться</b>"
                )
                logger.info(f"✅ Запрос на вступление успешно одобрен для пользователя {user_id}")
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg and attempt < max_retries - 1:
                    # Используем retry_after из ошибки, если есть, иначе увеличиваем задержку
                    if "retry_after" in error_msg:
                        import re
                        match = re.search(r'"retry_after":(\d+)', error_msg)
                        if match:
                            retry_after = int(match.group(1)) + 5  # Добавляем 5 секунд к указанному времени
                        else:
                            retry_after = 20 + attempt * 10  # 20с, 30с, 40с
                    else:
                        retry_after = 20 + attempt * 10  # 20с, 30с, 40с
                    
                    logger.warning(f"Rate limit при одобрении запроса, попытка {attempt + 1}/{max_retries}, ждем {retry_after}с")
                    await asyncio.sleep(retry_after)
                    continue
                elif "HIDE_REQUESTER_MISSING" in error_msg:
                    logger.warning(f"⚠️ Запрос на вступление для пользователя {user_id} не найден или уже обработан")
                    # Проверяем, не является ли пользователь уже участником группы
                    try:
                        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                        if member.status in ["member", "administrator", "creator"]:
                            logger.info(f"✅ Пользователь {user_id} уже является участником группы {chat_id}")
                            result["success"] = True
                            result["message"] = "Вы уже являетесь участником группы!"
                            # Создаем ссылку на группу
                            if chat.username:
                                result["group_link"] = f"https://t.me/{chat.username}"
                            break
                    except Exception as member_error:
                        logger.error(f"❌ Ошибка при проверке статуса участника: {member_error}")
                    
                    # Если пользователь не участник, считаем это успехом (возможно, запрос уже обработан)
                    result["success"] = True
                    result["message"] = "Запрос на вступление обработан!"
                    if chat.username:
                        result["group_link"] = f"https://t.me/{chat.username}"
                    break
                else:
                    raise e

        # Создаем ссылку на группу
        if result["success"]:
            if chat.username:
                # Публичная группа — можно зайти по username
                result["group_link"] = f"https://t.me/{chat.username}"
                logger.info(f"Ссылка на публичную группу: {result['group_link']}")
            else:
                # Приватная — делаем инвайт, который НЕ создаёт join request повторно
                # Добавляем задержку перед созданием инвайта
                await asyncio.sleep(5.0)
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id,
                    name=f"Invite for user {user_id}",
                    creates_join_request=False,
                )
                # Преобразуем invite.invite_link в строку явно
                result["group_link"] = str(invite.invite_link) if invite.invite_link else None
                logger.info(f"Ссылка-инвайт для приватной группы: {result['group_link']} (тип: {type(result['group_link'])})")

    except Exception as e:
        logger.error(f"Ошибка approve_chat_join_request: {e}")
        result["message"] = f"Капча пройдена, но не удалось автоматически добавить в группу: {e}"

        # Даже при ошибке попробуем отдать ссылку
        try:
            await asyncio.sleep(0.5)  # Задержка перед повторной попыткой
            chat = await bot.get_chat(chat_id)
            if chat.username:
                result["group_link"] = f"https://t.me/{chat.username}"
            else:
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id,
                    name=f"Invite for user {user_id}",
                    creates_join_request=False,
                )
                # Преобразуем invite.invite_link в строку явно
                result["group_link"] = str(invite.invite_link) if invite.invite_link else None
        except Exception as e2:
            logger.error(f"Ошибка резервного создания ссылки: {e2}")

    return result


async def get_group_display_name(group_name: str) -> str:
    """Красивое отображаемое имя группы (из Redis или формат из имени)."""
    cached = await redis.get(f"group_display_name:{group_name}")
    if cached:
        return str(cached)
    return group_name.replace("_", " ").title()


async def save_user_to_db(session: AsyncSession, user_data: dict) -> None:
    """Сохраняет/обновляет пользователя в БД (для рассылок и аналитики)."""
    try:
        result = await session.execute(select(User).where(User.user_id == user_data["user_id"]))
        existing = result.scalar_one_or_none()

        if not existing:
            new_user = User(
                user_id=user_data["user_id"],
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                language_code=user_data.get("language_code", "ru"),
                is_bot=user_data.get("is_bot", False),
                is_premium=user_data.get("is_premium", False),
                added_to_attachment_menu=user_data.get("added_to_attachment_menu", False),
                can_join_groups=user_data.get("can_join_groups", True),
                can_read_all_group_messages=user_data.get("can_read_all_group_messages", False),
                supports_inline_queries=user_data.get("supports_inline_queries", False),
                can_connect_to_business=user_data.get("can_connect_to_business", False),
                has_main_web_app=user_data.get("has_main_web_app", False),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"✅ Пользователь {user_data['user_id']} сохранён в БД")
        else:
            existing.username = user_data.get("username")
            existing.first_name = user_data.get("first_name")
            existing.last_name = user_data.get("last_name")
            existing.updated_at = datetime.utcnow()
            await session.commit()
            logger.info(f"♻️ Пользователь {user_data['user_id']} обновлён в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении пользователя: {e}")
        await session.rollback()


async def get_group_link_from_redis_or_create(bot: Bot, group_name: str) -> Optional[str]:
    """
    Возвращает рабочую ссылку на группу:
    - из кэша Redis,
    - для приватных — создаёт инвайт с creates_join_request=False,
    - для публичных — https://t.me/<username>.
    Возвращает None, если создать ссылку не удалось.
    """
    try:
        cached = await redis.get(f"group_link:{group_name}")
        if cached:
            # Преобразуем из bytes в строку если нужно
            cached_str = cached.decode('utf-8') if isinstance(cached, bytes) else str(cached)
            logger.info(f"🔗 Используем кэшированную ссылку для {group_name}: {cached_str} (тип: {type(cached_str)})")
            return cached_str

        logger.info(f"🔗 Создаем новую ссылку для группы: {group_name}")
        group_link: Optional[str] = None

        # Определяем chat_id для всех типов групп
        chat_id = None
        if group_name.startswith("private_"):
            chat_id = int(group_name.replace("private_", ""))
        elif group_name.startswith("-") and group_name[1:].isdigit():
            chat_id = int(group_name)
        else:
            # Публичная группа по username
            group_link = f"https://t.me/{group_name}"
            await redis.setex(f"group_link:{group_name}", 3600, group_link)
            return group_link

        # Для приватных групп и числовых ID
        if chat_id:
            try:
                chat = await bot.get_chat(chat_id)
                if chat.username:
                    group_link = f"https://t.me/{chat.username}"
                else:
                    # Добавляем задержку перед созданием инвайта
                    await asyncio.sleep(5.0)
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        name=f"Invite for {group_name}",
                        creates_join_request=False,
                    )
                    # Преобразуем invite.invite_link в строку явно  
                    group_link = str(invite.invite_link) if invite.invite_link else None
            except Exception as e:
                logger.error(f"Ошибка при получении ссылки для группы {chat_id}: {e}")
                # Повторная попытка: ещё раз создать инвайт
                try:
                    await asyncio.sleep(10.0)  # Увеличиваем задержку до 10 секунд
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        name=f"Invite for {group_name}",
                        creates_join_request=False,
                    )
                    # Преобразуем invite.invite_link в строку явно  
                    group_link = str(invite.invite_link) if invite.invite_link else None
                except Exception as e2:
                    logger.error(f"Повторная ошибка создания инвайта: {e2}")
                    group_link = None

        if group_link:
            await redis.setex(f"group_link:{group_name}", 3600, group_link)
            logger.info(f"🔗 Сохранена ссылка для {group_name}: {group_link}")
        else:
            logger.error(f"❌ Не удалось создать ссылку для группы {group_name}")

        return group_link
    except Exception as e:
        logger.error(f"Ошибка при получении ссылки на группу {group_name}: {e}")
        return None


async def is_visual_captcha_enabled(session: AsyncSession, chat_id: int) -> bool:
    """Статус визуальной капчи из БД (на случай, если используете таблицу CaptchaSettings)."""
    try:
        result = await session.execute(select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id))
        settings = result.scalar_one_or_none()
        is_enabled = settings.is_visual_enabled if settings else False
        logger.info(
            f"visual_captcha_logic: Проверка визуальной капчи для группы {chat_id}: "
            f"{'включена' if is_enabled else 'выключена'}"
        )
        return is_enabled
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса визуальной капчи: {e}")
        return False


# ==================== ПОВЕДЕНЧЕСКИЕ ПРОВЕРКИ ====================

async def start_behavior_tracking(user_id: int) -> None:
    """Начинает отслеживание поведения пользователя при решении капчи."""
    current_time = time.time()
    await redis.setex(f"captcha_start_time:{user_id}", 600, str(current_time))  # 10 минут
    await redis.setex(f"captcha_attempts:{user_id}", 600, "0")  # Счетчик попыток
    await redis.setex(f"captcha_inputs:{user_id}", 600, "")  # История ввода


async def track_captcha_input(user_id: int, input_text: str) -> None:
    """Отслеживает ввод пользователя для анализа поведения."""
    current_time = time.time()
    input_data = f"{current_time}:{input_text}"
    
    # Получаем существующую историю
    history = await redis.get(f"captcha_inputs:{user_id}")
    if history:
        history = history + "|" + input_data
    else:
        history = input_data
    
    await redis.setex(f"captcha_inputs:{user_id}", 600, history)


async def analyze_behavior_patterns(user_id: int) -> Dict[str, Any]:
    """Анализирует поведенческие паттерны пользователя."""
    analysis = {
        "is_suspicious": False,
        "reasons": [],
        "risk_score": 0
    }
    
    try:
        # Проверяем время решения
        start_time_str = await redis.get(f"captcha_start_time:{user_id}")
        if start_time_str:
            start_time = float(start_time_str)
            solve_time = time.time() - start_time
            
            # Слишком быстрое решение (менее 3 секунд) - подозрительно
            if solve_time < 3:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Слишком быстрое решение капчи")
                analysis["risk_score"] += 30
            
            # Слишком медленное решение (более 5 минут) - тоже подозрительно
            elif solve_time > 300:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Слишком медленное решение капчи")
                analysis["risk_score"] += 20
        
        # Анализируем паттерны ввода
        input_history = await redis.get(f"captcha_inputs:{user_id}")
        if input_history:
            inputs = input_history.split("|")
            
            # Проверяем на слишком быстрый ввод
            if len(inputs) > 1:
                for i in range(1, len(inputs)):
                    prev_time = float(inputs[i-1].split(":")[0])
                    curr_time = float(inputs[i].split(":")[0])
                    time_diff = curr_time - prev_time
                    
                    # Ввод быстрее 0.5 секунды между символами - подозрительно
                    if time_diff < 0.5:
                        analysis["is_suspicious"] = True
                        analysis["reasons"].append("Слишком быстрый ввод")
                        analysis["risk_score"] += 25
                        break
            
            # Проверяем на одинаковые попытки
            unique_inputs = set()
            for inp in inputs:
                text = inp.split(":", 1)[1] if ":" in inp else inp
                unique_inputs.add(text.lower().strip())
            
            # Если все попытки одинаковые - подозрительно
            if len(unique_inputs) == 1 and len(inputs) > 2:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Повторение одинаковых ответов")
                analysis["risk_score"] += 20
        
        # Проверяем количество попыток
        attempts_str = await redis.get(f"captcha_attempts:{user_id}")
        if attempts_str:
            attempts = int(attempts_str)
            if attempts > 5:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Слишком много попыток")
                analysis["risk_score"] += 15
        
        # Определяем общий уровень риска
        if analysis["risk_score"] >= 50:
            analysis["is_suspicious"] = True
        
    except Exception as e:
        logger.error(f"Ошибка при анализе поведенческих паттернов: {e}")
    
    return analysis


async def increment_captcha_attempts(user_id: int) -> int:
    """Увеличивает счетчик попыток решения капчи."""
    attempts_str = await redis.get(f"captcha_attempts:{user_id}")
    attempts = int(attempts_str) + 1 if attempts_str else 1
    await redis.setex(f"captcha_attempts:{user_id}", 600, str(attempts))
    return attempts


# ==================== ПРОВЕРКА ПРОФИЛЯ ====================

async def analyze_user_messages(user_id: int, bot: Bot, chat_id: int) -> Dict[str, Any]:
    """Анализирует сообщения пользователя на предмет спама и повторений."""
    analysis = {
        "is_suspicious": False,
        "reasons": [],
        "risk_score": 0
    }
    
    try:
        # Получаем последние сообщения пользователя в группе
        # Ограничиваем до 50 сообщений для анализа
        messages = []
        try:
            # Получаем последние сообщения через get_updates (ограниченный способ)
            # В реальных условиях лучше использовать webhook или другой метод
            # Пока что пропускаем анализ сообщений, так как get_chat_history недоступен
            logger.info(f"   ℹ️ АНАЛИЗ СООБЩЕНИЙ ПРОПУЩЕН (API ограничения) (0 баллов)")
            return analysis
        except Exception as e:
            logger.warning(f"Не удалось получить историю сообщений для анализа: {e}")
            return analysis
        
        if not messages:
            # Если нет сообщений - это нормально для новых пользователей
            logger.info(f"   ℹ️ НЕТ СООБЩЕНИЙ ДЛЯ АНАЛИЗА (0 баллов)")
            return analysis
        
        # Анализируем сообщения на повторения
        message_counts = {}
        for msg in messages:
            msg_lower = msg.lower().strip()
            if len(msg_lower) > 3:  # Игнорируем очень короткие сообщения
                message_counts[msg_lower] = message_counts.get(msg_lower, 0) + 1
        
        # Проверяем на спам (одинаковые сообщения)
        total_messages = len(messages)
        unique_messages = len(message_counts)
        
        # Если много повторяющихся сообщений
        if unique_messages < total_messages * 0.3:  # Менее 30% уникальных сообщений
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Много повторяющихся сообщений")
            analysis["risk_score"] += 30
            logger.warning(f"   ⚠️ МНОГО ПОВТОРЕНИЙ: {unique_messages}/{total_messages} уникальных (+30 баллов)")
        
        # Проверяем на конкретные повторения
        for msg, count in message_counts.items():
            if count >= 5:  # Одно сообщение повторяется 5+ раз
                analysis["is_suspicious"] = True
                analysis["reasons"].append(f"Сообщение повторяется {count} раз")
                analysis["risk_score"] += 20
                logger.warning(f"   ⚠️ ПОВТОРЕНИЕ: '{msg[:30]}...' {count} раз (+20 баллов)")
                break
        
        # Проверяем на подозрительные паттерны
        suspicious_patterns = [
            "реклама", "заработок", "деньги", "криптовалюта", "биткоин",
            "инвестиции", "пирамида", "млм", "работа на дому",
            "telegram.me", "t.me", "ссылка", "переходи", "подписывайся"
        ]
        
        spam_count = 0
        for msg in messages:
            msg_lower = msg.lower()
            for pattern in suspicious_patterns:
                if pattern in msg_lower:
                    spam_count += 1
                    break
        
        if spam_count > 0:
            analysis["is_suspicious"] = True
            analysis["reasons"].append(f"Подозрительные сообщения: {spam_count}")
            analysis["risk_score"] += spam_count * 10
            logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНЫЕ СООБЩЕНИЯ: {spam_count} (+{spam_count * 10} баллов)")
        
        if not analysis["is_suspicious"]:
            logger.info(f"   ✅ СООБЩЕНИЯ НОРМАЛЬНЫЕ: {unique_messages}/{total_messages} уникальных (0 баллов)")
        
    except Exception as e:
        logger.error(f"Ошибка при анализе сообщений пользователя: {e}")
    
    return analysis


async def analyze_user_profile(user_data: dict, bot: Bot = None) -> Dict[str, Any]:
    """
    Анализирует профиль пользователя с использованием расширенного анализатора
    Включает анализ возраста аккаунта по ID и проверку био
    """
    try:
        user_id = user_data.get('id') or user_data.get('user_id', 'unknown')
        logger.info(f"🔍 РАСШИРЕННЫЙ АНАЛИЗ ПРОФИЛЯ ПОЛЬЗОВАТЕЛЯ {user_id}:")
        
        # Используем новый расширенный анализатор
        enhanced_analysis = await enhanced_profile_analyzer.analyze_user_profile_enhanced(user_data, bot)
        
        # Возвращаем в формате, совместимом со старой функцией
        return {
            "is_suspicious": enhanced_analysis["is_suspicious"],
            "reasons": enhanced_analysis["reasons"],
            "risk_score": enhanced_analysis["risk_score"]
        }
        
    except Exception as e:
        logger.error(f"Ошибка в расширенном анализе профиля: {e}")
        # Fallback к старому анализу
        return await analyze_user_profile_old(user_data, bot)


async def analyze_user_profile_old(user_data: dict, bot: Bot = None) -> Dict[str, Any]:
    """Анализирует профиль пользователя на предмет подозрительности."""
    analysis = {
        "is_suspicious": False,
        "reasons": [],
        "risk_score": 0
    }
    
    user_id = user_data.get("user_id", "unknown")
    print(f"🔍 Анализ профиля пользователя {user_id}:")
    print(f"   📝 Имя: {user_data.get('first_name', 'НЕТ')}")
    print(f"   👤 Username: @{user_data.get('username', 'НЕТ')}")
    print(f"   🌍 Язык: {user_data.get('language_code', 'НЕТ')}")
    print(f"   🤖 Бот: {user_data.get('is_bot', False)}")
    print(f"   ⭐ Premium: {user_data.get('is_premium', False)}")
    
    logger.info(f"🔍 Анализ профиля пользователя {user_id}:")
    logger.info(f"   📝 Имя: {user_data.get('first_name', 'НЕТ')}")
    logger.info(f"   👤 Username: @{user_data.get('username', 'НЕТ')}")
    logger.info(f"   🌍 Язык: {user_data.get('language_code', 'НЕТ')}")
    logger.info(f"   🤖 Бот: {user_data.get('is_bot', False)}")
    logger.info(f"   ⭐ Premium: {user_data.get('is_premium', False)}")
    
    try:
        # Проверяем возраст аккаунта (если есть информация)
        if "created_at" in user_data:
            created_at = user_data["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            account_age = datetime.utcnow() - created_at.replace(tzinfo=None)
            
            # Аккаунт младше 1 дня - очень подозрительно
            if account_age.days < 1:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Очень новый аккаунт (менее 1 дня)")
                analysis["risk_score"] += 40
                logger.warning(f"   ⚠️ ОЧЕНЬ НОВЫЙ АККАУНТ: {account_age.days} дней (+40 баллов)")
            
            # Аккаунт младше 7 дней - подозрительно
            elif account_age.days < 7:
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Новый аккаунт (менее 7 дней)")
                analysis["risk_score"] += 25
                logger.warning(f"   ⚠️ НОВЫЙ АККАУНТ: {account_age.days} дней (+25 баллов)")
            
            # Аккаунт младше 30 дней - умеренно подозрительно
            elif account_age.days < 30:
                analysis["risk_score"] += 10
                logger.info(f"   ℹ️ МОЛОДОЙ АККАУНТ: {account_age.days} дней (+10 баллов)")
            else:
                logger.info(f"   ✅ СТАРЫЙ АККАУНТ: {account_age.days} дней (0 баллов)")
        
        # Дополнительная проверка через Telegram API для получения даты создания аккаунта
        if bot and user_id != "unknown":
            try:
                # Получаем информацию о пользователе через API
                user_info = await bot.get_chat(user_id)
                
                # Проверяем дату создания аккаунта через get_chat
                try:
                    # Пытаемся получить информацию о пользователе
                    user_chat = await bot.get_chat(user_id)
                    
                    # Проверяем различные атрибуты для даты создания
                    account_creation = None
                    if hasattr(user_chat, 'created_at') and user_chat.created_at:
                        account_creation = user_chat.created_at
                    elif hasattr(user_chat, 'date') and user_chat.date:
                        account_creation = user_chat.date
                    
                    if account_creation:
                        if isinstance(account_creation, str):
                            account_creation = datetime.fromisoformat(account_creation.replace('Z', '+00:00'))
                        
                        account_age = datetime.utcnow() - account_creation.replace(tzinfo=None)
                        
                        logger.info(f"   📅 ДАТА СОЗДАНИЯ АККАУНТА: {account_creation.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.info(f"   ⏰ ВОЗРАСТ АККАУНТА: {account_age.days} дней")
                        
                        # Более строгие проверки для новых аккаунтов
                        if account_age.days < 1:
                            analysis["is_suspicious"] = True
                            analysis["reasons"].append("Очень новый аккаунт (менее 1 дня)")
                            analysis["risk_score"] += 50
                            logger.warning(f"   🚨 ОЧЕНЬ НОВЫЙ АККАУНТ: {account_age.days} дней (+50 баллов)")
                        elif account_age.days < 3:
                            analysis["is_suspicious"] = True
                            analysis["reasons"].append("Новый аккаунт (менее 3 дней)")
                            analysis["risk_score"] += 35
                            logger.warning(f"   ⚠️ НОВЫЙ АККАУНТ: {account_age.days} дней (+35 баллов)")
                        elif account_age.days < 7:
                            analysis["is_suspicious"] = True
                            analysis["reasons"].append("Молодой аккаунт (менее 7 дней)")
                            analysis["risk_score"] += 20
                            logger.warning(f"   ⚠️ МОЛОДОЙ АККАУНТ: {account_age.days} дней (+20 баллов)")
                        elif account_age.days < 30:
                            analysis["risk_score"] += 8
                            logger.info(f"   ℹ️ МОЛОДОЙ АККАУНТ: {account_age.days} дней (+8 баллов)")
                        else:
                            logger.info(f"   ✅ СТАРЫЙ АККАУНТ: {account_age.days} дней (0 баллов)")
                    else:
                        # Если нет информации о дате создания, добавляем баллы за неизвестность
                        analysis["risk_score"] += 5
                        logger.info(f"   ℹ️ НЕИЗВЕСТНАЯ ДАТА СОЗДАНИЯ АККАУНТА (+5 баллов)")
                        
                except Exception as date_error:
                    logger.warning(f"   ⚠️ Не удалось получить дату создания аккаунта: {date_error}")
                    analysis["risk_score"] += 5
                    logger.info(f"   ℹ️ НЕИЗВЕСТНАЯ ДАТА СОЗДАНИЯ АККАУНТА (+5 баллов)")
                
                # Проверяем наличие фото профиля
                try:
                    # Пытаемся получить фото профиля
                    photos = await bot.get_user_profile_photos(user_id, limit=1)
                    logger.info(f"   📸 ПРОВЕРКА ФОТО ПРОФИЛЯ: найдено {photos.total_count} фото")
                    
                    if photos.total_count == 0:
                        # Отсутствие фото профиля - не критично
                        logger.info(f"   ℹ️ НЕТ ФОТО ПРОФИЛЯ (0 баллов)")
                    else:
                        # Есть фото - проверяем его возраст
                        photo = photos.photos[0][0]  # Берем самое большое фото
                        
                        # Пытаемся получить дату фото разными способами
                        photo_date = None
                        if hasattr(photo, 'date') and photo.date:
                            photo_date = photo.date
                        elif hasattr(photo, 'created_at') and photo.created_at:
                            photo_date = photo.created_at
                        
                        if photo_date:
                            if isinstance(photo_date, str):
                                photo_date = datetime.fromisoformat(photo_date.replace('Z', '+00:00'))
                            
                            photo_age = datetime.utcnow() - photo_date.replace(tzinfo=None)
                            
                            logger.info(f"   📅 ДАТА ЗАГРУЗКИ ФОТО: {photo_date.strftime('%Y-%m-%d %H:%M:%S')}")
                            logger.info(f"   ⏰ ВОЗРАСТ ФОТО: {photo_age.days} дней")
                            
                            # Свежее фото (менее 1 дня) - подозрительно
                            if photo_age.days < 1:
                                analysis["is_suspicious"] = True
                                analysis["reasons"].append("Свежее фото профиля (менее 1 дня)")
                                analysis["risk_score"] += 25
                                logger.warning(f"   ⚠️ СВЕЖЕЕ ФОТО: {photo_age.days} дней (+25 баллов)")
                            elif photo_age.days < 7:
                                analysis["risk_score"] += 10
                                logger.info(f"   ℹ️ НЕДАВНЕЕ ФОТО: {photo_age.days} дней (+10 баллов)")
                            else:
                                logger.info(f"   ✅ СТАРОЕ ФОТО: {photo_age.days} дней (0 баллов)")
                        else:
                            logger.info(f"   ✅ ЕСТЬ ФОТО ПРОФИЛЯ (дата неизвестна) (0 баллов)")
                            
                except Exception as photo_error:
                    logger.warning(f"   ⚠️ Не удалось проверить фото профиля: {photo_error}")
                    # Если не можем проверить фото, добавляем небольшой балл
                    analysis["risk_score"] += 3
                    logger.info(f"   ℹ️ НЕ УДАЛОСЬ ПРОВЕРИТЬ ФОТО (+3 балла)")
                    
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось получить дополнительную информацию о пользователе через API: {e}")
                # Если не можем получить информацию через API, добавляем баллы
                analysis["risk_score"] += 10
                logger.info(f"   ℹ️ НЕ УДАЛОСЬ ПОЛУЧИТЬ ДАННЫЕ ЧЕРЕЗ API (+10 баллов)")
        
        # Проверяем наличие username
        if not user_data.get("username"):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Отсутствует username")
            analysis["risk_score"] += 15
            logger.warning(f"   ⚠️ НЕТ USERNAME (+15 баллов)")
        else:
            logger.info(f"   ✅ ЕСТЬ USERNAME (0 баллов)")
            
            # Анализируем username на подозрительность
            username = user_data.get("username", "").lower()
            suspicious_patterns = [
                "bot", "admin", "support", "help", "service", "official",
                "test", "demo", "sample", "example", "temp", "tmp"
            ]
            
            for pattern in suspicious_patterns:
                if pattern in username:
                    analysis["is_suspicious"] = True
                    analysis["reasons"].append(f"Подозрительный username содержит '{pattern}'")
                    analysis["risk_score"] += 10
                    logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНЫЙ USERNAME: содержит '{pattern}' (+10 баллов)")
                    break
        
        # Проверяем наличие имени
        if not user_data.get("first_name"):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Отсутствует имя")
            analysis["risk_score"] += 20
            logger.warning(f"   ⚠️ НЕТ ИМЕНИ (+20 баллов)")
        else:
            logger.info(f"   ✅ ЕСТЬ ИМЯ (0 баллов)")
            
            # Анализируем имя на подозрительность
            first_name = user_data.get("first_name", "").lower()
            suspicious_names = [
                "bot", "admin", "support", "help", "service", "official",
                "test", "demo", "sample", "example", "temp", "tmp",
                "user", "member", "guest", "anonymous"
            ]
            
            for pattern in suspicious_names:
                if pattern in first_name:
                    analysis["is_suspicious"] = True
                    analysis["reasons"].append(f"Подозрительное имя содержит '{pattern}'")
                    analysis["risk_score"] += 10
                    logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНОЕ ИМЯ: содержит '{pattern}' (+10 баллов)")
                    break
        
        # Проверяем подозрительные имена
        first_name = user_data.get("first_name", "").lower()
        suspicious_names = [
            "user", "test", "bot", "admin", "support", "help",
            "пользователь", "тест", "бот", "админ", "поддержка"
        ]
        
        if any(name in first_name for name in suspicious_names):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Подозрительное имя")
            analysis["risk_score"] += 20
            logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНОЕ ИМЯ: '{first_name}' (+20 баллов)")
        else:
            logger.info(f"   ✅ НОРМАЛЬНОЕ ИМЯ: '{first_name}' (0 баллов)")
        
        # Проверяем подозрительные username
        username = user_data.get("username", "").lower()
        if username:
            # Username с числами в конце (часто боты)
            if username[-3:].isdigit() or username[-4:].isdigit():
                analysis["risk_score"] += 10
                logger.warning(f"   ⚠️ USERNAME С ЧИСЛАМИ: '{username}' (+10 баллов)")
            
            # Очень короткий username
            if len(username) < 3:
                analysis["risk_score"] += 15
                logger.warning(f"   ⚠️ КОРОТКИЙ USERNAME: '{username}' (+15 баллов)")
            
            # Username с подозрительными словами
            bot_keywords = ["bot", "user", "test", "auto", "spam"]
            if any(keyword in username for keyword in bot_keywords):
                analysis["is_suspicious"] = True
                analysis["reasons"].append("Подозрительный username")
                analysis["risk_score"] += 25
                logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНЫЙ USERNAME: '{username}' (+25 баллов)")
            else:
                logger.info(f"   ✅ НОРМАЛЬНЫЙ USERNAME: '{username}' (0 баллов)")
        
        # Проверяем язык
        language_code = user_data.get("language_code", "")
        if language_code and language_code not in ["ru", "en", "uk", "be"]:
            analysis["risk_score"] += 5
            logger.warning(f"   ⚠️ НЕСТАНДАРТНЫЙ ЯЗЫК: '{language_code}' (+5 баллов)")
        else:
            logger.info(f"   ✅ СТАНДАРТНЫЙ ЯЗЫК: '{language_code}' (0 баллов)")
        
        # Проверяем флаги бота
        if user_data.get("is_bot", False):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Аккаунт помечен как бот")
            analysis["risk_score"] += 50
            logger.error(f"   🚨 АККАУНТ ПОМЕЧЕН КАК БОТ (+50 баллов)")
        
        # Определяем общий уровень риска
        if analysis["risk_score"] >= 40:
            analysis["is_suspicious"] = True
        
        # Итоговое логирование
        logger.info(f"   📊 ИТОГОВЫЙ РЕЗУЛЬТАТ:")
        logger.info(f"      🎯 Общий балл риска: {analysis['risk_score']}/100")
        logger.info(f"      🚨 Подозрительный: {analysis['is_suspicious']}")
        if analysis["reasons"]:
            logger.info(f"      📝 Причины: {', '.join(analysis['reasons'])}")
        
    except Exception as e:
        logger.error(f"Ошибка при анализе профиля пользователя: {e}")
    
    return analysis


async def get_enhanced_captcha_decision(user_id: int, user_data: dict, captcha_answer: str, user_answer: str, bot: Bot = None, chat_id: int = None) -> Dict[str, Any]:
    """Принимает решение о прохождении капчи на основе всех проверок."""
    decision = {
        "approved": False,
        "reason": "",
        "risk_factors": [],
        "total_risk_score": 0
    }
    
    print(f"🎯 Принятие решения о капче для пользователя {user_id}")
    print(f"   📝 Ответ пользователя: '{user_answer}'")
    print(f"   ✅ Правильный ответ: '{captcha_answer}'")
    
    logger.info(f"🎯 Принятие решения о капче для пользователя {user_id}")
    logger.info(f"   📝 Ответ пользователя: '{user_answer}'")
    logger.info(f"   ✅ Правильный ответ: '{captcha_answer}'")
    
    try:
        # 0. Анализируем профиль пользователя ВСЕГДА (даже при неверном ответе)
        profile_analysis = await analyze_user_profile(user_data, bot)
        if profile_analysis["is_suspicious"]:
            decision["risk_factors"].extend(profile_analysis["reasons"])
            decision["total_risk_score"] += profile_analysis["risk_score"]
        
        # 0.5. Анализируем сообщения пользователя (если есть bot и chat_id)
        if bot and chat_id:
            messages_analysis = await analyze_user_messages(user_id, bot, chat_id)
            if messages_analysis["is_suspicious"]:
                decision["risk_factors"].extend(messages_analysis["reasons"])
                decision["total_risk_score"] += messages_analysis["risk_score"]
        
        # 1. Проверяем правильность ответа на капчу
        user_answer_clean = user_answer.upper().strip()
        captcha_answer_clean = captcha_answer.upper().strip()
        
        print(f"🔍 Сравнение ответов:")
        print(f"   Пользователь: '{user_answer}' -> '{user_answer_clean}'")
        print(f"   Правильный: '{captcha_answer}' -> '{captcha_answer_clean}'")
        print(f"   Совпадают: {user_answer_clean == captcha_answer_clean}")
        
        if user_answer_clean != captcha_answer_clean:
            decision["reason"] = "Неверный ответ на капчу"
            return decision
        
        # 2. Анализируем поведенческие паттерны (убираем баллы за неверный ответ)
        behavior_analysis = await analyze_behavior_patterns(user_id)
        # Не добавляем баллы за поведение при неверном ответе - пусть пытается
        logger.info(f"   ℹ️ ПОВЕДЕНЧЕСКИЙ АНАЛИЗ ПРОПУЩЕН (0 баллов)")
        
        # 3. Профиль уже проанализирован выше
        
        # 4. Принимаем решение с обновленными порогами
        logger.info(f"   🎯 ИТОГОВОЕ РЕШЕНИЕ:")
        logger.info(f"      📊 Общий балл риска: {decision['total_risk_score']}/100")
        
        # Обновленные пороги согласно требованиям:
        # 80+ баллов = автомут (высокий риск)
        # 50-79 баллов = автомут скаммера (средний риск) 
        # 30-49 баллов = дополнительная проверка (умеренный риск)
        # 0-29 баллов = разрешен (низкий риск)
        
        if decision["total_risk_score"] >= 80:
            decision["reason"] = f"Высокий риск скаммера (оценка: {decision['total_risk_score']}/100) - будет замьючен"
            decision["approved"] = True  # Разрешаем вход, но будем мутить
            decision["should_auto_mute"] = True  # Флаг для автомута
            logger.warning(f"   🚨 РЕШЕНИЕ: РАЗРЕШЕН С АВТОМУТОМ (высокий риск)")
            logger.warning(f"   📝 Причины: {', '.join(decision['risk_factors'])}")
        elif decision["total_risk_score"] >= 50:
            decision["reason"] = f"Средний риск скаммера (оценка: {decision['total_risk_score']}/100) - будет замьючен"
            decision["approved"] = True  # Разрешаем вход, но будем мутить
            decision["should_auto_mute"] = True  # Флаг для автомута
            logger.warning(f"   ⚠️ РЕШЕНИЕ: РАЗРЕШЕН С АВТОМУТОМ (средний риск)")
            logger.warning(f"   📝 Причины: {', '.join(decision['risk_factors'])}")
        elif decision["total_risk_score"] >= 30:
            decision["reason"] = f"Умеренный риск (оценка: {decision['total_risk_score']}/100), требуется дополнительная проверка"
            logger.warning(f"   ⚠️ РЕШЕНИЕ: ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА (умеренный риск)")
            logger.warning(f"   📝 Причины: {', '.join(decision['risk_factors'])}")
        else:
            decision["approved"] = True
            decision["reason"] = "Капча пройдена успешно"
            logger.info(f"   ✅ РЕШЕНИЕ: РАЗРЕШЕН (низкий риск)")
            if decision['risk_factors']:
                logger.info(f"   📝 Факторы риска: {', '.join(decision['risk_factors'])}")
        
    except Exception as e:
        logger.error(f"Ошибка при принятии решения о капче: {e}")
        decision["reason"] = "Ошибка при проверке капчи"
    
    return decision


async def format_user_log_info(bot: Bot, user_id: int, chat_id: int = None) -> str:
    """Форматирует информацию о пользователе и группе для логов с юзернеймами"""
    try:
        # Получаем информацию о пользователе
        user_info = f"id{user_id}"
        try:
            user = await bot.get_chat(user_id)
            if user.username:
                user_info = f"@{user.username} [{user_id}]"
            elif user.first_name:
                user_info = f"{user.first_name} [{user_id}]"
        except:
            pass
        
        # Получаем информацию о группе если указана
        if chat_id:
            try:
                chat = await bot.get_chat(chat_id)
                if chat.username:
                    chat_info = f"@{chat.username} [{chat_id}]"
                else:
                    chat_info = f"{chat.title} [{chat_id}]"
                return f"{user_info} в группе {chat_info}"
            except:
                return f"{user_info} в группе {chat_id}"
        
        return user_info
    except:
        return f"id{user_id}"


async def save_scam_level_to_db(session: AsyncSession, user_id: int, chat_id: int, risk_score: int, risk_factors: list, user_data: dict, bot: Bot = None) -> None:
    """Сохраняет уровень скама пользователя в базу данных."""
    try:
        # Используем прямую шкалу риска 0-100 вместо уровней 0-5
        scam_level = risk_score  # Теперь scam_level = risk_score (0-100)
        
        # Проверяем, есть ли уже запись для этого пользователя в этой группе
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        existing_record = result.scalar_one_or_none()
        
        if existing_record:
            # Обновляем существующую запись
            existing_record.scammer_level = scam_level
            existing_record.violation_count += 1
            existing_record.last_violation_at = datetime.utcnow()
            existing_record.notes = f"Обновлен уровень скама: {risk_score}/100. Факторы: {', '.join(risk_factors)}"
            existing_record.updated_at = datetime.utcnow()
            
            # Получаем информацию о пользователе и группе для лога
            user_log_info = await format_user_log_info(bot, user_id, chat_id) if bot else f"id{user_id} в группе {chat_id}"
            logger.info(f"📊 Обновлен уровень скама для {user_log_info}: {scam_level}/100 (балл: {risk_score})")
        else:
            # Создаем новую запись
            new_record = ScammerTracker(
                user_id=user_id,
                chat_id=chat_id,
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                violation_type="captcha_risk_assessment",
                violation_count=1,
                is_scammer=scam_level >= 50,  # Считаем скаммером при 50+ баллах риска
                scammer_level=scam_level,
                first_violation_at=datetime.utcnow(),
                last_violation_at=datetime.utcnow(),
                notes=f"Первая оценка риска: {risk_score}/100. Факторы: {', '.join(risk_factors)}"
            )
            session.add(new_record)
            
            # Получаем информацию о пользователе и группе для лога
            user_log_info = await format_user_log_info(bot, user_id, chat_id) if bot else f"id{user_id} в группе {chat_id}"
            logger.info(f"📊 Создана запись о скаме для {user_log_info}: {scam_level}/100 (балл: {risk_score})")
        
        await session.commit()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении уровня скама в БД: {e}")
        await session.rollback()


async def get_user_scam_level(session: AsyncSession, user_id: int, chat_id: int) -> int:
    """Получает уровень скама пользователя из базы данных."""
    try:
        result = await session.execute(
            select(ScammerTracker.scammer_level).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        scam_level = result.scalar_one_or_none()
        return scam_level if scam_level is not None else 0
    except Exception as e:
        logger.error(f"❌ Ошибка при получении уровня скама из БД: {e}")
        return 0


async def reset_user_scam_level(session: AsyncSession, user_id: int, chat_id: int = None) -> bool:
    """Сбрасывает уровень скама пользователя."""
    try:
        if chat_id:
            # Сбрасываем для конкретной группы
            result = await session.execute(
                select(ScammerTracker).where(
                    ScammerTracker.user_id == user_id,
                    ScammerTracker.chat_id == chat_id
                )
            )
            record = result.scalar_one_or_none()
            if record:
                record.scammer_level = 0
                record.is_scammer = False
                record.notes = f"Уровень скама сброшен администратором {datetime.utcnow()}"
                record.updated_at = datetime.utcnow()
                await session.commit()
                logger.info(f"✅ Сброшен уровень скама для пользователя {user_id} в группе {chat_id}")
                return True
        else:
            # Сбрасываем для всех групп
            result = await session.execute(
                select(ScammerTracker).where(ScammerTracker.user_id == user_id)
            )
            records = result.scalars().all()
            for record in records:
                record.scammer_level = 0
                record.is_scammer = False
                record.notes = f"Уровень скама сброшен администратором {datetime.utcnow()}"
                record.updated_at = datetime.utcnow()
            await session.commit()
            logger.info(f"✅ Сброшен уровень скама для пользователя {user_id} во всех группах")
            return True
        
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при сбросе уровня скама: {e}")
        await session.rollback()
        return False
