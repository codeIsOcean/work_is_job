# Инициализационный файл для пакета antispam services
# Импортируем основные функции и классы для удобного доступа из других модулей
from .antispam_service import (
    # Функция проверки сообщения на спам
    check_message_for_spam,
    # Класс результата проверки на спам
    AntiSpamDecision,
    # Функции работы с правилами
    get_rules_for_chat,
    upsert_rule,
    get_rule_by_type,
    # Функции работы с белым списком
    add_whitelist_pattern,
    remove_whitelist_pattern,
    list_whitelist_patterns,
    get_whitelist_by_id,
    check_whitelist,
    # Функции анализа контента
    extract_links,
    is_telegram_link,
    detect_forward_source,
    detect_quote_source,
    # Функции работы с URL и доменами
    extract_domain_from_url,
    is_url,
)

# Определяем список экспортируемых имен
__all__ = [
    "check_message_for_spam",
    "AntiSpamDecision",
    "get_rules_for_chat",
    "upsert_rule",
    "get_rule_by_type",
    "add_whitelist_pattern",
    "remove_whitelist_pattern",
    "list_whitelist_patterns",
    "get_whitelist_by_id",
    "check_whitelist",
    "extract_links",
    "is_telegram_link",
    "detect_forward_source",
    "detect_quote_source",
    "extract_domain_from_url",
    "is_url",
]
