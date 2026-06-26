# Multi-User Household — Tasks

> Each task traces to one or more requirements in `requirements.md`. Work top-to-bottom; respect dependencies. Task order follows the design's **safe rollout** (`design.md` §Rollout): ship gates enforcement-inert → close pre-existing holes → wire capabilities (still admin-seeded) → relax + expose. **Do not provision any non-admin (member/viewer) account until Task 3's route-audit + two-account matrix are green.**
>
> DB-backed tests run against a throwaway `pgvector/pgvector:pg16` on host port 5455 (`DB_HOST=127.0.0.1 DB_PORT=5455 DB_USER=michael DB_PASSWORD=test`), per project convention. Migration numbers per `design.md`.

## Task 1: Authz core — canonical role ladder, resolver, dependencies (enforcement-inert)
- **Effort:** L
- **Dependencies:** none
- **Requirements:** R1.1, R1.2, R1.3, R1.6
- [x] New `backend/services/authz.py`: canonical `ROLE_RANK={"viewer":10,"member":20,"admin":100}`, `rank(role)` (unknown/None → −1), `DENY=10_000` sentinel; `CapabilityCache` loading `bh_capabilities` with `reload()`; `min_role_rank(cap)` → configured rank, else `_DEFAULT_CAPS` fallback, else `DENY` (unknown capability denies — symmetric fail-closed, R1.1); `resolve(user, cap)` (rank check only for now — feature-override + floor join added in Task 9); `effective_access(user)` stub. Imports only `database.get_pool`/asyncpg (no import of `middleware.auth`/`skill_executor` — acyclic).
- [x] `middleware/auth.py`: add `require_role(min_role)` (unknown `min_role` key → 403) and `require_capability(cap)` dependency factories; redefine `require_admin = require_role("admin")` (existing call sites unchanged). Keep the live `bh_users` read; add a comment at the JWT-decode site that payload `role` is informational-only, never authorized on (R1.6).
- [x] `services/skill_executor.py`: delete local `ROLE_RANK` (`:21`); import from `authz`; `_user_meets_min_role` (`:84-97`) uses `authz.rank` (fixes the `viewer==member` bug and the 0/999 mismatch). Update `tests/test_skill_min_role.py:11,62` to the canonical values.
- [x] Boot-time self-check (startup): enumerate every `require_capability("…")` literal in code and fail startup if any lacks a `bh_capabilities` row.
- [x] **No endpoint is re-gated in this task** — finance writes still `require_admin`. Net behavior change: zero.
- [x] **Migration:** `backend/migrations/0039_capabilities.sql` — `bh_capabilities(capability PK, min_role CHECK in (viewer,member,admin), description, updated_at, updated_by FK→bh_users ON DELETE SET NULL)` + seed the enumerated capabilities (`finance.read`/`.write`/`.insight.action`/`.delete`, `users.manage`, `settings.write`, `db.query`, `db.browser`) + `GRANT SELECT … TO bowershub_app`.
- [x] **Tests:** pure/property — ladder ordering (`viewer<member<admin`), unknown/None role denies all, unknown capability → `DENY` denies all, single-`ROLE_RANK`-definition assertion, `_DEFAULT_CAPS == seed`; DB-backed — `authz.reload()` reflects a row change without restart.

## Task 2: Close pre-existing access holes — DB-browser lockdown (B1), conversation privacy (B2), object-level IDOR
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R1.5
- [x] **B1 (DONE — hotfix already applied):** every `routers/db_browser.py` endpoint (reads + `/export-csv` included) now `require_admin`; import + module docstring updated. DB browser is admin-only end-to-end.
- [ ] **B2:** tighten `routers/conversations.py:_check_conversation_access` to **owner-or-admin only** — remove the "any workspace member" branch (`:33-36`) so conversations are private-per-user (D3). Audit every conversation/message route to use the tightened check.
- [ ] Object-level checks: ensure no `bh_messages` route fetches by `message_id` without the `conversation_id`-ownership join; verify per-user `settings_json` and invite reads are owner-or-admin scoped.
- [ ] **Tests:** `T-DBBROWSER-1` (a member/viewer `GET /api/db/public/bh_users/export-csv` → 403 — note prefix is `/api/db`, not `/api/db-browser`); `T-IDOR-1/2` written to **fail against today's leaky helper** — a same-workspace non-owner is denied another user's conversation + its messages-by-`conversation_id`; `T-IDOR-3` settings + invites.

## Task 3: Re-gate finance endpoints + reads via capabilities; mechanical route-audit
- **Effort:** L
- **Dependencies:** Task 1, Task 2
- **Requirements:** R1.4, R3.3
- [ ] Swap `Depends(require_admin)` → `Depends(require_capability(...))` on every finance write per the enumerated table in `design.md` §API (categorize/bulk/split/unsplit/user-rules/budgets/retirement-inputs → `finance.write`; insight dismiss/action/reopen/dismiss-all → `finance.insight.action` [resolves the D2 vs `require_admin` contradiction]; account delete / account-type → `finance.delete`). Handler bodies unchanged (dependency still yields `user: dict`).
- [ ] Wrap finance **reads** and read-only POSTs (`/finance/qa`, `/rules/parse`, retirement `/project`,`/scenarios/compare`, all finance GETs) in `require_capability("finance.read")` so an admin feature-disable (Task 9) also blocks reads (R5.2 truthfulness).
- [ ] Viewer is read-only end-to-end across these endpoints (R3.3).
- [ ] **Tests:** **T-AUDIT-1** mechanical route-audit — introspect the FastAPI route table; every mutating route under `/api/finance|/api/retirement|/api/admin` **and every route (read+write) under `/api/db`** must carry a `require_capability`/`require_role` dependency (bare `get_current_user` fails). Two-account matrix at this stage: caps still admin-seeded ⇒ only admin passes (behavior identical to pre-change), proving the wiring grants nothing new before relaxation.

## Task 4: WebSocket per-message live-user enforcement
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.6, R1.7
- [ ] `websocket/handlers.py`: the message loop re-loads the live user (`role` + `is_active`) per message before dispatch, rather than reusing the connect-time `user` dict (`:74,:111`); a demoted/deactivated user is rejected on the **next message** without reconnect. Ensure no authz decision reads `RoutingContext.user_role` (`:260` — prompt-flavor only).
- [ ] **Tests:** `T-DEMOTE-1` (HTTP — demoted user 403 on next request despite unexpired JWT); `T-WS-1` (viewer/demoted member over an open socket denied a member-gated skill on the next message); deactivation-over-open-socket rejected next message.

## Task 5: Finance attribution columns + server-side stamping
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R4.1, R4.2
- [ ] **Migration:** `backend/migrations/0042_finance_attribution.sql` — add `created_by`/`updated_by` (FK→`public.bh_users` `ON DELETE SET NULL`) to `finance.transactions`, `finance.budgets`, `finance.categories`; additive/nullable, no backfill; `IF NOT EXISTS`; grant block per `0021`. (No cross-deps → its number-vs-author-order is safe.)
- [ ] Stamp `created_by`/`updated_by = user["id"]` in the service-layer finance write paths only; finance write request models get Pydantic `extra="forbid"` and carry no `*_by` field (anti-spoof). System/sync writers (`simplefin_sync.py`, nightly jobs) leave attribution NULL (D6).
- [ ] Frontend: surface "edited by {name}" on a manually-changed transaction/budget; render NULL as "Bank sync"/"Automatic" (system) or no hint (historical) — never blank/"undefined"/broken FK.
- [ ] **Tests:** `T-ATTR-1` (manual edit stamps `updated_by`; `updated_by` in request body ignored; NULL renders "Bank sync"; historical NULL renders without error); `T-DB-1` (app-role INSERT/UPDATE with a valid `bh_users.id` succeeds — writer grant present; an `n8n_app`-style NULL-attribution write succeeds).

## Task 6: User management core — role edit + last-admin invariant
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R2.1
- [ ] Wire the existing `PATCH /api/admin/users/{id}` (`admin.py:60`) into `frontend/src/pages/admin/UsersSection.tsx`: role `<select>` + activate/deactivate. Users are deactivate-only (no hard delete, D7).
- [ ] **Last-admin invariant (R2.1a):** in `update_user`, run the UPDATE + `SELECT count(*) … WHERE role='admin' AND is_active` inside one `conn.transaction()` with `FOR UPDATE` (or a txn-scoped advisory lock) so concurrent demotions serialize; roll back + **409** if the post-change count would be 0 (covers self/other demote+deactivate). Validate `role ∈ {viewer,member,admin}` before the UPDATE (CHECK is the backstop); confirm the dynamic-SQL builder still interpolates only field names, never values.
- [ ] **Tests:** `T-ADMIN-1` — demote/deactivate last admin (self + other) → 409; two concurrent last-admin demotions → exactly one succeeds; frontend role-edit/deactivate flow.

## Task 7: Provisioning hardening — invites, reset, password policy, member seeding
- **Effort:** M
- **Dependencies:** Task 1, Task 6
- **Requirements:** R2.2, R2.3, R2.4, R2.5, R2.6
- [ ] Invite-revoke + admin reset-link in `routers/auth.py` (where `bh_invite_links`/`bh_password_reset_tokens` machinery lives), gated `require_capability("users.manage")`: `POST /api/auth/invites/{id}/revoke` (R2.2), `POST /api/auth/users/{id}/reset-link` (R2.4). Verify invite tokens are `secrets.token_urlsafe`, single-use, time-boxed (R2.2).
- [ ] Password policy (R2.3): min length **10** + reject a small in-code common-password list, applied at **both** the register/set-password path (the `len<8` check in `register`, ~`auth.py:115`) and the reset path (`auth.py:259`).
- [ ] `register` seeds the new user as `member` of the designated default/shared workspace, transactionally (R2.5; finance is global, not workspace-gated). Verify the workspace add/remove-member UI is reachable.
- [ ] First-admin `display_name` from `Config.ADMIN_DISPLAY_NAME` (fallback: email local-part), replacing the hardcoded `"Michael"` at `services/auth.py:241` (R2.6).
- [ ] **Tests:** invite revoke prevents register; reset-link rotates password; password policy rejects <10 / common; new member lands in a workspace; admin display_name from env.

## Task 8: Capability/feature admin CRUD + feature registry + cache invalidation (end-to-end NO-HARDCODING)
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.3, R5.1
- [ ] **Migration:** `backend/migrations/0040_features_registry.sql` — `bh_features(feature_key PK, label, nav_routes jsonb, baseline_capability FK→bh_capabilities, admin_only_floor bool)` + seed `finance` (floor=false) and `database` (floor=true) + `GRANT SELECT … TO bowershub_app`.
- [ ] Admin endpoints in `admin.py`, gated `require_capability("settings.write")`, each calling `authz.reload()` after a write: `GET/PATCH /api/admin/capabilities[/{cap}]` (retune a gate), `GET /api/admin/features`.
- [ ] Extend the boot self-check to validate every `bh_features.baseline_capability` resolves to a real capability (catches a typo'd seed the FK wouldn't).
- [ ] Admin UI: a capabilities section to view/retune `min_role`.
- [ ] **Tests:** `T-NOHARDCODE-1` — retune `finance.write` admin→member via the API and confirm a member gains access **without a restart** (cache invalidation end-to-end); revert restores 403.

## Task 9: Per-user feature access — enforced, restrict-only (admin show/hide)
- **Effort:** M
- **Dependencies:** Task 8
- **Requirements:** R5.2, R5.3
- [ ] **Migration:** `backend/migrations/0041_user_feature_access.sql` — `bh_user_feature_access(user_id FK ON DELETE CASCADE, feature_key FK ON DELETE CASCADE, enabled bool, set_by FK→bh_users ON DELETE SET NULL, set_at, PK(user_id,feature_key))` + grants.
- [ ] Extend `authz.resolve` to the full precedence (R5.3): `rank ≥ min_role` AND `not feature-disabled-for-user` (any `enabled=false` row subtracts; `enabled=true` is a no-op — restrict-only) AND `not (admin_only_floor AND role<admin)` (floor applied last, unconditionally). Per-user feature cache keyed by `user_id`.
- [ ] Admin endpoints `GET/PUT /api/admin/users/{id}/features[/{key}]` (gated `users.manage`); **PUT rejects granting a floored feature (database) to a non-admin → 400**. UsersSection per-user feature toggles.
- [ ] **Tests:** `T-FEATURE-1` (admin disables Finance for a member → nav entry gone AND `/api/finance/*` 403; re-enable restores both); `T-FLOOR-1` (override cannot grant `database` to a member — still 403).

## Task 10: Role-aware frontend + effective-access API + cosmetic self-hide
- **Effort:** M
- **Dependencies:** Task 9
- **Requirements:** R3.1, R3.2, R5.4, R5.5
- [ ] `GET /api/me/features` returns `authz.effective_access(user)` — `{role, capabilities, features:[{key,label,routes,permitted}]}` (R5.5 source of truth; frontend never infers permission from role).
- [ ] Frontend: `hooks/useHasRole.ts` (NEW; `useIsAdmin` becomes a `useHasRole('admin')` shim) and `hooks/useFeatures.ts` (consumes `/me/features`); `stores/auth.ts` stores + refreshes the payload (R3.1).
- [ ] Nav (`TopNav.tsx`, `BottomTabBar.tsx`, `Sidebar.tsx`): a feature button shows iff `permitted (server) AND not self-hidden`; admin-gate the **Database** tab (and Finance when feature-disabled). Finance write affordances hidden/disabled for viewer (R3.2).
- [ ] Cosmetic self-hide (R5.4): `PUT /api/me/settings/nav` → `settings_json.hidden_nav` (**never 403s on access**; validated to list only permitted features); profile UI lists only features from `/me/features`.
- [ ] **Tests:** `T-COSMETIC-1` (self-hidden Finance still 200 on direct GET — cosmetic-only; another user's nav unaffected); vitest — `useHasRole` thresholds; nav computes from `/me/features ∩ settings_json`, never role alone; self-hidden feature still routable.

## Definition of Done

- [ ] All tasks complete; every requirement R1.1–R5.5 (incl. R2.1a) is satisfied.
- [ ] **No ungated route:** `T-AUDIT-1` green — zero finance/admin/`/api/db` routes on bare `get_current_user`.
- [ ] **Two-account matrix green** (admin/member/viewer + 2nd admin): member everyday finance writes pass; viewer 403 on all writes; neither reaches users.manage/db-browser/ask-db; demotion effective next HTTP request + next WS message; last-admin invariant holds; IDOR (conversations, `bh_messages`, settings, invites) closed; DB-browser export 403 for non-admin; per-user feature disable enforced; database floor un-liftable; cosmetic self-hide non-enforcing.
- [ ] No hardcoded config introduced — capability/feature gates are DB rows (the DB-browser admin floor is the one deliberate code invariant, owner-confirmed); retuning a gate or adding a feature is a row (`T-NOHARDCODE-1`).
- [ ] Migrations `0039`–`0042` apply on a fresh DB; grants intact; `finance_reader` unaffected.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`).
- [ ] **Only after the audit + matrix are green:** provision real family member/viewer accounts (operational step, not code).
- [ ] `context-log.md` updated with a dated entry.
