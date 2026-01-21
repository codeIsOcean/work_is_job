# ═══════════════════════════════════════════════════════════════════════════
# МОДУЛЬ РУЧНЫХ КОМАНД МОДЕРАЦИИ
# ═══════════════════════════════════════════════════════════════════════════
# Этот модуль предоставляет функционал для команд /amute, /aban, /akick.
# Админы могут модерировать группу через команды в чате.
#
# Создано: 2026-01-21
# ═══════════════════════════════════════════════════════════════════════════

# Экспортируем функции парсинга
from bot.services.manual_commands.parser import (
    parse_mute_command,
    parse_duration_extended,
    format_duration,
    ParsedCommand,
)

# Экспортируем функции мута
from bot.services.manual_commands.mute_service import (
    get_manual_command_settings,
    update_mute_settings,
    apply_mute,
    apply_unmute,
    format_user_link,
    format_user_link_by_id,
    MuteResult,
)

__all__ = [
    # Parser
    'parse_mute_command',
    'parse_duration_extended',
    'format_duration',
    'ParsedCommand',
    # Mute service
    'get_manual_command_settings',
    'update_mute_settings',
    'apply_mute',
    'apply_unmute',
    'format_user_link',
    'format_user_link_by_id',
    'MuteResult',
]
