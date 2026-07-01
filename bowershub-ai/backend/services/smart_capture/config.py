"""DB-driven smart-capture config (R2.6) — from public.bh_platform_settings.

Mirrors ``categorization/config.py``: every operational knob is a row, not a
constant (NO-HARDCODING). The engine switch (n8n|native|shadow) is the
cutover/rollback control; the token secret is the HMAC key for extract tokens.
Reads are **un-cached** — one small SELECT per dispatch — so flipping the engine
row takes effect on the next request with no restart (the basis of the R6.3
rollback claim). At 2-user scale this is negligible.

asyncpg is configured with a jsonb codec (see database.py), so ``value_json``
comes back already decoded (str/bool/int/None). We still defensively unwrap a
raw JSON-quoted string so this loader is correct whether or not the codec is on.
"""

from __future__ import annotations

import binascii
from typing import Optional

VALID_ENGINES = frozenset({"n8n", "native", "shadow"})
DEFAULT_ENGINE = "n8n"

_ENGINE_KEY = "smart_capture.engine"
_SECRET_KEY = "smart_capture.token_secret"
_PROCESS_ASSET_NATIVE_KEY = "smart_capture.process_asset_native"
_INBOX_WORKSPACE_KEY = "smart_capture.inbox_workspace_id"


class SmartCaptureConfigError(RuntimeError):
    """Raised when a required setting (e.g. the token secret) is missing/invalid."""


async def _fetch(conn, key: str):
    return await conn.fetchval(
        "SELECT value_json FROM public.bh_platform_settings WHERE key = $1", key
    )


async def get_engine(conn) -> str:
    """Return the active engine, defaulting to 'n8n' (fail-safe) for a missing or
    unrecognized value."""
    val = await _fetch(conn, _ENGINE_KEY)
    if isinstance(val, str):
        val = val.strip().strip('"')
    return val if val in VALID_ENGINES else DEFAULT_ENGINE


async def get_token_secret(conn) -> bytes:
    """Return the 32-byte HMAC secret (stored as 64 hex chars). Pinned decode so
    mint and verify always agree (m5)."""
    val = await _fetch(conn, _SECRET_KEY)
    if not isinstance(val, str):
        raise SmartCaptureConfigError(
            "smart_capture.token_secret is missing or not a string — run migration 0058"
        )
    hexstr = val.strip().strip('"')
    try:
        secret = binascii.unhexlify(hexstr)
    except (binascii.Error, ValueError) as e:
        raise SmartCaptureConfigError(f"smart_capture.token_secret is not valid hex: {e}")
    if len(secret) != 32:
        raise SmartCaptureConfigError(
            f"smart_capture.token_secret must decode to 32 bytes, got {len(secret)}"
        )
    return secret


async def get_process_asset_native(conn) -> bool:
    """True once native vision (process-asset) is live. Default False → image
    extract proxies to n8n even under engine=native (M4 fallback)."""
    val = await _fetch(conn, _PROCESS_ASSET_NATIVE_KEY)
    if isinstance(val, str):
        val = val.strip().strip('"').lower()
        return val in ("true", "1", "yes")
    return bool(val)


async def get_inbox_workspace_id(conn) -> Optional[int]:
    """Workspace for admin-only inbox extract routes, or None → resolve at
    runtime to the admin's default workspace (never a hardcoded id)."""
    val = await _fetch(conn, _INBOX_WORKSPACE_KEY)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
