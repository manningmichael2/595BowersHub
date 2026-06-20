# Finance Categorization — Tasks

> Each task traces to one or more requirements in `requirements.md` and follows the §Sequencing in `design.md`. Work top-to-bottom; respect dependencies. Ship behind the `categorizer_engine` feature-gate (`legacy → shadow → cascade`).

## Task 1: Fix R5.1 (code-only) + schedule SimpleFin + real-schema tests — ✅ DONE (commit 3235ba1)
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R5.1, R5.4
- [x] Schema-qualify every relation in `services/categorizer.py` to `finance.*` (the unqualified `transactions`/`categories`/`category_examples` that hit the non-updatable `public.transactions` JOIN view).
- [x] Schedule `simplefin_sync.sync_simplefin` in `main.py` to run **before** the 02:30 categorizer (was never scheduled); independent jobs, so a sync failure/overrun never blocks the run and is logged/alerted.
- [x] Replace the divergent hand-rolled schema in `test_finance_endpoints.py` (omitted `user_category_override`, which hid this bug) with the real baseline via `apply_migrations()` / `fresh_db`; fix the dashboard-test inserts for the real schema (varchar ids + account FK).
- [x] **Tests:** reproduce-then-fix on `fresh_db` — the unqualified `UPDATE public.transactions` raises, then `run_categorizer` persists `category_id` to `finance.transactions` (stub `_call_ollama`). Verified: **559 passed** on a throwaway pgvector pg16 (the new test is +1 over the prior 558).
- [x] **No migration** — code-only; no owned-object DDL, no migrator-role/cutover dependency.
- *Note:* baseline auto-rate capture (R5.6) deferred to the observability task (Task 10); the R5.1 fix is the prerequisite that makes any nonzero rate possible.

## Task 2: Schema migrations 0022+ (config tables, account_type, decision log, category seed) — ✅ DONE (commit 042d8b2)
- **Effort:** L
- **Dependencies:** Task 1
- **Requirements:** R1.2, R1.3, R1.4, R2.1, R2.6, R6.2
- [x] New `finance.*` tables (0022): `merchants` (+ merchant-level `halfvec(1024)` embedding + HNSW), `normalization_rules`, `mcc_categories`, `user_rules`, `merchant_memory`, `categorization_decision` (append-only provenance incl. `prior_category_id`), `eval_labels`.
- [x] Additive nullable columns + `public.transactions` view recreated with `merchant_key`/`categorized_by_tier`/`categorization_confidence`/`account_type`.
- [x] `finance.categorizer_config` key/value table.
- [x] **Extracted the live `finance.categories` tree** (verified against prod: 25 rows, 90% of live txns reference it → kept as-is, no overhaul) → idempotent category-seed migration (0023), `ON CONFLICT (name) DO NOTHING` (no-op on prod, fixes C2 category-empty rebuild); config defaults (gate=`legacy`); starter MCC→category map (full ISO-18245 = follow-up data load).
- [x] B1: `categorizer` key in `_FALLBACK_ROLE_MODEL` (local, not hosted) + `bh_model_aliases` row inheriting `local`'s model_id. *(Repointed to the empirically-chosen local model in Task 13.)*
- [x] **Migration:** `0022_finance_categorization_schema.sql` (owned-object DDL) + `0023_seed_finance_categorization.sql` (seed); migrator-authored, gated on the live C7 cutover.
- [x] **Tests:** apply-and-seed on `fresh_db` + pure B1 fallback check; `test_migrate_as_app_role` confirms the migrator/app split + grant propagation hold. **Full suite 561 passed** on throwaway pgvector pg16.
- *Note:* `eval_labels` taxonomy reconciliation happens when the eval set is seeded (Task 4).

## Task 3: NormalizationService + ingest hook + backfill (R1) — ✅ DONE (commit pending)
- **Effort:** M
- **Dependencies:** Task 2
- **Requirements:** R1.1, R1.5
- [x] `MerchantNormalizer.normalize(raw) → {key, display}` driven by `finance.normalization_rules` (intermediary-prefix strip, store numbers, store-type keywords, whitespace/case); unmatched → cleaned fallthrough, never errors. `0024` seeds the default rules.
- [x] `normalize_and_store()` single-txn primitive (upsert `finance.merchants` + set `merchant_key`) — the reusable inline-on-read path for the pipeline (B3, consumed in Task 10).
- [x] Hooked `backfill_merchant_keys(only_missing=True)` after the SimpleFin upsert (non-fatal). *(MCC-prior application deferred — SimpleFin ingest doesn't carry MCC; the MCC tier handles priors.)*
- [x] Separate idempotent `backfill_merchant_keys` (only_missing or full re-derive); runs in its own connection, not the nightly critical section.
- [x] **Tests:** R1.1 fixture table run against the **actual seeded rules** (incl. `COSTCO WHSE #0393 MADISON HEIGHMI → Costco`, `SQ *SUNRISE BAKERY → Sunrise Bakery`, unmatched fallthrough) + pure-engine + idempotent backfill. **Full suite 564 passed** on throwaway pgvector pg16.

## Task 4: Evaluation harness skeleton + labels (R2.7) — ✅ DONE
- **Effort:** S
- **Dependencies:** Task 2
- **Requirements:** R2.7
- [x] Seed `finance.eval_labels` with hand-verified `transaction → category` pairs, **including transfer/debt-payment cases** (`0025_seed_eval_labels.sql`: 25 labels, 6 transfer/debt cases incl. an ATM-not-transfer negative; idempotent `NOT EXISTS` guard; categories resolved by name).
- [x] `services/categorization_eval.py` skeleton — classifier-agnostic plumbing (`score_classifier(classify, labels)`) emitting per-tier/per-model accuracy + a transfer-flag confusion matrix (precision/recall). Category accuracy scored over non-transfer labels only. (Full-cascade scoring wired in Task 13.) Core `Decision`/`TxnContext`/`Classifier` value objects added in `services/categorization/base.py`.
- [x] **Tests:** labels seed + resolve on `fresh_db`; seed idempotency; the harness scores a stub classifier end-to-end (per-tier accuracy, transfer TP/FP, abstain count, serialization). **3 passed.**

## Task 5: TransferDetector tier (Feature 6) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 2, Task 3
- **Requirements:** R6.1, R6.2, R6.3, R6.4
- [x] Tier-0 detector (`services/categorization/transfer.py`): counterpart-matched inter-account transfers (R6.1, opposite-sign/~equal-amount/near-date in a *different* account) and confirmed payments into known-liability accounts via `finance.accounts.account_type` (R6.2); sets `is_transfer`, returns `category_id=None` so spending categorization is short-circuited (R6.4).
- [x] Asymmetric gate: counterpart/confirmed-liability → high confidence (0.95–0.98, terminal); ambiguous single-leg / unconfirmed liability inflow → confidence 0.5, non-terminal → distinct "transfer?" review item (R6.3), never a silent flag. Bare ATM cash withdrawal is NOT treated as a transfer.
- [x] Honor `is_transfer_manual`: detector abstains entirely on hand-marked rows (M6); the work-set predicate (`AND is_transfer = false`) keeps manually-flagged rows out.
- [x] One-time idempotent historical transfer-flag backfill (`transfer_backfill.py`): flags only ≥ `τ_transfer` (DB config), guarded UPDATE respects `is_transfer_manual`, per-row commit, own connection.
- [x] `investment_detector` / `is_investment` left untouched (orthogonal).
- [x] Added shared `services/categorization/config.py` (DB-driven per-tier thresholds / engine gate / kNN sizing — used here and by the gate/kNN later).
- [x] **Tests:** counterpart flag; liability payment via `account_type` (+ refund→queue); ambiguous single-leg → queue; ATM not a transfer; `is_transfer_manual` honored; flag excludes from spending total + un-flag restores; idempotent backfill (skips manual + ambiguous). **6 passed.**

## Task 6: RuleEngine tier (R2.1) — ✅ DONE
- **Effort:** S
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.1
- [x] `services/categorization/rules.py`: evaluate `finance.user_rules` by `priority` (then id) first-match-wins; match any combo of `merchant_key` / description regex / **amount range** (`amount_min`/`amount_max`) / `account_id` (all specified conditions AND-match); emit `Decision(confidence=1.0, terminal=True)` (rule-locked, R3.4). Rules with no conditions are inert (never match-all). Invalid regex is skipped, not fatal.
- [x] "Apply to existing matching" (`apply_rule_to_existing`) re-runs the predicate over history on demand; guarded UPDATE never clobbers a `user_category_override` (returns matched vs updated so the guard is observable). Bulk write via API → Writer choke point + RBAC in Task 11.
- [x] **Tests:** priority/first-match; amount-range + regex; empty rule inert; account-scoped rule loaded from DB; apply-to-existing guarded (matched=3, updated=2 with one override). **5 passed.**

## Task 7: MerchantMemory tier + LearningService (R2.2, R3) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.2, R3.1, R3.2
- [x] MerchantMemory tier (`services/categorization/memory.py`): deterministic lookup of the strongest `finance.merchant_memory` signal for the `merchant_key`, falling back to the directory `category_prior_id` (R1.2/R2.2), consulted **before any model call**; bounded monotone confidence (`memory_confidence`) from reinforcement count + recency half-life decay.
- [x] `LearningService.record_correction` (`services/categorization/learning.py`) upserts/strengthens `merchant_memory` keyed on normalized `merchant_key` (R3.1, derived via the DB rules when only a description is given), bumps reinforcement+recency, ensures a directory row, appends a provenance decision row — feeding the deterministic tier (R3.2).
- [x] **Redirect the existing writer (B-1):** `category_override.categorize_merchant` now calls `record_correction` (source=`chat_skill`) instead of the deprecated `category_examples` INSERT.
- [x] **Migration `0026_learning_service_cutover.sql`:** drops the `0018` trigger + `fn_learn_from_manual_override`; forward-migrates `category_examples` → `merchant_memory` (re-keyed via `UPPER(trim())`, `ON CONFLICT DO NOTHING` idempotent; provenance row); documented manual down-migration. `category_aliases` + `lookup_category_alias` retained (M1); deprecated `category_examples` table left in place (non-destructive/reversible).
- [x] **Tests:** corrected merchant categorized next time with **no model call** (unknown abstains); reinforcement raises confidence; category_prior fallback weaker; **chat-path correction lands in `merchant_memory`**; trigger+function gone, `category_aliases` reader intact; forward-migration idempotent. **7 passed.**
- *Note:* the **gated mass-recategorization** behind "apply to all from this merchant" (R3.3) is performed in Task 11 via the Writer choke point (Task 10) + endpoint RBAC — `record_correction` here only provides the learning helper, not the bulk write.

## Task 8: EmbeddingKNN tier (R2.3) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 2, Task 3, Task 7
- **Requirements:** R2.3
- [x] `services/categorization/knn.py`: `embed_merchants()` embeds normalized merchant strings once per merchant (`finance.merchants.embedding`, idempotent) reusing `EmbeddingsClient` + `bge-m3` + the current embedding version; `embed_categories()` computes category-description embeddings (humanized name) on `finance.categories.embedding` (cold-start B2).
- [x] kNN: nearest `k` merchants with a resolvable category (directory prior, else majority of their categorized txns) → majority vote, confidence = agreement fraction; `< min_neighbors` → nearest-category-embedding fallback (confidence = cosine similarity) → abstain; graceful Ollama-down abstain (stored vector reused when present, else embed-on-read).
- [x] **Volume measured (2026-06-20 live DB): 414 txns / 372 categorized / ≤ few-hundred distinct merchants** → seeded `k=15`, `min_neighbors=3` appropriate; merchant-level vectors keep the HNSW index (0022) trivially small. Figure documented in `knn.py`. Task 13 calibrates.
- [x] **Tests:** majority-vote + agreement-fraction confidence (k=3, 2-of-3); cold-start category-desc fallback; abstain when Ollama down; HNSW index present on fresh_db; embed_merchants/embed_categories populate + idempotent. **5 passed.**

## Task 9: LLMFallback tier (R2.4) + failure handling — ✅ DONE
- **Effort:** S
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.4, R5.5
- [x] `services/categorization/llm.py`: LLM tier via `resolve_role("categorizer")` (no literal model id; recorded in rationale for the eval per-model accuracy); single-txn structured prompt over the leaf-category tree, minus the hardcoded rules block; model self-reported score mapped+clamped to [0,1]. Model call is injectable for tests.
- [x] Parse-failure / Ollama-down / timeout → **abstain → queue, never "Other"** (rationale `model_unavailable` / `parse_failure_or_unknown`); unknown category name also abstains. Deleted the `_parse_response` Other-fallback in legacy `categorizer.py` (parse-failure → `[]`, unknown category → skip).
- [x] **Tests:** valid mapping + confidence; markdown-strip + clamp; Ollama-down abstain; parse-failure + unknown-category abstain (never Other); `build_llm_tier` loads leaves from DB; legacy Other-fallback source removed. **6 passed** (+ legacy reproduce-then-fix still green).

## Task 10: Pipeline + ConfidenceGate + Writer + nightly orchestration (R2.5, R2.6, R3.4, R5.2, R5.3, R5.6)
- **Effort:** L
- **Dependencies:** Task 5, Task 6, Task 7, Task 8, Task 9
- **Requirements:** R2.5, R2.6, R3.4, R5.2, R5.3, R5.6
- [ ] `CategorizationPipeline` runs tiers in **fixed code order** (transfer→rule→memory→kNN→LLM, R5.3), short-circuits on first decision clearing its per-tier τ or on `is_transfer`/`terminal` (R2.6); returns best sub-threshold decision for the queue.
- [ ] Work-set predicate excludes already-settled rows: `category_id IS NULL AND user_category_override = false AND is_transfer = false AND is_investment = false` (B-2 — investment rows must not be categorized as spending; leaves `investment_detector`/`is_investment` untouched).
- [ ] `ConfidenceGate` uses **per-tier thresholds** from `finance.categorizer_config` (R2.5); above → auto-apply, below → review queue (never "Other").
- [ ] Single Writer choke point: schema-qualified UPDATE with `WHERE user_category_override=false AND category_id IS NULL` (write-time re-check, R3.4); per-row commit (idempotent + resumable, R5.2); append `categorization_decision` with `prior_category_id` (R2.6, reversible).
- [ ] Evolve `run_categorizer()` into the orchestrator; honor the `categorizer_engine` gate incl. **shadow mode suppressing all writes** (category + `is_transfer`), provenance-only.
- [ ] Observability (R5.6): structured per-tier / auto-vs-queue / LLM-call / failure metrics computed from the decision log (authoritative).
- [ ] **Tests:** cascade order/short-circuit; per-tier gate (below→queue, above→auto); mid-batch correction not clobbered (R3.4); double-run no-op + partial-batch resumable (R5.2); shadow mode mutates nothing; provenance reconstructs coverage/LLM counts (R5.6); an `is_transfer=true` and an `is_investment=true` row are each never assigned a spending category.

## Task 11: Typed review write API (R4)
- **Effort:** M
- **Dependencies:** Task 8, Task 10
- **Requirements:** R3.3, R4.1, R4.2, R4.3, R4.4, R4.5
- [ ] `routers/finance_review.py` with Pydantic request/response models (no `any`), `Depends(get_current_user)` **+ explicit owner/admin role check** on every write endpoint. *(Follow-up, out of scope: generalize the hardcoded `ADMIN_ONLY_SKILLS` into a DB-driven `bh_skills.min_role` — tracked, not built here.)*
- [ ] `GET /review-queue` is the **backend read for R4.1** — predicted category + confidence + rationale from the decision log (the frontend in Task 12 renders it).
- [ ] "Apply to all from this merchant" (R3.3) is the **gated mass-recategorization**: write through the Task 10 Writer choke point (provenance + write-time guard), behind this endpoint's RBAC.
- [ ] `GET /review-queue` (uncategorized + below-threshold + "transfer?" items, with rationale from the decision log); `POST .../categorize` + `.../bulk-categorize` (R4.2/R4.3 → LearningService); `POST /merchants/{key}/apply-category` (R3.3/R4.3); `POST /user-rules` CRUD.
- [ ] `GET /recurring` (R4.5): ≥3 charges / ±X% / cadence window, DB-configured tolerances, live read-time query.
- [ ] DB-unavailable → typed error, no partial write; errors surface via the toast path. Chat skills keep working against the same service.
- [ ] **Tests:** endpoint contracts; RBAC denies non-owner; bulk + single correction fire learning; recurring grouping; DB-down typed error.

## Task 12: Finance Review frontend (R4.1, R1.6)
- **Effort:** M
- **Dependencies:** Task 11
- **Requirements:** R4.1, R1.6
- [ ] Dedicated Finance Review surface (replacing the chat-only `fill:` tool): queue list with predicted category + confidence + rationale chips (R4.1); multi-select bulk-apply; inline correct with "apply to all from this merchant / make a rule"; recurring sub-view.
- [ ] Typed API client + strict TS types matching the Pydantic models (no `any` at the boundary).
- [ ] Merchant logo via Logo.dev/favicon that **degrades gracefully** — no broken image, no blocked render (R1.6).
- [ ] **Tests:** `npx tsc --noEmit` clean; vitest for queue render + bulk/inline actions + logo-failure fallback.

## Task 13: Calibrate, gate, cut over (R2.4, R2.5, R2.7)
- **Effort:** M
- **Dependencies:** Task 4, Task 10, Task 12
- **Requirements:** R2.4, R2.5, R2.7
- [ ] Wire **full-cascade scoring** into the harness skeleton (deferred from Task 4 — the tiers + pipeline now exist), scoring each tier and the end-to-end cascade over `eval_labels`.
- [ ] Run the eval harness across candidate `categorizer` roles (local vs hosted); choose the default empirically (privacy-first), record rationale, and update the Task 2 fallback ID + alias row in lockstep (R2.4).
- [ ] Calibrate per-tier thresholds from the harness (precision targets) and write them to `finance.categorizer_config` (R2.5).
- [ ] Wire the eval harness as a CI regression gate that runs whenever the role or thresholds change (R2.7).
- [ ] Validate transfer-flagging + coverage from the decision log in `shadow`; flip `shadow → cascade` once backfill + embeddings are reconciled.
- [ ] **Tests:** eval CI gate fails on accuracy regression; thresholds loaded from DB; shadow→cascade cutover smoke test.

## Definition of Done
- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (validator clean).
- [ ] No hardcoded config introduced — taxonomy, MCC map, normalization/user rules, merchant directory, thresholds, and the categorizer model are DB rows; model selection via `resolve_role`.
- [ ] All new migrations apply on `fresh_db` from empty (C2); owned-object DDL is migrator-authored and cutover-gated; no applied migration edited.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`); the zero-coverage gap on categorizer/override/learning is closed.
- [ ] Shipped behind the `categorizer_engine` gate; shadow-validated before `cascade`.
- [ ] `context-log.md` updated with a dated entry.
