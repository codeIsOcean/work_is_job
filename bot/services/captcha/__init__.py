# bot/services/captcha/__init__.py
"""
Модуль капчи - бизнес-логика для трёх режимов капчи.

Архитектура:
- Visual Captcha (ЛС) - капча в личных сообщениях через deep link
- Join Captcha (группа) - капча в группе при самостоятельном входе
- Invite Captcha (группа) - капча в группе при приглашении

Структура модуля:
- settings_service.py - CRUD операции с настройками + CaptchaMode enum
- flow_service.py - основная бизнес-логика (решения, отправка)
- verification_service.py - проверка ответов на капчу
- cleanup_service.py - очистка капч, Redis, сообщений
"""

# ═══════════════════════════════════════════════════════════════════════════
# Экспорт из settings_service
# ═══════════════════════════════════════════════════════════════════════════
from bot.services.captcha.settings_service import (
    # Enum режимов капчи
    CaptchaMode,
    # Датакласс с настройками
    CaptchaSettings,
    # Функции работы с настройками
    get_captcha_settings,
    update_captcha_setting,
    is_captcha_configured,
    get_missing_settings,
)

# ═══════════════════════════════════════════════════════════════════════════
# Экспорт из flow_service
# ═══════════════════════════════════════════════════════════════════════════
from bot.services.captcha.flow_service import (
    determine_captcha_mode,
    send_captcha,
    process_captcha_success,
    process_captcha_failure,
    check_and_restore_restriction,
)

# ═══════════════════════════════════════════════════════════════════════════
# Экспорт из cleanup_service
# ═══════════════════════════════════════════════════════════════════════════
from bot.services.captcha.cleanup_service import (
    cleanup_user_captcha,
    cleanup_expired_captchas,
    enforce_captcha_limit,
    get_pending_captchas,
    save_captcha_data,
    get_captcha_data,
    save_captcha_message,
    get_captcha_owner,
    increment_attempts,
    CaptchaOverflowError,
    # Redis ключи (для использования в других модулях)
    CAPTCHA_DATA_KEY,
    CAPTCHA_MESSAGE_KEY,
    CAPTCHA_ATTEMPTS_KEY,
    CAPTCHA_OWNER_KEY,
)

# ═══════════════════════════════════════════════════════════════════════════
# Экспорт из verification_service
# ═══════════════════════════════════════════════════════════════════════════
from bot.services.captcha.verification_service import (
    hash_answer,
    verify_answer_hash,
    verify_captcha_answer,
    check_captcha_ownership,
    check_captcha_ownership_by_callback_data,
    generate_captcha_options,
)

# ═══════════════════════════════════════════════════════════════════════════
# Список всех экспортируемых имён
# ═══════════════════════════════════════════════════════════════════════════
__all__ = [
    # Enums и датаклассы
    "CaptchaMode",
    "CaptchaSettings",
    "CaptchaOverflowError",

    # Settings
    "get_captcha_settings",
    "update_captcha_setting",
    "is_captcha_configured",
    "get_missing_settings",

    # Flow
    "determine_captcha_mode",
    "send_captcha",
    "process_captcha_success",
    "process_captcha_failure",
    "check_and_restore_restriction",

    # Cleanup
    "cleanup_user_captcha",
    "cleanup_expired_captchas",
    "enforce_captcha_limit",
    "get_pending_captchas",
    "save_captcha_data",
    "get_captcha_data",
    "save_captcha_message",
    "get_captcha_owner",
    "increment_attempts",

    # Verification
    "hash_answer",
    "verify_answer_hash",
    "verify_captcha_answer",
    "check_captcha_ownership",
    "check_captcha_ownership_by_callback_data",
    "generate_captcha_options",

    # Redis keys
    "CAPTCHA_DATA_KEY",
    "CAPTCHA_MESSAGE_KEY",
    "CAPTCHA_ATTEMPTS_KEY",
    "CAPTCHA_OWNER_KEY",
]
