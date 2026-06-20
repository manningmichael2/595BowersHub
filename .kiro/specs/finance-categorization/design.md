# Finance Categorization — Design

> Satisfies the requirements in `requirements.md`. Requirement IDs referenced inline (e.g. "satisfies R2.3").
> Synthesized from a 3-approach design tournament (minimal-change / ideal-architecture / risk-first); key trade-off decisions and why the alternatives lost are recorded in §10.

## Architecture Overview

Today categorization is a single nightly Ollama pass (`services/categorizer.py:36`) that writes to an **unqualified** `transactions`, which under the `bowershub_app` role resolves to `public.transactions` — a non-updatable JOIN view (`migrations/0016_enhance_transactions_view.sql:7`, no `INSTEAD OF` trigger). So the nightly `UPDATE` raises and **nothing persists** (R5.1). Learning is a brittle trigger keyed on "first alphabetic word ≥3 chars" (`migrations/0018_category_aliases_and_triggers.sql:48`), and `category_examples` only feeds the LLM prompt as few-shot text (`categorizer.py:50-54`), never as a deterministic lookup.

This design replaces that with a **single composable categorization pipeline** — an ordered cascade of independently-testable tiers, each returning a uniform `Decision`, behind one auditable write choke point — built on machinery the codebase already proved out for semantic memory (`HybridRetriever(embeddings_client, pool)` at `services/hybrid_retrieval.py:30`; the idempotent reconcile loop in `services/embedding_worker.py:52`).

```
ingest (simplefin / email / manual)
  └─ NormalizationService (R1.1–R1.5): raw descriptor → merchant_key  ──► finance.transactions.merchant_key (additive col)
                                                                        ──► finance.merchants (directory + merchant embedding)
nightly batch (idempotent, resumable, per-row commit)  — engine selected by DB feature-gate (legacy | shadow | cascade)
  └─ for each uncategorized, non-overridden txn:  CategorizationPipeline.classify(ctx) → Decision
        tier 0  TransferDetector   (R6)   → is_transfer, short-circuit (asymmetric gate: under-flag → queue)
        tier 1  RuleEngine         (R2.1) → terminal, confidence 1.0
        tier 2  MerchantMemory     (R2.2/R3.2) → deterministic learned lookup, BEFORE any model call
        tier 3  EmbeddingKNN       (R2.3) → nearest-merchant vote (reuses bge-m3 / halfvec)
        tier 4  LLMFallback        (R2.4) → residue only, resolve_role("categorizer")
  └─ ConfidenceGate (R2.5): conf ≥ τ → auto-apply ; else → review queue (NEVER "Other")
  └─ Writer (one choke point): re-check `user_category_override=false AND category_id IS NULL` AT WRITE TIME (R3.4);
        write finance.transactions + append finance.categorization_decision (provenance, R2.6)
correction (review API / chat skill) → LearningService.record_correction → MerchantMemory + decision log (R3)
review API (typed, R4.4) ◄──► Finance Review frontend (R4.1–R4.5)
```

**Reused (no/near-zero change):** `services/embeddings.py` (`EmbeddingsClient.embed`, `embeddings.py:25`); `services/model_catalog.py` `resolve_role` (`model_catalog.py:632`) — a new `categorizer` role is one DB alias row, zero resolver code change; `services/category_override.py` (becomes the service layer the new API and chat skills both call); `services/normalization.py` `lookup_category_alias`; `services/simplefin_sync.py` (reused; only *scheduled*, R5.4); the `@native_skill` registry (`skill_registry.py:33`); the migration runner + migrator-role split (`database.py`, `migrations/0021_migration_role.sql`).

**Evolved:** `services/categorizer.py` `run_categorizer()` becomes the idempotent orchestrator over the pipeline (keeps its fetch/batch/commit scaffolding; the single-prompt block is replaced).

**New:** `services/categorization/` package (pipeline + tiers + Decision), `services/categorization_eval.py`, `routers/finance_review.py`, one frontend Finance Review surface, migrations `0022+`.

## Components

### The `Decision` value object — the spine of R2.5/R2.6
A frozen dataclass every tier returns; the uniformity is what makes one DB threshold meaningful across tiers and keeps the pipeline tier-agnostic.
```python
@dataclass(frozen=True)
class Decision:
    category_id: int | None     # None = abstain → cascade continues
    confidence: float           # common [0,1] scale (R2.5)
    tier: str                   # 'transfer'|'rule'|'merchant_memory'|'embedding_knn'|'llm'
    rationale: dict             # evidence for R4.1: rule_id, neighbor merchant_keys, vote fraction, model_id
    is_transfer: bool = False   # R6 short-circuit
    terminal: bool = False      # rule/transfer lock — never re-evaluated (R3.4/R6.4)
```
`category_id is None` ⇒ abstain. A non-null decision is gated by `ConfidenceGate`. The pipeline **never produces "Other"** — the `_parse_response` Other-fallback (`categorizer.py:213-214`) is deleted (R2.5/R5.5).

**Confidence is gated per-tier, not by one global threshold (critic M5).** A kNN agreement fraction of 0.6 and an LLM self-reported 0.6 are *not* commensurable just because both are in [0,1]. R2.5 explicitly permits "documented per-tier thresholds" — we take that path: `finance.categorizer_config` holds one auto-apply threshold **per tier** (`τ_rule`, `τ_merchant_memory`, `τ_embedding_knn`, `τ_llm`, `τ_transfer`). The eval harness (R2.7) **calibrates** these against the labeled set (pick each τ at the operating point where that tier's precision meets a target), so the gate is empirical rather than asserting cross-tier scale equivalence. Rule/transfer are effectively 1.0 (deterministic); the learned/LLM tiers carry the real tuning.

### `CategorizationPipeline` + `Classifier` protocol
Mirrors the injectable `DiscoverySource` Protocol pattern (`model_catalog.py:116`) so tiers are fakeable in tests. `classify(ctx)` runs tiers in **fixed code order**, short-circuits on the first decision that clears its (DB-configured) per-tier threshold, immediately short-circuits on `is_transfer`/`terminal`, and otherwise returns the best sub-threshold decision (so the queue can show "we guessed X at 0.4" — R4.1) marked *not auto-applied*. `TxnContext` carries the txn row + normalized merchant + account metadata, pre-fetched once (not re-queried per tier). Order is fixed in code because transfer-first/LLM-last is a **correctness invariant** (R6.4/R5.3), not a tunable; per-tier *enable* and *threshold* are DB config (kill switches, R2.5).

### NormalizationService (R1.1–R1.5)
`normalize(raw) → NormalizedMerchant{key, display, mcc?}`. Pure-function core wrapped by a DB-row rule loader (`finance.normalization_rules`, R1.4) — replaces the hardcoded prompt rules (`categorizer.py:113-122`) and the NL→category map (`finance.py:356-366`). Strips intermediary prefixes (`SQ*`/`TST*`/`PYPL*`), store numbers (`#0393`), trailing city/state; collapses case/whitespace; **unmatched → cleaned-but-unmatched string, never an error** (R1.1). The contract is a **fixture table of input→output pairs** (R1.1 acceptance). Runs **on ingest** (hooked after the SimpleFin upsert at `simplefin_sync.py:127-137`, plus email/manual paths) and via a **separate idempotent backfill** (R1.5). A `normalization_rules.version` bump re-derives keys only for affected rows (mirrors the embedding `version` gate at `embedding_worker.py:112-119`).

**No `merchant_key` ordering hazard (critic B3).** `TxnContext` construction normalizes **inline-on-read**: when `pipeline.classify()` builds the context for a row whose `merchant_key` is NULL (ingested before the hook shipped, or not yet backfilled), it derives the key on the spot from the DB rules and persists it. Normalization is a cheap pure-rule transform, so this is safe to do in the read path — it means tiers 1–3 can never silently miss because a key wasn't populated yet, and the nightly work-set needs no `merchant_key IS NOT NULL` filter. The on-ingest hook and backfill remain pure optimizations (they keep the merchant directory + embeddings warm); the *embedding* tier's effectiveness still depends on the directory being populated, which is why the `shadow → cascade` flip is gated on backfill + embedding reconciliation being caught up (§Rollout).

### TransferDetector — tier 0, runs first (R6), conservative by design
Flags inter-account transfers (R6.1) and liability-account payments (R6.2), sets `is_transfer`, and short-circuits spending categorization (R6.4). Liability detection uses the new DB-driven `finance.accounts.account_type` (`checking|savings|credit_card|loan|mortgage|brokerage`) — **not** hardcoded merchant matching. **Asymmetric gate (the key safety property):** auto-flag only on *high* confidence (≥ `τ_transfer`) — counterpart-matched transfers (opposite-sign, ~equal amount, near date, between two own accounts) or a payment into a known-liability account. **Everything ambiguous (single-leg heuristics) routes to a distinct "transfer?" review (R6.3), never a silent flag.** Rationale: a false transfer flag silently removes real spending from every budget; a missed flag is one manually-fixable queue item.

**`is_transfer_manual` honored in the predicate, not just "abstractly" (critic M6).** A row with `is_transfer_manual = true` is **excluded from tier 0 auto-flagging entirely** — TransferDetector skips it and uses the owner's value (the owner has full `db_browser` write access and may set this by hand). If the manual value says "is a transfer," the row short-circuits; if it says "not a transfer," tier 0 abstains and the row flows on to the spending tiers. The cascade-entry guard checks `is_transfer_manual` so a hand-marked row is never re-flagged. Column exists at `0001_baseline.sql:468`.

**First-ever writer of `is_transfer` — two consequences made explicit (critic M3).** Verified: nothing in the codebase writes `is_transfer` today; it is only read (finance/briefing). So this tier introduces the first writer. (a) **Un-flag → re-queue, intended:** un-flagging a transfer leaves `category_id IS NULL`, so the row re-enters the work-set next run and gets categorized as spending — that's the desired reversal, and a test asserts un-flag restores the spending total. (b) **Historical backfill:** existing history has no `is_transfer` set; a one-time idempotent transfer-flag pass (part of the R1.5-style backfill ops, run separately from the nightly critical section, respecting `is_transfer_manual`) flags past transfers. Until it runs, historical transfers simply remain unflagged — no corruption, just incomplete coverage.

**Does NOT touch `is_investment` (critic M2).** `services/investment_detector.py` writes `is_investment` (an orthogonal axis that `briefing.py:178-187` uses to exclude investments from spending) via its post-sync hook (`simplefin_sync.py:140-142`). That hook and column are **left untouched** — investment detection is out of this spec's scope (Feature 6 is transfers/debt only). TransferDetector neither supersedes nor removes it. **But leaving the detector alone is necessary, not sufficient (critic B-2):** an `is_investment=true` row has `category_id IS NULL` and `is_transfer=false`, so it would enter the work-set and get a spending category — which is why the work-set predicate (§Data Flow step 2) also carries `AND is_investment = false`, mirroring the `dashboard.py:430` spending-exclusion.

### RuleEngine — tier 1 (R2.1)
`finance.user_rules`, user-orderable `priority`, first-match-wins. Matches any combination of `merchant_key`, raw-description regex, **amount range** (`amount_min`/`amount_max`, not just sign), and `account_id`. Emits `Decision(confidence=1.0, terminal=True)` — rule-locked, never overwritten (R3.4). "Apply to existing matching" re-runs the predicate over history on demand (R2.1/R3.3). Replaces the fuzzy `similarity()>0.20` ILIKE hack (`category_override.py:42-48`) with a deterministic rule.

### MerchantMemory — tier 2 (R2.2/R3.2), the deterministic learned tier
For a `merchant_key`, consults (a) the directory `category_prior` (R1.2) and (b) the strongest learned signal in `finance.merchant_memory`. Confidence is a bounded monotone function of reinforcement count + recency. **Consulted before any model call** (R2.2) — so a corrected merchant is re-categorized with zero LLM cost next time (the "correction stickiness ~100%" success metric). This is the fix for `category_examples` only feeding the prompt.

### EmbeddingKNN — tier 3 (R2.3), built on the existing stack, embedding at the MERCHANT level
Reuses `EmbeddingsClient` + `bge-m3` + `halfvec(1024)` + the HNSW index pattern (`migrations/0010`). **Embeds the normalized merchant string once per distinct merchant** and stores it on `finance.merchants.embedding` — *not* per-transaction (far fewer vectors; "nearest merchants" is exactly the categorization signal). kNN: nearest *k* merchants that have a known category (prior or majority of their categorized txns), **majority-vote**, `confidence = agreement fraction` (R2.3/R2.5). `k`, index type (HNSW per `0010`), and `min_neighbors` are DB config sized against **measured transaction volume** (R1.5/R2.3 — measured in the first task). Degrades cleanly when Ollama is down (abstain, like `hybrid_retrieval.py:48-49`, R5.5).

**Cold-start bootstrap — made concrete (critic B2).** "Nearest categorized merchant" is circular on an empty system, so the tier has two explicit bootstrap sources, both established before it can contribute: (1) **MCC priors** — `finance.mcc_categories` (R1.3) gives a new merchant a `category_prior` from its MCC the moment it's seen, so the *merchant-memory* tier (2) covers most cold-start cases *before* kNN is even consulted; (2) **category-description embeddings** — `finance.categories` gets an `embedding halfvec(1024)` column (one vector per category, embedded from name + description); when fewer than `min_neighbors` categorized merchants exist, kNN votes over nearest **category** embeddings instead of nearest merchants, else abstains to the LLM. Required ordering, stated as a hard dependency in §Sequencing: **categories seeded (see §Data Model category-seed migration) → category embeddings computed → only then does tier 3 contribute.** On `fresh_db`/eval where the live category tree is absent (§10-T1), the category-seed migration is what makes both this tier and the eval harness (R2.7) testable at all.

### LLMFallback — tier 4 (R2.4), residue only
Only transactions unresolved by tiers 0–3 (R5.3). Model via `resolve_role("categorizer")` — a **new DB role defaulting to a local Ollama model** (privacy-first, R2.4), hosted A/B one DB row away. Reuses the structured-prompt scaffolding (`categorizer.py:109-127`) minus the hardcoded rules block and minus the Other-fallback. Confidence = the model's mapped-to-[0,1] score (R2.5); parse-failure or Ollama-down ⇒ **abstain → queue, never "Other"** (R5.5). The provider choice is **empirical against the eval set (R2.7), not asserted, and explicitly not a cost question** (R2.4 rationale: cheap tiers absorb the volume, LLM cost is pennies/month).

> **Privacy-safe role default — NOT zero-code (critic B1):** `resolve_role(role)` returns `_FALLBACK_ROLE_MODEL.get(role, _FALLBACK_ROLE_MODEL["chat"])` whenever the DB-catalog cache isn't warmed (`model_catalog.py:632-642`), and `chat` = `claude-sonnet-4-6` (hosted). A `categorizer` role with only a DB alias row would, on the cold-start / early-startup / test path, **silently resolve to hosted Anthropic and send transaction descriptors off-box** — violating R2.4. Required fix (one-line code change, contradicting any "zero resolver change" claim): add a `categorizer` key to `_FALLBACK_ROLE_MODEL` (`model_catalog.py:623`) pointing at a **named local model**, **and** seed the `public.bh_model_aliases` row in a `0022+` migration. Note: that row is a `public.*` change, not `finance.*`. The dict already has `"local": "llama3.2:3b"` — that 3B model is a **placeholder, almost certainly too weak to be the categorizer default**; the fallback ID committed here must be the same model Task 13's eval picks as the local default (updated in lockstep), not silently inherited from `local`.

### LearningService (R3) — replaces the 0018 trigger
A correction (API or chat skill) → `record_correction(txn, new_category, source)` upserts/strengthens `finance.merchant_memory` keyed on **normalized merchant_key** (R3.1/R3.2), bumping reinforcement + recency, and appends a decision-log row. MerchantMemory consults it deterministically (R3.2). "Apply to all from this merchant" (R3.3/R4.3) recategorizes all `merchant_key`-matching rows + optionally mints a `user_rule` or sets the merchant `category_prior`. **Only the `0018` AFTER-UPDATE trigger + `fn_learn_from_manual_override` function are dropped** (§10 trade-off T2): an explicit ordered service call is testable, concurrency-safe, and can call the Python normalizer (a trigger can't compute the normalized key without re-implementing the rules in SQL). Existing `category_examples` rows are forward-migrated into `merchant_memory` (re-keyed onto `merchant_key`) with a documented down-migration (R3.1).

> **Redirect the existing chat-skill writer (critic B-1).** `category_override.py:53-56` (the interactive path the new API and chat skills share) currently `INSERT … ON CONFLICT … times_reinforced+1` into `category_examples`. After that table is forward-migrated into `merchant_memory`, this writer must be **redirected to `LearningService.record_correction`** or it silently writes to a dead table and chat-path corrections stop reinforcing the tier that now reads `merchant_memory`. Done in Task 7 with a test that a chat-path override lands in `merchant_memory`.

> **Retain `category_aliases` (critic M1).** The `finance.category_aliases` table and its live reader `normalization.lookup_category_alias` (`normalization.py:67-83`) — which resolve a natural-language category *name* to a `category_id` on the write/commit path — are **kept untouched**. That is a different map from `normalization_rules` (which derives *merchant keys*) and from the ask-db NL hint at `finance.py:356-366` (a prompt string). Dropping the 0018 trigger does **not** drop the aliases table; only the trigger/function go.

### Writer — the one choke point (R3.4/R2.6/R5.1)
Every category/transfer mutation goes through one committer. It schema-qualifies all SQL to `finance.*` (R5.1) and carries the guard in the `WHERE` clause:
```sql
UPDATE finance.transactions
   SET category_id = $1, categorized_by_tier = $2, categorization_confidence = $3
 WHERE id = $4
   AND user_category_override = false   -- correction landed mid-batch → no-op (R3.4)
   AND category_id IS NULL              -- already categorized → no-op (idempotent, R5.2)
```
Read-old / check-at-write concurrency control — **no row lock is held across the slow embed/LLM window** (holding `FOR UPDATE` across an Ollama call would be a latency/deadlock hazard and is rejected). Each write also inserts a `finance.categorization_decision` row capturing `prior_category_id` → any auto-write is reversible by a single UPDATE (R2.6 reversibility). Per-row commit ⇒ partial-batch failure leaves committed rows, next run resumes (R5.2/R5.5).

### Eval harness (R2.7)
`finance.eval_labels` (data, incl. transfer/debt cases) + `services/categorization_eval.py`: runs each tier and the full cascade over the labeled set, reports per-tier/per-model accuracy + transfer-flag confusion. Makes R2.4's model choice and R2.5's thresholds empirical, and doubles as a CI regression guard whenever the `categorizer` role or thresholds change. Runs on `fresh_db` with fixture-seeded labels (categories must be seeded explicitly — see §10 T1).

## Data Flow (nightly batch, R5)
1. **Sync first (R5.4):** schedule `sync_simplefin` (`simplefin_sync.py:33`) as a job *before* the 02:30 categorizer in `main.py` (today only the categorizer is scheduled at `main.py:117`; the "after the 2am sync" comment is fiction). Sync failure/overrun → categorizer runs on present data, logs/alerts, picks up late arrivals next run (idempotent) — don't block.
2. **Find work:** `category_id IS NULL AND user_category_override = false AND is_transfer = false AND is_investment = false` (R5.2, idempotent) — settled transfers stay out; an un-flagged transfer (set back to `is_transfer=false`, `category_id` still NULL) re-enters and gets categorized.
3. **Per txn:** `pipeline.classify()` → `ConfidenceGate` → Writer (with the write-time re-check) → decision-log insert.
4. **Per-row commit** (resumable, R5.5).
5. **Emit structured metrics** (R5.6) computed from the decision log: counts per deciding tier, auto-applied vs queued, LLM calls, failures — makes the Success Metrics queryable.

## Data Model / Migrations
Forward-only files starting at **0022** (next unused), `bowershub_migrator`-role DDL for all owned-object changes, each applying cleanly from empty on `fresh_db` (C2 acceptance). Never edit an applied migration (`database.py` checksum-drift guard). **Defensive note:** `finance.categories` is populated only in the live DB, *not* in the `0001` data block (finding from the ideal-architecture pass) — migrations and tests must not assume seeded categories.

**New `finance.*` tables:** `merchants` (`merchant_key UNIQUE, display_name, category_prior_id, mcc, domain, embedding halfvec(1024), embedding_version`); `normalization_rules` (R1.1/R1.4); `mcc_categories` (R1.3, seeded ISO-18245); `user_rules` (R2.1); `merchant_memory` (R3.1); `categorization_decision` (R2.6/R5.6 — append-only: `txn_id, tier, confidence, model_id, prior_category_id, applied_category_id, is_transfer_set, auto_applied, rationale jsonb, decided_at`); `eval_labels` (R2.7).

**Altered (additive, nullable — safest class; no rewrite):** `finance.transactions ADD merchant_key text, categorized_by_tier text, categorization_confidence numeric`; `finance.accounts ADD account_type text` (R6.2 prerequisite); `finance.categories ADD embedding halfvec(1024)` (cold-start kNN fallback, B2); `public.transactions` view (`0016`) extended with the new columns (migrator-owned — the exact object that crash-looped on 2026-06-19).

**Category-seed migration (critic B2 — required for C2 + testability).** `finance.categories` is populated only in the live DB, *not* in the `0001` data block — meaning a from-empty rebuild (the C2 promise) and every `fresh_db` test currently come up with **zero categories**, which would leave the finance system non-functional on a clean deploy regardless of this feature. A `0022`-era **idempotent category-seed migration** establishes the canonical category taxonomy (`INSERT … ON CONFLICT (name) DO NOTHING`, so it never clobbers the live tree). This is data-as-config (NO-HARDCODING-aligned — the taxonomy is rows), it makes the live and fresh_db schemas converge, and it's the prerequisite that lets the kNN tier and the eval harness function in CI. Category-description embeddings are then computed from these seeded rows.

**Authoritative source for provenance (critic MN2):** the append-only `finance.categorization_decision` log is **authoritative** for R2.6 / R5.6 metrics and the R4.1 rationale. The `categorized_by_tier` / `categorization_confidence` columns on `finance.transactions` are a **denormalized cache of the current decision only**, for fast review-queue filtering — never the source of truth for history.

**Dropped:** the `0018` trigger + `fn_learn_from_manual_override` function (T2); `category_examples` forward-migrated into `merchant_memory` (reversible, R3.1).

**Config (not a table):** confidence thresholds, per-tier enable, the engine feature-gate (`legacy|shadow|cascade`), `k`/`min_neighbors`, recurring-detection tolerances → key/value rows in `finance.categorizer_config` (mirrors the `bh_platform_settings`/`embedding_config` pattern). **Taxonomy:** keep the existing `finance.categories` tree; if Plaid-PFC alignment is wanted later, add nullable mapping columns only — no destructive re-map (T1).

## API / Interfaces
New typed router `routers/finance_review.py` (`Depends(get_current_user)`, Pydantic request/response models, **no `any` at the boundary** — C6/R4.4), calling the **same `CategorizationService` the chat skills call** so existing native skills keep working (R4.4):
- `GET /api/finance/review-queue` — uncategorized + below-threshold + "transfer?" items, each with predicted category + confidence + rationale from the decision log (R4.1); supports the recurring-charge view (R4.5: ≥3 charges, ±X%, cadence window — DB-configured tolerances). Recurring detection is a **live read-time query** over history at current (single-household) volume (critic MN1); if the measured volume task shows it's expensive, it becomes a materialized signal — revisit then, not now.
- `POST /api/finance/transactions/{id}/categorize` (R4.3) and `…/bulk-categorize` (R4.2) → LearningService.
- `POST /api/finance/merchants/{key}/apply-category` — "apply to all from this merchant" + optional rule mint (R3.3/R4.3).
- `POST /api/finance/user-rules` — CRUD with priority.
DB-unavailable → typed error, no partial write (R4.4). Errors surface via the global toast path (C6).
**Frontend:** a dedicated Finance Review surface (the chat-only `fill:` tool is replaced): queue list with category + confidence + rationale chips, single/bulk/apply-to-merchant actions, recurring sub-view, merchant logo via Logo.dev/favicon that **degrades gracefully** (R1.6). Typed API client, strict TS types matching the Pydantic models.
**RBAC now, not deferred (critic MN4):** these are financial write endpoints, so each requires `Depends(get_current_user)` **and** an explicit owner/admin role check at the router (the system is single-owner today). The DB-driven `bh_skills.min_role` generalization of `ADMIN_ONLY_SKILLS` (`skill_executor.py:22`) is the **follow-up** — deferring the *generalization* is fine, deferring the *check* is not.

## Technology Choices
- **pgvector `halfvec(1024)` + bge-m3 + HNSW**, reusing the shipped stack (`migrations/0010`, `services/embeddings.py`) — no new embedding infra. Merchant-level vectors keep the index tiny.
- **`resolve_role` DB role** for the LLM tier — no literal model IDs (R2.4/NO-HARDCODING); default local for privacy.
- **No new dependency** beyond an open MCC dataset (greggles/mcc-codes or python-iso18245) seeded as data, and optional Logo.dev for logos.

## Rollout & Reversibility (risk-first graft)
- **DB feature-gate `categorizer_engine`:** `legacy` (the R5.1-fixed single-LLM path) → `shadow` → `cascade` (live). First cascade deploy is dark; flip one row to enable, flip back to roll back — no redeploy.
- **Shadow mode suppresses ALL writes — category *and* `is_transfer` (critic M4).** In `shadow`, the pipeline runs end-to-end and appends `finance.categorization_decision` rows (including the would-be transfer flag, its confidence, and `is_transfer_set`) but **mutates no row** in `finance.transactions`. R6 transfer-flagging accuracy is therefore validated entirely from the decision log before cutover — you inspect would-be flags against reality without ever zeroing a spending total. Shadow is a genuine dry run; it never silently mutates financial data.
- **The `shadow → cascade` flip is conditional** (B3) on the merchant-directory backfill + embedding-version reconciliation being caught up, so the embedding tier is effective (not abstaining) when live writes begin.
- **Confidence-gated auto-apply (R2.5):** below threshold ⇒ queue, never auto-write, never "Other"; tunable down to "queue everything" during initial rollout.
- **Per-tier kill switches** (DB config) — disable a misbehaving tier (e.g. kNN) without disabling rules/memory.

## Sequencing (each step independently shippable & verified)
1. **PR #1 — R5.1, code-only:** schema-qualify `categorizer.py`; reproduce-then-fix regression test on `fresh_db`; **schedule SimpleFin before the categorizer (R5.4)**; replace the divergent test schema (`test_finance_endpoints.py:46-81`, omits `user_category_override`) with `run_migrations()`. Capture the R5.6 baseline here (true auto-rate is ~0 until this lands). No migration, no cutover gate.
2. **Schema + normalization:** migrations `0022+` (merchants, rules, mcc, account_type, `categories` embedding col, decision log, config), the **idempotent category-seed migration** (B2), the `categorizer` `_FALLBACK_ROLE_MODEL` entry + alias row (B1), NormalizationService + fixture table (R1.1), inline-on-read + ingest hook + backfill (R1.5).
3. **Eval scaffold early (R2.7):** seed `finance.eval_labels` (incl. transfer cases) + the scoring harness, so every subsequent tier and the model choice are measured against it as they land — *not* deferred to the end (critic MN3).
4. **Deterministic tiers (no model):** TransferDetector (R6), RuleEngine (R2.1), MerchantMemory (R2.2) + LearningService (R3, drop the 0018 trigger). Ship in `shadow`, validate via decision log + eval.
5. **kNN tier (R2.3)** + merchant & category embeddings + worker hook.
6. **LLM tier + ConfidenceGate (R2.4/R2.5)**, delete the Other-fallback; `categorizer` role's local default chosen empirically against the eval set; per-tier thresholds calibrated by the harness.
7. **Review API + frontend (R4)**; eval harness wired into CI as a regression gate. Flip `shadow → cascade` once backfill + embeddings are reconciled.

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| **R5.1 masks everything** — true auto-rate ~0 today | Land R5.1 + reproduce-then-fix test **first** (PR #1); baseline measured after. |
| **Owned-object DDL crash-loop** (2026-06-19, `0021:5`) | All `finance.*`/view/trigger DDL as `bowershub_migrator`; deploy gated on cutover live; CI scoped-deploy test (per `test_migrate_as_app_role.py`). R5.1 itself is code-only (no migration). |
| **Transfer false-positive silently zeros spending** | Asymmetric gate: auto-flag only high-confidence; all ambiguity → "transfer?" queue; flags reversible (un-flag restores totals). |
| **Mid-batch correction clobbered** | Write-time `WHERE user_category_override=false` re-check; per-row commit; learning is an explicit ordered call, not a trigger firing mid-UPDATE. |
| **Taxonomy re-map orphans data** | Keep existing tree; PFC additive-only; no destructive remap (T1). |
| **Unmeasured volume mis-sizes kNN** | Measure txn volume in task 1; size `k`/index/min_neighbors against it; merchant-level vectors keep it small regardless. |
| **`finance.categories` absent from baseline** | Migrations/tests defensive; eval & tests seed categories explicitly. |
| **Cascade is a financial write-path change** | Feature-gate + shadow mode; dark by default; instant DB-row rollback. |

## Test Strategy
All DB-backed tests run against the **real `0001` baseline via `fresh_db` + `run_migrations()`** (per `semantic_helpers.apply_migrations` / `test_baseline_seed.py`) — replacing the divergent mini-schema that hid R5.1. Closes the current zero-coverage gap on `categorizer.py`/`category_override.py`/learning/L1 patterns (NFR).
- **R5.1 reproduce-then-fix** (PR #1): assert the unqualified `UPDATE public.transactions` raises, then the qualified path persists `category_id`.
- **Pure unit (no DB):** Normalizer fixture table (R1.1), ConfidenceGate, per-tier confidence math, `Decision` semantics (the `tests/properties` style).
- **Concurrency/R3.4:** correction set mid-flight → guarded UPDATE no-ops, correction survives.
- **Idempotency/resumability (R5.2/R5.5):** double-run is a no-op; mid-batch failure leaves committed rows and resumes.
- **Transfer (R6):** checking→savings + CC/loan/mortgage payment flagged via DB `account_type`, excluded from spending totals, never assigned a category; ambiguous single-leg → "transfer?" queue; un-flag restores totals.
- **Stickiness (R3):** corrected merchant categorized on next occurrence **without an LLM call** (assert the LLM tier wasn't invoked).
- **Gate (R2.5):** below-threshold → queue (not "Other"); above → auto-apply; thresholds from DB; assert the `213-214` Other-fallback is gone.
- **Failure modes (R5.5):** Ollama-down + parse-failure → queue (reuse `FakeEmbeddingsClient(fail=True)`); partial-batch resumable.
- **Provenance (R2.6):** every auto-write logs a row; a query reconstructs coverage + LLM-call counts.
- **Migration safety (C2):** all `0022+` apply on `fresh_db`; scoped-deploy test proves they apply under the migrator role and that `0021` default-privileges deliver grants to `bowershub_app`/`finance_reader`.
- **NO-HARDCODING inspection:** grep proves taxonomy/MCC/rules/thresholds/directory are DB rows and the prompt-rule block / NL-map constants are gone.
- **Eval harness (R2.7):** scores per tier/model incl. transfer cases; wired as a CI regression gate.

## §10 Synthesis decisions (trade-offs & why the alternatives lost)
- **T1 — Taxonomy: keep the existing `finance.categories` tree; defer full Plaid-PFC re-taxonomy.** *Loser:* a wholesale PFC re-map. Re-mapping live `category_id`s risks orphaning transactions, examples, and kNN neighbors for a data-integrity hazard disproportionate to the categorization-quality goal — and the tree isn't even in the baseline. PFC alignment becomes additive mapping columns later (accounting spec).
- **T2 — Learning: explicit `LearningService` call; drop the `0018` trigger.** *Loser:* evolving the trigger body. A trigger can't compute the normalized merchant_key without re-implementing the DB rules in SQL, fires mid-batch (concurrency foot-gun), and is hard to test. *Accepted cost:* corrections made out-of-band via raw `db_browser` SQL won't auto-learn — acceptable, as corrections flow through the API/skill path by design.
- **T3 — Embeddings at the merchant level on `finance.merchants`, not per-transaction and not in `kb_chunks`.** *Losers:* per-txn vectors (one per transaction — far more vectors, larger index) and reusing `public.kb_chunks` (couples finance to the message/entity store, crosses the `finance_reader` boundary). Merchant-level vectors are smaller and are exactly the "nearest merchant" signal categorization needs.
- **T4 — Cascade order fixed in code; only per-tier enable/threshold are DB config.** *Loser:* a fully DB-driven `categorization_tiers` ordering table. Transfer-first/LLM-last is a correctness invariant (R6.4/R5.3); making it reorderable invites a config change that runs the LLM before rules or skips the transfer gate. Kill switches and thresholds give the operational flexibility without the footgun.
- **T5 — R5.1 ships first as a code-only PR with a reproduce-then-fix test, ahead of all new schema/tiers.** Unanimous across approaches: it's the largest correctness win on the safest path and gives a working baseline to measure the overhaul against.
