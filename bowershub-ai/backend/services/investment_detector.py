"""
Investment Detector — flags transactions that represent flows to/from investment accounts.

These are not real income or expense — they're moving money within your wealth, so we
exclude them from spend/income totals to give an accurate cash-flow picture.

Patterns detected:
- "Investment:" prefix (Fidelity-style fund purchase/sale)
- "Transfer Investment to Cash" (brokerage withdrawal)
- Brokerage account names (Fidelity, Vanguard, Schwab, FID BKG SVC, etc.)
- 401k / IRA / Roth contributions
"""
import logging
import re
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)

# Description patterns (case-insensitive substring match)
INVESTMENT_PATTERNS = [
    r"^Investment:",                    # Fidelity fund purchase/sale
    r"Transfer Investment",             # Brokerage transfer
    r"Fidelity Investment",
    r"Vanguard Investment",
    r"FID BKG SVC LLC",                # Fidelity ACH
    r"Schwab",
    r"Brokerage",
    r"401\(?k\)?",                      # 401k contribution
    r"IRA Contribution",
    r"Roth IRA",
    r"FIDELITY INV TFR",
    r"VANGUARD",
    r"E\*?TRADE",
    r"Robinhood",
    r"Wealthfront",
    r"Betterment",
    r"Coinbase",                        # Crypto exchange
]

INVESTMENT_RE = re.compile("|".join(INVESTMENT_PATTERNS), re.IGNORECASE)


def is_investment_description(description: Optional[str]) -> bool:
    """Check if a transaction description matches investment patterns."""
    if not description:
        return False
    return bool(INVESTMENT_RE.search(description))


async def flag_investments_in_db(window_days: int = 90) -> dict:
    """
    Re-scan recent transactions and update is_investment flag based on patterns.
    Returns count of newly flagged transactions.
    """
    pool = get_pool()
    
    async with pool.acquire() as conn:
        # Get all unflagged transactions in the window
        rows = await conn.fetch("""
            SELECT id, description
            FROM finance.transactions
            WHERE posted_date >= CURRENT_DATE - $1::int
            AND is_investment = false
        """, window_days)
        
        ids_to_flag = []
        for row in rows:
            if is_investment_description(row["description"]):
                ids_to_flag.append(row["id"])
        
        if ids_to_flag:
            await conn.execute("""
                UPDATE finance.transactions
                SET is_investment = true,
                    updated_at = now()
                WHERE id = ANY($1::text[])
            """, ids_to_flag)
        
        return {
            "scanned": len(rows),
            "flagged": len(ids_to_flag),
        }


async def get_investment_summary(window_days: int = 30) -> dict:
    """Get summary of investment activity for the briefing/dashboard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) as count,
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) as inflow,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) as outflow
            FROM finance.transactions
            WHERE is_investment = true
            AND posted_date >= CURRENT_DATE - $1::int
        """, window_days)
    return {
        "count": row["count"] if row else 0,
        "inflow": float(row["inflow"]) if row else 0.0,
        "outflow": float(row["outflow"]) if row else 0.0,
    }
