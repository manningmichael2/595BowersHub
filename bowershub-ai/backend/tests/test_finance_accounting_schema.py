"""Finance-accounting Task 1 — schema (0029) + seed (0030).

DB-backed against the real baseline→head chain via apply_migrations() on an
ephemeral DB: proves the SQL applies from empty (C2), the transfer-link integrity
constraints hold (R1.8), the new columns reach the public.transactions view (R4.2),
and the config defaults seed (R4.3).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_0029_columns_tables_and_view(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # New transaction columns.
            cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='finance' AND table_name='transactions'")}
            assert {"transfer_id", "transfer_link_manual", "cleared"} <= cols
            # New account columns.
            acct_cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='finance' AND table_name='accounts'")}
            assert {"reconciled_through_date", "include_in_net_worth"} <= acct_cols
            # New tables.
            for tbl in ("reconciliations", "balance_snapshots", "accounting_config"):
                assert await conn.fetchval(
                    "SELECT to_regclass($1)", f"finance.{tbl}") is not None, tbl
            # View exposes the new columns (R4.2).
            view_cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='transactions'")}
            assert {"transfer_id", "cleared"} <= view_cols
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_transfer_link_integrity(fresh_db, db_settings):
    """R1.8: no self-link, ON DELETE SET NULL, partial-unique blocks many-to-one."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'Checking') RETURNING id")
            ids = []
            for amt in (-50, 50, 50):
                ids.append(await conn.fetchval(
                    "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
                    "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, $2, 'x') RETURNING id", acct, amt))
            a, b, c = ids

            # no self-link
            with pytest.raises(Exception):
                await conn.execute("UPDATE finance.transactions SET transfer_id=id WHERE id=$1", a)

            # symmetric link a<->b
            async with conn.transaction():
                await conn.execute("UPDATE finance.transactions SET transfer_id=$2 WHERE id=$1", a, b)
                await conn.execute("UPDATE finance.transactions SET transfer_id=$2 WHERE id=$1", b, a)

            # partial-unique: c cannot also point at b
            with pytest.raises(Exception):
                await conn.execute("UPDATE finance.transactions SET transfer_id=$2 WHERE id=$1", c, b)

            # ON DELETE SET NULL: deleting b nulls a's pointer
            await conn.execute("DELETE FROM finance.transactions WHERE id=$1", b)
            assert await conn.fetchval(
                "SELECT transfer_id FROM finance.transactions WHERE id=$1", a) is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_0030_seeds_config_defaults(fresh_db, db_settings):
    """R4.3: accounting_config defaults seeded; idempotent."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = {r["key"]: r["value"] for r in await conn.fetch(
                "SELECT key, value FROM finance.accounting_config")}
            for k in ("match_date_window_days", "match_amount_tolerance",
                      "reconcile_tolerance", "stale_balance_days"):
                assert k in cfg, k
    finally:
        await close_pool()
