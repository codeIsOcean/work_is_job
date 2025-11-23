from __future__ import annotations

from dataclasses import dataclass


def _group_username(group) -> str | None:
    return getattr(group, "username", None)


def build_group_header(group) -> str:
    parts = ["<b>Управление группой</b>", ""]
    if group is None:
        title = "Группа"
        chat_id = "?"
        username = None
    else:
        title = getattr(group, "title", "Группа")
        chat_id = getattr(group, "chat_id", getattr(group, "id", "?"))
        username = _group_username(group)
    if username:
        parts.append(
            f'Название: <a href="https://t.me/{username}">{title}</a> (@{username})'
        )
    else:
        parts.append(f"Название: {title} (username отсутствует)")
    parts.append(f"ID: {chat_id}")
    parts.append("")
    parts.append("Доступные функции:")
    return "\n".join(parts)


def build_group_header_with_preview_disabled(group) -> tuple[str, bool]:
    """Возвращает заголовок группы и флаг disable_web_page_preview=True."""
    return build_group_header(group), True


def format_group_link(group) -> str:
    username = _group_username(group)
    if username:
        return f'<a href="https://t.me/{username}">{group.title}</a>'
    return group.title
