# ============================================================
# UNIT ТЕСТЫ ДЛЯ МОДУЛЯ ЭКСПОРТА/ИМПОРТА НАСТРОЕК
# ============================================================
# Тестируем:
# - Сериализацию/десериализацию JSON
# - Валидацию данных импорта
# - Вспомогательные функции
# ============================================================

import pytest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch

# Импортируем тестируемые модули
from bot.services.settings_export.export_service import (
    serialize_settings_to_json,
    deserialize_settings_from_json,
    validate_import_data,
    _serialize_value,
    _deserialize_value,
    TABLE_REGISTRY,
)


# ============================================================
# ТЕСТЫ СЕРИАЛИЗАЦИИ
# ============================================================

class TestSerializeValue:
    """Тесты функции _serialize_value."""

    def test_serialize_none(self):
        """None должен возвращаться как None."""
        result = _serialize_value(None)
        assert result is None

    def test_serialize_datetime(self):
        """datetime должен конвертироваться в ISO строку."""
        dt = datetime(2025, 12, 21, 15, 30, 0)
        result = _serialize_value(dt)
        assert result == "2025-12-21T15:30:00"

    def test_serialize_date(self):
        """date должен конвертироваться в ISO строку."""
        d = date(2025, 12, 21)
        result = _serialize_value(d)
        assert result == "2025-12-21"

    def test_serialize_string(self):
        """Строки должны возвращаться как есть."""
        result = _serialize_value("test string")
        assert result == "test string"

    def test_serialize_integer(self):
        """Числа должны возвращаться как есть."""
        result = _serialize_value(42)
        assert result == 42

    def test_serialize_boolean(self):
        """Булевы значения должны возвращаться как есть."""
        assert _serialize_value(True) is True
        assert _serialize_value(False) is False

    def test_serialize_enum(self):
        """Enum должен конвертироваться в строковое значение."""
        # Создаём мок enum
        mock_enum = MagicMock()
        mock_enum.value = "TEST_VALUE"
        result = _serialize_value(mock_enum)
        assert result == "TEST_VALUE"


# ============================================================
# ТЕСТЫ JSON СЕРИАЛИЗАЦИИ/ДЕСЕРИАЛИЗАЦИИ
# ============================================================

class TestJsonSerialization:
    """Тесты функций serialize/deserialize JSON."""

    def test_serialize_simple_dict(self):
        """Простой словарь должен корректно сериализоваться."""
        data = {
            "export_version": "1.0",
            "data": {
                "filter_words": [{"word": "test", "normalized": "test"}]
            }
        }
        result = serialize_settings_to_json(data)
        assert '"export_version": "1.0"' in result
        assert '"word": "test"' in result

    def test_deserialize_valid_json(self):
        """Валидный JSON должен корректно десериализоваться."""
        json_str = '{"export_version": "1.0", "data": {}}'
        result = deserialize_settings_from_json(json_str)
        assert result["export_version"] == "1.0"
        assert result["data"] == {}

    def test_deserialize_invalid_json_raises_error(self):
        """Невалидный JSON должен вызывать ValueError."""
        with pytest.raises(ValueError):
            deserialize_settings_from_json("{ invalid json }")

    def test_serialize_with_indent(self):
        """Сериализация должна поддерживать отступы."""
        data = {"key": "value"}
        result = serialize_settings_to_json(data, indent=4)
        # Проверяем что есть отступы (4 пробела)
        assert "    " in result

    def test_serialize_unicode(self):
        """Unicode символы должны сериализоваться корректно."""
        data = {"word": "запрещённое слово"}
        result = serialize_settings_to_json(data)
        # ensure_ascii=False позволяет сохранять кириллицу
        assert "запрещённое слово" in result


# ============================================================
# ТЕСТЫ ВАЛИДАЦИИ ДАННЫХ ИМПОРТА
# ============================================================

class TestValidateImportData:
    """Тесты функции validate_import_data."""

    def test_valid_data(self):
        """Валидные данные не должны возвращать ошибок."""
        data = {
            "export_version": "1.0",
            "data": {
                "filter_words": []
            }
        }
        errors = validate_import_data(data)
        assert errors == []

    def test_missing_data_key(self):
        """Отсутствие ключа 'data' должно возвращать ошибку."""
        data = {"export_version": "1.0"}
        errors = validate_import_data(data)
        assert len(errors) == 1
        assert "data" in errors[0]

    def test_unsupported_version(self):
        """Неподдерживаемая версия должна возвращать ошибку."""
        data = {
            "export_version": "2.0",
            "data": {}
        }
        errors = validate_import_data(data)
        assert len(errors) == 1
        assert "версия" in errors[0].lower()

    def test_data_not_dict(self):
        """Если 'data' не словарь, должна быть ошибка."""
        data = {
            "export_version": "1.0",
            "data": "not a dict"
        }
        errors = validate_import_data(data)
        assert len(errors) == 1
        assert "словарём" in errors[0]


# ============================================================
# ТЕСТЫ РЕЕСТРА ТАБЛИЦ
# ============================================================

class TestTableRegistry:
    """Тесты реестра таблиц TABLE_REGISTRY."""

    def test_registry_not_empty(self):
        """Реестр должен содержать таблицы."""
        assert len(TABLE_REGISTRY) > 0

    def test_each_config_has_required_fields(self):
        """Каждая конфигурация должна иметь обязательные поля."""
        for config in TABLE_REGISTRY:
            # model должен быть классом
            assert config.model is not None
            # key_name должен быть строкой
            assert isinstance(config.key_name, str)
            assert len(config.key_name) > 0
            # chat_id_column должен быть строкой
            assert isinstance(config.chat_id_column, str)

    def test_key_names_are_unique(self):
        """Ключи таблиц должны быть уникальными."""
        key_names = [config.key_name for config in TABLE_REGISTRY]
        assert len(key_names) == len(set(key_names))

    def test_contains_filter_words(self):
        """Реестр должен содержать filter_words."""
        key_names = [config.key_name for config in TABLE_REGISTRY]
        assert "filter_words" in key_names

    def test_contains_antispam_rules(self):
        """Реестр должен содержать antispam_rules."""
        key_names = [config.key_name for config in TABLE_REGISTRY]
        assert "antispam_rules" in key_names

    def test_contains_scam_patterns(self):
        """Реестр должен содержать scam_patterns."""
        key_names = [config.key_name for config in TABLE_REGISTRY]
        assert "scam_patterns" in key_names


# ============================================================
# ТЕСТЫ ДЕСЕРИАЛИЗАЦИИ ЗНАЧЕНИЙ
# ============================================================

class TestDeserializeValue:
    """Тесты функции _deserialize_value."""

    def test_deserialize_none(self):
        """None должен возвращаться как None."""
        result = _deserialize_value(None, "VARCHAR")
        assert result is None

    def test_deserialize_datetime_string(self):
        """ISO строка должна конвертироваться обратно в datetime."""
        dt_str = "2025-12-21T15:30:00"
        result = _deserialize_value(dt_str, "DATETIME")
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 21

    def test_deserialize_regular_value(self):
        """Обычные значения должны возвращаться как есть."""
        result = _deserialize_value("test", "VARCHAR")
        assert result == "test"

        result = _deserialize_value(42, "INTEGER")
        assert result == 42


# ============================================================
# ИНТЕГРАЦИОННЫЙ ТЕСТ СЕРИАЛИЗАЦИИ/ДЕСЕРИАЛИЗАЦИИ
# ============================================================

class TestSerializeDeserializeCycle:
    """Тесты полного цикла сериализации/десериализации."""

    def test_full_cycle(self):
        """Данные должны сохраняться после полного цикла."""
        original_data = {
            "export_version": "1.0",
            "exported_at": "2025-12-21T15:30:00",
            "source_chat_id": -1001234567890,
            "data": {
                "filter_words": [
                    {"word": "тест", "normalized": "тест", "match_type": "word"},
                    {"word": "спам", "normalized": "спам", "match_type": "phrase"},
                ],
                "chat_settings": {
                    "captcha_join_enabled": True,
                    "captcha_timeout_seconds": 300,
                }
            }
        }

        # Сериализуем
        json_str = serialize_settings_to_json(original_data)

        # Десериализуем
        restored_data = deserialize_settings_from_json(json_str)

        # Проверяем что данные сохранились
        assert restored_data["export_version"] == original_data["export_version"]
        assert restored_data["source_chat_id"] == original_data["source_chat_id"]
        assert len(restored_data["data"]["filter_words"]) == 2
        assert restored_data["data"]["filter_words"][0]["word"] == "тест"
        assert restored_data["data"]["chat_settings"]["captcha_join_enabled"] is True
