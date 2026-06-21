"""Finance-accounting Tasks 2-4 — accounting config + TransferLinker + backfill.

Covers R1.1-1.6 (auto-link unique counterpart, asymmetric gate on ambiguity,
single-leg untouched, manual link/unlink sticky, idempotent backfill) and R4.3
(config loader). DB-backed on an ephemeral migrated DB.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.accounting.config import load_config
from backend.services.accounting.transfers import TransferLinker
from backend.tests.semantic_helpers import apply_migrations


async def _mk_account(conn, name):
    return await conn.fetchval(
        "INSERT INTO finance.accounts (id, org_name, account_name) "
        "VALUES (gen_random_uuid()::text, 'T', $1) RETURNING id", name)


async def _mk_txn(conn, acct, amount, *, is_transfer=False, days_ago=0, desc="x"):
    return await conn.fetchval(
        "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, is_transfer) "
        "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE - $2::int, $3, $4, $5) RETURNING id",
        acct, days_ago, amount, desc, is_transfer)


@pytest.mark.asyncio
async def test_config_defaults(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = await load_config(conn)
        assert cfg.match_date_window_days == 4
        assert cfg.match_amount_tolerance == 0.01
        assert cfg.reconcile_tolerance == 0.01
        assert cfg.stale_balance_days == 7
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_autolink_unique_counterpart(fresh_db, db_settings):
    """R1.2: a unique opposite leg in another account links symmetrically."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            chk = await _mk_account(conn, "Checking")
            sav = await _mk_account(conn, "Savings")
            a = await _mk_txn(conn, chk, -500, is_transfer=True)
            b = await _mk_txn(conn, sav, 500, is_transfer=True, days_ago=1)
            res = await TransferLinker(conn).link_pass()
            assert res["linked"] == 1
            assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id=$1", a) == b
            assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id=$1", b) == a
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_ambiguous_not_linked(fresh_db, db_settings):
    """R1.3: two candidate counterparts → leave for review, never auto-link."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            chk = await _mk_account(conn, "Checking")
            sav = await _mk_account(conn, "Savings")
            await _mk_txn(conn, chk, -500, is_transfer=True)
            await _mk_txn(conn, sav, 500, is_transfer=True)
            await _mk_txn(conn, sav, 500, is_transfer=True)  # second candidate
            res = await TransferLinker(conn).link_pass()
            assert res["linked"] == 0 and res["ambiguous"] >= 1
            assert await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE transfer_id IS NOT NULL") == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_single_leg_untouched(fresh_db, db_settings):
    """R1.4: a transfer with no counterpart stays is_transfer=true, transfer_id NULL."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            chk = await _mk_account(conn, "Checking")
            a = await _mk_txn(conn, chk, -500, is_transfer=True)
            res = await TransferLinker(conn).link_pass()
            assert res["linked"] == 0
            row = await conn.fetchrow(
                "SELECT is_transfer, transfer_id FROM finance.transactions WHERE id=$1", a)
            assert row["is_transfer"] is True and row["transfer_id"] is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_manual_link_unlink_sticky(fresh_db, db_settings):
    """R1.5: manual link sets is_transfer + sticky flag and survives a re-run; unlink clears both."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            chk = await _mk_account(conn, "Checking")
            sav = await _mk_account(conn, "Savings")
            a = await _mk_txn(conn, chk, -75, is_transfer=False)  # not yet a transfer
            b = await _mk_txn(conn, sav, 75, is_transfer=False)
            linker = TransferLinker(conn)
            await linker.link(a, b)
            row = await conn.fetchrow(
                "SELECT is_transfer, transfer_id, transfer_link_manual FROM finance.transactions WHERE id=$1", a)
            assert row["is_transfer"] is True and row["transfer_id"] == b and row["transfer_link_manual"] is True
            # auto pass must not disturb a manual link
            await linker.link_pass()
            assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id=$1", a) == b
            # unlink clears both
            await linker.unlink(a)
            assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id=$1", a) is None
            assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id=$1", b) is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_backfill_idempotent(fresh_db, db_settings):
    """R1.6: a second pass links nothing new."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            chk = await _mk_account(conn, "Checking")
            sav = await _mk_account(conn, "Savings")
            await _mk_txn(conn, chk, -500, is_transfer=True)
            await _mk_txn(conn, sav, 500, is_transfer=True)
            assert (await TransferLinker(conn).link_pass())["linked"] == 1
            assert (await TransferLinker(conn).link_pass())["linked"] == 0
    finally:
        await close_pool()
