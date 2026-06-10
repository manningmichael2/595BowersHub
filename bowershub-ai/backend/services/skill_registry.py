"""
Skill Registry: auto-discovery and dispatch for native Python skills.

Each native skill module registers its handlers via the @native_skill decorator.
The executor looks up handlers from this registry instead of a hardcoded if/elif
chain — so adding a new native skill is:
  1. Create backend/services/skills/<name>.py with @native_skill-decorated handlers
  2. Add a row to bh_skills (migration) with webhook_url = 'native://<name>'
  3. Done. No executor changes needed.

Usage in a skill module:

    from backend.services.skill_registry import native_skill

    @native_skill("weather", "get-weather")
    async def handle_weather(params: dict) -> dict:
        ...
        return {"_display": "☀️ 72°F in Detroit"}
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)

# The registry: skill_name -> async handler function
_handlers: Dict[str, Callable[..., Coroutine[Any, Any, dict]]] = {}


def native_skill(*names: str):
    """
    Decorator that registers an async function as the handler for one or more
    native skill names.

    Usage:
        @native_skill("weather", "get-weather")
        async def handle_weather(params: dict) -> dict:
            ...

    The function must accept a single `params: dict` argument and return a dict.
    If the dict contains a `_display` key, that string is used as the pre-formatted
    response shown to the user.
    """
    def decorator(fn: Callable[..., Coroutine[Any, Any, dict]]):
        for name in names:
            _handlers[name] = fn
            logger.debug(f"Registered native skill: {name}")
        return fn
    return decorator


def get_handler(skill_name: str) -> Optional[Callable[..., Coroutine[Any, Any, dict]]]:
    """Look up a registered native skill handler by name."""
    return _handlers.get(skill_name)


def list_registered() -> list[str]:
    """Return all registered native skill names (sorted)."""
    return sorted(_handlers.keys())


def discover_skills():
    """
    Import all modules in backend/services/skills/ to trigger their
    @native_skill registrations. Called once at app startup.
    """
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.is_dir():
        logger.warning(f"Skills directory not found: {skills_dir}")
        return

    package_name = "backend.services.skills"
    count = 0

    for module_info in pkgutil.iter_modules([str(skills_dir)]):
        if module_info.name.startswith("_"):
            continue
        module_path = f"{package_name}.{module_info.name}"
        try:
            importlib.import_module(module_path)
            count += 1
        except Exception as e:
            logger.error(f"Failed to load skill module {module_path}: {e}")

    logger.info(f"Discovered {count} skill module(s), {len(_handlers)} handler(s) registered: {list_registered()}")
