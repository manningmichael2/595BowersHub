# Lists v2 — Best-in-class generic list handler — Requirements

## Overview

Evolve the existing (intentionally simple) Lists module into a **best-in-class generic list handler**: many *typed* lists (grocery, chores, gift ideas, to-do, packing, …), each picked from a dropdown and filterable, with the AI assistant reliably routing free-text items to the **correct existing list** instead of guessing a name and silently spawning duplicates. List *types*, *stores*, and *departments* are DB-driven config (no hardcoding), so adding a new kind of list is a data insert, not a code change. We **extend** `bh_lists`/`bh_list_items` and the existing native `list` skill — we do not rewrite them. Scope deliberately stops short of Grocy/ERP territory (no inventory/stock/barcode).

Owner intent (from `context-log.md` 2026-06-28 + `grocery-list-v2` memory, broadened in this session): *"a more robust list handler in general… the list is selected from the dropdown and then the list itself can be filtered… I trust you can build a best-in-class list handler."*

## Feature 1: List types as data (configurable, not code)

### R1.1 — List-type definitions live in the database
The system stores list-type definitions in a new DB table (`bh_list_types`), each declaring at minimum: name, icon, which item fields are active and their labels, the grouping field (`group_by`), the default sort, and an ordered category set. Adding or editing a type is an INSERT/UPDATE — never a Python/TS enum or dict (Project rule #1, NO-HARDCODING).

### R1.2 — Seeded starter types
A forward-only migration seeds a starter set of types: at least `simple` (the generic default), `grocery`, `chores`, `gifts`, `todo`, and `packing`. Seeds are editable defaults (mirrors the theme/skill seed pattern). `bh_list_types` has a `UNIQUE(name)` (or `UNIQUE(LOWER(name))`) constraint so the seed is idempotent via `ON CONFLICT (name) DO NOTHING`.

### R1.3 — A list has a type; type drives behavior
Each list references a list-type (`bh_lists.list_type_id`). The migration **backfills** existing un-typed lists (and the legacy default list) to the seeded `simple` type rather than leaving `list_type_id` NULL with undefined behavior. The `simple` type explicitly defines its own field set (text/checked/quantity/notes only), `group_by` (none), and default sort (recently-added). The type definition drives which item fields, grouping, and sort options the UI and AI use for that list. Existing lists continue to work unchanged.

### R1.4 — Types exposed via API
List-type definitions are readable via an authenticated API endpoint so the frontend renders fields/grouping from data (same pattern as `/api/slash-commands`, `/api/themes`).

### R1.5 — User-defined custom columns (typed fields) — the Notion-database model
A user can add their own custom column/field to a list, choosing its **column type** from a supported set: at minimum `text`, `number`, `date`, `checkbox`, `single-select` (one user-defined option), `multi-select` (several user-defined options — the same array-valued mechanism as the per-item store tag in R5.4), and `url`. The system stores these field definitions as data (a per-list field schema — extending the type's `fields` definition, see R3.2), and renders/validates item values against the declared type. This makes a list behave like a lightweight Notion database. Concretely:
- **Field schema is data, not code** (NO-HARDCODING): a field definition = `{ key, label, col_type, options?, required?, sort_order }`, stored on the list (overriding/augmenting its type's seeded fields). Adding a column is a DB write + a small API call, never a code change.
- **Values live in the JSONB `attributes` tail** (R3.2), keyed by the field `key`, with the value shape governed by `col_type`. The cross-cutting typed columns (R3.1) are the built-in fields every list gets; custom fields are the user-extensible tail.
- **Validation:** the API rejects a value whose shape doesn't match its field's `col_type` (e.g. a non-numeric value for a `number` field, an option not in a `single-select`'s option set). Validation is server-side, parameterized.
- **Lifecycle:** a user can add, rename, reorder, and remove a custom field; removing a field hides it from the UI and stops validating it (existing values in `attributes` are retained, not destructively purged, so removal is reversible). For `single-select`/`multi-select` fields the user can also add, rename, reorder, and remove the field's **options** (e.g. add a new store to the store field's option set); renaming an option updates its label without orphaning items that hold the old value.
- **Type-vs-list scope:** seeded `bh_list_types` provide sensible default fields per type (grocery → store/department/quantity; gifts → recipient/price/url); a custom field added to a specific list layers on top of (or overrides) its type's defaults. Design decides whether a custom field can also be promoted to the type level — not required for v1.
- Custom fields participate in grouping/sorting/filtering (R5) **where the `col_type` supports it** (e.g. group/sort by a `single-select` or `date` field; `url` is display-only). Sorting on a JSONB-backed custom field still goes through the validated sort whitelist mechanism (R5.2), not raw interpolation.

## Feature 2: Multiple named lists — full lifecycle

### R2.1 — Create / rename / delete / archive lists, by ID
The system provides REST endpoints and UI to create a new named list (with a chosen type), rename it, delete it, and archive/unarchive it. (Today the router has *no* create/rename/delete; the UI can only switch between existing lists.) Because rename and the no-duplicate rule (R4.3) are impossible on the current name-addressed API, **mutating list/item operations move to list-ID addressing**: the API contract migrates from `{list_name}` paths to `{list_id}`. Name resolution (chat/AI) happens once, up front, to select an ID; mutations never re-resolve a name and never auto-create. The frontend switches the dropdown to carry list IDs. (Migrating the public API contract name→ID is explicitly in scope.)

### R2.2 — Shared-name uniqueness is correct for a household
The current `UNIQUE (name, user_id)` constraint on `bh_lists` lets two members create same-named shared lists, after which the resolver silently picks one. The system enforces uniqueness appropriate to sharing via a partial functional unique index: a shared list name is unique household-wide (`UNIQUE(LOWER(name)) WHERE is_shared`); private (`is_shared=false`) lists stay unique per creator. **Existing-duplicate dedupe procedure (explicit):** before adding the index, the migration merges any colliding shared lists — items of the newer list(s) are re-pointed to the oldest (lowest `id`) list, the emptied loser lists are archived (not deleted), and the merge is recorded (a log row / `notes`), so no item data is lost. A test seeds a duplicate-shared-name scenario and asserts this outcome.

### R2.3 — Lists stay household-shared by default
Shared lists (`is_shared=true`) remain visible/editable by every active household member; private lists stay creator-scoped. Owner attribution (`user_id`, `added_by`) is a display/filter label, never an access boundary (consistent with the household-setup decision). No per-user list silos are introduced.

### R2.4 — Deleting a list is safe and intentional
Deleting a list cascades to its items (existing FK behavior) but requires explicit confirmation in the UI and is reversible-by-archive as the soft default; only an explicit delete removes data.

## Feature 3: Item data model — typed core + flexible tail

### R3.1 — Cross-cutting item fields are typed columns
The system adds typed, queryable/sortable columns to `bh_list_items`: `category` (the grouping bucket — department/aisle for grocery, section/assignee-bucket for others), `due_date timestamptz`, `assignee_user_id int`, and `sort_order` (manual ordering). `assignee_user_id` is a FK to `bh_users` with **`ON DELETE SET NULL`** (deleting a household member must NOT cascade-delete their assigned items — contrast `bh_lists.user_id`'s `ON DELETE CASCADE`). `quantity`, `text`, `checked`, `notes`, `checked_at` are retained as-is. `added_by` stays **free-text** (its existing `'chat'`/source-label semantics) and is the *provenance* field; structured *assignment* is the separate `assignee_user_id` — the two are not merged, and this split is intentional and documented.

### R3.4 — Concurrency on shared lists
Two members may edit a shared list at once. Check/uncheck and field edits are **last-write-wins** (acceptable; no version column required). Manual reordering writes `sort_order` **relative/transactionally** (e.g. fractional or gap-based ordering, or a single transactional re-sequence) rather than each client overwriting absolute indices, so concurrent reorders don't clobber each other or corrupt order.

### R3.2 — Type-specific fields live in a JSONB tail
Low-cardinality, type-specific fields (e.g. `url`, `price`, `store`, `priority`) are stored in a JSONB `attributes` column on `bh_list_items` (default `'{}'`), not as ever-growing columns and not as EAV rows. Which attributes are active for an item is governed by its list's type (R1.1).

### R3.3 — Additive, back-compatible migration
All schema changes are a forward-only additive migration (next free number, `0054+`), using `ADD COLUMN IF NOT EXISTS`, applying cleanly on a `fresh_db` build-from-empty (project rule C2). No existing column is dropped or repurposed.

## Feature 4: AI routing — "which list does this item belong to?"

### R4.1 — The router sees the live list inventory
When the assistant handles a list action, it is given the household's current active lists (name + type + short description) as a constrained choice, rather than inferring a bare `list_name` string from prose. This closes the current gap where `router_engine._classify` passes no list inventory.

### R4.2 — Per-item routing for multi-item input
Free-text containing items for different lists ("milk, wrap mom's gift, call dentist") is split and each item routed to its appropriate list independently, returning structured `{text, list_name, attributes}` per item.

### R4.3 — No silent duplicate-list creation (ID-resolved, numeric thresholds)
The assistant resolves free-text to an **existing list ID** and adds there when a match is confident; it does **not** auto-create. The auto-create-on-add behavior in `_resolve_list_id(create=True)` is removed from the add path and replaced by explicit create intent. Thresholds are **numeric and DB-driven** (a config table/row, mirroring the existing read-only-vs-`0.75`-write threshold precedent): add-to-existing when best-match similarity ≥ `match_threshold`; create-new only when an explicit new-list verb is present ("start/make/create a … list") **or** best-match similarity < `create_threshold`; disambiguate (R4.4) when the top-2 candidates are within `ambiguity_margin`. New lists get a type auto-classified from `bh_list_types`. (Concrete defaults to be set in design, e.g. match ≥0.75, create <0.45, margin ≤0.1 — tunable via DB.)

### R4.4 — Disambiguate only when genuinely ambiguous
When the top candidate lists fall within `ambiguity_margin` (R4.3), the assistant asks one short clarifying question rather than guessing; otherwise it acts without friction (default-confident, ask-rarely).

### R4.5 — Cost-tiered classification with graceful degradation
Routing follows the existing tiered router and the `categorizer.py` precedent: cheap heuristics/Ollama (and item→list similarity reusing `hybrid_retrieval.py`/`embeddings.py`) handle the obvious majority; the expensive model (L3/Sonnet) is used only for ambiguous or multi-intent input. Interactive add stays off L3 in the common case. **Degradation:** if Ollama/pgvector/the classifier is unavailable, the add still succeeds via deterministic case-insensitive name match (or the explicitly named list); the item is simply added uncategorized — routing never blocks, loops, or drops the item.

## Feature 5: Grouping, sorting, filtering (grocery is the flagship)

### R5.1 — Grouping by the type's group field
The list view groups items by the type's declared `group_by` (grocery → department/aisle; chores/todo → assignee or status; packing → section). Grouping is one parameterized mechanism, not per-type code.

### R5.2 — Sort options
Each list supports sorting by manual order (`sort_order`), name, due date, recently-added, and checked state. **DB-driven vs whitelist boundary:** the set of sort *algorithms* is a fixed server-side validated whitelist (a security control against SQL identifier injection — the `transactions_query` precedent); the **default sort per type** is the DB-driven, configurable bit (lives on `bh_list_types`). Adding a brand-new sort algorithm is a code change (rare); changing a type's default is a DB edit. The list above is the initial whitelist, not a frozen contract.

### R5.3 — Departments are ordered, DB-driven data
Departments/aisles are stored as data (per-type ordered `category_set`), never a code enum. Department order reflects a physical store walk (the AnyList pattern). **Precedence:** when a store is active (R5.4), that store's aisle order overrides the type's default `category_set` order; with no active store, the type's order applies.

### R5.4 — Store dropdown and store-scoped ordering (grocery) — store is PER-ITEM, MULTI-VALUED
**Decision (owner):** store is a **per-item, multi-select** tag (`attributes.stores` = an array), not a per-list property — an item can be available at several stores ("milk at Meijer *and* Kroger") and one grocery list spans stores. The active-store dropdown *filters/reorders* the single list: selecting a store shows items whose `stores` array contains it (plus un-tagged items) and reorders them by that store's aisle layout. An item with no store tag always shows under any active store. Each store's department ordering is stored as data (a store→ordered-departments mapping). Stores and their layouts are DB-driven user data (household-specific), not constants. Filtering an array-valued field uses parameterized array containment (e.g. `attributes->'stores' ? $1`), never interpolation.

### R5.5 — Auto-categorize new grocery items
When an item is added to a grocery list without a department, the system assigns a department via a cheap lookup/classifier (a seeded item→department alias table and/or the Ollama classifier — never L3), editable by the user.

### R5.6 — Filterable list view
The selected list can be filtered in the UI by category/assignee/status/store via filter chips, driven by the type's declared fields — one component for all types.

## Feature 6: Frontend — one generic list experience

### R6.1 — Type-aware single list view
`ListsPage` renders a single component parameterized by the list's type definition: it shows the right fields, grouping, sort, and filters for grocery vs chores vs gifts without bespoke per-type screens.

### R6.2 — List management UI
The dropdown switcher gains create / rename / delete / archive affordances (R2.1) and a type picker on create.

### R6.3 — Preserve current ergonomics
Add / check / remove / clear-checked and optimistic updates are preserved; no regression to the fast add-and-check flow the owner already likes.

### R6.4 — No hardcoded UI config
All themes/colors use existing theme tokens; type/store/department options are fetched from the API, never hardcoded in the component.

### R6.5 — Per-list settings panel (columns & options editor)
Each list has a settings panel (opened from the list view) that shows **that list's columns/fields** and lets the user manage them without leaving the app: add a new column (choosing its `col_type` per R1.5), rename/reorder/remove columns, and — for `single-select`/`multi-select` fields, including the built-in **store** field — view and edit the option set (add a new store, rename, reorder, remove). The panel also exposes list-level settings (name, type, default sort/grouping, archive). All options shown are fetched from the API (DB-driven), never hardcoded. This is the surface where "add a new store to pick from" and "see/edit the columns per list" live.

### R6.6 — Remove the legacy hardcoded "shopping" default
The hardcoded `list_name="shopping"` default in `services/skills/lists.py` and the `default: shopping` hint in the L3 `manage_list` tool description are removed. Any fallback list is sourced from DB config (e.g. a household "default list" setting), not a code constant — closing the NO-HARDCODING gap the new routing depends on.

## Acceptance Criteria

- [ ] A migration adds `bh_list_types`, `bh_lists.list_type_id`, and `bh_list_items.{category, due_date, assignee_user_id, sort_order, attributes}`; it applies cleanly on `fresh_db` and is idempotent.
- [ ] Starter types (grocery/chores/gifts/todo/packing) are seeded and editable; adding a 6th type is a pure DB insert with no code change.
- [ ] REST endpoints exist for create/rename/delete/archive list; the UI exposes all four with confirm-on-delete.
- [ ] Two household members cannot end up with two same-named shared lists; the constraint migration succeeds against existing data.
- [ ] "add milk and wrap mom's gift" via chat puts milk on the grocery list and the gift item on the gifts list, creating neither a duplicate grocery list nor a stray list.
- [ ] Asking to add an item whose target is ambiguous yields one clarifying question, not a guess.
- [ ] A grocery list groups items by department in store-walk order, supports a store dropdown, and offers the five sort options.
- [ ] New grocery items get an auto-assigned, user-editable department without an L3 model call.
- [ ] The list view can be filtered by the type's fields via chips.
- [ ] Existing lists are backfilled to the `simple` type and the current add/check/clear flow continues to work unchanged.
- [ ] A seeded duplicate-shared-name scenario merges into the oldest list, archives the loser(s), and loses no items (R2.2).
- [ ] A fixtured routing test set (labeled `item → expected list` cases) passes the routing thresholds; deterministic name-match fallback works with Ollama/pgvector stubbed unavailable (R4.5).
- [ ] No code path auto-creates a list on add; create requires explicit intent (R4.3).
- [ ] A user can add a custom column to a list (e.g. a `number` "price" or a `single-select` "priority"), set values on items, and the API rejects a value that violates the column's type; the column can be renamed/removed and existing values survive removal (R1.5).
- [ ] Mutating list/item endpoints are ID-addressed; the frontend dropdown carries list IDs (R2.1).
- [ ] From a list's settings panel, a user can see that list's columns, add a new store to the store field's options, and that store immediately appears in the active-store dropdown (R6.5).
- [ ] `npx tsc --noEmit` clean; new DB-backed tests in `test_lists.py` (or a v2 file) pass; full suite green.

## Non-Functional Requirements

- **No hardcoding:** list types, stores, departments, sort options, and any new slash flags are DB-driven (Postgres), read via API — never code constants (Project rule #1). New `list`-skill behavior and any command/flag are DB rows.
- **Data safety:** parameterized SQL only; identifiers (e.g. dynamic sort key) go through a whitelist (`transactions_query` precedent), never interpolation. Forward-only additive migration; the constraint change must be safe against existing rows. Delete is confirmed; archive is the soft default.
- **Security:** every endpoint `Depends(get_current_user)`; per-item access stays enforced in the service (`_item_accessible`). Shared/private semantics unchanged; attribution never used as an access gate.
- **Performance / cost:** AI routing and auto-categorization stay off L3 for the common case (heuristics/Ollama/embeddings first); interactive add/check remains optimistic and fast; grouping/sort done in-query where index-friendly.

## Constraints & Assumptions

- Runs on the existing stack (FastAPI + Postgres + React/Vite) on the Minisforum; migrations auto-applied on startup, forward-only, checksummed.
- Extend the existing module (`services/lists.py`, `routers/lists.py`, `services/skills/lists.py`, `pages/ListsPage.tsx`) — do not fork a parallel structure or entangle with `services/inventory.py`.
- Household is two users (Michael + Manon); sharing is the default; no workspace-level access gating for lists.
- Embeddings infra (pgvector, `hybrid_retrieval.py`, `embeddings.py`, Ollama `bge-m3`) already exists and may be reused for item→list similarity.

## Dependencies

- Migration `0054+` must land before service/router/UI changes that read the new columns.
- AI routing changes depend on `router_engine.py` (L2 `_classify` ~line 1010, L3 `tool_router.py` list tool ~line 368) and the `categorizer.py` classifier pattern.
- No new external APIs. No new infra containers (explicitly not Grocy).

## Out of Scope (scope discipline — avoid the ERP trap)

- Inventory/stock levels, on-hand quantities, pantry tracking, expiry dates.
- Barcode scanning, purchase history analytics, price-over-time tracking, supplier management, recipe→ingredient explosion.
- `quantity` stays simple free-text (not a numeric stock unit).
- The one allowed "smart" extra beyond the above: **past-item autocomplete/suggestions** — suggest previously-used item *names* by frequency/recency when typing. Explicitly bounded: no time-series, no purchase/price history, no analytics surface. (This is the scope seam with "purchase history analytics" above — suggestions are name reuse only.)

## Goals (non-gating — direction, not pass/fail gates)

These are targets to steer by; the mechanically-checkable bar is the Acceptance Criteria above.

- **Routing accuracy:** ≥90% of the fixtured labeled single-item cases route to the correct existing list with zero duplicate-list creations. (Gated via the fixtured test in Acceptance Criteria; the "90%" target is measured against that set.)
- **Extensibility:** adding a new list type or store requires 0 code changes (DB insert only).
- **No regression:** the existing add/check/clear flow stays as fast/optimistic as today.
- **Adoption signal (owner, non-testable):** the owner actually uses ≥2 distinct list types and the store/department grouping in real use — the "I use the features" bar that motivated the work.
