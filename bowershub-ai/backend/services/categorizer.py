"""
Transaction Categorizer — in-process replacement for the n8n Categorizer workflow.

Runs as a scheduled job (apscheduler) after SimpleFin nightly sync, or on-demand.
Uses the local Ollama model (llama3.2:3b) instead of Anthropic Haiku for zero-cost
classification.

Logic mirrors the n8n workflow:
1. Fetch uncategorized transactions from Postgres (up to 500)
2. Fetch leaf categories + few-shot examples from category_examples
3. Build a classification prompt per batch (50 txns per batch)
4. Send to Ollama llama3.2:3b
5. Parse JSON response, update transaction rows

Fallback: if Ollama is unreachable or returns garbage, logs the error and
skips — the next run will pick up the same uncategorized transactions.
"""
import json
from backend.services.model_catalog import resolve_role
import logging
from typing import Optional

import httpx

from ..database import get_pool

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = "http://ollama:11434"
BATCH_SIZE = 50
MAX_TRANSACTIONS = 500


async def run_categorizer() -> dict:
    """
    Main entry point. Fetches uncategorized transactions and classifies them.
    Returns a summary dict with counts.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Fetch categories (to build the leaf list)
        categories = await conn.fetch(
            "SELECT id, name, parent_id FROM categories ORDER BY COALESCE(parent_id, id), name"
        )

        # 2. Fetch few-shot examples
        examples = await conn.fetch(
            "SELECT e.description_pattern, c.name AS category_name "
            "FROM category_examples e JOIN categories c ON e.category_id = c.id "
            "ORDER BY e.times_reinforced DESC, e.updated_at DESC LIMIT 30"
        )

        # 3. Fetch uncategorized transactions
        transactions = await conn.fetch(
            "SELECT id, description, memo, amount FROM transactions "
            "WHERE category_id IS NULL AND user_category_override = false "
            "ORDER BY posted_date DESC LIMIT $1",
            MAX_TRANSACTIONS,
        )

    if not transactions:
        logger.info("Categorizer: no uncategorized transactions")
        return {"status": "skipped", "reason": "no uncategorized transactions", "count": 0}

    # Build leaf category list
    child_ids = {c["parent_id"] for c in categories if c["parent_id"] is not None}
    leaves = [c for c in categories if c["id"] not in child_ids]

    # Category tree for prompt (parent/leaf format)
    cat_by_id = {c["id"]: c for c in categories}
    tree = []
    for leaf in leaves:
        parent = cat_by_id.get(leaf["parent_id"]) if leaf["parent_id"] else None
        tree.append(f"{parent['name']}/{leaf['name']}" if parent else leaf["name"])
    tree.sort()

    # Category name → id lookup
    cat_id_by_name = {leaf["name"]: leaf["id"] for leaf in leaves}
    other_id = cat_id_by_name.get("Other")

    # Few-shot examples block
    example_lines = [
        f'"{ex["description_pattern"]}" -> {ex["category_name"]}'
        for ex in examples
        if ex["description_pattern"] and ex["category_name"]
    ]
    examples_block = ""
    if example_lines:
        examples_block = (
            "\n\nHere are past categorization decisions made by the user. "
            "Use these as strong guidance:\n" + "\n".join(example_lines)
        )

    # Process in batches
    total_updated = 0
    total_fallback = 0
    errors = []

    for i in range(0, len(transactions), BATCH_SIZE):
        batch = transactions[i : i + BATCH_SIZE]
        txn_data = [
            {"id": str(t["id"]), "description": t["description"] or "", "amount": float(t["amount"])}
            for t in batch
        ]

        prompt = (
            "Categorize each bank transaction below. Choose the MOST specific leaf category "
            "from this list (only use the leaf name, not the parent):\n\n"
            + "\n".join(tree)
            + "\n\nRules:\n"
            "- Transfers between your own accounts -> Transfer\n"
            "- Paychecks, interest, dividends -> Income\n"
            "- Woodworking tools/supplies (Rockler, Festool, Harbor Freight, blades, wood) -> Woodshop\n"
            "- Airlines, hotels, travel insurance -> Travel\n"
            "- Grocery stores, food markets (Kroger, Meijer, Costco food) -> Food_Groceries\n"
            "- Restaurants, food delivery, Uber Eats -> Food_Dining\n"
            "- Gas stations, vehicle fuel -> Trans_Gas\n"
            "- Streaming, software, memberships -> Subscriptions\n"
            "- When unsure -> Other\n"
            + examples_block
            + "\n\nReturn ONLY a JSON array, no markdown, no explanation: "
            '[{"id":"<id>","category":"<leaf_name>"}, ...]\n\n'
            "Transactions:\n" + json.dumps(txn_data)
        )

        # Call Ollama
        result = await _call_ollama(prompt)
        if result is None:
            errors.append(f"Batch {i//BATCH_SIZE}: Ollama call failed")
            continue

        # Parse response
        parsed = _parse_response(result, [str(t["id"]) for t in batch], cat_id_by_name, other_id)

        # Update DB
        async with pool.acquire() as conn:
            for item in parsed:
                if item["category_id"] is None:
                    continue
                await conn.execute(
                    "UPDATE transactions SET category_id = $1 "
                    "WHERE id = $2 AND user_category_override = false AND category_id IS NULL",
                    item["category_id"],
                    item["id"],
                )
                total_updated += 1
                if item.get("fallback"):
                    total_fallback += 1

    summary = {
        "status": "completed",
        "transactions_found": len(transactions),
        "updated": total_updated,
        "fallback_to_other": total_fallback,
        "errors": errors,
        "model": resolve_role("local"),
    }
    logger.info(f"Categorizer: {summary}")
    return summary


async def _call_ollama(prompt: str) -> Optional[str]:
    """Call the local Ollama model. Returns the response text or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": resolve_role("local"),
                    "messages": [
                        {
                            "role": "system",
                            "content": "You classify bank transactions. Return ONLY the JSON array requested, nothing else.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 2048},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"Categorizer: Ollama call failed: {e}")
        return None


def _parse_response(
    content: str,
    batch_ids: list[str],
    cat_id_by_name: dict[str, int],
    other_id: Optional[int],
) -> list[dict]:
    """Parse the model's JSON response into update instructions."""
    # Clean markdown fencing if present
    clean = content.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Extract JSON array
    try:
        import re
        match = re.search(r"\[[\s\S]*\]", clean)
        if not match:
            raise ValueError("No JSON array found")
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Categorizer: failed to parse response: {e}")
        # Fallback: assign all to Other
        return [{"id": tid, "category_id": other_id, "fallback": True} for tid in batch_ids]

    results = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id", ""))
        cat_name = item.get("category", "")
        cat_id = cat_id_by_name.get(cat_name, other_id)
        results.append({
            "id": tid,
            "category_id": cat_id,
            "assigned_category": cat_name,
            "fallback": cat_name not in cat_id_by_name,
        })

    return results
