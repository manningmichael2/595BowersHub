"""Account reconciliation (R2.1-2.4) — lightweight, for bank-synced balances.

There is no app-computed running balance (balances are synced); reconciliation
compares a user-entered statement balance to the synced `last_balance` (drift,
R2.1), tracks a per-transaction `cleared` flag + tally (R2.2), and records each
reconcile event in finance.reconciliations (R2.3) while advancing
`reconciled_through_date` (R2.4).
"""

from __future__ import annotations

from .config import load_config


async def account_status(conn, account_id: str) -> dict:
    """Drift vs synced balance + cleared tally for one account (R2.1/R2.2)."""
    cfg = await load_config(conn)
    acct = await conn.fetchrow(
        "SELECT last_balance, last_balance_date, reconciled_through_date "
        "FROM finance.accounts WHERE id = $1", account_id)
    if acct is None:
        raise LookupError(account_id)
    synced = float(acct["last_balance"]) if acct["last_balance"] is not None else None
    # Cleared tally since the last reconcile (R2.2) — a partial cross-check, not a
    # full running balance.
    cleared = await conn.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM finance.transactions "
        "WHERE account_id = $1 AND cleared = true "
        "  AND ($2::date IS NULL OR posted_date > $2::date)",
        account_id, acct["reconciled_through_date"])
    return {
        "account_id": account_id,
        "synced_balance": synced,
        "as_of": acct["last_balance_date"].isoformat() if acct["last_balance_date"] else None,
        "reconciled_through_date": acct["reconciled_through_date"].isoformat() if acct["reconciled_through_date"] else None,
        "cleared_tally": float(cleared),
        "reconcile_tolerance": cfg.reconcile_tolerance,
    }


async def reconcile(conn, account_id: str, statement_date, statement_balance: float) -> dict:
    """Record a reconcile event (R2.3) and advance reconciled_through_date (R2.4).
    Returns the drift vs the synced balance."""
    cfg = await load_config(conn)
    synced = await conn.fetchval(
        "SELECT last_balance FROM finance.accounts WHERE id = $1", account_id)
    if synced is None and not await conn.fetchval(
            "SELECT 1 FROM finance.accounts WHERE id = $1", account_id):
        raise LookupError(account_id)
    synced_f = float(synced) if synced is not None else None
    delta = round(statement_balance - synced_f, 2) if synced_f is not None else None
    async with conn.transaction():
        rec_id = await conn.fetchval(
            "INSERT INTO finance.reconciliations "
            "(account_id, statement_date, statement_balance, synced_balance, delta) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            account_id, statement_date, statement_balance, synced_f, delta)
        await conn.execute(
            "UPDATE finance.accounts SET reconciled_through_date = $2 WHERE id = $1",
            account_id, statement_date)
    return {
        "reconciliation_id": rec_id,
        "account_id": account_id,
        "statement_balance": statement_balance,
        "synced_balance": synced_f,
        "delta": delta,
        "in_sync": delta is not None and abs(delta) <= cfg.reconcile_tolerance,
    }
