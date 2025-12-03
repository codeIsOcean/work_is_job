"""
Хендлер для тестирования расширенного анализа профиля
Позволяет протестировать анализ возраста аккаунта и био
"""

import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from bot.services.enhanced_profile_analyzer import enhanced_profile_analyzer
from bot.services.account_age_estimator import account_age_estimator
from bot.services.bio_content_analyzer import bio_analyzer

logger = logging.getLogger(__name__)
enhanced_analysis_router = Router()


@enhanced_analysis_router.message(Command("test_analysis"))
async def test_enhanced_analysis(message: Message, bot: Bot):
    """Тестирует расширенный анализ профиля пользователя"""
    try:
        user_id = message.from_user.id
        user_data = {
            "id": user_id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
            "is_bot": message.from_user.is_bot,
            "is_premium": getattr(message.from_user, 'is_premium', False)
        }

        await message.answer("🔍 Запускаю расширенный анализ профиля...")

        # Анализ возраста аккаунта
        age_info = account_age_estimator.get_detailed_age_info(user_id)

        # Анализ био
        bio_text = "Тестовое био для проверки анализа"
        bio_analysis = bio_analyzer.analyze_bio_content(bio_text)

        # Полный анализ профиля
        full_analysis = await enhanced_profile_analyzer.analyze_user_profile_enhanced(user_data, bot)

        # Формируем отчет
        report = f"""
🔍 **РЕЗУЛЬТАТЫ РАСШИРЕННОГО АНАЛИЗА**

👤 **Пользователь:** {user_data['first_name']} (@{user_data['username']})
🆔 **ID:** {user_id}

📅 **АНАЛИЗ ВОЗРАСТА АККАУНТА:**
• Предполагаемая дата создания: {age_info['creation_date_str']}
• Возраст: {age_info['age_days']} дней
• Балл риска: {age_info['risk_score']}/100 ({age_info['risk_label']})
• Описание: {age_info['risk_description']}

📝 **АНАЛИЗ БИО:**
• Балл риска: {bio_analysis['risk_score']}/100
• Подозрительный: {bio_analysis['is_suspicious']}
• Категории: {', '.join(bio_analysis['categories']) if bio_analysis['categories'] else 'Нет'}
• Причина: {bio_analysis['reason']}

🎯 **ИТОГОВЫЙ РЕЗУЛЬТАТ:**
• Общий балл риска: {full_analysis['risk_score']}/100
• Подозрительный: {full_analysis['is_suspicious']}
• Причины: {', '.join(full_analysis['reasons']) if full_analysis['reasons'] else 'Нет'}
        """

        await message.answer(report, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при тестировании анализа: {e}")
        await message.answer(f"❌ Ошибка при анализе: {e}")


@enhanced_analysis_router.message(Command("test_bio"))
async def test_bio_analysis(message: Message):
    """Тестирует анализ био"""
    try:
        # Получаем текст после команды
        bio_text = message.text.replace("/test_bio", "").strip()

        if not bio_text:
            await message.answer("❌ Укажите текст био для анализа\nПример: /test_bio продам наркотики")
            return

        # Анализируем био
        analysis = bio_analyzer.analyze_bio_content(bio_text)

        report = f"""
📝 **АНАЛИЗ БИО:**

**Текст:** {bio_text}

**Результаты:**
• Балл риска: {analysis['risk_score']}/100
• Подозрительный: {analysis['is_suspicious']}
• Категории: {', '.join(analysis['categories']) if analysis['categories'] else 'Нет'}
• Причина: {analysis['reason']}

**Найденные паттерны:**
{chr(10).join(f"• {pattern}" for pattern in analysis['matched_patterns']) if analysis['matched_patterns'] else "• Нет"}
        """

        await message.answer(report, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при анализе био: {e}")
        await message.answer(f"❌ Ошибка при анализе био: {e}")


@enhanced_analysis_router.message(Command("test_age"))
async def test_age_analysis(message: Message):
    """Тестирует анализ возраста аккаунта"""
    try:
        user_id = message.from_user.id

        # Анализируем возраст
        age_info = account_age_estimator.get_detailed_age_info(user_id)

        report = f"""
📅 **АНАЛИЗ ВОЗРАСТА АККАУНТА:**

**Пользователь:** {message.from_user.first_name} (@{message.from_user.username})
**ID:** {user_id}

**Результаты:**
• Предполагаемая дата создания: {age_info['creation_date_str']}
• Возраст: {age_info['age_days']} дней
• Балл риска: {age_info['risk_score']}/100
• Категория: {age_info['risk_label']}
• Описание: {age_info['risk_description']}
        """

        await message.answer(report, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при анализе возраста: {e}")
        await message.answer(f"❌ Ошибка при анализе возраста: {e}")
