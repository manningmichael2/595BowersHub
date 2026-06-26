"""Transaction splits (finance-budgets-splits R1.x) — child-subtransaction model.

A split parent keeps its `amount` but becomes a container (`category_id=NULL`,
`is_split=true`, `user_category_override=true` so the cascade skips it). Children
are real finance.transactions rows that sum exactly to the parent, inherit its
`posted_date`/`account_id`, and carry their own `category_id`. Integrity is
enforced in the write transaction (proportionate at this scale; mirrors Actual).
"""

from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def _same_sign(a: Decimal, b: Decimal) -> bool:
    return (a >= 0) == (b >= 0)


async def create_split(conn, txn_id: str, allocations: list[dict], actor_id: int | None = None) -> dict:
    """Create or replace a split. `allocations` = [{category_id, amount}, …] (≥2)
    summing to the parent amount, same sign. Idempotent re-split (edit) replaces
    existing children. Raises LookupError/ValueError on bad input.

    `actor_id` (the editing user) is stamped on the parent's updated_by and each
    child's created_by/updated_by (R4.1); a system caller passing None leaves
    attribution NULL."""
    if len(allocations) < 2:
        raise ValueError("a split needs at least 2 allocations")

    parent = await conn.fetchrow(
        "SELECT id, account_id, posted_date, amount, description, is_transfer, transfer_id, parent_id "
        "FROM finance.transactions WHERE id = $1", txn_id)
    if parent is None:
        raise LookupError(txn_id)
    if parent["is_transfer"] or parent["transfer_id"]:
        raise ValueError("cannot split a transfer")
    if parent["parent_id"]:
        raise ValueError("cannot split a split child")

    amount = Decimal(str(parent["amount"]))
    alloc = [(a.get("category_id"), Decimal(str(a["amount"]))) for a in allocations]
    if sum(a for _, a in alloc) != amount:
        raise ValueError(f"allocations must sum to {amount}")
    if any(not _same_sign(a, amount) for _, a in alloc):
        raise ValueError("all allocations must share the parent's sign")

    async with conn.transaction():
        await conn.execute("DELETE FROM finance.transactions WHERE parent_id = $1", txn_id)
        await conn.execute(
            "UPDATE finance.transactions "
            "SET category_id = NULL, is_split = true, user_category_override = true, updated_at = now(), "
            "    updated_by = $2 "
            "WHERE id = $1", txn_id, actor_id)
        for cat_id, amt in alloc:
            await conn.execute(
                "INSERT INTO finance.transactions "
                "(id, account_id, posted_date, amount, description, category_id, parent_id, "
                " user_category_override, source, created_by, updated_by) "
                "VALUES (gen_random_uuid()::text, $1, $2, $3, $4, $5, $6, $7, 'split', $8, $8)",
                parent["account_id"], parent["posted_date"], amt, parent["description"],
                cat_id, txn_id, cat_id is not None, actor_id)
    return {"transaction_id": txn_id, "children": len(alloc)}


async def unsplit(conn, txn_id: str, actor_id: int | None = None) -> dict:
    """Remove a split: delete children, restore the parent as a normal
    categorizable row (clears is_split + override; category stays NULL).
    `actor_id` stamps the parent's updated_by (R4.1)."""
    async with conn.transaction():
        deleted = await conn.execute("DELETE FROM finance.transactions WHERE parent_id = $1", txn_id)
        await conn.execute(
            "UPDATE finance.transactions "
            "SET is_split = false, user_category_override = false, updated_at = now(), updated_by = $2 "
            "WHERE id = $1", txn_id, actor_id)
    n = int(deleted.split()[-1]) if deleted.split()[-1].isdigit() else 0
    return {"transaction_id": txn_id, "children_removed": n}


async def get_allocations(conn, txn_id: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, category_id, amount, description FROM finance.transactions "
        "WHERE parent_id = $1 ORDER BY id", txn_id)
    return [{"id": r["id"], "category_id": r["category_id"],
             "amount": float(r["amount"]), "description": r["description"]} for r in rows]
