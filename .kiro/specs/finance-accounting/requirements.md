# Finance Accounting — Requirements

## Overview

Add the **accounting layer** that the shipped `finance-categorization` spec explicitly deferred (`/.kiro/specs/finance-categorization/requirements.md:13` names "the accounting spec"): **transfer matching** (linking the two legs of an inter-account movement into one logical entry so it isn't double-counted), lightweight **account reconciliation** (confirm the app's numbers match the bank), and **net worth** (assets − liabilities, point-in-time and over time). This turns a pile of categorized transactions into a coherent Monarch/Origin-style financial picture — the owner's stated north star (`project-review.md` §8.4), now unblocked since categorization is live and `account_type` exists.

**Modeling decision (settled by grounding research — do not relitigate):** stay **single-entry** (signed `amount` per account, already pervasive across ~15 queries + the categorization cascade) and add a **self-referential `transfer_id` link** between the two legs — the model used by Actual Budget, Monarch, YNAB, and Lunch Money. Double-entry is rejected as disproportionate for a single household whose synced bank balances are the source of truth.

**Explicitly out of scope (adjacent/next specs):** budgets, transaction **splits** (split changes the transaction data model — its own spec), multi-currency/FX (no multi-currency accounts today), and any general-ledger/double-entry rewrite.

## Feature 1: Transfer Matching

The categorization cascade already *flags* `is_transfer` and even finds the counterpart at detection time, but it only stashes the counterpart id in a decision-log JSON — the two legs are **not linked** on `finance.transactions` (`services/categorization/transfer.py:104-110`). This feature persists the pairing.

### R1.1 — Persist the transfer link
The system stores a durable link between the two legs of a matched transfer (a self-referential `transfer_id` on `finance.transactions` pointing at the paired row), so a transfer is one logical movement, not two unrelated rows.

### R1.2 — Reuse the existing counterpart algorithm
Auto-matching reuses the existing `TransferDetector._find_counterpart` heuristic (`transfer.py:67-88`: opposite sign, near-equal magnitude, different account, within a date window) rather than introducing a second matcher. When a **unique** counterpart is found and neither leg is manually linked, both legs' `transfer_id` are set.

### R1.3 — Asymmetric gate (honor prior decision)
Auto-linking happens only for high-confidence unique matches. Ambiguous cases (multiple candidate counterparts, or a near-miss outside tolerance such as a fee/FX delta) are surfaced to the existing **"transfer?" review queue** rather than auto-linked — never silently netted. (Honors the categorization spec's asymmetric-gate decision; under-linking is the safe failure mode.)

### R1.4 — Single-leg transfers
A transfer whose counterpart account isn't synced (e.g. the mortgage/loan not on SimpleFin) keeps `is_transfer = true` with `transfer_id = NULL`. A counterpart is **not required** to mark something a transfer. (This is the common case for liability payments — the detector's liability-payment path already handles flagging.)

### R1.5 — Manual link / unlink (sticky)
An admin can manually link two transactions as a transfer and unlink a pair, via API. A manual link sets a sticky `transfer_link_manual` flag (mirroring the existing `is_transfer_manual` convention, `transfer.py:94`) that the auto-matcher must honor and never override.

### R1.6 — Idempotent historical backfill
A one-time, idempotent, resumable backfill links existing history's transfer legs (per-row commit, guarded `WHERE` so re-runs are no-ops), mirroring `transfer_backfill.py`. It must not override manual links and must be dry-runnable against the populated prod DB (0023-incident discipline).

### R1.7 — Transfers excluded from spend/income rollups
Linked transfers (and single-leg `is_transfer` rows) are excluded from spending and income totals so an inter-account movement never inflates either side. (Mostly already true via `is_transfer`; this requirement guards that net-worth/reporting paths added here respect it.)

### R1.8 — Link integrity invariants
The link is constrained to stay consistent: it is **symmetric** (if A.transfer_id = B then B.transfer_id = A), **1:1** (a transaction links to at most one counterpart — no chains, no many-to-one), and **no self-link** (id ≠ transfer_id). The FK uses `ON DELETE SET NULL` so deleting one leg clears the dangling pointer on the other; clearing `is_transfer` (manually or by re-detection) also clears both legs' `transfer_id`. A link only joins transactions in **different** accounts.

### R1.9 — Single writer of is_transfer (no double-write with the cascade)
The nightly categorization cascade currently writes `is_transfer` (`services/categorization/transfer.py`). The transfer-link writer must coordinate so the two paths don't fight: linking is performed by/after the same nightly pass, reuses the detector's decision, and both honor `is_transfer_manual`/`transfer_link_manual`. The spec must state which component owns the `is_transfer` write so there is exactly one writer, run with per-row commits (no long locks, mirroring the cascade).

## Feature 2: Account Reconciliation

**Reconciliation model (resolves the "computed balance from what?" ambiguity):** balances are bank-**synced** — the app does NOT maintain a transaction-derived running balance, and it does not have full historical transactions for every account. So "reconcile" here means: **the user enters the balance from their bank statement, and the system compares it to the bank-synced `last_balance`** (drift between two authoritative-ish sources), plus an optional **cleared-transaction tally** as the manual cross-check. There is no app-computed running balance to reconcile against; any requirement implying one is wrong.

### R2.1 — Statement-vs-synced drift check
The user enters a statement balance (and date) for an account; the system surfaces the **delta** against the bank-synced `last_balance` (`finance.accounts.last_balance`, `0001_baseline.sql:269`) as of that date, so drift between the statement and the sync is visible. Within a configurable tolerance (R4.3) the account shows "in sync."

### R2.2 — Cleared status + tally
Transactions carry a `cleared` boolean (default false, NOT NULL) so the user can mark which transactions have appeared on a statement (Actual Budget's model). The system shows the **cleared-transaction tally** for an account (sum of cleared since the last reconciled date) as a manual cross-check when the statement and sync diverge. This is the only transaction-derived figure — explicitly a *partial* tally, not a full running balance.

### R2.3 — Reconcile event + audit trail
On reconcile, the system records the event in a new `finance.reconciliations` table: account, statement date, statement balance, the synced `last_balance` at that time, and the delta — an audit trail of "as of X, statement said Y, sync said Z." It does **not** persist a fabricated "app-computed" balance.

### R2.4 — Reconciled-through date
An account tracks a `reconciled_through_date` (the date through which everything is confirmed), giving a cheap "trust everything before this date" signal. Reconciled transactions are **not** hard-locked (no immutable rows — friction not worth it at this scale).

### R2.5 — Reconciliation API + UI
A typed API and a UI surface expose per-account drift, cleared totals, the reconcile action, and reconciliation history — following the `finance_review.py` typed-router and `financeReview.ts` typed-client patterns.

## Feature 3: Net Worth

### R3.1 — account_type-driven classification
Net worth classifies each account as asset or liability by `account_type` (liabilities = the existing `LIABILITY_TYPES = {credit_card, loan, mortgage}`, `transfer.py:33`; everything else is an asset), replacing today's fragile **balance-sign** guess (`services/finance.py:55-58`, `routers/dashboard.py:490`). An account with **NULL `account_type`** (e.g. a newly-added account before it's typed) is **excluded from net worth and surfaced as "needs type"** rather than silently mis-classified — it must not default to asset or liability.

### R3.2 — Correct liability sign handling
A liability's balance **reduces** net worth (a $500 credit-card balance lowers net worth by $500), fixing the current `dashboard.py:497` naive `+= last_balance`. Testable invariant: net worth = Σ(asset `last_balance`) − Σ(|liability balance|). The implementation determines the stored sign of `last_balance` for liabilities from real prod data and normalizes accordingly (single biggest correctness risk — a wrong sign silently doubles or zeroes net worth), and a test asserts the hand-checked figure for the ~16 accounts.

### R3.3 — Remove hardcoded org exclusions (NO-HARDCODING)
The hardcoded org-name exclusion list in `dashboard.py:480` (`'Email Receipts','ADP Redbox','Credit Karma'`) is replaced with DB-driven configuration (e.g. an `include_in_net_worth` flag on accounts, or a config row), per project rule #1.

### R3.4 — Single net-worth implementation
The two duplicate net-worth calculations (`services/finance.py:get_balances` and `routers/dashboard.py:finance_balances`) are consolidated into one service function that both the `balances` skill and the dashboard call.

### R3.5 — Balance-snapshot history
A new `finance.balance_snapshots` table (`account_id`, `snapshot_date`, `balance`, PK `(account_id, snapshot_date)`) records each account's balance per sync. The SimpleFin sync path **upserts** a snapshot per account keyed on `(account_id, last_balance_date)` — same-day re-syncs are last-write-wins (the PK makes this idempotent), and if `last_balance_date` is NULL the sync date is used. History begins when snapshotting turns on — past net worth cannot be reconstructed (no historical balance source), matching how every synced app behaves; "starts now" is the expected, tested behavior (a backfill of pre-existing history is explicitly NOT a requirement).

### R3.6 — Net-worth over time
The system computes a net-worth time series from `balance_snapshots` (`SUM(asset) − SUM(liability)` grouped by `snapshot_date`), exposed via API for a trend chart.

### R3.7 — Net-worth API + UI
Typed endpoints expose current net worth (with asset/liability breakdown by account) and the net-worth trend; a UI surface renders them (a dashboard widget and/or an accounts page). Each account's contribution shows its balance **as-of date** (`last_balance_date`) and flags a **stale** balance (not synced within a configurable window, R4.3) so an out-of-date account doesn't silently skew net worth without the user knowing.

## Feature 4: Schema Reproducibility & Config (cross-cutting)

### R4.1 — account_type is operational metadata (reproducibility)
**Reframed during implementation:** `finance.accounts` rows come from the SimpleFin sync, not migrations, so a static seed can't reproduce `account_type` on a fresh DB (no account rows exist until a sync). The *column* is reproducible (migration); the *values* are operational metadata set via the **admin set-type API** (`PUT /accounts/{id}/type`), and net worth **excludes + flags** untyped accounts as "needs type" (R3.1) so nothing is silently mis-counted. The `0030` seed still types known prod accounts (e.g. the mortgage) as a one-time correction (no-op on fresh DB).

### R4.2 — Migrator-owned DDL + read view
All new `finance.*` objects (columns, `transfer_links`/`reconciliations`/`balance_snapshots`) are created in forward-only migrations authored under the `bowershub_migrator` role (C7). New columns surfaced to `ask-db`/`finance_reader` are added to the `public.transactions` view, recreated under the migrator with `GRANT SELECT ... finance_reader` re-applied (mirrors `0022:125-156`).

### R4.3 — DB-driven accounting config
Tunables (transfer match date window, amount tolerance, reconcile tolerance, near-miss/fee tolerance) are DB-driven config rows (extend the `finance.categorizer_config` k/v pattern or a parallel `finance.accounting_config`), never code constants.

## Acceptance Criteria

- [ ] A bank-to-card payment and a checking↔savings transfer each show as **one linked movement** (both legs carry each other's `transfer_id`); spending/income totals exclude them.
- [ ] A manually linked pair survives a re-run of the auto-matcher (sticky); unlink clears both sides.
- [ ] Transfer links stay consistent: deleting one leg nulls the other's `transfer_id`; no transaction links to two counterparts; no self-links; `is_transfer` has exactly one writer (no cascade double-write).
- [ ] Reconcile compares a user-entered statement balance to the synced `last_balance` (no fabricated app-computed balance); an account with NULL `account_type` is excluded from net worth and flagged "needs type"; a stale-balance account is flagged in the net-worth breakdown.
- [ ] A single-leg liability payment (counterpart not synced) is `is_transfer=true, transfer_id=NULL` and is not forced into the review queue.
- [ ] Net worth subtracts credit-card/loan balances (verified against real data) and classifies by `account_type`, not balance sign; the hardcoded org exclusions are gone.
- [ ] Net-worth current + a trend series render from `balance_snapshots`; a new snapshot row is written on each SimpleFin sync.
- [ ] Per-account reconciliation shows computed-vs-synced drift, supports entering a statement balance, and records a `finance.reconciliations` audit row.
- [ ] A from-empty `fresh_db` rebuild yields non-NULL `account_type` and all new tables/columns + the updated `public.transactions` view.
- [ ] No new hardcoded config: tolerances and net-worth inclusion are DB rows.

## Non-Functional Requirements

- **No hardcoding:** match tolerances, reconcile tolerance, and net-worth inclusion/classification are DB-driven (Postgres), read via API — never code constants. (Project rule #1.)
- **Data safety:** parameterized SQL only; schema via forward-only migrations (next number **0029**), migrator-owned; seed/idempotency migrations dry-run (BEGIN…ROLLBACK) against the **populated** prod DB, not just empty `fresh_db` (0023-incident lesson); additive nullable columns + `IF NOT EXISTS`/guarded writes.
- **Reversibility:** changes that alter derived numbers (net worth, transfer netting) follow the categorization rollout's dark-launch + reversible pattern where practical; the transfer-link backfill is idempotent and a link can be cleared.
- **Security / RBAC:** reads via `get_current_user`, mutations (manual link/unlink, reconcile) via `require_admin` (mirrors `finance_review.py`). No raw SQL from the client.
- **Performance / scale:** deterministic SQL, **no LLM** (matching/reconciliation/net-worth are exact joins/sums at 414 txns / ~16 accounts). Snapshots ~6k rows/yr — no partitioning/rollups. Must fit the 12GB single-box reality.

## Constraints & Assumptions

- Single Minisforum box over Tailscale; ~414 transactions, ~16 accounts; `amount` is signed (negative = outflow). Single-user/household.
- Reuse, don't duplicate: the counterpart-match algorithm (`transfer.py`), the `is_transfer`/`is_transfer_manual` conventions, `LIABILITY_TYPES`, the `finance_review.py` router + `financeReview.ts` client + service-package patterns.
- Assumes no multi-currency accounts (FX matching out of scope; verify before relying on tight amount tolerance).
- Honor settled decisions: asymmetric transfer gate, sticky manual flags, the 25-category taxonomy, `is_investment` excluded from income/expense (but investment **balances** count toward net worth).

## Dependencies

- finance-categorization (shipped) — provides `is_transfer`, `account_type`, the `TransferDetector`, the review-queue pattern.
- C7 migrator-role cutover (live) — required to author `finance.*` DDL.
- SimpleFin sync path (`services/simplefin_sync.py`) — the hook point for balance snapshots (R3.5).
- Next: `finance-budgets-splits` builds on this spec's accounting rollups.

## Success Metrics

- **Transfer double-counting eliminated:** 0 linked-transfer legs counted in spending/income totals; ≥90% of true two-leg transfers in history auto-linked, remainder in the review queue (none silently netted).
- **Net-worth correctness:** computed net worth equals Σ(asset `last_balance`) − Σ(liability `last_balance`) with correct signs, validated against a hand-check of the ~16 accounts.
- **Reproducibility:** `fresh_db` CI build passes with non-NULL `account_type` and all new schema (C2 intact).
- **Net-worth history:** a snapshot row per account per sync from turn-on; trend endpoint returns a dated series.
