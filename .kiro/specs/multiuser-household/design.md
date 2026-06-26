# Multi-User Household — Design

> Satisfies requirements in `requirements.md` (R1.1–R5.5, decisions D1–D8). Requirement IDs referenced inline.

## Synthesis note (design tournament)

Three approaches were generated in parallel and synthesized here:

- **Spine = minimal-change.** The substrate already does ~80% of this (live role reads, `bh_skills.min_role` DB-gate precedent, `_invalidate_resolver` cache pattern, per-message role re-fetch on the WS path). The project's standing rule is no over-engineering for a ≤5-user household, so the base is a small, surgical generalization — **not** a policy engine, ABAC, or a `role_permissions` join (D4).
- **Grafted from risk-first (the decisive additions):** a **rollout order with no ungated window** (§7), a **boot-time self-check** that fails startup if any `require_capability` literal lacks a DB row, a **mechanical route-audit test** ("zero ungated finance/admin routes"), the **`__deny__` sentinel** ranked above admin for unknown capabilities, the **`bh_messages` IDOR** decision (enforce via conversation join, do *not* denormalize `user_id`), the **cache-key audit** with concrete targets, and the **panic-revert** path.
- **Grafted from ideal-architecture:** the **single-chokepoint** framing (one resolver is the only place R5.3 precedence lives) and the **server-computed effective-access payload** the frontend consumes (never infers permission from role).
- **Why the losers lost:** *ideal* introduced 2 services + a resolver class + a feature-registry abstraction that is over-built for two features — its concepts were kept, its ceremony dropped. *minimal* alone under-weighted the rollout-order risk and the boot self-check — its diff discipline was kept, risk-first's safety rails added on top.

The result: **one cohesive `authz` module + 4 additive migrations + dependency swaps**, shipped in a safe order.

---

## Architecture Overview

```
  PWA (React)                         FastAPI                              Postgres
  ┌──────────────┐   GET /me/features ┌───────────────────────────┐
  │ useHasRole   │◀───────────────────│  authz.effective_access()  │       bh_users (role, live read)
  │ useFeatures  │  {role,caps,        └───────────────────────────┘       bh_capabilities  (cap→min_role)
  │ nav, profile │   features[]}                 ▲                          bh_features       (key, floor)
  └──────┬───────┘                               │                          bh_user_feature_access (override)
         │ request + JWT                         │ one chokepoint           finance.* (+created_by/updated_by)
         ▼                                       │
  ┌────────────────────────────────────────────────────────────────┐
  │ get_current_user  → live bh_users row (role read live, NEVER JWT) │  R1.6
  │   ↓                                                              │
  │ require_role(min) | require_capability(cap) | require_feature(k) │  R1.2 / R1.4 / R5.2
  │   → authz.resolve(user, cap) =                                   │
  │       rank(role) ≥ min_role(cap)        [DB, fail-closed]        │  R1.1 / R1.3
  │       AND NOT feature-disabled-for-user [restrict-only]          │  R5.3
  │       AND NOT (floor AND role<admin)    [unconditional]          │  R5.3 / R1.5
  └────────────────────────────────────────────────────────────────┘
         │ pass                                   │ WS path: skill_executor re-fetches role per message (R1.7)
         ▼                                        ▼
  router handler → service stamps created_by/updated_by from session (R4.1)
```

**New vs reused.** *New:* one backend module `services/authz.py`, 4 migrations, ~6 admin endpoints, 1 effective-access endpoint, 1 frontend hook + UI wiring. *Reused as-is:* `get_current_user` live-role read (`auth.py:24,40`), the per-message role re-fetch on the WS path (`skill_executor.py:90-96`), the `_invalidate_resolver` cache pattern (`admin.py:38`), the `bh_skills.min_role` semantics (`0028`), `bh_users.settings_json`, `bh_invite_links` / `bh_password_reset_tokens`, the existing `update_user` PATCH (`admin.py:60`), and the `0021` grant convention.

## Components

### `services/authz.py` (NEW) — the single authorization module
- **Responsibility:** the one place role rank, capability resolution, and per-user feature access compose. Holds the canonical ladder; resolves a `(user, capability) → bool`; computes the frontend effective-access payload.
- **Location:** `bowershub-ai/backend/services/authz.py`
- **Key contents:**
  - `ROLE_RANK = {"viewer": 10, "member": 20, "admin": 100}` — **canonical, single definition** (R1.1). `skill_executor.py:21` deletes its local map and imports this.
  - `DENY = 10_000` — sentinel rank above admin. `rank(role)` returns `ROLE_RANK.get(role or "", -1)` (unknown/None → −1, below viewer → fail-closed).
  - `CapabilityCache` — in-process `{capability: min_role}` from `bh_capabilities`, with `reload()`. `min_role_rank(cap)` returns the configured rank, else a code fallback (`_DEFAULT_CAPS`), else **`DENY`** (unknown capability denies everyone — R1.1/R1.3 symmetric fail-closed). The fallback dict is asserted equal to the seed by a test.
  - `FeatureCache` — `bh_features` (incl. `admin_only_floor`) + per-user overrides from `bh_user_feature_access`; per-user lookups are **keyed by `user_id`**.
  - `resolve(user, capability) -> bool` = `rank(role) ≥ min_role_rank(cap)` **AND** `not feature_disabled(user_id, feature_of(cap))` **AND** `not (floor(feature) and rank(role) < ROLE_RANK['admin'])`. This is the **only** implementation of the R5.3 precedence.
  - `effective_access(user) -> dict` = `{role, capabilities:[...], features:[{key,label,routes,permitted}]}` for `GET /me/features` (R5.5).
- **Reuses:** mirrors `model_catalog` cache+reload shape; parameterized asyncpg queries.

### `middleware/auth.py` (EXTENDED) — dependencies (the chokepoint)
- `require_role(min_role)` — factory; 403 when `rank(user.role) < rank(min_role)`; **unknown `min_role` key → 403** (fail-closed). (R1.2)
- `require_capability(cap)` — factory; 403 when `not authz.resolve(user, cap)`. The preferred gate for finance/admin endpoints (carries feature-override + floor). (R1.4/R5.2)
- `require_admin = require_role("admin")` — preserved name; ~30 existing call sites untouched. (R1.2)
- All read the **live** `bh_users` row via `get_current_user`; **never** the JWT `role` (R1.6). A code comment at the JWT decode site marks payload role as informational-only.

### `services/skill_executor.py` (MODIFIED)
- Delete local `ROLE_RANK`; import from `authz`; `_user_meets_min_role` (`:84-97`) uses `authz.rank` — fixes the `viewer == member` bug and the 0/999 mismatch (R1.1/R3.3). Per-message live re-fetch (`:90-96`) is preserved → WS demotion effective next skill message (R1.7).
- **Import direction (M2):** `authz.py` imports only `database.get_pool` + asyncpg (no import of `skill_executor`/`middleware.auth`), so `skill_executor → authz` is acyclic. **Test fix:** `tests/test_skill_min_role.py:11,62` imports and asserts on the old `ROLE_RANK` values (`member:0`) — it must be updated to the canonical `{viewer:10,member:20,admin:100}` (a named task).

### `websocket/handlers.py` (MODIFIED) — per-message live user (M1)
- **The connect-time `user` dict (`handlers.py:74`) is captured once and reused for the socket's life (`:111`, and `RoutingContext.user_role` `:260`).** Skill gating re-fetches role live, but **deactivation** (`is_active`) and any non-skill path would otherwise read the stale snapshot. Fix: the message loop **re-loads the live user (role + `is_active`) per message** before dispatch; a deactivated or demoted user is rejected on the **next message** with no reconnect (R1.6/R1.7). `RoutingContext.user_role` is treated as prompt-flavor only — **no authz decision may read it**.

### `routers/admin.py` (EXTENDED)
- Capability CRUD (`GET`, `PATCH /capabilities/{cap}`), feature registry (`GET /features`), per-user feature override (`GET/PUT /users/{id}/features`). Every write calls `authz.reload()` (R1.3).
- `update_user` (`:60`) gains the **transactional last-admin invariant** (R2.1a) and role-value validation against `{viewer,member,admin}`. **Locking (M3):** the role/active UPDATE and the `SELECT count(*) FROM bh_users WHERE role='admin' AND is_active` run inside one `conn.transaction()`, and the count query takes `FOR UPDATE` on the admin rows (or a transaction-scoped advisory lock on a fixed key) so two concurrent demotions serialize — without the lock both readers see "1 remaining admin" and both commit → zero admins. Roll back + **409** if the post-change count is 0. The existing dynamic-SQL builder (`admin.py:67`) interpolates only Pydantic **field names** (never values) — preserved; role-value validation is an `in {viewer,member,admin}` check before the UPDATE, the DB CHECK is the backstop.
- **Invite-revoke / reset-link placement (M4):** these belong with the provisioning machinery in `routers/auth.py` + `services/auth.py` (`use_invite`, `bh_invite_links`, `bh_password_reset_tokens` live there). Implement them in `auth.py` under `require_capability("users.manage")` (admin) — *not* duplicated into `admin.py`. If kept on the admin surface, `admin.py` must take an `AuthService` dependency (today it imports only `require_admin` + `get_pool`).

### Finance routers (MODIFIED) — dependency swap only
- `finance_review.py`, `finance_budgets.py`, `finance_accounting.py`, `finance_insights.py`, `retirement.py`, `finance_qa.py`: swap `Depends(require_admin)` → `Depends(require_capability(...))` per the enumerated table below. Handler bodies unchanged (the dependency still yields `user: dict`). Service-layer writes stamp `created_by`/`updated_by` from `user["id"]` (R4.1).

### Frontend
- `hooks/useHasRole.ts` (NEW; `useIsAdmin` becomes a `useHasRole('admin')` shim), `hooks/useFeatures.ts` (NEW; consumes `/me/features`).
- `stores/auth.ts` stores the effective-access payload, refreshed with the user.
- `Sidebar.tsx` / `BottomTabBar.tsx`: a feature button shows iff `permitted (server) AND not self-hidden (settings_json)` (R5.5).
- `pages/admin/UsersSection.tsx`: wire the existing PATCH (role select + activate/deactivate), revoke-invite, reset-link, per-user feature toggles.
- Profile/settings: cosmetic self-hide → `settings_json.hidden_nav`; lists **only** permitted features (R5.4).

## Data Flow

**HTTP write (member categorizes):** JWT → `get_current_user` (live row) → `require_capability("finance.write")` → `authz.resolve` (rank ✓ ∧ finance not disabled ✓ ∧ not floored ✓) → handler → service stamps `updated_by = user["id"]`. Any layer fails → 403, handler never runs.

**WS skill:** per message, `skill_executor._user_meets_min_role` re-fetches role from `bh_users` → `authz.rank` → demotion effective this message, no reconnect (R1.7).

**Admin disables Finance for a member (R5.2):** `PUT /users/{id}/features/finance {enabled:false}` → `authz.reload()` → that member's next request: `/me/features` omits finance **and** `/api/finance/*` returns 403.

**Self-hide (R5.4, cosmetic):** `PUT /me/settings/nav` → `settings_json.hidden_nav` → frontend hides button → direct `GET /api/finance/*` still **200** (proves cosmetic; a 403 here is a bug).

## Data Model / Migrations

Forward-only, auto-applied, additive/nullable, idempotent (`IF NOT EXISTS`), each ending with the `0021`-style grant block so `bowershub_app` keeps DML and `finance_reader` is unaffected. Numbered from **0039**.

### `0039_capabilities.sql` (R1.3, generalizes `0028`)
```sql
CREATE TABLE IF NOT EXISTS public.bh_capabilities (
    capability text PRIMARY KEY,
    min_role   text NOT NULL CHECK (min_role IN ('viewer','member','admin')),
    description text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL
);
INSERT INTO public.bh_capabilities (capability, min_role, description) VALUES
  ('finance.read',           'viewer', 'View finance data'),
  ('finance.write',          'member', 'Everyday finance writes (categorize/split/budget/rules/retirement) — D2'),
  ('finance.insight.action', 'member', 'Dismiss/action insights — resolves D2 vs require_admin'),
  ('finance.delete',         'admin',  'Structural/destructive finance ops (delete/account-type) — D2'),
  ('users.manage',           'admin',  'User provisioning & role changes'),
  ('settings.write',         'admin',  'Platform/theme/skill/model/hooks settings'),
  ('db.query',               'admin',  'ask-db / finance-query skills'),
  ('db.browser',             'admin',  'DB browser — admin-only floor')
ON CONFLICT (capability) DO NOTHING;
GRANT SELECT ON public.bh_capabilities TO bowershub_app;
```
**Decision:** new table (not reusing `bh_skills` — capabilities are endpoint gates, a different noun) but copies `bh_skills.min_role` semantics so the loader/fail-closed logic is reused, not reinvented.

### `0040_features_registry.sql` (R5.1)
```sql
CREATE TABLE IF NOT EXISTS public.bh_features (
    feature_key      text PRIMARY KEY,                 -- 'finance','database'
    label            text NOT NULL,
    nav_routes       jsonb NOT NULL DEFAULT '[]',
    baseline_capability text REFERENCES public.bh_capabilities(capability),
    admin_only_floor boolean NOT NULL DEFAULT false
);
INSERT INTO public.bh_features (feature_key,label,nav_routes,baseline_capability,admin_only_floor) VALUES
  ('finance', 'Finance',  '["/finance"]',  'finance.read', false),
  ('database','Database',  '["/database"]', 'db.browser',   true)
ON CONFLICT DO NOTHING;
GRANT SELECT ON public.bh_features TO bowershub_app;
```

### `0041_user_feature_access.sql` (R5.2/R5.3 — enforced, restrict-only)
```sql
CREATE TABLE IF NOT EXISTS public.bh_user_feature_access (
    user_id     integer NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    feature_key text    NOT NULL REFERENCES public.bh_features(feature_key) ON DELETE CASCADE,
    enabled     boolean NOT NULL,          -- only enabled=false is meaningful (restrict-only)
    set_by      integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, feature_key)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bh_user_feature_access TO bowershub_app;
```
**Decision:** dedicated table, **not** `settings_json` — this is admin-set, security-load-bearing, cross-user data needing an FK + `set_by` stamp; physically separating it from the user's own cosmetic prefs is itself a correctness guard (D8). The resolver treats any `enabled=false` row as a subtraction and **ignores `enabled=true`** (an override can never grant above role/floor — R5.3).

### `0042_finance_attribution.sql` (R4.1/D5/D7)
```sql
ALTER TABLE finance.transactions
  ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;
ALTER TABLE finance.budgets   ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
                              ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;
ALTER TABLE finance.categories ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
                              ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;
```
Cross-schema FK (`finance.* → public.bh_users`) is **new** — no existing `finance.*→public.bh_users` FK exists today. **M5 correction:** the real requirement is that the **writing** role holds a grant on `public.bh_users` for the FK validation on INSERT/UPDATE — `bowershub_app` does (`0003` grants on all `public` tables), so app writes are fine; `finance_reader` SELECTs don't trigger FK validation (a NULL FK column skips it entirely), so reads were never the risk. `n8n_app` sync writes must leave `created_by`/`updated_by` **NULL** (D6) — a NULL FK column needs no grant and skips validation. **Test T-DB-1 (restated):** an app-role INSERT/UPDATE stamping a valid `bh_users.id` succeeds (writer grant present), and an `n8n_app`-style write with NULL attribution succeeds — *not* "does finance_reader still SELECT." Historical + system/sync rows stay NULL by design (R4.1/D6).

**DB-driven config rows added:** the capability/feature seed rows above (config-as-data, NO-HARDCODING). No new `bh_slash_commands`/skill rows.

## API / Interfaces

**Enumerated endpoint → capability map (R1.4 — the auditable artifact; "~16" made concrete):**

| Endpoint | File:line | Capability | min_role |
|---|---|---|---|
| POST `/transactions/{id}/categorize` | finance_review.py:253 | finance.write | member |
| POST `/transactions/bulk-categorize` | finance_review.py:291 | finance.write | member |
| POST `/merchants/{key}/apply-category` | finance_review.py:329 | finance.write | member |
| POST `/user-rules`, DELETE `/user-rules/{id}` | finance_review.py:379,408 | finance.write | member |
| POST `/transactions/{id}/split`, `/unsplit` | finance_review.py:431,448 | finance.write | member |
| PUT `/budgets` | finance_budgets.py:61 | finance.write | member |
| PUT `/retirement/inputs` | retirement.py:68 | finance.write | member |
| POST `/insights/{id}/dismiss`,`/action`,`/reopen`,`/dismiss-all` | finance_insights.py:61-83 | finance.insight.action | member **(D2 fix — was admin)** |
| POST `/transactions/link`,`/unlink`, `/accounts/{id}/reconcile` | finance_accounting.py:135,149,158 | finance.write | member |
| PUT `/accounts/{id}/type`, delete account | finance_accounting.py:170 | finance.delete | admin |
| POST `/rules/parse` (proposes only, no write) | finance_qa.py:122 | finance.read | viewer |
| POST `/finance/qa` (reads via ask_db sandbox, no write) | finance_qa.py:75 | finance.read | viewer |
| `/retirement/project`, `/scenarios/compare` (read-only POSTs) | retirement.py:78,92 | finance.read | viewer |
| All finance GET reads + the read-only POSTs above | various | finance.read | viewer *(wrapped so a finance-disabled user is also 403'd on reads — R5.2 truthfulness; "read" includes POSTs that only compute/read, e.g. `/qa`, `/rules/parse`)* |

> **Line numbers rot (m1):** this table is the human-readable artifact; the *authoritative* guarantee is the **route-audit test** (Risks), which introspects the live route table — so a moved or newly-added endpoint is caught even if these line numbers drift.
| `ask-db` / `finance-query` skills | skill gate | db.query | admin |
| DB browser **writes** (DDL/CRUD) | db_browser.py | db.browser | admin (already `require_admin`) |
| **⚠ DB browser READS/EXPORT** (`/schemas`:79, `/rows`:420, `/rows/{id}`:334, `/export-csv`:617, columns/pk/lookup/field-hints/views) | db_browser.py | db.browser | **admin** — **currently UNGATED (`get_current_user` only) — PRE-EXISTING HOLE: a member/viewer can export `public.bh_users` password hashes. Must be admin-gated in Phase 1 (B1).** |
| SimpleFIN/n8n sync, nightly jobs | simplefin_sync.py:136, categorizer | — | **out of model (D6)** — no session, NULL attribution |

> **B1 (critic, BLOCKER — fixed here):** the DB-browser *reads/exports* are not admin-only today. Every DB-browser route (reads included, not just mutations) must require `db.browser` (admin). The route-audit (below) is widened to `/api/db-browser` and to **reads**, not just mutating verbs, specifically because the dangerous surface here is a `GET` export.

**New endpoints:**
- `GET /api/me/features` (`get_current_user`) → effective-access payload (R5.5).
- `PUT /api/me/settings/nav` (`get_current_user`) → cosmetic self-hide into `settings_json.hidden_nav`; **never 403s on access**; validated to list only permitted features (R5.4).
- `GET/PATCH /api/admin/capabilities[/{cap}]` (`require_capability("settings.write")`) → retune a gate; `authz.reload()` (R1.3).
- `GET /api/admin/features` (`settings.write`) → registry (R5.1).
- `GET/PUT /api/admin/users/{id}/features[/{key}]` (`users.manage`) → per-user override; **PUT rejects granting a floored feature to a non-admin (400)** (R5.3).
- `PATCH /api/admin/users/{id}` (`users.manage`) → role/active edit + last-admin invariant (R2.1a) + role-value validation.
- `POST /api/auth/users/{id}/reset-link`, `POST /api/auth/invites/{id}/revoke` (`users.manage`) → R2.4/R2.2. **Placed in `routers/auth.py`** with the existing invite/reset machinery (M4), not `admin.py`.

**Auth/provisioning changes:** `register` (`auth.py:102`) seeds the new user as `member` of the designated default workspace, transactionally (R2.5; finance is global, not workspace-gated). Password policy at set-password/reset: min length **10** + reject a small in-code common-password list (R2.3), applied at **both** the register/set-password path (the `len < 8` check in the `register` handler, ~`auth.py:115`) **and** the reset path (`auth.py:259`) — m3. First-admin `display_name` from `Config.ADMIN_DISPLAY_NAME` env, fallback to email local-part (R2.6). Finance write request models get Pydantic `extra="forbid"` and carry no `*_by` field (anti-spoof, R4.1).

## Technology Choices

- **Postgres tables + parameterized asyncpg + in-process dict cache with `reload()`** — identical to every existing DB-driven config (`bh_skills`, `bh_model_rates`, `model_catalog`). No Redis, no new dependency.
- **FastAPI `Depends` factories** for gates — native, no decorator metaprogramming.
- **No policy engine / ABAC / `role_permissions` join** — explicitly rejected by D4; the rank ladder buys total-ordering simplicity, which is correct for a household and the stated trade-off.
- **Floor = `bh_features.admin_only_floor` (data) enforced unconditionally in `authz.resolve` + the DB-browser router *also* keeps a direct `require_admin`.** This hybrid resolves the ideal-vs-NO-HARDCODING tension: the flag is data, but it can only ever *restrict*, and the most dangerous surface (full-DDL DB browser) has a second independent code gate so no DB row can lift it. **⚠ Owner-confirm gate item:** this keeps the DB browser admin-only and *unable* to be granted to a non-admin (per D8/R5.3). Confirm you don't want admins to be able to grant DB access to a trusted non-admin.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Fail-OPEN on unknown/typo'd capability** (the `:97` bug class) | Unknown capability → `DENY` sentinel (rank above admin); **boot-time self-check** enumerates every `require_capability("…")` literal and fails startup if any lacks a `bh_capabilities` row, **and validates every `bh_features.baseline_capability` resolves to a real capability** (catches a typo'd seed the 0040 FK wouldn't — m4) (R1.1). |
| **Ladder drift** (two copies again) | One `ROLE_RANK` in `authz.py`; `skill_executor` imports it; test asserts a single definition. |
| **An endpoint left ungated** during the loosening | **Mechanical route-audit test**: introspect the FastAPI route table; every mutating route under `/api/finance|/api/retirement|/api/admin` **and every route (read or write) under `/api/db-browser`** must have a `require_capability`/`require_role` dep — bare `get_current_user` fails CI ("zero ungated" metric made executable). The db-browser inclusion + read coverage is mandatory (B1: the hole there is a `GET` export). |
| **DB-browser read/export exfiltrates secrets** (B1, pre-existing) | All db-browser routes (reads incl. `/export-csv`) require `db.browser` (admin); fixed in **Phase 1** *before* any non-admin account exists. Test T-DBBROWSER-1: member/viewer `GET /api/db-browser/public/bh_users/export-csv` → 403. |
| **JWT role trusted for perf** → stale-role escalation | Live `bh_users` read preserved; test demotes mid-session and asserts next request 403 despite valid JWT (R1.6). Comment marks payload role informational-only. |
| **WS stale role** | Per-message live re-fetch preserved + tested (R1.7); no authz reads the connect-time snapshot. |
| **IDOR on `bh_messages`** (scoped only by `conversation_id`) | **Do not** denormalize `user_id` onto messages (single source of truth); every message access joins through `conversation_id` and re-runs the conversation-ownership check. **B2 fix (see below):** that check must be **owner-or-admin only**. Two-account ID-swap test (T-IDOR-2). |
| **Conversation privacy leak via workspace membership** (B2, critic BLOCKER) | `_check_conversation_access` (`conversations.py:29-39`) today grants access to the owner, an admin, **OR any member of the conversation's workspace** — so in a shared household workspace user B can read user A's private conversation/messages by iterating `conversation_id`, violating **D3 / R-privacy**. Fix: **remove the workspace-member branch** — access = `owner OR admin` only. Audit every conversation/message route to use the tightened check. T-IDOR-1/2 must be written to **fail against the current leaky helper** (i.e. assert a same-workspace non-owner is denied), so they prove the tightening, not pass vacuously. |
| **Attribution spoofing** | `*_by` set only in the service layer from `user["id"]`; request models `extra="forbid"`, no `*_by` field; test sends `updated_by` in body and asserts ignored. |
| **Zero-admin lockout** (catastrophic, irreversible) | Transactional read-after-write in `update_user`: count active admins after the change, **roll back + 409** if 0; covers self/other demote+deactivate; concurrent-demotion race test (R2.1a). |
| **DB-browser floor lifted by override** | Floor applied last + unconditionally in resolver; PUT rejects granting floored feature to non-admin; DB-browser router also keeps direct `require_admin`. Test T-FLOOR-1. |
| **Cosmetic mistaken for security** | No server access check ever reads `settings_json.hidden_nav`; test T-COSMETIC-1 asserts self-hidden Finance still 200 on direct GET. |
| **Cross-user cache leak** | Capability cache is user-independent (keyed by capability); per-user feature cache keyed by `user_id` (or no cache); grep audit of module-level dicts/`lru_cache`/singletons for missing `user_id` keys (`ws_manager.connections` and `_active_tasks` already user-keyed — verified). |
| **Bad gate change** | Policy is DB rows → **panic-revert** = `UPDATE bh_capabilities SET min_role='admin' …` + `authz.reload()` (≤60s/instant), no redeploy. Migrations additive/nullable → no data rollback. |
| **Cross-schema FK breaks `finance_reader` reads** | RI runs as constraint owner; test T-DB-1 verifies `SET ROLE finance_reader` SELECTs over `finance.transactions` still work post-migration. |

## Rollout Order (no ungated window — grafted from risk-first)

Each phase is independently deployable, reversible, and gated by the two-account test matrix passing in CI before the next.

0. **Ladder + resolver + migrations, enforcement-inert.** Ship `authz.py`, `0039–0042`, fix `skill_executor:97`. All finance writes **still `require_admin`**; caps exist but no endpoint depends on them. *Net behavior change: zero.*
1. **IDOR closure + DB-browser read lockdown + attribution.** Pure tightenings (can only reduce access) — safe to ship while still single-user; removes the holes **before** a second real account exists. Includes: gate all `/api/db-browser` routes (reads + export) behind `db.browser`/admin (B1); tighten `_check_conversation_access` to owner-or-admin, dropping the workspace-member branch (B2/D3); add `created_by`/`updated_by` stamping.
2. **Wire `require_capability` on finance endpoints, caps still seeded `admin`.** Behavior identical (only admins pass); run the route-audit + two-account matrix with a *test* member. Proves the new path is wired **before** it grants anyone new access.
3. **Relax cap rows to `member` (the actual policy change) via DB edit** — instantly reversible. Provision the spouse's `member`/`viewer` account **after** this.
4. **Per-user feature access + cosmetic self-hide + frontend role hooks.** UI last (least security-critical; server already enforces).

## Test Strategy

- **Pure/property (`backend/tests/properties/`, no DB):** ladder ordering (`viewer<member<admin`); unknown/None role denies all; unknown capability → `DENY` denies all (symmetric fail-closed); single-ladder-definition assertion; fallback-dict == seed.
- **DB-backed (throwaway pgvector pg16, per project pattern):** capability resolve (member passes `finance.write`, viewer 403); admin-floor `database` denied to member even with an enabling override attempted; `authz.reload()` makes a retune take effect with no restart (R1.3 end-to-end); T-DB-1 FK-vs-`finance_reader`.
- **Two-account matrix (the headline metric), accounts `admin_a`/`member_b`/`viewer_c` (+`admin_d`):** T-WRITE-1 member can do all everyday writes incl. insight dismiss/action; T-WRITE-2 viewer 403 on all; T-GOV-1 member+viewer 403 on users.manage/db-browser/ask-db/capability-edit; T-AUDIT-1 mechanical zero-ungated; T-DEMOTE-1 demoted member 403 next request despite JWT; T-WS-1 viewer/demoted over open socket denied next message; T-ADMIN-1 last-admin 409 + concurrent race; T-ATTR-1 stamps `updated_by`, ignores body spoof, NULL renders "Bank sync"; T-FEATURE-1 admin-disable Finance → nav gone + `/api/finance/*` 403, re-enable restores; T-FLOOR-1 override can't grant database to member; T-COSMETIC-1 self-hidden Finance still 200 direct; T-NOHARDCODE-1 cap retune via API grants access w/o restart; **T-DBBROWSER-1** member/viewer `GET /api/db-browser/public/bh_users/export-csv` → 403 (B1); **T-IDOR-1/2** a same-workspace non-owner (`member_b`) is **denied** another user's conversation and its messages-by-`conversation_id` — written to FAIL against today's workspace-member branch so it proves the B2 tightening (D3); T-IDOR-3 settings, invites.
- **CI gate:** T-AUDIT-1 + the two-account matrix run on every PR; red blocks merge — the success metrics become enforced, not aspirational.
- **Frontend (vitest):** `useHasRole` thresholds; nav computes from `/me/features ∩ settings_json`, never role alone; self-hidden feature still routable.
