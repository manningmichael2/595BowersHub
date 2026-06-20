"""Task 3 — merchant normalization (R1.1/R1.5).

The R1.1 contract is a fixture table of raw→clean pairs, exercised against the
ACTUAL seeded rules (0024) loaded from the DB — so the test verifies the rules
ship correctly, not just the engine. Plus a pure-engine test and a backfill test.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.merchant_normalizer import (
    MerchantNormalizer,
    backfill_merchant_keys,
    build_normalizer,
)
from backend.tests.semantic_helpers import apply_migrations

# Raw bank descriptor → expected clean display name (R1.1 acceptance contract).
FIXTURES = [
    ("COSTCO WHSE #0393 MADISON HEIGHMI", "Costco"),
    ("SQ *SUNRISE BAKERY",                "Sunrise Bakery"),
    ("TST* THE COFFEE HOUSE",             "The Coffee House"),
    ("WALMART SUPERCENTER",               "Walmart"),
    ("KROGER #123",                       "Kroger"),
    ("SHELL OIL 12345",                   "Shell Oil"),
    ("RANDOM LOCAL SHOP",                 "Random Local Shop"),  # unmatched → cleaned fallthrough
]


def test_engine_applies_rules_in_order():
    """Pure engine: ordered substitutions + whitespace collapse + title-case."""
    norm = MerchantNormalizer([
        (r"^\s*(SQ|TST)\s*\*\s*", ""),
        (r"\s*#\s*\d+.*$", ""),
    ])
    assert norm.normalize("SQ *SUNRISE BAKERY").display == "Sunrise Bakery"
    assert norm.normalize("KROGER #123").display == "Kroger"
    # key is the stable UPPER form
    assert norm.normalize("KROGER #123").key == "KROGER"
    # empty / unmatched-to-empty falls back, never raises
    assert norm.normalize("").key == ""
    assert norm.normalize(None).key == ""


@pytest.mark.asyncio
async def test_seeded_rules_match_fixture_table(fresh_db, db_settings):
    """R1.1: the rules seeded by 0024 produce the expected clean names."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            normalizer = await build_normalizer(conn)
        for raw, expected in FIXTURES:
            assert normalizer.normalize(raw).display == expected, f"{raw!r} → {expected!r}"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_backfill_sets_key_and_upserts_merchant(fresh_db, db_settings):
    """R1.5: backfill derives merchant_key for NULL rows and populates the directory."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'Test', 'Checking') RETURNING id"
            )
            for desc in ("COSTCO WHSE #0393 MADISON HEIGHMI", "SQ *SUNRISE BAKERY"):
                await conn.execute(
                    "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
                    "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -10.00, $2)",
                    acct, desc,
                )

        result = await backfill_merchant_keys(only_missing=True)
        assert result["updated"] == 2

        async with pool.acquire() as conn:
            keys = await conn.fetch(
                "SELECT merchant_key FROM finance.transactions ORDER BY merchant_key"
            )
            assert [r["merchant_key"] for r in keys] == ["COSTCO", "SUNRISE BAKERY"]
            costco = await conn.fetchval(
                "SELECT display_name FROM finance.merchants WHERE merchant_key = 'COSTCO'"
            )
            assert costco == "Costco"

        # Idempotent: a second pass touches nothing (all keys populated).
        again = await backfill_merchant_keys(only_missing=True)
        assert again["updated"] == 0
    finally:
        await close_pool()
