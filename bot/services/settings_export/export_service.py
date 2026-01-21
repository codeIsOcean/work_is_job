# ============================================================
# СЕРВИС ЭКСПОРТА/ИМПОРТА НАСТРОЕК ГРУППЫ (v2.0 - автосбор)
# ============================================================
# Этот модуль реализует:
# - Экспорт настроек группы в JSON формат
# - Импорт настроек из JSON в другую группу
# - АВТОМАТИЧЕСКИЙ сбор моделей через ExportableMixin
#
# Архитектура v2.0:
# 1. Модели с ExportableMixin автоматически регистрируются
# 2. При экспорте: читаем данные из БД → конвертируем в словарь
# 3. При импорте: читаем словарь → создаём/обновляем записи в БД
# 4. Поддержка связанных моделей (parent-child через __export_parent_key__)
#
# Добавление новой модели:
# 1. Добавить ExportableMixin к модели
# 2. Определить __export_key__ и другие атрибуты
# 3. Готово! Модель автоматически появится в экспорте
# ============================================================

# Импортируем стандартные библиотеки
import json
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Type

# Импортируем SQLAlchemy для работы с БД
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

# Импортируем миксин и функции для работы с реестром
from bot.database.exportable_mixin import (
    ExportableMixin,
    get_exportable_models,
    get_model_by_export_key,
    get_child_models,
)

# ============================================================
# ВАЖНО: Импортируем все модели чтобы они зарегистрировались
# ============================================================
# При импорте модели с ExportableMixin автоматически регистрируются
# в реестре через __init_subclass__. Этот импорт гарантирует что
# все модели будут доступны для экспорта/импорта.
#
# При добавлении новой модели с ExportableMixin добавьте её сюда!
# ============================================================

# Основные настройки (ChatSettings, CaptchaSettings)
from bot.database.models import ChatSettings, CaptchaSettings  # noqa: F401

# Content Filter (настройки, слова, паттерны, разделы)
from bot.database.models_content_filter import (  # noqa: F401
    ContentFilterSettings,
    FilterWord,
    FilterWhitelist,
    ScamPattern,
    ScamSignalCategory,
    ScamScoreThreshold,
    CustomSpamSection,
    CustomSectionPattern,
    CustomSectionThreshold,
    CrossMessagePattern,  # Паттерны кросс-сообщение детекции
    CrossMessageThreshold,  # Пороги действий кросс-сообщение детекции
)

# Антиспам (правила, белый список)
from bot.database.models_antispam import (  # noqa: F401
    AntiSpamRule,
    AntiSpamWhitelist,
)

# Profile Monitor (настройки)
from bot.database.models_profile_monitor import ProfileMonitorSettings  # noqa: F401

# Scam Media (настройки, хеши фото)
from bot.database.models_scam_media import (  # noqa: F401
    ScamMediaSettings,
    BannedImageHash,
)

# Anti-Raid (настройки, паттерны имён)
from bot.database.models_antiraid import (  # noqa: F401
    AntiRaidSettings,
    AntiRaidNamePattern,
)

# Manual Commands (ручные команды /amute, /aban, /akick)
from bot.database.models_manual_commands import (  # noqa: F401
    ManualCommandSettings,
)

# Создаём логгер для отслеживания операций экспорта/импорта
logger = logging.getLogger(__name__)

# Версия формата экспорта
# 1.0 - старый формат с TABLE_REGISTRY
# 2.0 - новый формат с ExportableMixin и поддержкой parent-child
EXPORT_VERSION = '2.0'


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

    # Для Date конвертируем из ISO строки
    if 'DATE' in type_name and 'DATETIME' not in type_name and isinstance(value, str):
        return date.fromisoformat(value)

    # Остальные типы возвращаем как есть
    return value


def _deserialize_dict_for_model(
    data: Dict[str, Any],
    model_class: Type[ExportableMixin],
) -> Dict[str, Any]:
    """
    Десериализует все значения в словаре для конкретной модели.

    Конвертирует строки в datetime/date и другие типы согласно
    типам колонок модели.

    Args:
        data: Словарь с данными (из JSON)
        model_class: Класс модели SQLAlchemy

    Returns:
        Словарь с конвертированными значениями
    """
    result = {}

    # Получаем маппер модели для доступа к колонкам
    mapper = inspect(model_class)

    # Создаём словарь колонок для быстрого доступа
    columns_by_name = {col.key: col for col in mapper.columns}

    for key, value in data.items():
        # Пропускаем служебные поля
        if key.startswith('_'):
            result[key] = value
            continue

        # Ищем соответствующую колонку
        if key in columns_by_name:
            column = columns_by_name[key]
            result[key] = _deserialize_value(value, column.type)
        else:
            # Колонка не найдена - оставляем значение как есть
            result[key] = value

    return result


def _model_to_dict(
    instance: Any,
    model_class: Type[ExportableMixin],
    include_parent_id: bool = False,
    include_own_id: bool = False,
) -> Dict[str, Any]:
    """
    Конвертирует SQLAlchemy модель в словарь для JSON.

    Args:
        instance: Экземпляр модели
        model_class: Класс модели с настройками экспорта
        include_parent_id: True = включить parent_column в экспорт
        include_own_id: True = включить собственный ID как _old_id

    Returns:
        Словарь с данными модели
    """
    # Получаем настройки экспорта из миксина
    exclude_columns = model_class.__export_exclude__
    chat_id_column = model_class.__export_chat_id_column__
    parent_column = model_class.__export_parent_column__

    # Получаем маппер модели для доступа к колонкам
    mapper = inspect(instance.__class__)

    # Результирующий словарь
    result = {}

    # Для родительских моделей сохраняем старый ID для маппинга
    if include_own_id and hasattr(instance, 'id'):
        result['_old_id'] = instance.id

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

        # Для дочерних моделей: сохраняем parent_column как _parent_id
        if col_name == parent_column:
            if include_parent_id:
                value = getattr(instance, col_name)
                result['_parent_id'] = _serialize_value(value)
            continue

        # Получаем значение колонки
        value = getattr(instance, col_name)

        # Сериализуем значение и добавляем в результат
        result[col_name] = _serialize_value(value)

    return result


# ============================================================
# ЭКСПОРТ МОДЕЛЕЙ ВЕРХНЕГО УРОВНЯ (с chat_id)
# ============================================================

async def _export_top_level_model(
    session: AsyncSession,
    model_class: Type[ExportableMixin],
    chat_id: int,
) -> Any:
    """
    Экспортирует модель верхнего уровня (привязанную к chat_id).

    Args:
        session: Сессия БД
        model_class: Класс модели
        chat_id: ID группы

    Returns:
        Словарь (для settings) или список словарей (для data)
    """
    # Получаем колонку chat_id
    chat_id_col = getattr(model_class, model_class.__export_chat_id_column__)

    # Формируем запрос
    query = select(model_class).where(chat_id_col == chat_id)

    # Выполняем запрос
    db_result = await session.execute(query)

    # Для settings-таблиц возвращаем один словарь
    if model_class.__export_is_settings__:
        instance = db_result.scalar_one_or_none()
        if instance:
            return _model_to_dict(instance, model_class)
        return None

    # Для data-таблиц возвращаем список
    instances = db_result.scalars().all()

    # Проверяем есть ли дочерние модели для этой модели
    # Если есть - нужно сохранить _old_id для маппинга
    child_models = get_child_models(model_class.__export_key__)
    has_children = len(child_models) > 0

    return [
        _model_to_dict(inst, model_class, include_parent_id=False, include_own_id=has_children)
        for inst in instances
    ]


# ============================================================
# ЭКСПОРТ ДОЧЕРНИХ МОДЕЛЕЙ (с parent_id)
# ============================================================

async def _export_child_model(
    session: AsyncSession,
    model_class: Type[ExportableMixin],
    parent_ids: List[int],
) -> List[Dict[str, Any]]:
    """
    Экспортирует дочернюю модель (привязанную к parent_id).

    Args:
        session: Сессия БД
        model_class: Класс дочерней модели
        parent_ids: Список ID родительских записей

    Returns:
        Список словарей с _parent_id для привязки
    """
    if not parent_ids:
        return []

    # Получаем колонку parent_id
    parent_col = getattr(model_class, model_class.__export_parent_column__)

    # Формируем запрос
    query = select(model_class).where(parent_col.in_(parent_ids))

    # Выполняем запрос
    db_result = await session.execute(query)
    instances = db_result.scalars().all()

    # Конвертируем с сохранением parent_id
    return [
        _model_to_dict(inst, model_class, include_parent_id=True)
        for inst in instances
    ]


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ ЭКСПОРТА
# ============================================================

async def export_group_settings(
    session: AsyncSession,
    chat_id: int,
) -> Dict[str, Any]:
    """
    Экспортирует все настройки группы в словарь.

    Автоматически собирает все модели с ExportableMixin
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
        # Версия формата экспорта
        'export_version': EXPORT_VERSION,
        # Дата и время экспорта
        'exported_at': datetime.utcnow().isoformat(),
        # ID группы-источника (для информации)
        'source_chat_id': chat_id,
        # Данные настроек (будут заполнены ниже)
        'data': {},
    }

    # Получаем все экспортируемые модели (отсортированы по order)
    models = get_exportable_models()

    # Словарь для хранения ID родительских записей (для дочерних моделей)
    # Формат: {'custom_spam_sections': [1, 2, 3], ...}
    parent_ids_map: Dict[str, List[int]] = {}

    # Проходим по всем моделям
    for model_class in models:
        key = model_class.__export_key__
        parent_key = model_class.__export_parent_key__

        # Если это дочерняя модель - экспортируем через parent_ids
        if parent_key is not None:
            parent_ids = parent_ids_map.get(parent_key, [])
            data = await _export_child_model(session, model_class, parent_ids)
        else:
            # Модель верхнего уровня - экспортируем по chat_id
            data = await _export_top_level_model(session, model_class, chat_id)

        # Сохраняем данные если они есть
        if data:
            result['data'][key] = data

            # Для родительских моделей верхнего уровня сохраняем ID для дочерних
            # (только для списков, не для settings, и только если есть chat_id)
            # Дочерние модели (parent_key != None) пропускаем - у них нет chat_id
            if (isinstance(data, list) and
                not model_class.__export_is_settings__ and
                parent_key is None):  # Только модели верхнего уровня!
                # Получаем ID из БД - нужно запросить снова
                chat_id_col = getattr(model_class, model_class.__export_chat_id_column__)
                query = select(model_class).where(chat_id_col == chat_id)
                db_result = await session.execute(query)
                instances = db_result.scalars().all()
                parent_ids_map[key] = [inst.id for inst in instances]

            # Логируем
            if isinstance(data, list):
                logger.debug(f"  ✓ {key}: {len(data)} записей")
            else:
                logger.debug(f"  ✓ {key}: 1 запись")

    # Логируем завершение экспорта
    total_keys = len([k for k, v in result['data'].items() if v])
    logger.info(f"📤 [EXPORT] Экспорт завершён: {total_keys} секций с данными")

    return result


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ ИМПОРТА
# ============================================================

async def import_group_settings(
    session: AsyncSession,
    chat_id: int,
    data: Dict[str, Any],
    user_id: int,
    merge: bool = False,
) -> Dict[str, int]:
    """
    Импортирует настройки из словаря в группу.

    Поддерживает как формат v1.0 (старый), так и v2.0 (с parent-child).

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

    # Маппинг старых ID на новые (для parent-child связей)
    # Формат: {'custom_spam_sections': {old_id: new_id, ...}, ...}
    id_mapping: Dict[str, Dict[int, int]] = {}

    # Получаем все экспортируемые модели (отсортированы по order)
    models = get_exportable_models()

    # Проходим по всем моделям
    for model_class in models:
        key = model_class.__export_key__
        parent_key = model_class.__export_parent_key__
        parent_column = model_class.__export_parent_column__

        # Проверяем есть ли данные для этой модели
        if key not in import_data:
            continue

        # Получаем данные для импорта
        table_data = import_data[key]

        # Пропускаем пустые данные
        if not table_data:
            continue

        # Если не merge - удаляем старые данные
        if not merge:
            if parent_key is not None:
                # Для дочерних моделей удаляем через parent_ids
                parent_mapping = id_mapping.get(parent_key, {})
                if parent_mapping:
                    parent_col = getattr(model_class, parent_column)
                    # Удаляем по новым parent_id (которые уже созданы)
                    delete_stmt = delete(model_class).where(
                        parent_col.in_(list(parent_mapping.values()))
                    )
                    await session.execute(delete_stmt)
            else:
                # Для моделей верхнего уровня удаляем по chat_id
                chat_id_col = getattr(model_class, model_class.__export_chat_id_column__)
                delete_stmt = delete(model_class).where(chat_id_col == chat_id)
                await session.execute(delete_stmt)
                logger.debug(f"  🗑️ {key}: удалены старые записи")

        # Для settings-таблиц создаём одну запись
        if model_class.__export_is_settings__:
            new_data = dict(table_data)
            new_data[model_class.__export_chat_id_column__] = chat_id

            # Десериализуем DateTime и другие типы из JSON строк
            new_data = _deserialize_dict_for_model(new_data, model_class)

            instance = model_class(**new_data)

            if merge:
                await session.merge(instance)
            else:
                session.add(instance)

            stats[key] = 1
            logger.debug(f"  ✓ {key}: импортированы настройки")
        else:
            # Для data-таблиц создаём много записей
            count = 0
            key_id_mapping: Dict[int, int] = {}

            for item in table_data:
                new_data = dict(item)

                # Убираем служебные поля
                old_parent_id = new_data.pop('_parent_id', None)
                old_own_id = new_data.pop('_old_id', None)

                # Для дочерних моделей - подставляем новый parent_id
                if parent_key is not None and parent_column is not None:
                    if old_parent_id is not None:
                        parent_mapping = id_mapping.get(parent_key, {})
                        new_parent_id = parent_mapping.get(old_parent_id)
                        if new_parent_id is None:
                            logger.warning(
                                f"⚠️ {key}: не найден parent_id {old_parent_id}, пропускаем"
                            )
                            continue
                        new_data[parent_column] = new_parent_id
                else:
                    # Для моделей верхнего уровня - добавляем chat_id
                    new_data[model_class.__export_chat_id_column__] = chat_id

                # Добавляем user_id если есть колонки аудита
                # Разные модели используют разные названия колонок
                if hasattr(model_class, 'created_by'):
                    new_data['created_by'] = user_id
                if hasattr(model_class, 'added_by'):
                    new_data['added_by'] = user_id
                if hasattr(model_class, 'added_by_user_id'):
                    new_data['added_by_user_id'] = user_id

                # Десериализуем DateTime и другие типы из JSON строк
                new_data = _deserialize_dict_for_model(new_data, model_class)

                # Создаём новую запись
                instance = model_class(**new_data)
                session.add(instance)

                # Flush чтобы получить новый ID (для parent-child маппинга)
                await session.flush()

                # Сохраняем маппинг старый ID -> новый ID для родительских моделей
                if parent_key is None and hasattr(instance, 'id') and old_own_id is not None:
                    key_id_mapping[old_own_id] = instance.id

                count += 1

            # Сохраняем маппинг для этой модели
            if parent_key is None:
                id_mapping[key] = key_id_mapping
                if key_id_mapping:
                    logger.debug(f"  📎 {key}: создан маппинг {len(key_id_mapping)} ID")

            stats[key] = count
            if count > 0:
                logger.debug(f"  ✓ {key}: импортировано {count} записей")

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
    - Версию формата (поддерживаются 1.0 и 2.0)
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

    # Проверяем версию формата (поддерживаем 1.0 и 2.0)
    version = data.get('export_version', '1.0')
    if version not in ('1.0', '2.0'):
        errors.append(f"Неподдерживаемая версия формата: {version}")

    # Проверяем что data это словарь
    if not isinstance(data['data'], dict):
        errors.append("Ключ 'data' должен быть словарём")
        return errors

    # Проверяем известные ключи
    known_keys = {m.__export_key__ for m in get_exportable_models()}
    for key in data['data'].keys():
        if key not in known_keys:
            # Это не ошибка - просто предупреждение о неизвестном ключе
            logger.warning(f"⚠️ Неизвестный ключ в данных: {key}")

    return errors