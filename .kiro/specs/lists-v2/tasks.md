# Lists v2 — Tasks

> Each task traces to one or more requirements. Work them top-to-bottom; respect dependencies.
> Backend: `bowershub-ai/backend`; frontend: `bowershub-ai/frontend`. DB-backed tests use the `fresh_db` + two-member `env` fixtures (`tests/test_lists.py:36-63`); run a throwaway `postgres:16` locally if no DB is reachable.

## Task 1: Migration `0054_lists_v2.sql` — schema spine, stores, seeds, backfill, dedupe
- **Effort:** L
- **Dependencies:** none
- **Requirements:** R1.1, R1.2, R1.3, R3.1, R3.2, R3.3, R2.2, R5.3
- [ ] Create `bh_list_types` (+ `uq_list_types_name` on `LOWER(name)`) and `bh_list_field_defs` (3-scope, `field_scope_target` CHECK, the three partial unique indexes on `key`).
- [ ] Add columns: `bh_lists.{list_type_id (FK ON DELETE RESTRICT), notes}`; `bh_list_items.{category, due_date, assignee_user_id, sort_order double precision, attributes jsonb DEFAULT '{}'}`. Add `bh_list_items_assignee_fkey` → `bh_users` **`ON DELETE SET NULL`** (guarded `DO $$…duplicate_object`). Indexes: `idx_list_items_{sort,category,assignee}`, GIN `idx_list_items_attrs`.
- [ ] Create first-class store tables: `bh_stores` (+`uq_stores_name`), `bh_store_aisles` (store→ordered departments), `bh_item_category_aliases` (+`uq_item_alias`).
- [ ] Seed 6 types (`simple, grocery, chores, gifts, todo, packing`) `ON CONFLICT DO NOTHING`; seed `core` field-defs (`storage='column'`), per-`type` field-defs (grocery `store` = `multi_select` `options_source='stores'`, `price`; etc.), grocery `category_set` (walk order, R5.3), starter `bh_item_category_aliases`.
- [ ] Backfill: every list `list_type_id IS NULL` → `simple`; `bh_list_items.sort_order = row_number()*1000` per list where NULL.
- [ ] Widen `kb_chunks_source_type_check` to include `'list'` (design Part 6) — DDL lives here, in the single `0054` file, so no later task re-opens an applied migration.
- [ ] Seed `bh_platform_settings` config rows: `lists.routing` (placeholder thresholds) and `lists.default_list_id`. **Elect a concrete default** in-migration: legacy `shopping` list if present, else oldest active shared list, else leave `null` (empty install).
- [ ] **R2.2 dedupe (ordered, before indexes):** create `bh_list_merges` audit table; merge colliding **active shared** lists into the lowest `id` (re-point items via `UPDATE`, log to `bh_list_merges`, archive losers + append note); DROP `bh_lists_name_user_id_key`; create `uq_lists_shared_name` on `LOWER(name) WHERE is_shared AND NOT is_archived` and `uq_lists_private_name` on `(name, user_id) WHERE NOT is_shared AND NOT is_archived` (**case-sensitive** private, matches dropped constraint).
- [ ] **Migration:** `bowershub-ai/backend/migrations/0054_lists_v2.sql` — forward-only, all `IF NOT EXISTS`/`ON CONFLICT`, single-transaction safe, applies on `fresh_db`.
- [ ] **Tests:** applies on `fresh_db` + idempotent re-run; `source_type='list'` insert into `kb_chunks` succeeds post-widen; config rows present; default elected (or null on empty install); **dedupe (the dangerous step, isolated):** seeded-duplicate merges into oldest / archives loser / zero item loss / one `bh_list_merges` row / re-run = no-op / partial index exists; member-deletion safety (assignee→NULL, item survives; list delete still cascades); backfill sets all lists to `simple`; existing `test_lists.py:66-124` add/check/clear still green.

## Task 2: Schema engine — `services/list_schema.py`
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.4, R1.5
- [ ] `resolve(conn, list_id) -> EffectiveSchema`: merge `core` → `type` → `list` rows by `key`, precedence list>type>core; expose merged field list with `storage`/`col_type`/`options`/flags.
- [ ] `validate_value(field_def, value)` per `col_type` (`number`/`single_select`/`multi_select`/`date`/`url`/`checkbox`/`text` + optional `{min,max,regex}`); parameterized; raises a 422-mapped error on mismatch.
- [ ] Write-dispatch helper: `storage='column'` → named column; `storage='attribute'` → `attributes[key]`. Option-set mutation helpers keyed by stable `value` (rename keeps value).
- [ ] `options_source='stores'` resolves options from `bh_stores` at read time.
- [ ] **Tests:** precedence + per-list override (rename grocery `store` label); accept/reject per `col_type` incl. core columns; soft-remove (`is_active=false`) keeps stored values; option rename by `value` doesn't orphan.

## Task 3: List service refactor — ID-addressing, resolve/create split, fractional ordering
- **Effort:** L
- **Dependencies:** Task 1, Task 2
- **Requirements:** R2.1, R3.4, R4.3
- [ ] Split `_resolve_list_id(create=True)` (`lists.py:18`) into `resolve_only()` and `create_list()`; **remove auto-create from the add path** (R4.3).
- [ ] Add ID-addressed twins: `add_items_by_id`, `check/uncheck`, `remove`, `clear`, all validating via `list_schema`.
- [ ] Fractional `sort_order`: `set_sort_order(item_id, prev, next)` = midpoint; `reorder(list_id, ordered_ids)` = transactional re-sequence to `n*1000`; all reads `ORDER BY sort_order, id` (deterministic tiebreak). Check/edit = last-write-wins.
- [ ] Rebalance on midpoint underflow (Risk #11): when the gap between neighbors is below an epsilon, trigger a transactional full re-sequence before inserting, so precision never exhausts.
- [ ] **Tests:** mutations are ID-addressed; no add path creates a list; midpoint move + full reorder preserve order; concurrent single-moves tie stably; underflow triggers a rebalance and order is preserved.

## Task 4: REST router — ID routes, name shims, type/field/store/config endpoints
- **Effort:** L
- **Dependencies:** Task 2, Task 3
- **Requirements:** R2.1, R2.3, R2.4, R1.4, R6.5
- [ ] ID-addressed routes: `GET /api/lists` (now returns `id`), `POST /api/lists`, `GET/PATCH /api/lists/{id}`, `POST /api/lists/{id}/{items,clear,items/reorder}`, `PATCH/DELETE /api/lists/items/{id}`, archive/unarchive, `DELETE /api/lists/{id}?confirm=true` (R2.4).
- [ ] Retained name-addressed compat shims (`GET/POST .../{list_name}/…`) resolving name→id; **UI shim keeps create-on-add**, chat path does not.
- [ ] Config/schema endpoints: `GET /api/list-types[/{id}]` (R1.4), `GET /api/lists/config`, `GET /api/lists/{id}/fields`; store CRUD `GET/POST/PATCH/DELETE /api/lists/stores[/{id}]` + `PUT .../stores/{id}/aisles`.
- [ ] Field endpoints by `{list_id}+key` with **integrity enforcement** (R6.5): core/type defs immutable via API; per-list remove writes a `scope='list'` override; reject cross-list/global mutation (IDOR guard). All routes `Depends(get_current_user)`; `_item_accessible` retained; shared/private semantics unchanged (R2.3).
- [ ] **Tests:** ID routes + name shims both work; confirm-required delete; per-list field call can't disable a core field globally or touch a sibling list; private list not visible/editable cross-user; bodies `extra:"forbid"`.

## Task 5: Embedding worker — list reconcile + reap
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R4.5
- [ ] (The `kb_chunks` CHECK widening is done in Task 1's migration — this task is worker code only, no migration edit.)
- [ ] Add `_reconcile_lists` (content = `name · type label · description`, content-hash dirty predicate; skips archived); extend `_reap_orphans` to delete `source_type='list'` chunks for gone/`is_archived` lists. Document the worker as the only `kb_chunks` write path; note tick latency for brand-new lists.
- [ ] **Tests:** a reconciled list gets a chunk; an archived/deleted list is reaped and never a candidate.

## Task 6: AI routing resolver — `services/list_router.py` + classifier/tool wiring
- **Effort:** L
- **Dependencies:** Task 3, Task 5
- **Requirements:** R4.1, R4.2, R4.3, R4.4, R4.5
- [ ] `route_items(text, user_id)`: split → per item deterministic name-match first, else embed + cosine `1-(emb<=>$1)` vs candidate list chunks filtered `(is_shared OR user_id=$me) AND NOT is_archived`; threshold decision from `bh_platform_settings['lists.routing']`; returns `[{text,list_id,list_name,attributes,confidence,needs_disambiguation}]`.
- [ ] No auto-create (R4.3): create only on explicit verb or `<create_threshold`; unmatched → default list uncategorized. Ambiguity within margin → one clarifying question (R4.4).
- [ ] Default-list resolution: if `lists.default_list_id` is null or points to an archived/deleted list, lazily create (once) a single shared `Shopping` default, persist its id back to the config, and add there — the one sanctioned system auto-create (idempotent by name), preserving the no-drop guarantee on `fresh_db`.
- [ ] Inject live active-list inventory into `router_engine._classify` (`:1010`, R4.1); make `tool_router` `manage_list` emit structured per-item output, drop `default: shopping` (R4.2).
- [ ] Degradation (R4.5): catch `EmbeddingError`/Ollama failure → name-match/default; add always succeeds.
- [ ] **Tests:** "milk + wrap mom's gift + call dentist" → 3 correct lists, zero new/dup lists; ambiguous → one question; classifier-down → name-match still adds, unmatched → default uncategorized, nothing raises/drops, no junk list created; **unmatched item on a `fresh_db` with no elected default lands on a lazily-created `Shopping` default** (no-drop holds).

## Task 7: Grouping / sort / filter + grocery auto-categorize — `services/list_grouping.py`
- **Effort:** L
- **Dependencies:** Task 2, Task 3
- **Requirements:** R5.1, R5.2, R5.3, R5.4, R5.5, R5.6
- [ ] Group by the type's `group_by` (R5.1); group order = active store's `bh_store_aisles` else type `category_set` (R5.3).
- [ ] Sort whitelist `_SORTS` (manual/name/due/recent/checked) via `.get(sort, 'sort_order')`; custom JSONB-field sort validates `key` ∈ effective schema + `^[a-z0-9_]+$`, casts by `col_type`; never interpolated (R5.2).
- [ ] Per-item multi-select store filter via parameterized `attributes->'stores' ? $1`; untagged items always shown; reorder by store layout (R5.4). Filter chips by category/assignee/status/store (R5.6).
- [ ] Grocery auto-categorize on add when `category` empty: `bh_item_category_aliases` lookup → Ollama fallback, never L3, editable (R5.5).
- [ ] **Tests:** grocery groups by department in store-walk order; store filter by containment + untagged shown; five sort options; injection sort key falls back to default; auto-cat assigns department without L3.

## Task 8: Remove legacy hardcoded "shopping" default
- **Effort:** S
- **Dependencies:** Task 3, Task 4
- **Requirements:** R6.6
- [ ] Remove `list_name="shopping"` default (`skills/lists.py:21`) and the `default: shopping` hint in the L3 tool; fallback list comes from `bh_platform_settings['lists.default_list_id']`.
- [ ] **Tests:** no `"shopping"` constant remains in the list skill/tool path; fallback resolves from DB config.

## Task 9: Frontend — generic schema-driven list view
- **Effort:** L
- **Dependencies:** Task 4
- **Requirements:** R6.1, R6.2, R6.3, R6.4
- [ ] Rework `ListsPage.tsx` to carry `activeId:number` (was name, `:31`); fetch `/api/list-types` + effective schema; one `ListView` parameterized by schema (`FieldRenderer`/`FilterChips`/`SortMenu`/`GroupedItems`) — no per-type branches (R6.1).
- [ ] `ListSwitcher` with create/rename/delete(confirm)/archive + type picker (R6.2). Preserve optimistic add/toggle/remove/clear against ID endpoints (`:84-116`, R6.3).
- [ ] All options API-fetched, theme tokens only, no hardcoded type/store/department lists (R6.4).
- [ ] **Tests:** `npx tsc --noEmit` clean; component tests for grouped render, optimistic add/toggle, switcher.

## Task 10: Frontend — per-list settings panel (columns + options/store editor)
- **Effort:** M
- **Dependencies:** Task 9, Task 4
- **Requirements:** R6.5, R1.5, R5.4
- [ ] `ListSettingsPanel`: view list's columns; add column (col_type picker incl. `multi_select`); rename/reorder/soft-remove; edit select/multi-select **options** incl. the built-in store field; list-level name/type/default-sort/archive (R6.5/R1.5).
- [ ] Adding a store option (→ `bh_stores`) immediately repopulates the active-store dropdown (R5.4).
- [ ] **Tests:** add a `number`/`single_select` column → set value → bad-typed value rejected → remove keeps values; add a store → appears in active-store dropdown.

## Task 11: Threshold calibration + end-to-end routing fixture — DONE (2026-06-30)
- **Effort:** M
- **Dependencies:** Task 5, Task 6
- **Requirements:** R4.3, R4.4
- [x] Fixture setup: seed representative lists, **run `_reconcile_lists` so `kb_chunks` is populated**, then measure — never calibrate against an empty `kb_chunks`.
- [x] Build a labeled `item → expected list` fixture set; measure the bge-m3 cosine distribution; **UPSERT** `lists.routing` `match_threshold`/`create_threshold`/`ambiguity_margin` from it (the seeded values are placeholders).
- [x] **Tests:** fixtured set achieves the ≥90% routing goal with zero duplicate-list creations; test fails loudly if placeholder thresholds underperform (forces real calibration).

> **Design amendment (calibration finding).** Real bge-m3 calibration showed the as-built routing document — `name · type_label · LIST.description` — was too thin (~71% accuracy, real mis-routes; correct/noise overlapped with NO separating threshold), because real lists rarely carry a per-list description, so the embedded text was often just `"Groceries · Grocery · "`. Fix (migration `0055` + `embedding_worker._LIST_CONTENT_SQL`): fold the **TYPE** description into the document via `concat_ws`, and enrich the seeded type descriptions with representative item terms (stable, type-level — NOT churning per-list item names, so no re-embed storm; the "item names excluded" decision stands in spirit). This lifts routing to **90.3%** (0 noise-leak, 1 mis-route) with clean separation, calibrating thresholds at **match=0.40 / margin=0.04** (was the 0.55/0.07 placeholder). Verified three ways: calibration script (real Ollama), deterministic fixture test (`test_list_routing_calibration.py`, CI-safe, also asserts the placeholder *fails*), and a live end-to-end run through real pgvector halfvec (6/6). Fixture: `backend/tests/fixtures/lists_routing_calibration.json`.

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (validator exits 0).
- [ ] No hardcoded config introduced — list types, stores, departments, thresholds, default list are DB rows read via API; no `"shopping"` constant remains.
- [ ] Parameterized SQL only; dynamic sort/group identifiers go through the whitelist + schema-key validation; JSONB filters use array containment params.
- [ ] Migration `0054` is forward-only, applies on `fresh_db`, idempotent, loses no data (dedupe merge logged + reversible).
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`).
- [ ] Name→ID cutover deployed in the staged order (migration → backend dual-contract → frontend) with no broken window.
- [ ] `context-log.md` updated with a dated entry.
