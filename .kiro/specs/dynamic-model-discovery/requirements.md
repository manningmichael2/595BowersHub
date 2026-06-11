# Dynamic Model Discovery — Requirements

## Overview

Replace hardcoded Claude model IDs throughout the backend with a **DB-driven model catalog** populated by runtime discovery against the Anthropic Models API (`GET /v1/models`). Adding, swapping, or retiring a model becomes a database update — never a code change — satisfying the project's Rule #1 (NO HARDCODING) and removing the standing "silent breakage" risk where an Anthropic ID deprecation breaks every hardcoded reference at once (`project-review.md` §9.6).

Why now: the foundation blockers (C2 reproducible schema, C5 CI, C1/C7 DB roles) are closed, which §9.6 and `context-log.md` gate this work behind. Partial discovery already exists in `services/model_provider.py` — this feature makes it the single, persisted source of truth and delitteralizes the 14 hardcoded sites that depend on it.

## Feature 1: Model catalog as the single DB source of truth

### R1.1 — Persist discovered models to `bh_model_rates`
The system upserts each discovered model into the existing `public.bh_model_rates` table (keyed on the existing `UNIQUE(model_id)` constraint) so the catalog survives restarts and is admin-editable. Today discovery is in-memory only (`model_provider.py:556-571`) and lost on restart.

### R1.2 — `GET /api/models` reads from the DB catalog
The public model endpoint (`main.py:270`) serves the persisted `bh_model_rates` catalog instead of the ephemeral in-memory provider list, so the list the frontend sees, the list cost-tracking prices against, and the list admins edit are **one list**. Today `/api/models` serves `model_provider.list_models()` (ephemeral) while `bh_model_rates` is a separate table nothing reads for live cost — this requirement reconciles that split.

### R1.3 — Real capabilities and context window from the API
Discovery reads and persists the actual `display_name`, `max_input_tokens` (context window), `max_tokens` (max output), and capability flags (vision, tools, thinking, effort, structured-outputs as available) from the Models API response — not the fabricated values currently hardcoded (`model_provider.py:156-158` sets `supports_vision/supports_tools=True` and `max_output_tokens` by guess). Capability/context fields are owned by discovery (API-sourced); see R3 for pricing, which is not.

### R1.4 — Model lifecycle flags, with deactivation safety
The catalog records, per model, whether it is currently offered by the API (e.g. `is_active` / `last_seen_at`) so a model that disappears from `GET /v1/models` is marked inactive rather than silently lingering or being deleted. The table currently has no such flag, which defeats the "no silent breakage" goal. Inactive models are retained (not hard-deleted) to preserve historical cost-attribution rows that reference them.

**Deactivation must be churn-safe:** a model is marked inactive only after a *successful, complete* discovery fetch fails to include it across a defined staleness threshold (e.g. N consecutive complete fetches, or `last_seen_at` older than a bound) — never on a single error, partial page, or truncated response (R2.4 notes the API is flaky). A failed or incomplete fetch never deactivates anything.

### R1.5 — Filter to valid chat targets
Discovery filters the `GET /v1/models` result to models usable as chat/completion targets before persisting them, so non-chat entries (e.g. embedding-only or otherwise non-conversational models the endpoint may list) do not land in the catalog or surface in the public model picker.

## Feature 2: Runtime discovery via the Anthropic Models API

### R2.1 — Discover via `GET /v1/models`
The system extends the existing `AnthropicProvider.list_models()` (`model_provider.py:127-165`) to page through the full `GET /v1/models` result set (the endpoint is paginated) using the existing `ANTHROPIC_API_KEY` (`config.py:129`) — no new secret. Both the Ollama provider and any future provider continue to contribute to the same catalog.

### R2.2 — Scheduled refresh
Discovery runs on a schedule via the existing `AsyncIOScheduler` (`main.py:87-157`) so the catalog auto-updates as Anthropic ships/retires models without a deploy. No new scheduling infrastructure is introduced. The refresh interval is itself DB-driven config (per Rule #1 — e.g. a `bh_platform_settings` row), with a sane default (e.g. daily) and an enforced minimum to avoid hammering the rate-limited `/v1/models` endpoint; if a DB-driven value is impractical, the env-var exception must be justified in design.

### R2.3 — Admin-triggered refresh
An admin-only endpoint triggers an immediate catalog refresh (so a newly released model can be picked up on demand). It is gated by the existing `require_admin` dependency (`auth.py:47-51`), matching every other write/admin model endpoint.

### R2.4 — Graceful degradation when the API is unavailable
If `GET /v1/models` errors or returns non-200, the system serves the last-known persisted catalog rather than failing, and makes no destructive change (no deactivation — see R1.4). On a cold start (API down **and** catalog empty), a minimal hardcoded seed keeps the app usable. Discovery failures are logged, never fatal.

### R2.5 — Refresh is idempotent, single-flight, and auditable
A refresh that finds no changes is a no-op (idempotent — re-running it does not churn rows or timestamps beyond `last_seen_at`). Concurrent refreshes (scheduled vs admin-triggered) are serialized so the multi-step upsert + cache-invalidation critical section cannot interleave. Each refresh logs a summary of what changed — models added, deactivated, reactivated, and rows newly flagged for price confirmation — so "marked inactive" is auditable and a no-op is distinguishable from a real change.

### R2.6 — Discovery source is injectable for testing
The discovery HTTP call (today hardcoded against the live URL at `model_provider.py:131`) is injectable/fakeable so the R1–R3 behaviors (model appears, model disappears → inactive, API-unreachable degradation, price preservation) are testable without the live Anthropic API. DB-backed catalog tests run against the ephemeral Postgres the test suite already provisions (`conftest.py`).

## Feature 3: Pricing reconciliation (pricing stays admin-owned)

### R3.1 — Discovery must never clobber operator-set prices
The Models API returns **no pricing**. The upsert refreshes identity/capability columns by `model_id` but leaves `input_cost_per_mtok` / `output_cost_per_mtok` untouched for models that already exist in `bh_model_rates`, so an admin-corrected rate is never overwritten by a refresh.

### R3.2 — New models get a clearly-provisional default price
For a model seen for the first time (no existing row), the system sets a default rate via the existing name heuristic (`_infer_pricing`, `model_provider.py:24-33`) and flags the row as needing human price confirmation, so cost tracking has a value but the provisional nature is explicit rather than silently authoritative.

### R3.3 — One cost-calculation path that reads the catalog, with a safe miss-path
Live cost calculation reads pricing from the `bh_model_rates` catalog through a single function. The duplicated name-heuristics (`RouterEngine._calculate_cost` at `router_engine.py:1556-1567` and `_infer_pricing`) and the dead `CostTracker.calculate_cost` (`cost_tracker.py:126-135`, no callers) are consolidated/removed so pricing has exactly one home.

**The miss-path must not silently under-bill:** if the invoked model has no catalog row or a NULL price, the cost function falls back to the provisional name heuristic and logs a warning — it must never return cost 0 for an unknown/unpriced model. Today `_calculate_cost` always yields a non-zero heuristic; the consolidation must preserve that floor, not regress it (which would be the opposite of the "no silent breakage" goal).

### R3.4 — Catalog key normalization across providers / dangling aliases
Cost lookup and role resolution operate on a normalized model key so a runtime invocation that differs from the discovered key still resolves — e.g. a Bedrock invocation `us.anthropic.claude-…-v1:0` must map to the corresponding catalog/pricing entry, not miss. If a role alias points at a model_id that is no longer active (renamed/retired away by the API), resolution fails closed to a known-good active model in that tier and emits an alert, rather than returning a dead ID to the caller.

## Feature 4: Role/alias resolution — eliminate hardcoded model IDs

### R4.1 — DB-driven model role aliases, with a defined day-one seed
The system resolves logical roles — "current Haiku", "current Sonnet", "current Opus", "current local" — to concrete model IDs from the database (a role→model_id mapping in/alongside `bh_model_rates`). Changing which concrete model fills a role is a DB update, per §9.6.

**The migration must seed every role to an existing, active catalog row** — and must *not* copy the current config constants verbatim, because `config.py:62` (`SONNET_MODEL = "claude-sonnet-4-5-20250514"`) is stale and matches **no** `bh_model_rates` row. The seed maps each role to a real seeded `model_id` (haiku/sonnet/opus → the corresponding current Anthropic rows; local → the current Ollama row, e.g. `llama3.2:3b`); the exact IDs are fixed at migration time against the live seed rows. Post-migration, every role must resolve to a non-null, existing, active model.

### R4.2 — Tier/role config resolves from the DB, not constants
The tier model selections currently in `config.py` (`HAIKU_MODEL`, `SONNET_MODEL`, `LOCAL_MODEL` at `config.py:61-63`, the latter already stale) resolve from the role aliases (R4.1). This single seam covers the 8 `router_engine.py` call sites that already reference `config.HAIKU_MODEL/SONNET_MODEL` rather than literals.

### R4.3 — Replace remaining inline literals
The inline hardcoded model strings are replaced with role-alias lookups. This covers **both** Anthropic and local/Ollama literals (the "current local" role aliases the latter):
- Anthropic: `services/finance.py:403` (ask_db), `services/context_capture.py:62`, `services/scheduled_prompts.py:66`, `services/hook_engine.py:423`, `services/tool_router.py:38`.
- Local/Ollama: `services/categorizer.py:30`, `services/inbox_cleaner.py:26`, `services/knowledge.py:238`, `services/router_engine.py:670`, `services/local_intelligence.py:23`.

After this, no `claude-*` or `llama*`/Ollama literal remains as a live default in backend service code. The only permitted residual literals are the documented cold-start fallback seed (R2.4) and migration seed data. (If any enumerated site is deliberately deferred, it must be scope-excluded explicitly and the acceptance grep's allow-list updated to match — no silent gaps.)

### R4.4 — Default chat model resolves from the DB
`get_default_chat_model()` (`model_provider.py:573-581`) returns the role-resolved default rather than the hardcoded `claude-sonnet-4-5`.

## Feature 5: Management & frontend surface

### R5.1 — Admin can curate the catalog
The existing admin endpoints (`GET/PATCH /api/admin/models`, `admin.py:150-178`) continue to let an admin view and edit catalog rows (notably pricing and role assignments), extended as needed for the new columns/aliases. All writes remain `require_admin` and parameterized. Any newly-editable column (price-confirm flag, role assignment) is added as a typed field on the request model (`ModelRateUpdate`), never as a free-form column name — the existing `f"{field} = ${idx}"` builder (`admin.py:159`) is safe only because that field set is a closed Pydantic whitelist.

### R5.2 — Frontend model picker contract is unchanged; pricing stays admin-only
The public `/api/models` response continues to expose at least `id`, `provider`, and `display_name` so `ModelPicker.tsx` (`frontend/src/components/ModelPicker.tsx:25`) needs no contract change. New **capability/context** fields are additive on the public endpoint; **pricing** fields ($/mtok) are *not* added to the public endpoint — they remain on the `require_admin` endpoint, so per-token cost data is not exposed publicly as a side effect of unifying the lists.

## Acceptance Criteria

- [ ] A model newly returned by a (fakeable) `GET /v1/models` appears in `bh_model_rates` after a refresh, with API-sourced capabilities/context, and is offered by `GET /api/models` — with zero code changes.
- [ ] An admin-edited price on an existing model survives a subsequent discovery refresh (not clobbered).
- [ ] A brand-new model gets a provisional price and is flagged as needing confirmation.
- [ ] A model absent from N consecutive **complete** fetches is marked inactive (not deleted) and stops being offered, while historical cost rows referencing it still resolve. A single failed/partial fetch deactivates nothing.
- [ ] With the Anthropic API unreachable, `GET /api/models` still returns the last-known catalog and no model is deactivated; cold-start with empty catalog still serves a minimal seed.
- [ ] Immediately after the migration runs on the live DB, every role ("current Haiku/Sonnet/Opus/local") resolves to an existing, active model row, and every currently-offered model is still offered (no row goes dark).
- [ ] Cost calc for a model with no catalog row / NULL price returns the non-zero provisional heuristic and logs a warning — never 0.
- [ ] `grep -rE "claude-[a-z0-9.-]+|llama[0-9]" bowershub-ai/backend --include=*.py` outside `migrations/`, tests, and the single documented cold-start fallback/seed returns no live-default model literals (all sites in R4.3 covered, or explicitly scope-excluded in the allow-list).
- [ ] Changing the "current Sonnet" role alias in the DB changes which model the L3 router tier and ask_db use, with no redeploy and no per-call DB round-trip on the hot path.
- [ ] A refresh logs a change summary (added/deactivated/reactivated/price-flagged); a no-change refresh is a logged no-op.
- [ ] Full backend suite green (`PYTHONPATH=. .venv/bin/python -m pytest -q`); `npx tsc --noEmit` clean.

## Non-Functional Requirements

- **No hardcoding:** the model catalog and role aliases are DB-driven (Postgres), read via API — never code constants (Project Rule #1, `595bowershub-project.md:5`). The only permitted hardcoded model IDs are the documented cold-start fallback seed (R2.4) and migration seed data.
- **Data safety:** all SQL parameterized; non-parameterizable identifiers via `_quote_ident` (`db_browser.py:400`). Schema change is a single forward-only migration `0005_*.sql` (next free number) auto-applied by `database.py:90`; never edit a shipped migration (checksum-immutable). Must keep the schema reproducible-from-zero (C2). The migration must **backfill the 8 existing `bh_model_rates` seed rows** for the new columns — existing rows get `is_active=true`, `last_seen_at=now()`, and `needs_price_confirmation=false` (admin-curated rows must not be falsely flagged or hidden) — so no currently-offered model disappears across the migration.
- **Testability:** discovery is injectable (R2.6) so all discovery-dependent acceptance criteria are exercisable without the live Anthropic API; catalog/cost tests run against the suite's ephemeral Postgres.
- **Security / RBAC:** discovery uses the existing `ANTHROPIC_API_KEY` env var — no new secret, no key in code/repo. Every refresh/write endpoint is `require_admin`-gated; `GET /api/models` stays public-read.
- **Performance:** role-alias and default-model resolution must be cheap on the hot path — the router resolves a model per message, so alias lookups are cached in-process (with invalidation on refresh/admin edit), not a DB round-trip per LLM call.
- **Resilience:** discovery is best-effort and never blocks app startup or request handling; failures degrade to the persisted catalog and are logged.

## Constraints & Assumptions

- Backend is FastAPI/Python at `bowershub-ai/backend/`; deploys on the Minisforum over Tailscale; one Postgres (`finance` DB) is the canonical store.
- The Anthropic Models API returns identity, `display_name`, context window, and capabilities — **but no pricing**; pricing remains operator-curated (R3). This is a hard constraint, not a design choice.
- `bh_model_rates` already exists with `UNIQUE(model_id)` and columns mapping 1:1 to `ModelInfo` (`message.py:8-17`); it lacks alias and lifecycle columns, which this feature adds.
- **Out of scope:** rewriting n8n workflows (which hardcode `claude-haiku-4-5-20251001` and a pricing map). n8n is a downstream beneficiary that unblocks later when those skills migrate to native Python reading this catalog (`project-review.md:343`, steering item #6). Non-Anthropic providers (Ollama/Bedrock) keep working but are not the focus.

## Dependencies

- Existing `services/model_provider.py` discovery + provider abstraction (extended, not replaced).
- Existing `AsyncIOScheduler` in `main.py` (for R2.2).
- Existing `bh_model_rates` table + admin CRUD (`admin.py`) and forward-migration runner (`database.py`).
- `ANTHROPIC_API_KEY` env var (already required, `config.py:87,129`).

## Success Metrics

- **Hardcoded live-default model literals in backend service code:** all enumerated sites (R4.3: ~10 inline literals across Anthropic + Ollama, plus the `config.py` tier constants) → 0 (excluding the single documented cold-start fallback seed and migration seed data).
- **Model lists reconciled:** 2 disconnected lists (ephemeral provider cache vs `bh_model_rates`) → 1 persisted source.
- **Time to adopt a newly released Anthropic model:** from "edit + redeploy across N files" → "0 (auto-discovered) or 1 DB row for pricing/role."
- **Cost-calculation code paths for model pricing:** 3 (router heuristic + `_infer_pricing` + dead `CostTracker`) → 1 catalog-reading function.
