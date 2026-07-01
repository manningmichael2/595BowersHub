"""Native smart-capture commit (R2.2 / R2.2a / R2.7).

Per-intent commit: verify the extract token (HMAC + expiry + uid/wid +
membership incl. asset) → idempotency guard → route to the domain committer.

Idempotency (m3): `dedup_key = sha256(extract_token || intent.hash())`. An
INSERT … ON CONFLICT DO NOTHING claims the key; a replay (0 rows inserted)
returns the stored result and writes nothing. For DB domains the guard row, the
write, and the result-record are one transaction, so a committer failure rolls
back the guard too (a retry can proceed) and a row+asset-link is atomic (no
orphan). Service-backed domains guard the replay, then delegate to services that
own their connection + content-dedup.
"""

from __future__ import annotations

import hashlib
import json
import logging

from .committers import DB_COMMITTERS, DB_DOMAINS, SERVICE_COMMITTERS
from .config import get_token_secret
from .intents import DOMAINS, intent_hash
from .tokens import verify

logger = logging.getLogger(__name__)

_GUARD_TABLE = "public.bh_smart_capture_commits"


def _dedup_key(extract_token: str, ihash: str) -> str:
    return hashlib.sha256(f"{extract_token}|{ihash}".encode("utf-8")).hexdigest()


async def commit_native(
    *,
    domain: str,
    payload: dict,
    asset_id,
    extract_token: str,
    user_id: int,
    workspace_id: int,
    conn,
    now: float,
) -> dict:
    domain = (domain or "").strip().lower()
    payload = payload or {}
    if domain not in DOMAINS:
        return {"ok": False, "domain": domain, "error": f"Unknown domain: {domain}"}

    # 1. Verify token (tamper/expiry/wrong-ws/membership-incl-asset).
    secret = await get_token_secret(conn)
    ihash = intent_hash(domain, payload, asset_id)
    ok, reason = verify(extract_token, ihash, user_id, workspace_id, secret, now)
    if not ok:
        return {"ok": False, "domain": domain, "error": f"extract_token invalid: {reason}"}

    dedup_key = _dedup_key(extract_token, ihash)

    # 2a. DB domains: guard + write + record, all in one transaction.
    if domain in DB_DOMAINS:
        committer = DB_COMMITTERS[domain]
        try:
            async with conn.transaction():
                claimed = await conn.fetchval(
                    f"INSERT INTO {_GUARD_TABLE} (dedup_key) VALUES ($1) "
                    "ON CONFLICT (dedup_key) DO NOTHING RETURNING dedup_key",
                    dedup_key,
                )
                if claimed is None:  # replay
                    return await _replay(conn, dedup_key, domain)
                result = await committer(conn, payload, asset_id)
                if not result.get("ok"):
                    # A committer-level rejection (e.g. cook_log no match) is not
                    # a crash — surface it, but roll back so the guard row doesn't
                    # make a corrected retry look like a replay.
                    raise _CommitRejected(result)
                await conn.execute(
                    f"UPDATE {_GUARD_TABLE} SET result_json = $2::jsonb WHERE dedup_key = $1",
                    dedup_key, json.dumps(result),
                )
                return result
        except _CommitRejected as rej:
            return rej.result
        except Exception as e:  # real DB error → txn rolled back, guard released
            logger.warning("smart-capture commit (%s) failed: %s", domain, e)
            return {"ok": False, "domain": domain, "error": str(e)}

    # 2b. Service-backed domains: guard replay, delegate, then record.
    committer = SERVICE_COMMITTERS[domain]
    claimed = await conn.fetchval(
        f"INSERT INTO {_GUARD_TABLE} (dedup_key) VALUES ($1) "
        "ON CONFLICT (dedup_key) DO NOTHING RETURNING dedup_key",
        dedup_key,
    )
    if claimed is None:
        return await _replay(conn, dedup_key, domain)
    try:
        result = await committer(payload, user_id)
    except Exception as e:  # release the guard so a retry can proceed
        await conn.execute(
            f"DELETE FROM {_GUARD_TABLE} WHERE dedup_key = $1 AND result_json IS NULL", dedup_key
        )
        logger.warning("smart-capture commit (%s) failed: %s", domain, e)
        return {"ok": False, "domain": domain, "error": str(e)}
    if not result.get("ok"):
        await conn.execute(
            f"DELETE FROM {_GUARD_TABLE} WHERE dedup_key = $1 AND result_json IS NULL", dedup_key
        )
        return result
    await conn.execute(
        f"UPDATE {_GUARD_TABLE} SET result_json = $2::jsonb WHERE dedup_key = $1",
        dedup_key, json.dumps(result),
    )
    return result


async def _replay(conn, dedup_key: str, domain: str) -> dict:
    prior = await conn.fetchval(
        f"SELECT result_json FROM {_GUARD_TABLE} WHERE dedup_key = $1", dedup_key
    )
    if prior:
        # asyncpg jsonb codec returns a dict; be defensive if it's a str.
        return prior if isinstance(prior, dict) else json.loads(prior)
    return {"ok": False, "domain": domain, "error": "duplicate commit already in progress"}


class _CommitRejected(Exception):
    """Rolls back the DB-domain transaction on a committer-level rejection while
    carrying the rejection result back to the caller."""

    def __init__(self, result: dict):
        self.result = result
        super().__init__(result.get("error", "commit rejected"))
