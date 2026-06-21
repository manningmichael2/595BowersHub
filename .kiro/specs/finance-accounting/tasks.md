# Finance Accounting — Tasks

> **STATUS: COMPLETE (2026-06-21).** All 9 tasks implemented, merged (PRs #27–#31), and deployed. Validator 24/24. See context-log 2026-06-21.

> Each task traces to one or more requirements. Work top-to-bottom; respect dependencies. Each task is verified against its Definition of Done before the next.

## Task 1: Schema + seed migrations (0029, 0030)
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R4.1, R4.2, R4.3
- [ ] `0029_finance_accounting_schema.sql` (migrator-owned, additive/nullable): `finance.transactions` `+ transfer_id varchar(128) REFERENCES finance.transactions(id) ON DELETE SET NULL`, `+ transfer_link_manual boolean NOT NULL DEFAULT false`, `+ cleared boolean NOT NULL DEFAULT false`; `CHECK (transfer_id IS NULL OR transfer_id <> id)`; partial `UNIQUE` index on `transfer_id WHERE transfer_id IS NOT NULL`; index on `transfer_id`.
- [ ] Same migration: `finance.accounts` `+ reconciled_through_date date`, `+ include_in_net_worth boolean NOT NULL DEFAULT true`; new tables `finance.reconciliations`, `finance.balance_snapshots`, `finance.accounting_config` (per design Data Model).
- [ ] Recreate `public.transactions` view to expose `transfer_id, cleared` under the migrator + re-`GRANT SELECT ... finance_reader` (mirror `0022:125-156`).
- [ ] `0030_seed_finance_accounting.sql` (idempotent): seed `account_type` where NULL for known accounts (incl. typing the untyped ~−160k mortgage as `mortgage`); set `include_in_net_worth=false` for `Email Receipts`/`ADP Redbox`/`Credit Karma`; seed `accounting_config` defaults (`match_date_window_days=4`, `match_amount_tolerance=0.01`, `reconcile_tolerance=0.01`, `stale_balance_days=7`).
- [ ] **Migration:** `bowershub-ai/backend/migrations/0029_finance_accounting_schema.sql`, `0030_seed_finance_accounting.sql`.
- [ ] **Tests:** applies from empty `fresh_db`; `account_type` non-NULL after `0030` (C2/R4.1); view exposes new columns; `0030` dry-run (BEGIN…ROLLBACK) on populated prod is a clean no-op (0023 lesson).

## Task 2: Accounting config loader
- **Effort:** S
- **Dependencies:** Task 1
- **Requirements:** R4.3
- [ ] `services/accounting/config.py` (`load_config(conn)` over `finance.accounting_config`) + `base.py`, mirroring `services/categorization/config.py`. No constants — tolerances read from DB.
- [ ] **Tests:** loader returns seeded defaults; missing key falls back safely.

## Task 3: TransferLinker (link, manual link/unlink, integrity)
- **Effort:** L
- **Dependencies:** Task 1, Task 2
- **Requirements:** R1.1, R1.2, R1.3, R1.4, R1.5, R1.8, R1.9
- [ ] `services/accounting/transfers.py`: auto-link by reusing `TransferDetector._find_counterpart` (no re-derivation); writes **only `transfer_id`** symmetrically on both legs in one tx (R1.1, R1.2, R1.9).
- [ ] Asymmetric gate: unique high-confidence → link; ambiguous/near-miss → existing "transfer?" review queue, never auto-link (R1.3). Single-leg → stays `transfer_id=NULL` (R1.4).
- [ ] `link(a,b)` / `unlink(id)`: manual link sets both `transfer_id` + `is_transfer=true` + sticky `transfer_link_manual`; unlink clears both sides; auto-path skips `transfer_link_manual` rows (R1.5, R1.8).
- [ ] **Tests:** symmetry; `ON DELETE SET NULL`; no-self-link CHECK; partial-unique blocks many-to-one; manual link sticky across an auto re-run; single-leg untouched; only `transfer_id` written by the auto path (R1.9).

## Task 4: Transfer-link backfill + nightly wiring
- **Effort:** M
- **Dependencies:** Task 3
- **Requirements:** R1.6, R1.9
- [ ] `services/accounting/transfer_link_backfill.py`: idempotent, resumable, per-row commit, `WHERE is_transfer=true AND transfer_id IS NULL AND transfer_link_manual=false`; never overrides manual links (mirror `categorization/transfer_backfill.py`).
- [ ] Wire `TransferLinker` as a step **after** `run_cascade` in the nightly pass (its own scan, not the cascade work-set) so the detector stays the sole nightly `is_transfer` writer (R1.9).
- [ ] **Tests:** backfill idempotent (second run = no-op); does not touch manual links; runs after cascade without double-writing `is_transfer`. Dry-run on populated prod before deploy.

## Task 5: Balance snapshots + sync hook
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R3.5
- [ ] `services/accounting/snapshots.py`: `upsert_balance_snapshot` (`INSERT ... ON CONFLICT (account_id, snapshot_date) DO UPDATE`), keyed on `last_balance_date` (NULL → sync date).
- [ ] Hook into `services/simplefin_sync.py` after balances update (`:118-124`) to snapshot every account per sync.
- [ ] **Tests:** same-day re-sync is last-write-wins (idempotent); NULL `last_balance_date` falls back to sync date; one row per account per date.

## Task 6: Net-worth service (consolidated)
- **Effort:** L
- **Dependencies:** Task 1, Task 5
- **Requirements:** R1.7, R3.1, R3.2, R3.3, R3.4, R3.6
- [ ] `services/accounting/networth.py`: single net-worth function classifying by `account_type` (liabilities = `LIABILITY_TYPES`); net worth = `SUM(signed last_balance)` over `include_in_net_worth=true` accounts (signs verified correct); NULL `account_type` excluded + "needs type"; transfers excluded from spend/income rollups (R1.7); time series from `balance_snapshots` (R3.6).
- [ ] Repoint `services/finance.py:get_balances` (the `balances` skill) and `routers/dashboard.py:finance_balances` at this service; **preserve the skill's response contract**; remove the hardcoded org-exclusion list (`dashboard.py:480`) in favor of `include_in_net_worth` (R3.3, R3.4).
- [ ] **Tests:** asset−liability total with the verified signs incl. a **hand-checked figure** for a fixture mirroring the ~16 accounts (R3.2); NULL-type + `include_in_net_worth=false` excluded; stale flag; history series from snapshots; `balances` skill output shape unchanged.

## Task 7: Reconciliation service
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R2.1, R2.2, R2.3, R2.4
- [ ] `services/accounting/reconciliation.py`: drift = statement_balance − synced `last_balance` within `reconcile_tolerance` (R2.1); cleared tally since `reconciled_through_date` (R2.2); write `finance.reconciliations` audit row + advance `reconciled_through_date` on reconcile (R2.3, R2.4).
- [ ] **Tests:** drift math + tolerance; cleared tally; audit row persisted; `reconciled_through_date` advances; no fabricated "computed balance".

## Task 8: finance_accounting router (API)
- **Effort:** M
- **Dependencies:** Task 3, Task 6, Task 7
- **Requirements:** R1.5, R2.5, R3.7
- [ ] `routers/finance_accounting.py` (Pydantic in/out, no `any`): `GET /net-worth`, `GET /net-worth/history`, `GET /accounts` (reads, `get_current_user`); `POST /transactions/link`, `/transactions/unlink`, `POST /accounts/{id}/reconcile` (`require_admin`); `GET /accounts/{id}/reconciliations`. DB-down → typed 503. Register in `main.py`.
- [ ] **Tests:** endpoint auth (member vs admin on the mutating routes); response shapes; 503 on DB-down.

## Task 9: Frontend — net-worth + accounts/reconcile UI
- **Effort:** L
- **Dependencies:** Task 8
- **Requirements:** R2.5, R3.7
- [ ] `services/financeAccounting.ts` typed client (mirrors Pydantic, via `./api`); an Accounts / Net-worth page (lazy route in `App.tsx`, nav link) showing net worth + asset/liability breakdown with as-of/stale flags, a net-worth trend chart, and per-account drift + reconcile action + manual link/unlink.
- [ ] **Tests:** typed-client + page-render tests; `npx tsc --noEmit` clean; `npm test`.

## Definition of Done
- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (validator exit 0).
- [ ] No hardcoded config introduced (tolerances + net-worth inclusion are DB rows; the org-exclusion list is gone).
- [ ] All new `finance.*` DDL is migrator-owned; `public.transactions` view updated under the migrator; `fresh_db` builds from empty with non-NULL `account_type` (C2).
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`); migrations dry-run clean on populated prod before deploy.
- [ ] `context-log.md` updated with a dated entry.
