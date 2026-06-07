"""
Themes API: list/create/update/delete theme palettes plus admin
"set platform default".

Visibility (R3.5):
    - Built-in presets (`is_preset=true`)              → visible to ALL users
    - Admin-published (`is_preset=false`, owner=NULL`) → visible to ALL users
    - Personal (`owner_id = <user_id>`)                → visible only to that user

Permissions:
    - Anyone authenticated may list themes (filtered by visibility) and
      create personal themes.
    - Admins may publish (`owner_id=NULL`), edit any theme, and delete any
      non-preset theme.
    - Members may edit/delete only their own themes.
    - Presets cannot be deleted (R1.x; design "Database Changes").

Save-time validation (R1.6, R1.7, R1.8):
    - Hex tokens validated via `theme_validator.validate_tokens`. Field
      errors → 400.
    - Contrast between `text` and `background` checked via
      `theme_validator.contrast_decision`:
          * "block" → 422 (refuse save)
          * "warn"  → save with warning string in response body
          * "ok"    → save silently

DELETE cascade (R1.9, R3.8):
    Inside a single transaction, after the row is removed:
      - Clear `bh_users.settings_json.theme_id` for any user whose override
        pointed at the deleted theme. The next resolver call falls through
        to the platform default.
      - If the deleted theme was the platform default, clear that pointer
        too. The resolver then falls through to the synthetic Dark Navy
        fallback.

Audit log: every create/update/delete and set-platform-default emits an
entry to `bh_audit_log`.

_Requirements: R1.2, R1.3, R1.5, R1.6, R1.8, R1.9, R1.10, R3.4, R3.5
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.database import get_pool
from backend.middleware.audit import AuditLogger
from backend.middleware.auth import get_current_user, require_admin
from backend.services.theme_validator import (
    REQUIRED_TOKEN_KEYS,
    contrast_decision,
    validate_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/themes", tags=["themes"])


# ----------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------


class ThemeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    tokens_json: dict
    publish: bool = False  # admin-only; ignored for non-admins


class ThemeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tokens_json: Optional[dict] = None


class ThemeResponse(BaseModel):
    id: int
    name: str
    slug: str
    is_preset: bool
    owner_id: Optional[int]
    tokens_json: dict
    is_default: bool
    created_at: datetime
    updated_at: datetime
    contrast_warning: Optional[str] = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Produce a url-safe slug from a theme name. Empty input → 'theme'."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")[:50]
    return slug or "theme"


async def _unique_slug_for(
    conn: asyncpg.Connection,
    base: str,
    owner_id: Optional[int],
    *,
    exclude_id: Optional[int] = None,
) -> str:
    """
    Return a slug that does not collide with any existing row in the same
    `owner_id` bucket. The unique key on `bh_themes` is `(slug, owner_id)`.
    """
    candidate = base
    suffix = 2
    while True:
        if owner_id is None:
            row = await conn.fetchrow(
                """
                SELECT id FROM public.bh_themes
                WHERE slug = $1 AND owner_id IS NULL
                """,
                candidate,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT id FROM public.bh_themes
                WHERE slug = $1 AND owner_id = $2
                """,
                candidate,
                owner_id,
            )
        if row is None or (exclude_id is not None and row["id"] == exclude_id):
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def _get_platform_default_id(conn: asyncpg.Connection) -> Optional[int]:
    """Read the current platform-default theme id from bh_platform_settings."""
    row = await conn.fetchrow(
        """
        SELECT value_json FROM public.bh_platform_settings
        WHERE key = 'default_theme_id'
        """
    )
    if not row:
        return None
    value = row["value_json"]
    if not isinstance(value, dict):
        return None
    theme_id = value.get("theme_id")
    return theme_id if isinstance(theme_id, int) else None


def _can_modify(theme_row: dict, user: dict) -> bool:
    """A user can update/delete a theme iff they're admin or its owner."""
    if user["role"] == "admin":
        return True
    return theme_row.get("owner_id") == user["id"]


def _validate_payload(tokens_json: dict) -> tuple[Optional[str], Optional[HTTPException]]:
    """
    Run hex + contrast validation. Returns `(contrast_warning, error)`:
      - `error` is set when validation fails (field errors or contrast block);
        callers should `raise error`.
      - `contrast_warning` is a non-blocking message ("warn" tier) included
        in the response body when contrast is below 4.5:1 but above 2.0:1.
    """
    field_errors = validate_tokens(tokens_json)
    if field_errors:
        return None, HTTPException(
            status_code=400,
            detail={
                "message": "Invalid theme tokens",
                "errors": [
                    {"field": e.field, "message": e.message} for e in field_errors
                ],
            },
        )

    decision = contrast_decision(tokens_json["text"], tokens_json["background"])
    if decision == "block":
        return None, HTTPException(
            status_code=422,
            detail={
                "message": (
                    "Contrast between `text` and `background` is too low to "
                    "be readable (must be at least 2.0:1)."
                ),
                "contrast": "block",
            },
        )
    if decision == "warn":
        return (
            "Contrast between text and background is below the recommended "
            "4.5:1 — the theme may be hard to read.",
            None,
        )
    return None, None


def _shape(row: asyncpg.Record, platform_default_id: Optional[int],
           contrast_warning: Optional[str] = None) -> ThemeResponse:
    """Project a DB row into the ThemeResponse shape."""
    return ThemeResponse(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        is_preset=row["is_preset"],
        owner_id=row["owner_id"],
        tokens_json=row["tokens_json"] if isinstance(row["tokens_json"], dict) else {},
        is_default=(platform_default_id is not None and row["id"] == platform_default_id),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        contrast_warning=contrast_warning,
    )


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@router.get("", response_model=List[ThemeResponse])
async def list_themes(user: dict = Depends(get_current_user)):
    """
    Return all themes visible to the current user (R1.2, R3.1, R3.5).

    Visibility:
      - all `is_preset=true` rows
      - all rows with `owner_id IS NULL` (admin-published)
      - all rows with `owner_id = current_user_id`
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        platform_default_id = await _get_platform_default_id(conn)
        rows = await conn.fetch(
            """
            SELECT * FROM public.bh_themes
            WHERE is_preset = true
               OR owner_id IS NULL
               OR owner_id = $1
            ORDER BY is_preset DESC, owner_id NULLS FIRST, name
            """,
            user["id"],
        )
    return [_shape(r, platform_default_id) for r in rows]


@router.post("", response_model=ThemeResponse, status_code=201)
async def create_theme(body: ThemeCreate, user: dict = Depends(get_current_user)):
    """
    Create a theme.

    By default the theme is personal (`owner_id = current_user`). An admin
    may pass `publish=true` to publish it to all users (`owner_id=NULL`,
    R1.5).

    Non-admins who set `publish=true` get HTTP 403 — silently downgrading
    the request would hide a permissions error from the caller (R1.10).
    """
    if body.publish and user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can publish themes platform-wide",
        )

    contrast_warning, err = _validate_payload(body.tokens_json)
    if err is not None:
        raise err

    is_publish = bool(body.publish) and user["role"] == "admin"
    owner_id: Optional[int] = None if is_publish else user["id"]

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            base_slug = _slugify(body.name)
            slug = await _unique_slug_for(conn, base_slug, owner_id)
            row = await conn.fetchrow(
                """
                INSERT INTO public.bh_themes
                    (name, slug, is_preset, owner_id, tokens_json)
                VALUES ($1, $2, false, $3, $4::jsonb)
                RETURNING *
                """,
                body.name,
                slug,
                owner_id,
                json.dumps(body.tokens_json),
            )
            platform_default_id = await _get_platform_default_id(conn)

    await AuditLogger.log(
        user["id"],
        "create_theme",
        target_type="theme",
        target_id=row["id"],
        details={"published": is_publish, "name": row["name"]},
    )

    return _shape(row, platform_default_id, contrast_warning=contrast_warning)


@router.patch("/{theme_id}", response_model=ThemeResponse)
async def update_theme(
    theme_id: int,
    body: ThemeUpdate,
    user: dict = Depends(get_current_user),
):
    """
    Update a theme's name and/or tokens.

    Permission: must own the theme OR be admin (R3.5). Presets are not
    editable through this endpoint (a preset has `owner_id=NULL` and
    `is_preset=true`, so a non-admin fails the owner check and an admin
    can edit only at their own risk — we still block edits on presets
    since they ship as part of the platform).
    """
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT * FROM public.bh_themes WHERE id = $1", theme_id
            )
            if existing is None:
                raise HTTPException(status_code=404, detail="Theme not found")

            existing_dict = dict(existing)

            if existing_dict["is_preset"]:
                raise HTTPException(
                    status_code=409,
                    detail="Preset themes cannot be modified",
                )

            if not _can_modify(existing_dict, user):
                raise HTTPException(status_code=403, detail="Access denied")

            # Compute the post-update tokens for contrast validation. If
            # tokens_json wasn't supplied, fall back to the existing tokens.
            new_tokens = (
                fields["tokens_json"]
                if "tokens_json" in fields
                else existing_dict["tokens_json"]
            )
            if not isinstance(new_tokens, dict):
                new_tokens = {}

            contrast_warning: Optional[str] = None
            if "tokens_json" in fields:
                contrast_warning, err = _validate_payload(new_tokens)
                if err is not None:
                    raise err

            updates: list[str] = []
            values: list[Any] = []
            idx = 1

            if "name" in fields:
                updates.append(f"name = ${idx}")
                values.append(fields["name"])
                idx += 1
                # Re-slug from the new name so the URL-safe identifier
                # tracks the display name. Unique within (slug, owner_id).
                base_slug = _slugify(fields["name"])
                new_slug = await _unique_slug_for(
                    conn,
                    base_slug,
                    existing_dict["owner_id"],
                    exclude_id=theme_id,
                )
                updates.append(f"slug = ${idx}")
                values.append(new_slug)
                idx += 1

            if "tokens_json" in fields:
                updates.append(f"tokens_json = ${idx}::jsonb")
                values.append(json.dumps(fields["tokens_json"]))
                idx += 1

            updates.append("updated_at = now()")
            values.append(theme_id)

            row = await conn.fetchrow(
                f"""
                UPDATE public.bh_themes
                SET {', '.join(updates)}
                WHERE id = ${idx}
                RETURNING *
                """,
                *values,
            )
            platform_default_id = await _get_platform_default_id(conn)

    await AuditLogger.log(
        user["id"],
        "update_theme",
        target_type="theme",
        target_id=theme_id,
        details={"fields": list(fields.keys())},
    )

    return _shape(row, platform_default_id, contrast_warning=contrast_warning)


@router.delete("/{theme_id}")
async def delete_theme(theme_id: int, user: dict = Depends(get_current_user)):
    """
    Delete a non-preset theme.

    Cascade in the same transaction (R1.9, R3.8):
      - Clear `bh_users.settings_json.theme_id` for users whose override
        was this theme.
      - If this theme was the platform default, clear that pointer too.

    Returns:
        `{deleted: True, affected_user_count: N, was_platform_default: bool}`
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT * FROM public.bh_themes WHERE id = $1", theme_id
            )
            if existing is None:
                raise HTTPException(status_code=404, detail="Theme not found")

            existing_dict = dict(existing)

            if existing_dict["is_preset"]:
                raise HTTPException(
                    status_code=409,
                    detail="Preset themes cannot be deleted",
                )

            if not _can_modify(existing_dict, user):
                raise HTTPException(status_code=403, detail="Access denied")

            # Clear matching user overrides. Compare on the JSON text
            # representation so the delete works regardless of the JSONB
            # codec's decoded type.
            affected = await conn.fetch(
                """
                UPDATE public.bh_users
                SET settings_json = settings_json - 'theme_id'
                WHERE settings_json->>'theme_id' = $1
                RETURNING id
                """,
                str(theme_id),
            )

            # Clear the platform-default pointer if it pointed here.
            default_row = await conn.fetchrow(
                """
                SELECT value_json FROM public.bh_platform_settings
                WHERE key = 'default_theme_id'
                """
            )
            was_platform_default = False
            if default_row and isinstance(default_row["value_json"], dict):
                if default_row["value_json"].get("theme_id") == theme_id:
                    was_platform_default = True
                    await conn.execute(
                        """
                        UPDATE public.bh_platform_settings
                        SET value_json = jsonb_build_object('theme_id', NULL),
                            updated_by = $1,
                            updated_at = now()
                        WHERE key = 'default_theme_id'
                        """,
                        user["id"],
                    )

            await conn.execute(
                "DELETE FROM public.bh_themes WHERE id = $1", theme_id
            )

    await AuditLogger.log(
        user["id"],
        "delete_theme",
        target_type="theme",
        target_id=theme_id,
        details={
            "name": existing_dict["name"],
            "owner_id": existing_dict["owner_id"],
            "affected_user_count": len(affected),
            "was_platform_default": was_platform_default,
        },
    )

    return {
        "deleted": True,
        "affected_user_count": len(affected),
        "was_platform_default": was_platform_default,
    }


@router.post("/{theme_id}/set-platform-default")
async def set_platform_default(
    theme_id: int, user: dict = Depends(require_admin)
):
    """
    Mark a theme as the platform default applied to users with no override
    (R1.3). Admin only.

    Rejects user-scoped themes with 409: a personal theme is not visible
    to other users, so it can't serve as a platform-wide default.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            theme = await conn.fetchrow(
                "SELECT * FROM public.bh_themes WHERE id = $1", theme_id
            )
            if theme is None:
                raise HTTPException(status_code=404, detail="Theme not found")

            # User-scoped themes (owner_id IS NOT NULL AND is_preset=false)
            # are not visible to other users → cannot be platform default.
            if not theme["is_preset"] and theme["owner_id"] is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "User-scoped themes cannot be set as platform "
                        "default. Publish the theme first (admin) or pick "
                        "a preset / admin-published theme."
                    ),
                )

            await conn.execute(
                """
                INSERT INTO public.bh_platform_settings (key, value_json, updated_by)
                VALUES ('default_theme_id', $1::jsonb, $2)
                ON CONFLICT (key) DO UPDATE
                  SET value_json = EXCLUDED.value_json,
                      updated_by = EXCLUDED.updated_by,
                      updated_at = now()
                """,
                json.dumps({"theme_id": theme_id}),
                user["id"],
            )

    await AuditLogger.log(
        user["id"],
        "set_platform_default_theme",
        target_type="theme",
        target_id=theme_id,
        details={"name": theme["name"]},
    )

    return {"ok": True, "theme_id": theme_id}
