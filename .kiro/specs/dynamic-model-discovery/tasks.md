# Dynamic Model Discovery — Tasks

> Each task traces to one or more requirements in `requirements.md`. Work top-to-bottom; the order follows the design's phased, git-revertable rollout (T0 precondition → P0 migration → P1 discovery shadow-writes → P2 read cutover → P3 cost cutover → P4 delitteralize → P5 cleanup). Nothing on the hot cost path changes until P3, and that is gated by the cost-parity review.

## Task 1: Verify the Anthropic SDK discovery fields (precondition T0) — ✅ DONE
- **Effort:** S
- **Dependencies:** none
- **Requirements:** R1.3, R2.1
- [x] Introspect the pinned `anthropic` SDK (or make one live `client.models.list()` call) to confirm which fields are exposed: `id`, `display_name`, `max_input_tokens`, `max_tokens`, and the `capabilities` mapping shape.
- [x] Record the result (and any missing fields) as a short note in the spec/PR; decide the per-field fallback (absent field → `NULL`/`false`, never the old fabricated `True/4096` guesses).
- [x] Confirm `models.list()` auto-paginates on iteration (do not rely on `.data`).
- [x] **Tests:** none (investigation task); output is the documented field-availability matrix that gates Task 3.
- **Outcome:** `anthropic==0.105.0`; all design-assumed fields are real **and** populated live (no NULL fallback needed today; defensive guard kept). Full matrix + live result in `T0-sdk-verification.md`. **Surfaced a gating finding:** the alias seed's bare `claude-sonnet-4-5` / `claude-opus-4-5` IDs are **not** returned by `models.list()` (it returns canonical dated IDs), so they'd be deactivated by discovery and break `resolve_role` — must be resolved before Task 2/Task 4 (see that note + the decision below).

## Task 2: Migration `0005_dynamic_model_discovery.sql` (phase P0) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.4, R3.2, R4.1, R2.2, R2.5
- **Outcome:** `migrations/0005_dynamic_model_discovery.sql` written + validated on a throwaway PG16 (`0001`→`0005` from zero): applies clean, guard passes, 10 rows all active / 0 falsely-flagged, 2 canonical rows inserted, all 4 aliases resolve to active rows, `bh_model_refresh_log` + 3 discovery settings present, and **idempotent on re-run** (`ADD COLUMN/CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING`). Safe for the live DB (additive, guarded); deploys on next app restart per the owner. (`0002`–`0004` are role-only migrations that don't touch these tables; real chain applies `0005` after them.)
- [ ] Add lifecycle/capability/price-confirm columns to `bh_model_rates` (`is_active`, `last_seen_at`, `missed_fetch_count`, `needs_price_confirmation`, `max_input_tokens`, `supports_thinking`, `supports_effort`, `supports_structured_outputs`) with the design's defaults.
- [ ] Explicit backfill `UPDATE` of the existing seed rows (`is_active=true`, `last_seen_at=now()`, `missed_fetch_count=0`, `needs_price_confirmation=false`).
- [ ] Insert the canonical alias-target rows that `models.list()` returns but `0001` lacks (`claude-sonnet-4-6`, `claude-opus-4-5-20251101`) with current known prices, `ON CONFLICT DO NOTHING` (T0 decision — so aliases sit on discovery-refreshed rows). `claude-haiku-4-5-20251001` (id 1) and `llama3.2:3b` (id 10) already exist.
- [ ] Create `bh_model_aliases` (`role` PK, `model_id` FK → `bh_model_rates(model_id)`); seed to the **canonical discoverable IDs**: haiku→`claude-haiku-4-5-20251001`, sonnet→`claude-sonnet-4-6`, opus→`claude-opus-4-5-20251101`, local→`llama3.2:3b` (per the approved T0 decision — not the stale bare/`config.py` forms).
- [ ] Add the `DO $$ ... RAISE EXCEPTION` guard that aborts if any seeded role fails to resolve to an active row.
- [ ] Create `bh_model_refresh_log` (audit table). Insert the three `bh_platform_settings` rows (`model_discovery_interval_hours`, `model_discovery_stale_misses`, `model_discovery_enabled`) with `ON CONFLICT (key) DO NOTHING`.
- [ ] **Migration:** `bowershub-ai/backend/migrations/0005_dynamic_model_discovery.sql` (forward-only, next free number, parameterized DDL, single transaction).
- [ ] **Tests:** apply against a fresh empty PG (from-zero `0001→…→0005`) and against a prod-like clone; assert all 8 rows backfilled active, all 4 aliases resolve to active rows, guard passes, and a re-run is idempotent.

## Task 3: Discovery sources — `DiscoverySource` + Anthropic/Ollama/Static (phase P1) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R2.1, R1.3, R1.5, R2.4, R2.6
- **Outcome:** `services/model_catalog.py` (discovery section): `DiscoveredModel` (no price), `DiscoveryResult{models, complete}`, `DiscoverySource` Protocol, `AnthropicDiscoverySource` (async SDK `models.list()`, auto-paged, real caps, chat-target filter, partial→`complete=False`), `OllamaDiscoverySource`, `StaticDiscoverySource` (cold-start seed, IDs match the 0005 aliases, `complete=False`). Tests `tests/test_model_discovery.py` (9 pass, no network) incl. a `FakeDiscoverySource` with an `asyncio.Event` gate for Task 4's single-flight test. **Live smoke-tested**: real `discover()` → complete, 9 models, all 3 Anthropic alias targets discovered (T0 fix holds end-to-end).
- [ ] Define `DiscoveredModel` (no price field) and the `DiscoverySource` Protocol returning `DiscoveryResult{models, complete}` in `services/model_catalog.py`.
- [ ] `AnthropicDiscoverySource` via the SDK `client.models.list()` (paged), mapping real `display_name`/`max_input_tokens`/`max_output_tokens`/capabilities; any exception/partial page → `complete=False`.
- [ ] Chat-target filter (R1.5): keep `claude-*` chat targets; defensive fallback to an id-prefix rule when `capabilities` is unavailable; never silently drop a chat model.
- [ ] `OllamaDiscoverySource` (`/api/tags`, NULL caps) and `StaticDiscoverySource` (the single documented cold-start seed — replaces `_fallback_models`). **Pin the static seed model_ids to exactly the alias-seed ids** (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-5-20251101`, `llama3.2:3b` — the canonical IDs per the T0 decision) — not the dateless `_fallback_models` forms — so a cold-start catalog still satisfies the alias FK and `resolve_role`.
- [ ] Sources are constructed **outside** `ModelProvider` and injected, so tests can substitute a `FakeDiscoverySource`; the fake exposes an injectable `asyncio.Event` gate (a suspension point inside discovery) so single-flight serialization is observably testable (Task 4).
- [ ] **Tests:** `FakeDiscoverySource` drives model-appears / model-disappears / API-down(`complete=False`) / empty-cold-start; assert chat-target filtering, that no network is hit, and that **every alias role resolves against a catalog built only from the `StaticDiscoverySource` seed** (cold-start coherence).

## Task 4: `CatalogRefresh` orchestration — upsert, deactivation, single-flight, audit (phase P1) — ✅ DONE
- **Effort:** L
- **Dependencies:** Task 2, Task 3
- **Requirements:** R1.1, R1.4, R3.1, R3.2, R2.5, R2.4
- **Outcome:** `CatalogRefresh` in `services/model_catalog.py` — single-flight `asyncio.Lock`; upsert by `model_id` that refreshes identity/caps + `last_seen_at`/`missed_fetch_count=0`/`is_active` but **never** touches price/`needs_price_confirmation` on existing rows (R3.1); new rows get the byte-identical `_infer_pricing` provisional price + flag (R3.2); provider-scoped, alias-protected, churn-safe deactivation via `missed_fetch_count` (R1.4); cold-start static seed when empty (R2.4); `RefreshSummary` + `bh_model_refresh_log` audit row + `invalidate()` hook (wired in Task 5). Tests `tests/test_model_catalog_refresh.py` (4 DB-backed) cover price-preserve+new-flag, churn/alias/provider deactivation, incomplete-deactivates-nothing, single-flight+audit+no-op. **13/13** discovery+refresh tests green on ephemeral PG.
- [ ] `refresh(trigger)` under an `asyncio.Lock` (single-flight): run sources, compute `complete_providers`.
- [ ] Upsert by `model_id` (`ON CONFLICT DO UPDATE`) writing identity/caps/context + `last_seen_at`/`missed_fetch_count=0`/`is_active=true`, **omitting both price columns** for existing rows (preserve operator prices, R3.1); new rows get heuristic provisional price + `needs_price_confirmation=true` (R3.2).
- [ ] Provider-scoped, churn-safe deactivation: increment `missed_fetch_count` only for `complete_providers`' unseen rows; deactivate at the `stale_misses` threshold; **never deactivate a model that is the target of a role alias** (alias-protection invariant, T0 decision); never delete.
- [ ] Compute `RefreshSummary{added, reactivated, deactivated, price_flagged}` (reactivated from prior `is_active=false`), write `bh_model_refresh_log` + structured log; invalidate the in-process caches.
- [ ] On any incomplete fetch: serve last-known, deactivate nothing (R2.4).
- [ ] **Tests:** (ephemeral Postgres) admin-edited price survives a refresh; new model → provisional+flagged; absent across N complete fetches → inactive (single incomplete fetch deactivates nothing); an **alias-targeted** model absent from N complete fetches is **not** deactivated (alias-protection); a complete Anthropic-only fetch does **not** age-out Ollama/Bedrock rows (provider-scoped); concurrent admin+scheduled refresh serialize — proven by holding one refresh open at the injected `asyncio.Event` gate and asserting the second blocks until release; no-op refresh is a logged no-op.

## Task 5: Catalog read + Resolver + singleton + lifespan cache warm (precondition T1) — ✅ DONE
- **Effort:** M
- **Dependencies:** Task 2, Task 4
- **Requirements:** R4.1, R4.4, R3.4, R2.6
- **Outcome:** `Resolver` in `services/model_catalog.py` — in-process cache of all rows (incl. inactive, for historical cost) + role aliases; `resolve_role`/`default_chat_model` off the cache (no per-call DB hit), fail-closed to a same-tier active model on a dangling/inactive alias; `row_for_cost`/`price_for` exact-match-first (Bedrock reads its own row — B1) with same-provider `normalize_key` fallback; `list_active`/`get` for the read path. Module singleton `get_resolver()`/`init_resolver(pool)` (mirrors `database.get_pool`); warmed in `main.py` lifespan **after `run_migrations`, before the scheduler** (T1). `CatalogRefresh.invalidate` now awaits an async hook so refresh rebuilds the cache. Tests `tests/test_model_resolver.py` (5 DB-backed) prove role resolution, cache-not-DB (mutate-without-reload), fail-closed, exact-match Bedrock + inactive cost lookup, and refresh→invalidate→reload. **18/18** model-catalog tests green.
- [ ] `Catalog.list_active()` and the read-through in-process cache; `get_resolver()` module-level singleton (mirrors `database.py` `get_pool()`).
- [ ] `Resolver.resolve_role(role)` and `default_chat_model()` off the cache (no per-call DB hit); fail-closed to a known-good active tier model + alert on inactive/dangling alias.
- [ ] Exact-match-first key lookup with a same-provider `normalize_key` fallback (so Bedrock rows id 5/14 resolve to their own priced row, never collapsed onto bare `claude-*`).
- [ ] Warm the resolver + catalog caches in `lifespan` **after `run_migrations(pool)` (`main.py:62`) and before the scheduler block (`main.py:87`)** so the `0005` columns exist before the first read; define empty-cache reads as single-DB-read-then-memoize (never crash).
- [ ] **Tests:** post-migration every role resolves to an active row; repoint `sonnet` alias → L3/ask_db target changes with no DB round-trip on the hot path; dangling alias fails closed; Bedrock key resolves to its own row.

## Task 6: Scheduler job + admin refresh endpoint (phase P1) — ✅ DONE
- **Effort:** S
- **Dependencies:** Task 4
- **Requirements:** R2.2, R2.3, R2.5
- **Outcome:** `main.py` lifespan builds the shared `CatalogRefresh` (`build_default_sources(config)`, `invalidate=resolver.reload`) on `app.state` and adds an `AsyncIOScheduler` `model_discovery` job — interval from `get_discovery_config` (DB-driven, floored to ≥6h), with the `model_discovery_enabled` lever checked at fire time (runtime toggle, no restart). `POST /api/admin/models/refresh` (`require_admin`) shares the single-flight instance and runs even when the lever is off (explicit operator action); returns the `RefreshSummary`. Tests `tests/test_model_discovery_wiring.py` (4): require_admin (401/403), admin trigger invokes refresh, 503 when uninitialized, interval-clamp + enabled lever. **22/22** model-discovery tests green; edited files compile clean.
- [ ] Add the `AsyncIOScheduler` job (`main.py`) reading `model_discovery_interval_hours` and clamping to the enforced floor (≥ 6h), `replace_existing=True`, no-op when `model_discovery_enabled` is false.
- [ ] `POST /api/admin/models/refresh` (`Depends(require_admin)`) → `CatalogRefresh.refresh(trigger="admin")`, returns the `RefreshSummary`. Define behavior when `model_discovery_enabled` is false: the **admin** trigger still runs (it's an explicit operator action — only the scheduled job is gated by the setting).
- [ ] **Tests:** admin refresh requires admin (401/403 without); a sub-floor `model_discovery_interval_hours` DB value is clamped to the floor; disabling `model_discovery_enabled` stops the scheduled job but an admin `POST /refresh` still works.

## Task 7: `GET /api/models` reads the catalog via a public DTO (phase P2) — ✅ DONE
- **Effort:** S
- **Dependencies:** Task 5
- **Requirements:** R1.2, R5.2
- **Outcome:** `/api/models` now serves `get_resolver().list_active_public()` instead of the ephemeral provider list — the DB catalog is the single source for the picker (R1.2). `Resolver.list_active_public()` is an **explicit allowlist projection** (`id`=model_id string + `provider`/`display_name` + capability/context), **no price fields** and no internal lifecycle columns, so future `bh_model_rates` columns can't auto-leak (R5.2). Picker contract (`id`/`provider`/`display_name`) unchanged. Test asserts string-id, active-only, exact allowlist, no `*cost*`. **6/6** resolver tests green; frontend `npx tsc --noEmit` clean (`ModelPicker.tsx` untouched).
- [ ] Repoint `main.py:270` to `Catalog.list_active()`, serialized through a dedicated public DTO that is an **explicit allowlist projection** (`id/provider/display_name` + additive `supports_*`/context) — not `dict(row)` minus price — so future `0005`/later columns never auto-surface on the public endpoint.
- [ ] **Tests:** `/api/models` returns active rows with the unchanged `id/provider/display_name` contract and **no** `*_cost_per_mtok` fields; `frontend npx tsc --noEmit` + `npm test` clean (`ModelPicker.tsx` unchanged).

## Task 8: Consolidate the cost path + cost-parity gate (phase P3)
- **Effort:** M
- **Dependencies:** Task 5
- **Requirements:** R3.3, R3.4
- [ ] Implement `Catalog.cost_for(model_id, in, out)` as the single cost function: exact-match price (against **all** rows incl. inactive), same-provider normalize fallback, then non-zero heuristic + WARN on miss/NULL (never 0).
- [ ] Repoint **all three** `RouterEngine._calculate_cost` callers (`router_engine.py:239`, `:1203`, `:1436` — confirm via `grep -n _calculate_cost services/router_engine.py`), then delete the definition + heuristic (`:1556-1567`); fold `_infer_pricing` in as the one private heuristic inside the cost function; delete the dead `CostTracker.calculate_cost` (`cost_tracker.py:126-135`).
- [ ] Build the cost-parity artifacts: (a) a permanent `==` regression test that the miss-path returns the identical non-zero value the old heuristic produced; (b) a human-reviewed old-vs-new diff report over recent invoked models — ship P3 on sign-off of the diff, not on equality.
- [ ] **Tests:** unknown/NULL-price model → non-zero heuristic + logged WARN (never 0); the miss-path parity regression test covering the L2/tool-result (`:239`) and `:1203` paths, not just L3; a Bedrock id prices via its own row (id 5/14), not the bare `claude-*` row; an **inactivated** model still prices from its retained row (not the heuristic).

## Task 9: Delitteralize tier config + inline literals + default model (phase P4)
- **Effort:** M
- **Dependencies:** Task 5, Task 8 (cost cutover ships first, so the P3 parity diff reflects the post-delitteralize invoked-model set)
- **Requirements:** R4.2, R4.3, R4.4
- [ ] Replace `self.config.HAIKU_MODEL/SONNET_MODEL/LOCAL_MODEL` reads (8 `router_engine` sites) with `get_resolver().resolve_role(...)`; remove the now-unused `config.py:61-63` constants per the design (one site per commit).
- [ ] Replace the inline literals: Anthropic (`finance.py:403`, `context_capture.py:62`, `scheduled_prompts.py:66`, `hook_engine.py:423`, `tool_router.py:38`) and Ollama/local (`categorizer.py:30`, `inbox_cleaner.py:26`, `knowledge.py:238`, `router_engine.py:670`, `local_intelligence.py:23`) with resolver calls — deleting module-level model constants (resolved at use-time, not import).
- [ ] **Remove the `os.environ.get(..., "literal")` model overrides** (`tool_router.py:38`, `local_intelligence.py:23`, `hook_engine.py:423` `config.get("model", ...)`) — the DB is the single source of truth (Rule #1); do not leave an env value as a higher-precedence fallback (which would also defeat the acceptance grep).
- [ ] Point `get_default_chat_model()` (`model_provider.py:573`) at `get_resolver().default_chat_model()`.
- [ ] **Tests:** each de-littered site selects the role-resolved model; changing a role alias changes the model used with no redeploy; **`ask_db` still works after the wire-id change** (`finance.py:403` now sends the resolved `claude-haiku-4-5-20251001` instead of the dateless form — explicit behavior-change test on the C1-sandboxed path); existing service tests still pass.

## Task 10: Admin curation surface — typed fields + alias repoint endpoint
- **Effort:** S
- **Dependencies:** Task 2, Task 5
- **Requirements:** R5.1
- [ ] Extend `ModelRateUpdate` (`admin.py`) with **typed** `is_active`/`needs_price_confirmation` fields (closed Pydantic whitelist — never a free-form column name); `GET /api/admin/models` returns the new columns + joined alias assignments.
- [ ] Add `PUT /api/admin/models/aliases/{role}` (`require_admin`, parameterized) to repoint a role to an active model; invalidate the resolver cache on success.
- [ ] **Tests:** admin can edit price/flags and repoint an alias; both require admin; `ModelRateUpdate` rejects unknown fields; repoint to an inactive model is refused.

## Task 11: Cleanup, full-suite + delitteralization gate (phase P5)
- **Effort:** S
- **Dependencies:** Task 7, Task 8, Task 9, Task 10
- **Requirements:** R4.3
- [ ] Remove any dead legacy constants/paths left behind; confirm the only residual model literals are the `StaticDiscoverySource` cold-start seed and migration seed data.
- [ ] **Tests:** acceptance grep `grep -rE "claude-[a-z0-9.-]+|llama[0-9]" bowershub-ai/backend --include=*.py` outside `migrations/`/tests returns only the documented seed; full backend suite `PYTHONPATH=. .venv/bin/python -m pytest -q` green; CI from-empty migration build passes.

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (validated by `.claude/hooks/spec-validate.py`).
- [ ] No hardcoded live-default model literals remain in backend service code (only the documented cold-start seed + migration seed) — Rule #1.
- [ ] `bh_model_rates` is the single source of truth; `/api/models`, cost calc, and the picker all read it; discovery refreshes it on schedule and never clobbers operator prices.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`); schema builds from zero in CI.
- [ ] `context-log.md` updated with a dated entry.
