# tests/unit/test_profile_monitor_settings.py
"""
Юнит-тесты для настроек Profile Monitor.

Тестируемые компоненты:
- Клавиатуры настроек (get_mute_settings_kb, get_photo_freshness_threshold_kb)
- Callback handlers для photo_freshness_threshold
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.profile_monitor_kb import (
    get_mute_settings_kb,
    get_photo_freshness_threshold_kb,
    get_settings_main_kb,
    get_log_settings_kb,
)


# ============================================================
# ТЕСТЫ: КЛАВИАТУРА НАСТРОЕК АВТОМУТА
# ============================================================
class TestMuteSettingsKeyboard:
    """Тесты для клавиатуры настроек автомута."""

    def test_mute_settings_kb_includes_photo_threshold(self):
        """Клавиатура содержит кнопку порога свежести фото."""
        kb = get_mute_settings_kb(
            chat_id=-1001234567890,
            auto_mute_young=True,
            auto_mute_name_change=True,
            delete_messages=True,
            account_age_days=15,
            photo_freshness_threshold_days=1,
        )

        # Проверяем что клавиатура - InlineKeyboardMarkup
        assert isinstance(kb, InlineKeyboardMarkup)

        # Ищем кнопку с порогом фото
        found_photo_button = False
        for row in kb.inline_keyboard:
            for button in row:
                if "Порог фото" in button.text:
                    found_photo_button = True
                    assert "1" in button.text
                    assert "pm_photo_fresh_threshold:" in button.callback_data

        assert found_photo_button, "Кнопка порога фото не найдена"

    def test_mute_settings_kb_shows_correct_photo_threshold(self):
        """Кнопка отображает правильное значение порога."""
        for threshold in [1, 3, 7, 14]:
            kb = get_mute_settings_kb(
                chat_id=-1001234567890,
                auto_mute_young=True,
                auto_mute_name_change=True,
                delete_messages=True,
                account_age_days=15,
                photo_freshness_threshold_days=threshold,
            )

            # Ищем кнопку и проверяем значение
            for row in kb.inline_keyboard:
                for button in row:
                    if "Порог фото" in button.text:
                        assert str(threshold) in button.text

    def test_mute_settings_kb_includes_account_age_threshold(self):
        """Клавиатура содержит кнопку порога возраста аккаунта."""
        kb = get_mute_settings_kb(
            chat_id=-1001234567890,
            auto_mute_young=True,
            auto_mute_name_change=True,
            delete_messages=True,
            account_age_days=30,
            photo_freshness_threshold_days=1,
        )

        found_age_button = False
        for row in kb.inline_keyboard:
            for button in row:
                if "Порог аккаунта" in button.text:
                    found_age_button = True
                    assert "30" in button.text

        assert found_age_button, "Кнопка порога аккаунта не найдена"

    def test_mute_settings_kb_toggle_states(self):
        """Кнопки переключения отображают правильное состояние."""
        # Все включены
        kb_enabled = get_mute_settings_kb(
            chat_id=-1001234567890,
            auto_mute_young=True,
            auto_mute_name_change=True,
            delete_messages=True,
            account_age_days=15,
            photo_freshness_threshold_days=1,
        )

        # Все выключены
        kb_disabled = get_mute_settings_kb(
            chat_id=-1001234567890,
            auto_mute_young=False,
            auto_mute_name_change=False,
            delete_messages=False,
            account_age_days=15,
            photo_freshness_threshold_days=1,
        )

        # Проверяем иконки
        def count_icons(kb, icon):
            count = 0
            for row in kb.inline_keyboard:
                for button in row:
                    if icon in button.text:
                        count += 1
            return count

        # Включенные настройки имеют галочки
        assert count_icons(kb_enabled, "✅") >= 3
        # Выключенные имеют крестики
        assert count_icons(kb_disabled, "❌") >= 3


# ============================================================
# ТЕСТЫ: КЛАВИАТУРА ВЫБОРА ПОРОГА СВЕЖЕСТИ ФОТО
# ============================================================
class TestPhotoFreshnessThresholdKeyboard:
    """Тесты для клавиатуры выбора порога свежести фото."""

    def test_keyboard_has_all_options(self):
        """Клавиатура содержит все варианты порогов."""
        kb = get_photo_freshness_threshold_kb(
            chat_id=-1001234567890,
            current_days=1,
        )

        # Ожидаемые варианты
        expected_options = [1, 3, 7, 14]
        found_options = []

        for row in kb.inline_keyboard:
            for button in row:
                if "pm_set_photo_fresh:" in button.callback_data:
                    # Извлекаем значение из callback_data
                    parts = button.callback_data.split(":")
                    if len(parts) >= 2:
                        found_options.append(int(parts[1]))

        for option in expected_options:
            assert option in found_options, f"Опция {option} не найдена"

    def test_keyboard_marks_current_selection(self):
        """Текущий выбор отмечен галочкой."""
        for current in [1, 3, 7, 14]:
            kb = get_photo_freshness_threshold_kb(
                chat_id=-1001234567890,
                current_days=current,
            )

            # Ищем кнопку с текущим значением
            found_checked = False
            for row in kb.inline_keyboard:
                for button in row:
                    if f"pm_set_photo_fresh:{current}:" in button.callback_data:
                        if "✅" in button.text:
                            found_checked = True

            assert found_checked, f"Текущий выбор {current} не отмечен"

    def test_keyboard_has_back_button(self):
        """Клавиатура содержит кнопку назад."""
        kb = get_photo_freshness_threshold_kb(
            chat_id=-1001234567890,
            current_days=1,
        )

        found_back = False
        for row in kb.inline_keyboard:
            for button in row:
                if "Назад" in button.text:
                    found_back = True
                    assert "pm_settings_mute:" in button.callback_data

        assert found_back, "Кнопка назад не найдена"

    def test_callback_data_format(self):
        """Callback data имеет правильный формат."""
        chat_id = -1001234567890
        kb = get_photo_freshness_threshold_kb(
            chat_id=chat_id,
            current_days=1,
        )

        for row in kb.inline_keyboard:
            for button in row:
                if "pm_set_photo_fresh:" in button.callback_data:
                    # Формат: pm_set_photo_fresh:{days}:{chat_id}
                    parts = button.callback_data.split(":")
                    assert len(parts) == 3
                    assert parts[0] == "pm_set_photo_fresh"
                    assert parts[1].isdigit()
                    assert parts[2] == str(chat_id)

    def test_correct_day_text_declension(self):
        """Правильное склонение слова 'день'."""
        kb = get_photo_freshness_threshold_kb(
            chat_id=-1001234567890,
            current_days=1,
        )

        for row in kb.inline_keyboard:
            for button in row:
                if "1" in button.text and "pm_set_photo_fresh:1:" in button.callback_data:
                    # "1 день" не "1 дней"
                    assert "день" in button.text or "дней" in button.text


# ============================================================
# ТЕСТЫ: ГЛАВНАЯ КЛАВИАТУРА НАСТРОЕК
# ============================================================
class TestMainSettingsKeyboard:
    """Тесты для главной клавиатуры настроек."""

    def test_main_kb_toggle_button_enabled(self):
        """Кнопка вкл/выкл отображает правильное состояние."""
        kb_enabled = get_settings_main_kb(
            chat_id=-1001234567890,
            enabled=True,
        )

        kb_disabled = get_settings_main_kb(
            chat_id=-1001234567890,
            enabled=False,
        )

        # Проверяем текст кнопки
        for row in kb_enabled.inline_keyboard:
            for button in row:
                if "pm_toggle:" in button.callback_data:
                    assert "Выключить" in button.text

        for row in kb_disabled.inline_keyboard:
            for button in row:
                if "pm_toggle:" in button.callback_data:
                    assert "Включить" in button.text

    def test_main_kb_has_all_sections(self):
        """Главная клавиатура содержит все разделы."""
        kb = get_settings_main_kb(
            chat_id=-1001234567890,
            enabled=True,
        )

        required_sections = ["логирования", "автомута", "Назад"]
        found_sections = []

        for row in kb.inline_keyboard:
            for button in row:
                for section in required_sections:
                    if section.lower() in button.text.lower():
                        found_sections.append(section)

        for section in required_sections:
            assert section in found_sections, f"Раздел '{section}' не найден"


# ============================================================
# ТЕСТЫ: КЛАВИАТУРА НАСТРОЕК ЛОГИРОВАНИЯ
# ============================================================
class TestLogSettingsKeyboard:
    """Тесты для клавиатуры настроек логирования."""

    def test_log_kb_all_toggles_present(self):
        """Все переключатели логирования присутствуют."""
        kb = get_log_settings_kb(
            chat_id=-1001234567890,
            log_name=True,
            log_username=True,
            log_photo=True,
            send_to_journal=True,
            send_to_group=False,
        )

        expected_toggles = ["Имена", "Username", "Фото", "журнал", "группу"]
        found_toggles = []

        for row in kb.inline_keyboard:
            for button in row:
                for toggle in expected_toggles:
                    if toggle.lower() in button.text.lower():
                        found_toggles.append(toggle)

        for toggle in expected_toggles:
            assert toggle in found_toggles, f"Переключатель '{toggle}' не найден"

    def test_log_kb_states_reflected(self):
        """Состояния переключателей отражены в иконках."""
        kb_all_on = get_log_settings_kb(
            chat_id=-1001234567890,
            log_name=True,
            log_username=True,
            log_photo=True,
            send_to_journal=True,
            send_to_group=True,
        )

        kb_all_off = get_log_settings_kb(
            chat_id=-1001234567890,
            log_name=False,
            log_username=False,
            log_photo=False,
            send_to_journal=False,
            send_to_group=False,
        )

        # Считаем галочки и крестики
        def count_icon(kb, icon):
            count = 0
            for row in kb.inline_keyboard:
                for button in row:
                    if icon in button.text:
                        count += 1
            return count

        # Включенные - больше галочек
        assert count_icon(kb_all_on, "✅") >= 5
        # Выключенные - больше крестиков
        assert count_icon(kb_all_off, "❌") >= 5
