# ============================================================
# СЕРВИС ЭКСПОРТА/ИМПОРТА НАСТРОЕК ГРУППЫ
# ============================================================
# Этот модуль реализует:
# - Экспорт настроек группы в JSON формат
# - Импорт настроек из JSON в другую группу
# - Расширяемый реестр таблиц (TABLE_REGISTRY)
#
# Архитектура:
# 1. TABLE_REGISTRY содержит конфигурацию каждой экспортируемой таблицы
# 2. При экспорте: читаем данные из БД → конвертируем в словарь
# 3. При импорте: читаем словарь → создаём/обновляем записи в БД
# ============================================================

# Импортируем стандартные библиотеки
import json
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional, TypedDict, Callable
from dataclasses import dataclass

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

# Импортируем модели данных для экспорта
from bot.database.models import ChatSettings, CaptchaSettings
from bot.database.models_content_filter import (
    ContentFilterSettings,
    FilterWord,
    FilterWhitelist,
    ScamPattern,
    ScamSignalCategory,
)
from bot.database.models_antispam import AntiSpamRule, AntiSpamWhitelist
from bot.database.models_profile_monitor import ProfileMonitorSettings

# Создаём логгер для отслеживания операций экспорта/импорта
logger = logging.getLogger(__name__)


# ============================================================
# КОНФИГУРАЦИЯ РЕЕСТРА ТАБЛИЦ
# ============================================================
# Этот dataclass описывает как экспортировать/импортировать одну таблицу

@dataclass
class TableConfig:
    """
    Конфигурация для экспорта/импорта одной таблицы.

    Attributes:
        model: SQLAlchemy модель таблицы (класс)
        key_name: Название ключа в JSON (например 'filter_words')
        chat_id_column: Имя колонки с ID чата (обычно 'chat_id')
        exclude_columns: Колонки которые НЕ экспортировать (id, created_at, etc.)
        is_settings: True если это таблица настроек (одна запись на группу)
    """
    # SQLAlchemy модель таблицы
    model: Any
    # Название ключа в JSON для этой таблицы
    key_name: str
    # Имя колонки содержащей chat_id
    chat_id_column: str = 'chat_id'
    # Колонки которые исключаем из экспорта (служебные)
    exclude_columns: tuple = ('id', 'created_at', 'updated_at', 'created_by', 'added_by', 'added_at')
    # Является ли таблица настройками (одна запись на группу)
    is_settings: bool = False


# ============================================================
# РЕЕСТР ТАБЛИЦ ДЛЯ ЭКСПОРТА
# ============================================================
# Для добавления новой таблицы: добавить новый TableConfig в этот список
# Порядок важен для импорта (зависимости сначала)

TABLE_REGISTRY: List[TableConfig] = [
    # ─────────────────────────────────────────────────────────
    # НАСТРОЙКИ ГРУПП (settings-таблицы, одна запись на группу)
    # ─────────────────────────────────────────────────────────

    # Основные настройки чата (капча, фильтры, муты)
    TableConfig(
        model=ChatSettings,
        key_name='chat_settings',
        chat_id_column='chat_id',
        # Исключаем username т.к. это идентификатор конкретной группы
        exclude_columns=('username',),
        is_settings=True,
    ),

    # Настройки капчи (устаревшие, но ещё используются)
    TableConfig(
        model=CaptchaSettings,
        key_name='captcha_settings',
        chat_id_column='group_id',
        exclude_columns=('created_at',),
        is_settings=True,
    ),

    # Настройки фильтра контента
    TableConfig(
        model=ContentFilterSettings,
        key_name='content_filter_settings',
        is_settings=True,
    ),

    # Настройки мониторинга профилей
    TableConfig(
        model=ProfileMonitorSettings,
        key_name='profile_monitor_settings',
        is_settings=True,
    ),

    # ─────────────────────────────────────────────────────────
    # ДАННЫЕ (много записей на группу)
    # ─────────────────────────────────────────────────────────

    # Запрещённые слова
    TableConfig(
        model=FilterWord,
        key_name='filter_words',
        # Исключаем id, created_at, created_by - они служебные
        exclude_columns=('id', 'created_at', 'created_by'),
    ),

    # Белый список слов
    TableConfig(
        model=FilterWhitelist,
        key_name='filter_whitelist',
        exclude_columns=('id', 'added_by', 'added_at'),
    ),

    # Паттерны скама
    TableConfig(
        model=ScamPattern,
        key_name='scam_patterns',
        exclude_columns=('id', 'created_at', 'created_by', 'triggers_count', 'last_triggered_at'),
    ),

    # Категории сигналов скама
    TableConfig(
        model=ScamSignalCategory,
        key_name='scam_signal_categories',
        exclude_columns=('id', 'created_at', 'updated_at', 'created_by'),
    ),

    # Правила антиспама
    TableConfig(
        model=AntiSpamRule,
        key_name='antispam_rules',
        exclude_columns=('id', 'created_at', 'updated_at'),
    ),

    # Белый список антиспама
    TableConfig(
        model=AntiSpamWhitelist,
        key_name='antispam_whitelist',
        exclude_columns=('id', 'added_by', 'added_at'),
    ),
]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _serialize_value(value: Any) -> Any:
    """
    Конвертирует значение в JSON-совместимый формат.

    Обрабатывает специальные типы:
    - datetime → ISO формат строки
    - date → ISO формат строки
    - Enum → строковое значение
    - остальное → как есть

    Args:
        value: Значение для конвертации

    Returns:
        JSON-совместимое значение
    """
    # Если значение None - возвращаем как есть
    if value is None:
        return None

    # datetime конвертируем в ISO строку
    if isinstance(value, datetime):
        return value.isoformat()

    # date конвертируем в ISO строку
    if isinstance(value, date):
        return value.isoformat()

    # Enum конвертируем в строковое значение
    if hasattr(value, 'value'):
        return value.value

    # Остальные типы возвращаем как есть
    return value


def _deserialize_value(value: Any, column_type: Any) -> Any:
    """
    Конвертирует JSON значение обратно в тип колонки.

    Args:
        value: Значение из JSON
        column_type: Тип колонки SQLAlchemy

    Returns:
        Значение в нужном типе для БД
    """
    # Если значение None - возвращаем как есть
    if value is None:
        return None

    # Получаем имя типа колонки
    type_name = str(column_type).upper()

    # Для DateTime конвертируем из ISO строки
    if 'DATETIME' in type_name and isinstance(value, str):
        return datetime.fromisoformat(value)

    # Остальные типы возвращаем как есть
    return value


def _model_to_dict(
    instance: Any,
    exclude_columns: tuple,
    chat_id_column: str,
) -> Dict[str, Any]:
    """
    Конвертирует SQLAlchemy модель в словарь для JSON.

    Args:
        instance: Экземпляр модели
        exclude_columns: Колонки которые исключить
        chat_id_column: Имя колонки с chat_id (тоже исключаем)

    Returns:
        Словарь с данными модели
    """
    # Получаем маппер модели для доступа к колонкам
    mapper = inspect(instance.__class__)

    # Результирующий словарь
    result = {}

    # Проходим по всем колонкам модели
    for column in mapper.columns:
        # Получаем имя колонки
        col_name = column.key

        # Пропускаем исключённые колонки
        if col_name in exclude_columns:
            continue

        # Пропускаем колонку chat_id (она будет заменена при импорте)
        if col_name == chat_id_column:
            continue

        # Получаем значение колонки
        value = getattr(instance, col_name)

        # Сериализуем значение и добавляем в результат
        result[col_name] = _serialize_value(value)

    return result


# ============================================================
# ОСНОВНЫЕ ФУНКЦИИ ЭКСПОРТА
# ============================================================

async def export_group_settings(
    session: AsyncSession,
    chat_id: int,
) -> Dict[str, Any]:
    """
    Экспортирует все настройки группы в словарь.

    Читает данные из всех таблиц зарегистрированных в TABLE_REGISTRY
    и формирует единый словарь для сериализации в JSON.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID группы для экспорта

    Returns:
        Словарь со всеми настройками группы
    """
    # Логируем начало экспорта
    logger.info(f"📤 [EXPORT] Начало экспорта настроек для chat_id={chat_id}")

    # Результирующий словарь с метаданными
    result = {
        # Версия формата экспорта (для совместимости при импорте)
        'export_version': '1.0',
        # Дата и время экспорта
        'exported_at': datetime.utcnow().isoformat(),
        # ID группы-источника (для информации)
        'source_chat_id': chat_id,
        # Данные настроек (будут заполнены ниже)
        'data': {},
    }

    # Проходим по всем зарегистрированным таблицам
    for config in TABLE_REGISTRY:
        # Получаем имя колонки chat_id для этой модели
        chat_id_col = getattr(config.model, config.chat_id_column)

        # Формируем запрос на выборку данных
        query = select(config.model).where(chat_id_col == chat_id)

        # Выполняем запрос
        db_result = await session.execute(query)

        # Для settings-таблиц берём одну запись
        if config.is_settings:
            # Получаем единственную запись (или None)
            instance = db_result.scalar_one_or_none()

            if instance:
                # Конвертируем в словарь
                result['data'][config.key_name] = _model_to_dict(
                    instance,
                    config.exclude_columns,
                    config.chat_id_column,
                )
                # Логируем успех
                logger.debug(f"  ✓ {config.key_name}: 1 запись")
        else:
            # Для data-таблиц берём все записи
            instances = db_result.scalars().all()

            # Конвертируем каждую запись в словарь
            result['data'][config.key_name] = [
                _model_to_dict(inst, config.exclude_columns, config.chat_id_column)
                for inst in instances
            ]

            # Логируем количество записей
            count = len(result['data'][config.key_name])
            if count > 0:
                logger.debug(f"  ✓ {config.key_name}: {count} записей")

    # Логируем завершение экспорта
    total_keys = len([k for k, v in result['data'].items() if v])
    logger.info(f"📤 [EXPORT] Экспорт завершён: {total_keys} секций с данными")

    return result


async def import_group_settings(
    session: AsyncSession,
    chat_id: int,
    data: Dict[str, Any],
    user_id: int,
    merge: bool = False,
) -> Dict[str, int]:
    """
    Импортирует настройки из словаря в группу.

    Args:
        session: Асинхронная сессия БД
        chat_id: ID группы для импорта
        data: Словарь с настройками (результат export_group_settings)
        user_id: ID пользователя который делает импорт (для аудита)
        merge: True = добавить к существующим, False = заменить полностью

    Returns:
        Словарь со статистикой: {'filter_words': 5, 'scam_patterns': 3, ...}
    """
    # Логируем начало импорта
    logger.info(
        f"📥 [IMPORT] Начало импорта настроек в chat_id={chat_id}, "
        f"merge={merge}, user_id={user_id}"
    )

    # Проверяем формат данных
    if 'data' not in data:
        raise ValueError("Неверный формат данных: отсутствует ключ 'data'")

    # Словарь со статистикой импорта
    stats: Dict[str, int] = {}

    # Данные для импорта
    import_data = data['data']

    # Проходим по всем зарегистрированным таблицам
    for config in TABLE_REGISTRY:
        # Проверяем есть ли данные для этой таблицы
        if config.key_name not in import_data:
            continue

        # Получаем данные для импорта
        table_data = import_data[config.key_name]

        # Пропускаем пустые данные
        if not table_data:
            continue

        # Получаем колонку chat_id
        chat_id_col = getattr(config.model, config.chat_id_column)

        # Если не merge - удаляем старые данные
        if not merge:
            # Удаляем все записи для этой группы
            delete_stmt = delete(config.model).where(chat_id_col == chat_id)
            await session.execute(delete_stmt)
            logger.debug(f"  🗑️ {config.key_name}: удалены старые записи")

        # Для settings-таблиц создаём одну запись
        if config.is_settings:
            # table_data это словарь
            new_data = dict(table_data)
            # Добавляем chat_id
            new_data[config.chat_id_column] = chat_id

            # Создаём новую запись
            instance = config.model(**new_data)

            # Если merge - используем merge, иначе add
            if merge:
                await session.merge(instance)
            else:
                session.add(instance)

            stats[config.key_name] = 1
            logger.debug(f"  ✓ {config.key_name}: импортированы настройки")
        else:
            # Для data-таблиц создаём много записей
            count = 0
            for item in table_data:
                # Копируем данные
                new_data = dict(item)
                # Добавляем chat_id
                new_data[config.chat_id_column] = chat_id

                # Добавляем user_id если есть колонка created_by/added_by
                if hasattr(config.model, 'created_by'):
                    new_data['created_by'] = user_id
                if hasattr(config.model, 'added_by'):
                    new_data['added_by'] = user_id

                # Создаём новую запись
                instance = config.model(**new_data)
                session.add(instance)
                count += 1

            stats[config.key_name] = count
            if count > 0:
                logger.debug(f"  ✓ {config.key_name}: импортировано {count} записей")

    # Сохраняем изменения
    await session.commit()

    # Логируем завершение импорта
    total_imported = sum(stats.values())
    logger.info(f"📥 [IMPORT] Импорт завершён: {total_imported} записей в {len(stats)} таблиц")

    return stats


# ============================================================
# ФУНКЦИИ СЕРИАЛИЗАЦИИ/ДЕСЕРИАЛИЗАЦИИ JSON
# ============================================================

def serialize_settings_to_json(data: Dict[str, Any], indent: int = 2) -> str:
    """
    Сериализует словарь настроек в JSON строку.

    Args:
        data: Словарь с настройками (результат export_group_settings)
        indent: Отступ для форматирования (по умолчанию 2 пробела)

    Returns:
        JSON строка с настройками
    """
    return json.dumps(data, ensure_ascii=False, indent=indent)


def deserialize_settings_from_json(json_string: str) -> Dict[str, Any]:
    """
    Десериализует JSON строку в словарь настроек.

    Args:
        json_string: JSON строка с настройками

    Returns:
        Словарь с настройками для передачи в import_group_settings

    Raises:
        ValueError: Если JSON невалидный
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError(f"Неверный формат JSON: {e}")


# ============================================================
# ФУНКЦИЯ ВАЛИДАЦИИ ДАННЫХ
# ============================================================

def validate_import_data(data: Dict[str, Any]) -> List[str]:
    """
    Валидирует данные перед импортом.

    Проверяет:
    - Наличие обязательных ключей
    - Версию формата
    - Корректность структуры данных

    Args:
        data: Словарь с данными для импорта

    Returns:
        Список ошибок (пустой если всё ок)
    """
    errors = []

    # Проверяем наличие ключа data
    if 'data' not in data:
        errors.append("Отсутствует обязательный ключ 'data'")
        return errors

    # Проверяем версию формата
    version = data.get('export_version', '1.0')
    if version != '1.0':
        errors.append(f"Неподдерживаемая версия формата: {version}")

    # Проверяем что data это словарь
    if not isinstance(data['data'], dict):
        errors.append("Ключ 'data' должен быть словарём")
        return errors

    # Проверяем известные ключи
    known_keys = {config.key_name for config in TABLE_REGISTRY}
    for key in data['data'].keys():
        if key not in known_keys:
            # Это не ошибка - просто предупреждение о неизвестном ключе
            logger.warning(f"⚠️ Неизвестный ключ в данных: {key}")

    return errors
