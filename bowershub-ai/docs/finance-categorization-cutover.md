# Finance Categorization — cutover runbook (Task 13)

The categorization cascade ships **dark** behind the `categorizer_engine`
feature-gate in `finance.categorizer_config` (`legacy → shadow → cascade`). This
runbook covers the remaining **owner-gated, live-environment** steps: choosing the
local model empirically, calibrating thresholds, validating in shadow, and flipping
to cascade. None of these require a redeploy — each is a single config row.

> Everything below runs against the live `finance` DB + the server's Ollama. The
> CI regression gate (`backend/tests/test_eval_regression_gate.py`) already guards
> the deterministic parts on every push; the model A/B and the prod flip are
> deliberately manual.

## 0. Preconditions
- PRs for Tasks 4–12 merged & deployed; migrations `0022`–`0026` applied on prod.
- C7 migrator-role cutover live (already true) — `0022`/`0026` are migrator-owned DDL.
- `categorizer_engine` is still `legacy` (the R5.1-fixed single pass) until step 4.

## 1. Reconcile the cascade's inputs
The nightly `categorization_warmup` job (`main.py`, 02:15) does this idempotently,
but to do it on demand:
```python
from backend.database import get_pool
from backend.services.embeddings import EmbeddingsClient
from backend.services.categorization.knn import embed_merchants, embed_categories
from backend.services.merchant_normalizer import backfill_merchant_keys
from backend.services.categorization.transfer_backfill import backfill_transfer_flags
pool = get_pool(); client = EmbeddingsClient("http://ollama:11434", pool)
await backfill_merchant_keys(only_missing=True)   # populate merchant_key + directory
await embed_categories(client, pool)              # cold-start kNN fallback vectors
await embed_merchants(client, pool, only_missing=True)
await backfill_transfer_flags()                   # high-confidence historical transfers
```

## 2. Model A/B — choose the local `categorizer` model empirically (R2.4)
For each candidate **local** model (privacy-first; never a hosted model), point the
`categorizer` role at it and score the full cascade over `finance.eval_labels`:
```python
from backend.services.categorization_eval import score_cascade
report = await score_cascade(pool)        # uses resolve_role("categorizer") + live Ollama
print(report.as_dict())                    # per-tier + per-model accuracy + transfer P/R
```
Switch candidates by updating the alias row, then re-run:
```sql
UPDATE public.bh_model_aliases SET model_id = '<candidate>' WHERE role = 'categorizer';
```
Pick the model with the best end-to-end accuracy (ties → smaller/faster). The
current default is `llama3.2:3b` — a **placeholder almost certainly too weak**;
replace it with the empirical winner.

**Update in lockstep (R2.4 / critic B1):** both the DB alias (above) AND the
cold-start fallback constant `_FALLBACK_ROLE_MODEL["categorizer"]` in
`backend/services/model_catalog.py` must point at the chosen model, so the
cold-start path can never fall back to the hosted `chat` model and leak descriptors.

## 3. Calibrate per-tier thresholds (R2.5)
From the A/B reports, pick each tier's τ at the operating point where its precision
meets target, then persist:
```python
from backend.services.categorization_eval import write_thresholds
async with pool.acquire() as conn:
    await write_thresholds(conn, {"rule": 1.0, "merchant_memory": 0.8,
                                  "embedding_knn": 0.7, "llm": 0.6, "transfer": 0.9})
```
Rule/transfer are effectively deterministic; the learned/LLM tiers carry the tuning.
Start conservative (higher τ → more goes to the review queue, never "Other").

## 4. Shadow validation (M4 — a true dry run, mutates nothing)
```python
from backend.services.categorization_eval import set_engine
async with pool.acquire() as conn:
    await set_engine(conn, "shadow")
```
Run the categorizer (or wait for 02:30). It writes ONLY provenance rows — no
category, no `is_transfer`. Validate from the authoritative decision log:
```python
from backend.services.categorization.orchestrator import categorization_metrics
async with pool.acquire() as conn:
    print(await categorization_metrics(conn))   # per-tier coverage, auto vs queue, llm/transfer counts
```
Inspect would-be transfer flags against reality (the asymmetric gate must show **no
false positives** — `is_transfer_set=true` rows should all be real transfers):
```sql
SELECT transaction_id, confidence, rationale
FROM finance.categorization_decision
WHERE is_transfer_set AND tier = 'transfer' ORDER BY decided_at DESC;
```

## 5. Flip shadow → cascade (live writes)
Once shadow coverage/accuracy look right AND step 1 is caught up:
```python
async with pool.acquire() as conn:
    await set_engine(conn, "cascade")
```
The next run auto-applies confident decisions through the Writer (guarded,
provenance-logged, reversible). Below-threshold rows go to the Finance Review queue
(`/finance/review`).

## 6. Rollback (instant, no redeploy)
```python
async with pool.acquire() as conn:
    await set_engine(conn, "shadow")   # or "legacy"
```
Any auto-write is reversible per-row from the decision log's `prior_category_id`.
Per-tier kill switches: set `tiers_enabled.<tier>=false` in
`finance.categorizer_config` to disable a misbehaving tier (e.g. kNN) without
touching the others.
```

## CI regression gate
`backend/tests/test_eval_regression_gate.py` runs in the backend CI job on every
push: it scores the cascade over `eval_labels` and fails if transfer precision/recall
or end-to-end accuracy drop below baseline — so a change to any tier, the
`categorizer` role, or the thresholds is caught before merge.
