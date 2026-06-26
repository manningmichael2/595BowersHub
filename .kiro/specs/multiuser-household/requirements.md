# Multi-User Household — Requirements

## Overview

Turn 595BowersHub from a single-owner app into one a **trusted household** (2–5 family members) can share. Finance and other personal data stay **shared household-wide** (one global dataset — no per-user finance silos); members are **provisioned manually by an admin** (no public self-signup). Most of the substrate already exists (invite-only registration, `bh_users`/`bh_workspace_users` with `admin/member/viewer`, an admin Users console, a DB-driven `min_role` gate). This spec **finishes, reconciles, and exposes** that model: a real role hierarchy, a household-appropriate finance write policy, role-aware UI, per-user feature visibility (admin-enforced access + self-service nav decluttering), lightweight shared-data attribution, and the security checks a single→multi-user transition demands.

**Why now:** the foundation is stable and the finance product is mature; the owner wants family members (e.g. a spouse) to co-use it. The dangerous part is that going multi-user *without* the role work means `member`/`viewer` accounts silently inherit near-admin write access — so this must be done deliberately, not incidentally.

## Decisions baked in (confirm at this gate; each is overridable)

- **D1 — Role tiers:** three global roles, totally ordered: `viewer < member < admin`. No per-resource/per-account ACLs (shared dataset by design).
- **D2 — Finance write policy:** `member` gets **everyday finance writes** (categorize, split, add/edit transactions, edit budgets, create user-rules, edit retirement inputs, dismiss/action insights). `admin` keeps **structural/destructive + governance** (delete accounts, manage users, platform/theme/skill/model settings, `ask-db`/`finance-query`, DB browser, hooks). `viewer` = read-only everywhere. The authoritative per-endpoint capability mapping is produced as an enumerated table in the design phase (R1.4); D2 is the policy intent it must satisfy.
- **D6 — System/automated writes are out of the role model:** background writers (SimpleFIN/n8n sync, nightly categorizer/insight jobs) are not subject to D2 and are **NULL-attributed by design** (not a logged-in user). The UI renders NULL attribution as "Bank sync"/"Automatic", never blank or "undefined".
- **D7 — Users are deactivate-only (no hard delete)** in this spec, which keeps attribution FKs stable; if deletion is ever added, attribution FKs are `ON DELETE SET NULL`.
- **D8 — Two distinct visibility layers (do not conflate):** (a) **admin per-user feature access** is an *enforced* control (nav hidden **and** API/skills 403); (b) **user profile show/hide** is *cosmetic only* (declutters one's own nav, never changes real access). Toggleable features are a **DB-driven registry** (`finance`, `database`, … as rows). The admin toggle can only **restrict** below the role baseline, never grant above it — in particular the **DB browser keeps its admin-only floor** (R1.5; C4 allowlist declined), so it can't be granted to a non-admin. *(Confirm this floor at the gate.)*
- **D3 — Conversations stay private-per-user** (current behavior — each user sees only their own chats, even in a shared workspace). Shared household chat history is an explicit **non-goal** here (deferrable later).
- **D4 — Permission storage:** generalize the existing `min_role` rank ladder into a small **DB-driven capability→min_role table**. No `role_permissions` join tables, no policy engine (over-engineering for a household).
- **D5 — Attribution:** add `created_by`/`updated_by` to the user-mutated finance tables; historical rows stay NULL (no backfill).

---

## Feature 1: Role hierarchy & permission gating (backend)

### R1.1 — Canonical role ladder (single source of truth), symmetric fail-closed
The system defines exactly one ordered role ranking `viewer(10) < member(20) < admin(100)`, used by **both** the auth middleware and `skill_executor`, replacing the current `ROLE_RANK = {"member":0,"admin":100}` that omits `viewer` (`services/skill_executor.py:21`). Gating must fail closed in **both** directions, fixing the current mismatched-default logic (`ROLE_RANK.get(role,0) >= ROLE_RANK.get(min_role,999)`, `skill_executor.py:97`): an **unknown/absent caller role → denied** (treated as below the lowest tier), AND an **unknown/missing/typo'd required capability or min_role key → denied, never allowed**. The latter is what stops a DB-driven capability gate (R1.3) from failing *open* on a misspelled capability name. This also fixes the latent bug where a `viewer` ranks equal to a `member`.

### R1.2 — `require_role(min_role)` dependency
The system provides a FastAPI dependency `require_role(min_role)` (and/or `require_min_role`) in `middleware/auth.py` alongside the existing `require_admin`, returning 403 when the caller's rank is below the threshold. `require_admin` is preserved (becomes `require_role("admin")` semantically) so existing call sites keep working.

### R1.3 — DB-driven capability → min_role registry (with cache invalidation)
Protected capabilities (e.g. `finance.write`, `finance.delete`, `users.manage`, `settings.write`, `db.query`) map to a required `min_role` in a **Postgres table** (mirroring `bh_skills.min_role`, migration `0028`), loaded via a parameterized loader and editable by an admin — adding/retuning a gate is a **DB row, not a code constant** (NO-HARDCODING). Code-level defaults exist only as a missing-row fallback (and per R1.1, a request for a capability with no row and no default fails **closed**). If the capability map is cached in-process, an admin write to the table **invalidates/reloads the cache** (following the existing `_invalidate_resolver` pattern, `admin.py:38`) so a retune takes effect without a restart; any TTL fallback has a stated bound (≤60s).

### R1.4 — Finance endpoints honor the write policy (D2) — enumerated mapping
The design phase produces an **explicit enumerated table** of every finance write/admin endpoint → its required capability → resulting min_role (covering `finance_accounting.py`, `finance_review.py`, `finance_insights.py`, `retirement.py:69`, `finance_qa.py:130`, plus any bulk/export endpoints), so the "100% coverage, zero gaps" audit (success metric) is checkable against a real list — not "~16". The mapping must resolve the current contradiction where insight dismiss/action is `require_admin` (`finance_insights.py:62-84`) but D2 assigns it to `member` (the spec's intent: dismiss/action = `member`). Background/system writers (SimpleFIN/n8n sync at `simplefin_sync.py:136`, nightly jobs) are **out of scope of this gating** per D6 — they run without a user role and are not re-gated.

### R1.5 — Admin-only governance stays admin-only
User management (`admin.py`), skills/themes/slash-commands/model settings, hooks, the DB browser, and the `ask-db`/`finance-query` skills remain `admin`-gated. A `member` or `viewer` calling any of these receives 403. The DB browser in particular must stay admin-only (the C4 table-allowlist was declined, so members must never reach full-table DDL/CRUD).

### R1.6 — Role is always read live; changes take effect on the next request
Authorization decisions read the caller's role **live from `bh_users`**, never from the JWT payload. This is the existing behavior — `get_current_user` re-loads the user every request (`auth.py:40`), `require_admin` reads the fresh row (`auth.py:49`), and the skill path re-fetches role per call (`skill_executor.py:90-96`) — and the new `require_role`/capability path must preserve it. Consequence (and a real, testable guarantee): a role demotion or deactivation (`is_active=false`) takes effect on the user's **next HTTP request and next WebSocket message**, with no privilege-escalation window. The system must **not** start trusting the JWT's embedded `role` for enforcement (that would silently introduce a stale-role window).

### R1.7 — WebSocket chat path enforces the role ladder
A `viewer` (or a member demoted mid-session) connected over WebSocket cannot invoke a `member`/`admin`-gated skill: skill gating re-fetches role live per message (`handlers.py` → `skill_executor`), so a demotion takes effect on the **next message** without requiring a reconnect. This is an explicit requirement with its own AC, not an incidental property.

---

## Feature 2: User provisioning & management

### R2.1 — Admin can manage existing users (wire the existing PATCH)
The admin Users console lets an admin **change a user's role and activate/deactivate** them via the existing-but-unwired `PATCH /api/admin/users/{id}` (`admin.py:60`). The current `UsersSection.tsx` is list + invite only; this adds the edit affordances. Users are **deactivate-only** (no hard delete) per D7.

### R2.1a — Last-admin invariant (any path, transactional)
The system maintains **≥1 active admin at all times**. Any operation that would transition the household to zero active admins — demoting *any* admin, deactivating *any* admin, or self-demotion — is rejected. The check is performed **transactionally** (read-and-write in one transaction) so two concurrent admin changes cannot race past it. This is broader than a self-lockout guard.

### R2.2 — Invite-token provisioning verified & hardened
The existing admin-only invite flow (`POST /api/auth/invite` → single-use, expiring `bh_invite_links` → `POST /register` requires a valid token) is the sole provisioning path (no public signup). The system verifies the token is cryptographically random (`secrets.token_urlsafe`), single-use, and time-boxed, and lets an admin **revoke an unused invite**.

### R2.3 — Strong password at account creation
When a user consumes an invite and sets their password, the system enforces a **concrete, testable** policy server-side: **minimum length 10**, and rejection of a small built-in common-password list (top-K). No composition rules (no forced symbol/case mixing — avoids security-theater for a trusted household). The user chooses their own password; no plaintext secret is ever transmitted by the admin.

### R2.4 — Admin-initiated password reset
An admin can generate a password-reset link for a member who is locked out (reusing the existing `bh_password_reset_tokens` table), so recovery doesn't require manual SQL on `bh_users.password_hash`. Self-service email reset is **out of scope** (trusted household; admin hands the link over a trusted channel).

### R2.5 — New members land usable, not stranded
On registration, the system **seeds the new user as a `member` of at least one shared workspace** so they aren't stuck at "no workspace → empty app" (the workspace-null deadlock, already partially fixed in `stores/workspace.ts`, but provisioning must not depend on that client-side heal). Clarification: **finance access is NOT workspace-gated** — finance data is global/shared and gated only by the app role (D1/R1.4); workspace membership gates the **chat** surface (conversations/skills). The default to seed and the role within it are concrete (member of the designated shared/default workspace). The workspace add/remove-member UI (`workspaces.py:235-260` backend exists) is reachable and functional from the admin/workspace settings surface.

### R2.6 — Seed admin identity is not hardcoded
The first-admin bootstrap (`ensure_admin_exists`, display_name hardcoded `"Michael"`) sources its display name from config/env (or is editable via R2.1 after boot), so a second admin/spouse doesn't see a stranger's hardcoded name. Low priority, but a visible wart once the app is multi-user.

---

## Feature 3: Role-aware frontend

### R3.1 — Role-aware gating hook
The frontend provides a `useRole`/`useHasRole(min)` hook (generalizing the binary `useIsAdmin.ts`) reading `role` from the auth store, so UI affordances can be gated by the same ladder as the backend.

### R3.2 — UI reflects capabilities
Finance write affordances (categorize, split, bulk, edit budget, create rule, dismiss insight, edit retirement) are **hidden or disabled** for `viewer`; admin-only governance UI (Admin console, DB browser, settings sections) stays admin-only. Hiding is **UX only** — every gate is also enforced server-side (R1.4/R1.5); the frontend never carries the authorization by itself.

### R3.3 — Viewer is read-only end-to-end
A `viewer` account can browse finance, dashboards, and insights but cannot mutate anything via UI, API, or skills (including the `ROLE_RANK` skill path from R1.1). A `viewer` attempting a write gets a clear, non-broken read-only experience.

---

## Feature 4: Shared-data attribution

### R4.1 — Who-changed-what on shared finance rows
The user-mutated finance tables (`finance.transactions`, `finance.budgets`, `finance.categories`) gain `created_by`/`updated_by` (FK to `bh_users`, **`ON DELETE SET NULL`** per D7), set **server-side from the session** — never from the request body. Attribution is **NULL by design** for (a) historical rows at migration time and (b) ongoing system/automated writes (SimpleFIN/n8n sync, nightly jobs — D6); only a logged-in user's manual edit stamps `updated_by`. This answers the #1 shared-dataset question ("who recategorized this / changed the budget?") and matches the existing convention on `bh_workspaces`/`bh_entities`/`bh_hooks`.

### R4.2 — Attribution surfaced minimally, NULL-safe
At least one user-facing surface shows attribution where it matters (e.g. an "edited by {name}" hint on a transaction/budget that was **manually** changed). NULL attribution renders gracefully as **"Bank sync"/"Automatic"** (system writes) or simply no hint (historical) — never blank, "undefined", or a broken FK lookup. Full per-field change history / an audit-trail table is **out of scope** for this spec.

---

## Feature 5: Per-user feature visibility & access

### R5.1 — DB-driven toggleable-feature registry
A small **Postgres registry** lists the top-level features that can be shown/hidden (initially `finance` and `database`, extensible by row — NO-HARDCODING), each with a key, display label, the nav route(s) it controls, and the baseline capability/min_role that governs it (linking to R1.3). Adding a new toggleable feature is a DB row, not a code change.

### R5.2 — Admin per-user feature access (ENFORCED)
From the Users console, an admin can **enable/disable a feature for a specific user** (e.g. turn Finance off for one member). This is an **enforced access control, not cosmetic**: a disabled feature is hidden from that user's nav **and** its API endpoints and skills return **403** for that user (server-side). The per-user override is stored durably (e.g. a `bh_user_feature_access` table or `bh_users.settings_json` — design's call) and set only by an admin. Default for a new user = the feature's role baseline (no override row ⇒ role decides).

### R5.3 — Access resolution & precedence (restrict-only)
Effective **access** to a feature = `role/capability baseline (R1.4/R1.5)` **AND** `NOT admin-disabled-for-this-user (R5.2)`. The admin override can only **subtract** access a role would grant; it can never add access a role forbids. The **database feature retains an admin-only floor** — it is never accessible to a non-admin regardless of override (R1.5; C4 declined). All three checks (role, admin-override, floor) are enforced server-side on the feature's endpoints, not just in nav rendering.

### R5.4 — User self-service show/hide (COSMETIC)
A user can hide/show the Finance and Database buttons in their **own** nav from their profile/settings, persisted in `bh_users.settings_json`. This is **cosmetic only**: a self-hidden feature remains fully reachable by direct URL/API for a user who is permitted (no 403), and self-hiding never affects any other user. The profile UI lists **only** features the user is actually permitted to see (per R5.3) — a user cannot "show" a feature an admin disabled or their role forbids.

### R5.5 — Effective nav visibility
A feature's button appears in a user's nav iff `permitted (R5.3)` **AND** `not self-hidden (R5.4)`. The frontend computes this from the user's effective-access list (served by the API) plus their local `settings_json` preference — it never infers permission client-side from role alone (which would drift from the server's R5.3 decision).

## Acceptance Criteria

- [ ] A single canonical role ladder including `viewer` is used by both middleware and `skill_executor`; the old `member:0` map is gone.
- [ ] Fail-closed both ways: an unknown caller role is denied, AND a request gated on an unknown/missing capability key is denied (not allowed).
- [ ] `require_role(min)` exists; a `member` is allowed past member-gates and 403'd on admin-gates; a `viewer` is 403'd on all writes.
- [ ] Capability→min_role lives in a DB table editable by an admin; changing a gate requires no code change AND takes effect without a restart (cache invalidated/reloaded on write, demonstrated end-to-end).
- [ ] An enumerated endpoint→capability→min_role table exists; auditing every finance-write/admin route against it shows zero ungated routes.
- [ ] Two-account test: a `member` can categorize/split/add a transaction, edit a budget, and dismiss/action an insight; a `viewer` cannot; neither can manage users, open the DB browser, or run `ask-db`.
- [ ] Role demotion takes effect on the caller's next HTTP request; a `viewer`/demoted member over an already-open WebSocket cannot invoke a member/admin-gated skill on the next message.
- [ ] Admin can change another user's role and deactivate them from the Users console; the ≥1-active-admin invariant blocks any path to zero admins (self- or other-, transactionally).
- [ ] Admin can revoke an unused invite and generate a reset link for a locked-out member.
- [ ] A newly provisioned member is seeded into a shared workspace, logs in, and reaches a usable app with finance access (no empty-workspace dead end).
- [ ] Frontend hides write/admin affordances by role, and every hidden action is independently 403'd server-side when called directly.
- [ ] Manual finance edits record `updated_by`; a UI surface shows who last changed a manually-edited transaction/budget; system/sync rows show "Bank sync"/"Automatic" and historical rows render without error.
- [ ] An IDOR test confirms one user cannot read/modify another user's private resources — chat conversations, **individual messages by guessing `conversation_id`**, settings, invites — via ID swapping.
- [ ] Toggleable features (`finance`, `database`) live in a DB registry; adding a feature is a row, not a code change.
- [ ] When an admin disables Finance for a member, that member loses the nav entry **and** gets 403 from `/api/finance/*` (enforced, not cosmetic); re-enabling restores both.
- [ ] The admin override cannot grant the DB browser to a non-admin (admin-only floor holds regardless of override).
- [ ] A user can hide the Finance/Database buttons in their own profile; the feature stays reachable by direct URL for that user (cosmetic), and another user's nav is unaffected.
- [ ] The profile show/hide UI lists only features the user is permitted to see; an admin-disabled or role-forbidden feature is not offered as a "show" option.

## Non-Functional Requirements

- **No hardcoding:** role→capability gates are DB-driven (capability→min_role table), read via API; code holds only fallback defaults. No reintroduction of an `ADMIN_ONLY_*` constant.
- **Data safety:** parameterized SQL only; forward-only migrations starting at `0039`, auto-applied on startup, carrying scoped-role grants (per `0021_migration_role.sql` default-privilege convention); attribution columns are additive and nullable (no destructive backfill).
- **Security (the core of this spec):**
  - Authorization enforced **server-side on every mutating/admin endpoint** — frontend gating is never the only check.
  - **Object-level checks** on the enumerated per-user resources — conversations, **individual `bh_messages` (scoped only by `conversation_id` today — a classic IDOR vector)**, user settings (`bh_users.settings_json`), and invites: the row must belong to the caller or the caller must be admin (BOLA/IDOR — OWASP API1:2023). Validated with a two-real-account ID-swap test.
  - **Cache/session-key scoping audit:** any cache, memoization, WebSocket session map, or pre-multi-user singleton keyed without `user_id` must be fixed so data can't leak across users.
  - **Least privilege preserved:** `member`/`viewer` must never reach write-capable DB roles; the `finance_reader` scoped role + `ask-db` sandbox remain admin-gated and unchanged.
  - Attribution/ownership set from the session, never from the request payload.
  - **Avoid security theater:** no MFA mandate, no per-field encryption, no WAF/anomaly detection — out of scope for a trusted ≤5-user Tailscale-only app.
- **Performance / cost:** no new interactive LLM calls; role checks are O(1) rank comparisons + a cached capability map.

## Constraints & Assumptions

- Runs on the Minisforum server, **Tailscale-only** (no public internet exposure) — reinforces the no-public-signup decision.
- Postgres is the `pgvector/pgvector:pg16` instance in the Portainer `finance`/`ai-services` stack; schema is rebuildable from `0001_baseline.sql` (C2 resolved).
- Household is trusted and small (≤5). Threat model is **accidental over-permission and role/function-level mistakes**, not adversarial insiders.
- DB-engine roles (`finance_reader`, `bowershub_app`, `bowershub_migrator`) are a **separate** least-privilege layer from app `bh_users.role` and are not modified by this spec except to keep their grants intact on new objects.

## Dependencies

- None blocking. Builds on shipped foundation: invite/register flow (`routers/auth.py`), admin user API (`routers/admin.py`), workspace membership (`routers/workspaces.py`), DB-driven `min_role` precedent (`0028`), scoped DB roles (`0002`/`0003`/`0021`).
- Migration numbering continues at `0039`.

## Success Metrics

- **Authorization coverage:** 100% of finance-write and admin endpoints have a server-side role/capability gate (audited list, zero gaps).
- **Viewer containment:** 0 successful writes by a `viewer` across UI, API, and skills in the two-account test matrix.
- **IDOR:** 0 cross-user reads/writes of private resources in the two-account ID-swap test.
- **No-hardcoding:** adding or retuning a permission gate — or adding a toggleable feature (R5.1) — requires only a DB row change (demonstrated once end-to-end).
- **Enforced visibility:** an admin-disabled feature yields 0 successful API/skill calls by the affected user (not merely a hidden button); a self-hidden feature yields a working direct-URL access for the permitted user (confirming cosmetic-only).
- **Usability:** a freshly provisioned member reaches a working finance view in one session with no manual DB intervention.
