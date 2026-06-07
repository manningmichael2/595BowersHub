"""
Branding Store: manages the on-disk app-icon set and the matching pointers
in `bh_platform_settings`.

Disk layout under ``$FILES_ROOT/branding/`` (default ``/files/branding/``):

    active/                      <- currently served at /icons/<file>
        icon-192.png
        icon-512.png
        icon-maskable-512.png
    previous/                    <- single rollback slot (R2.7); empty on first deploy
        icon-192.png
        icon-512.png
        icon-maskable-512.png
    default/                     <- materialized on revert_to_default()
        icon-192.png
        icon-512.png
        icon-maskable-512.png
    history/<UTC-timestamp>/     <- archived prior `previous/` sets

`bh_platform_settings` rows tracked:
    app_icon_version              {"version": "<unix-epoch-string>"}
    app_icon_active_filename      {"filename": "<logical name>"}
    app_icon_previous_filename    {"filename": "<logical name>"|null}

The `version` column is the cache-busting query string the manifest and
``<link rel="icon">`` use; the `filename` columns are logical labels for
audit/UI purposes only — the URLs served at ``/icons/<file>`` are stable
(R2.5).

This module is the implementation surface for property test §13-4
(``test_icon_validator.py``) and integration test §7.3
(``test_branding_store_integration.py``).
"""

from __future__ import annotations

import importlib.util
import io
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PIL import Image, UnidentifiedImageError

from backend.config import Config
from backend.database import get_pool

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Validation rules (R2.3): image/png, square within 1% tolerance, min 512px,
# max 4 MB.
# -----------------------------------------------------------------------------

_REQUIRED_MIME = "image/png"
_MIN_DIMENSION = 512
_MAX_FILE_SIZE = 4 * 1024 * 1024  # 4 MB
_SQUARE_TOLERANCE = 0.01  # 1%

# Maskable safe-zone: 12% padding on each side, matching scripts/generate_icons.py
_MASKABLE_PADDING_RATIO = 0.12

# File names served under /icons/ (stable; R2.5)
_VARIANT_FILENAMES: tuple[str, ...] = (
    "icon-192.png",
    "icon-512.png",
    "icon-maskable-512.png",
)


@dataclass(frozen=True)
class FieldError:
    """Per-field validation error, JSON-friendly."""

    field: str
    message: str


class IconValidationError(Exception):
    """Raised when uploaded icon bytes fail validation. Carries field errors."""

    def __init__(self, errors: list[FieldError]):
        self.errors = errors
        super().__init__(
            "; ".join(f"{e.field}: {e.message}" for e in errors) or "icon validation failed"
        )


class RollbackUnavailable(Exception):
    """Raised by ``rollback()`` when no previous slot is populated."""


# -----------------------------------------------------------------------------
# Pure validator (sync)
# -----------------------------------------------------------------------------


def validate_icon(
    mime: str,
    width: int,
    height: int,
    size_bytes: int,
) -> tuple[bool, list[FieldError]]:
    """
    Apply the four published rules to a candidate upload. Returns
    ``(ok, errors)`` where ``ok`` is True iff every rule passed and
    ``errors`` enumerates per-rule failures otherwise.

    Rules (R2.3):
      1. ``mime == 'image/png'``
      2. ``min(width, height) >= 512``
      3. ``abs(width - height) / max(width, height) <= 0.01`` (square ±1%)
      4. ``size_bytes <= 4 * 1024 * 1024``

    Total over (mime, width, height, size_bytes); never raises. Property
    test §13-4 covers boundary inputs.
    """
    errors: list[FieldError] = []

    if mime != _REQUIRED_MIME:
        errors.append(
            FieldError(
                field="mime",
                message=(
                    f"icon must be {_REQUIRED_MIME}; got "
                    f"{mime!r}"
                ),
            )
        )

    # Guard against zero/negative dimensions before computing ratios.
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        errors.append(
            FieldError(
                field="dimensions",
                message="width and height must be positive integers",
            )
        )
    else:
        if min(width, height) < _MIN_DIMENSION:
            errors.append(
                FieldError(
                    field="dimensions",
                    message=(
                        f"icon must be at least {_MIN_DIMENSION}x{_MIN_DIMENSION}px; "
                        f"got {width}x{height}px"
                    ),
                )
            )
        ratio = abs(width - height) / max(width, height)
        if ratio > _SQUARE_TOLERANCE:
            errors.append(
                FieldError(
                    field="aspect",
                    message=(
                        f"icon must be square within 1% tolerance; "
                        f"got {width}x{height} (ratio {ratio:.4f})"
                    ),
                )
            )

    if not isinstance(size_bytes, int) or size_bytes < 0:
        errors.append(
            FieldError(
                field="size",
                message="size_bytes must be a non-negative integer",
            )
        )
    elif size_bytes > _MAX_FILE_SIZE:
        errors.append(
            FieldError(
                field="size",
                message=(
                    f"icon must be {_MAX_FILE_SIZE} bytes (4 MB) or smaller; "
                    f"got {size_bytes} bytes"
                ),
            )
        )

    return (len(errors) == 0, errors)


# -----------------------------------------------------------------------------
# Path helpers
# -----------------------------------------------------------------------------


def _branding_root(config: Optional[Config] = None) -> Path:
    """
    Resolve the branding root directory. Read from the supplied Config or
    fall back to ``$FILES_ROOT/branding`` from the environment-driven
    Config defaults.
    """
    if config is None:
        # Lazy import so test fixtures can monkeypatch FILES_ROOT before
        # this module is imported.
        import os

        files_root = os.environ.get("FILES_ROOT", "/files")
    else:
        files_root = config.FILES_ROOT
    return Path(files_root) / "branding"


def _build_urls(version: str) -> dict[str, str]:
    """Versioned URLs for the three variants (R2.4, R2.5)."""
    return {
        "icon_192": f"/icons/icon-192.png?v={version}",
        "icon_512": f"/icons/icon-512.png?v={version}",
        "icon_maskable_512": f"/icons/icon-maskable-512.png?v={version}",
    }


# -----------------------------------------------------------------------------
# Pillow processing
# -----------------------------------------------------------------------------


def _load_uploaded(file_bytes: bytes) -> Image.Image:
    """
    Decode the uploaded bytes and surface bad files as IconValidationError.
    Returns a Pillow image already in RGBA mode.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise IconValidationError(
            [FieldError(field="file", message=f"could not decode image: {e}")]
        )
    return img


def _square_crop(img: Image.Image) -> Image.Image:
    """
    If the source is non-square (within the 1% tolerance allowed by
    ``validate_icon``), center-crop to a perfect square. Already-square
    inputs pass through unchanged.
    """
    width, height = img.size
    if width == height:
        return img
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return img.crop((left, top, left + side, top + side))


def _generate_variants(file_bytes: bytes) -> dict[str, bytes]:
    """
    Build the three icon variants from uploaded source bytes.

    - ``icon-192.png``: source resized to 192x192 (any-purpose)
    - ``icon-512.png``: source resized to 512x512 (any-purpose)
    - ``icon-maskable-512.png``: source resized to fit the inner 76% safe
      zone (12% padding each side) on a 512x512 transparent canvas. Matches
      the safe-zone convention from ``scripts/generate_icons.py``.
    """
    img = _load_uploaded(file_bytes).convert("RGBA")
    img = _square_crop(img)

    icon_192 = img.resize((192, 192), Image.LANCZOS)
    icon_512 = img.resize((512, 512), Image.LANCZOS)

    canvas_size = 512
    pad = int(canvas_size * _MASKABLE_PADDING_RATIO)
    inner = canvas_size - 2 * pad
    inner_img = img.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(inner_img, (pad, pad), inner_img)
    icon_maskable_512 = canvas

    out: dict[str, bytes] = {}
    for name, im in (
        ("icon-192.png", icon_192),
        ("icon-512.png", icon_512),
        ("icon-maskable-512.png", icon_maskable_512),
    ):
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        out[name] = buf.getvalue()
    return out


def _draw_default_variant(size: int, maskable: bool) -> Image.Image:
    """
    Invoke ``scripts/generate_icons.py``'s ``draw_icon`` in-process so the
    built-in fallback set matches the existing PWA branding exactly.
    """
    cache_attr = "_module"
    cache: dict[str, Any] = _draw_default_variant.__dict__.setdefault(cache_attr, {})
    if "module" not in cache:
        # backend/services/branding_store.py -> parents[2] = bowershub-ai/
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_icons.py"
        spec = importlib.util.spec_from_file_location("_bh_generate_icons", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load generate_icons module from {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        cache["module"] = module
    return cache["module"].draw_icon(size, maskable=maskable)


def _generate_default_set() -> dict[str, bytes]:
    """Build the built-in fallback icon set as raw PNG bytes per filename."""
    out: dict[str, bytes] = {}
    for name, size, maskable in (
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ):
        img = _draw_default_variant(size, maskable=maskable)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        out[name] = buf.getvalue()
    return out


# -----------------------------------------------------------------------------
# Filesystem helpers — atomic swaps, archive, write
# -----------------------------------------------------------------------------


def _write_set(target_dir: Path, files: dict[str, bytes]) -> None:
    """Materialize the three variant files inside ``target_dir``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in _VARIANT_FILENAMES:
        if name not in files:
            raise RuntimeError(f"missing variant {name!r} in generated set")
        (target_dir / name).write_bytes(files[name])


def _dir_has_files(d: Path) -> bool:
    return d.exists() and d.is_dir() and any(d.iterdir())


def _archive_existing_previous(branding_root: Path) -> Optional[str]:
    """
    Move ``branding/previous/`` to ``branding/history/<utc-ts>/`` if it
    has any files. Returns the timestamp dir name on success, None if
    nothing was archived.
    """
    previous = branding_root / "previous"
    if not _dir_has_files(previous):
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
        return None

    history = branding_root / "history"
    history.mkdir(parents=True, exist_ok=True)
    # Microsecond suffix avoids collisions when multiple uploads happen
    # in the same second (rare; mostly defensive).
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = history / ts
    shutil.move(str(previous), str(target))
    logger.info("Archived previous icon set to %s", target)
    return ts


def _atomic_install_active(branding_root: Path, files: dict[str, bytes]) -> Optional[str]:
    """
    Install ``files`` as the new active icon set, archiving the prior
    active into ``previous/`` (and the prior previous into ``history/``).

    Steps (each individually atomic on a single filesystem):
      1. Write new bytes to ``branding/.tmp_<uuid>/``.
      2. Archive existing ``previous/`` into ``history/<ts>/`` if populated.
      3. Move existing ``active/`` to ``previous/``.
      4. Rename ``.tmp_<uuid>/`` to ``active/``.

    Returns the history timestamp if any archive was made, else None.
    """
    branding_root.mkdir(parents=True, exist_ok=True)
    tmp = branding_root / f".tmp_{uuid.uuid4().hex}"
    try:
        _write_set(tmp, files)

        archived_ts = _archive_existing_previous(branding_root)

        active = branding_root / "active"
        previous = branding_root / "previous"
        if _dir_has_files(active):
            shutil.move(str(active), str(previous))
        elif active.exists():
            shutil.rmtree(active, ignore_errors=True)

        shutil.move(str(tmp), str(active))
        return archived_ts
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _swap_active_and_previous(branding_root: Path) -> None:
    """
    Atomically swap ``active/`` and ``previous/`` directory contents.
    Caller must ensure both exist with content; ``rollback()`` enforces
    that.
    """
    active = branding_root / "active"
    previous = branding_root / "previous"
    swap_tmp = branding_root / f".swap_{uuid.uuid4().hex}"

    # Each rename is atomic; the worst outcome on partial failure is a
    # leftover swap_tmp dir which is harmless and easy to spot.
    active.rename(swap_tmp)
    try:
        previous.rename(active)
    except Exception:
        swap_tmp.rename(active)  # best-effort restore
        raise
    swap_tmp.rename(previous)


# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------


async def _read_setting(conn, key: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT value_json FROM public.bh_platform_settings WHERE key = $1",
        key,
    )
    return row["value_json"] if row else None


async def _write_version_and_filenames(
    conn,
    *,
    version: str,
    active_filename: str,
    previous_filename: Optional[str],
) -> None:
    """Update the three icon-tracking rows in ``bh_platform_settings``."""
    await conn.execute(
        """
        UPDATE public.bh_platform_settings
        SET value_json = jsonb_build_object('version', $1::text),
            updated_at = now()
        WHERE key = 'app_icon_version'
        """,
        version,
    )
    await conn.execute(
        """
        UPDATE public.bh_platform_settings
        SET value_json = jsonb_build_object('filename', $1::text),
            updated_at = now()
        WHERE key = 'app_icon_active_filename'
        """,
        active_filename,
    )
    await conn.execute(
        """
        UPDATE public.bh_platform_settings
        SET value_json = jsonb_build_object('filename', $1::text),
            updated_at = now()
        WHERE key = 'app_icon_previous_filename'
        """,
        previous_filename,
    )


def _new_version() -> str:
    """Cache-busting version string. Unix epoch as text; matches migration 009."""
    return str(int(time.time()))


# -----------------------------------------------------------------------------
# Public API — touched the DB so async
# -----------------------------------------------------------------------------


async def upload_icon(file_bytes: bytes) -> dict[str, Any]:
    """
    Validate, render variants, atomically install, update settings.

    Raises
    ------
    IconValidationError
        Bytes are not a valid PNG, are below 512px, are not square within
        1%, are larger than 4 MB, or fail to decode.
    """
    img = _load_uploaded(file_bytes)
    fmt = (img.format or "").upper()
    mime = "image/png" if fmt == "PNG" else f"image/{fmt.lower() or 'unknown'}"
    width, height = img.size
    ok, errors = validate_icon(mime, width, height, len(file_bytes))
    if not ok:
        raise IconValidationError(errors)

    variants = _generate_variants(file_bytes)
    branding_root = _branding_root()
    _atomic_install_active(branding_root, variants)

    version = _new_version()
    new_active_filename = f"icon-set-uploaded-{version}"

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            prior_active = await _read_setting(conn, "app_icon_active_filename")
            prior_active_filename = (prior_active or {}).get("filename")
            await _write_version_and_filenames(
                conn,
                version=version,
                active_filename=new_active_filename,
                previous_filename=prior_active_filename,
            )

    logger.info(
        "Uploaded new app icon: version=%s active=%s previous=%s",
        version,
        new_active_filename,
        prior_active_filename,
    )
    return {"version": version, "urls": _build_urls(version)}


async def revert_to_default() -> dict[str, Any]:
    """
    Replace ``active/`` with a freshly-generated built-in icon set.
    Preserves ``previous/`` so the admin can still rollback to the
    immediately-prior custom icon if they regret reverting (R2.6).
    """
    branding_root = _branding_root()
    branding_root.mkdir(parents=True, exist_ok=True)

    default_set = _generate_default_set()
    default_dir = branding_root / "default"
    if default_dir.exists():
        shutil.rmtree(default_dir)
    _write_set(default_dir, default_set)

    active = branding_root / "active"
    if active.exists():
        shutil.rmtree(active)
    shutil.copytree(default_dir, active)

    version = _new_version()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            prior_previous = await _read_setting(conn, "app_icon_previous_filename")
            prior_previous_filename = (prior_previous or {}).get("filename")
            await _write_version_and_filenames(
                conn,
                version=version,
                active_filename="icon-set-default",
                previous_filename=prior_previous_filename,
            )

    logger.info("Reverted app icon to default: version=%s", version)
    return {"version": version, "urls": _build_urls(version)}


async def rollback() -> dict[str, Any]:
    """
    Swap ``active/`` and ``previous/`` directories and update DB pointers
    to match. Raises ``RollbackUnavailable`` if no previous slot is
    populated (R2.7).
    """
    branding_root = _branding_root()
    previous = branding_root / "previous"
    if not _dir_has_files(previous):
        raise RollbackUnavailable("no previous icon set available to roll back to")

    active = branding_root / "active"
    if not active.exists():
        # Make the swap symmetric: an empty active swapping with previous
        # would leave previous empty after, breaking has_rollback. Treat
        # it as the same error class.
        raise RollbackUnavailable("active icon set is missing on disk")

    _swap_active_and_previous(branding_root)

    version = _new_version()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur_active = await _read_setting(conn, "app_icon_active_filename")
            cur_previous = await _read_setting(conn, "app_icon_previous_filename")
            cur_active_name = (cur_active or {}).get("filename")
            cur_previous_name = (cur_previous or {}).get("filename")
            await _write_version_and_filenames(
                conn,
                version=version,
                active_filename=cur_previous_name or "icon-set-rolled-back",
                previous_filename=cur_active_name,
            )

    logger.info("Rolled back app icon: version=%s", version)
    return {"version": version}


async def get_manifest() -> dict[str, Any]:
    """
    Return the manifest payload for ``GET /api/branding/icon`` (R2.1).

    ``has_rollback`` is true iff the disk-side previous slot has files;
    the DB pointers are advisory and may briefly disagree if a manual
    edit was made on the host filesystem.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key, value_json
            FROM public.bh_platform_settings
            WHERE key IN ('app_icon_version', 'app_icon_previous_filename')
            """
        )
    settings = {row["key"]: row["value_json"] for row in rows}
    version = (settings.get("app_icon_version") or {}).get("version") or "0"

    has_rollback = _dir_has_files(_branding_root() / "previous")

    return {
        "version": str(version),
        "urls": _build_urls(str(version)),
        "has_rollback": has_rollback,
    }
