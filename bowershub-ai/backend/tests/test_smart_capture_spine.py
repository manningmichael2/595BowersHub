"""Task 2 + 6 — smart_capture spine: intents canonical form, HMAC tokens,
DB-driven config, and migration 0058. (n8n-decommission spec)

Pure tests (intents/tokens) need no DB; config + migration tests use fresh_db.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.smart_capture import config as sc_config
from backend.services.smart_capture import tokens as sc_tokens
from backend.services.smart_capture.intents import (
    DOMAINS,
    CaptureIntent,
    canonical,
    intent_hash,
)
from backend.tests.semantic_helpers import apply_migrations

SECRET = bytes(range(32))  # deterministic 32-byte key
T0 = 1_000_000.0          # fixed "now" so expiry math is exact


# ─────────────────────────── intents.canonical ───────────────────────────

def test_canonical_stable_under_reordered_keys_and_whitespace():
    a = canonical("tool", {"brand": "DeWalt", "model": "DW735"}, None)
    b = canonical("tool", {"model": "DW735", "brand": "DeWalt"}, None)
    assert a == b  # sort_keys makes payload ordering irrelevant
    assert " " not in a  # tight separators — no incidental whitespace
    assert intent_hash("tool", {"a": 1, "b": 2}, None) == intent_hash("tool", {"b": 2, "a": 1}, None)


def test_canonical_stable_under_unicode():
    h1 = intent_hash("other", {"content": "café ☕ naïve"}, None)
    h2 = intent_hash("other", {"content": "café ☕ naïve"}, None)
    assert h1 == h2


def test_canonical_binds_asset_id():
    # Same domain+payload but different asset → different hash (asset is bound).
    assert intent_hash("recipe", {"title": "x"}, "asset-A") != intent_hash(
        "recipe", {"title": "x"}, "asset-B"
    )
    assert intent_hash("recipe", {"title": "x"}, None) != intent_hash(
        "recipe", {"title": "x"}, "asset-A"
    )


def test_captureintent_roundtrip_and_domains():
    i = CaptureIntent.from_dict(
        {"domain": "shopping_list", "summary": "s", "payload": {"items": ["milk"]}},
        asset_id="a1",
    )
    assert i.hash() == intent_hash("shopping_list", {"items": ["milk"]}, "a1")
    assert i.to_dict()["domain"] == "shopping_list"
    assert "asset_id" not in i.to_dict()  # wire shape hides the bound asset
    assert "knowledge_fact" in DOMAINS and len(DOMAINS) == 13


# ─────────────────────────── tokens mint/verify ───────────────────────────

def _mint_one(domain="tool", payload=None, asset_id=None, uid=7, wid=3, now=T0):
    h = intent_hash(domain, payload or {"x": 1}, asset_id)
    return sc_tokens.mint([h], uid, wid, SECRET, now), h


def test_valid_token_verifies():
    tok, h = _mint_one()
    ok, reason = sc_tokens.verify(tok, h, 7, 3, SECRET, T0 + 60)
    assert ok, reason


def test_tampered_token_rejected():
    import base64

    tok, h = _mint_one(uid=7)
    body_b64, sig_b64 = tok.split(".")
    # Mutate the SIGNED content (uid 7 → 8) but keep the original signature:
    # the recomputed HMAC over the mutated body can't match → signature mismatch.
    raw = base64.urlsafe_b64decode(body_b64.encode())
    assert b'"uid":7' in raw
    tampered = base64.urlsafe_b64encode(raw.replace(b'"uid":7', b'"uid":8')).decode() + "." + sig_b64
    ok, reason = sc_tokens.verify(tampered, h, 7, 3, SECRET, T0)
    assert not ok and "signature" in reason


def test_wrong_secret_rejected():
    tok, h = _mint_one()
    ok, _ = sc_tokens.verify(tok, h, 7, 3, bytes(range(1, 33)), T0)
    assert not ok


def test_expired_token_rejected():
    tok, h = _mint_one(now=T0)
    ok, reason = sc_tokens.verify(tok, h, 7, 3, SECRET, T0 + sc_tokens.TOKEN_TTL_SECONDS + 1)
    assert not ok and "expired" in reason


def test_wrong_workspace_rejected():
    tok, h = _mint_one(wid=3)
    ok, reason = sc_tokens.verify(tok, h, 7, 99, SECRET, T0)
    assert not ok and "user/workspace" in reason


def test_wrong_user_rejected():
    tok, h = _mint_one(uid=7)
    ok, _ = sc_tokens.verify(tok, h, 99, 3, SECRET, T0)
    assert not ok


def test_membership_multi_intent():
    h1 = intent_hash("tool", {"a": 1}, None)
    h2 = intent_hash("shopping_list", {"items": ["x"]}, None)
    tok = sc_tokens.mint([h1, h2], 7, 3, SECRET, T0)
    # Both signed intents verify individually (membership, not equality).
    assert sc_tokens.verify(tok, h1, 7, 3, SECRET, T0)[0]
    assert sc_tokens.verify(tok, h2, 7, 3, SECRET, T0)[0]
    # An intent NOT in the extract is rejected.
    fake = intent_hash("wood", {"species": "oak"}, None)
    ok, reason = sc_tokens.verify(tok, fake, 7, 3, SECRET, T0)
    assert not ok and "membership" in reason


def test_asset_swap_rejected():
    # Token minted over an intent bound to asset-A; committing the same
    # domain/payload with asset-B must fail membership.
    tok, _ = _mint_one(domain="recipe", payload={"title": "x"}, asset_id="asset-A")
    swapped = intent_hash("recipe", {"title": "x"}, "asset-B")
    ok, reason = sc_tokens.verify(tok, swapped, 7, 3, SECRET, T0)
    assert not ok and "membership" in reason


def test_fabricated_token_rejected():
    ok, _ = sc_tokens.verify("not-a-token", "deadbeef", 7, 3, SECRET, T0)
    assert not ok
    ok2, _ = sc_tokens.verify("", "deadbeef", 7, 3, SECRET, T0)
    assert not ok2


# ─────────────────────────── config + migration (DB) ───────────────────────────

@pytest.mark.asyncio
async def test_migration_0058_applies_and_is_idempotent(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # settings seeded
            assert await sc_config.get_engine(conn) == "n8n"
            secret = await sc_config.get_token_secret(conn)
            assert isinstance(secret, bytes) and len(secret) == 32
            assert await sc_config.get_process_asset_native(conn) is False
            assert await sc_config.get_inbox_workspace_id(conn) is None
            # dedup table present
            reg = await conn.fetchval("SELECT to_regclass('public.bh_smart_capture_commits')")
            assert reg is not None

            # Idempotent re-run: secret is stable, no duplicate-key errors.
            secret_before = secret
            with open(_migration_path()) as f:
                sql = f.read()
            await conn.execute(sql)
            assert await sc_config.get_token_secret(conn) == secret_before
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_get_engine_defaults_and_validates(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # unknown value → fail-safe to n8n
            await conn.execute(
                "UPDATE public.bh_platform_settings SET value_json='\"bogus\"'::jsonb "
                "WHERE key='smart_capture.engine'"
            )
            assert await sc_config.get_engine(conn) == "n8n"
            for eng in ("native", "shadow", "n8n"):
                await conn.execute(
                    "UPDATE public.bh_platform_settings SET value_json=$1::jsonb "
                    "WHERE key='smart_capture.engine'",
                    f'"{eng}"',
                )
                assert await sc_config.get_engine(conn) == eng
            # missing row → default
            await conn.execute(
                "DELETE FROM public.bh_platform_settings WHERE key='smart_capture.engine'"
            )
            assert await sc_config.get_engine(conn) == "n8n"
    finally:
        await close_pool()


def _migration_path() -> str:
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "migrations", "0058_smart_capture_native.sql")
