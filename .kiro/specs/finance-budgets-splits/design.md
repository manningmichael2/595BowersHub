# Finance Budgets & Splits — Design

> Satisfies requirements in `requirements.md`. Reference IDs inline (e.g. "satisfies R2.1").

## Design tournament (how this was chosen)

- **Minimal-change** — add `parent_id`/`is_split`, inline-edit the ~8 rollup queries to add `is_split=false`, CRUD straight on `finance.budgets`, no new module. *Won:* reuse `finance.budgets` + the live `alerts.py check_budgets` loop instead of rebuilding budgets. *Lost:* 8 scattered `is_split` edits will drift and miss one → centralize in a view.
- **Ideal-architecture** — a `finance.real_activity` view as the single allocation-aware source + a `services/budgets/` package + a budgets router. *Won:* the view (one place to get the split/canonical-filter rule right). *Lost:* a full package is overkill for arithmetic — single modules (`services/splits.py`, `services/budgets.py`) suffice.
- **Risk-first** — additive nullable columns; integrity enforced in the write transaction; the rollup change is a **no-op until a split exists**; no runtime feature-gate (splits are inherently additive/reversible — unsplit). *Won:* all of it; a gate would be over-engineering (consistent with the accounting spec's call).

**Synthesis:** a **`public.real_activity` view** as the single allocation-aware rollup source (ideal+risk) + reuse `finance.budgets`/`alerts.py` (minimal) + child-subtransaction splits with in-transaction integrity (risk), via two small service modules. No feature-gate.

## Architecture Overview

```
PWA (React)                          FastAPI                                 Postgres (finance.*)
─────────────                        ───────────────────────                 ─────────────────────
FinanceReviewPage (split editor) ─> routers/finance_review.py (+split)  ─> services/splits.py
BudgetsPage / widget             ─> routers/finance_budgets.py          ─> services/budgets.py
  financeReview.ts / financeBudgets.ts (typed)                              (read finance.budgets + accounting_config)

ALL category/amount rollups ─────────────────────────────────────────────> public.real_activity  (is_split=false grain)
  finance.py · dashboard.py · alerts.check_budgets · briefing.py                │
nightly check_budgets (hourly, alerts.py) ─────────────────────────────────────┘ (now allocation-aware)
```

**New:** `parent_id`/`is_split` columns, the `public.real_activity` view, `services/splits.py` + `services/budgets.py`, split endpoints on `finance_review.py`, a `finance_budgets.py` router, a Budgets page + split editor. **Reused:** `finance.budgets` + `alert_log` + `alerts.py:check_budgets` (`main.py:204`), the `transfer_id` self-FK idiom (`0029`), `is_transfer`/`is_investment` exclusions, `accounting_config` config pattern, `finance_review.py`/`finance_accounting.py` router patterns, `frontend/src/lib/budget.ts` tone helper.

## Components

### Schema (migrations)
- **`0031_finance_splits_schema.sql`** (migrator-owned, additive): `finance.transactions += parent_id varchar(128) REFERENCES finance.transactions(id) ON DELETE CASCADE` (R1.1/R1.8) + `is_split boolean NOT NULL DEFAULT false`; index on `parent_id`. Recreate `public.transactions` view to expose `parent_id`, `is_split` under the migrator + re-`GRANT finance_reader` (R4.1, mirrors `0029:70-102`). Create **`public.real_activity`** view = `SELECT id, account_id, category_id, posted_date, amount FROM finance.transactions WHERE is_split = false AND is_transfer = false AND is_investment = false` + `GRANT SELECT … finance_reader` (R2.1+R2.2). It **bakes all three exclusions in one place**: `is_split=false` (children included, parents excluded — splits) AND the canonical `is_transfer=false AND is_investment=false` (resolves the finance.py-vs-dashboard.py inconsistency). Both spend (`amount<0`) and income (`amount>0`) read this one view, differing only by sign — so no caller can forget an exclusion.
- **`0032_seed_budget_config.sql`** (idempotent seed): budget alert thresholds into `finance.accounting_config` (`budget_warn_ratio=0.8`, `budget_over_ratio=1.0`) (R3.5/R4.2). `finance.categories.budget_monthly` documented deprecated (no DDL; left unread) (R3.1). Dry-run on populated prod (0023 lesson).

### services/splits.py
- **Responsibility:** `create_split(conn, txn_id, allocations)` — validate `SUM(allocations.amount) == parent.amount` and same sign **in one transaction** (R1.2), reject otherwise; set parent `category_id=NULL, is_split=true, user_category_override=true` (R1.3); insert children inheriting parent `posted_date`/`account_id`, `source='split'`, sticky override iff a category was chosen (R1.1/R1.5). `edit_split` (re-validate sum), `unsplit(conn, txn_id)` (delete children, clear `is_split`, restore categorizable parent) (R1.4). Rejects splitting a transfer / making a child a transfer leg (R1.6).
- **Reuses:** the `_quote_ident`-free parameterized style; the transfer-linker's "guarded write in one tx" idiom.

### services/budgets.py
- **Responsibility:** `list_budgets(conn, month)`, `upsert_budget(conn, category_id, month, limit)` on `finance.budgets` (R3.2); `budget_vs_actual(conn, month)` — join `finance.budgets` to actual spend from `public.real_activity` (`is_transfer=false AND is_investment=false`, `date_trunc('month')`), returning budgeted/spent/remaining per category (R3.3). Thresholds from `accounting_config` (R3.5).

### Rollup migration (allocation-aware) — R2.1/R2.2/R2.3
Repoint every category/amount rollup at `public.real_activity` with the canonical `is_transfer=false AND is_investment=false` filter: `finance.py` `spending_summary`/income (`:196-228`), `dashboard.py` MTD/top/prev (`:382-431`), `alerts.py check_budgets` (`:39-54`), `briefing.py` weekly status (`:285-303`). The **sum-vs-list rule**: sums use `real_activity`/`is_split=false`; the transaction list uses `parent_id IS NULL`.

### Routers
- **`finance_review.py`** (+): `POST /transactions/{id}/split` `{allocations:[{category_id,amount}]}`, `POST /transactions/{id}/unsplit`, `GET /transactions/{id}/allocations` — `require_admin` for writes (R1.4/R1.7).
- **`finance_budgets.py`** (new, registered): `GET /budgets?month=`, `PUT /budgets` `{category_id,month,limit}` (require_admin), `GET /budgets/actual?month=` (R3.2/R3.3).

### Frontend
- **FinanceReviewPage** + `financeReview.ts`: a split editor expanding a row into N allocation lines with a running-sum-equals-total guard before save; parent rows show a "Split" badge (R1.7).
- **BudgetsPage** (`/finance/budgets`, lazy, nav link) + `financeBudgets.ts`: Budgeted/Spent/Remaining table using `budget.ts` ok/warn/over tone; optional dashboard budget-progress widget (R3.4).

## Data Flow

1. **Split:** user allocates a txn → `create_split` validates sum-to-total in one tx → parent becomes container (`is_split=true`, category NULL, override), children inserted (own category/amount, parent's date/account). Idempotent unsplit reverses it.
2. **Rollup (read):** any category/amount sum reads `public.real_activity` (parents excluded, children included) with the canonical filter → splits counted per child category, no double-count.
3. **Budget actual:** `budget_vs_actual` = `finance.budgets` ⟕ `real_activity` for the month.
4. **Alerts (hourly):** `check_budgets` reads the same allocation-aware actual + config thresholds → Pushover at warn/over.

## Data Model / Migrations
- `finance.transactions`: `+ parent_id varchar(128) FK→transactions(id) ON DELETE CASCADE`, `+ is_split boolean NOT NULL DEFAULT false`; index `(parent_id)`.
- `public.transactions` view recreated (adds `parent_id`,`is_split`); new `public.real_activity` view; both `GRANT SELECT finance_reader`.
- `finance.budgets` reused as-is (`category_id, month, limit_amount`, UNIQUE `(category_id, month)`); `finance.categories.budget_monthly` deprecated (unread).
- `finance.accounting_config`: `budget_warn_ratio`, `budget_over_ratio` rows.
- Migrations `0031` (schema) + `0032` (seed); forward-only, migrator-owned.

## API / Interfaces
- `POST /api/finance/transactions/{id}/split` · `/unsplit` · `GET …/allocations` (review router).
- `GET /api/finance/budgets?month=` · `PUT /api/finance/budgets` · `GET /api/finance/budgets/actual?month=` (budgets router).
- Reads `get_current_user`; writes `require_admin`; Pydantic in/out; DB-down → 503.

## Technology Choices
- **Child-subtransaction splits** (Actual Budget model) over an allocation table or JSON: children are first-class rows, so the existing categorizer/rules/merchant-memory pipeline and `finance_reader`/ask-db work unchanged — no new grants. The `parent.amount = Σchildren` invariant + the sum-vs-list rule keep every existing `amount` sum correct.
- **`real_activity` view** as the single rollup source: one place enforces `is_split=false` + (callers add) the canonical filter, instead of 8 drift-prone edits.
- **Reuse `finance.budgets` + `alerts.py`**: the table is already correct (per-category-per-month); the work is API + UI + allocation-aware actual, not a new model.
- **In-transaction sum integrity, not a DB trigger** — proportionate at 414 txns; mirrors Actual.
- **No new deps, no LLM.**

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| A missed rollup double-counts splits (R2.3) | Single `real_activity` view; a test enumerates the rollups; rollups are a no-op until a split exists (R4.3). |
| Account-level `amount` sums double-count (parent+children) | The sum-vs-list rule: sums use `is_split=false`; net-worth orthogonal (snapshots) — test asserts unchanged (R2.4). |
| Cascade overwrites a split parent | Parent set `user_category_override=true` (Writer already honors) + `is_split=false` guard added (R1.5). |
| Split breaks transfer invariants | Transfer/split mutually exclusive in v1 (R1.6); `transfer_id` partial-unique untouched. |
| Two budget stores ambiguity | `finance.budgets` is the single source; `categories.budget_monthly` deprecated/unread (R3.1). |
| View recreate ownership (C7) | Recreate under `bowershub_migrator` + re-GRANT, mirroring `0029`. |
| Seed on populated prod (0023 class) | `0032` guarded + dry-run BEGIN…ROLLBACK on prod. |

## Test Strategy
DB-backed (`fresh_db` + `apply_migrations`):
- Split: create validates sum-to-total (reject on mismatch), parent becomes container, children inherit date/account, unsplit restores; transfer/split rejection (R1.1-1.6).
- Rollups: a split txn's children count per category, parent excluded; account-level sum + net worth unchanged after split (R2.1/2.4); canonical filter consistent across `finance.py`/`dashboard.py` (R2.2).
- Budgets: upsert + budget_vs_actual allocation-aware; `check_budgets` uses the new actual + config thresholds (R3.2/3.3/3.5).
- Schema-from-empty (C2); `public.transactions`/`real_activity` views expose columns + grants; `0032` dry-run clean on prod.
- Frontend: split-editor sum guard; budgets table tone; `tsc` + page tests.
