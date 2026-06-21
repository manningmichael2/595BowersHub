"""Net worth (R3.1-3.7) — the single, consolidated implementation that replaces
the sign-based guess in services/finance.py and routers/dashboard.py.

Classification is by `account_type` (R3.1): liabilities = LIABILITY_TYPES, assets
otherwise. An account with NULL account_type is **excluded** and flagged
`needs_type` — never silently counted (R3.1). `include_in_net_worth=false` accounts
are excluded (R3.3 — replaces the hardcoded org list). Net worth = SUM of signed
`last_balance` over included, typed accounts: verified against prod, liabilities
store `last_balance` negative, so the signed sum is already assets − liabilities
(R3.2). Stale balances (older than the configured window) are flagged (R3.7).
"""

from __future__ import annotations

from ..categorization.transfer import LIABILITY_TYPES
from .config import load_config


async def compute_net_worth(conn) -> dict:
    """Structured net worth: total + per-account breakdown with classification,
    inclusion, staleness. Both the `balances` skill and the dashboard call this."""
    cfg = await load_config(conn)
    rows = await conn.fetch(
        """
        SELECT id, org_name, account_name, currency, account_type,
               last_balance, last_balance_date,
               (last_balance_date IS NOT NULL
                AND last_balance_date < CURRENT_DATE - $1::int) AS stale
        FROM finance.accounts
        WHERE last_balance IS NOT NULL AND include_in_net_worth = true
        ORDER BY org_name, account_name
        """,
        cfg.stale_balance_days,
    )

    accounts = []
    assets = 0.0
    liabilities = 0.0
    for r in rows:
        bal = float(r["last_balance"])
        atype = r["account_type"]
        needs_type = atype is None
        is_liab = atype in LIABILITY_TYPES
        included = not needs_type  # typed + include_in_net_worth (filtered above)
        if included:
            if is_liab:
                liabilities += bal   # liabilities stored negative
            else:
                assets += bal
        accounts.append({
            "id": r["id"],
            "name": r["account_name"] or r["id"],
            "org": r["org_name"],
            "currency": r["currency"] or "USD",
            "account_type": atype,
            "balance": bal,
            "as_of": r["last_balance_date"].isoformat() if r["last_balance_date"] else None,
            "classification": "needs_type" if needs_type else ("liability" if is_liab else "asset"),
            "included": included,
            "stale": bool(r["stale"]),
        })

    return {
        "net_worth": assets + liabilities,
        "assets": assets,
        "liabilities": liabilities,
        "accounts": accounts,
    }


async def net_worth_history(conn, *, days: int = 365) -> list[dict]:
    """Net-worth time series from balance_snapshots (R3.6). Signed sum over
    included, typed accounts grouped by snapshot date."""
    rows = await conn.fetch(
        """
        SELECT s.snapshot_date, SUM(s.balance) AS net_worth
        FROM finance.balance_snapshots s
        JOIN finance.accounts a ON a.id = s.account_id
        WHERE a.include_in_net_worth = true
          AND a.account_type IS NOT NULL
          AND s.snapshot_date >= CURRENT_DATE - $1::int
        GROUP BY s.snapshot_date
        ORDER BY s.snapshot_date
        """,
        days,
    )
    return [{"date": r["snapshot_date"].isoformat(), "net_worth": float(r["net_worth"])} for r in rows]
