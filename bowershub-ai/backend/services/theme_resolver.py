"""
Theme Resolver: pure priority-order resolution of the active theme for a user.

This module has no I/O. Callers (typically `routers/settings.py` or
`routers/themes.py`) query `bh_themes` and `bh_platform_settings` and pass
the resulting rows in as the `themes_table_view` and `platform_default_id`
arguments. The resolver itself never touches the database.

Resolution priority (from R3.7):
  1. User override         — `user["settings_json"]["theme_id"]`
  2. Platform default      — `bh_platform_settings.default_theme_id`
  3. Built-in fallback     — the `dark-navy` preset slug; if that row is
                             also missing or invisible, a hardcoded synthetic
                             Dark Navy theme is returned with `id=None`.

Visibility rules (from R3.5 and the design "Database Changes" section):
  - is_preset=true,  owner_id=NULL          → visible to ALL users
  - is_preset=false, owner_id=NULL          → admin-published; visible to ALL
  - is_preset=false, owner_id=<user_id>     → personal; visible only to that
                                              user

Stale references — a theme that was deleted, or one that is owned by a
different user — fall through to the next entry in the priority order.
The function never raises.

`is_default` is true on the returned record iff the resolved theme's id
matches the supplied `platform_default_id`. The synthetic Dark Navy
fallback always has `id=None`, so it is `is_default=False` (callers can
use that to distinguish a DB-row return from a synthetic fallback).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional


# ----------------------------------------------------------------------
# Synthetic Dark Navy fallback
# ----------------------------------------------------------------------
# These tokens MUST mirror the seed in migration 009 so that the synthetic
# fallback renders identically to the DB-backed Dark Navy preset.
# If the migration seed changes, update these alongside it.
_FALLBACK_DARK_NAVY: dict[str, Any] = {
    "id": None,
    "name": "Dark Navy",
    "slug": "dark-navy",
    "tokens_json": {
        "background": "#0f0f1a",
        "surface": "#1a1a2e",
        "primary": "#6366f1",
        "accent": "#818cf8",
        "text": "#e5e7eb",
        "text_muted": "#94a3b8",
        "border": "#374151",
        "danger": "#ef4444",
        "success": "#22c55e",
    },
    "is_default": False,
}


def _is_visible(theme: Mapping[str, Any], user_id: Optional[int]) -> bool:
    """
    Apply the visibility rules above. Returns True iff `user_id` is allowed
    to see/select this theme.

    A theme is visible when:
      - It's a preset (is_preset=true), OR
      - Its owner_id is NULL (admin-published), OR
      - Its owner_id matches the requesting user's id.
    """
    if theme.get("is_preset"):
        return True
    owner_id = theme.get("owner_id")
    if owner_id is None:
        return True
    return owner_id == user_id


def _shape(
    theme: Mapping[str, Any],
    platform_default_id: Optional[int],
) -> dict[str, Any]:
    """Project a theme row into the public return shape."""
    theme_id = theme.get("id")
    return {
        "id": theme_id,
        "name": theme.get("name"),
        "slug": theme.get("slug"),
        "tokens_json": theme.get("tokens_json"),
        "is_default": (
            platform_default_id is not None and theme_id == platform_default_id
        ),
    }


def _find_by_id(
    themes: list[Mapping[str, Any]],
    theme_id: Any,
) -> Optional[Mapping[str, Any]]:
    """Linear scan for a theme by primary key. Returns None if absent."""
    if theme_id is None:
        return None
    for theme in themes:
        if theme.get("id") == theme_id:
            return theme
    return None


def _find_dark_navy_preset(
    themes: list[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    """
    Find the built-in Dark Navy preset row by slug. Restricts to preset rows
    with `owner_id=NULL` so a personal theme that happens to share the slug
    cannot impersonate the fallback.
    """
    for theme in themes:
        if (
            theme.get("slug") == "dark-navy"
            and theme.get("is_preset")
            and theme.get("owner_id") is None
        ):
            return theme
    return None


def resolve(
    user: Optional[Mapping[str, Any]],
    themes_table_view: Iterable[Mapping[str, Any]],
    platform_default_id: Optional[int],
) -> dict[str, Any]:
    """
    Resolve the active theme for `user`.

    Parameters
    ----------
    user :
        Dict-like with at least `id` and (optionally) `settings_json`. The
        settings_json may include a `theme_id` key naming the user's
        override. Missing keys are tolerated; `user=None` is also tolerated
        and behaves like an unauthenticated request (no override applied).
    themes_table_view :
        Iterable of theme row dicts. Each row should provide at least
        `id`, `name`, `slug`, `tokens_json`, `is_preset`, and `owner_id`.
        The caller is responsible for the DB query.
    platform_default_id :
        The id stored in `bh_platform_settings.default_theme_id`, or None
        if no platform default has been configured.

    Returns
    -------
    A dict of shape ``{id, name, slug, tokens_json, is_default}``.

    Notes
    -----
    - This function NEVER raises. Any malformed input is treated as a
      cache miss and the resolver falls through to the next priority
      level, ultimately returning the synthetic Dark Navy fallback.
    - `is_default` is true iff the resolved theme's id equals
      `platform_default_id`. The synthetic fallback always has `id=None`,
      so it is `is_default=False`.
    """
    # Defensively materialize the iterable so we can scan it multiple times.
    try:
        themes = [t for t in themes_table_view if isinstance(t, Mapping)]
    except TypeError:
        # themes_table_view was not actually iterable.
        themes = []

    user_id: Optional[int] = None
    user_override_id: Any = None
    if isinstance(user, Mapping):
        user_id = user.get("id") if isinstance(user.get("id"), int) else user.get("id")
        settings_json = user.get("settings_json")
        if isinstance(settings_json, Mapping):
            user_override_id = settings_json.get("theme_id")

    # ---- 1. User override ----
    override = _find_by_id(themes, user_override_id)
    if override is not None and _is_visible(override, user_id):
        return _shape(override, platform_default_id)

    # ---- 2. Platform default ----
    default = _find_by_id(themes, platform_default_id)
    if default is not None and _is_visible(default, user_id):
        return _shape(default, platform_default_id)

    # ---- 3. Built-in Dark Navy preset (DB row) ----
    preset = _find_dark_navy_preset(themes)
    if preset is not None and _is_visible(preset, user_id):
        return _shape(preset, platform_default_id)

    # ---- 4. Synthetic fallback (the migration's Dark Navy seed never
    #         reached this view). id=None so callers can distinguish.
    return dict(_FALLBACK_DARK_NAVY)
