import importlib
import sys

from aiogram import Router


def build_fresh_router():
    """Reload handler modules to get fresh Router instances."""
    module_names = [name for name in list(sys.modules) if name.startswith("bot.handlers")]
    for name in module_names:
        sys.modules.pop(name)

    import bot.handlers  # type: ignore

    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("bot.handlers"):
            continue
        for value in getattr(module, "__dict__", {}).values():
            if isinstance(value, Router):
                object.__setattr__(value, "_parent_router", None)

    from bot.handlers import create_fresh_handlers_router

    return create_fresh_handlers_router()

