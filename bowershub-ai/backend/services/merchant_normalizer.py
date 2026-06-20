"""Merchant normalization (R1.1) — derive a stable merchant key from the raw
bank descriptor using DB-driven rules (finance.normalization_rules).

Root cause the cascade fixes: the system used to categorize raw strings like
`COSTCO WHSE #0393 MADISON HEIGHMI`. This module turns those into a stable key
(`COSTCO`) + display name (`Costco`) so every downstream tier and the kNN
embedding operate on the clean form.

Pieces:
- MerchantNormalizer: the pure regex-substitution engine (unit-testable with
  rules passed directly).
- build_normalizer(conn): loads the active rules from the DB (NO-HARDCODING).
- backfill_merchant_keys(): idempotent pass that sets finance.transactions.
  merchant_key and upserts finance.merchants. Used by the SimpleFin ingest hook
  (only_missing=True) and runnable standalone over all history (R1.5).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..database import get_pool

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedMerchant:
    key: str       # stable canonical key (UPPER), used for joins/grouping
    display: str   # human-readable (Title Case), used in the UI / directory


class MerchantNormalizer:
    """Applies ordered regex substitutions to a raw descriptor, then collapses
    whitespace. Rules are `(pattern, replacement)` pairs in application order —
    supplied directly (tests) or via build_normalizer() (DB-driven)."""

    def __init__(self, rules: Iterable[tuple[str, str]]):
        self._rules = [(re.compile(p, re.IGNORECASE), r or "") for (p, r) in rules]

    def normalize(self, raw: Optional[str]) -> NormalizedMerchant:
        s = (raw or "").strip()
        for rx, repl in self._rules:
            s = rx.sub(repl, s)
        s = _WS.sub(" ", s).strip()
        if not s:
            # Over-stripped or unmatched-to-empty → fall back to the cleaned raw
            # so a real transaction never gets an empty key (R1.1 fallthrough).
            s = _WS.sub(" ", (raw or "").strip())
        return NormalizedMerchant(key=s.upper(), display=s.title())


async def build_normalizer(conn) -> MerchantNormalizer:
    """Load the active normalization rules from the DB, in priority order."""
    rows = await conn.fetch(
        "SELECT pattern, replacement FROM finance.normalization_rules "
        "WHERE is_active ORDER BY priority, id"
    )
    return MerchantNormalizer([(r["pattern"], r["replacement"]) for r in rows])


async def normalize_and_store(conn, normalizer: MerchantNormalizer, txn_id: str,
                              description: Optional[str]) -> Optional[str]:
    """Normalize one transaction's descriptor, upsert finance.merchants, and set
    finance.transactions.merchant_key. Returns the key (None if the raw is empty).

    The single-transaction primitive — reused by the backfill and by the
    pipeline's inline-on-read path (Task 10)."""
    nm = normalizer.normalize(description)
    if not nm.key:
        return None
    await conn.execute(
        """
        INSERT INTO finance.merchants (merchant_key, display_name)
        VALUES ($1, $2)
        ON CONFLICT (merchant_key) DO UPDATE
            SET display_name = COALESCE(finance.merchants.display_name, EXCLUDED.display_name),
                updated_at = now()
        """,
        nm.key, nm.display,
    )
    await conn.execute(
        "UPDATE finance.transactions SET merchant_key = $1 WHERE id = $2",
        nm.key, txn_id,
    )
    return nm.key


async def backfill_merchant_keys(*, only_missing: bool = True,
                                 limit: Optional[int] = None) -> dict:
    """Derive merchant keys over the transaction history. Idempotent.

    only_missing=True (the ingest hook) touches only rows whose merchant_key is
    NULL; only_missing=False re-derives all (e.g. after a normalization-rule
    change). Runs in its own pool connection — NOT inside the categorizer's
    critical section (R1.5)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        normalizer = await build_normalizer(conn)
        where = "WHERE merchant_key IS NULL" if only_missing else ""
        query = f"SELECT id, description FROM finance.transactions {where} ORDER BY posted_date DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = await conn.fetch(query)
        updated = 0
        for r in rows:
            key = await normalize_and_store(conn, normalizer, r["id"], r["description"])
            if key:
                updated += 1
    logger.info("Merchant normalization backfill: updated %d/%d", updated, len(rows))
    return {"updated": updated, "scanned": len(rows)}
