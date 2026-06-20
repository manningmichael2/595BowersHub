# Finance Categorization — Tasks

> Each task traces to one or more requirements in `requirements.md` and follows the §Sequencing in `design.md`. Work top-to-bottom; respect dependencies. Ship behind the `categorizer_engine` feature-gate (`legacy → shadow → cascade`).

## Task 1: Fix R5.1 (code-only) + schedule SimpleFin + real-schema tests
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R5.1, R5.4
- [ ] Schema-qualify every relation in `services/categorizer.py` to `finance.*` (the unqualified `transactions`/`categories`/`category_examples` at `categorizer.py:46,51,57,144` currently hit the non-updatable `public.transactions` JOIN view).
- [ ] Schedule `simplefin_sync.sync_simplefin` in `main.py` to run (and complete) **before** the 02:30 categorizer; on sync failure/overrun the categorizer runs on present data and logs/alerts — does not block.
- [ ] Replace the divergent hand-rolled schema in `test_finance_endpoints.py:46-81` (omits `user_category_override`/`memo`, which hid this bug) with the real baseline via `run_migrations()` / `fresh_db`.
- [ ] Capture the pre-overhaul baseline auto-categorization rate (expected ~0 until this lands).
- [ ] **Tests:** DB-backed reproduce-then-fix on `fresh_db` — assert the unqualified `UPDATE public.transactions` raises, then assert the qualified path persists `category_id` to `finance.transactions` (stub `_call_ollama`).
- [ ] **No migration** — code-only; verify no owned-object DDL, so no migrator-role/cutover dependency.

## Task 2: Schema migrations 0022+ (config tables, account_type, decision log, category seed)
- **Effort:** L
- **Dependencies:** Task 1
- **Requirements:** R1.2, R1.3, R1.4, R2.1, R2.6, R6.2
- [ ] New `finance.*` tables: `merchants` (R1.2: `merchant_key UNIQUE, display_name, category_prior_id, mcc, domain, embedding halfvec(1024), embedding_version`), `normalization_rules` (R1.4), `mcc_categories` (R1.3), `user_rules` (R2.1: priority, merchant_key, description_regex, amount_min/max, account_id, category_id), `categorization_decision` (R2.6: append-only provenance incl. `prior_category_id`, `tier`, `confidence`, `model_id`, `is_transfer_set`, `auto_applied`, `rationale jsonb`).
- [ ] Additive nullable columns: `finance.transactions ADD merchant_key, categorized_by_tier, categorization_confidence`; `finance.accounts ADD account_type` (R6.2); `finance.categories ADD embedding halfvec(1024)`; extend the `public.transactions` view (`0016`) with the new columns.
- [ ] `finance.categorizer_config` key/value table: per-tier thresholds, `categorizer_engine` gate, per-tier enable, `k`/`min_neighbors`, recurring tolerances.
- [ ] **Extract the live `finance.categories` tree** (it exists only in prod, not in `0001`) as the seed source-of-truth; reconcile category names against the `eval_labels` taxonomy (Task 4).
- [ ] **Idempotent category-seed migration** (`INSERT … ON CONFLICT (name) DO NOTHING`, rows = the extracted live tree so it's a genuine no-op against prod) — so fresh_db/clean-rebuild aren't category-empty (C2); seed MCC→category data.
- [ ] Add a `categorizer` entry to `_FALLBACK_ROLE_MODEL` (`model_catalog.py:623`) pointing at a **named local model** + seed the `public.bh_model_aliases` row (B1 — privacy-safe cold-start). The named ID is a placeholder until Task 13 picks the local default empirically — keep the two in lockstep; do **not** inherit the weak `local` = `llama3.2:3b`.
- [ ] **Migration:** `bowershub-ai/backend/migrations/0022_*.sql …` — all owned-object DDL authored as `bowershub_migrator`, gated on the C7 cutover being live; never edit an applied file.
- [ ] **Tests:** all new migrations apply on `fresh_db` from empty; scoped-deploy test (per `test_migrate_as_app_role.py`) proves they apply under the migrator role and that `0021` default-privileges grant DML to `bowershub_app` / SELECT to `finance_reader`.

## Task 3: NormalizationService + ingest hook + backfill (R1)
- **Effort:** M
- **Dependencies:** Task 2
- **Requirements:** R1.1, R1.5
- [ ] Pure-core `normalize(raw) → {key, display, mcc?}` driven by `finance.normalization_rules` (prefix-strip `SQ*`/`TST*`/`PYPL*`, store numbers, city/state tails, case/whitespace); unmatched → cleaned-but-unmatched fallthrough.
- [ ] Inline-on-read: `TxnContext` derives + persists `merchant_key` when NULL (eliminates the ordering hazard — B3).
- [ ] Hook normalization after the SimpleFin upsert (`simplefin_sync.py:127-137`) and email/manual paths; upsert into `finance.merchants` (apply MCC prior).
- [ ] Separate idempotent backfill op (re-derives keys only for rows affected by a `normalization_rules.version` bump; never inline in the nightly critical section).
- [ ] **Tests:** R1.1 fixture table of input→output pairs (incl. `COSTCO WHSE #0393 MADISON HEIGHMI → Costco`, `SQ *SUNRISE BAKERY → Sunrise Bakery`), each rule individually + unmatched fallthrough; backfill idempotency.

## Task 4: Evaluation harness skeleton + labels (R2.7)
- **Effort:** S
- **Dependencies:** Task 2
- **Requirements:** R2.7
- [ ] Seed `finance.eval_labels` with hand-verified `transaction → category` pairs, **including transfer/debt-payment cases**.
- [ ] `services/categorization_eval.py` skeleton — scoring/reporting plumbing that takes a classifier callable and emits per-tier/per-model accuracy + transfer-flag confusion. (Full-cascade scoring is wired once the pipeline exists — Task 13.)
- [ ] **Tests:** labels seed on `fresh_db` against seeded categories; the harness scores a single stub classifier end-to-end (proves the plumbing, not the real tiers).

## Task 5: TransferDetector tier (Feature 6)
- **Effort:** M
- **Dependencies:** Task 2, Task 3
- **Requirements:** R6.1, R6.2, R6.3, R6.4
- [ ] Tier-0 detector: counterpart-matched inter-account transfers (R6.1) and payments into known-liability accounts via `finance.accounts.account_type` (R6.2); sets `is_transfer`, short-circuits spending categorization (R6.4).
- [ ] Asymmetric gate: auto-flag only ≥ `τ_transfer`; ambiguous single-leg cases → distinct "transfer?" review item, never a silent flag (R6.3).
- [ ] Honor `is_transfer_manual` in the cascade-entry predicate and the work-set (`AND is_transfer = false`); never re-flag a hand-marked row (M6).
- [ ] One-time idempotent historical transfer-flag backfill (respects `is_transfer_manual`).
- [ ] Leave `investment_detector` / `is_investment` untouched (orthogonal, out of scope).
- [ ] **Tests:** checking→savings + CC/loan/mortgage payment flagged via DB `account_type`, excluded from spending totals, never categorized; ambiguous single-leg → queue; un-flag restores the spending total.

## Task 6: RuleEngine tier (R2.1)
- **Effort:** S
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.1
- [ ] Evaluate `finance.user_rules` by user-orderable `priority`, first-match-wins; match any combo of `merchant_key` / description regex / **amount range** / `account_id`; emit `Decision(confidence=1.0, terminal=True)` (rule-locked, R3.4).
- [ ] "Apply to existing matching" re-runs the predicate over history on demand.
- [ ] **Tests:** priority ordering / first-match; amount-range match; terminal rule not overwritten by later tiers; apply-to-existing.

## Task 7: MerchantMemory tier + LearningService (R2.2, R3)
- **Effort:** M
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.2, R3.1, R3.2
- [ ] MerchantMemory tier: deterministic lookup of `finance.merchants.category_prior` + strongest `finance.merchant_memory` signal for the `merchant_key`, consulted **before any model call** (R2.2); confidence from reinforcement + recency.
- [ ] `LearningService.record_correction` upserts/strengthens `merchant_memory` keyed on normalized `merchant_key` (R3.1), feeding the deterministic tier (R3.2).
- [ ] **Redirect the existing writer (B-1):** route `category_override.py:53-56` corrections through `LearningService.record_correction` instead of the (now-migrated-away) `category_examples` table, so chat-path corrections reinforce `merchant_memory`.
- [ ] **Migration:** drop the `0018` trigger + `fn_learn_from_manual_override`; forward-migrate `category_examples` → `merchant_memory` (re-keyed; documented down-migration). Retain `category_aliases` + `lookup_category_alias`.
- [ ] **Tests:** corrected merchant categorized on next occurrence **without an LLM call**; reinforcement raises confidence; **a correction via the chat-skill path lands in `merchant_memory`**; trigger gone, aliases intact.
- *Note:* the **gated mass-recategorization** behind "apply to all from this merchant" (R3.3) is performed in Task 11 via the Writer choke point (Task 10) + endpoint RBAC — `record_correction` here only provides the learning helper, not the bulk write.

## Task 8: EmbeddingKNN tier (R2.3)
- **Effort:** M
- **Dependencies:** Task 2, Task 3, Task 7
- **Requirements:** R2.3
- [ ] Embed normalized merchant strings once per merchant (`finance.merchants.embedding`) reusing `EmbeddingsClient` + `bge-m3`; compute category-description embeddings on `finance.categories.embedding` (cold-start).
- [ ] kNN: nearest `k` categorized merchants → majority vote, confidence = agreement fraction; `< min_neighbors` → category-description fallback → abstain; graceful Ollama-down abstain.
- [ ] Measure transaction volume; size `k` / HNSW index / `min_neighbors` from it; document the figure.
- [ ] **Tests:** majority-vote + agreement-fraction confidence; cold-start category-desc fallback; abstain when Ollama down; index applies on fresh_db.

## Task 9: LLMFallback tier (R2.4) + failure handling
- **Effort:** S
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.4, R5.5
- [ ] LLM tier over residue only, via `resolve_role("categorizer")` (no literal model ID); reuse the prompt scaffolding minus the hardcoded rules block; map score to [0,1].
- [ ] Parse-failure / Ollama-down / Batch-timeout → **abstain → queue, never "Other"**; delete the `_parse_response` Other-fallback (`categorizer.py:213-214`).
- [ ] **Tests:** residue-only invocation; parse-failure and Ollama-down defer to queue (reuse `FakeEmbeddingsClient(fail=True)` pattern); assert the Other-fallback is gone.

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
