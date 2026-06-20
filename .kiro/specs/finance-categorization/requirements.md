# Finance Categorization — Requirements

## Overview

Overhaul transaction categorization so it approaches Monarch/Origin quality. Today categorization is a nightly local-Ollama prompt that the owner rates "still poor," plus a chat-only interactive tool rated "only OK." This spec replaces the single weak LLM pass with a **precedence cascade** (user rules → merchant memory → embedding similarity → LLM fallback) built on a new **merchant-normalization** layer, a **learning loop** that actually uses corrections, and a real **review-queue UX**. It is the categorization slice of the finance north star (`project-review.md` §8.4) — explicitly scoped to make categorization *good*.

**This is an overhaul of an existing stack, not greenfield.** A categorization subsystem already exists and must be evolved, not duplicated: `services/categorizer.py` (nightly Ollama job), `services/category_override.py` (interactive skills), the `0018` manual-override learning trigger, `0019/0020` L1 `bh_patterns`, and the `finance.categories` / `category_examples` / `category_aliases` tables.

### Scope

**In scope:** merchant normalization/enrichment, the categorization engine (cascade), the learning/feedback loop, the human review-queue UX (+ its write API), and nightly-job correctness/ingestion fixes.

**Out of scope (adjacent finance-product specs):** the full accounting model — transfer *matching/reconciliation* (pairing both legs into a single ledger entry), net-worth roll-up, splits — plus budgets and the full Monarch-style dashboard. Transaction **splitting** is deferred to the accounting spec — the review queue must not architecturally preclude it, but does not implement it here. Note: transfer/debt-payment **flagging** (so transfers and credit-card/loan/mortgage payments aren't miscategorized as spending) *is* in scope — see Feature 6 — because it's a categorization-correctness concern, not the reconciliation engine.

---

## Feature 1: Merchant normalization & enrichment

The root cause of poor categorization is that the system categorizes raw bank strings like `COSTCO WHSE #0393 MADISON HEIGHMI`. Clean inputs first.

### R1.1 — Normalize raw bank descriptors to a clean merchant name
The system derives a normalized merchant key from the raw `finance.transactions.description` by applying DB-driven rules: stripping payment-intermediary prefixes (e.g. `SQ*`, `TST*`, `PYPL*`, `SP `, `PP*`), store/location numbers (e.g. `#0393`), trailing city/state fragments, and collapsing whitespace/casing. The contract is a **fixture set of input→output pairs** (the acceptance criterion), not a single example, because the long tail is where this lives. Each rule is individually testable. Inputs that no rule matches fall through to a defined default (the cleaned-but-unmatched string) rather than failing.

### R1.2 — Merchant directory with category priors
The system maintains a merchant directory mapping a normalized merchant key → canonical display name and an optional **category prior** (and, where known, an MCC). Once a merchant is known, its prior is a high-confidence categorization signal reusable across all transactions from that merchant.

### R1.3 — MCC → category mapping
When a transaction (or its merchant) carries a Merchant Category Code, the system maps it to a default category via a seeded MCC→category table (open ISO-18245 dataset), used as a cold-start prior before any learned signal exists.

### R1.4 — Normalization rules are DB-driven (no hardcoding)
The intermediary-prefix list, stripping/cleanup rules, MCC→category map, and merchant directory are **Postgres rows**, not Python constants — addable/editable as data. (Replaces the hardcoded rules block in `categorizer.py:113-122` and the NL→category map in `finance.py:356-366`.)

### R1.5 — Enrichment on ingest, and bounded backfill
Normalization runs as transactions are ingested (SimpleFin/email/manual). Existing history is enriched by an explicit, **idempotent backfill** that (a) runs as a separate operation — not inline in the ingest path or the nightly categorizer's critical section, (b) is re-runnable without altering already-correct categorizations, and (c) has a stated wall-clock budget and throughput assumption for the current transaction volume (volume to be measured; the design must size embedding/normalization throughput against it and document the figure). Re-running normalization after a rule change re-derives keys for affected rows only.

### R1.6 — Merchant logos (non-blocking, degrades gracefully)
The UI may surface a merchant logo via a free source (Logo.dev free tier or self-hosted favicon by merchant domain). Absence, rate-limiting, or failure of the logo source degrades gracefully — no broken-image, no blocked render, no effect on categorization. This is presentation-only.

---

## Feature 2: Categorization engine (precedence cascade)

Replace the single nightly LLM call with an ordered cascade; each tier short-circuits when it produces a confident result.

### R2.1 — Deterministic user rules (highest precedence)
User-defined rules always win and are evaluated first, in a **user-orderable priority** (first match applies). A rule matches on any combination of normalized merchant, raw description, **amount range/threshold** (not just sign), and account, and sets a category. Rules are DB rows and can be applied to future transactions and, on demand, to existing matching transactions.

### R2.2 — Merchant-memory tier
For transactions with no matching rule, the system applies the merchant directory's category prior (R1.2) and/or the strongest `category_examples` entry for that normalized merchant, as a **deterministic first-pass lookup** consulted **before** any model call (today `category_examples` only feeds the LLM prompt as few-shot text — R3 fixes this).

### R2.3 — Embedding-similarity tier (pgvector kNN)
For merchants with no memory hit, the system embeds the normalized merchant string (reusing the existing `bge-m3` + `embeddings`/`hybrid_retrieval` infrastructure), finds the k nearest already-categorized transactions in pgvector, and predicts the majority-vote category. At cold start (fewer than a configurable minimum neighbors) it falls back to nearest category-description embeddings or defers to R2.4. The vector index type (HNSW vs IVFFlat) and `k` are design decisions but must be chosen against the measured transaction volume (R1.5) with recall/build-cost noted.

### R2.4 — LLM fallback (last resort), model chosen by role + evaluation
Only transactions unresolved by R2.1–R2.3 are sent to an LLM. Model selection goes through a DB-driven `resolve_role` role (e.g. a `categorizer` role) — **no hardcoded model IDs** — so the model is a config row, swappable without a code change. The spec does **not** hard-commit to a provider: the choice (local Ollama / a different local model / a hosted open model / Anthropic Batch) is made **empirically against the evaluation set (R2.7)**, not by assertion. **Default the role to a local model** — this keeps sensitive transaction data on-box, consistent with the private-PWA stance — and keep a hosted role one DB row away for A/B. Decision rationale recorded so it isn't re-litigated as a cost question: because the cheap tiers (R2.2/R2.3) resolve most transactions and the LLM sees only the residue, the cost difference across providers is **pennies per month** (a full lifetime backfill is a few dollars even on a frontier model) — so the decision is driven by **privacy first, then quality, then operational simplicity — not cost.** Latency is irrelevant (nightly batch), so a slower-but-stronger local model run overnight is a viable option, not just a small one.

### R2.7 — Evaluation harness for model/tier and threshold choice
A labeled evaluation set — a few hundred hand-verified `transaction → category` pairs, stored as data — plus a repeatable scoring harness measure categorization accuracy per model/tier. This is what makes R2.4's model choice and R2.5's confidence thresholds **empirical rather than guessed**, and it doubles as a regression guard whenever the categorizer role or thresholds change. The eval set must include transfer/debt-payment examples (Feature 6) so flagging accuracy is measured too.

### R2.5 — Confidence on a common scale, confidence-gated outcomes
Every tier emits a confidence on a **common [0,1] scale** with a defined mapping per tier (e.g. a rule/merchant-prior hit = 1.0 / a configured constant; kNN = fraction of neighbors agreeing; LLM = a calibrated/self-reported score), so a single DB-configurable threshold (or documented per-tier thresholds) is meaningful across tiers. Above threshold the category is auto-applied; below it the transaction is **left uncategorized and routed to the review queue (Feature 4) — never guessed and never bucketed into "Other."** This is an explicit behavior change from the current `_parse_response` fallback that assigns unparseable results to `Other` (`categorizer.py:213-214`); that fallback is removed.

### R2.6 — Defined precedence, short-circuit, and provenance
The cascade's order, each tier's confidence output, and the auto-apply-vs-review decision are explicitly specified and deterministic given the same inputs and DB state. **Each automatic categorization records its provenance**: the deciding tier, the confidence, and (if used) the model — persisted, so the Success-Metrics measurements (coverage, LLM-call reduction) and the review-queue rationale (R4.1) are computable from data rather than guessed.

---

## Feature 3: Learning & feedback loop

Every manual correction must make future categorization better — the groundwork (`category_examples`, the `0018` trigger, pg_trgm) exists but is crude and underused.

### R3.1 — Corrections strengthen merchant memory (keyed on normalized merchant)
When a user manually recategorizes a transaction, the system records/strengthens a signal keyed on the **normalized merchant** (R1.1), replacing the current `fn_learn_from_manual_override` heuristic ("first alphabetic word ≥3 chars," `0018:48`). Reinforcement count and recency inform future confidence. Changing the `category_examples` key/uniqueness semantics implies a **forward data migration** of existing example rows (with a documented rollback), authored as migrator-role DDL since the trigger/function live in the `finance` schema (owned objects).

### R3.2 — Corrections feed the deterministic tier
Learned signals from corrections are consulted by the merchant-memory tier (R2.2) as a first-pass lookup, not merely injected as LLM few-shot text — so a corrected merchant is reliably categorized next time without a model call.

### R3.3 — "Apply to all from this merchant"
A correction offers, in one action, to apply the new category to all existing transactions from the same normalized merchant and to create/strengthen a reusable rule or merchant prior.

### R3.4 — Corrections are never overwritten; batch re-checks at write time
A user correction (`user_category_override = true`) or a rule-locked categorization is never overwritten by the automatic cascade. The nightly batch re-checks `user_category_override` **at write time** (preserving the existing guard at `categorizer.py:145`), so a correction landing mid-batch is not clobbered by an in-flight categorization computed against a stale snapshot.

---

## Feature 4: Review-queue UX & write API

The interactive tool is chat-only today (`fill:` URI pre-filling "Recategorize <id> to "). Build a real review surface.

### R4.1 — Review queue
A frontend surface lists transactions needing attention (uncategorized + below-threshold), each showing the predicted category, its confidence, and the rationale (the provenance from R2.6 — which rule/merchant/neighbors drove it) so the user can confirm or correct in one tap.

### R4.2 — Bulk recategorization
The user can multi-select transactions in the queue and recategorize them in one action.

### R4.3 — Inline correction with learning entry point
Confirming or correcting a single transaction triggers the learning loop (R3) and offers the "apply to all from this merchant" / "make a rule" options.

### R4.4 — Categorization write API
Categorization writes are exposed as typed HTTP endpoints (today writes exist only through the chat→skill path). Endpoints respect auth/RBAC, return typed responses (no `any` at the API boundary), surface errors via a toast/error path (not silent failure), and define behavior when the DB is unavailable (clear error, no partial write). Existing chat skills continue to work against the same underlying service.

### R4.5 — Recurring/subscription surfacing
The queue surfaces likely recurring charges as a distinct view. **Definition (the testable default, all thresholds DB-configurable):** ≥3 charges from the same normalized merchant where amounts fall within ±X% of each other and inter-charge intervals fall within a recognized cadence window (weekly/monthly/annual ± a tolerance in days). Detection is advisory — it groups for bulk confirmation, it does not auto-apply categories outside the R2.5 gate.

---

## Feature 5: Nightly job correctness, failure modes & ingestion

### R5.1 — Fix the categorizer's schema-qualification bug (code-only, no migration)
`categorizer.py` issues its UPDATE against **unqualified** `transactions` (and reads unqualified `categories`/`category_examples`). The runtime `bowershub_app` role has no `SET search_path` (verified: no `ALTER ROLE … SET search_path` in any migration), so it uses the default `"$user", public` and unqualified `transactions` resolves to `public.transactions` — a **non-updatable multi-table JOIN view** (`0016:7`, no INSTEAD OF trigger). The nightly UPDATE therefore errors and **no categorization persists**. Fix: schema-qualify all categorizer SQL to `finance.*` (matching `category_override.py`). This is a **code-only change — no migration, no owned-object DDL.** Acceptance: a DB-backed regression test on the real baseline first **reproduces** the current failure, then proves the qualified UPDATE persists `category_id` to `finance.transactions`.

### R5.2 — Idempotent, correction-respecting batch
The nightly job is idempotent (re-running yields the same result) and only (re)categorizes transactions that are not manually overridden and not rule-locked (R3.4).

### R5.3 — Cheap tiers first, model last
The batch job runs the cascade in cost order (rules → merchant memory → embedding kNN → LLM), so the LLM handles only the residue — turning today's blanket nightly LLM pass into a rare fallback.

### R5.4 — Sync-before-categorize sequencing, with failure semantics
SimpleFin ingestion runs and completes before the nightly categorizer (today the categorizer is scheduled at 02:30 "after" a SimpleFin sync that is **not actually on the scheduler** — `simplefin_sync.sync_simplefin` exists but is unscheduled; this gap is closed). Defined behavior when the upstream sync fails or overruns its window: the categorizer runs on whatever data is present (it is idempotent and will pick up late arrivals on the next run) rather than blocking, and the sync failure is logged/alerted.

### R5.5 — Failure-mode behavior across tiers
Defined, tested behavior for: Ollama unreachable during the embedding tier (skip to LLM/defer to queue, don't crash the batch) and during the LLM tier (defer to queue, don't bucket to "Other"); Batch-API failure/timeout if that path is chosen (retry/defer); and partial-batch failure (committed rows stay, the batch is resumable and idempotent — no all-or-nothing loss). No failure path silently assigns a wrong category.

### R5.6 — Observability
The nightly run emits structured metrics — counts per deciding tier, auto-applied vs queued, LLM calls made, failures — sufficient to compute the Success Metrics and to establish the pre-overhaul baseline.

---

## Feature 6: Transfer & debt-payment flagging

A move between the user's own accounts, or a payment to a credit card / loan / mortgage, is **not spending** — categorizing it as such double-counts (the underlying purchases are already categorized) and corrupts every spending total and budget. These must be detected and flagged distinctly, ahead of spending categorization.

### R6.1 — Flag inter-account transfers
The system detects transactions that move money between the user's own accounts (e.g. checking → savings) and flags them as transfers (reusing the existing `finance.transactions.is_transfer` column), excluding them from spending categorization. Where both legs are synced it may match counterpart transactions (opposite-sign, ~equal amount, near date); where only one leg exists it falls back to destination/merchant signals.

### R6.2 — Flag payments to liability accounts (credit card / loan / mortgage)
The system detects and flags payments to credit-card, loan, and mortgage accounts as debt-payments/transfers rather than spending. This requires knowing which accounts are liabilities — an **account-type/role attribute on `finance.accounts`, DB-driven** (NO-HARDCODING), not inferred from hardcoded merchant-name matching. (`finance.accounts` has no type column today — adding one is a prerequisite; see Dependencies.)

### R6.3 — DB-driven, override-respecting, review-queue-aware
Detection rules and account roles are DB rows. Detection respects the existing manual flag (`is_transfer_manual`) and never overrides a user's manual transfer designation. Ambiguous cases (low-confidence transfer detection) route to the review queue (Feature 4) as a distinct "transfer?" review rather than surfacing as a spending miscategorization.

### R6.4 — Precedence in the cascade
Transfer/debt-payment flagging runs **ahead of** spending categorization (Feature 2) and short-circuits it: a transaction flagged as a transfer is never assigned a spending category. This precedence is part of the defined cascade order (R2.6).

---

## Acceptance Criteria

- [ ] R1.1 ships with a fixture table of raw→normalized pairs (incl. `COSTCO WHSE #0393 MADISON HEIGHMI`→`Costco`, `SQ *SUNRISE BAKERY`→`Sunrise Bakery`), all passing, via DB-driven rules.
- [ ] A previously corrected merchant is categorized correctly on its next occurrence **without an LLM call** (merchant-memory tier hit), demonstrated by a test.
- [ ] The cascade routes a below-threshold transaction to the review queue (not "Other") and auto-applies an above-threshold one; the threshold and per-tier confidence mapping are read from the DB.
- [ ] Each automatic categorization persists its provenance (tier, confidence, model); a query reconstructs coverage and LLM-call counts from that data.
- [ ] The review-queue UI lists uncategorized/low-confidence transactions with category + confidence + rationale, supports single and bulk correction, and "apply to all from this merchant."
- [ ] A manual correction is never overwritten by a subsequent nightly run, including one that lands mid-batch.
- [ ] A checking→savings transfer and a credit-card/loan/mortgage payment are flagged as transfers (via DB-driven account roles), excluded from spending categorization and spending totals, and never assigned a spending category — demonstrated by a test.
- [ ] A labeled evaluation set scores categorization (and transfer-flagging) accuracy per model/tier; the categorizer model is a DB role defaulting to a local model, swappable without a code change.
- [ ] Regression test: the nightly categorizer first reproduces the unqualified-UPDATE failure, then (after the fix) persists `category_id` to `finance.transactions`; SimpleFin sync is scheduled to run before it.
- [ ] Failure tests: Ollama-down and parse-failure defer to the queue rather than bucketing to "Other"; partial-batch failure is resumable.
- [ ] No new hardcoded config: taxonomy, MCC map, prefix/normalization rules, user rules, merchant directory, and confidence thresholds are all DB rows read via service/API, verified by inspection.
- [ ] All new finance migrations apply cleanly on a from-empty `fresh_db` (CI build-from-baseline path); no already-applied migration was edited.

## Non-Functional Requirements

- **No hardcoding:** category taxonomy, MCC→category map, intermediary-prefix/normalization rules, user rules, merchant directory, and confidence thresholds are DB-driven (Postgres), read via service/API — never code constants. Mirror the existing `bh_skills`/`bh_patterns`/`category_aliases` data-as-config pattern. Removes the hardcoded prompt rules in `categorizer.py:113-122` and the NL→category map in `finance.py:356-366`.
- **Data safety:** parameterized SQL only; dynamic identifiers via `_quote_ident`. Schema changes are forward-only migration files starting at **0022** (next unused number), auto-applied, applying cleanly on a from-empty database (C2). Never edit an already-applied migration (checksum drift).
- **DB roles (C1/C7) — be explicit about which changes need which role:** the categorizer/override **write** path runs as the runtime `bowershub_app` role (holds finance DML) — never under read-only `finance_reader`. **R5.1 is code-only (no migration).** Migrations that ALTER owned objects — the `fn_learn_from_manual_override` trigger/function (R3.1), `finance.transactions`, the `public.transactions` view, new `finance` tables — are authored as `bowershub_migrator`-role DDL and are gated on the migrator cutover being live, or deploy crash-loops (the 2026-06-19 incident).
- **Model/cost:** all model selection via `resolve_role` against the DB model catalog — no literal model IDs. Keep the interactive review path responsive; run heavy categorization as the non-interactive nightly batch (local Ollama or Batch API per the R2.4 decision).
- **Security/RBAC:** new write endpoints respect existing auth; admin-gating of finance skills should move toward the DB-driven per-skill `min_role` rather than the hardcoded `ADMIN_ONLY_SKILLS` set (NO-HARDCODING tail — adopt if low-cost, else note as follow-up).
- **Concurrency:** the nightly batch and live user corrections both write `finance.transactions`; the batch must tolerate concurrent corrections (re-check `user_category_override` at write time, R3.4) and the `0018`-style AFTER-UPDATE learning trigger firing during a batch. No requirement may assume the batch has exclusive access.
- **Testing:** close the current **zero-coverage** gap on `categorizer.py`/`category_override.py`/the learning trigger/L1 patterns. Tests run against the **real `0001_baseline` schema via the `fresh_db` fixture** — not a hand-rolled divergent test schema (the current `test_finance_endpoints.py` mini-schema omits `user_category_override`/`memo`; it must be replaced with the baseline, per C2 reproducibility).
- **Frontend quality (C6 tail):** the review UI uses typed API responses (no `any` at the boundary) and surfaces errors via a toast/error path rather than silent failure.

## Constraints & Assumptions

- Runs on the Minisforum over Tailscale; Postgres has pgvector + Ollama `bge-m3` already running (reuse, don't rebuild the embedding stack).
- The authoritative migration set is `bowershub-ai/backend/migrations/` (`0001_baseline.sql` through `0021`); the top-level `/migrations/` dir and `backend/migrations/_archive/` are dead — ignore them.
- **Taxonomy change is a data-integrity requirement, not a free constraint** (see R-set below): the existing `finance.categories` tree is populated and in use. If a standard taxonomy (Plaid PFC: 16 primary / ~104 detailed) is adopted, it must be additive/aligned — existing `category_id` references, `category_examples` rows, and kNN-neighbor categories must remain valid or be re-mapped by a reversible migration; no retired category may orphan a transaction or an example row.
- Sequencing: this work is gated on foundation stability (now satisfied) and on the migrator-role cutover being confirmed live before deploying any owned-object DDL.
- Transaction volume is currently unmeasured; R1.5/R2.3 sizing decisions must be made against a measured figure (gather it early in implementation).

## Dependencies

- **Foundation (done):** C1/C7 scoped DB roles, C2 reproducible schema/`fresh_db` CI, dynamic model catalog (`resolve_role`).
- **Embedding stack (done):** `services/{embeddings,hybrid_retrieval,embedding_worker}.py`, migrations `0010/0011`, Ollama `bge-m3`.
- **Migrator-role cutover** (`docs/c7-db-roles-cutover.md`) must be live before deploying owned-object DDL migrations.
- **SimpleFin sync** (`services/simplefin_sync.py`) must be scheduled (R5.4) — a prerequisite for the nightly categorizer to have fresh data.
- External seed data: an open MCC→category dataset (e.g. greggles/mcc-codes or python-iso18245) and, optionally, Logo.dev for logos.
- **Account-type/role metadata on `finance.accounts`** (a new DB-driven attribute marking checking/savings/credit-card/loan/mortgage) — prerequisite for R6.2. `is_transfer`/`is_transfer_manual` already exist on `finance.transactions` and are reused (R6.1/R6.3).
- **A labeled evaluation set** of hand-verified `transaction → category` pairs (including transfer/debt-payment examples) — prerequisite for R2.4 model selection, R2.5 threshold tuning, and R2.7.

## Success Metrics

- **Auto-categorization coverage:** share of new transactions confidently categorized without landing in the review queue — target a clear improvement over baseline (baseline established via R5.6 metrics *before* the overhaul, partly because R5.1 means today's true auto-rate may be ~0).
- **LLM-call reduction:** fraction of nightly transactions resolved by the cheap tiers (rules/memory/kNN) before any LLM call — target the LLM handles only a small residue, computed from R2.6 provenance.
- **Correction stickiness:** a corrected merchant is categorized correctly on its next occurrence ~100% of the time (deterministic memory tier).
- **No regressions:** zero manually-corrected transactions overwritten by the nightly job; full backend suite green on `fresh_db`.
