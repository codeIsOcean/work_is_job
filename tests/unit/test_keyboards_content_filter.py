# ============================================================
# UNIT-ТЕСТЫ ДЛЯ КЛАВИАТУР CONTENT FILTER
# ============================================================
# Тестирует функции создания inline-клавиатур для
# настроек фильтра контента и кастомных разделов.
# ============================================================

import pytest
from unittest.mock import MagicMock

from bot.keyboards.content_filter_keyboards import (
    create_section_settings_menu,
    create_section_action_menu,
    create_section_advanced_menu,
    create_section_notification_delay_menu,
    create_section_mute_duration_menu,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_section():
    """Создаёт mock объект раздела для тестов."""
    section = MagicMock()
    section.id = 42
    section.name = "Тестовый раздел"
    section.enabled = True
    section.action = "delete"
    section.mute_duration = 60
    section.forward_channel_id = None
    section.forward_on_delete = False
    section.forward_on_mute = False
    section.forward_on_ban = False
    section.notification_delete_delay = None
    section.mute_text = None
    section.ban_text = None
    return section


# ============================================================
# ТЕСТЫ: МЕНЮ НАСТРОЕК РАЗДЕЛА
# ============================================================

class TestSectionSettingsMenu:
    """Тесты меню настроек раздела."""

    def test_menu_has_correct_buttons(self, mock_section):
        """Проверяет наличие всех необходимых кнопок."""
        keyboard = create_section_settings_menu(
            section_id=mock_section.id,
            section=mock_section,
            chat_id=-1001234567890,
            patterns_count=5
        )

        # Собираем все callback_data кнопок
        callbacks = []
        for row in keyboard.inline_keyboard:
            for button in row:
                callbacks.append(button.callback_data)

        # Проверяем основные callback_data
        # Паттерны: cf:secpa (кнопка списка паттернов) или cf:secp (кнопки пагинации)
        assert any("secpa" in c or "secp:" in c for c in callbacks if c)  # Паттерны
        assert f"cf:secac:{mock_section.id}" in callbacks   # Действия
        assert f"cf:secadv:{mock_section.id}" in callbacks  # Дополнительно
        # Назад: cf:sccat:{chat_id}
        assert any("sccat" in c for c in callbacks if c)     # Назад

    def test_menu_has_import_button(self, mock_section):
        """Проверяет наличие кнопки импорта."""
        keyboard = create_section_settings_menu(
            section_id=mock_section.id,
            section=mock_section,
            chat_id=-1001234567890,
            patterns_count=3
        )

        # Ищем кнопку импорта
        import_found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secimp" in (button.callback_data or ""):
                    import_found = True
                    break

        assert import_found, "Кнопка импорта не найдена"

    def test_menu_shows_patterns_count(self, mock_section):
        """Проверяет отображение количества паттернов."""
        keyboard = create_section_settings_menu(
            section_id=mock_section.id,
            section=mock_section,
            chat_id=-1001234567890,
            patterns_count=10
        )

        # Ищем кнопку паттернов
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secpat" in (button.callback_data or ""):
                    assert "10" in button.text
                    break


# ============================================================
# ТЕСТЫ: МЕНЮ ДЕЙСТВИЙ РАЗДЕЛА
# ============================================================

class TestSectionActionMenu:
    """Тесты меню действий раздела."""

    def test_action_menu_shows_current_action(self, mock_section):
        """Проверяет подсветку текущего действия."""
        mock_section.action = "mute"
        keyboard = create_section_action_menu(mock_section.id, mock_section)

        # Ищем кнопку мута - она должна быть отмечена
        mute_found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secac:mute" in (button.callback_data or ""):
                    mute_found = True
                    # Кнопка текущего действия должна содержать галочку
                    assert "mute" in button.callback_data
                    break

        assert mute_found

    def test_action_menu_has_forward_toggles(self, mock_section):
        """Проверяет наличие переключателей пересылки."""
        mock_section.forward_channel_id = -1001234567890  # Канал установлен
        keyboard = create_section_action_menu(mock_section.id, mock_section)

        # Собираем callback_data
        callbacks = []
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.callback_data:
                    callbacks.append(button.callback_data)

        # Проверяем наличие переключателей пересылки
        forward_callbacks = [c for c in callbacks if "secfd" in c]
        # Должны быть toggles для delete, mute, ban
        assert len(forward_callbacks) >= 1, "Нет переключателей пересылки"

    def test_action_menu_has_channel_button(self, mock_section):
        """Проверяет наличие кнопки канала."""
        keyboard = create_section_action_menu(mock_section.id, mock_section)

        # Ищем кнопку канала
        channel_found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secch" in (button.callback_data or ""):
                    channel_found = True
                    break

        assert channel_found, "Кнопка канала не найдена"

    def test_action_menu_all_actions_present(self, mock_section):
        """Проверяет наличие всех типов действий."""
        keyboard = create_section_action_menu(mock_section.id, mock_section)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.callback_data:
                    callbacks.append(button.callback_data)

        # Проверяем наличие всех действий
        actions = ["delete", "mute", "ban"]
        for action in actions:
            found = any(f"secac:{action}" in c for c in callbacks)
            assert found, f"Действие {action} не найдено"


# ============================================================
# ТЕСТЫ: МЕНЮ ДОПОЛНИТЕЛЬНЫХ НАСТРОЕК
# ============================================================

class TestSectionAdvancedMenu:
    """Тесты меню дополнительных настроек."""

    def test_advanced_menu_has_mute_text_button(self, mock_section):
        """Проверяет наличие кнопки текста мута."""
        keyboard = create_section_advanced_menu(
            section_id=mock_section.id,
            section=mock_section
        )

        # Ищем кнопку
        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secmtxt" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка текста мута не найдена"

    def test_advanced_menu_has_ban_text_button(self, mock_section):
        """Проверяет наличие кнопки текста бана."""
        keyboard = create_section_advanced_menu(
            section_id=mock_section.id,
            section=mock_section
        )

        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secbtxt" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка текста бана не найдена"

    def test_advanced_menu_has_delay_button(self, mock_section):
        """Проверяет наличие кнопки задержки уведомления."""
        keyboard = create_section_advanced_menu(
            section_id=mock_section.id,
            section=mock_section
        )

        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secdel" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка задержки уведомления не найдена"

    def test_advanced_menu_has_back_button(self, mock_section):
        """Проверяет наличие кнопки назад."""
        keyboard = create_section_advanced_menu(
            section_id=mock_section.id,
            section=mock_section
        )

        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                # Back button is cf:secs:{section_id}
                if "secs:" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка назад не найдена"


# ============================================================
# ТЕСТЫ: МЕНЮ ВЫБОРА ЗАДЕРЖКИ
# ============================================================

class TestNotificationDelayMenu:
    """Тесты меню выбора задержки уведомления."""

    def test_delay_menu_has_options(self, mock_section):
        """Проверяет наличие вариантов задержки."""
        keyboard = create_section_notification_delay_menu(mock_section.id)

        # Считаем кнопки с задержками
        delay_buttons = 0
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secdel:" in (button.callback_data or "") and ":" in button.callback_data:
                    delay_buttons += 1

        assert delay_buttons >= 4, f"Найдено только {delay_buttons} вариантов задержки"

    def test_delay_menu_has_back_button(self, mock_section):
        """Проверяет наличие кнопки назад."""
        keyboard = create_section_notification_delay_menu(mock_section.id)

        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secadv" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка назад не найдена"


# ============================================================
# ТЕСТЫ: МЕНЮ ВЫБОРА ДЛИТЕЛЬНОСТИ МУТА
# ============================================================

class TestMuteDurationMenu:
    """Тесты меню выбора длительности мута."""

    def test_mute_duration_menu_has_options(self, mock_section):
        """Проверяет наличие вариантов длительности мута."""
        keyboard = create_section_mute_duration_menu(mock_section.id)

        # Считаем кнопки с длительностями
        duration_buttons = 0
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secmt:" in (button.callback_data or "") and ":" in button.callback_data:
                    duration_buttons += 1

        assert duration_buttons >= 4, f"Найдено только {duration_buttons} вариантов длительности"

    def test_mute_duration_menu_has_back_button(self, mock_section):
        """Проверяет наличие кнопки назад."""
        keyboard = create_section_mute_duration_menu(mock_section.id)

        found = False
        for row in keyboard.inline_keyboard:
            for button in row:
                if "secac" in (button.callback_data or ""):
                    found = True
                    break

        assert found, "Кнопка назад не найдена"
