# Dynamic Model Discovery — Design

> Satisfies the requirements in `requirements.md`. Requirement IDs are referenced inline (e.g. "satisfies R1.2"). This design is the synthesis of three tournament approaches (minimal-change / ideal-architecture / risk-first); see **Design Decisions** at the end for what was taken from each and why.

## Architecture Overview

Today there are **two disconnected model lists**: an ephemeral in-process cache (`ModelProvider.list_models()`, `model_provider.py:556`) that `/api/models` serves (`main.py:270`), and the `bh_model_rates` table that *nothing reads on the live cost path*. Cost is a name heuristic that ignores the DB (`router_engine.py:1556`); tier selection reads `config.py:61-63` constants, one of which (`SONNET_MODEL`) matches no DB row.

The end state makes **`bh_model_rates` the single source of truth**. A new cohesive module, `services/model_catalog.py`, owns four internal seams behind one facade:

```
   Anthropic /v1/models ──▶ DiscoverySource (injectable) ──┐  caps+context, NO price
   Ollama /api/tags     ──▶   AnthropicDiscoverySource     │
                              OllamaDiscoverySource         │  DiscoveryResult{models, complete}
   (cold start)         ──▶   StaticDiscoverySource ────────┤
                                                            ▼
  scheduler ─┐                                  ┌──────────────────────────────┐
  admin POST ┼──single-flight asyncio.Lock────▶│ CatalogRefresh.refresh()      │ R2.2/R2.3/R2.5
             │                                  │  upsert identity+caps by id   │ R1.1/R3.1
             │                                  │  preserve operator prices     │
             │                                  │  provisional price + flag     │ R3.2
             │                                  │  churn-safe deactivation      │ R1.4
             │                                  │  write refresh-log + invalidate caches
             │                                  └───────────────┬──────────────┘
             │                                                  ▼
             │                     ┌──────────────── bh_model_rates ───────────┐  single source of truth
             │                     │ identity | caps | context | lifecycle |   │
             │                     │ price (operator-owned) | needs_confirm    │
             │                     └────┬──────────────────────────┬───────────┘
             │                          ▼                          ▼
             │            ┌──────────────────────┐   ┌──────────────────────────┐
  /api/models│ caps only  │ Catalog (read+cache) │   │ bh_model_aliases (FK)    │  R4.1
  ───────────┴──────────▶ │  list_active()       │   │  role → model_id         │
                          │  cost_for(model)─────┼─▶ │  cached resolver         │  R4 (no per-call DB)
                          └──────────────────────┘   └──────────────────────────┘
```

What's **new**: `services/model_catalog.py` (the four seams), one migration `0005`, one admin endpoint + one scheduler job. What's **reused**: `bh_model_rates`, `bh_platform_settings`, the `AsyncIOScheduler` (`main.py:87`), admin CRUD (`admin.py:150-178`), `require_admin`, the migration runner (`database.py:90`), the `anthropic` SDK already imported at `model_provider.py:50`.

## Components

All new code lives in **`bowershub-ai/backend/services/model_catalog.py`** (one module, internal seams clearly named — chosen over a 5-file package to match the repo's flat-service convention and keep the diff reviewable; it can be promoted to a package later if it grows).

### `DiscoverySource` (discovery seam)
- **`DiscoveredModel`** dataclass: `id, provider, display_name, max_input_tokens, max_output_tokens, supports_vision, supports_tools, supports_thinking, supports_effort, supports_structured_outputs`. **No price field** — the hard constraint (Models API has no pricing) is enforced at the type level (R1.3, R3).
- **`DiscoverySource` (Protocol)**: `async def discover(self) -> DiscoveryResult` where `DiscoveryResult = {models: list[DiscoveredModel], complete: bool}`. `complete` is the load-bearing primitive for churn-safe deactivation (R1.4) — a partial/errored/non-200 fetch returns `complete=False` and the refresh never deactivates against it (R2.4).
- **`AnthropicDiscoverySource`**: uses the official SDK `client.models.list()` (Technology Choices) — auto-paginates, returns `id`, `display_name`, `max_input_tokens`, `max_tokens`, and a `capabilities` dict. Any exception/partial page → `complete=False`.
  - **R1.5 chat-target filter — concrete rule:** keep a model only if it is a usable text-conversation target. Primary signal: the `id` is in the chat family (`claude-*`) **and** the `capabilities` dict does not mark it embedding-only; if `capabilities` exposes a structured-output / messages capability leaf, require it. Because the exact `capabilities` schema varies by SDK version (see precondition T0), the filter is implemented defensively: unknown/missing capability → fall back to an allow-by-id-prefix rule (`claude-`), never silently drop a chat model.
  - **SDK field fallback (M3/R1.3):** field availability is verified for the installed `anthropic` version in precondition **T0** before build. If `max_input_tokens` / `capabilities` are absent on the pinned SDK, the source writes `NULL` context and `false`/`NULL` capability flags rather than guessing — "as available" per R1.3. The design does **not** re-introduce the old fabricated `True/True/4096` guesses (`model_provider.py:156-158`).
- **`OllamaDiscoverySource`**: keeps `/api/tags`; contributes to the same catalog (R2.1). Ollama's API supplies **no** capability/context metadata, so Ollama rows get `NULL` `max_input_tokens` and `false` capability flags — acceptable for the picker (display only) and for R1.5 (Ollama IDs are local-chat targets by construction). `complete=False` if `/api/tags` errors.
- **`StaticDiscoverySource`**: the documented cold-start seed (R2.4) — the **only** place hardcoded model literals live, replacing the scattered `_fallback_models` (`model_provider.py:167`, which uses dateless `claude-haiku-4-5`/`claude-sonnet-4-5`). This is the single residual the acceptance grep allow-lists. **Its model_ids MUST match the alias-seed model_ids exactly** (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-5-20251101`, `llama3.2:3b` — the canonical IDs per the T0 decision) — otherwise a cold-start catalog built only from the static seed would not contain the rows the aliases point at, and `resolve_role` would fail closed on first boot. (Note: the old dateless forms in `_fallback_models`/`get_default_chat_model` are *not* carried over.)
- Injectable: `CatalogRefresh` takes `list[DiscoverySource]`; tests pass a `FakeDiscoverySource` with scripted pages (R2.6) — no live URL reached.

### `CatalogRefresh` (orchestration seam)
`async def refresh(self, *, trigger: str) -> RefreshSummary` — the critical section, single-flight under an `asyncio.Lock` (R2.5):
1. Run every `DiscoverySource`. Compute `complete_providers` = the set of providers whose source returned `complete=True` this run. Only those providers' rows are eligible for miss-counting/deactivation (R1.4/R2.4) — a provider whose source was down (`complete=False`) is left entirely untouched.
2. Upsert by `model_id` (`INSERT ... ON CONFLICT (model_id) DO UPDATE`): the `DO UPDATE SET` writes identity/capability/context columns + `last_seen_at=now()`, `missed_fetch_count=0`, `is_active=true`, and **deliberately omits the two price columns** so operator prices are never clobbered (R3.1). Capture each conflicting row's prior `is_active` (via `RETURNING ... , (xmax<>0) ...` or a pre-read) so `reactivated` = rows that were `is_active=false` before this upsert. New rows get a provisional price via the name heuristic and `needs_price_confirmation=true` (R3.2).
3. **Provider-scoped, churn-safe deactivation.** For each provider in `complete_providers`, increment `missed_fetch_count` for that provider's rows **not** seen this run, and deactivate where the count reaches the threshold — one statement, partitioned by provider so a complete Anthropic fetch can never age-out Ollama/Bedrock rows (M5):
   ```sql
   UPDATE public.bh_model_rates
      SET missed_fetch_count = missed_fetch_count + 1,
          is_active = (missed_fetch_count + 1 < $stale_misses)   -- deactivate at the Nth consecutive complete-miss
    WHERE provider = ANY($complete_providers)
      AND model_id <> ALL($seen_ids)
      AND model_id NOT IN (SELECT model_id FROM public.bh_model_aliases);  -- alias-targeted models are never auto-deactivated
   ```
   **Alias-protection invariant (approved T0 decision):** a model that is the target of any role alias is never auto-deactivated — even if discovery stops returning it — so a "current X" role can never be aged-out from under the operator. The day-one aliases point at canonical discoverable IDs anyway (so this is belt-and-suspenders), but it also makes future operator repoints safe. (`bh_model_aliases.model_id` is indexed/PK-joined; this sub-select is cheap.)
   Semantics pinned: with `stale_misses=3`, a model deactivates on its **3rd** consecutive complete-miss (count goes 1→2→3, `is_active` flips false when the post-increment count ≥ 3). A single reappearance resets `missed_fetch_count=0, is_active=true` via step 2's upsert. Never delete (R1.4).
4. Build `RefreshSummary{added, reactivated, deactivated, price_flagged}`, insert a `bh_model_refresh_log` row (with the full per-model detail in its `summary jsonb`), and log it; a no-change run is a logged no-op (R2.5). (`unchanged` is derivable and lives only in the `jsonb`, not a column.)
5. Invalidate the in-process catalog + alias caches; release the lock.

### `Catalog` (read + cache seam)
- `list_active(provider=None)` backs `GET /api/models` (R1.2) and the admin GET.
- `cost_for(model_id, input_tokens, output_tokens)` — the **single** cost function (R3.3). Reads price from the in-process cache by exact key (then same-provider normalize); on miss/NULL falls back to the name heuristic and **logs a warning, never returns 0** (R3.3 floor). Replaces **all three** `RouterEngine._calculate_cost` call sites (`router_engine.py:239,:1203,:1436`) and the definition (`:1556`), `_infer_pricing` (`model_provider.py:24`), and the dead `CostTracker.calculate_cost` (`cost_tracker.py:126`). The heuristic lives here as **one** private function — the sole provisional-price source for both R3.2 and the R3.3 miss-path.
- **Cost keys against ALL rows (active + inactive); only `list_active`/`resolve_role` filter to active.** A model that was deactivated (R1.4) must still price its *historical* usage from its retained row, not fall through to the heuristic — so the cost cache is not the active-only cache (satisfies the requirements acceptance criterion "historical cost rows referencing an inactivated model still resolve").
- Holds the read-through in-process cache, invalidated by refresh and admin edits.

### `Resolver` (resolution seam)
- `resolve_role(role) -> str`, `default_chat_model() -> str` (R4.4), and a **price/catalog key lookup** that does **exact-match first** (R3.4).
- **In-process cache of the role map + the active catalog (keyed by exact `model_id`)**, built at startup, rebuilt on refresh/admin-edit — **no per-call DB round-trip** on the router hot path (explicit perf NFR + acceptance criterion).
- **Key resolution for cost is exact-match, not collapsing (B1 fix).** The seed carries *separate, independently admin-priced* Bedrock rows (`us.anthropic.claude-haiku-4-5-20251001-v1:0` id 5, `us.anthropic.claude-sonnet-4-5-v1:0` id 14) alongside the bare `claude-*` rows; the router genuinely invokes the Bedrock id when Bedrock is enabled (`model_provider.py:539,578`, cost logged with that id at `router_engine.py:1441`). Therefore cost lookup **first matches the invoked `model_id` exactly** against the catalog — so an operator price on the Bedrock row is read, never bypassed (R3.1). `normalize_key` is **only** a last-resort fallback that strips trailing version decoration (e.g. `…-v1:0`) to find a *same-provider* row when no exact row exists; it must never map a `us.anthropic.…` invocation onto a different-provider bare `claude-…` row. If neither exact nor same-provider normalized match exists → the R3.3 heuristic miss-path (non-zero + WARN).
- Fail-closed: if a cached alias points at an inactive/missing model, returns a known-good active model in the same tier and emits an alert (R3.4). The FK on `bh_model_aliases` prevents pointing a role at a *non-existent* row; the resolver handles the *inactive* case.

### Wiring into existing code — the resolver singleton (B2)
`config.HAIKU_MODEL`/`SONNET_MODEL`/`LOCAL_MODEL` are **`@dataclass` instance fields** on `Config` (`config.py:61-63`), set by `load_config()` (`config.py:128`) and read as `self.config.HAIKU_MODEL` at the 8 `router_engine` sites. They **cannot** become properties without removing the fields. The cutover does not touch `Config`; instead it uses a **module-level resolver singleton**, mirroring the existing `database.py` `_pool` / `get_pool()` pattern (`database.py:20,72`):

- A module `services/model_catalog.py` exposes `get_resolver() -> Resolver` backed by a process-global, populated in `lifespan` **after** `run_migrations` and `get_pool()` (a one-time cache warm — see precondition T1), so there is no import cycle (the resolver needs the pool, not `Config`; `Config` needs nothing from the catalog) and no chicken-and-egg.
- Call sites change from reading a config constant to calling the resolver: e.g. `self.config.HAIKU_MODEL` → `get_resolver().resolve_role("haiku")`. These are **runtime** calls on already-populated caches (no per-call DB hit), so they cannot be module-level constants evaluated at import.
- The R4.3 sites are a mix of `self.config.*` reads, **module-level constants** (`categorizer.py:30` `MODEL=...`, `scheduled_prompts.py:66` `DEFAULT_MODEL=...`, `local_intelligence.py:23`), **inline literals inside arg-less functions** (`finance.py:403` inside `ask_db`, `categorizer.py` `run_categorizer()`), and **`os.environ.get(..., "literal")` defaults** (`tool_router.py:38`, `local_intelligence.py:23`, `hook_engine.py:423` via `config.get("model", ...)`). All become `get_resolver().resolve_role(...)` calls at use-time — the module-level constants are deleted, not reassigned. **Env-var model overrides are removed, not preserved** (intentional behavior change): per Rule #1 the DB is the single source of truth, so an `os.environ.get("HAIKU_MODEL")` that could shadow the DB is dropped entirely — not left as a higher-precedence fallback (which would also slip past the acceptance grep). Full list (Anthropic: `finance.py:403`, `context_capture.py:62`, `scheduled_prompts.py:66`, `hook_engine.py:423`, `tool_router.py:38`; Ollama/local: `categorizer.py:30`, `inbox_cleaner.py:26`, `knowledge.py:238`, `router_engine.py:670`, `local_intelligence.py:23`).
- **Behavior-change call-out (`ask_db`, C1-sandboxed path):** `finance.py:403` currently sends the *dateless* `claude-haiku-4-5` straight to the Anthropic HTTP API; `resolve_role("haiku")` will send `claude-haiku-4-5-20251001` instead. This is the intended unification, but because ask_db is the least-privilege C1 path it gets an explicit test asserting it still functions with the resolved id.
- `get_default_chat_model()` (`model_provider.py:573`) delegates to `get_resolver().default_chat_model()` (R4.4).
- The provider `list_models()` discovery methods are retired in favor of `DiscoverySource`. **`DiscoverySource`s are constructed *outside* `ModelProvider`** (today providers are built inside `ModelProvider.__init__`, `model_provider.py:519`) and injected into `CatalogRefresh`, so tests can pass a `FakeDiscoverySource` (R2.6). `ModelProvider` keeps `complete`/`stream`/`_resolve_provider` (transport).

## Data Flow

**Refresh (scheduled or admin):** scheduler fires (interval from `bh_platform_settings`, R2.2) or admin `POST /api/admin/models/refresh` (R2.3) → `CatalogRefresh.refresh()` takes the single-flight lock → each source `discover()`s (Anthropic pages `models.list()`; error → `complete=False`) → upsert identity/caps, preserve prices, flag new, bump/reset `missed_fetch_count`, churn-safe deactivate → write `bh_model_refresh_log` + log summary → invalidate caches → release lock.

**Role resolution (hot path, per message):** `router_engine` / `config.HAIKU_MODEL` → `Resolver.resolve_role("sonnet")` → concrete `model_id` from the in-process cache (no DB hit). Dangling/inactive → fail closed + alert (R3.4).

**Cost (hot path):** after a completion → `Catalog.cost_for(model_id, in, out)` → **exact-match** the invoked `model_id` against the catalog cache (so a Bedrock invocation reads its own operator-priced Bedrock row, id 5/14 — never the bare `claude-…` row); on no exact match, try the same-provider `normalize_key` fallback; on still-miss/NULL → heuristic+WARN (never 0, R3.3/R3.4).

**Public list:** `GET /api/models` → `Catalog.list_active()` → `id/provider/display_name` + additive caps/context, **no price** (R1.2/R5.2). `ModelPicker.tsx:25` contract unchanged.

## Data Model / Migrations

**`0005_dynamic_model_discovery.sql`** — forward-only, auto-applied by `database.py:90`, parameterized DDL, one transaction, reproducible-from-zero (C2; `0001`→…→`0005` lands identical to a migrated live DB; never edit the checksum-immutable `0001`).

```sql
-- Lifecycle + capability + pricing-confirm columns on the catalog (R1.3, R1.4, R3.2)
ALTER TABLE public.bh_model_rates
  ADD COLUMN is_active                   boolean     NOT NULL DEFAULT true,
  ADD COLUMN last_seen_at                timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN missed_fetch_count          integer     NOT NULL DEFAULT 0,   -- churn-safe deactivation
  ADD COLUMN needs_price_confirmation    boolean     NOT NULL DEFAULT false,
  ADD COLUMN max_input_tokens            integer,                          -- context window (nullable until discovered)
  ADD COLUMN supports_thinking           boolean     NOT NULL DEFAULT false,
  ADD COLUMN supports_effort             boolean     NOT NULL DEFAULT false,
  ADD COLUMN supports_structured_outputs boolean     NOT NULL DEFAULT false;

-- Explicit backfill of the existing seed rows (auditable; admin-curated rows not flagged/hidden) — NFR data-safety.
-- No WHERE: at 0005 the only rows present are the 8 `0001` seeds (ids 1,5,9,10,11,12,13,14); the column DEFAULTs
-- already cover from-zero, the UPDATE makes the intent explicit and is a harmless no-op on a fresh build.
UPDATE public.bh_model_rates
   SET is_active = true, last_seen_at = now(), missed_fetch_count = 0, needs_price_confirmation = false;

-- Role/alias table — single source of truth for "current X" (R4.1). FK guarantees a role can never point at a non-existent model.
CREATE TABLE public.bh_model_aliases (
    role        text PRIMARY KEY,                                          -- 'haiku','sonnet','opus','local'
    model_id    text NOT NULL REFERENCES public.bh_model_rates(model_id),  -- FK on UNIQUE(model_id) (0001:3010)
    updated_by  integer,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Aliases must point at the CANONICAL IDs discovery actually returns (T0 finding: models.list() returns dated
-- canonical IDs, not the bare config.py forms). Ensure those rows exist before seeding, so the FK + guard pass AND
-- discovery keeps the alias targets fresh (so they're never deactivated). haiku's canonical id is already seed row
-- id 1; sonnet-4-6 and the dated opus are inserted here with current known prices (seed data, like the 8 existing
-- rows); discovery refreshes their capabilities on first run. (Approved T0 decision; sonnet → 4.6.)
INSERT INTO public.bh_model_rates
    (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens)
VALUES
  ('anthropic', 'claude-sonnet-4-6',        'Claude Sonnet 4.6', 3.00, 15.00, true, true, 64000),
  ('anthropic', 'claude-opus-4-5-20251101', 'Claude Opus 4.5',   5.00, 25.00, true, true, 64000)
ON CONFLICT (model_id) DO NOTHING;

INSERT INTO public.bh_model_aliases (role, model_id) VALUES
  ('haiku',  'claude-haiku-4-5-20251001'),   -- seed row id 1 (already canonical + discoverable)
  ('sonnet', 'claude-sonnet-4-6'),           -- inserted above; current best Sonnet
  ('opus',   'claude-opus-4-5-20251101'),    -- inserted above; canonical dated Opus
  ('local',  'llama3.2:3b');                 -- seed row id 10 (Ollama; OllamaDiscoverySource keeps it fresh)

-- Guard: abort the migration if any seeded role fails to resolve to an ACTIVE row (a typo can never go dark) — R4.1.
-- The guard references only model_ids that exist in the 0001 seed block, so a from-zero 0001→…→0005 build always
-- passes. This holds as long as 0001 is never re-cut (checksum-immutable, database.py:144) — an explicit dependency,
-- not a hazard: future model churn happens via discovery + alias repoint at runtime, never by editing 0005 or 0001.
DO $$
BEGIN
  IF (SELECT count(*) FROM public.bh_model_aliases a
        JOIN public.bh_model_rates r ON r.model_id = a.model_id AND r.is_active) <> 4 THEN
    RAISE EXCEPTION 'model alias seed failed: not all roles resolve to an active model row';
  END IF;
END $$;

-- Refresh audit log (R2.5 observability)
CREATE TABLE public.bh_model_refresh_log (
    id            serial PRIMARY KEY,
    ran_at        timestamptz NOT NULL DEFAULT now(),
    trigger       text        NOT NULL,           -- 'scheduled' | 'admin'
    complete      boolean     NOT NULL,
    added         integer     NOT NULL DEFAULT 0,
    deactivated   integer     NOT NULL DEFAULT 0,
    reactivated   integer     NOT NULL DEFAULT 0,
    price_flagged integer     NOT NULL DEFAULT 0,
    summary       jsonb
);
```

DB-driven config rows (per Rule #1, R2.2) in the existing `bh_platform_settings`:
```sql
INSERT INTO public.bh_platform_settings (key, value_json) VALUES
  ('model_discovery_interval_hours', '{"hours": 24}'),   -- default daily; scheduler enforces a floor (>= 6h)
  ('model_discovery_stale_misses',   '{"count": 3}'),    -- N consecutive complete-fetch misses before deactivation
  ('model_discovery_enabled',        '{"enabled": true}')-- write/scheduler kill-lever (see Rollout)
ON CONFLICT (key) DO NOTHING;                            -- bh_platform_settings PK is `key` (0001:3066); idempotent re-run
```

The alias-seed `model_id`s exist in the `0001` seed block, so the FK and guard pass on a from-empty build too (C2 preserved).

## API / Interfaces

- **`GET /api/models`** (`main.py:270`) → `Catalog.list_active()`, serialized through a **dedicated public DTO** that exposes `id, provider, display_name` + additive `supports_*` / `max_input_tokens` / `max_output_tokens` and **omits the price fields** (today the endpoint returns `ModelInfo` which carries `input_cost_per_mtok`/`output_cost_per_mtok` at `message.py:8-17` — the new DTO drops them so pricing is not leaked publicly; a test asserts their absence). `ModelPicker.tsx:25` contract (`id`/`provider`/`display_name`) unchanged (R1.2/R5.2). Public-read (unchanged).
- **`POST /api/admin/models/refresh`** (new, `Depends(require_admin)`, R2.3) → `CatalogRefresh.refresh(trigger="admin")`; returns the `RefreshSummary`.
- **`GET /api/admin/models`** (`admin.py:150`) → catalog rows incl. price, `is_active`, `needs_price_confirmation`, and joined alias assignments (R5.1).
- **`PATCH /api/admin/models/{id}`** (`admin.py:159`) → `ModelRateUpdate` extended with **typed** fields only (`is_active: Optional[bool]`, `needs_price_confirmation: Optional[bool]`); the `f"{field} = ${idx}"` builder stays safe solely because the field set is a closed Pydantic whitelist (R5.1, m1). On success → invalidate caches.
- **`PUT /api/admin/models/aliases/{role}`** (new, `require_admin`) → body `{model_id}`; validates the target is active, writes `bh_model_aliases` (parameterized, not the free-form builder), invalidates the resolver cache. This makes "change current Sonnet via DB, no redeploy" an API action (R4.1/R5.1).
- **Scheduler job** (`main.py` after :154): `scheduler.add_job(catalog_refresh.run_scheduled, IntervalTrigger(hours=<setting, floored>), id="model_discovery", replace_existing=True)`, no-op when `model_discovery_enabled` is false.

## Technology Choices

- **Official `anthropic` SDK `client.models.list()` over raw httpx** (R2.1, R1.3). The SDK is already a dependency (`anthropic.AsyncAnthropic`, `model_provider.py:50`); `models.list()` auto-paginates on iteration (do **not** use `.data`), exposes typed `id`/`display_name`/`max_input_tokens`/`max_tokens` plus a `capabilities` dict (`image_input`, `thinking.types.adaptive`, `effort`, `structured_outputs`, each with a `["supported"]` leaf), and returns **no pricing** — matching the hard constraint. This deletes the hand-rolled pagination, the hardcoded URL/version headers (`model_provider.py:131-137`), and the fabricated capability guesses (`:156-158`).
- **Postgres as the single store** — `bh_model_rates` + `bh_model_aliases` + `bh_model_refresh_log`; no new datastore.
- **Existing `AsyncIOScheduler`** for the refresh job — no new infra (R2.2).
- **In-process dict caches guarded by the refresh lock** for the resolver/catalog hot paths — cheapest correct option; invalidation is a method call at the end of the critical section and on admin edits (NFR Performance).
- **`asyncio.Lock` for single-flight** — sufficient because the backend runs as a **single process** (`Dockerfile:44` → uvicorn `--workers 1`), so the scheduler + admin endpoint share one event loop and the in-process caches are authoritative. This single-worker assumption is **load-bearing**: both single-flight and per-process cache invalidation silently break under `--workers > 1`. If multi-process is ever introduced, escalate single-flight to a Postgres advisory lock and cache invalidation to LISTEN/NOTIFY (noted, out of scope).

## Preconditions / verification tasks

- **T0 — Verify the installed `anthropic` SDK exposes the discovery fields** before building `AnthropicDiscoverySource`: confirm `client.models.list()` yields `id`, `display_name`, `max_input_tokens`, `max_tokens`, and a `capabilities` mapping on the pinned version (introspect, or one live call). Fields that are absent are written `NULL`/`false`, not guessed (M3/R1.3). This gates the chat-target filter (R1.5), which falls back to an id-prefix rule when `capabilities` is unavailable.
- **T1 — Warm the caches in `lifespan`** (`main.py:36-164`) **after `run_migrations(pool)` (`main.py:62`) and before the scheduler block (`main.py:87`)** — so the `0005` columns exist before any catalog read (the lifespan uses `init_pool`, `main.py:17`; warm strictly after migrations). Populate the resolver role map and the catalog cache from the DB so the first request never races an empty cache. Empty-cache read behavior is defined as fall-through to a single DB read (then memoize), never a crash; if even the DB is empty (cold start), the `StaticDiscoverySource` seed answers (R2.4).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Flaky/partial `/v1/models` deactivates a live model → vanishes from picker, chat picks a dead model (R1.4/R2.4) | `DiscoveryResult.complete` gate + `missed_fetch_count` counter; deactivate only after N **consecutive complete** misses; a single incomplete fetch changes nothing. |
| Discovery clobbers an operator-corrected price → mis-billing (R3.1) | The upsert `DO UPDATE SET` omits both price columns for existing rows; new rows get a provisional price + `needs_price_confirmation=true` (R3.2). Acceptance-tested: edit price → refresh → assert unchanged. |
| Cost miss-path silently returns 0 → under-billing (R3.3) | `Catalog.cost_for` falls back to the non-zero name heuristic + WARN on any miss/NULL; **cost-parity harness** (below) gates the cutover. |
| Cross-provider key mismatch / dangling alias (R3.4) | `normalize_key` maps Bedrock IDs to the catalog key; `resolve_role` fails closed to a known-good active tier model + alert; FK blocks aliasing a non-existent model. |
| Migration seeds an alias to a stale/non-existent model → tier breaks on deploy (R4.1) | Seed against verified live rows (ids 1/12/13/10), not `config.py` constants; FK + end-of-migration **guard assertion** aborts the transaction if any role doesn't resolve to an active row. |
| Migration hides a currently-offered model | Explicit backfill (`is_active=true, last_seen_at=now(), missed_fetch_count=0, needs_price_confirmation=false`) in the same transaction. |
| Concurrent scheduled + admin refresh interleave (R2.5) | Single `asyncio.Lock` over the whole upsert + log + invalidate critical section; second caller waits; no-op refresh is idempotent (touches only `last_seen_at`/counter). |
| Hot-path regression from a per-call DB lookup | Resolver/Catalog in-process caches; `config.*` accessors read the cache, never query; acceptance criterion asserts no per-call DB round-trip. |
| Schema not reproducible-from-zero (C2) | Forward-only additive `0005`; alias-seed targets exist in `0001`'s seed block so FK + guard pass on an empty build; CI runs the from-empty migration build. |

## Rollout (phased, each phase independently git-revertable)

The cost path is cut over **last**, only after the catalog is observed to match. Each phase is a separate commit; rollback is `git revert` + `deploy.sh` (minutes on this single service). The `model_discovery_enabled` setting disables the *scheduler/writes* at runtime without a deploy. (A permanent runtime `legacy|catalog` kill-switch in the hot cost/resolver paths was considered and **rejected** — it costs permanent dual-path branching in hot code to save a few minutes of redeploy; the phased revertable commits + the write-disable lever give the safety without the complexity.)

- **P0 — migration only.** Ship `0005` (columns, backfill, alias table+seed+guard, refresh-log). No code reads the new columns. Verify: 8 rows active, 4 aliases resolve.
- **P1 — discovery writes (shadow).** Ship `model_catalog.py` + scheduler job + admin refresh endpoint, writing the catalog. Reads still legacy. Observe discovery against prod with zero user-facing change.
- **P2 — `/api/models` reads catalog.** Lowest-risk read cutover (display only).
- **P3 — cost path to catalog.** Flip `RouterEngine` cost to `Catalog.cost_for`; delete the duplicate/dead heuristics — **gated by the cost-parity harness**.
- **P4 — delitteralize.** Replace `config.*` tier constants + the R4.3 inline literals with `resolve_role(...)`; cut `get_default_chat_model()` (R4.4). One site per commit.
- **P5 — cleanup.** Remove dead legacy constants once stable.

## Test Strategy

- **Injectable discovery (R2.6):** `FakeDiscoverySource` with scripted pages — model appears → upserted active with API caps; disappears across N complete fetches → `is_active=false` (not deleted), historical cost rows still resolve; single incomplete fetch → nothing deactivated; cold start (empty catalog + API down) → `StaticDiscoverySource` seed served. No network.
- **Catalog/pricing (ephemeral Postgres, `conftest.py`):** run the real `0005`; admin-edited price survives refresh (R3.1); new model → provisional price + `needs_price_confirmation=true` (R3.2); `cost_for` for unknown/NULL-price → non-zero heuristic + logged WARN, never 0 (R3.3).
- **Cost-parity harness (P3 gate) — two distinct invariants** (the old path was a heuristic, the new path reads admin-curated prices, so blanket `old == new` is impossible by design, M1):
  1. **Hard equality, permanent regression test:** for any model with *no catalog row or NULL price*, `Catalog.cost_for` must return the **identical** non-zero value the old `_calculate_cost` heuristic produced (the miss-path must not change historical costing or drift toward 0). This is asserted with `==`.
  2. **Reviewed diff report, human-gated (not `==`):** for priced catalog rows, generate a report of old-heuristic vs new-catalog cost across a token grid for the models actually invoked in recent usage history. Differences are *expected and intended* (that's the point of operator-curated prices); P3 ships on **human sign-off of the diff**, not on equality. The report is the artifact; it is not a passing/failing equality test.
- **Resolution (R4.1/R3.4):** post-migration every role resolves to an active row; repointing `bh_model_aliases.sonnet` changes what L3/ask_db use with no redeploy and no per-call DB hit (cache assertion); dangling alias fails closed + alert; Bedrock key normalizes to the catalog/pricing entry.
- **Refresh semantics (R2.5):** no-op refresh is a logged no-op that doesn't churn rows beyond `last_seen_at`; summary counts correct; concurrent admin+scheduled refresh serialize.
- **Security (R5.1/R5.2):** refresh/edit/alias endpoints `require_admin`; `/api/models` exposes no price fields; `ModelRateUpdate` rejects unknown fields.
- **Delitteralization grep (R4.3):** `grep -rE "claude-[a-z0-9.-]+|llama[0-9]" bowershub-ai/backend --include=*.py` outside `migrations/`/tests returns only the documented `StaticDiscoverySource` seed.
- **Whole suite:** `PYTHONPATH=. .venv/bin/python -m pytest -q` green; `npx tsc --noEmit` clean (`ModelPicker.tsx` unchanged); CI from-empty migration build passes.

## Design Decisions (tournament synthesis)

- **Spine = minimal-change** (one `model_catalog.py`, columns-on-`bh_model_rates` + one alias table, reuse scheduler/admin/CRUD) — most shippable, matches the repo's flat-service convention. The *ideal* 5-file package was rejected as premature structure for the diff size; its **internal seams** (discovery/refresh/catalog/resolver/pricing) are kept as clearly-named units within the one module.
- **Grafted from ideal-architecture:** the official **SDK `client.models.list()`** (real capabilities, deletes hand-rolled pagination + fabricated caps), the injectable **`DiscoverySource`** protocol, and **`StaticDiscoverySource`** as the single home for fallback literals.
- **Grafted from risk-first:** the **phased revertable rollout**, the **`missed_fetch_count`** counter (cleaner than a time-bound staleness window), the end-of-migration **guard assertion**, the **`bh_model_refresh_log`** audit table, and the **cost-parity harness** gating the cost cutover.
- **Rejected:** a permanent runtime `legacy|catalog` kill-switch in hot code (over-engineering for a single-process app with fast redeploys); copying `config.py` constants into the alias seed (the constants are stale — seed from real rows).
