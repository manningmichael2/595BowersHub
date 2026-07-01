"""Engine branch for native smart-capture (R2.5 / R2.6).

Reads `smart_capture.engine` per call (un-cached) and routes:
  - extract: n8n → proxy; native → in-process; shadow → run native + proxy,
    return n8n's body, but re-mint a native token over n8n's intents so body +
    token agree (the B1 fix), and log the native-vs-n8n diff.
  - commit: n8n → proxy; native/shadow → in-process (no shadow double-write; B2).

Image sub-path (M4): under native/shadow, an image-based extract proxies to n8n
until `smart_capture.process_asset_native` is on (text cuts over first).
"""

from __future__ import annotations

import logging
import time

import httpx

from backend.database import get_pool
from backend.http_client import get_http_client

from .commit import commit_native
from .config import get_engine, get_process_asset_native, get_token_secret
from .extract import extract_native
from .intents import CaptureIntent
from .tokens import mint

logger = logging.getLogger(__name__)

# n8n webhook contract (fixed by the n8n `Smart Capture` workflow, not user config).
_EXTRACT_PATH = "smart-capture/extract"
_COMMIT_PATH = "smart-capture/commit"


async def _proxy_n8n(path: str, body: dict, config) -> dict:
    """POST to the n8n webhook (the rollback/fallback path). Tolerates a
    non-JSON body the way skill_executor does."""
    base = (getattr(config, "N8N_BASE", "") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "n8n engine selected but N8N_BASE is not configured"}
    url = f"{base}/webhook/{path}"
    client = get_http_client()
    try:
        resp = await client.post(url, json=body, timeout=httpx.Timeout(5.0, read=60.0))
    except httpx.TimeoutException:
        return {"ok": False, "error": "n8n request timed out"}
    except httpx.ConnectError:
        return {"ok": False, "error": "n8n connection refused"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"n8n returned HTTP {resp.status_code}"}
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "raw": resp.text[:2000]}


def _log_shadow_diff(native_out: dict, n8n_resp: dict) -> None:
    """Structured, low-noise diff for the S2 soak (R6.2). Compares intent domains
    (structural parity), not full payloads."""
    try:
        nat = [i.get("domain") for i in (native_out.get("intents") or [])]
        ref = [i.get("domain") for i in (n8n_resp.get("intents") or [])]
        logger.info(
            "smart_capture.shadow_diff native_ok=%s n8n_ok=%s domains_match=%s native=%s n8n=%s",
            native_out.get("ok"), n8n_resp.get("ok"), sorted(nat) == sorted(ref), nat, ref,
        )
    except Exception as e:  # never let diagnostics break the request
        logger.debug("shadow diff logging failed: %s", e)


async def _resolve_asset(conn, image_path, params, config) -> tuple[bool, dict | None]:
    """Return (proxied, asset). If native vision isn't enabled/available, signal
    the caller to proxy the whole extract to n8n (M4)."""
    if not await get_process_asset_native(conn):
        return True, None  # flag off → proxy image extract to n8n
    try:
        from .process_asset import process_asset_native
    except ImportError:
        logger.warning("process_asset_native flag on but native module missing; proxying to n8n")
        return True, None
    asset = await process_asset_native(
        image_path=image_path,
        domain_hint=params.get("domain_hint"),
        model_provider=params.get("_model_provider"),
        conn=conn,
    )
    return False, asset


async def run_extract(params: dict) -> dict:
    user_id = params.get("_user_id")
    workspace_id = params.get("_workspace_id")
    config = params.get("_config")
    model_provider = params.get("_model_provider")
    text = params.get("text")
    image_path = params.get("image_path")
    domain_hint = params.get("domain_hint")
    body = {k: params[k] for k in ("text", "image_path", "domain_hint") if params.get(k) is not None}

    pool = get_pool()
    async with pool.acquire() as conn:
        engine = await get_engine(conn)
        if engine == "n8n":
            return await _proxy_n8n(_EXTRACT_PATH, body, config)

        asset = None
        if image_path:
            proxied, asset = await _resolve_asset(conn, image_path, params, config)
            if proxied:
                return await _proxy_n8n(_EXTRACT_PATH, body, config)

        now = time.time()
        if engine == "shadow":
            n8n_resp = await _proxy_n8n(_EXTRACT_PATH, body, config)
            try:
                native_out = await extract_native(
                    text=text, domain_hint=domain_hint, user_id=user_id,
                    workspace_id=workspace_id, model_provider=model_provider,
                    conn=conn, now=now, asset=asset,
                )
                _log_shadow_diff(native_out, n8n_resp)
            except Exception as e:
                logger.warning("shadow native extract failed: %s", e)
            # Re-mint a NATIVE token over n8n's returned intents so the returned
            # body and token agree (B1) — every circulating token is native-HMAC.
            if isinstance(n8n_resp, dict) and n8n_resp.get("ok") and isinstance(n8n_resp.get("intents"), list):
                asset_id = (n8n_resp.get("asset") or {}).get("asset_id")
                secret = await get_token_secret(conn)
                hashes = [CaptureIntent.from_dict(i, asset_id=asset_id).hash() for i in n8n_resp["intents"]]
                n8n_resp["extract_token"] = mint(hashes, user_id, workspace_id, secret, now)
            return n8n_resp

        # engine == native
        return await extract_native(
            text=text, domain_hint=domain_hint, user_id=user_id,
            workspace_id=workspace_id, model_provider=model_provider,
            conn=conn, now=now, asset=asset,
        )


async def run_process_asset(params: dict) -> dict:
    """Standalone process-asset skill. Native when engine≠n8n AND the
    process_asset_native flag is on; otherwise proxy to n8n (M4)."""
    config = params.get("_config")
    model_provider = params.get("_model_provider")
    image_path = params.get("path") or params.get("image_path")
    domain_hint = params.get("domain_hint")
    body = {
        k: params[k]
        for k in ("path", "domain_hint", "uploaded_by", "original_name")
        if params.get(k) is not None
    }

    pool = get_pool()
    async with pool.acquire() as conn:
        engine = await get_engine(conn)
        if engine == "n8n" or not await get_process_asset_native(conn):
            return await _proxy_n8n("process-asset", body, config)
        try:
            from .process_asset import process_asset_native
            asset = await process_asset_native(
                image_path=image_path, domain_hint=domain_hint,
                model_provider=model_provider, conn=conn,
            )
        except ImportError:
            asset = None
        if asset is None:  # native unavailable/failed → fall back to n8n
            return await _proxy_n8n("process-asset", body, config)
        return asset


async def run_commit(params: dict) -> dict:
    user_id = params.get("_user_id")
    workspace_id = params.get("_workspace_id")
    config = params.get("_config")

    pool = get_pool()
    async with pool.acquire() as conn:
        engine = await get_engine(conn)
        if engine == "n8n":
            body = {
                k: params[k]
                for k in ("domain", "payload", "asset_id", "extract_token", "source")
                if params.get(k) is not None
            }
            return await _proxy_n8n(_COMMIT_PATH, body, config)
        # native and shadow both commit natively (no double-write — B2).
        return await commit_native(
            domain=params.get("domain"),
            payload=params.get("payload") or {},
            asset_id=params.get("asset_id"),
            extract_token=params.get("extract_token"),
            user_id=user_id,
            workspace_id=workspace_id,
            conn=conn,
            now=time.time(),
        )
