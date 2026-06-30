# Lists v2 — Design

> Satisfies requirements in `requirements.md`. Reference IDs inline (e.g. "satisfies R1.2").
> Synthesis of three tournament approaches: **ideal-architecture** field-definition spine + **risk-first** migration/cutover/degradation mechanics + **minimal-change** reuse discipline and scope restraint.

## Architecture Overview

The crux of this feature (user-definable typed columns R1.5 + multi-select R5.4) makes Lists v2 a **lightweight typed-property engine scoped to lists** — a mini-Notion-database. The whole design hangs off one abstraction: a **field-definition** that is the single source of truth for storage, validation, the React renderer, and the AI's understanding of a list. Everything else (routing, grouping, sorting, stores) consumes that schema.

We **extend the existing module in place** (per `requirements.md` Constraints) — `services/lists.py`, `routers/lists.py`, `services/skills/lists.py`, `pages/ListsPage.tsx` — and add a config/schema layer plus two thin new services. PWA → FastAPI L1/L2/L3 router → `list` skill → Postgres, exactly as today; new pieces are consumers of the schema and config tables.

Four layers, each with one job and one risk profile:

1. **Schema layer (the spine).** `bh_list_field_defs` defines every field a list can hold across three scopes — `core` (built-in, every list), `type` (seeded per `bh_list_types`), `list` (user-added, R1.5). A resolver merges them by `key` with precedence **list > type > core** into one **effective schema** per list. A `storage` discriminator (`'column'` vs `'attribute'`) says where each value physically lives, so the renderer/validator treat all fields uniformly and only persistence branches.
2. **Data layer.** Hot, cross-cutting fields are real typed **columns** on `bh_list_items` (indexed, queryable). The user-extensible tail lives in a JSONB `attributes` column. The field-def supplies the typing/validation that EAV's "attribute row" pretends to give — without EAV's join cost or type erasure.
3. **Service layer.** `lists.py` (CRUD, ID-addressed), `list_schema.py` (resolve effective schema + validate values), `list_router.py` (item→list routing with degradation), `list_grouping.py` (parameterized group/sort/filter + sort whitelist).
4. **Surface layer.** One ID-addressed REST API (with name-addressed compat shims during cutover); one generic schema-driven React `ListView` + settings panel; the chat `list` skill + tiered router as a thin consumer of `list_router`.

### Why typed-core + JSONB tail (not EAV, not all-JSONB)

- **EAV** (`item_id, key, value` rows): every read is a pivot/self-join, types erased to text, ordering/grouping/filtering need aggregation. Rejected.
- **All-JSONB**: loses cheap indexed sort/filter on the hot path (category, due_date, checked, sort_order) and makes FK integrity (assignee) impossible. Rejected.
- **Typed-core + JSONB tail** (chosen, satisfies R3.1/R3.2): ~8 cross-cutting fields as indexed columns; the long, low-cardinality, per-type/per-list tail in one JSONB blob. `bh_list_field_defs` is the typing authority; JSONB is just the value store.

### Key tournament trade-offs (why the losers lost)

| Decision | Chosen | Lost | Why |
|---|---|---|---|
| Field schema storage | **Normalized `bh_list_field_defs` table** (ideal) | JSONB `fields` array on type + per-list override (minimal) | Minimal flagged this as its own ugly compromise: reorder/rename rewrites the whole blob → lost-updates under concurrent schema edits; no per-option FK. The table gives per-field CRUD, clean precedence, soft-remove, and an `options_source` reference. The feature *is* a schema engine, so the table is core, not gold-plating. |
| name→ID API | **Staged dual-contract + compat shims** (risk-first) | Hard cutover (minimal) | Cached PWAs hold name-addressed URLs; a hard swap 404s them. Dual-contract has no outage window; minimal itself flagged this risk. |
| Stores | **First-class `bh_stores`/`bh_store_aisles`** (ideal), surfaced as a multi-select field via `options_source='stores'` | Store layouts as a JSON blob in `bh_platform_settings` (minimal/risk) | R6.5 wants store add/rename/reorder in list settings, and store→aisle order is relational. A blob can't be edited per-row cleanly. |
| Dedupe migration | **Risk-first's audit-table + collision-free predicate** | minimal/ideal's merge (correct but under-specified) | Risk-first caught that the partial unique index predicate must exclude archived losers (`WHERE is_shared AND is_archived=false`), else the archived loser collides with its survivor at index-creation and aborts the migration. |

## Components

**Backend (new / changed):**

| Component | File | Change |
|---|---|---|
| List service | `services/lists.py` | Split `_resolve_list_id(create=True)` (`lists.py:18`) into `resolve_only()` + `create_list()`; ID-addressed mutations; fractional `sort_order`; delegates validation to `list_schema` |
| Schema engine (new) | `services/list_schema.py` | `resolve(conn, list_id) -> EffectiveSchema` (merge core/type/list); `validate_value(field_def, value)` per `col_type` (parameterized, server-side); option-set mutation helpers keyed by stable `value` |
| Routing resolver (new) | `services/list_router.py` | Item→list resolution: split → embed (cosine) → threshold decision (add/create/disambiguate); deterministic name-match fallback; grocery auto-categorize |
| Grouping/sort/filter (new) | `services/list_grouping.py` | Builds parameterized group/sort/filter SQL; owns the **sort whitelist** (the `transactions_query.py:13` `_SORTS` precedent) + JSONB-key safety gate |
| REST router | `routers/lists.py` | ID-addressed routes **+ retained name-addressed shims**; type/field/store/config endpoints; confirm-on-delete |
| Chat skill | `services/skills/lists.py` | Remove `"shopping"` default (`skills/lists.py:21`); resolve-once via `list_router` |
| L2 classifier | `services/router_engine.py:1010` | Inject live active-list inventory into classification context (R4.1) |
| L3 tool | `services/tool_router.py:368` | Remove `default: shopping` hint; structured per-item `[{text,list_id,attributes}]` output (R4.2) |
| Embedding worker | `services/embedding_worker.py` | Add a `_reconcile_lists` reconcile pass + list reap (see below) |

**Embedding worker is a poll/reconcile engine, not event-driven** (`embedding_worker.py` has `_reconcile_messages`/`_reconcile_entities`/`_reap_orphans` driven by a content-hash dirty predicate on a `run_tick` timer — there is no per-write hook). So list routing integrates as a fourth reconcile pass, with two consequences spec'd here:
- **New `_reconcile_lists`**: content expression = `name · type label · description` (NOT item names — they churn constantly and would re-embed every add); dirty-predicate on a content hash like the others. It is the **only** write path into `kb_chunks` for lists. A brand-new or just-renamed list is invisible to embedding-routing until the next tick — acceptable because the deterministic name-match path (R4.5) covers it in the interim (a freshly-created list matches its own name exactly). This latency is stated, not hidden.
- **List reap**: `_reap_orphans` today removes only `message`/`entity` chunks (`embedding_worker.py:200-226`), so archived/merged/deleted lists would keep stale embeddings and the router could match a dead list. Extend reaping to delete `source_type='list'` chunks whose list is gone **or** `is_archived=true`; `_reconcile_lists` itself skips archived lists. Tested (a reaped/archived list is never a routing candidate).

**Frontend (new / changed):**
- `pages/ListsPage.tsx` — orchestrator; carries `list_id` (was name, `ListsPage.tsx:31`); preserves optimistic add/toggle/remove/clear (`ListsPage.tsx:84-116`).
- `components/lists/ListView.tsx` — generic, schema-driven (R6.1); `FieldRenderer.tsx` (per `col_type`), `FilterChips.tsx`, `SortMenu.tsx`, `GroupedItems.tsx`, `ListSwitcher.tsx` (create/rename/delete/archive + type picker, R6.2), `ListSettingsPanel.tsx` (columns editor + select-option editor + store manager, R6.5).

## Data Flow

**UI add (R6.3, optimistic preserved):** `ListsPage` holds `activeId:number` → `POST /api/lists/{list_id}/items {items:[{text, attributes?}]}` → `list_schema.resolve` → `validate_value` each field → if grocery-typed and no `category`, `list_router.categorize_item()` (alias lookup → Ollama, never L3, R5.5) → INSERT (core columns + `attributes`) → return list + merged schema + grouped items. No name resolution, no auto-create.

**Chat add ("milk, wrap mom's gift, call dentist", R4.2/4.3/4.5):**
1. `router_engine._classify` sees the `list` skill **and an injected active-list inventory line** (names + types) → routes to `list` skill.
2. Skill calls `list_router.route_items(text, user_id)`:
   - Split into items (L3 `manage_list` already splits when invoked; cheap path uses punctuation/conjunction heuristic).
   - Per item: **deterministic exact case-insensitive name match first** (degradation-safe). Else embed (Ollama `bge-m3`, reuse `embeddings.py`) → cosine `1 - (embedding <=> $1)` vs accessible list embeddings (`kb_chunks` `source_type='list'`, joined to `bh_lists` and filtered `(is_shared OR user_id = $me) AND NOT is_archived` so a private list is never matched for the other household member, R2.3). *(Direct cosine, not `HybridRetriever` RRF rank — thresholding needs a normalized similarity, not a fusion rank. This is a deliberate, noted deviation from R4.5's "reuse `hybrid_retrieval.py`" wording — same infra, correct metric.)*
   - Threshold decision from `bh_platform_settings['lists.routing']`: best-sim ≥ `match_threshold` → add to that list ID; top-2 within `ambiguity_margin` → return `needs_disambiguation` (one question, R4.4); explicit "start/make/create … list" verb **or** best-sim < `create_threshold` → flag explicit-create intent; otherwise add to the DB-config default list (`lists.default_list_id`) **uncategorized** — never auto-create.
   - Returns `[{text, list_id, list_name, attributes, confidence, needs_disambiguation}]`. Caller mutates by ID; never re-resolves a name.
3. **Degradation (R4.5):** embeddings/pgvector/classifier down → catch `EmbeddingError` (`embeddings.py:55`) / Ollama failure (`categorizer.py:236` precedent) → deterministic name match or explicitly-named list; item added uncategorized; routing never blocks, loops, or drops.

**Grouping/sort/filter (R5):** `GET /api/lists/{id}?store=Meijer&group=true&sort=manual` → `list_grouping` reads effective schema → `group_by` field key → group order = active store's aisle layout (`bh_store_aisles`, R5.4) else type `category_set` (R5.3) → sort via whitelist (default from `bh_list_types.default_sort`) → filters as parameterized predicates (array containment `attributes->'stores' ? $1` for multi-select store).

## Data Model / Migrations

One forward-only migration **`0054_lists_v2.sql`** (next free number; latest is `0053`). The runner executes each migration in a single transaction with `SET LOCAL search_path = public, finance` (`database.py:226`); on failure the whole migration rolls back and startup aborts (`database.py:235`) — no half-migrated state. All DDL is `IF NOT EXISTS` / seeds `ON CONFLICT DO NOTHING` so it applies cleanly on `fresh_db` (R3.3, project rule C2).

### Part 1 — Type + field-definition tables (R1.1–R1.5, R3.1, R3.2)

```sql
-- List types (R1.1–R1.3)
CREATE TABLE IF NOT EXISTS public.bh_list_types (
    id            serial PRIMARY KEY,
    name          text NOT NULL,                  -- machine key, e.g. 'grocery'
    label         text NOT NULL,
    icon          text,
    description   text,                            -- feeds AI routing + UI
    group_by      text,                            -- field key to group by (NULL = none)
    default_sort  text NOT NULL DEFAULT 'recent',  -- must be in sort whitelist
    default_order text NOT NULL DEFAULT 'desc' CHECK (default_order IN ('asc','desc')),
    category_set  jsonb NOT NULL DEFAULT '[]',     -- ordered [{key,label,sort_order}] (R5.3)
    is_active     boolean NOT NULL DEFAULT true,
    is_seed       boolean NOT NULL DEFAULT false,
    sort_order    integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_list_types_name ON public.bh_list_types (LOWER(name)); -- R1.2

-- Field definitions (the spine, R1.5 / R3.1 / R3.2)
CREATE TABLE IF NOT EXISTS public.bh_list_field_defs (
    id             serial PRIMARY KEY,
    scope          text NOT NULL CHECK (scope IN ('core','type','list')),
    list_type_id   integer REFERENCES public.bh_list_types(id) ON DELETE CASCADE,
    list_id        integer REFERENCES public.bh_lists(id)      ON DELETE CASCADE,
    key            text NOT NULL,                  -- stable id; column name if storage='column'
    label          text NOT NULL,
    col_type       text NOT NULL CHECK (col_type IN
                     ('text','number','date','checkbox','single_select','multi_select','url')),
    storage        text NOT NULL DEFAULT 'attribute' CHECK (storage IN ('column','attribute')),
    options        jsonb,                          -- inline [{value,label,sort_order,color?}] for selects
    options_source text,                           -- e.g. 'stores' → options come from bh_stores; NULL = inline
    required       boolean NOT NULL DEFAULT false,
    is_active      boolean NOT NULL DEFAULT true,  -- soft remove keeps values (R1.5 lifecycle)
    groupable      boolean NOT NULL DEFAULT false,
    sortable       boolean NOT NULL DEFAULT false,
    filterable     boolean NOT NULL DEFAULT false,
    validation     jsonb,                          -- optional {min,max,regex}
    sort_order     integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT field_scope_target CHECK (
        (scope='core' AND list_type_id IS NULL AND list_id IS NULL) OR
        (scope='type' AND list_type_id IS NOT NULL AND list_id IS NULL) OR
        (scope='list' AND list_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_core ON public.bh_list_field_defs (key)              WHERE scope='core';
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_type ON public.bh_list_field_defs (list_type_id,key) WHERE scope='type';
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_list ON public.bh_list_field_defs (list_id,key)      WHERE scope='list';
```

**Effective-schema resolution** (`list_schema.resolve`): start with `core` rows, overlay the list's `type` rows, overlay the list's own `list` rows — keyed by `key`, last writer wins on `label/options/sort_order/is_active`. A `list`-scope row with the same `key` as a `type`/`core` row **overrides** presentation (rename, reorder, soft-hide); a list **cannot** delete a core field, only override its presentation. One merged schema object drives the renderer AND the AI prompt AND validation — the single source of truth (R1.5). Custom-field→type promotion (R1.5 optional) is a future `UPDATE scope='type'`; designed-for, not built in v1.

### Part 2 — `bh_lists` / `bh_list_items` additions (R1.3, R3.1, R3.2)

```sql
ALTER TABLE public.bh_lists
    ADD COLUMN IF NOT EXISTS list_type_id integer REFERENCES public.bh_list_types(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS notes        text;     -- merge-audit note target (R2.2)

ALTER TABLE public.bh_list_items
    ADD COLUMN IF NOT EXISTS category         text,
    ADD COLUMN IF NOT EXISTS due_date         timestamptz,
    ADD COLUMN IF NOT EXISTS assignee_user_id integer,                 -- FK added below (SET NULL)
    ADD COLUMN IF NOT EXISTS sort_order       double precision,        -- fractional ranking (R3.4)
    ADD COLUMN IF NOT EXISTS attributes       jsonb NOT NULL DEFAULT '{}';

-- R3.1: assignee FK is ON DELETE SET NULL — deliberately UNLIKE bh_lists.user_id CASCADE (0001_baseline.sql:3940),
-- so deleting a household member nulls assignments but NEVER deletes assigned items. Guarded for re-safety.
DO $$ BEGIN
    ALTER TABLE public.bh_list_items
        ADD CONSTRAINT bh_list_items_assignee_fkey
        FOREIGN KEY (assignee_user_id) REFERENCES public.bh_users(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_list_items_sort     ON public.bh_list_items (list_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_list_items_category ON public.bh_list_items (list_id, category);
CREATE INDEX IF NOT EXISTS idx_list_items_assignee ON public.bh_list_items (assignee_user_id);
CREATE INDEX IF NOT EXISTS idx_list_items_attrs    ON public.bh_list_items USING gin (attributes); -- array containment (R5.4)
```

`added_by` stays free-text provenance (its existing `'chat'` semantics); `assignee_user_id` is the separate structured assignment (R3.1) — the split is intentional and documented.

### Part 3 — Stores + aisle layouts (R5.4) — first-class household entities

```sql
CREATE TABLE IF NOT EXISTS public.bh_stores (
    id serial PRIMARY KEY,
    name text NOT NULL, is_active boolean NOT NULL DEFAULT true, sort_order integer NOT NULL DEFAULT 0,
    created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS uq_stores_name ON public.bh_stores (LOWER(name));

CREATE TABLE IF NOT EXISTS public.bh_store_aisles (   -- store → ordered departments (walk order)
    id serial PRIMARY KEY,
    store_id integer NOT NULL REFERENCES public.bh_stores(id) ON DELETE CASCADE,
    department text NOT NULL,            -- matches a category_set key
    sort_order integer NOT NULL,
    UNIQUE (store_id, department));

CREATE TABLE IF NOT EXISTS public.bh_item_category_aliases (   -- grocery auto-cat (R5.5)
    id serial PRIMARY KEY,
    list_type_id integer REFERENCES public.bh_list_types(id) ON DELETE CASCADE,  -- NULL = any
    alias text NOT NULL, department text NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS uq_item_alias ON public.bh_item_category_aliases (LOWER(alias), COALESCE(list_type_id,0));
```

The grocery `store` field is a `multi_select` field-def with `options_source='stores'` — its options come from `bh_stores`, so "add a store in list settings" (R6.5) is an INSERT into `bh_stores`, immediately reflected everywhere.

### Part 4 — Seeds + backfill (R1.2, R1.3)

- Seed 6 types (`simple, grocery, chores, gifts, todo, packing`) `ON CONFLICT DO NOTHING`. `simple`: fields = `quantity/notes` only, `group_by=NULL`, `default_sort='recent'` (R1.3).
- Seed `core` field-defs (`storage='column'`): `text, checked, quantity, notes, category, due_date, assignee_user_id, sort_order`.
- Seed per-`type` field-defs (`storage='attribute'`): grocery → `store` (multi_select, `options_source='stores'`), `price`; gifts → `recipient`, `url`, `price`; chores → `priority` (single_select); etc.
- Seed grocery `category_set` (Produce→Bakery→…→Checkout walk order) + starter `bh_item_category_aliases` (milk→Dairy, …).
- **Backfill** every existing/un-typed list to `simple`; backfill `sort_order = row_number()*1000` per list (deterministic manual order):

```sql
UPDATE public.bh_lists SET list_type_id = (SELECT id FROM public.bh_list_types WHERE LOWER(name)='simple')
 WHERE list_type_id IS NULL;
UPDATE public.bh_list_items i SET sort_order = sub.rn*1000.0
  FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY list_id ORDER BY created_at) rn FROM public.bh_list_items) sub
 WHERE i.id = sub.id AND i.sort_order IS NULL;
```

`list_type_id` is left nullable (not `SET NOT NULL`) for `fresh_db` insert-ordering safety; the service reads it with a `COALESCE`-to-`simple` guard.

### Part 5 — R2.2 dedupe, then constrain (the dangerous step)

Audit table first, then merge colliding **active shared** lists into the oldest (lowest `id`) — re-point items (never delete), log, archive losers:

```sql
CREATE TABLE IF NOT EXISTS public.bh_list_merges (
    id serial PRIMARY KEY, survivor_id integer NOT NULL, merged_id integer NOT NULL,
    merged_name text NOT NULL, item_count integer NOT NULL, merged_at timestamptz NOT NULL DEFAULT now());

WITH dups AS (
    SELECT id, MIN(id) OVER (PARTITION BY LOWER(name)) AS survivor_id
    FROM public.bh_lists WHERE is_shared AND is_archived = false),
losers AS (SELECT id, survivor_id FROM dups WHERE id <> survivor_id),
moved AS (
    UPDATE public.bh_list_items i SET list_id = l.survivor_id
    FROM losers l WHERE i.list_id = l.id RETURNING l.id AS loser_id),
counts AS (SELECT loser_id, COUNT(*) c FROM moved GROUP BY loser_id)
INSERT INTO public.bh_list_merges (survivor_id, merged_id, merged_name, item_count)
SELECT l.survivor_id, l.id, b.name, COALESCE(c.c,0)
FROM losers l JOIN public.bh_lists b ON b.id=l.id LEFT JOIN counts c ON c.loser_id=l.id;

UPDATE public.bh_lists b
   SET is_archived = true,
       notes = COALESCE(b.notes,'') || ' [lists-v2: merged into list #' ||
               (SELECT survivor_id FROM bh_list_merges m WHERE m.merged_id=b.id LIMIT 1) || ' on 0054]'
 WHERE b.id IN (SELECT id FROM losers);

-- Partial unique index — predicate MUST exclude archived losers or it fails at creation.
ALTER TABLE public.bh_lists DROP CONSTRAINT IF EXISTS bh_lists_name_user_id_key;   -- 0001_baseline.sql:2986
CREATE UNIQUE INDEX IF NOT EXISTS uq_lists_shared_name
    ON public.bh_lists (LOWER(name)) WHERE is_shared AND is_archived = false;       -- R2.2 household-wide (case-insensitive)
-- Private index stays CASE-SENSITIVE (name, not LOWER(name)) to exactly match the dropped
-- constraint's coverage, so it CANNOT abort on existing data: a user legally holding 'Todo' AND
-- 'todo' (both private) was allowed before and stays allowed. (Going case-insensitive here would
-- collide on such pairs and abort — and Part 5's merge only dedupes SHARED lists, not private.)
CREATE UNIQUE INDEX IF NOT EXISTS uq_lists_private_name
    ON public.bh_lists (name, user_id) WHERE NOT is_shared AND is_archived = false;  -- private per-creator
```

**Why the `is_archived=false` predicate is load-bearing:** the archived loser still has `is_shared=true` and shares `LOWER(name)` with its survivor; a naïve `WHERE is_shared` index would see two entries and abort the migration. Scoping to live shared rows matches exactly what the resolver queries (`get_all_lists` already filters active, `lists.py:223`). **Re-runnability:** after merge, no two active-shared lists share `LOWER(name)` → re-evaluating `losers` yields zero rows; `CREATE … IF NOT EXISTS` skips. **Item-collision note:** re-pointing may create two items with the same text on the survivor — no DB unique on `(list_id, text)` (dedup is app-level insert-time, `lists.py:98`), so it's a harmless visible duplicate the user can remove; we deliberately do **not** auto-delete (destructive guess).

### Part 6 — Allow `source_type='list'` on `kb_chunks` (required for routing)

`kb_chunks` has `CONSTRAINT kb_chunks_source_type_check CHECK (source_type = ANY (ARRAY['message','entity']))` (`0010_semantic_memory.sql:33`). Without altering it, every list embedding INSERT raises `check_violation` and the entire embedding-routing path is dead. `0054` must widen it (guarded for re-runnability):

```sql
ALTER TABLE public.kb_chunks DROP CONSTRAINT IF EXISTS kb_chunks_source_type_check;
ALTER TABLE public.kb_chunks ADD  CONSTRAINT kb_chunks_source_type_check
    CHECK (source_type = ANY (ARRAY['message','entity','list']));
```

### Config rows in `bh_platform_settings` (R4.3, R6.6 — no hardcoding)

```sql
INSERT INTO public.bh_platform_settings (key, value_json) VALUES
 ('lists.routing', '{"match_threshold":0.55,"create_threshold":0.35,"ambiguity_margin":0.07}'),
 ('lists.default_list_id', 'null')             -- replaces hardcoded "shopping" fallback (R6.6)
ON CONFLICT (key) DO NOTHING;
```

**Electing the default list (closes the no-drop guarantee).** `'null'` is the *initial* seed; the migration then **elects a concrete default** in the same step: the legacy list named `shopping` if it exists, else the oldest active shared list, else left `null` (a brand-new/empty install has no list to elect). `list_router` defines the runtime behavior when `lists.default_list_id` is null **or** points to an archived/deleted list: it **lazily creates (once) a single shared default list** named `Shopping`, persists its id back to `lists.default_list_id`, and adds the item there. This is the one sanctioned auto-create — a deterministic *system* default, not a name-driven spawn — so the no-drop guarantee (R4.5) holds even on `fresh_db`, while R4.3's "no junk duplicate from a misheard name" still holds (the default is created at most once, by name `Shopping`, idempotently). A degradation test asserts an unmatched item lands somewhere on a `fresh_db` with no pre-existing default.

**⚠ These threshold numbers are PLACEHOLDERS to be calibrated by the fixtured routing test, not reasoned values.** The earlier draft borrowed `0.75` from `router_engine.py:164`, but that is a Haiku *classification probability*, not a `bge-m3` *cosine similarity* — a category error. `bge-m3` cosine between a short item ("milk") and a list's `name·type·description` routinely sits well below 0.75, so a 0.75 gate would dump most correct items onto the default list. The implementation task MUST measure the cosine distribution over the labeled `item→expected list` fixture set (acceptance criterion) and set `match_threshold`/`create_threshold`/`ambiguity_margin` from that distribution; the values above are a starting point only. They live in `bh_platform_settings` so they're tunable without deploy (R4.3 DB-driven goal). We do not refactor the global router threshold (out of scope).

### Rollback / forward-fix story

Migrations are forward-only and checksummed (`database.py:107`), no down-migration. Reversibility is engineered into the forward path: everything additive is non-destructive (no DROP/repurpose, R3.3); the merge is fully reconstructable from `bh_list_merges` (a `0055` could un-archive + split items back out); a mid-migration failure rolls the whole transaction back and aborts startup rather than serving a half-migrated schema.

## API / Interfaces

All routes `Depends(get_current_user)` (`requirements.md` Security); per-item access stays in the service (`_item_accessible`, `lists.py:256`); bodies are Pydantic `extra:"forbid"`.

**Config / schema (read):**
- `GET /api/list-types`, `GET /api/list-types/{id}` — type defs + effective fields + `category_set` (R1.4, mirrors `/api/themes`)
- `GET /api/lists/config` — sort-whitelist labels, default list, store list
- `GET /api/lists/stores`; `POST/PATCH/DELETE /api/lists/stores[/{id}]`; `PUT /api/lists/stores/{id}/aisles` (ordered departments) — R5.4/R6.5

**Lists (ID-addressed, R2.1):**
- `GET /api/lists` → summaries `{id,name,type,icon,pending,done}` (**adds `id`** — the load-bearing change for the dropdown)
- `POST /api/lists {name, list_type_id, is_shared}` → **explicit** create (R2.1/R4.3)
- `GET /api/lists/{list_id}?store=&group=&sort=&filter=` → `{list, schema, groups[]}` (R5.1/5.2/5.6)
- `PATCH /api/lists/{list_id} {name?, list_type_id?, default_sort?, group_by?, is_shared?}` (rename/retype)
- `POST /api/lists/{list_id}/archive` · `/unarchive` (soft default, R2.4); `DELETE /api/lists/{list_id}?confirm=true` (hard, UI-confirmed)

**Items:**
- `POST /api/lists/{list_id}/items {items:[{text,quantity?,category?,attributes?,...}]}` (validated, auto-cat)
- `PATCH /api/lists/items/{item_id} {checked?,text?,category?,due_date?,assignee_user_id?,attributes?,sort_order?}` (LWW, R3.4)
- `DELETE /api/lists/items/{item_id}` · `POST /api/lists/{list_id}/clear`
- `POST /api/lists/{list_id}/items/reorder {ordered_item_ids:[...]}` → transactional fractional re-sequence (R3.4)

**Fields / custom columns (R1.5 / R6.5):**
- `GET /api/lists/{list_id}/fields` → effective merged schema
- `POST /api/lists/{list_id}/fields {key,label,col_type,options?,required?}` → creates a `scope='list'` row for this list
- `PATCH /api/lists/{list_id}/fields/{key} {label?,options?,sort_order?,is_active?}` (rename/reorder/soft-remove — values retained)
- `PATCH /api/lists/{list_id}/fields/{key}/options` (add/rename/reorder/remove options keyed by stable `value` — rename never orphans items)

**Field-mutation integrity (enforced, not prose — closes an IDOR + global-mutation hole):** field endpoints are addressed by `{list_id}` + field **`key`**, never by a global field-def `id`. The handler always resolves the field within *this list's* effective schema and writes a **`scope='list'`** override row keyed to `list_id`:
- A `core` field can never be deleted/disabled globally. A per-list "remove" of a core field writes a `scope='list'` override with `is_active=false` for that list only; core/type rows (`list_id IS NULL`) are immutable via this API.
- Mutating a field whose def is `scope IN ('type','core')` is rejected as a direct edit; the handler instead upserts the overriding `scope='list'` row. So one list can never edit another list's (or every list's) field def — the `list_id` in the path is the ownership boundary, enforced server-side. A test asserts a per-list call cannot globally disable a core field, and cannot affect a sibling list.

**Name-addressed compat shims (retained during cutover, R2.1):** `GET /api/lists/{list_name}`, `POST /api/lists/{list_name}/items`, `POST /api/lists/{list_name}/clear` resolve name→id internally. **Critical distinction:** the UI/REST name-POST shim **keeps create-on-add** (a cached client adding to a brand-new list must still work — deterministic explicit user action); the **AI/chat path drops auto-create** (R4.3). Surgical: `_resolve_list_id(create=True)` (`lists.py:18`) splits into `resolve_only()` (chat/`list_router`) + `create_list()` (explicit REST create + compat shim).

**Deploy ordering (each step independently safe, no broken window):**
1. Migration `0054` (additive; old code ignores new columns).
2. Backend: ID routes added **alongside** name shims; chat path switched to resolve-once/no-create. Cached PWAs still succeed on name routes.
3. Frontend: dropdown carries IDs; switch to ID routes; SW update rolls out per-client.
4. Later release demotes shims once name-route traffic ≈ 0 (no migration needed).

**Sort whitelist (R5.2):** `_SORTS = {'manual':'sort_order','name':'LOWER(text)','due':'due_date','recent':'created_at','checked':'checked'}`, resolved via `.get(sort, 'sort_order')` (the `transactions_query.py:85` security control). A custom JSONB-field sort validates the field `key` against the resolved effective-schema key set **and** `^[a-z0-9_]+$` before composing `attributes->>'<key>'` with a `col_type` cast (`number→::numeric`, `date→::timestamptz`). Identifiers are never raw-interpolated; values always `$n`-parameterized.

**Validation + the column-vs-attribute write path (R1.5):** `list_schema.validate_value(field_def, value)` validates per `col_type` — `number`→numeric, `single_select`→value ∈ options, `multi_select`→array ⊆ options, `date`→ISO parse, `url`→scheme check, optional `{min,max,regex}`. Reject 422 on mismatch; writes via `$n` params. The write layer dispatches on the field-def's `storage`: a `storage='column'` field's value is written to its named column (`text`, `checked`, `category`, `due_date`, `assignee_user_id`, `sort_order` arrive as named body params); a `storage='attribute'` field's value is written into `attributes[key]`. Item-PATCH iterates the **effective schema** to validate *every* submitted field uniformly (so core columns are validated too, not just the JSONB tail), then routes each to its storage — implementers neither double-handle nor skip core-column validation.

## Technology Choices

- **`bh_list_field_defs` normalized table** over JSONB-blob schema — per-field CRUD, clean 3-scope precedence, soft-remove, `options_source` reference; avoids whole-blob lost-updates.
- **pgvector cosine** (`1 - (embedding <=> $1)`) for item→list routing (reuse `embeddings.py`/`kb_chunks`, `source_type='list'`) — a normalized similarity for thresholding, not `HybridRetriever`'s RRF rank. No new infra.
- **Tiered routing as a clean specialization** of the existing L1/L2/L3 router: L1 explicit `/list`+named (deterministic); L2 embedding similarity + live inventory as a *constrained choice* (R4.1); L3 (Sonnet) only for multi-intent split or genuine ambiguity. Interactive add stays off L3.
- **Fractional `double precision sort_order`** with midpoint inserts + transactional bulk re-sequence — clobber-free concurrent reorders (R3.4) without a version column; periodic rebalance guards precision exhaustion. Two mechanisms: `PATCH item {sort_order}` = single move (server computes the midpoint of the chosen neighbors); `POST .../items/reorder {ordered_item_ids}` = full transactional re-sequence to `n*1000`. Two concurrent single-moves between the *same* neighbors can compute an equal midpoint (a benign tie, not a clobber); all ordering reads use a deterministic `ORDER BY sort_order, id` so a tie is stable, and the next reorder/rebalance re-spaces them.
- **JSONB GIN** (default opclass supports `?` and `@>`) for `attributes` → parameterized array containment for the multi-select store filter (R5.4).
- **DB-driven numeric thresholds + default list** in `bh_platform_settings` (`value_json`) — tunable without deploy (R4.3/R6.6).
- **Plain `CREATE UNIQUE INDEX`** (not `CONCURRENTLY`) — can't run inside the migration transaction; household table is tiny so the brief lock is irrelevant.
- No new Python/JS dependencies.

## Risks & Mitigations

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Partial unique index fails because archived loser shares name with survivor | Predicate `WHERE is_shared AND is_archived=false`; merge archives losers *before* index creation. Provably collision-free + re-runnable. |
| 2 | Dedupe merge loses items | Items re-pointed (UPDATE, never DELETE); losers archived not deleted; every merge logged to `bh_list_merges` + `notes`. Reconstructable. |
| 3 | Migration half-applies | Single transaction (`database.py:216`); failure rolls back fully, aborts startup (`database.py:235`). |
| 4 | Deleting a household member cascade-deletes their assigned items | `assignee_user_id` FK `ON DELETE SET NULL` (≠ `user_id` CASCADE). Member-deletion test asserts items survive. |
| 5 | Cached PWA breaks on name→ID cutover | Name shims retained; UI-shim keeps create-on-add; staged deploy. |
| 6 | AI auto-creates junk list from misheard name | `create=True` removed from add path (`resolve_only`); create needs explicit verb or `<create_threshold`; unmatched → default list, uncategorized. |
| 7 | Ollama/pgvector down blocks/drops adds | Catch `EmbeddingError`/Ollama failure → deterministic name match or default list; add **always succeeds**, item uncategorized (R4.5). |
| 8 | AI destructively deletes a list/items | AI tool exposes archive + add/check only; delete-list and clear require explicit UI confirm (R2.4); no AI delete path. |
| 9 | SQL identifier injection via dynamic sort/group | Whitelist `.get(...,default)`; JSONB sort keys validated ∈ effective schema + `^[a-z0-9_]+$`; never interpolated. |
| 10 | Custom-column removal purges values | Soft-remove (`is_active=false`); `attributes` values retained (R1.5); reversible. Option rename keyed by stable `value`, items keep value. |
| 11 | Sort_order precision exhaustion | Periodic transactional re-sequence on gap underflow. |
| 12 | Field-schema concurrent edit lost-update | Per-field rows (not a blob) → edits touch one row; `PATCH` read-modify-write is single-row. |
| 13 | `source_type='list'` rejected by `kb_chunks` CHECK → routing dead | Part 6 widens the CHECK to include `'list'` before any list embed. |
| 14 | Router matches an archived/merged-away list | `_reconcile_lists` skips archived; reap deletes chunks for gone/`is_archived` lists; candidate query filters `NOT is_archived`. |
| 15 | Per-list field call mutates a core/type def globally, or a sibling list (IDOR) | Field endpoints addressed by `{list_id}`+`key`; core/type rows immutable via API; per-list "remove" writes a `scope='list'` override only. |
| 16 | Brand-new/renamed list invisible to embedding-routing until next worker tick | Deterministic name-match (R4.5) covers the interim (a new list matches its own name exactly); latency is bounded by the tick interval. |

## Test Strategy

Tests extend `tests/test_lists.py` (or `test_lists_v2.py`), reusing the ephemeral-Postgres `fresh_db` + two-member `env` fixtures (`test_lists.py:36-63`). The suite runs migrations from empty, so it also proves `0054` applies on `fresh_db` (R3.3).

**Risk-targeted (the named three):**
1. **Seeded-duplicate dedupe (R2.2):** the merge SQL is factored into a callable; a test seeds two same-named active shared lists (older with `['milk']`, newer with `['eggs']`), invokes it, asserts survivor = lower id holding both items, loser `is_archived=true`, one `bh_list_merges` row `item_count=1`, zero items lost, partial index exists; re-invoke asserts a no-op.
2. **Member-deletion safety (R3.1):** item with `assignee_user_id=manon`; `DELETE` Manon; assert item survives with `assignee_user_id IS NULL`. Contrast: deleting a list still cascades items.
3. **Classifier-down degradation (R4.5):** monkeypatch embeddings/Ollama to raise; assert "add milk to grocery list" still adds via name match, an unmatched item lands on the default list uncategorized, nothing raises/loops/drops, no list created.

**Supporting:**
- Migration Part 6: after `0054`, a `source_type='list'` insert into `kb_chunks` succeeds (CHECK widened).
- Routing excludes dead lists: an archived/merged list is never returned as a routing candidate; its chunks are reaped.
- Threshold calibration: the fixtured `item→expected list` test measures the bge-m3 cosine distribution and asserts the configured `lists.routing` thresholds achieve the ≥90% goal (and fails loudly if the placeholder values don't — forcing real calibration).
- Field-mutation integrity (IDOR/core): a per-list `PATCH .../fields/{key}` on a core field disables it for that list only (writes a `scope='list'` override), leaves the core row and a sibling list untouched; direct edit of a `type`/`core` def is rejected.
- Schema engine: resolution precedence (list>type>core); override (rename grocery `store` label); `validate_value` accept/reject per `col_type` including core columns; soft-remove keeps values; option rename by `value` doesn't orphan.
- Per-item routing: "milk + wrap mom's gift + call dentist" → 3 correct lists, zero new/duplicate lists (acceptance 5).
- Fixtured labeled `item→expected list` set passing thresholds (≥90% goal, gated); ambiguous input → one clarifying question.
- No-auto-create on chat path; create requires explicit intent (acceptance 13).
- Custom column lifecycle (R1.5): add `number`/`single_select`, set value, reject bad-typed value 422, remove field retains `attributes` values (acceptance 14).
- Grouping/sort/filter: grocery groups by department in store-walk order; store dropdown filters by `attributes.stores` containment + shows untagged + reorders; five sort options; custom JSONB-field sort via whitelist; auto-cat assigns department without L3 (acceptance 7,8).
- ID-addressing: name shims still work; reorder writes fractional `sort_order` without clobber.
- Backfill: existing lists → `simple`; existing add/check/clear flow unchanged (re-run `test_lists.py:66-124`).
- Store option add (R6.5): add a store → appears in active-store dropdown (acceptance 16).
- `npx tsc --noEmit` clean.
