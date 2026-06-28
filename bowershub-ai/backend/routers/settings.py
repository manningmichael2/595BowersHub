"""
User settings API routes: per-user preferences (theme, text size, morning card,
voice, etc.) plus the resolved `effective_theme` and `effective_text_size` so
the frontend doesn't have to do the priority dance.

Endpoints:
    GET  /api/settings           — current user's settings + resolved effects
    PATCH /api/settings          — JSON-merge partial settings keys
    POST /api/settings/reset-theme — clear the user's theme_id override

The reads/writes stay scoped to `bh_users.settings_json` for the authenticated
user. Theme resolution is delegated to `services.theme_resolver`; text-size
resolution to `services.text_size_resolver`. Both resolvers tolerate missing
keys, unknown values, and stale references so the GET path never fails.

Validates: R3.2, R3.3, R3.5, R3.6, R3.7, R4.3, R4.5, R4.6, R8.9, R10.9
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services.text_size_resolver import resolve as resolve_text_size
from backend.services.theme_resolver import resolve as resolve_theme

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---- Request models -------------------------------------------------------

class SettingsPatch(BaseModel):
    """
    Partial settings update. All fields optional. `theme_id` may be explicitly
    `null` to clear the override (same effect as POST /api/settings/reset-theme).
    Unknown keys in the request body are ignored.
    """
    theme_id: Optional[int] = Field(default=None)
    text_size: Optional[str] = Field(default=None)
    morning_card_workspace_id: Optional[int] = Field(default=None)
    morning_card_disabled: Optional[bool] = Field(default=None)
    voice: Optional[dict[str, Any]] = Field(default=None)
    use_experimental_dashboard: Optional[bool] = Field(default=None)
    # When true, the background context-capture pass is skipped for this user's
    # exchanges (privacy opt-out). Honored in services.hook_engine.
    context_capture_disabled: Optional[bool] = Field(default=None)
    # DB Browser sidebar prefs (per-user): favorited / hidden tables as
    # "schema.table" keys, and the set of expanded schema names. Each list
    # replaces wholesale (RFC 7396 merge treats a list as a scalar value).
    db_favorites: Optional[list[str]] = Field(default=None)
    db_hidden: Optional[list[str]] = Field(default=None)
    db_expanded: Optional[list[str]] = Field(default=None)

    model_config = {"extra": "ignore"}


# ---- Helpers --------------------------------------------------------------

# Allow explicit-null for these keys so the PATCH body distinguishes between
# "I omitted this key" and "I want to clear this key".
_NULLABLE_KEYS = {
    "theme_id",
    "text_size",
    "morning_card_workspace_id",
    "morning_card_disabled",
    "voice",
    "use_experimental_dashboard",
    "context_capture_disabled",
    "db_favorites",
    "db_hidden",
    "db_expanded",
}


def _theme_visible_to_user(theme: dict[str, Any], user_id: int) -> bool:
    """
    Mirror of `services.theme_resolver._is_visible`. We keep a local copy so
    the router doesn't reach into a private helper, and so the visibility
    check is auditable next to the SQL that loads themes for this user.
    """
    if theme.get("is_preset"):
        return True
    owner_id = theme.get("owner_id")
    if owner_id is None:
        return True
    return owner_id == user_id


async def _load_themes_visible_to(user_id: int) -> list[dict[str, Any]]:
    """Fetch every theme row visible to `user_id`. One query, ordered by id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, slug, is_preset, owner_id, tokens_json,
                   created_at, updated_at
              FROM public.bh_themes
             WHERE is_preset = true
                OR owner_id IS NULL
                OR owner_id = $1
             ORDER BY id
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def _load_platform_default_id() -> Optional[int]:
    """Read `bh_platform_settings.default_theme_id`; tolerate missing row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value_json FROM public.bh_platform_settings WHERE key = 'default_theme_id'"
        )
    if not row:
        return None
    value = row["value_json"]
    if not isinstance(value, dict):
        return None
    theme_id = value.get("theme_id")
    return theme_id if isinstance(theme_id, int) else None


def _merge_settings(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """
    JSON Merge Patch (RFC 7396) semantics, scoped to the keys the patch model
    allows. Explicit `null` removes the key. Nested dicts (e.g. `voice`) are
    merged recursively against the current value when both sides are dicts;
    otherwise the patch value replaces wholesale.
    """
    merged = dict(current) if isinstance(current, dict) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


async def _save_settings_json(user_id: int, settings: dict[str, Any]) -> None:
    """Persist the new settings_json blob for `user_id`."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.bh_users SET settings_json = $1 WHERE id = $2",
            settings,
            user_id,
        )


def _resolve_effects(
    user: dict[str, Any],
    themes: list[dict[str, Any]],
    platform_default_id: Optional[int],
) -> tuple[dict[str, Any], str]:
    """Run both resolvers and return (effective_theme, effective_text_size)."""
    effective_theme = resolve_theme(user, themes, platform_default_id)
    settings_json = user.get("settings_json") or {}
    label, _multiplier = resolve_text_size(settings_json.get("text_size"))
    return effective_theme, label


async def _build_response(user: dict[str, Any]) -> dict[str, Any]:
    """Shared GET/PATCH/reset response shape."""
    themes = await _load_themes_visible_to(user["id"])
    platform_default_id = await _load_platform_default_id()
    effective_theme, effective_text_size = _resolve_effects(
        user, themes, platform_default_id
    )
    return {
        "settings": user.get("settings_json") or {},
        "effective_theme": effective_theme,
        "effective_text_size": effective_text_size,
    }


# ---- Routes ---------------------------------------------------------------

@router.get("")
async def get_settings(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current user's settings_json plus resolved effects."""
    return await _build_response(user)


@router.patch("")
async def patch_settings(
    body: dict[str, Any] = Body(default_factory=dict),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Merge partial settings into `bh_users.settings_json`.

    - `theme_id` must reference a theme visible to the user, else 400.
    - `text_size` is stored verbatim; unknown values get mapped to `medium`
      by the resolver on read (R4.6).
    - Other keys are merged with JSON Merge Patch semantics (RFC 7396).
    """
    # Pydantic-validate the subset we care about, but build the actual patch
    # from the raw body so we can distinguish "key absent" from "key=null".
    parsed = SettingsPatch.model_validate(body)
    raw_keys = body.keys() if isinstance(body, dict) else []
    allowed = set(SettingsPatch.model_fields.keys())

    patch: dict[str, Any] = {}
    for key in raw_keys:
        if key not in allowed:
            continue  # silently ignore unknown keys
        value = getattr(parsed, key)
        if value is None and key not in _NULLABLE_KEYS:
            # model coerced absent to None for a non-nullable key; skip.
            continue
        patch[key] = value

    # Validate theme_id visibility before touching the DB.
    if "theme_id" in patch and patch["theme_id"] is not None:
        target_id = patch["theme_id"]
        themes = await _load_themes_visible_to(user["id"])
        target = next((t for t in themes if t.get("id") == target_id), None)
        if target is None or not _theme_visible_to_user(target, user["id"]):
            raise HTTPException(
                status_code=400,
                detail=f"Theme {target_id} is not visible to this user",
            )

    current = user.get("settings_json") or {}
    new_settings = _merge_settings(current, patch)
    await _save_settings_json(user["id"], new_settings)

    # Build response with the freshly-saved settings on the user dict.
    refreshed_user = dict(user)
    refreshed_user["settings_json"] = new_settings
    return await _build_response(refreshed_user)


@router.post("/reset-theme")
async def reset_theme(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Clear `settings_json.theme_id` so the resolver falls back to the platform
    default (and then to the built-in Dark Navy preset). Idempotent — calling
    this when no override is set is a no-op write.
    """
    current = user.get("settings_json") or {}
    new_settings = dict(current)
    new_settings.pop("theme_id", None)
    await _save_settings_json(user["id"], new_settings)

    refreshed_user = dict(user)
    refreshed_user["settings_json"] = new_settings
    response = await _build_response(refreshed_user)
    response["theme_id"] = None  # explicit signal per design.md spec
    return response
