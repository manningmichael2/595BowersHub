# Finance Budgets & Splits — Tasks

> **STATUS: COMPLETE (2026-06-21).** All 8 tasks implemented, merged, and deployed. Validator 21/21. See context-log 2026-06-21.

> Each task traces to one or more requirements. Work top-to-bottom; respect dependencies. Each task is verified against its Definition of Done before the next.

## Task 1: Schema + config migrations (0031, 0032)
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R1.1, R1.8, R2.1, R2.2, R4.1, R4.2
- [ ] `0031_finance_splits_schema.sql` (migrator-owned, additive): `finance.transactions += parent_id varchar(128) REFERENCES finance.transactions(id) ON DELETE CASCADE` + `is_split boolean NOT NULL DEFAULT false`; index on `parent_id`.
- [ ] Recreate `public.transactions` view to expose `parent_id`, `is_split` under the migrator + re-`GRANT SELECT … finance_reader` (mirror `0029:70-102`).
- [ ] Create `public.real_activity` view = `WHERE is_split=false AND is_transfer=false AND is_investment=false` (bakes splits + canonical filter, R2.1/R2.2) + `GRANT SELECT … finance_reader`.
- [ ] `0032_seed_budget_config.sql` (idempotent): `budget_warn_ratio=0.8`, `budget_over_ratio=1.0` into `finance.accounting_config`; comment `categories.budget_monthly` deprecated.
- [ ] **Migration:** `bowershub-ai/backend/migrations/0031_*.sql`, `0032_*.sql`.
- [ ] **Tests:** applies from empty `fresh_db`; views expose new columns + grants; `parent_id` FK is `ON DELETE CASCADE`; config seeded; `0031`/`0032` dry-run (BEGIN…ROLLBACK) clean on populated prod.

## Task 2: Splits service
- **Effort:** L
- **Dependencies:** Task 1
- **Requirements:** R1.2, R1.3, R1.4, R1.5, R1.6
- [ ] `services/splits.py`: `create_split` — validate `SUM(children)=parent.amount` + same sign in one tx (R1.2), reject otherwise; parent → `category_id=NULL, is_split=true, user_category_override=true` (R1.3); insert children inheriting `posted_date`/`account_id`, `source='split'`, sticky override iff categorized (R1.5).
- [ ] `edit_split` (re-validate sum) + `unsplit` (delete children, clear `is_split`, restore categorizable parent) (R1.4).
- [ ] Reject splitting a transfer / a split child becoming a transfer leg (R1.6).
- [ ] Add `AND is_split = false` guard to the categorization Writer (`pipeline.py:114`) as defense-in-depth (R1.5).
- [ ] **Tests:** sum-to-total accept/reject; parent container state; children inherit date/account; unsplit restores; transfer/split rejection; Writer skips split parent.

## Task 3: Allocation-aware rollups
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R2.3, R2.4, R4.3
- [ ] Repoint every category/amount rollup at `public.real_activity`: `finance.py` spending_summary/income (`:196-228`), `dashboard.py` MTD/top/prev (`:382-431`), `briefing.py` weekly (`:285-303`). Apply the sum-vs-list rule (sums → `real_activity`; lists → `parent_id IS NULL`).
- [ ] **Tests:** a split txn's children count per category, parent excluded; account-level `amount` sum + net worth unchanged after split (R2.4); all rollups agree on totals (canonical filter, R2.2); rollups unchanged on un-split data (no-op-until-split, R4.3).

## Task 4: Budgets service
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R3.1, R3.3, R3.5, R3.6
- [ ] `services/budgets.py`: `budget_vs_actual(conn, month)` — `finance.budgets` ⟕ actual from `public.real_activity` (`date_trunc('month')`), budgeted/spent/remaining per category (R3.3); `finance.budgets` is the single store, `categories.budget_monthly` unread (R3.1).
- [ ] Update `alerts.py check_budgets` to the allocation-aware actual + DB-driven `budget_warn_ratio`/`budget_over_ratio` from config (replaces hardcoded 80/100) (R3.5).
- [ ] Document deferred non-goals (rollover/income/envelope/goals/flexible periods) (R3.6).
- [ ] **Tests:** budget_vs_actual allocation-aware (split children count toward their budgets); check_budgets reads config thresholds + new actual; rollover/etc. absent by design.

## Task 5: Split API endpoints
- **Effort:** S
- **Dependencies:** Task 2
- **Requirements:** R1.4
- [ ] `routers/finance_review.py` (+): `POST /transactions/{id}/split` `{allocations}`, `POST /transactions/{id}/unsplit`, `GET /transactions/{id}/allocations` — `require_admin` writes, Pydantic, DB-down → 503.
- [ ] **Tests:** split/unsplit endpoint RBAC (member denied); sum-mismatch → 400; allocations round-trip.

## Task 6: Budget API endpoints
- **Effort:** S
- **Dependencies:** Task 4
- **Requirements:** R3.2, R3.3
- [ ] `routers/finance_budgets.py` (new, registered in `main.py`): `GET /budgets?month=`, `PUT /budgets` `{category_id,month,limit}` (require_admin), `GET /budgets/actual?month=` (reads `budget_vs_actual`).
- [ ] **Tests:** upsert + list round-trip; actual endpoint shape; RBAC on the write.

## Task 7: Frontend — split editor
- **Effort:** M
- **Dependencies:** Task 5
- **Requirements:** R1.7
- [ ] `financeReview.ts` (+ split/unsplit/allocations) + a split editor in `FinanceReviewPage.tsx`: expand a row into N allocation lines with a running-sum-equals-total guard before save; "Split" badge on split parents.
- [ ] **Tests:** sum-guard blocks save until balanced; calls split API; `tsc --noEmit` clean.

## Task 8: Frontend — budgets page
- **Effort:** M
- **Dependencies:** Task 6
- **Requirements:** R3.4
- [ ] `financeBudgets.ts` typed client + `BudgetsPage.tsx` (`/finance/budgets`, lazy, 🎯 nav link): Budgeted/Spent/Remaining per category, reusing `frontend/src/lib/budget.ts` ok/warn/over tone; edit a category's limit.
- [ ] **Tests:** renders budget rows + tone; edit calls upsert; `tsc --noEmit` clean.

## Definition of Done
- [ ] All tasks complete; every requirement in `requirements.md` satisfied (validator exit 0).
- [ ] No hardcoded config (budget thresholds + limits are DB rows; taxonomy untouched).
- [ ] All new `finance.*` DDL migrator-owned; `public.transactions`/`real_activity` views updated + granted; `fresh_db` builds from empty (C2).
- [ ] No rollup double-counts splits; net worth + account sums unchanged by splitting; all rollups agree on totals.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`); `0031`/`0032` dry-run clean on populated prod.
- [ ] `context-log.md` updated with a dated entry.
