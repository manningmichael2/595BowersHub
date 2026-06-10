"""
Native override-category skill — replaces the n8n Override Transaction Category workflow.

Flow:
1. Validate category exists (or create if create_if_missing=true)
2. Extract merchant pattern from the transaction description
3. Count similar transactions
4. If similar exist and confirm_retroactive not set → return needs_confirmation
5. On confirmation → update primary + cascade to similar + upsert category_examples
"""
import logging
import re
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)


def _extract_merchant_pattern(description: str) -> Optional[str]:
    """
    Extract a merchant pattern from a transaction description.
    Takes the first alphabetic word >=3 chars, uppercased.
    E.g., "WALMART SUPERCENTER #1234" → "WALMART"
    """
    if not description:
        return None
    words = re.findall(r'[A-Za-z]{3,}', description)
    if words:
        return words[0].upper()
    return None


async def override_category(
    transaction_id: str,
    category_name: str,
    create_if_missing: bool = False,
    confirm_retroactive: bool = False,
) -> dict:
    """
    Override a transaction's category with a learning loop.
    """
    if not transaction_id or not transaction_id.strip():
        return {"error": "Missing transaction_id.", "_display": "⚠️ Provide a transaction ID."}
    if not category_name or not category_name.strip():
        return {"error": "Missing category_name.", "_display": "⚠️ Provide the new category name."}

    transaction_id = transaction_id.strip()
    category_name = category_name.strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        # 1. Look up the category
        cat_row = await conn.fetchrow(
            "SELECT id, name FROM finance.categories WHERE name = $1",
            category_name,
        )

        if not cat_row:
            # Category doesn't exist
            if not create_if_missing:
                # Return all categories so the agent/user can pick
                cats = await conn.fetch("""
                    SELECT c.name, p.name as parent_name
                    FROM finance.categories c
                    LEFT JOIN finance.categories p ON p.id = c.parent_id
                    ORDER BY COALESCE(p.name, c.name), c.name
                """)
                
                by_parent = {}
                for c in cats:
                    parent = c["parent_name"] or "Top-level"
                    by_parent.setdefault(parent, []).append(c["name"])
                
                cat_display = []
                for parent, children in sorted(by_parent.items()):
                    if parent == "Top-level":
                        cat_display.extend(children)
                    else:
                        cat_display.append(f"{parent}: {', '.join(children)}")

                return {
                    "success": False,
                    "error": "category_not_found",
                    "message": f'Category "{category_name}" does not exist. Confirm with the user whether to create it, then call again with create_if_missing=true.',
                    "existing_categories_by_parent": by_parent,
                    "_display": (
                        f'⚠️ Category "{category_name}" doesn\'t exist.\n\n'
                        f"**Available categories:**\n" +
                        "\n".join(f"- {c}" for c in cat_display) +
                        f'\n\nTo create it, re-run with `create_if_missing=true`.'
                    ),
                }
            else:
                # Create the category
                cat_row = await conn.fetchrow(
                    "INSERT INTO finance.categories (name) VALUES ($1) RETURNING id, name",
                    category_name,
                )
                logger.info(f"Created new category: {category_name} (id={cat_row['id']})")

        category_id = cat_row["id"]

        # 2. Look up the transaction
        txn = await conn.fetchrow(
            "SELECT id, description, amount, category_id FROM finance.transactions WHERE id = $1",
            int(transaction_id) if transaction_id.isdigit() else transaction_id,
        )
        if not txn:
            return {"error": f"Transaction {transaction_id} not found.", "_display": f"⚠️ Transaction `{transaction_id}` not found."}

        # 3. Extract merchant pattern
        pattern = _extract_merchant_pattern(txn["description"])

        # 4. Count similar transactions (same pattern, not user-overridden)
        similar_count = 0
        if pattern:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) as cnt FROM finance.transactions
                WHERE UPPER(description) LIKE $1
                  AND id != $2
                  AND user_category_override = false
                """,
                f"%{pattern}%",
                txn["id"],
            )
            similar_count = row["cnt"] if row else 0

        # 5. If similar exist and not confirmed → ask for confirmation
        if similar_count > 0 and not confirm_retroactive:
            return {
                "success": False,
                "needs_confirmation": True,
                "similar_count": similar_count,
                "pattern": pattern,
                "message": f"Found {similar_count} similar transactions matching pattern \"{pattern}\". Retroactively update them all to \"{category_name}\"?",
                "_display": (
                    f"Found **{similar_count}** similar transactions matching \"{pattern}\".\n\n"
                    f"Update them all to **{category_name}**?\n\n"
                    f"Call again with `confirm_retroactive=true` to apply."
                ),
            }

        # 6. Apply the override
        # Update the primary transaction
        await conn.execute(
            "UPDATE finance.transactions SET category_id = $1, user_category_override = true WHERE id = $2",
            category_id, txn["id"],
        )

        # Cascade to similar transactions (if confirmed)
        cascade_count = 0
        if similar_count > 0 and confirm_retroactive and pattern:
            result = await conn.execute(
                """
                UPDATE finance.transactions
                SET category_id = $1
                WHERE UPPER(description) LIKE $2
                  AND id != $3
                  AND user_category_override = false
                """,
                category_id, f"%{pattern}%", txn["id"],
            )
            # Parse "UPDATE N" result
            try:
                cascade_count = int(result.split()[-1])
            except (ValueError, IndexError):
                cascade_count = similar_count

        # 7. Upsert into category_examples (learning loop)
        if pattern:
            await conn.execute(
                """
                INSERT INTO finance.category_examples (pattern, category_id, times_reinforced)
                VALUES ($1, $2, 1)
                ON CONFLICT (pattern) DO UPDATE
                SET category_id = $2, times_reinforced = category_examples.times_reinforced + 1,
                    last_reinforced_at = NOW()
                """,
                pattern, category_id,
            )

    display_parts = [f"✅ Updated transaction #{transaction_id} → **{category_name}**"]
    if cascade_count > 0:
        display_parts.append(f"Also updated {cascade_count} similar \"{pattern}\" transactions.")
    if pattern:
        display_parts.append(f"Pattern \"{pattern}\" saved for future auto-categorization.")

    return {
        "success": True,
        "transaction_id": transaction_id,
        "category": category_name,
        "pattern": pattern,
        "cascade_count": cascade_count,
        "_display": "\n".join(display_parts),
    }
