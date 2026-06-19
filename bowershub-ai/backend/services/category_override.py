"""
Native categorization tools — replaces the jumbled override-category skill.
Implements the 'Propose & Commit' pattern for bulk updates and specific ID fixes.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from backend.database import get_pool
from backend.services.normalization import lookup_category_alias

logger = logging.getLogger(__name__)


async def categorize_merchant(description_pattern: str, category_name: str) -> dict:
    """
    PROPOSE: Set a merchant rule and preview the impact.
    Does NOT update transactions yet.
    """
    if not description_pattern or not category_name:
        return {"error": "Missing merchant pattern or category name."}

    pool = get_pool()
    async with pool.acquire() as conn:
        # 1. Normalize category
        canonical_category = await lookup_category_alias(conn, category_name)
        
        cat_row = await conn.fetchrow(
            "SELECT id, name FROM finance.categories WHERE name ILIKE $1",
            canonical_category.strip(),
        )
        if not cat_row:
            return {"error": f"Category '{category_name}' not found."}

        # 2. Find matching transactions (fuzzy + ilike)
        rows = await conn.fetch(
            """
            SELECT id, description, amount, posted_date
            FROM finance.transactions
            WHERE (UPPER(description) LIKE $1 OR similarity(description, $2) > 0.20)
              AND user_category_override = false
              AND (category_id IS NULL OR category_id != $3)
            ORDER BY posted_date DESC
            """,
            f"%{description_pattern.upper()}%",
            description_pattern,
            cat_row["id"]
        )

        # 3. Always save the rule (Learning Loop)
        await conn.execute(
            """
            INSERT INTO finance.category_examples (description_pattern, category_id, times_reinforced)
            VALUES ($1, $2, 1)
            ON CONFLICT (lower(description_pattern), category_id) DO UPDATE
            SET times_reinforced = finance.category_examples.times_reinforced + 1,
                updated_at = NOW()
            """,
            description_pattern.upper(), cat_row["id"],
        )

    if not rows:
        return {
            "success": True,
            "rule_saved": True,
            "_display": f"✅ Rule saved: **{description_pattern}** will now be auto-categorized as **{cat_row['name']}**.\n\n(No existing transactions found to update.)"
        }

    # Format preview
    total_amount = sum(float(r["amount"]) for r in rows)
    preview_lines = [f"✅ Rule saved: **{description_pattern}** is now **{cat_row['name']}**.\n"]
    preview_lines.append(f"I found **{len(rows)}** existing transactions that match this pattern (Total: ${abs(total_amount):,.2f}).")
    preview_lines.append("\n**Should I update them all now?** (Say 'yes' or 'proceed')")
    
    return {
        "success": True,
        "needs_commit": True,
        "pattern": description_pattern,
        "category": cat_row["name"],
        "match_count": len(rows),
        "_display": "\n".join(preview_lines)
    }


async def commit_bulk_update(description_pattern: str, category_name: str) -> dict:
    """
    COMMIT: Execute the bulk update previously proposed.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Resolve natural-language aliases (e.g. "groceries" -> "Food_Groceries"),
        # matching categorize_merchant/categorize_transaction. Without this, the
        # commit step of the propose→commit flow fails whenever the user (or the
        # LLM echoing context) names a category by alias rather than exact name.
        canonical_category = await lookup_category_alias(conn, category_name)
        cat_row = await conn.fetchrow(
            "SELECT id, name FROM finance.categories WHERE name ILIKE $1",
            canonical_category.strip(),
        )
        if not cat_row:
            return {"error": f"Category '{category_name}' not found."}

        result = await conn.execute(
            """
            UPDATE finance.transactions
            SET category_id = $1, user_category_override = true
            WHERE (UPPER(description) LIKE $2 OR similarity(description, $3) > 0.20)
              AND user_category_override = false
            """,
            cat_row["id"], 
            f"%{description_pattern.upper()}%",
            description_pattern,
        )
        
        try:
            count = int(result.split()[-1])
        except (ValueError, IndexError):
            count = 0

    return {
        "success": True,
        "updated_count": count,
        "_display": f"🚀 Successfully updated **{count}** transactions to **{cat_row['name']}**."
    }


async def categorize_transaction(transaction_id: str, category_name: str) -> dict:
    """
    SPECIFIC: Update a single transaction by ID.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Normalize category
        canonical_category = await lookup_category_alias(conn, category_name)
        cat_row = await conn.fetchrow(
            "SELECT id, name FROM finance.categories WHERE name ILIKE $1",
            canonical_category.strip(),
        )
        if not cat_row:
            return {"error": f"Category '{category_name}' not found."}

        # Update the row
        result = await conn.execute(
            "UPDATE finance.transactions SET category_id = $1, user_category_override = true WHERE id = $2",
            cat_row["id"], transaction_id
        )
        
        if result == "UPDATE 0":
            return {"error": f"Transaction '{transaction_id}' not found."}

    return {
        "success": True,
        "transaction_id": transaction_id,
        "category": cat_row["name"],
        "_display": f"✅ Transaction **{transaction_id}** updated to **{cat_row['name']}**."
    }
