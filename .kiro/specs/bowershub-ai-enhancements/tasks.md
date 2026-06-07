# Implementation Plan: BowersHub AI Enhancements

## Overview

This implementation plan extends the existing BowersHub AI platform (`bowershub-ai/`) with admin branding, per-user appearance preferences, workspace prompt + pinned-context tooling, and four creative day-to-day features (morning card, quick capture, voice mode, scheduled prompts). Tasks are ordered to minimize rework: database migrations first, then backend pure-logic services (each with property-based tests close to the implementation), then backend routers, then frontend foundation (CSS custom-property wiring, stores), then feature components, and finally wiring + smoke tests.

The backend is Python/FastAPI; the frontend is React + TypeScript + Tailwind. Tests use `hypothesis` (Python) and `fast-check` (TypeScript). All paths are relative to `/home/michael/KiroProject/bowershub-ai/`.

## Tasks

### A. Database migrations

- [x] 1. Database migrations for themes, platform settings, and `settings_json` documentation
  - [x] 1.1 Write migration `009_themes_and_branding.sql`
    - Create `public.bh_themes` table (id, name, slug, is_preset, owner_id FK→bh_users, tokens_json JSONB, created_at, updated_at, UNIQUE(slug, owner_id)) with indexes on owner_id and is_preset
    - Create `public.bh_platform_settings` (key TEXT PK, value_json JSONB, updated_by FK→bh_users, updated_at)
    - Seed 4 preset rows in `bh_themes` with `is_preset=true`, `owner_id=NULL`: Dark Navy (current default), Light Stone, Forest, Mono
    - Seed 4 rows in `bh_platform_settings`: `default_theme_id` (points at Dark Navy id), `app_icon_version` (current epoch), `app_icon_active_filename` (`"icon-set-default"`), `app_icon_previous_filename` (`null`)
    - File: `backend/migrations/009_themes_and_branding.sql`
    - _Requirements: R1.1, R1.5, R2.4, R2.5, R3.7_

  - [x] 1.2 Write migration `010_settings_json_keys.sql`
    - Comment-only migration documenting new optional keys in `bh_users.settings_json`: `theme_id`, `text_size`, `morning_card_workspace_id`, `morning_card_disabled`, `voice` object
    - Body is `SELECT 1;` plus a SQL comment block listing every key and its expected shape
    - File: `backend/migrations/010_settings_json_keys.sql`
    - _Requirements: R3.2, R4.3, R8.9, R10.9_

  - [x] 1.3 Migration smoke test
    - Apply both migrations against a fresh test DB; assert 4 preset theme rows are present, 4 platform settings rows are present, and `bh_migrations` records both files
    - File: `backend/tests/test_migrations_009_010.py`
    - _Requirements: R1.1, R3.7_

### B. Backend pure-logic services

- [x] 2. Theme validator (pure functions; hex grammar + contrast)
  - [x] 2.1 Implement `theme_validator.py`
    - `is_valid_hex(s: str) -> bool` matches `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`
    - `relative_luminance(hex: str) -> float` per WCAG formula
    - `contrast_ratio(text_hex: str, bg_hex: str) -> float`
    - `contrast_decision(text_hex, bg_hex) -> Literal['ok','warn','block']` with thresholds `< 2.0 → block`, `[2.0, 4.5) → warn`, `>= 4.5 → ok`
    - `validate_tokens(tokens_json: dict) -> list[FieldError]` returning per-field errors for any non-hex token; required keys: background, surface, primary, accent, text, text_muted, border, danger, success
    - File: `backend/services/theme_validator.py`
    - _Requirements: R1.4, R1.6, R1.7, R1.8_

  - [x] 2.2 Property test for hex validator
    - **Property 2: Hex token validator accepts exactly the hex grammar**
    - Use `hypothesis` strategies that include valid hex (with/without `#`, mixed case, 6 and 8 digits) and deliberate near-misses (5/7/9 chars, non-hex chars, leading whitespace, empty string)
    - **Validates: Requirements R1.6**
    - File: `backend/tests/properties/test_theme_validator_hex.py`
    - _Property: P2_

  - [x] 2.3 Property test for contrast decision
    - **Property 3: Contrast threshold decision is monotonic and symmetric**
    - Generate pairs of valid hex; assert decision matches manual ratio computation in `{ok, warn, block}`; assert `decision(a, b) == decision(b, a)`
    - **Validates: Requirements R1.7, R1.8**
    - File: `backend/tests/properties/test_theme_validator_contrast.py`
    - _Property: P3_

- [x] 3. Theme resolver (priority-order resolution)
  - [x] 3.1 Implement `theme_resolver.py`
    - `resolve(user, themes_table_view, platform_default_id) -> Theme` returns the highest-priority theme that exists and is visible to the user
    - Priority order: user override (`settings_json.theme_id`) → platform default (`bh_platform_settings.default_theme_id`) → built-in fallback (`Dark Navy` slug)
    - Stale references (deleted theme, theme owned by another user) fall through to the next entry; never raises
    - Return shape: `{id, name, slug, tokens_json, is_default}`
    - File: `backend/services/theme_resolver.py`
    - _Requirements: R3.5, R3.7, R3.8_

  - [x] 3.2 Property test for theme resolution
    - **Property 1: Theme resolution priority is total and stable**
    - Generate combinations of `(user_override_id, platform_default_id, deleted_id_set, themes_owned_by_other_user_id_set)`; assert the resolver returns the highest-priority theme not in the deleted set and not owned by another user, falling through to the built-in fallback; assert it never raises
    - **Property 13: settings_json.theme_id is always resolvable or absent**
    - **Validates: Requirements R1.3, R1.9, R3.5, R3.7, R3.8, R4.6**
    - File: `backend/tests/properties/test_theme_resolver.py`
    - _Property: P1, P13_

- [x] 4. Text size resolver (trivial pure function)
  - [x] 4.1 Implement `text_size_resolver.py`
    - `resolve(value: Any) -> tuple[str, float]` mapping `'small'→0.875`, `'medium'→1.0`, `'large'→1.125`, `'extra_large'→1.25`; every other input including `None`, ints, and unknown strings returns `('medium', 1.0)`
    - File: `backend/services/text_size_resolver.py`
    - _Requirements: R4.1, R4.6_

  - [x] 4.2 Property test for text size resolver
    - **Property 5: Text size resolver is total and falls back to medium**
    - Generate arbitrary strings, ints, None, dicts; assert exact values for the four known strings and `('medium', 1.0)` for everything else; assert never raises
    - **Validates: Requirements R4.1, R4.6**
    - File: `backend/tests/properties/test_text_size_resolver.py`
    - _Property: P5_

- [x] 5. Briefing summary parser (pure markdown sectioner)
  - [x] 5.1 Implement `briefing_summary.py`
    - `parse_sections(markdown: str) -> list[{key, label, content}]` extracts the five expected sections from the briefing markdown produced by `BriefingService.generate()`: Weather, Yesterday's Spending, Inbox, Today's Schedule, Anything Else
    - Detects sections by `**<Label>:**` heading pattern as emitted by `briefing.py`
    - For any expected section that the briefing omitted, returns the section with content `"—"` (R8.7)
    - File: `backend/services/briefing_summary.py`
    - _Requirements: R8.2, R8.7_

  - [x] 5.2 Unit tests for briefing summary parser
    - Cover: full briefing with all sections, briefing missing weather, briefing missing multiple sections, malformed markdown
    - Assert section keys and labels; assert `—` placeholder for missing sections
    - File: `backend/tests/test_briefing_summary.py`
    - _Requirements: R8.2, R8.7_

- [x] 6. Cron expression validator (croniter wrapper)
  - [x] 6.1 Add `validate_cron` helper to `scheduled_prompts.py` (full module created in §C)
    - `validate_cron(expr: str) -> bool` calls `croniter.croniter.is_valid(expr)` and returns its result; never raises
    - This is a tiny utility — defined here so the property test can target it before the rest of the module exists
    - File: `backend/services/scheduled_prompts.py` (helper only at this stage)
    - _Requirements: R11.11_

  - [x] 6.2 Property test for cron validator
    - **Property 10: Cron expression validator agrees with croniter**
    - Generate strings: known valid crons (`* * * * *`, `0 7 * * *`, `*/5 * * * *`), known invalid (`bogus`, ``, `60 24 32 13 8`, `* * * *`); assert `validate_cron(s) == croniter.is_valid(s)`; assert never raises
    - **Validates: Requirements R11.11**
    - File: `backend/tests/properties/test_cron_validator.py`
    - _Property: P10_

### C. Backend stateful services

- [x] 7. Branding store (on-disk icon management)
  - [x] 7.1 Implement `branding_store.py`
    - `validate_icon(mime, width, height, size_bytes) -> tuple[bool, list[FieldError]]` enforcing: `mime == 'image/png'`, `min(w,h) >= 512`, `abs(w - h) / max(w, h) <= 0.01` (square within 1% tolerance), `size_bytes <= 4 * 1024 * 1024`
    - `upload_icon(file_bytes) -> {version, urls}`: validate, generate 192px and maskable-512px (12% inner padding) variants via Pillow, atomically swap into `/files/branding/active/`, archive previous active into `/files/branding/previous/` (after archiving any existing previous into `/files/branding/history/<ts>/`)
    - `revert_to_default()`: invoke existing `scripts/generate_icons.py` in-process, write into `/files/branding/default/`, symlink-swap `active/` to point at it; preserve `previous/` slot
    - `rollback() -> {version}`: swap `active/` ↔ `previous/`; raise `RollbackUnavailable` if `previous/` empty
    - `get_manifest() -> {version, urls, has_rollback}` reads `bh_platform_settings`
    - File: `backend/services/branding_store.py`
    - _Requirements: R2.2, R2.3, R2.4, R2.5, R2.6, R2.7_

  - [x] 7.2 Property test for icon validator
    - **Property 4: Icon upload validator accepts exactly the published rules**
    - Generate `(mime, width, height, size_bytes)` tuples bracketing thresholds (511 vs 512 px, 4MB vs 4MB+1, ratio 1.005 vs 1.015, mime variants); assert `ok` iff all four rules pass; assert per-rule error message present otherwise
    - **Validates: Requirements R2.2, R2.3**
    - File: `backend/tests/properties/test_icon_validator.py`
    - _Property: P4_

  - [x] 7.3 Integration test for upload pipeline
    - Real PNG (1024x1024) → `upload_icon` → assert 192px and maskable-512px files exist under `/files/branding/active/` with correct dimensions; assert `previous/` populated; assert version string changed
    - File: `backend/tests/test_branding_store_integration.py`
    - _Requirements: R2.2, R2.4, R2.7_

- [x] 8. Scheduled prompts service (CRUD facade over bh_hooks)
  - [x] 8.1 Flesh out `scheduled_prompts.py`
    - `list_for_user(user, workspace_id?)`: SELECT from `bh_hooks` WHERE `event_type='schedule'` AND `action_type='call_ai'`, joining workspace access, returning `{id, name, workspace_id, prompt_template, cron_expression, cron_human, delivery_method, is_enabled, last_run, last_status}`. Use `cronstrue` for `cron_human`.
    - `create(user, payload)`: validate cron via `validate_cron`, INSERT row with `event_type='schedule'`, `action_type='call_ai'`, `action_config={prompt, model: 'claude-haiku-4-5-20251001', delivery_method, workspace_id}`
    - `update(user, id, partial)`: PATCH with ownership/access check, re-validate cron if changed
    - `delete(user, id)`, `toggle(user, id, enabled)`
    - `run_now(user, id) -> {run_id, status, response_snippet?}`: build synthetic `RoutingContext`, call `hook_engine._execute_hook(hook, context)` directly, return result synchronously if <30s else 202 (caller decides)
    - `get_log(user, id, limit=10)`: SELECT from `bh_hook_log` for that hook, newest first
    - File: `backend/services/scheduled_prompts.py`
    - _Requirements: R11.1, R11.2, R11.3, R11.4, R11.7, R11.8, R11.9, R11.10, R11.11_

  - [x] 8.2 Unit tests for scheduled_prompts CRUD
    - Cover: create with valid cron, create with invalid cron returns 400-shape error, update toggles `is_enabled`, list filters to user's accessible workspaces, get_log returns rows in reverse-chronological order
    - Use a test DB fixture with seed workspaces and hooks
    - File: `backend/tests/test_scheduled_prompts.py`
    - _Requirements: R11.1, R11.7, R11.10, R11.11_

- [x] 9. Hook engine extension — `call_ai` delivery routing
  - [x] 9.1 Extend `hook_engine._execute_hook` for `action_type='call_ai'`
    - Read `action_config.delivery_method` ∈ `{'pin', 'pushover'}`
    - For `'pin'`: insert a `system` message into `bh_messages` for the workspace's primary conversation with `metadata = {pinned: true, scheduled_prompt_id: hook.id}`
    - For `'pushover'`: build payload via new `pushover_payload(response_text, ws) -> {message, url}` helper that truncates the message to 1000 chars and appends the workspace deep-link `https://595bowershub.tailc4d58a.ts.net/workspace/<ws.id>`; call `notifications.send_pushover()`
    - Mark `context.skip_capture=true` and `context.is_scheduled=true` in the synthetic `RoutingContext` (so `context_capture` does not fire and per-user streaming notifications are suppressed)
    - On AI invocation failure: log to `bh_hook_log` with `success=false` and the error message; do not retry (R11.12)
    - File: `backend/services/hook_engine.py` (extension to existing module)
    - _Requirements: R11.4, R11.5, R11.6, R11.12_

  - [x] 9.2 Property test for pushover payload truncation
    - **Property 12: Pushover delivery truncates to 1000 chars and includes workspace link**
    - Generate arbitrary strings (short, exactly 1000 chars, much longer) and arbitrary workspace ids; assert `len(message) <= 1000` AND `url` is the workspace deep-link
    - **Validates: Requirements R11.6**
    - File: `backend/tests/properties/test_pushover_payload.py`
    - _Property: P12_

  - [x] 9.3 Property test for cron firing exactness
    - **Property 11: Scheduled prompt fires once per matching tick**
    - Under a virtual clock (`freezegun` + APScheduler test mode), for any valid cron `c` and any range `[t0, t1]`, assert `count(hook_engine.fires(hook(c), t0, t1)) == count(croniter(c).get_next_in_range(t0, t1))`; no duplicate fires; no missed fires
    - **Validates: Requirements R11.4**
    - File: `backend/tests/properties/test_cron_firing.py`
    - _Property: P11_

### D. Backend routers

- [x] 10. Themes router (`/api/themes/*`)
  - [x] 10.1 Implement `routers/themes.py`
    - `GET /api/themes` returns all themes visible to the user (presets + admin-published + user-owned), with `is_default` flag
    - `POST /api/themes` validates via `theme_validator`; admin can pass `publish: true` to set `owner_id=NULL`
    - `PATCH /api/themes/{id}` requires `owner_id == user.id` OR admin role; re-runs validator
    - `DELETE /api/themes/{id}`: returns 409 if `is_preset`; cascades clear `bh_users.settings_json.theme_id` for users whose override was the deleted theme; if it was platform default, clear that too — both via SQL UPDATE in the same transaction
    - `POST /api/themes/{id}/set-platform-default` requires admin; rejects user-scoped themes (409)
    - All endpoints emit audit log entries for create/update/delete/set-default
    - File: `backend/routers/themes.py`
    - Register in `backend/main.py`
    - _Requirements: R1.2, R1.3, R1.5, R1.6, R1.8, R1.9, R1.10, R3.4, R3.5_

  - [x] 10.2 RBAC + smoke test for themes endpoints
    - Cover: admin creates published theme, member creates personal theme, member tries to PATCH another member's theme → 403, member tries to publish → 403, admin sets platform default → 200, admin deletes preset → 409, contrast block returns 422
    - File: `backend/tests/test_themes_router.py`
    - _Requirements: R1.5, R1.8, R1.10, R3.5_

- [x] 11. Branding router (`/api/branding/*` + `/icons/*` static)
  - [x] 11.1 Implement `routers/branding.py`
    - `GET /api/branding/icon` (any user): returns `{version, urls, has_rollback}`
    - `POST /api/branding/icon` (admin only, multipart/form-data): calls `branding_store.upload_icon`; emits audit log; updates `bh_platform_settings`
    - `POST /api/branding/icon/revert-to-default` (admin only)
    - `POST /api/branding/icon/rollback` (admin only); 409 if no rollback slot
    - File: `backend/routers/branding.py`
    - In `backend/main.py`: mount `/icons/` as a static directory pointing at `/files/branding/active/`
    - In `backend/main.py`: replace the static `manifest.json` mount with a dynamic FastAPI handler that emits the manifest with versioned icon URLs (`?v=<version>`)
    - Update `backend/main.py` index.html serving so the `<link rel="icon">` tag includes the current version string
    - _Requirements: R2.1, R2.2, R2.4, R2.5, R2.6, R2.7, R2.8_

  - [x] 11.2 RBAC + smoke test for branding endpoints
    - Cover: GET works for any user, POST returns 403 for non-admin, POST with non-PNG returns 400, POST with 4.5MB PNG returns 413, rollback returns 409 when no slot
    - File: `backend/tests/test_branding_router.py`
    - _Requirements: R2.3, R2.8_

- [x] 12. Settings router (`/api/settings/*`)
  - [x] 12.1 Implement `routers/settings.py`
    - `GET /api/settings`: returns user's full `settings_json` plus resolved `effective_theme: {id, tokens_json}` and `effective_text_size: 'medium'`, computed via `theme_resolver` and `text_size_resolver`
    - `PATCH /api/settings`: accepts partial keys (`theme_id`, `text_size`, `morning_card_workspace_id`, `morning_card_disabled`, `voice`); JSON-patch merge into `settings_json`; reject `theme_id` not visible to user (400); ignore unknown values for `text_size` (resolver handles fallback)
    - `POST /api/settings/reset-theme`: clears `settings_json.theme_id` so resolver falls back to platform default
    - File: `backend/routers/settings.py`
    - Register in `backend/main.py`
    - _Requirements: R3.2, R3.3, R3.5, R3.6, R3.7, R4.3, R4.5, R4.6, R8.9, R10.9_

  - [x] 12.2 Unit + RBAC tests for settings router
    - Cover: GET returns `effective_theme` and `effective_text_size`, PATCH `theme_id` to a private theme owned by another user → 400, PATCH `text_size: "huge"` → resolver returns medium, reset-theme clears the override
    - File: `backend/tests/test_settings_router.py`
    - _Requirements: R3.2, R3.5, R4.6_

- [x] 13. Workspace system prompt + pinned context (extend existing endpoints)
  - [x] 13.1 Extend `routers/workspaces.py` PATCH handler
    - Add 50,000-char length check on `system_prompt`; return 400 with length-limit error
    - Require admin role when `system_prompt` is in the body; non-admin → 403
    - On successful save, write to `bh_audit_log` with the workspace id and a hash of the new system_prompt
    - GET handler already returns `system_prompt`; no change needed beyond confirming RBAC for non-members → 403 (R5.6)
    - _Requirements: R5.1, R5.2, R5.6, R6.4, R6.6, R6.7, R6.8_

  - [x] 13.2 Add pinned-context refresh endpoint
    - `POST /api/workspaces/{id}/pinned-context/{eid}/refresh`: re-execute the SQL against the workspace's permitted schemas using existing `SchemaGuard`; update `cached_result`, `cached_at`, `token_estimate`; return 400 if entry is `type='static'`
    - File: extension to `backend/routers/workspaces.py`
    - _Requirements: R7.7_

  - [x] 13.3 Tests for workspace prompt + pinned-context refresh
    - PATCH with 60,000-char prompt → 400, non-admin PATCH with `system_prompt` → 403, member GET → 200 with prompt, refresh on static entry → 400, refresh on dynamic entry → 200 with updated cache
    - File: `backend/tests/test_workspaces_extensions.py`
    - _Requirements: R5.6, R6.6, R6.8, R7.7, R7.9_

- [x] 14. Quick capture router (`/api/quick-capture/*`)
  - [x] 14.1 Implement `routers/quick_capture.py`
    - `POST /api/quick-capture/extract`: thin pass-through to existing `smart-capture-extract` skill via `skill_executor.execute()`; body `{text?, image_path?, workspace_id}`; returns `{intents, asset, raw_text, extract_token}`; 502 on n8n error with `{retryable: true}`
    - `POST /api/quick-capture/commit`: pass-through to `smart-capture-commit`; body `{domain, payload, asset_id?, extract_token, workspace_id}`
    - `POST /api/quick-capture/raw-note`: writes verbatim to `/knowledge/captures/<slug>.md` via existing filewriter helpers; bypasses AI entirely (R9.9 fallback)
    - All three run in the user's workspace context — permission inheritance is via `skill_executor`'s existing checks
    - File: `backend/routers/quick_capture.py`
    - Register in `backend/main.py`
    - _Requirements: R9.2, R9.3, R9.4, R9.8, R9.9_

  - [x] 14.2 Quick capture happy-path integration test
    - Mock `skill_executor` to return canned extract + commit responses; assert the router produces the expected `{intents}` shape and that commit is called per accepted intent
    - Cover: extract failure → 502, raw-note → file written under `/knowledge/captures/`
    - File: `backend/tests/test_quick_capture_router.py`
    - _Requirements: R9.2, R9.4, R9.9_

- [x] 15. Scheduled prompts router (`/api/scheduled-prompts/*`)
  - [x] 15.1 Implement `routers/scheduled_prompts.py`
    - Endpoints: GET list (with optional `workspace_id` filter), POST create, PATCH update, DELETE, POST `/toggle`, POST `/run-now`, GET `/log`
    - All endpoints filter to workspaces the user has access to
    - Wraps `scheduled_prompts.py` service
    - File: `backend/routers/scheduled_prompts.py`
    - Register in `backend/main.py`
    - _Requirements: R11.1, R11.2, R11.3, R11.7, R11.8, R11.9, R11.10, R11.11_

  - [x] 15.2 Smoke + RBAC tests for scheduled prompts router
    - Cover: create with invalid cron → 400, create scoped to other user's private workspace → 403, run-now triggers immediate execution and writes a `bh_hook_log` row, log endpoint returns last 10
    - File: `backend/tests/test_scheduled_prompts_router.py`
    - _Requirements: R11.3, R11.9, R11.10, R11.11_

- [x] 16. Briefing router (`/api/briefing/*`)
  - [x] 16.1 Implement `routers/briefing.py`
    - `GET /api/briefing/latest?workspace_id=X`: query `bh_messages` for the most recent `system` message with `metadata.briefing=true` in the user's morning-card workspace (default General); compute `age_hours`; if no briefing within last 24h, return `{briefing_id: null}`; otherwise parse via `briefing_summary.parse_sections` and return `{briefing_id, content, generated_at, age_hours, parsed_sections}`
    - `POST /api/briefing/generate-now?workspace_id=X`: call existing `BriefingService.generate()`, persist the result as a system message, return same shape as GET; 503 on briefing service error
    - File: `backend/routers/briefing.py`
    - Register in `backend/main.py`
    - _Requirements: R8.1, R8.3, R8.4, R8.7_

  - [x] 16.2 Tests for briefing router
    - Cover: no briefing in last 24h → `briefing_id: null`, with briefing → parsed sections returned, missing weather section → returns with `—` placeholder, member of non-target workspace → 403
    - File: `backend/tests/test_briefing_router.py`
    - _Requirements: R8.1, R8.3, R8.7_

- [x] 17. Backend integration checkpoint
  - Ensure all migrations apply, all new routers registered in `backend/main.py`, `/api/themes`, `/api/branding/icon`, `/api/settings`, `/api/quick-capture/*`, `/api/scheduled-prompts/*`, `/api/briefing/*` reachable via curl with admin credentials
  - Run the full backend test suite; confirm pre-existing custom-chat-app tests still pass
  - Ensure all tests pass, ask the user if questions arise

### E. Frontend foundation

- [x] 18. Settings + branding stores and CSS-variable theming
  - [x] 18.1 Create `useSettingsStore` (Zustand)
    - File: `frontend/src/stores/settings.ts`
    - Shape: `{ settings, effectiveTheme, effectiveTextSize, loadSettings(), patch(delta), resetTheme() }`
    - `loadSettings` calls `GET /api/settings`; `patch` calls `PATCH /api/settings` and updates store optimistically
    - Persist `effectiveTheme.tokens_json` and `effectiveTextSize` to `localStorage` for instant first-render before network resolves
    - _Requirements: R3.2, R3.6, R3.7, R4.3, R4.5_

  - [x] 18.2 Create `useBrandingStore` (Zustand)
    - File: `frontend/src/stores/branding.ts`
    - Shape: `{ version, urls, hasRollback, refresh() }` — `refresh()` calls `GET /api/branding/icon`
    - _Requirements: R2.4, R2.5_

  - [x] 18.3 Wire CSS custom properties on `<html>`/`<body>` via `App.tsx`
    - On settings load, write every token from `effectiveTheme.tokens_json` to `:root` style as `--color-<token>`: background, surface, primary, accent, text, text_muted, border, danger, success
    - Toggle text-size class (`bh-text-small | bh-text-medium | bh-text-large | bh-text-xlarge`) on the chat-content wrapper inside `MessageList.tsx` (NOT on the app root, so UI chrome stays fixed-size — R4.4)
    - File: `frontend/src/App.tsx`, `frontend/src/components/MessageList.tsx`
    - _Requirements: R3.2, R3.6, R4.3, R4.4_

  - [x] 18.4 Update `tailwind.config.ts` and `index.css`
    - Map Tailwind colors to the new custom properties: `background`, `surface` (DEFAULT/light/dark), `primary`, `accent`, `text` (DEFAULT/muted), `border`, `danger`, `success`
    - Add the four `.bh-text-*` size classes to `index.css`
    - Existing `brand-50..brand-900` palette retained for backward compat — leave unchanged in this pass
    - File: `frontend/tailwind.config.ts`, `frontend/src/index.css`
    - _Requirements: R3.2, R4.1, R4.2, R4.4_

  - [x] 18.5 Unit test for settings store + theme application
    - Mock `fetch`; assert `loadSettings()` populates store, `patch({theme_id})` updates `effectiveTheme`, CSS custom properties match the new theme tokens after a re-render, text-size class toggles correctly
    - File: `frontend/src/stores/__tests__/settings.test.ts`
    - _Requirements: R3.2, R4.3_

### F. Settings page refactor + Appearance + Voice

- [x] 19. Settings page section refactor and AppearancePanel
  - [x] 19.1 Refactor `pages/SettingsPage.tsx`
    - Section-based layout: Profile, Appearance, Voice, Notifications, Briefing, Context Capture, Scheduled Prompts (in that order — R12.1)
    - Render Admin entry only when user has admin role (R12.5)
    - Each section is a child component; SettingsPage is a thin shell
    - File: `frontend/src/pages/SettingsPage.tsx`
    - _Requirements: R12.1, R12.4, R12.5_

  - [x] 19.2 Implement `components/AppearancePanel.tsx`
    - Theme grid: lists all themes from `GET /api/themes`, highlights `is_default`, shows preset/custom badges, click selects (calls `useSettingsStore.patch({theme_id})`)
    - "Use platform default" button → `POST /api/settings/reset-theme`
    - Text size buttons: four labeled buttons (Small, Medium, Large, Extra Large), each rendered at its corresponding size as a live preview, click calls `patch({text_size})`
    - "Build a custom theme" button → opens `<ThemeBuilder>`
    - One-time toast if user's selected theme was reset by backend fallback (uses `effectiveTheme.id !== settings.theme_id` condition — R3.8)
    - File: `frontend/src/components/AppearancePanel.tsx`
    - _Requirements: R3.1, R3.2, R3.3, R3.8, R4.1, R4.2, R4.3, R12.2_

  - [x] 19.3 Implement `components/VoicePanel.tsx`
    - Toggle: TTS output enabled/disabled
    - Voice picker (populated from `speechSynthesis.getVoices()`)
    - Speech rate slider (0.5–2.0)
    - Auto-submit pause threshold input (ms)
    - Manual-send toggle
    - Browser-capability badge: shows "Voice unavailable in this browser" when `SpeechRecognition` is undefined, hides controls accordingly (R10.8)
    - All changes call `useSettingsStore.patch({voice: {...}})`
    - File: `frontend/src/components/VoicePanel.tsx`
    - _Requirements: R10.8, R10.9, R12.3_

  - [x] 19.4 Component tests for AppearancePanel + VoicePanel
    - Cover: theme select calls `patch`, text-size buttons render at correct font-size, voice panel hides controls when capability detection fails
    - File: `frontend/src/components/__tests__/SettingsPanels.test.tsx`
    - _Requirements: R3.1, R4.2, R10.8_

- [x] 20. ThemeBuilder modal
  - [x] 20.1 Implement `components/ThemeBuilder.tsx`
    - Color pickers (HTML `<input type="color">` paired with hex text field) for each token: background, surface, primary, accent, text, text_muted, border, danger, success
    - Live preview pane: renders a fake user message + assistant message + sidebar fragment using the working tokens
    - Contrast badge: live `ok` / `warn` / `block` indicator computed against the design's contrast formula (mirror `theme_validator.contrast_decision` in TS — small pure helper)
    - Save button: disabled when contrast is `block`; calls `POST /api/themes` with `publish: false` for users, `publish: true` checkbox for admins
    - Mobile: full-screen; desktop: centered modal
    - Props: `themeId?: number`, `onSave: (theme) => void`, `onClose: () => void`
    - File: `frontend/src/components/ThemeBuilder.tsx`, plus `frontend/src/lib/contrast.ts` for the pure contrast helper
    - _Requirements: R1.4, R1.6, R1.7, R1.8, R3.4_

  - [x] 20.2 Property test for frontend contrast helper
    - **Property 3 (frontend mirror): contrast decision matches backend**
    - Use `fast-check` to generate hex pairs; assert the TS helper agrees with a reference implementation; assert symmetry
    - **Validates: Requirements R1.7, R1.8**
    - File: `frontend/src/lib/__tests__/contrast.property.test.ts`
    - _Property: P3_

### G. Admin tooling

- [x] 21. IconUploader (admin)
  - [x] 21.1 Implement `components/IconUploader.tsx`
    - Renders current 192/512 icons side-by-side from `useBrandingStore.urls`
    - Upload control: file picker, validates client-side (PNG, ≥512px square within 1%, ≤4MB) before POST
    - "Revert to default" button
    - "Rollback" button (disabled when `!hasRollback`)
    - On success: `useBrandingStore.refresh()`, fire service-worker update notification (the existing PWA SW supports versioned cache-busting via the manifest version string; nothing extra needed here)
    - File: `frontend/src/components/IconUploader.tsx`
    - _Requirements: R2.1, R2.2, R2.3, R2.6, R2.7_

  - [x] 21.2 Component test for IconUploader
    - Cover: upload of non-PNG → client-side rejection with message, upload of 511px PNG → rejection, successful upload → `refresh()` called and version updates
    - File: `frontend/src/components/__tests__/IconUploader.test.tsx`
    - _Requirements: R2.3_

### H. Workspace settings panel (system prompt + pinned context)

- [x] 22. Workspace settings panel and prompt viewer/editor
  - [x] 22.1 Implement `components/WorkspaceSettingsPanel.tsx`
    - Right-side modal/panel triggered from the workspace settings cog
    - Tabs: "System Prompt", "Pinned Context"
    - Mounts `<SystemPromptViewer>` / `<SystemPromptEditor>` and `<PinnedContextManager>` based on tab + admin role
    - Props: `workspaceId`, `mode: 'view' | 'edit'`
    - File: `frontend/src/components/WorkspaceSettingsPanel.tsx`
    - _Requirements: R5.1, R5.2, R6.1_

  - [x] 22.2 Implement `components/SystemPromptViewer.tsx`
    - Read-only markdown render of `bh_workspaces.system_prompt` using existing `react-markdown` + `rehype-highlight` setup
    - Empty-prompt placeholder: "No system prompt set for this workspace"
    - Character count + token count (chars / 4, rounded) below the viewer
    - Props: `workspaceId`, `prompt`
    - File: `frontend/src/components/SystemPromptViewer.tsx`
    - _Requirements: R5.1, R5.2, R5.3, R5.4, R5.5_

  - [x] 22.3 Implement `components/SystemPromptEditor.tsx`
    - Side-by-side or tabbed layout (raw markdown textarea + rendered preview)
    - Editor: monospace, line numbers, soft wrap, tab/shift-tab indentation
    - Live preview debounced 300ms (no server call)
    - Save button → `PATCH /api/workspaces/{id}` with `{system_prompt}`; success toast
    - Cancel with unsaved changes → confirm dialog before discarding
    - Length-limit error from backend (50,000 chars) shown inline
    - Props: `workspaceId`, `initialPrompt`, `canEdit`
    - File: `frontend/src/components/SystemPromptEditor.tsx`
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7_

- [x] 23. PinnedContextManager
  - [x] 23.1 Implement `components/PinnedContextManager.tsx`
    - List entries from `GET /api/workspaces/{id}/pinned-context`: title, type badge (`static`/`dynamic`), priority, token estimate, last refresh timestamp (dynamic only)
    - Click entry → expand to full content (static) or SQL + cached result (dynamic)
    - Add/Edit form fields: title, type, content/query, priority, refresh_minutes (dynamic)
    - "Refresh now" on dynamic entries → `POST .../refresh`, update inline
    - Running token total at top with 75%-of-budget warning (yellow banner) — uses pure helper `should_warn(L, budget)`
    - Add/Edit/Delete only for admins; non-admin sees read-only list
    - File: `frontend/src/components/PinnedContextManager.tsx`, plus `frontend/src/lib/pinned_budget.ts` for the pure helper
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R7.9_

  - [x] 23.2 Property test for budget warning
    - **Property 6: Pinned context budget warning matches the threshold**
    - Use `fast-check` to generate `(list of token estimates, budget)`; assert `should_warn(L, budget) == (sum(L) > 0.75 * budget)`; assert no exception on empty list or zero budget (returns false)
    - **Validates: Requirements R7.8**
    - File: `frontend/src/lib/__tests__/pinned_budget.property.test.ts`
    - _Property: P6_

- [x] 24. Checkpoint — workspace settings + appearance done
  - Ensure all tests pass, ask the user if questions arise

### I. Morning card

- [x] 25. MorningCard component + visibility logic
  - [x] 25.1 Implement pure helper `morning_card.ts`
    - `is_visible(briefing_age_hours: number, dismiss_set: Set<string>, current_date_iso: string): boolean` returns `briefing_age_hours < 24 AND !dismiss_set.has(current_date_iso)`
    - Helpers: `read_dismiss_set()` from localStorage, `dismiss_today(date)` writes to localStorage
    - File: `frontend/src/lib/morning_card.ts`
    - _Requirements: R8.5, R8.6_

  - [x] 25.2 Implement `components/MorningCard.tsx`
    - Renders at top of `ChatArea` when `activeWorkspace.id === settings.morning_card_workspace_id` AND `!settings.morning_card_disabled`
    - Fetches `GET /api/briefing/latest?workspace_id=X`
    - If `briefing_id == null`: shows "Generate today's briefing" button → `POST /api/briefing/generate-now`
    - If briefing present: renders parsed sections with icons (☀ weather, 💸 spending, 📥 inbox, 📅 schedule, ✨ anything else)
    - Sections with `—` content (R8.7) render with muted placeholder
    - Close button → `dismiss_today` for the rest of the calendar day on this browser
    - Settings choice: include "Disable" option in the morning-card workspace setting (writes `morning_card_disabled: true`)
    - Props: `workspaceId`
    - File: `frontend/src/components/MorningCard.tsx`
    - _Requirements: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9_

  - [x] 25.3 Property test for morning-card visibility
    - **Property 7: Morning card visibility follows the truth table**
    - Use `fast-check` to generate `(briefing_age_hours, dismiss_set, current_date_iso)`; assert `is_visible == (age < 24 AND date ∉ dismiss_set)`
    - **Validates: Requirements R8.1, R8.5, R8.6**
    - File: `frontend/src/lib/__tests__/morning_card.property.test.ts`
    - _Property: P7_

  - [x] 25.4 Component test for MorningCard
    - Cover: no-briefing state shows generate button, dismissed state hides card, generate-now click calls correct endpoint, sections render with icons and `—` placeholders for missing data
    - File: `frontend/src/components/__tests__/MorningCard.test.tsx`
    - _Requirements: R8.3, R8.4, R8.7_

### J. Quick capture

- [x] 26. QuickCaptureOverlay + global hotkey + share-target wiring
  - [x] 26.1 Implement `components/QuickCaptureOverlay.tsx`
    - Modal triggered by global keyboard handler (`Ctrl+Shift+K` / `Cmd+Shift+K`) registered in `App.tsx`, OR by navigating to `/quick-capture` (PWA share target)
    - Inputs: multi-line textarea, image attach button (uses existing `/api/files/upload`), Save/Cancel
    - On Save: calls `/api/quick-capture/extract` → renders extracted intents in a confirm sub-view → on Confirm calls `/api/quick-capture/commit` per accepted intent → success toast summarizing saves
    - On Cancel/Escape: closes without any backend calls
    - On extract failure: Retry + "Save as raw note" → `/api/quick-capture/raw-note` (R9.9)
    - Props: `initialText?`, `initialImage?` (for share-target pre-population)
    - File: `frontend/src/components/QuickCaptureOverlay.tsx`
    - _Requirements: R9.1, R9.2, R9.3, R9.4, R9.5, R9.7, R9.8, R9.9_

  - [x] 26.2 Wire global hotkey + `/quick-capture` route
    - Register `keydown` handler in `App.tsx` that opens the overlay on Ctrl/Cmd+Shift+K (uses existing global keyboard handler pattern)
    - Add React Router route for `/quick-capture` that mounts the overlay with `initialText` / `initialImage` parsed from `URLSearchParams` and form-data
    - File: `frontend/src/App.tsx`
    - _Requirements: R9.1, R9.7_

  - [x] 26.3 Add Web Share Target to `manifest.json` and service worker
    - Add `share_target` block to `frontend/public/manifest.json`: `action: "/quick-capture"`, `method: "POST"`, `enctype: "multipart/form-data"`, `params: {title, text, url, files: [{name: "files", accept: ["image/*"]}]}`
    - Update `frontend/public/sw.js` to handle `POST /quick-capture` navigations: read multipart form, store in IDB or pass via `postMessage` to client, then `Response.redirect('/quick-capture')` so the SPA route picks it up
    - File: `frontend/public/manifest.json`, `frontend/public/sw.js`
    - _Requirements: R9.6, R9.7_

  - [x] 26.4 Component test + manifest assertion for QuickCapture
    - Component test: keystroke `Cmd+Shift+K` opens overlay, Escape closes without backend calls, extract failure surfaces Retry + raw-note, raw-note path posts to `/api/quick-capture/raw-note`
    - Manifest test: read built `manifest.json`, assert `share_target.action === '/quick-capture'` and `share_target.params.files[0].accept` contains `image/*`
    - File: `frontend/src/components/__tests__/QuickCaptureOverlay.test.tsx`, `frontend/tests/manifest.test.ts`
    - _Requirements: R9.5, R9.6, R9.9_

### K. Voice mode

- [x] 27. Voice mode hook + button + TTS prose stripping
  - [x] 27.1 Implement pure helper `tts_strip.ts`
    - `tts_strip(markdown: string): string` strips fenced code blocks (replace with `"code block omitted"`), markdown tables (replace with `"table omitted"`), and inline images (replace with `"image: <alt>"` if alt non-empty else `"image omitted"`); preserves prose order and characters
    - File: `frontend/src/lib/tts_strip.ts`
    - _Requirements: R10.5_

  - [x] 27.2 Implement `hooks/useVoiceMode.ts`
    - Capability detection: `'SpeechRecognition' in window || 'webkitSpeechRecognition' in window` plus `'speechSynthesis' in window`
    - `start()`: `getUserMedia({audio:true})` for permission, then instantiate `SpeechRecognition` with `continuous=true`, `interimResults=true`, `lang=navigator.language`
    - On `onresult`: append finalized partials to chat input, show interim in lighter color
    - Silence timer: reset on each result; if elapsed > `voice.auto_submit_pause_ms` AND `!voice.manual_send`, finalize + submit
    - TTS: subscribe to assistant streaming events, accumulate into a buffer, segment via `tts_strip`, speak each chunk via `SpeechSynthesisUtterance` with `voice = voice.voice_name`, `rate = voice.speech_rate`
    - `stop()`: `recognition.stop()` (finalizes without auto-submit, R10.6) + `window.speechSynthesis.cancel()` for stop-speaking button
    - File: `frontend/src/hooks/useVoiceMode.ts`
    - _Requirements: R10.1, R10.2, R10.3, R10.4, R10.5, R10.6, R10.7, R10.8, R10.9_

  - [x] 27.3 Implement `components/VoiceModeButton.tsx`
    - Microphone button next to send button in `InputArea.tsx`
    - Returns `null` if capability detection fails; fires one-time toast on first render in unsupported browser (R10.8)
    - Stop-speaking button shown when TTS is active
    - File: `frontend/src/components/VoiceModeButton.tsx`
    - Wire into `frontend/src/components/InputArea.tsx`
    - _Requirements: R10.1, R10.7, R10.8_

  - [x] 27.4 Property test for tts_strip
    - **Property 8: TTS markdown stripping preserves prose and elides code/tables/images**
    - Use `fast-check` to generate markdown documents (mix of fenced blocks, tables, images, prose); assert: no character of any code block body is in the output, no table row is in the output, no image URL is in the output, "code block omitted" appears iff at least one fenced block, "table omitted" appears iff at least one table, prose chars appear in original order
    - **Validates: Requirements R10.5**
    - File: `frontend/src/lib/__tests__/tts_strip.property.test.ts`
    - _Property: P8_

  - [x] 27.5 Privacy property test (no audio over network)
    - **Property 9: Voice mode never emits audio over the network**
    - Mount `useVoiceMode` in a test harness; mock `fetch`, `XMLHttpRequest`, and `WebSocket.send`; drive a sequence of voice events (start, partial result, finalize, submit, stop, TTS speak); assert no call body has MIME type `audio/*` or contains a `MediaRecorder` blob
    - **Validates: Requirements R10.10**
    - File: `frontend/src/hooks/__tests__/useVoiceMode.privacy.test.ts`
    - _Property: P9_

### L. Scheduled prompts page

- [x] 28. ScheduledPromptsPage with cron preset picker and log viewer
  - [x] 28.1 Implement `pages/ScheduledPromptsPage.tsx`
    - Lists all scheduled prompts via `GET /api/scheduled-prompts`
    - Columns: name, workspace, schedule (human-readable via `cronstrue`), delivery method, enabled toggle, last run status, actions (Edit, Run Now, Disable, Delete)
    - Click row → expand to show last 10 log entries from `GET /api/scheduled-prompts/{id}/log`
    - "New scheduled prompt" button opens form panel
    - File: `frontend/src/pages/ScheduledPromptsPage.tsx`
    - Add route in `App.tsx`: `/scheduled-prompts`
    - _Requirements: R11.1, R11.7, R11.8, R11.9, R11.10_

  - [x] 28.2 Implement `components/ScheduledPromptForm.tsx`
    - Fields: name, workspace (limited to user's accessible), prompt template (textarea), schedule (raw cron input + friendly preset picker), delivery method radio (`pin` / `pushover`)
    - Cron preset picker: "every day at X" / "weekly on Y at X" / "monthly on day Z at X" — translates to cron client-side
    - Validates cron client-side using `cronstrue`; backend returns 400 with descriptive error on save if invalid (link to cron-expression help)
    - File: `frontend/src/components/ScheduledPromptForm.tsx`
    - _Requirements: R11.2, R11.3, R11.11_

  - [x] 28.3 Component test for ScheduledPromptsPage
    - Cover: list renders, edit/delete/toggle/run-now call correct endpoints, expand row fetches log, invalid cron shows error inline, preset picker translates to expected cron string
    - File: `frontend/src/pages/__tests__/ScheduledPromptsPage.test.tsx`
    - _Requirements: R11.2, R11.7, R11.8, R11.9, R11.11_

### M. Admin console

- [x] 29. AdminConsolePage refactor
  - [x] 29.1 Refactor `pages/AdminConsolePage.tsx`
    - Replaces existing `AdminPanel.tsx` as the entry
    - Sidebar navigation: Users, Skills, Hooks, Cost, Workspaces (existing) + Theme Management + Icon Management (new)
    - Each section is a child route; admin-only via existing role check
    - Theme Management section embeds the admin variant of theme list + builder (calls `POST /api/themes` with `publish: true`, sets platform default via `POST /api/themes/{id}/set-platform-default`)
    - Icon Management section embeds `<IconUploader>`
    - File: `frontend/src/pages/AdminConsolePage.tsx`, route registration in `App.tsx`
    - _Requirements: R1.2, R1.3, R12.5, R12.6, R12.7_

  - [x] 29.2 Tests for AdminConsolePage RBAC
    - Cover: non-admin user navigating to `/admin` → redirect to home, admin user sees Theme Management + Icon Management sections, admin can publish theme via the UI
    - File: `frontend/src/pages/__tests__/AdminConsolePage.test.tsx`
    - _Requirements: R12.5, R12.6_

### N. Final wiring + smoke

- [x] 30. Final wiring, manifest refresh, and full-feature smoke test
  - [x] 30.1 Settings navigation link audit
    - Wire links: SettingsPage → ScheduledPromptsPage section anchor, AdminConsolePage entry visible only to admins, "Build a custom theme" → ThemeBuilder modal, redirect unauthenticated users from any Settings or Admin route to login (R12.7)
    - File: `frontend/src/pages/SettingsPage.tsx`, `frontend/src/App.tsx`
    - _Requirements: R12.4, R12.5, R12.7_

  - [x] 30.2 Manifest.json + service worker refresh
    - Confirm dynamic manifest emission includes versioned icon URLs and the `share_target` block
    - Confirm service worker pass-through still functions; share-target POST handler routes correctly
    - File: `frontend/public/manifest.json`, `frontend/public/sw.js`, backend dynamic manifest handler
    - _Requirements: R2.4, R2.5, R9.6_

  - [x] 30.3 End-to-end smoke test script
    - Extend `bowershub-ai/scripts/smoke_test.py` with new scenarios:
      - Login as admin, create a custom theme, set platform default, observe `effective_theme` change for non-admin user
      - Upload a test PNG icon, GET `/icons/icon-192.png` → 200 with new bytes
      - PATCH workspace `system_prompt` as non-admin → 403; as admin → 200 + audit log entry
      - POST pinned-context refresh on a dynamic entry → cached_at changes
      - GET `/api/briefing/latest` for the General workspace → 200 (with or without briefing_id)
      - POST a quick-capture extract with a canned text → returns intents shape
      - POST a scheduled prompt with `* * * * *`, run-now → success log entry, GET log → entries returned
    - File: `bowershub-ai/scripts/smoke_test.py`
    - _Requirements: R1.3, R2.2, R6.4, R7.7, R8.1, R9.2, R11.9, R11.10_

  - [x] 30.4 Update CHANGELOG-style notes in `bowershub-ai/README.md`
    - Append a "BowersHub AI Enhancements (this spec)" section listing: new tables (`bh_themes`, `bh_platform_settings`), new routers (themes, branding, settings, quick-capture, scheduled-prompts, briefing), new frontend pages/components, new env-var requirements (none — feature is additive), the seven Settings sections, and the `/quick-capture` PWA share-target action
    - File: `bowershub-ai/README.md`
    - _Requirements: All_

  - [x] 30.5 Final checkpoint
    - Run full backend test suite (pytest), full frontend test suite (vitest), full property test suite (hypothesis + fast-check); all pass
    - Run smoke test against a dev container (`docker build` then `docker run` on a non-prod port)
    - Ensure all tests pass, ask the user if questions arise

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP, but the property tests are the only mechanical guarantee of the 13 correctness properties — recommend running them at minimum once before deploy
- Each task references specific requirements for traceability
- Property tests are placed close to the code they validate (catch errors early)
- Backend pure-logic services (theme_validator, theme_resolver, text_size_resolver, briefing_summary, cron validator) are intentionally split out so they're testable without a DB or HTTP layer
- The `call_ai` hook delivery routing extension is the only modification to existing hook_engine code — everything else is additive
- All migrations are reversible during dev (DROP TABLE); no production rollback planned
- Branding asset directory `/files/branding/` lives inside the existing `/files` bind mount — no new docker volumes
- Voice mode runs entirely in the browser; no audio reaches the backend (Property 9 enforces this)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "4.1", "5.1", "6.1", "18.1", "18.2"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "4.2", "5.2", "6.2", "7.1", "18.3", "18.4"] },
    { "id": 3, "tasks": ["3.2", "7.2", "7.3", "8.1", "9.1", "18.5"] },
    { "id": 4, "tasks": ["8.2", "9.2", "9.3", "10.1", "11.1", "12.1", "13.1", "13.2", "14.1", "15.1", "16.1"] },
    { "id": 5, "tasks": ["10.2", "11.2", "12.2", "13.3", "14.2", "15.2", "16.2", "19.1"] },
    { "id": 6, "tasks": ["19.2", "19.3", "20.1", "21.1", "22.1", "25.1", "26.3", "27.1"] },
    { "id": 7, "tasks": ["19.4", "20.2", "21.2", "22.2", "22.3", "23.1", "25.2", "26.1", "27.2", "28.2"] },
    { "id": 8, "tasks": ["23.2", "25.3", "25.4", "26.2", "27.3", "28.1", "29.1"] },
    { "id": 9, "tasks": ["26.4", "27.4", "27.5", "28.3", "29.2", "30.1", "30.2"] },
    { "id": 10, "tasks": ["30.3", "30.4"] },
    { "id": 11, "tasks": ["30.5"] }
  ]
}
```
