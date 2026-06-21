# Finance Budgets & Splits — Requirements

## Overview

The final north-star finance slice (`project-review.md` §8.4 items 3–4), deferred from the categorization and accounting specs because **splits change the categorization data model** and **budgets read the spending rollups** those specs established. Two capabilities:

- **Transaction splits** — divide one transaction across multiple categories (e.g. a $120 Target receipt = $80 Groceries + $40 Household), so category spend is accurate.
- **Budgets** — per-category monthly targets with actual-vs-budget and "left to spend," building on the **existing live budget infrastructure** (`finance.budgets` + the hourly `check_budgets` alert loop).

**Settled by grounding research (do not relitigate):**
- **Splits = the child-subtransaction model** (Actual Budget / Monarch / Lunch Money consensus), reusing the `transfer_id` self-FK idiom from `finance-accounting`: children are real `finance.transactions` rows with their own `category_id`/`amount` + a `parent_id`; the parent becomes a container (`category_id=NULL`, `is_split=true`). Not a separate allocation table, not JSON — child rows mean the existing categorizer/rules/merchant-memory pipeline works on children unchanged, and ask-db/`finance_reader` need no new grants.
- **Budgets reuse `finance.budgets`** (already per-category-per-month, UNIQUE `(category_id, month)`, with a live `check_budgets` worker). The work is a CRUD API + an allocation-aware actual + UI — not a new table.
- **One allocation-aware rollup serves everything** (category breakdown, budget actual, alerts): exclude `is_split=true` parents; children already carry their own `category_id`.

**Explicitly out of scope (defer):** budget rollover/carryover, income budgeting, envelope/zero-based mechanics, goals, flexible/custom periods, splitting a transfer (and a split child being a transfer leg), and any taxonomy change. Double-entry remains rejected.

## Feature 1: Transaction Splits

### R1.1 — Split data model (child subtransactions)
A transaction can be split into ≥2 child rows. Add `finance.transactions.parent_id varchar(128) REFERENCES finance.transactions(id) ON DELETE CASCADE` and `is_split boolean NOT NULL DEFAULT false`. Children are normal transaction rows (own `category_id`, `amount`, `description`) with `parent_id` set; the parent carries `is_split=true`. **Children inherit the parent's `posted_date` and `account_id`** (so month/account rollups place them correctly) and are `source='split'`.

### R1.2 — Sum-to-total integrity
A split's child amounts must sum exactly to the parent's `amount` and share its sign. Enforced **server-side within the write transaction** (validate `SUM(children.amount) = parent.amount`, reject otherwise) — not a DB trigger (proportionate at this scale; mirrors how Actual enforces it). The parent `amount` is never changed by splitting (bank sync / reconciliation / net worth key off it).

### R1.3 — Parent becomes a container
On split, the parent's `category_id` is set NULL and `is_split=true`; the parent is excluded from category spend (its children are counted instead). `user_category_override` is set so the cascade never re-touches it.

### R1.4 — Split / edit / unsplit API
Admin endpoints to create a split (parent + N child allocations), edit allocations (re-validating the sum), and **unsplit** (delete children, restore the parent as a normal categorizable row). Reversible.

### R1.5 — Auto-categorizer skips split parents; children sticky-or-eligible
A split parent is protected from the cascade primarily by `user_category_override=true` (R1.3), which the Writer already honors (`pipeline.py:114`); add an `AND is_split = false` guard as defense-in-depth so a parent is never categorized or mis-provenanced. Child rows created **with** a user-chosen category are sticky (`user_category_override=true`); children created **without** one are eligible for the normal cascade.

### R1.6 — Transfer/split boundary (v1)
A transfer transaction (`is_transfer=true` or linked via `transfer_id`) cannot be split, and a split child cannot be made a transfer leg. The split and transfer-link writers reject the cross-case. (Interplay deferred.)

### R1.7 — Split UI
A transaction row shows a "Split" badge + total and expands to its child allocations (category + amount each), with an editor that enforces the running sum equals the total before save. Lives in the Finance Review surface; reuses the typed-client pattern.

### R1.8 — Deletion/edit integrity
Deleting a parent cascades to its children (`ON DELETE CASCADE`). Editing the parent amount is blocked while split (or forces a re-balance). The `transfer_id` partial-unique + transfer invariants from `finance-accounting` are unaffected.

## Feature 2: Allocation-aware rollups

### R2.1 — Single category-spend source of truth + the sum-vs-list rule
Introduce one allocation-aware category-spend source (a `public`/`finance` view or a shared query/function) that all category rollups use: counts split **children** (which carry `category_id`) and **excludes `is_split=true` parents**, so no transaction is double-counted. Rather than editing 8 queries independently, migrate them to this one source.

**The sum-vs-list rule (applies beyond category rollups):** since `parent.amount = SUM(children.amount)`, any query that **sums `amount`** (category *or* account/total level) must use **`is_split = false`** (counts children + normal txns, skips parents) to avoid double-counting; any query that **lists/displays** transactions must use **`parent_id IS NULL`** (shows normal txns + parents, with children nested under their parent). Auditing both classes of query — not just category sums — is in scope.

### R2.2 — Canonical "spending" definition
Resolve the existing inconsistency (`services/finance.py` excludes only `is_transfer`; `routers/dashboard.py` also excludes `is_investment`). The canonical real-spending filter is **`is_transfer = false AND is_investment = false`**, applied uniformly by the source in R2.1 and by budget "actual."

### R2.3 — Migrate all rollups to the allocation-aware source
Every category-sum rollup is updated to the R2.1 source so splits and the canonical filter take effect together: `finance.py` `spending_summary`/income; `dashboard.py` MTD spend/income, top-categories, prev-month; `alerts.py` `check_budgets`; `briefing.py` weekly budget status. (8 queries / 4 files + 2 budget readers, per research.)

### R2.4 — Net worth unaffected
Net worth (`services/accounting/networth.py`) sums `balance_snapshots`, never `category_id`, so it is orthogonal to splits — a test asserts split transactions don't change net worth.

## Feature 3: Budgets

### R3.1 — Reuse finance.budgets; one budget store
Per-category monthly budgets use the existing `finance.budgets (category_id, month, limit_amount)` (UNIQUE `(category_id, month)`). The redundant `finance.categories.budget_monthly` is **deprecated** — documented as legacy and not read; `finance.budgets` is the single source. (Optionally repurpose `budget_monthly` as a default-template only, otherwise leave unread.)

### R3.2 — Budget CRUD API
Admin endpoints to list budgets for a month and upsert a category's `limit_amount` for a month (`require_admin`), parameterized SQL, typed Pydantic models.

### R3.3 — Budget-vs-actual endpoint
A read endpoint returning, per category for a month: budgeted `limit_amount`, **actual** (from the R2.1 allocation-aware source, calendar-month boundary via `date_trunc('month', …)`), and remaining. Uncategorized + over-budget surfaced.

### R3.4 — Budget UI
A budgets view (Budgeted / Spent / Remaining per category) reusing the existing `frontend/src/lib/budget.ts` ok/warn/over tone helper (already property-tested) for the progress coloring; typed client. A dashboard budget-progress widget may reuse the same data.

### R3.5 — DB-driven alert thresholds; allocation-aware alerts
The hardcoded 80%/100% thresholds in `alerts.py:63,75` move to DB-driven config (NO-HARDCODING). `check_budgets` is updated to the R2.1 allocation-aware actual so split spending counts toward budgets and the live Pushover loop stays correct.

### R3.6 — Explicit budget non-goals (defer)
Rollover/carryover, income budgeting, envelope/zero-based, goals, and flexible/custom periods are out of scope; if added later they are DB-config rows (e.g. a per-category rollover flag) needing no schema change. Calendar-month periods only.

## Feature 4: Schema, config & rollout (cross-cutting)

### R4.1 — Migrator-owned DDL + read view
New columns/objects ship in forward-only migrations authored under `bowershub_migrator` (C7), starting at `0031`. The `public.transactions` view is recreated under the migrator to expose `parent_id`/`is_split` with `GRANT SELECT … finance_reader` re-applied (mirrors `0029:70-102`). Seed/idempotency migrations dry-run (BEGIN…ROLLBACK) against the **populated** prod DB (0023 lesson).

### R4.2 — DB-driven budget config
Budget tunables (alert thresholds; any future rollover toggle) are rows (extend `finance.accounting_config` or a `budgets`-scoped config), never code constants.

### R4.3 — Additive, reversible rollout
Splits are additive (no transaction is split until a user splits it) and reversible (unsplit). The rollup migration (R2.3) is a **no-op until a split exists** (no parent has `is_split=true`), so it carries no behavior-change risk for existing data — verified by a test that rollups are unchanged on un-split data.

## Acceptance Criteria

- [ ] A $120 transaction split into $80 Groceries + $40 Household: parent shows `is_split=true`, `category_id=NULL`; two children sum to −$120; category spend shows $80 + $40 (not $120 on one), and the parent isn't counted.
- [ ] A split with children that don't sum to the parent amount is rejected; unsplit restores a normal categorizable transaction.
- [ ] The auto-categorizer never sets a category on a split parent.
- [ ] Splitting a transfer is rejected; a split child can't become a transfer leg.
- [ ] Every category rollup (spending summary, dashboard MTD/top/prev, weekly briefing, `check_budgets`) counts split children and excludes parents, using the canonical `is_transfer=false AND is_investment=false` filter.
- [ ] Net worth — and any account-level `amount` sum — is identical before/after splitting a transaction (no double-count); the transaction list shows the parent once (children nested), not three rows.
- [ ] Budget set for a category/month is returned by the budget-vs-actual endpoint with a correct allocation-aware actual + remaining; the Pushover alert fires off the same number; 80/100 thresholds come from config.
- [ ] `fresh_db` builds from empty with the new columns + recreated view; `0031` seed dry-runs clean on populated prod.

## Non-Functional Requirements

- **No hardcoding:** budget limits (rows already), alert thresholds, any rollover toggle, and the taxonomy are DB-driven — never constants.
- **Data safety:** parameterized SQL only (`_quote_ident` for identifiers); forward-only migrations (`0031`+), migrator-owned; seed/idempotency dry-run on populated prod; additive nullable columns + `IF NOT EXISTS`.
- **Integrity:** the split sum-to-total invariant and the transaction-`amount`/transfer-leg sum invariants from `finance-accounting` must both continue to hold; no rollup double-counts.
- **Security / RBAC:** reads via `get_current_user`, mutations (split/unsplit, budget upsert) via `require_admin`; mirrors `finance_review.py`/`finance_accounting.py`.
- **Performance / scale:** deterministic SQL, **no LLM** (splits/budgets are arithmetic). 414 txns / ~16 accounts / single household — child rows + monthly budgets are trivial volume.

## Constraints & Assumptions

- Reuse, don't rebuild: `finance.budgets` + `alerts.py check_budgets` (live, hourly), the `transfer_id` self-FK idiom, the `is_transfer`/`is_investment` exclusions, the `finance_review.py`/`finance_accounting.py` router patterns, `services/accounting/config.py` config pattern, `frontend/src/lib/budget.ts`.
- The 25-category taxonomy is fixed; budgets target those categories.
- Single-entry + `transfer_id` model; splits fit it (child rows), not double-entry.

## Dependencies

- finance-categorization (shipped) — the cascade Writer that must skip split parents.
- finance-accounting (shipped) — `transfer_id`/`is_transfer` (split/transfer boundary), `accounting_config` (config pattern), net-worth (orthogonality test).
- The live `check_budgets` worker (`alerts.py`, `main.py:204`) + `finance.budgets`/`alert_log` tables.

## Success Metrics

- **No double-counting:** category spend over a period with splits equals the sum of all child allocations + un-split transactions; parents contribute 0.
- **Canonical spending:** all rollups return identical totals for the same period (the finance.py vs dashboard.py discrepancy is gone).
- **Budgets correct:** budget-vs-actual and the Pushover alert agree on "actual" for every category, allocation-aware.
- **Reproducibility:** `fresh_db` CI build passes with the new schema (C2); rollups unchanged on un-split data.
