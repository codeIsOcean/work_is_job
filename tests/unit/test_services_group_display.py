from types import SimpleNamespace

from bot.services.group_display import build_group_header, format_group_link


def test_build_group_header_with_username():
    group = SimpleNamespace(chat_id=-100, title="My Group", username="mygroup")

    header = build_group_header(group)

    assert "https://t.me/mygroup" in header
    assert "@mygroup" in header
    assert "Доступные функции" in header


def test_build_group_header_without_username():
    group = SimpleNamespace(chat_id=-200, title="No Link", username=None)

    header = build_group_header(group)

    assert "username отсутствует" in header
    assert "https://t.me" not in header


def test_format_group_link_prefers_username():
    group = SimpleNamespace(chat_id=-300, title="Title", username="link")
    assert format_group_link(group) == '<a href="https://t.me/link">Title</a>'


def test_format_group_link_plain_title():
    group = SimpleNamespace(chat_id=-400, title="Plain", username=None)
    assert format_group_link(group) == "Plain"
