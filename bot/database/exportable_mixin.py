# ============================================================
# МИКСИН ДЛЯ АВТОМАТИЧЕСКОГО ЭКСПОРТА МОДЕЛЕЙ
# ============================================================
# Этот миксин позволяет моделям автоматически регистрироваться
# для экспорта/импорта настроек группы.
#
# Использование:
#   class MyModel(Base, ExportableMixin):
#       __tablename__ = 'my_table'
#       __export_key__ = 'my_models'  # ключ в JSON
#       __export_exclude__ = ('id', 'created_at')  # исключить колонки
#       __export_is_settings__ = False  # True если одна запись на группу
#       __export_chat_id_column__ = 'chat_id'  # колонка с chat_id
#       __export_parent_key__ = None  # для связанных моделей (section_id -> custom_spam_sections)
#       __export_parent_column__ = None  # колонка FK на родителя
#       ...
#
# При старте бота export_service автоматически соберёт все модели
# с этим миксином и включит их в экспорт/импорт.
# ============================================================

from typing import Optional, Tuple, List, Set, Type, TYPE_CHECKING

# Реестр всех экспортируемых моделей
# Заполняется автоматически при импорте моделей
_EXPORTABLE_REGISTRY: List[Type['ExportableMixin']] = []


class ExportableMixin:
    """
    Миксин для моделей которые должны экспортироваться/импортироваться.

    Добавьте этот миксин к модели и определите class attributes:
    - __export_key__: str - ключ в JSON (обязательно)
    - __export_exclude__: tuple - колонки для исключения (по умолчанию стандартные)
    - __export_is_settings__: bool - True если одна запись на группу
    - __export_chat_id_column__: str - имя колонки с chat_id
    - __export_parent_key__: str | None - ключ родительской модели (для связанных)
    - __export_parent_column__: str | None - колонка FK на родителя
    - __export_order__: int - порядок экспорта (меньше = раньше)
    """

    # ─────────────────────────────────────────────────────────
    # ОБЯЗАТЕЛЬНЫЕ АТРИБУТЫ (должны быть переопределены)
    # ─────────────────────────────────────────────────────────

    # Ключ в JSON файле экспорта
    # Пример: 'filter_words', 'antispam_rules', 'custom_spam_sections'
    __export_key__: str = None  # type: ignore

    # ─────────────────────────────────────────────────────────
    # ОПЦИОНАЛЬНЫЕ АТРИБУТЫ (есть значения по умолчанию)
    # ─────────────────────────────────────────────────────────

    # Колонки которые исключаются из экспорта
    # По умолчанию: служебные колонки (id, timestamps, audit)
    __export_exclude__: Tuple[str, ...] = (
        'id',
        'created_at',
        'updated_at',
        'created_by',
        'added_by',
        'added_at',
    )

    # True = таблица настроек (одна запись на группу)
    # False = таблица данных (много записей на группу)
    __export_is_settings__: bool = False

    # Имя колонки содержащей chat_id группы
    # Для большинства моделей это 'chat_id'
    # Для CaptchaSettings это 'group_id'
    __export_chat_id_column__: str = 'chat_id'

    # ─────────────────────────────────────────────────────────
    # АТРИБУТЫ ДЛЯ СВЯЗАННЫХ МОДЕЛЕЙ (parent-child)
    # ─────────────────────────────────────────────────────────
    # Используются когда модель связана не напрямую с chat_id,
    # а через родительскую модель (например CustomSectionPattern -> CustomSpamSection)

    # Ключ родительской модели в экспорте
    # Пример: 'custom_spam_sections' для CustomSectionPattern
    # None = модель связана напрямую с chat_id
    __export_parent_key__: Optional[str] = None

    # Колонка FK на родительскую модель
    # Пример: 'section_id' для CustomSectionPattern
    __export_parent_column__: Optional[str] = None

    # ─────────────────────────────────────────────────────────
    # ПОРЯДОК ЭКСПОРТА/ИМПОРТА
    # ─────────────────────────────────────────────────────────
    # Меньшее значение = экспортируется/импортируется раньше
    # Важно для зависимостей: родители должны импортироваться до детей
    #
    # Рекомендуемые значения:
    # 0-99: Основные настройки (ChatSettings, CaptchaSettings)
    # 100-199: Настройки модулей (ContentFilterSettings, ScamMediaSettings)
    # 200-299: Родительские данные (CustomSpamSection)
    # 300-399: Дочерние данные (CustomSectionPattern, CustomSectionThreshold)
    # 400-499: Обычные данные (FilterWord, AntiSpamRule)
    __export_order__: int = 400

    def __init_subclass__(cls, **kwargs):
        """
        Автоматически вызывается при создании подкласса.
        Регистрирует модель в реестре если она экспортируемая.
        """
        super().__init_subclass__(**kwargs)

        # Проверяем что это конкретная модель с __export_key__
        # (не промежуточный класс без ключа)
        if hasattr(cls, '__export_key__') and cls.__export_key__ is not None:
            # Проверяем что модель ещё не зарегистрирована
            if cls not in _EXPORTABLE_REGISTRY:
                _EXPORTABLE_REGISTRY.append(cls)


def get_exportable_models() -> List[Type[ExportableMixin]]:
    """
    Возвращает список всех зарегистрированных экспортируемых моделей.
    Отсортирован по __export_order__ для правильного порядка импорта.

    Returns:
        Список классов моделей с ExportableMixin
    """
    return sorted(_EXPORTABLE_REGISTRY, key=lambda m: m.__export_order__)


def get_model_by_export_key(key: str) -> Optional[Type[ExportableMixin]]:
    """
    Находит модель по её __export_key__.

    Args:
        key: Ключ экспорта (например 'filter_words')

    Returns:
        Класс модели или None если не найден
    """
    for model in _EXPORTABLE_REGISTRY:
        if model.__export_key__ == key:
            return model
    return None


def get_child_models(parent_key: str) -> List[Type[ExportableMixin]]:
    """
    Находит все дочерние модели для родительского ключа.

    Args:
        parent_key: Ключ родительской модели

    Returns:
        Список классов дочерних моделей
    """
    return [
        model for model in _EXPORTABLE_REGISTRY
        if model.__export_parent_key__ == parent_key
    ]