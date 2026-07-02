"""
Transaction Categorizer — in-process replacement for the n8n Categorizer workflow.

Runs as a scheduled job (apscheduler) after SimpleFin nightly sync, or on-demand.
Uses the configured local Ollama model (resolved from the DB catalog) for zero-cost
classification.

Logic mirrors the n8n workflow:
1. Fetch uncategorized transactions from Postgres (up to 500)
2. Fetch leaf categories + few-shot examples from category_examples
3. Build a classification prompt per batch (50 txns per batch)
4. Send to the local Ollama model
5. Parse JSON response, update transaction rows

Fallback: if Ollama is unreachable or returns garbage, logs the error and
skips — the next run will pick up the same uncategorized transactions.
"""
import json
from backend.services.model_catalog import resolve_role
import logging
from typing import Optional

import httpx
from backend.http_client import get_http_client

from ..database import get_pool
from backend.services.task_registry import tracked

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = "http://ollama:11434"
BATCH_SIZE = 50
MAX_TRANSACTIONS = 500


@tracked("Categorizer")
async def run_categorizer() -> dict:
    """
    Main entry point, dispatched by the `categorizer_engine` feature-gate
    (finance.categorizer_config):
      - 'legacy'        → the R5.1-fixed single-LLM pass below.
      - 'shadow'        → the new cascade, provenance-only (no writes).
      - 'cascade'       → the new cascade, live writes through the Writer.
    Defaults to 'legacy' so the new path is dark until explicitly enabled.
    """
    pool = get_pool()
    from backend.services.categorization.config import load_config
    async with pool.acquire() as conn:
        cfg = await load_config(conn)
    if cfg.engine in ("shadow", "cascade"):
        from backend.services.categorization.orchestrator import run_cascade
        result = await run_cascade(pool, config=cfg)
    else:
        result = await _run_legacy()
    # Readiness watermark (R2.1): the categorizer is the only in-process nightly
    # finance job (SimpleFin sync runs externally via n8n), so its successful
    # completion is the "data is categorized for this window" signal the insight
    # runner gates on. Only reached when the run did NOT raise (failure → no row).
    await _write_categorizer_watermark(pool)
    # Surface the run on the dashboard Task Reel (fire-and-forget).
    from backend.services.agent_logger import log_event
    _n = result.get("count") or result.get("categorized") or result.get("written") or 0
    await log_event(
        "categorizer",
        f"Categorized {_n} transaction(s)" if _n else "Categorizer run complete",
        level="success",
    )
    return result


_CATEGORIZER_JOB = "categorizer"


async def _write_categorizer_watermark(pool) -> None:
    """Record a finance.job_runs 'completed' row for today's window. Best-effort:
    a watermark write must never fail the categorizer (a missing watermark just
    makes the insight runner conservatively skip-not-ready)."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO finance.job_runs (job_name, status, ran_for, completed_at) "
                "VALUES ($1, 'completed', CURRENT_DATE, now())",
                _CATEGORIZER_JOB,
            )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Categorizer watermark write failed: {e}")


async def _run_legacy() -> dict:
    """
    The original single-pass categorizer (R5.1-fixed: schema-qualified to
    finance.*). Retained as the `legacy` engine path.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Fetch categories (to build the leaf list)
        # NOTE: all finance relations are schema-qualified to finance.* (R5.1).
        # The runtime bowershub_app role has no SET search_path, so unqualified
        # `transactions` resolves to public.transactions — a non-updatable JOIN
        # view (migration 0016) — which made the nightly UPDATE below silently
        # error and persist nothing.
        categories = await conn.fetch(
            "SELECT id, name, parent_id FROM finance.categories ORDER BY COALESCE(parent_id, id), name"
        )

        # 2. Fetch few-shot examples
        examples = await conn.fetch(
            "SELECT e.description_pattern, c.name AS category_name "
            "FROM finance.category_examples e JOIN finance.categories c ON e.category_id = c.id "
            "ORDER BY e.times_reinforced DESC, e.updated_at DESC LIMIT 30"
        )

        # 3. Fetch uncategorized transactions
        transactions = await conn.fetch(
            "SELECT id, description, memo, amount FROM finance.transactions "
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
                    "UPDATE finance.transactions SET category_id = $1 "
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
        client = get_http_client()
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
        # R5.5: parse failure → abstain (rows stay uncategorized → review queue),
        # NEVER assign "Other". The previous Other-fallback masked failures.
        return []

    results = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id", ""))
        cat_name = item.get("category", "")
        cat_id = cat_id_by_name.get(cat_name)
        if cat_id is None:
            # Unknown category → abstain (queue), never "Other" (R5.5).
            continue
        results.append({
            "id": tid,
            "category_id": cat_id,
            "assigned_category": cat_name,
            "fallback": False,
        })

    return results
