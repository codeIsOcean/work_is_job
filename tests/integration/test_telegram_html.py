# tests/integration/test_telegram_html.py
"""
Интеграционные тесты для проверки HTML сообщений через реальный Telegram API.

Эти тесты отправляют реальные сообщения в тестовую группу и проверяют,
что Telegram API принимает HTML разметку без ошибок.

Запуск:
    pytest tests/integration/test_telegram_html.py -v

Требования:
    - .env.test с TEST_BOT_TOKEN и TEST_CHAT_ID
    - Бот должен быть админом в тестовой группе
"""

import os
import pytest
import asyncio
from pathlib import Path
from dotenv import load_dotenv

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

# Загружаем тестовые креды
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(env_test_path)

TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")


# Skip all tests if credentials not available
pytestmark = pytest.mark.skipif(
    not TEST_BOT_TOKEN or not TEST_CHAT_ID,
    reason="TEST_BOT_TOKEN or TEST_CHAT_ID not set in .env.test"
)


@pytest.fixture
async def bot():
    """Создаёт реальный Bot instance для тестов."""
    bot = Bot(token=TEST_BOT_TOKEN)
    yield bot
    await bot.session.close()


@pytest.fixture
def chat_id():
    """Возвращает ID тестового чата."""
    return int(TEST_CHAT_ID)


# ============================================================
# ТЕСТЫ: БАЗОВЫЙ HTML
# ============================================================
class TestBasicHtml:
    """Тесты базовых HTML тегов."""

    @pytest.mark.asyncio
    async def test_bold_tag(self, bot: Bot, chat_id: int):
        """<b> тег работает."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<b>Bold text</b>",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_italic_tag(self, bot: Bot, chat_id: int):
        """<i> тег работает."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<i>Italic text</i>",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_code_tag(self, bot: Bot, chat_id: int):
        """<code> тег работает."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<code>code text</code>",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_combined_tags(self, bot: Bot, chat_id: int):
        """Комбинация тегов работает."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<b>Bold</b> and <i>italic</i> and <code>code</code>",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)


# ============================================================
# ТЕСТЫ: ЭКРАНИРОВАНИЕ СПЕЦСИМВОЛОВ
# ============================================================
class TestHtmlEscaping:
    """Тесты экранирования HTML спецсимволов."""

    @pytest.mark.asyncio
    async def test_escaped_lt(self, bot: Bot, chat_id: int):
        """&lt; правильно отображается как <."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="Value &lt;5",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_escaped_gt(self, bot: Bot, chat_id: int):
        """&gt; правильно отображается как >."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="Value &gt;10",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_escaped_amp(self, bot: Bot, chat_id: int):
        """&amp; правильно отображается как &."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="A &amp; B",
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_unescaped_lt_fails(self, bot: Bot, chat_id: int):
        """Неэкранированный < с цифрой вызывает ошибку."""
        with pytest.raises(TelegramBadRequest) as exc_info:
            await bot.send_message(
                chat_id=chat_id,
                text="Value <5",  # Это вызовет ошибку!
                parse_mode=ParseMode.HTML
            )
        assert "start tag" in str(exc_info.value).lower()


# ============================================================
# ТЕСТЫ: РЕАЛЬНЫЕ СЦЕНАРИИ ИЗ БОТА
# ============================================================
class TestRealBotScenarios:
    """Тесты реальных текстов из бота."""

    @pytest.mark.asyncio
    async def test_photo_freshness_criteria_fixed(self, bot: Bot, chat_id: int):
        """Исправленный текст критериев 4 и 5 работает."""
        # Это текст который вызывал ошибку до исправления
        text = (
            "⚡ <b>Настройки автомута</b>\n\n"
            "<b>Критерий 4:</b> Свежее фото (&lt;1 дн) + "
            "смена имени + сообщение ≤30 мин\n"
            "<b>Критерий 5:</b> Свежее фото (&lt;1 дн) + "
            "сообщение ≤30 мин"
        )
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_photo_freshness_criteria_buggy(self, bot: Bot, chat_id: int):
        """Баговый текст без экранирования вызывает ошибку."""
        # Это текст который вызывал TelegramBadRequest
        buggy_text = (
            "⚡ <b>Настройки автомута</b>\n\n"
            "<b>Критерий 4:</b> Свежее фото (<1 дн) + "
            "смена имени + сообщение ≤30 мин"
        )
        with pytest.raises(TelegramBadRequest):
            await bot.send_message(
                chat_id=chat_id,
                text=buggy_text,
                parse_mode=ParseMode.HTML
            )

    @pytest.mark.asyncio
    async def test_mute_settings_text(self, bot: Bot, chat_id: int):
        """Полный текст настроек автомута работает."""
        text = (
            "⚡ <b>Настройки автомута</b>\n\n"
            "🔇 Автомут новичков: ✅ Включен\n"
            "📝 Автомут при смене имени: ✅ Включен\n"
            "🗑 Удалять сообщения: ❌ Выключено\n\n"
            "<b>Пороги:</b>\n"
            "• Возраст аккаунта: &lt;15 дней\n"
            "• Свежесть фото: &lt;1 день\n"
            "• Окно первого сообщения: 30 мин\n\n"
            "<b>Критерии автомута:</b>\n"
            "<b>1.</b> Нет фото + возраст &lt;15 дн + сообщение ≤30 мин\n"
            "<b>2.</b> Нет фото + возраст &lt;15 дн + смена имени\n"
            "<b>3.</b> Смена имени + сообщение ≤30 мин\n"
            "<b>4.</b> Свежее фото (&lt;1 дн) + смена имени + сообщение ≤30 мин\n"
            "<b>5.</b> Свежее фото (&lt;1 дн) + сообщение ≤30 мин"
        )
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_photo_threshold_selection_text(self, bot: Bot, chat_id: int):
        """Текст выбора порога свежести фото работает."""
        text = (
            "📷 <b>Порог свежести фото</b>\n\n"
            "Выберите максимальный возраст фото, "
            "при котором оно считается \"свежим\".\n\n"
            "Текущий порог: <b>1 день</b>\n\n"
            "Фото моложе этого возраста + сообщение в течение 30 минут "
            "→ автоматический мут."
        )
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        assert msg is not None
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)


# ============================================================
# ТЕСТЫ: РЕДАКТИРОВАНИЕ СООБЩЕНИЙ
# ============================================================
class TestMessageEditing:
    """Тесты редактирования сообщений (как в callback handlers)."""

    @pytest.mark.asyncio
    async def test_edit_message_with_html(self, bot: Bot, chat_id: int):
        """Редактирование сообщения с HTML работает."""
        # Отправляем
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<b>Original</b>",
            parse_mode=ParseMode.HTML
        )

        # Редактируем
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text="<b>Edited</b> with &lt;special&gt; chars",
            parse_mode=ParseMode.HTML
        )

        # Удаляем
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)

    @pytest.mark.asyncio
    async def test_edit_fails_with_unescaped_lt(self, bot: Bot, chat_id: int):
        """Редактирование с неэкранированным < вызывает ошибку."""
        msg = await bot.send_message(
            chat_id=chat_id,
            text="<b>Original</b>",
            parse_mode=ParseMode.HTML
        )

        try:
            with pytest.raises(TelegramBadRequest):
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    text="Value <5 causes error",  # Это вызовет ошибку
                    parse_mode=ParseMode.HTML
                )
        finally:
            await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
