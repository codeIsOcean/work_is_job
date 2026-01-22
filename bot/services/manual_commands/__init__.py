# ═══════════════════════════════════════════════════════════════════════════
# МОДУЛЬ РУЧНЫХ КОМАНД МОДЕРАЦИИ
# ═══════════════════════════════════════════════════════════════════════════
# Этот модуль предоставляет функционал для команд /amute, /aban, /akick.
# Админы могут модерировать группу через команды в чате.
#
# Создано: 2026-01-21
# Обновлено: 2026-01-22 — добавлены /aban и /akick
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

# Экспортируем функции бана
from bot.services.manual_commands.ban_service import (
    apply_ban,
    apply_unban,
    ban_across_groups,
    BanResult,
)

# Экспортируем функции кика
from bot.services.manual_commands.kick_service import (
    apply_kick,
    KickResult,
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
    # Ban service
    'apply_ban',
    'apply_unban',
    'ban_across_groups',
    'BanResult',
    # Kick service
    'apply_kick',
    'KickResult',
]
