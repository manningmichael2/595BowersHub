"""
SimpleFin Sync — pulls account balances and transactions from SimpleFin Bridge
and upserts them into Postgres. Native Python replacement for the n8n workflow.

Triggered:
- On-demand via `/transactions --sync`
- Could be scheduled via apscheduler (replacing the n8n nightly sync)
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from backend.http_client import get_http_client

from backend.database import get_pool

logger = logging.getLogger(__name__)

SIMPLEFIN_URL = "https://beta-bridge.simplefin.org/simplefin/accounts"

# SimpleFin auth — read from env (set SIMPLEFIN_AUTH in .env)
SIMPLEFIN_AUTH = os.environ.get("SIMPLEFIN_AUTH", "")

# Accounts to ignore (SimpleFin phantom/duplicate accounts)
IGNORED_ACCOUNT_IDS = {
    "ACT-ad8f670e-99f0-4259-b5e1-73721805d770",
    "ACT-c04ed2cb-9b38-4d38-a685-d98fc22434d0",
}


async def sync_simplefin(window_days: int = 14) -> dict:
    """
    Pull last N days of transactions and account balances from SimpleFin,
    upsert into Postgres. Idempotent (ON CONFLICT DO NOTHING on txn id).
    
    Returns a summary dict with counts and any connection errors.
    """
    if not SIMPLEFIN_AUTH:
        return {
            "ok": False,
            "error": "SIMPLEFIN_AUTH not configured",
            "_display": "⚠️ SimpleFin sync not configured (missing SIMPLEFIN_AUTH).",
        }

    start = datetime.now() - timedelta(days=window_days)
    start_ts = int(start.replace(hour=0, minute=0, second=0).timestamp())
    url = f"{SIMPLEFIN_URL}?start-date={start_ts}"

    try:
        client = get_http_client()
        resp = await client.get(url, headers={"Authorization": SIMPLEFIN_AUTH}, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"SimpleFin HTTP error: {e.response.status_code}")
        return {
            "ok": False,
            "error": f"SimpleFin returned {e.response.status_code}",
            "_display": f"⚠️ SimpleFin sync failed: HTTP {e.response.status_code}. The access token may need refreshing.",
        }
    except Exception as e:
        logger.error(f"SimpleFin sync failed: {e}")
        return {
            "ok": False,
            "error": str(e),
            "_display": f"⚠️ SimpleFin sync failed: {e}",
        }

    accounts = data.get("accounts", [])
    conn_errors = data.get("errors", [])

    # Collect transactions and account updates
    transactions = []
    account_updates = []
    for account in accounts:
        if account["id"] in IGNORED_ACCOUNT_IDS:
            continue

        # Account balance update
        bal_date = None
        if account.get("balance-date"):
            bal_date = datetime.fromtimestamp(account["balance-date"]).date()
        account_updates.append({
            "id": account["id"],
            "org_name": (account.get("org", {}).get("name") or "")[:200],
            "account_name": (account.get("name") or "")[:200],
            "currency": account.get("currency", "USD"),
            "last_balance": float(account.get("balance") or 0),
            "last_balance_date": bal_date,
        })

        # Transactions
        for txn in account.get("transactions", []):
            posted_date = None
            if txn.get("posted"):
                posted_date = datetime.fromtimestamp(txn["posted"]).date()
            transactions.append({
                "id": txn["id"],
                "account_id": account["id"],
                "posted_date": posted_date,
                "amount": float(txn.get("amount") or 0),
                "description": (txn.get("description") or "")[:500],
                "memo": (txn.get("memo") or "")[:500],
                "pending": bool(txn.get("pending", False)),
            })

    # Upsert into Postgres
    pool = get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        # Update account balances
        for acc in account_updates:
            await conn.execute("""
                INSERT INTO finance.accounts (id, org_name, account_name, currency, last_balance, last_balance_date)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    last_balance = EXCLUDED.last_balance,
                    last_balance_date = EXCLUDED.last_balance_date,
                    org_name = EXCLUDED.org_name,
                    account_name = EXCLUDED.account_name
            """, acc["id"], acc["org_name"], acc["account_name"], acc["currency"],
                acc["last_balance"], acc["last_balance_date"])

        # Persist a balance-history snapshot per account (R3.5) — net-worth-over-time.
        try:
            from backend.services.accounting.snapshots import snapshot_all_accounts
            await snapshot_all_accounts(conn)
        except Exception as e:
            logger.warning(f"Balance snapshot after sync failed: {e}")

        # Insert transactions
        for t in transactions:
            result = await conn.fetchval("""
                INSERT INTO finance.transactions
                    (id, account_id, posted_date, amount, description, memo, pending, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'simplefin')
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """, t["id"], t["account_id"], t["posted_date"], t["amount"],
                t["description"], t["memo"], t["pending"])
            if result:
                inserted += 1

    # Normalize merchant keys for newly-ingested transactions (R1.1/R1.5 ingest
    # hook). Non-fatal: a normalization failure must not fail the sync.
    try:
        from backend.services.merchant_normalizer import backfill_merchant_keys
        await backfill_merchant_keys(only_missing=True)
    except Exception as e:
        logger.warning(f"Merchant normalization after sync failed: {e}")

    # Flag investments and transfers on the new data
    try:
        from backend.services.investment_detector import flag_investments_in_db
        inv_result = await flag_investments_in_db(window_days=window_days)
    except Exception as e:
        logger.warning(f"Investment flagging after sync failed: {e}")
        inv_result = {"flagged": 0}

    # Build display
    lines = [f"**🔄 SimpleFin Sync Complete**\n"]
    lines.append(f"- ✅ **{inserted}** new transactions imported")
    lines.append(f"- 📊 {len(account_updates)} account balances updated")
    if inv_result.get("flagged"):
        lines.append(f"- 📈 {inv_result['flagged']} flagged as investments")

    if conn_errors:
        lines.append(f"\n⚠️ **{len(conn_errors)} bank connection(s) need re-auth:**")
        for e in conn_errors:
            # Extract bank name from error message
            short = e.split(" may need")[0].replace("Connection to ", "")
            lines.append(f"  - {short}")
        lines.append("\n_Re-link these at https://beta-bridge.simplefin.org_")

    # Surface the sync on the dashboard Task Reel (fire-and-forget). Re-auth
    # needs land as a warning so the Action Center can pick them up later.
    from backend.services.agent_logger import log_event
    if conn_errors:
        await log_event("simplefin", f"{len(conn_errors)} bank connection(s) need re-auth", level="warning")
    await log_event(
        "simplefin",
        f"Synced {inserted} new transaction(s) across {len(account_updates)} account(s)",
        level="success" if inserted else "info",
    )

    return {
        "ok": True,
        "inserted": inserted,
        "accounts_updated": len(account_updates),
        "errors": conn_errors,
        "_display": "\n".join(lines),
    }
