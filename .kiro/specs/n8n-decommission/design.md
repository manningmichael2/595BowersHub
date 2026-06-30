# n8n Decommission — Design

## Context & current state (from code inspection, this session)

The migration off n8n is far along:
- **Native skills** (`@native_skill`) already cover balances, transactions, finance-query/ask-db, filter-transactions, categorize-*, run-categorizer, commit-bulk-update, lists, calendar, read-email, send-email, news, sports-score, weather, recall, remember, inventory(-admin), list-files.
- **`apscheduler` in `main.py`** runs ~11 jobs: simplefin sync, categorization warmup, run_categorizer, transfer-link, insight agent, embedding worker, budgets, inbox, reminders, capture digest, gameday alerts, briefing, model discovery.
- **Native service replacements** exist for the categorizer, knowledge memory, email sending, inventory, category override.

What still genuinely needs n8n at runtime:
1. **smart-capture** extract + commit (`bh_skills` rows `/webhook/smart-capture/{extract,commit}`), invoked by `routers/quick_capture.py` and the URL builder in `routers/db_browser.py:3942`.
2. Any remaining non-native `bh_skills` rows (audit-confirmed; `process-asset` + possibly finance stragglers).
3. **Boot:** `config.py` does `N8N_BASE=os.environ["N8N_BASE"]` (KeyError if unset).
4. **Cosmetic:** `healthcheck.check_n8n` / `/health --n8n`; `dashboard/app.py` `proxy_n8n` + `/api/anthropic-spend` n8n path.

## Guiding principles

- **Strangler-fig, not big-bang.** Stand up the native path beside n8n, flip the DB pointer, soak, then remove. n8n keeps running until the very end (R6.3).
- **The DB pointer is the switch.** Because skills route by `bh_skills.webhook_url`, cutover/rollback for each skill is a single row update (`native://x` ↔ `/webhook/x`) — no code redeploy to revert.
- **Reuse the native commit actions.** smart-capture *commit* shouldn't reimplement finance/list/knowledge writes — it routes intents to the services that already back the native skills.
- **Parity before removal.** The smart-capture port ships behind a parity gate (R2.4) and a soak window before anything is deleted.

## Phase map (each phase = one shippable PR; ordered)

### Phase 0 — Inventory (R1) — read-only, no code
- Grep-confirm the touchpoints (done in part this session; finalize into a checked list).
- **Owner/`ask-db` runs:** `SELECT name, webhook_url FROM bh_skills WHERE webhook_url LIKE '/webhook/%' ORDER BY name;` → the authoritative R1.2 list.
- **Owner/n8n UI:** list active workflows with schedule/webhook triggers → R1.3 list.
- Output: a short `inventory.md` in this spec dir recording each touchpoint's disposition (R1.4). No production change.

### Phase 1 — Native smart-capture (R2) — the bulk of the effort
- New `backend/services/smart_capture.py`:
  - `extract(text, asset_path|None, user, workspace) -> ExtractResult` — one `model_provider` call with the ported prompt; parses to the existing intent schema; mints an `extract_token` (HMAC over the intents + issued-at, 30-min expiry — mirror the n8n signature so the overlay's confirm→commit contract is unchanged).
  - `commit(extract_token, accepted_intents, user, workspace) -> CommitResult` — verifies the token, then dispatches each intent to the **already-native** action for its domain (finance txn, list add, knowledge remember, …) reusing those services directly. No new write logic.
- Expose as native skills `smart-capture/extract` + `smart-capture/commit` (so the existing `skill_executor.execute(...)` permission/workspace inheritance in `quick_capture.py` is preserved verbatim — only the handler becomes native).
- `routers/quick_capture.py` + `db_browser.py` smart-capture URL builder: call the native skills; keep the raw-note fallback.
- Migration `00NN_smart_capture_native.sql`: flip the two `smart-capture/*` `bh_skills` rows to `native://`. Forward-only, idempotent, guarded on the exact old `webhook_url`.
- **Parity tests (R2.4):** a fixture corpus of representative captures (grocery text, a multi-intent note, an image receipt) asserting native `extract` yields the expected intents and `commit` produces the expected rows. Token expiry + tamper rejection tested.

### Phase 2 — Remaining webhooks (R3)
- For each `port-required` row from Phase 0: implement a `@native_skill` (e.g. `process-asset` → reuse the filewriter upload + asset-metadata path Quick Capture already exercises) and flip the row to `native://` via a small migration. Anything superseded is removed with a recorded reason.
- Port or confirm-covered the n8n schedules from R1.3 (`apscheduler` job or a note that `check_inbox`/native usage logging already owns it).
- `skill_executor`: once no row points at `/webhook/`, the n8n-base dispatch branch becomes dead; leave a clear guard that raises `SkillExecutionError("n8n skill <x> no longer available")` if ever hit.

### Phase 3 — n8n-free boot & surfaces (R4)
- `config.py`: `N8N_BASE` optional (default `""`); drop from the required-vars list.
- `healthcheck.py`: remove `check_n8n`; `router_engine` drops the `/health --n8n` flag and the n8n component.
- `dashboard/app.py`: remove `proxy_n8n`; `/api/anthropic-spend` uses only the Postgres fallback; `index.html` drops the n8n UI link.
- Add a boot test (R6.2): app starts + `/health` green with `N8N_BASE` unset.

### Phase 4 — Decommission (R5) — owner-gated, deploy-side
- After a soak window on Phases 1–3 in prod: confirm the live n8n is the Portainer `ai-services` stack; stop + remove the n8n container there; remove the `n8n` service from `infrastructure/docker-compose.yml`.
- Delete `n8n-workflows/`; remove `N8N_BASE` from deploy secrets.
- Final full regression (R6.1) + the n8n-free boot check (R6.2).

## Key design decisions

- **Why native skills (not a bare service call) for smart-capture:** keeps `quick_capture.py`'s permission/workspace inheritance and telemetry identical — the router doesn't change, only the handler target. Lowest-risk swap.
- **Why keep the `extract_token` HMAC:** the overlay already does extract→(user edits intents)→commit; the token binds the commit to the reviewed intents with an expiry. Reimplementing it natively preserves that contract and the overlay needs no change.
- **Why the DB pointer, not a feature flag:** `bh_skills.webhook_url` is already the dispatch source of truth (NO-HARDCODING). Using it as the switch means rollback is a row update, not a deploy — directly satisfies R6.3.
- **Dashboard `anthropic-spend`:** the Postgres fallback already exists and is more reliable than the n8n webhook; removing the webhook path is a simplification, not a feature loss.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Native extract produces different intents than n8n (parity drift) | R2.4 corpus gate + prod soak with rollback-by-row before any deletion |
| An n8n schedule fires work nothing else does (silent data job) | R1.3 forces an explicit per-workflow disposition before Phase 4 |
| App can't boot without `N8N_BASE` mid-migration | R4.1 makes it optional in its own phase, with a boot test |
| Removing the wrong container / the repo compose isn't the live one | R5.1 confirms the Portainer `ai-services` stack first (infra memory); owner-gated |

## Test strategy

- **Phase 1:** smart-capture parity corpus (extract intents + commit effects), token expiry/tamper, raw-note fallback still works. DB-backed via `fresh_db`.
- **Phase 2:** per-ported-skill unit tests; dead-webhook guard raises cleanly.
- **Phase 3:** boots with `N8N_BASE` unset; `/health` has no n8n component; dashboard `anthropic-spend` returns from Postgres.
- **Phase 4:** full backend + frontend suites; manual Quick-Capture E2E (overlay + PWA share) in prod soak.
