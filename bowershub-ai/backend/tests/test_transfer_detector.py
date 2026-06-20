"""Task 5 — TransferDetector tier (R6).

Counterpart-matched transfers + liability payments auto-flag (high confidence);
ambiguous single-leg cases route to the "transfer?" queue (low confidence, never
silent); is_transfer_manual is honored; flagged transfers drop out of spending
totals and un-flagging restores them; the historical backfill is idempotent.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import TxnContext
from backend.services.categorization.transfer import TransferDetector
from backend.services.categorization.transfer_backfill import backfill_transfer_flags
from backend.tests.semantic_helpers import apply_migrations


async def _account(conn, name: str, account_type: str) -> str:
    return await conn.fetchval(
        "INSERT INTO finance.accounts (id, org_name, account_name, account_type) "
        "VALUES (gen_random_uuid()::text, 'Test', $1, $2) RETURNING id",
        name, account_type,
    )


async def _txn(conn, account_id: str, amount: float, desc: str, *, day: str = "CURRENT_DATE") -> str:
    return await conn.fetchval(
        f"INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
        f"VALUES (gen_random_uuid()::text, $1, {day}, $2, $3) RETURNING id",
        account_id, amount, desc,
    )


def _ctx(txn_id, desc, amount, *, account_id=None, account_type=None, posted_date=None,
         is_transfer_manual=False) -> TxnContext:
    return TxnContext(txn_id=txn_id, description=desc, amount=amount, account_id=account_id,
                      account_type=account_type, posted_date=posted_date,
                      is_transfer_manual=is_transfer_manual)


@pytest.mark.asyncio
async def test_counterpart_matched_transfer_auto_flags(fresh_db, db_settings):
    """checking → savings: opposite-sign equal-amount legs near in date → high-conf terminal flag."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            checking = await _account(conn, "Checking", "checking")
            savings = await _account(conn, "Savings", "savings")
            out_id = await _txn(conn, checking, -500.00, "TRANSFER TO SAVINGS XXXX1234")
            await _txn(conn, savings, 500.00, "TRANSFER FROM CHECKING XXXX5678")

            detector = TransferDetector(conn)
            out_row = await conn.fetchrow(
                "SELECT posted_date FROM finance.transactions WHERE id = $1", out_id)
            decision = await detector.classify(_ctx(
                out_id, "TRANSFER TO SAVINGS XXXX1234", -500.00,
                account_id=checking, account_type="checking",
                posted_date=out_row["posted_date"]))

        assert decision.is_transfer is True
        assert decision.terminal is True
        assert decision.confidence >= 0.9
        assert decision.category_id is None  # never categorized as spending (R6.4)
        assert decision.rationale["method"] == "counterpart_match"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_liability_payment_flags_via_account_type(fresh_db, db_settings):
    """A confirmed payment into a credit_card / loan account → high-conf transfer (R6.2)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            detector = TransferDetector(conn)
            cc = await detector.classify(_ctx(
                "t1", "ONLINE PAYMENT THANK YOU", 250.00, account_type="credit_card"))
            # A bare inflow without a payment descriptor is ambiguous (could be a refund).
            refund = await detector.classify(_ctx(
                "t2", "AMZN REFUND", 40.00, account_type="credit_card"))

        assert cc.is_transfer is True and cc.terminal is True and cc.confidence >= 0.9
        assert cc.rationale["method"] == "liability_payment"
        assert refund.is_transfer is True and refund.terminal is False
        assert refund.confidence < 0.9  # → "transfer?" queue, not auto-flagged
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_ambiguous_single_leg_routes_to_queue(fresh_db, db_settings):
    """A descriptor-only transfer with no counterpart → low-confidence (queue), never auto."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            detector = TransferDetector(conn)
            ambiguous = await detector.classify(_ctx(
                "t1", "CHASE CREDIT CRD AUTOPAY", -250.00, account_type="checking"))
            # ATM cash is NOT a transfer.
            atm = await detector.classify(_ctx(
                "t2", "ATM WITHDRAWAL #0921", -100.00, account_type="checking"))

        assert ambiguous.is_transfer is True
        assert ambiguous.terminal is False
        assert ambiguous.confidence < 0.9
        assert atm.is_transfer is False  # abstain → flows to spending tiers
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_is_transfer_manual_is_honored(fresh_db, db_settings):
    """A hand-marked row is excluded from auto-flagging entirely (M6)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            detector = TransferDetector(conn)
            decision = await detector.classify(_ctx(
                "t1", "TRANSFER TO SAVINGS", -500.00, account_type="checking",
                is_transfer_manual=True))
        assert decision.is_transfer is False
        assert decision.rationale.get("skipped") == "is_transfer_manual"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_flag_excludes_from_spending_and_unflag_restores(fresh_db, db_settings):
    """Flagging removes the row from the spending total; un-flagging restores it."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            checking = await _account(conn, "Checking", "checking")
            spend_id = await _txn(conn, checking, -80.00, "GROCERY STORE")
            xfer_id = await _txn(conn, checking, -500.00, "TRANSFER TO SAVINGS")

            spend_sql = ("SELECT COALESCE(SUM(ABS(amount)) FILTER "
                         "(WHERE amount < 0 AND is_transfer = false AND is_investment = false), 0) "
                         "FROM finance.transactions")
            before = await conn.fetchval(spend_sql)
            assert float(before) == 580.00

            await conn.execute("UPDATE finance.transactions SET is_transfer = true WHERE id = $1", xfer_id)
            flagged = await conn.fetchval(spend_sql)
            assert float(flagged) == 80.00  # transfer excluded

            await conn.execute("UPDATE finance.transactions SET is_transfer = false WHERE id = $1", xfer_id)
            restored = await conn.fetchval(spend_sql)
            assert float(restored) == 580.00  # un-flag restores total
            _ = spend_id  # silence unused
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_historical_backfill_flags_high_confidence_idempotently(fresh_db, db_settings):
    """Backfill flags counterpart-matched legs; skips manual + ambiguous; re-run is a no-op."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            checking = await _account(conn, "Checking", "checking")
            savings = await _account(conn, "Savings", "savings")
            await _txn(conn, checking, -500.00, "TRANSFER TO SAVINGS")
            await _txn(conn, savings, 500.00, "TRANSFER FROM CHECKING")
            await _txn(conn, checking, -42.00, "GROCERY STORE")  # not a transfer
            # ambiguous single-leg — must NOT be auto-flagged by the backfill
            await _txn(conn, checking, -75.00, "CHASE CREDIT CRD AUTOPAY")
            # manual row pre-set to not-a-transfer — must be left alone
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
                "is_transfer_manual) VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -500.00, "
                "'TRANSFER MANUAL KEEP', true)", checking)

        result = await backfill_transfer_flags()
        assert result["flagged"] == 2  # the two counterpart legs only

        async with pool.acquire() as conn:
            flagged = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE is_transfer = true")
            assert flagged == 2
            manual_kept = await conn.fetchval(
                "SELECT is_transfer FROM finance.transactions WHERE description = 'TRANSFER MANUAL KEEP'")
            assert manual_kept is False

        again = await backfill_transfer_flags()
        assert again["flagged"] == 0  # idempotent
    finally:
        await close_pool()
