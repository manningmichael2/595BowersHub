# Finance Accounting — Design

> Satisfies requirements in `requirements.md`. Reference IDs inline (e.g. "satisfies R1.2").

## Design tournament (how this design was chosen)

Three angles were considered and synthesized (recorded so the trade-offs aren't relitigated):

- **Minimal-change** — extend `TransferDetector` in place, add net-worth to `services/finance.py`, reuse `finance.categorizer_config`, endpoints onto `dashboard.py`. *Won:* reuse the existing counterpart algorithm; consolidate (not rewrite) net worth. *Lost:* it leaves net-worth logic split and gives budgets/splits (the next spec) no home.
- **Ideal-architecture** — a clean `services/accounting/` package + a dedicated typed router + a dedicated config table. *Won:* the package spine (budgets/splits land here next, so it pays off) and a single net-worth service. *Lost:* a full rewrite of the `balances` skill path — avoided; we wrap, not replace.
- **Risk-first** — everything additive/nullable, idempotent reversible backfill, fold transfer-linking into the **existing nightly pass** (one writer of `is_transfer`), verify the liability sign before trusting it, recreate the view under the migrator. *Won:* all of the above. *Lost:* a `legacy→shadow→on` runtime feature-gate — deliberately **rejected** as over-engineering: net worth/snapshots/reconciliation are additive read-only or user-initiated, and the only live-number change (transfer *linking*) is reversible and folded into the existing cascade. (Matches the steering note that runtime kill-switches are over-engineering at this scale.)

**Synthesis:** the `services/accounting/` package spine (ideal) + reuse `_find_counterpart` and consolidate net worth (minimal) + additive/idempotent/single-writer/view-under-migrator (risk-first), minus the feature-gate.

## Architecture Overview

```
PWA (React)                         FastAPI                              Postgres (finance.*)
─────────────                       ───────────────────────             ─────────────────────
AccountsPage / NetWorthWidget  ──>  routers/finance_accounting.py  ──>  services/accounting/
  financeAccounting.ts (typed)        (get_current_user / require_admin)   ├─ config.py     (accounting_config k/v)
                                                                           ├─ transfers.py  (TransferLinker — reuses TransferDetector._find_counterpart)
SimpleFin nightly sync  ───────────────────────────────────────────────> ├─ snapshots.py  (upsert balance_snapshots on sync)
  (services/simplefin_sync.py)                                            ├─ networth.py   (account_type-driven; consolidates finance.py + dashboard.py)
nightly categorizer (02:30) ──> run_cascade ──> TransferLinker ─────────> ├─ reconciliation.py (drift + cleared tally + audit)
  (single writer of is_transfer + transfer_id)                           └─ base.py
```

**New:** the `services/accounting/` package, `routers/finance_accounting.py`, a typed FE client + UI, four schema additions, two seed defaults. **Reused:** `TransferDetector._find_counterpart` (`services/categorization/transfer.py:67-88`), `LIABILITY_TYPES` (`transfer.py:33`), the `is_transfer`/`is_transfer_manual` conventions, the `finance_review.py` typed-router pattern, the `categorizer_config` `load_config` pattern, `simplefin_sync.py` as the snapshot hook.

## Components

### services/accounting/config.py
- **Responsibility:** DB-driven tunables (R4.3) — `match_date_window_days`, `match_amount_tolerance`, `reconcile_tolerance`, `stale_balance_days`.
- **Location:** `bowershub-ai/backend/services/accounting/config.py`
- **Reuses:** mirrors `services/categorization/config.py` `load_config(conn)` k/v pattern, reading `finance.accounting_config`.

### services/accounting/transfers.py — `TransferLinker`
- **Responsibility:** persist the two-leg link (R1.1); auto-link unique high-confidence counterparts (R1.2); manual `link(a,b)` / `unlink(id)` (R1.5); maintain symmetry/1:1/no-self-link (R1.8).
- **is_transfer ownership (R1.9):** the nightly cascade's `TransferDetector` remains the **sole nightly writer of `is_transfer`**. The auto-link path operates *only* on rows already flagged `is_transfer=true AND transfer_id IS NULL AND transfer_link_manual=false` — it writes **only `transfer_id`** (both legs, one transaction), never `is_transfer`. The *manual* `link()` path is the one exception that may set `is_transfer=true` — a user action, marked sticky via `transfer_link_manual` (exactly mirroring the existing `is_transfer_manual` user-override convention). So: one nightly writer of `is_transfer` (the detector), plus the explicit user link — no race.
- **Own scan, not the cascade work-set:** runs as a step *after* `run_cascade` with its **own query** over `is_transfer` rows lacking a link (the cascade's work-set is uncategorized rows, a different set). Reuses the `_find_counterpart` SQL to locate the counterpart — does **not** re-derive the heuristic.
- **Inputs/Outputs:** sets `transfer_id` on both rows, or routes ambiguous/near-miss (fee/FX) to the existing "transfer?" review queue (R1.3). Single-leg (no counterpart) → stays `is_transfer=true, transfer_id=NULL` (R1.4).

### services/accounting/transfer_link_backfill.py
- **Responsibility:** one-time idempotent, resumable historical linking (R1.6) — per-row commit, `WHERE transfer_id IS NULL AND transfer_link_manual=false`, never overrides manual links. Mirrors `categorization/transfer_backfill.py`.

### services/accounting/networth.py
- **Responsibility:** the single net-worth implementation (R3.4), replacing `services/finance.py:get_balances` sign-based logic (`:55-58`) and `routers/dashboard.py:finance_balances` (`:460-509`). Classifies by `account_type` (R3.1); NULL type → excluded + "needs type" (R3.1); liabilities via `LIABILITY_TYPES`; net worth = `SUM(last_balance)` over `include_in_net_worth=true` accounts (sign already correct — see Technology Choices); flags stale balances (R3.7). Time series from `balance_snapshots` (R3.6).
- **Note:** the `balances` skill (`services/finance.py`) and dashboard both call this one function. The skill's existing **response contract is preserved** (it still returns the `net_worth` + grouped balances shape its chat formatter expects) — only the internal classification (sign-based → `account_type`-based) and the exclusion source (hardcoded list → `include_in_net_worth`) change, so no chat-skill regression.

### services/accounting/snapshots.py
- **Responsibility:** `upsert_balance_snapshot(account)` (R3.5) — `INSERT ... ON CONFLICT (account_id, snapshot_date) DO UPDATE` keyed on `last_balance_date` (NULL → sync date). Called from `simplefin_sync.py` after balances update (`:118-124`).

### services/accounting/reconciliation.py
- **Responsibility:** drift = statement_balance − synced `last_balance` (R2.1); cleared tally since `reconciled_through_date` (R2.2); write a `finance.reconciliations` audit row + advance `reconciled_through_date` (R2.3-2.4).

### routers/finance_accounting.py
- **Responsibility:** typed endpoints (R1.5, R2.5, R3.7). Reads via `get_current_user`, mutations via `require_admin` (mirrors `finance_review.py`); DB-down → typed 503. Registered in `main.py`.

### Frontend
- `services/financeAccounting.ts` (typed client, mirrors Pydantic, via `./api`); an **Accounts / Net-worth** page (route in `App.tsx`, lazy) + a dashboard net-worth widget; reuse `MerchantLogo`/existing finance styles.

## Data Flow

1. **Nightly link (R1.9 — single writer):** the 02:30 `run_cascade` finishes (the detector having set `is_transfer` as it does today), then `TransferLinker` runs its own scan of `is_transfer=true AND transfer_id IS NULL AND transfer_link_manual=false` rows and writes `transfer_id` on both legs of each unique match (per-row commit). The linker writes **only `transfer_id`**, never `is_transfer` — so the detector stays the single nightly `is_transfer` writer (no race).
2. **Snapshot (R3.5):** SimpleFin sync updates `last_balance`/`last_balance_date`, then `upsert_balance_snapshot` writes one `balance_snapshots` row per account (idempotent same-day).
3. **Net worth (read):** `networth.py` sums signed `last_balance` over included, typed accounts; returns total + asset/liability breakdown + per-account as-of/stale flags. Trend = group snapshots by date.
4. **Reconcile (user-initiated):** user submits statement balance+date → drift vs `last_balance`, cleared tally, audit row, `reconciled_through_date` advanced.
5. **Manual link/unlink (user-initiated):** `POST /link {a,b}` sets both `transfer_id` + `transfer_link_manual=true`; `/unlink` clears both sides.

## Data Model / Migrations

**`0029_finance_accounting_schema.sql`** (DDL, additive/nullable, migrator-owned — R4.2):
- `finance.transactions`: `+ transfer_id varchar(128) REFERENCES finance.transactions(id) ON DELETE SET NULL` (R1.8 deletion-safe); `+ transfer_link_manual boolean NOT NULL DEFAULT false` (R1.5); `+ cleared boolean NOT NULL DEFAULT false` (R2.2). `CHECK (transfer_id IS NULL OR transfer_id <> id)` (no self-link, R1.8); partial `UNIQUE` index on `transfer_id WHERE transfer_id IS NOT NULL` (no many-to-one → enforces 1:1 with the writer's symmetric set, R1.8); index on `transfer_id`.
- `finance.accounts`: `+ reconciled_through_date date` (R2.4); `+ include_in_net_worth boolean NOT NULL DEFAULT true` (R3.3 — replaces the hardcoded org list).
- `finance.reconciliations` (new): `id serial PK, account_id varchar(128) REFERENCES finance.accounts(id), statement_date date NOT NULL, statement_balance numeric(12,2) NOT NULL, synced_balance numeric(12,2), delta numeric(12,2), created_at timestamptz DEFAULT now()` (R2.3).
- `finance.balance_snapshots` (new): `account_id varchar(128) REFERENCES finance.accounts(id), snapshot_date date NOT NULL, balance numeric(12,2) NOT NULL, PRIMARY KEY (account_id, snapshot_date)` (R3.5).
- `finance.accounting_config` (new): `key text PRIMARY KEY, value jsonb NOT NULL, updated_at timestamptz DEFAULT now()` (R4.3) — mirrors `categorizer_config`.
- Recreate `public.transactions` view to add `transfer_id, cleared` under the migrator + re-`GRANT SELECT ... finance_reader` (R4.2; mirrors `0022:125-156`).

**`0030_seed_finance_accounting.sql`** (seed, idempotent, dry-run vs populated prod — 0023 lesson):
- Seed `account_type` for the known accounts where NULL (R4.1) — incl. typing the untyped −160k mortgage as `mortgage`. Guarded `WHERE account_type IS NULL`; no-op on prod (already typed), fixes fresh-DB (C2).
- `include_in_net_worth=false` for the previously-excluded orgs (`Email Receipts`, `ADP Redbox`, `Credit Karma`) (R3.3).
- `accounting_config` defaults: `match_date_window_days=4`, `match_amount_tolerance=0.01`, `reconcile_tolerance=0.01`, `stale_balance_days=7`.

## API / Interfaces

All under `/api/finance` (router `finance_accounting.py`):
- `GET /net-worth` → total, asset/liability breakdown by account (balance, type, as_of, stale, included) — `get_current_user`.
- `GET /net-worth/history?from=&to=` → dated series from snapshots — `get_current_user`.
- `GET /accounts` → per-account: type, last_balance, as_of, drift vs last reconcile, cleared tally, reconciled_through_date — `get_current_user`.
- `POST /transactions/link` `{a_id, b_id}` / `POST /transactions/unlink` `{id}` — `require_admin` (R1.5).
- `POST /accounts/{id}/reconcile` `{statement_date, statement_balance}` → delta + audit row — `require_admin` (R2.3).
- `GET /accounts/{id}/reconciliations` → audit history — `get_current_user`.

## Technology Choices

- **Single-entry + `transfer_id` self-FK** (settled in requirements; Actual Budget's model). A self-FK over a `transfer_pairs` table because a transfer is intrinsically 1:1 and `is_transfer` already gates spending in ~15 queries — the link just adds "here's the other leg."
- **Net worth = `SUM(signed last_balance)`.** Verified against prod: liabilities store `last_balance` **negative** (credit_card −4,444; loan −19,347), assets positive — so summing signed balances is sign-correct. `account_type` drives the asset/liability **breakdown display** + NULL-exclusion + stale flags, not sign correction. This retires R3.2's "biggest correctness risk" (it was a real risk; verification shows the data is already consistent — a test pins it).
- **Dedicated `finance.accounting_config`** rather than overloading `categorizer_config` — budgets/splits (next spec) will share it; keeps categorization vs accounting config separate. (Trade-off vs minimal-change's reuse: a tiny extra table for cleaner separation.)
- **No new Python deps; no LLM** — deterministic SQL at 414 txns / ~16 accounts.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `is_transfer` double-written by cascade + linker (R1.9) | Linker runs as a step **inside** the nightly pass after `run_cascade`; single writer; honors manual flags. |
| Transfer link inconsistency (R1.8) | `ON DELETE SET NULL` + no-self-link `CHECK` + partial `UNIQUE(transfer_id)`; writer sets both legs in one tx; unit tests for symmetry/delete/dup. |
| Liability sign wrong → net worth doubled/zeroed | **Verified**: liabilities stored negative; net worth = SUM(signed); a test asserts the hand-checked total for the ~16 accounts (R3.2). |
| NULL `account_type` (new account) mis-counted | Excluded + surfaced "needs type" (R3.1); seed types known accounts incl. the −160k mortgage (R4.1). |
| Seed migration breaks on populated prod (0023 class) | `0030` guarded (`WHERE ... IS NULL`), dry-run BEGIN…ROLLBACK on the live `postgres` container before deploy. |
| View recreate ownership (C7) | `public.transactions` recreated under `bowershub_migrator` + re-GRANT, mirroring `0022`. |
| Net-worth history can't be backfilled | Documented + tested: history starts at snapshot turn-on (R3.5). |

## Test Strategy

DB-backed (`fresh_db` + `apply_migrations`, throwaway pgvector pg16):
- Schema applies from empty; `account_type` non-NULL after `0030` (C2 / R4.1); `public.transactions` view exposes new columns.
- Transfer link: symmetric set, `ON DELETE SET NULL`, no-self-link `CHECK`, partial-unique blocks many-to-one; manual link sticky across a re-run; single-leg stays `transfer_id=NULL` (R1.1-1.9). Backfill idempotent.
- Net worth: asset−liability with the verified signs, NULL-type excluded, `include_in_net_worth=false` excluded, stale flag; **hand-checked total** for a fixture mirroring the 16 accounts (R3.1-3.4, R3.7). History series from snapshots; snapshot upsert idempotent same-day (R3.5-3.6).
- Reconcile: drift math, audit row, cleared tally, `reconciled_through_date` advance (R2.1-2.4).
- Migration dry-run (BEGIN…ROLLBACK) on populated prod before deploy.
- Frontend: typed client + page-render tests; `tsc --noEmit`.
- CI: the existing `test_migrate_as_app_role.py` guards C7; full suite green.
