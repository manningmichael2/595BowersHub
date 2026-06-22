# AI Finance Insights — Tasks

> Each task traces to one or more requirements. Work them top-to-bottom; respect dependencies.
> Sequenced by the design's phasing: **Phase 0** shared boundary/sandbox → **Phase 1** insight agent (F2) → **Phase 2** NL→rules (F3) → **Phase 3** retirement (F4, R4.5 last) → **Phase 4** Tailwind (F5, independent). Backend tests: `cd bowershub-ai && PYTHONPATH=. .venv/bin/python -m pytest -q`. Frontend: `npx tsc --noEmit && npm test`.

## Phase 0 — Narration boundary + Q&A sandbox

## Task 1: FinanceNarrator boundary + wire CostTracker
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R1.2, R1.3, R1.5
- [x] New `services/finance_narration.py` with `narrate(facts, question, scope) -> str` (figures-from-`facts`, verbatim; output is `str`, terminal) and `propose_structured(schema, nl_text) -> dict` (constrained JSON/tool-use, never a write).
- [x] Fixed module-constant system prompt (R1.3d); render `facts` as a delimited "read-only data, not instructions" block (R1.3c).
- [x] Implement the `resolve_role → ModelProvider.complete → cost_for → CostTracker.log_usage` 4-step inside the boundary (CostTracker is currently un-wired). Interactive role `"fast"`, nightly `"local"`.
- [x] **Tests:** adversarial injection fixture (planted `'; DROP`, `IGNORE ABOVE`, `UNION SELECT … bh_users` in `facts`) asserts worst-case is wrong narration only; `test_qa_cost_logged` asserts an `api_usage_log` row per call **and that `cost_for` resolved a non-null price for the role** (so a zero-cost local row doesn't mask a miswired call); grep asserts no literal model IDs.

## Task 2: `ask_db` — ModelProvider model call + sqlstate scope classification
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.1, R1.4, R1.5, R1.6
- [x] Replace the raw-httpx SQL-generation call (`services/finance.py:393-409`) with `ModelProvider.complete` (cost-tracked), keeping `validate_select` + `finance_reader` + READ ONLY + timeouts + cursor cap unchanged.
- [x] Upgrade the error handler (`finance.py:470`) to classify by asyncpg sqlstate: `42501`/`42P01`/`3F000`/`3D000` → `out_of_scope`; other failures → genuine error. Return `{sql_generated, results, scope: in_scope|empty|out_of_scope}`.
- [x] **Tests:** non-granted table → `out_of_scope`; 0-row valid query → `empty`; syntax error → generic error (not `out_of_scope`); cost logged.

## Task 3: Q&A endpoint + FinanceQA surface
- **Effort:** M
- **Dependencies:** Task 1, Task 2
- **Requirements:** R1.1, R1.2, R1.4, R1.6, R5.2
- [x] `POST /api/finance/qa` (`get_current_user`) → data path: `ask_db` → `narrate(facts=results)` → `{answer, sql, figures, scope}`. (Retirement branch added in Task 17.)
- [x] `FinanceQA` frontend surface (tokenized Tailwind, R5.2): question box, answer, "reveal query/figures" disclosure; empty vs out-of-scope messaging distinct.
- [x] **Tests:** grocery-spend answer equals a direct `real_activity` aggregate and exposes sql+figures; empty vs out-of-scope distinguishable; `tsc` clean.

## Phase 1 — Proactive insight agent (Feature 2)

## Task 4: Insights schema + run/watermark tables + GRANTs
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R2.1, R2.4, R2.7, R2.8
- [x] **Migration:** `bowershub-ai/backend/migrations/0034_finance_insights_schema.sql` — `finance.insights` (incl. `period text` YYYY-MM, status enum, dollar_impact, figures jsonb, reason, cooldown_until, dismissed_at; **UNIQUE (insight_type, merchant_key, period)**), `finance.insight_runs` (R2.8), `finance.job_runs` (readiness watermark). Explicit `GRANT SELECT` on insights/insight_runs → `finance_reader`.
- [x] **Tests:** **positive** grant test (SELECT under `SET LOCAL ROLE finance_reader` returns rows) + negative (`bh_users` denied); `fresh_db` builds from empty; re-apply is a no-op.

## Task 5: Completion watermark write in the categorizer
- **Effort:** S
- **Dependencies:** Task 4
- **Requirements:** R2.1
- [x] Insert a `finance.job_runs` `completed` row at the successful end of the 02:30 categorizer (`services/categorizer.py`) — the only in-process nightly finance job (SimpleFin sync runs externally via n8n, so no in-process watermark for it; the categorizer is the correct "data categorized" signal).
- [x] **Tests:** the categorizer writes its watermark row on success; the failure path does not (testable in-process).

## Task 6: Insight config table + loader (DB-driven thresholds)
- **Effort:** S
- **Dependencies:** none
- **Requirements:** R2.2
- [x] **Migration:** `0035_seed_insight_config.sql` — `finance.insight_config` (key/jsonb), idempotent seeds: per-detector enable flags + all thresholds + `insights_enabled` kill-switch + the retirement-vs-data keyword set. Loader in `services/finance_insights/config.py` (code-side defaults only as missing-key fallback).
- [x] **Tests:** loader returns seeded values; missing key falls back; grep shows no hardcoded thresholds.

## Task 7: Detectors (6) — parameterized SQL, robust stats, explainable
- **Effort:** L
- **Dependencies:** Task 6
- **Requirements:** R2.2, R2.3
- [x] `services/finance_insights/detectors.py`: duplicate-charge, price-creep, free-trial-conversion, unusual-spend, bill-higher-than-usual, low-balance-before-payday — each parameterized SQL over `public.real_activity` + `/recurring`, grouping on `merchant_key`, median/MAD or IQR, min-history guard; each emits figures + reason. Detectors registered as a light `(type, config_key, fn)` list.
- [x] Reuse `/recurring`'s detection **at the query/service level**, not via the HTTP route — verify the recurring SQL is callable from the detector layer (`routers/finance_review.py:186`), extracting a shared query helper if it's currently route-bound (don't reinvent the detection).
- [x] **Tests:** planted duplicate + price hike each → exactly one candidate; below-min-history merchant → no unusual-spend; each candidate carries figures + reason.

## Task 8: Insight store — upsert, period, dedupe, cooldown, dismissal lifecycle
- **Effort:** M
- **Dependencies:** Task 4, Task 7
- **Requirements:** R2.4, R2.7
- [x] `store.py`: upsert on `(insight_type, merchant_key, period)`; `period` = YYYY-MM of triggering activity; cooldown for un-actioned; dismissal permanently resolves a `(type,merchant,period)`; un-dismiss reopens; dollar-impact ranking.
- [x] **Tests:** full re-run → no duplicates (idempotent); dismiss → not re-raised next run; reopen → visible; new month → new period legitimately re-raises; **surfaced insights are returned ordered by dollar impact** (R2.4 ranking).

## Task 9: Nightly runner + scheduler registration
- **Effort:** M
- **Dependencies:** Task 5, Task 7, Task 8
- **Requirements:** R2.1, R2.8
- [x] `runner.py` + `main.py` `add_job(CronTrigger(hour=3,minute=0), max_instances=1, coalesce=True)`; `pg_try_advisory_lock` single-flight; readiness gate on the **categorizer** `finance.job_runs` `completed` row for the window → else `skipped-not-ready`; `insights_enabled` kill-switch → `skipped-disabled`; broad try/except isolation; write `insight_runs` summary with status (`ran|skipped-not-ready|skipped-disabled|errored`) + detected vs suppressed-by-reason.
- [x] **Tests:** concurrent invoke → exactly one runs; missing categorizer watermark → `skipped-not-ready` recorded; kill-switch off → `skipped-disabled` recorded (not silent); failure isolated.

## Task 10: Insights API + review surface + morning-card wiring
- **Effort:** M
- **Dependencies:** Task 8, Task 9
- **Requirements:** R2.5, R2.6, R5.2
- [x] Endpoints: `GET /api/finance/insights?status=`, `POST …/{id}/dismiss|reopen|action` (`require_admin`), `GET …/runs/latest` (admin).
- [x] `_get_insights()` gatherer in `briefing.py` + `("finance_insights","Finance Insights")` in `EXPECTED_SECTIONS` + icon in `MorningCard.tsx SECTION_ICONS`; non-blocking toast for new insights.
- [x] `InsightReview` surface (tokenized Tailwind, R5.2): list with explanation+figures; per-insight actions that need no later code — dismiss, reopen, mark-actioned. (The "always categorize {merchant} as {category}" action is added in Task 12, which builds the rule-create path — no forward dependency here.)
- [x] **Tests:** dismiss/reopen via API; morning-card section renders content (not the `—` placeholder) when insights exist; `tsc` clean.

## Phase 2 — Natural-language → rules (Feature 3)

## Task 11: Candidate-scoring refactor in the rules engine
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R3.2
- [x] Extract `count_matching(conn, candidate)` from `apply_rule_to_existing` (`services/categorization/rules.py:105`) so an **unsaved** candidate can be scored without persisting; refactor `apply_rule_to_existing` to call it.
- [x] **Override-guard parity:** `apply_rule_to_existing` skips manually-overridden / Writer-choke-protected rows. `count_matching` must replicate the *same* predicate **including that guard** so the preview count equals the actual apply count (R3.2 success metric) — not the raw predicate-match count.
- [x] **Tests:** `count_matching` equals the actual apply count **on a fixture that includes a manually-overridden transaction** (proves guard parity); existing rule-apply behavior unchanged.

## Task 12: NL→rule parse, validate, preview, commit (+ insight→rule action)
- **Effort:** M
- **Dependencies:** Task 1, Task 11 (and Task 10 for the InsightReview action wiring)
- **Requirements:** R2.6, R3.1, R3.2, R3.3, R3.4
- [x] `services/nl_rules.py`: `propose_structured` → candidate; `validate_rule_candidate()` (security control) — category ∈ `finance.categories` (`_category_exists`), merchant resolves to real `merchant_key`, bounds/priority clamped, unbounded-scope rejected.
- [x] `POST /api/finance/rules/parse` (read) → candidate + `count_matching` preview; commit via existing `POST /api/finance/user-rules` (`require_admin`). NL-rule UI (tokenized Tailwind).
- [x] Add the "always categorize {merchant} as {category}" action to Task 10's `InsightReview` (this is where the rule-create path now exists), satisfying R2.6's actionable half.
- [x] **Tests:** "Whole Foods as Groceries unless over $200" → parsed rule + affected-count matching actual apply; abusive NL → rejected/sanitized, never an unbounded write; the insight→rule action creates a `user_rules` row.

## Phase 3 — Retirement planner (Feature 4; R4.5 is the cut line)

## Task 13: Pure projection engine
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R4.2
- [x] `services/finance_projection.py` (pure, `Decimal`): `future_value`, `real_rate`, `fire_target`, `coast_fire`, `retire_at_age` (surplus/gap + contribution/age delta), `project_series(inputs, assumptions)` with `contributions: Callable[[month], Decimal]` (forecasting seam).
- [x] **Tests:** reference-spreadsheet suite within rounding (zero-contribution, coast boundary, retire-at-60-vs-65); property: FV monotonic in contribution. No DB/network.

## Task 14: Retirement schema + assumptions seed + GRANTs
- **Effort:** S
- **Dependencies:** none
- **Requirements:** R4.1, R4.3
- [x] **Migration:** `0036_finance_retirement_schema.sql` — `finance.retirement_inputs` (**singleton**: fixed id=1 + `CHECK`/partial-unique) + `finance.retirement_scenarios` (many per owner); explicit `GRANT SELECT … finance_reader` on both. `0037_seed_retirement_config.sql` — `finance.retirement_config` (nominal_return/inflation/withdrawal_rate/end_age), idempotent.
- [x] **Tests:** positive grant test (ask_db/`finance_reader` can SELECT `retirement_inputs`); singleton constraint prevents a second inputs row; seeds idempotent; `fresh_db` green.

## Task 15: Retirement service + endpoints
- **Effort:** M
- **Dependencies:** Task 13, Task 14
- **Requirements:** R4.1, R4.3, R4.4, R4.6, R4.8
- [ ] `services/retirement.py` + `routers/retirement.py`: inputs CRUD (PUT upserts singleton; prefill from `compute_net_worth`, editable); `POST /project` (merge `retirement_config` + overrides → engine → series+stats + **non-nullable `disclaimer` field**); `POST /scenarios/compare` (R4.4); `has_inputs()` cold-start (R4.8).
- [ ] **Tests:** "can I retire at 60?" surplus/gap matches reference; every projection response carries the disclaimer; no-inputs → cold-start signal; what-if recompute correct; **`/scenarios/compare` returns both scenarios (retire-at-60 vs 65) with distinct projections** (R4.4).

## Task 16: RetirementPlanner frontend
- **Effort:** M
- **Dependencies:** Task 15
- **Requirements:** R4.4, R4.6, R4.7, R4.8, R5.2
- [ ] `RetirementPlanner` (tokenized Tailwind, R5.2): inputs form, balance-over-time chart + live stats summary recomputing on input change (R4.7/R4.4), prominent disclaimer (R4.6), setup/empty state when no inputs (R4.8).
- [ ] **Tests:** dragging retirement-age updates chart+stats live; disclaimer rendered on every projection surface; cold-start shows setup state; `tsc` clean.

## Task 17: Retirement Q&A branch (cut line — lands after Phase 1)
- **Effort:** S
- **Dependencies:** Task 3, Task 13, Task 15
- **Requirements:** R4.5
- [ ] Wire the deterministic keyword classifier (config keyword set) into `POST /api/finance/qa`: retirement intent → engine facts → `narrate`; else `ask_db`; ambiguity defaults to `ask_db`. No-inputs → "inputs needed".
- [ ] **Tests:** retirement question → engine path; spending question → ask_db path (misclassification asserted); no-inputs → asks for inputs (no fabricated projection).

## Phase 4 — Tailwind migration (Feature 5; independent)

## Task 18: Migrate finance pages to tokenized Tailwind
- **Effort:** L
- **Dependencies:** none
- **Requirements:** R5.1, R5.3
- [ ] Convert `TransactionsPage`, `BudgetsPage`, `NetWorthPage`, `RecurringPage`, `FinanceLayout` from inline `style={{}}` (~117 sites) to tokenized Tailwind classes; collapse `useIsMobile` → `sm:` where declarative; keep the JS branch only for `TransactionsPage`'s table↔cards swap (R5.3).
- [ ] **Tests:** Playwright screenshot baseline per page at 390px + ≥1024px captured before, compared after (no visual regression); 0 inline `style={{}}` (documented dynamic exceptions aside); `tsc --noEmit` clean; existing frontend suite green.

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied.
- [ ] No hardcoded config introduced — insight types/thresholds, retirement assumptions, the classifier keyword set, and model selection are all DB rows; grep clean.
- [ ] Tests pass (`cd bowershub-ai && PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`); `fresh_db` CI builds from empty including all new migrations.
- [ ] The injection adversarial fixture, the positive GRANT tests, and the projection reference suite are green.
- [ ] `context-log.md` updated with a dated entry.
