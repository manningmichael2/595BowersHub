"""Nightly cascade orchestrator (R2.5, R2.6, R5.2, R5.3, R5.6).

Evolves the old single-pass categorizer into an idempotent, resumable run over
the cascade. Honors the `categorizer_engine` feature-gate: `shadow` runs the full
pipeline and writes only provenance (suppressing category *and* is_transfer
mutations, M4); `cascade` applies confident decisions through the Writer.

Work-set (R5.2): `category_id IS NULL AND user_category_override = false AND
is_transfer = false AND is_investment = false` — settled transfers and investment
rows stay out (B-2). Per-row commit ⇒ a partial failure leaves committed rows and
the next run resumes.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..embeddings import EmbeddingsClient
from ..merchant_normalizer import build_normalizer, normalize_and_store
from .base import TxnContext
from .config import CategorizerConfig, load_config
from .knn import EmbeddingKNN
from .llm import build_llm_tier
from .memory import MerchantMemory
from .pipeline import CategorizationPipeline, Writer
from .rules import build_rule_engine
from .transfer import TransferDetector

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434"

_WORKSET_SQL = (
    "SELECT t.id, t.account_id, t.posted_date, t.amount, t.description, t.memo, "
    "       t.merchant_key, t.is_transfer_manual, "
    "       (SELECT account_type FROM finance.accounts a WHERE a.id = t.account_id) AS account_type "
    "FROM finance.transactions t "
    "WHERE t.category_id IS NULL AND t.user_category_override = false "
    "  AND t.is_transfer = false AND t.is_investment = false "
    "ORDER BY t.posted_date DESC LIMIT $1"
)


async def run_cascade(pool, *, config: Optional[CategorizerConfig] = None,
                      embeddings_client: Optional[EmbeddingsClient] = None,
                      llm_call_model=None, max_transactions: int = 500) -> dict:
    """Run the cascade over the work-set. `embeddings_client` / `llm_call_model`
    are injectable for tests (so no live Ollama is required)."""
    async with pool.acquire() as conn:
        if config is None:
            config = await load_config(conn)
    shadow = config.engine == "shadow"
    client = embeddings_client or EmbeddingsClient(OLLAMA_URL, pool)
    writer = Writer()

    async with pool.acquire() as conn:
        normalizer = await build_normalizer(conn)
        # Tiers that only hold the connection / pre-loaded data are built once.
        rule_engine = await build_rule_engine(conn)
        llm_tier = await build_llm_tier(conn, call_model=llm_call_model)
        knn = config.knn
        tiers = [
            TransferDetector(conn),
            rule_engine,
            MerchantMemory(conn),
            EmbeddingKNN(conn, client, k=int(knn.get("k", 15)),
                         min_neighbors=int(knn.get("min_neighbors", 3))),
            llm_tier,
        ]
        pipeline = CategorizationPipeline(tiers, config)

        rows = await conn.fetch(_WORKSET_SQL, max_transactions)
        applied = 0
        queued = 0
        transfers = 0
        errors = []
        for r in rows:
            try:
                async with conn.transaction():  # per-row commit (R5.2)
                    merchant_key = r["merchant_key"]
                    if not merchant_key:
                        # Inline-on-read normalization (B3): derive + persist the key so
                        # tiers 1–3 never silently miss. Pure-rule, safe in shadow.
                        merchant_key = await normalize_and_store(
                            conn, normalizer, r["id"], r["description"])
                    ctx = TxnContext(
                        txn_id=r["id"], description=r["description"] or "",
                        amount=float(r["amount"]), account_id=r["account_id"],
                        account_type=r["account_type"], merchant_key=merchant_key,
                        posted_date=r["posted_date"], memo=r["memo"],
                        is_transfer_manual=r["is_transfer_manual"],
                    )
                    result = await pipeline.classify(ctx)
                    written = await writer.apply(conn, ctx, result, shadow=shadow)
                    if written["wrote_category"]:
                        applied += 1
                    elif written["wrote_transfer"]:
                        transfers += 1
                    elif result.is_actionable:
                        queued += 1
            except Exception as e:  # noqa: BLE001 — one bad row must not abort the run
                logger.exception("cascade: row %s failed", r["id"])
                errors.append(f"{r['id']}: {e}")

    summary = {
        "status": "completed",
        "engine": config.engine,
        "shadow": shadow,
        "transactions_found": len(rows),
        "auto_applied": applied,
        "transfers_flagged": transfers,
        "queued": queued,
        "errors": errors,
    }
    logger.info("cascade: %s", summary)
    return summary


async def categorization_metrics(conn) -> dict:
    """Observability (R5.6) computed from the AUTHORITATIVE decision log: counts
    per deciding tier, auto-applied vs queued, transfer flags, LLM decisions."""
    rows = await conn.fetch(
        "SELECT tier, "
        "       count(*) AS n, "
        "       count(*) FILTER (WHERE auto_applied) AS auto, "
        "       count(*) FILTER (WHERE is_transfer_set) AS transfers "
        "FROM finance.categorization_decision GROUP BY tier ORDER BY tier"
    )
    per_tier = {r["tier"]: {"n": r["n"], "auto_applied": r["auto"], "transfers": r["transfers"]}
                for r in rows}
    totals = await conn.fetchrow(
        "SELECT count(*) AS decisions, count(*) FILTER (WHERE auto_applied) AS auto_applied, "
        "count(*) FILTER (WHERE tier = 'llm') AS llm_calls, "
        "count(*) FILTER (WHERE is_transfer_set) AS transfer_flags "
        "FROM finance.categorization_decision"
    )
    return {
        "per_tier": per_tier,
        "decisions": totals["decisions"],
        "auto_applied": totals["auto_applied"],
        "llm_calls": totals["llm_calls"],
        "transfer_flags": totals["transfer_flags"],
    }
