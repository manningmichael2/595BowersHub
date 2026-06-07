# Technical Design Document

## Overview

This document defines the technical design for the BowersHub AI Enhancements feature set: admin-controlled branding (theme palettes and app icon), per-user appearance preferences (theme and text size), workspace system-prompt viewing/editing, pinned-context viewer/editor, a proactive morning card, a quick-capture overlay, voice mode, and a UI for scheduled prompts. The work extends the existing `custom-chat-app` platform — a FastAPI backend plus React PWA frontend deployed as a single Docker container at port 5003 — and intentionally avoids introducing new services. Every feature plugs into a service that already exists in the platform: the briefing service (R16) for the morning card, the existing pinned-context API (R15) for the pinned-context UI, the smart-capture skill chain for quick capture, the hook engine (R17) for scheduled prompts, and the existing admin panel (R29) for theme/icon administration.

The design choices favor server-side persistence so user preferences follow the user across the PWA on multiple devices, on-disk branding assets so visual identity changes do not require a redeploy, and per-user theme + text-size resolution so the platform can support multiple users with different visual needs without forking the UI. Voice mode runs entirely in the browser (Web Speech API for STT, SpeechSynthesis for TTS), so no audio ever leaves the device. The new code is additive: no existing tables are altered destructively, the `bh_users.settings_json` JSONB column gets new keys but no schema change, and migrations are appended starting at `009_themes_and_branding.sql`.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          Docker Container (bowershub-ai:5003)               │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                      FastAPI Application                              │ │
│  │                                                                       │ │
│  │  Existing services (unchanged externally):                            │ │
│  │  ┌────────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐     │ │
│  │  │  router_   │  │ briefing │  │  hook_    │  │  skill_      │     │ │
│  │  │  engine    │  │          │  │  engine   │  │  executor    │     │ │
│  │  └─────┬──────┘  └─────┬────┘  └─────┬─────┘  └──────┬───────┘     │ │
│  │        │               │              │               │             │ │
│  │  ┌─────▼───────────────▼──────────────▼───────────────▼─────────┐  │ │
│  │  │  NEW routers: themes, branding, settings, scheduled_prompts,  │  │ │
│  │  │               quick_capture                                    │  │ │
│  │  └──────────────────────────────────────────────────────────────┘  │ │
│  │                                                                       │ │
│  │  NEW services:                                                        │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐             │ │
│  │  │ theme_       │  │ branding_    │  │ scheduled_     │             │ │
│  │  │ resolver     │  │ store        │  │ prompts        │             │ │
│  │  └──────────────┘  └──────────────┘  └────────────────┘             │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Static mounts:                                                             │
│    /static/         → React PWA build output (existing)                     │
│    /icons/          → /files/branding/active/ (NEW, served by FastAPI)      │
│    /files/branding/ → /files/branding/{active,previous,history}/ (NEW)      │
└────────────────────────────────────────────────────────────────────────────┘
        │                  │                    │                  │
        ▼                  ▼                    ▼                  ▼
┌──────────────┐  ┌─────────────────┐  ┌───────────────┐  ┌───────────────┐
│   Postgres   │  │ Pillow (icon    │  │  n8n          │  │  Browser-only │
│ (bh_themes,  │  │  resize +       │  │  /webhook/    │  │  Web Speech / │
│  bh_platform │  │  maskable)      │  │  smart-       │  │  TTS — never  │
│  _settings,  │  │                 │  │  capture/*    │  │  reaches the  │
│  bh_users    │  │                 │  │               │  │  backend      │
│  .settings_  │  │                 │  │               │  │               │
│  json)       │  │                 │  │               │  │               │
└──────────────┘  └─────────────────┘  └───────────────┘  └───────────────┘
```

How the new pieces plug into the existing services:

- **router_engine** is unchanged. The system-prompt editor saves to `bh_workspaces.system_prompt`; on the next message the router reads the row fresh, so the new prompt is live without restart (R6.7).
- **briefing service** is unchanged. The morning card calls `GET /api/briefing/latest` (new thin endpoint that reads the most recent `system` message tagged `metadata.briefing=true`) and `POST /api/briefing/generate-now` which delegates to `BriefingService.generate()`.
- **skill_executor** is unchanged. Quick capture calls the existing `smart-capture-extract` and `smart-capture-commit` skills through the new `/api/quick-capture/*` thin endpoints; permissions flow through the existing skill registry.
- **hook_engine** is unchanged. Scheduled prompts are written as standard `bh_hooks` rows with `event_type='schedule'` and `action_type='call_ai'`. The engine already supports `call_ai` (see existing `_execute_hook` action dispatch); we extend the action handler to deliver via `pin` or `pushover` based on `action_config.delivery_method`.
- **auth middleware** is unchanged. New endpoints reuse `get_current_user` and `require_admin` dependencies.
- **files mount** is unchanged. The new `/files/branding/` directory lives inside the same `/files` bind mount.

## Components and Interfaces

The detailed component breakdown lives in two later sections of this document — see [Backend Services and Modules](#backend-services-and-modules) for the new Python modules and routes, and [Frontend Components](#frontend-components) for the React components, hooks, and Zustand stores. The high-level inventory is:

- **New backend services**: `theme_resolver`, `theme_validator`, `branding_store`, `text_size_resolver`, `scheduled_prompts`, `briefing_summary`. Plus extension points on the existing `hook_engine` (`call_ai` action delivery routing).
- **New backend routers**: `themes`, `branding`, `settings`, `quick_capture`, `scheduled_prompts`, `briefing`.
- **New frontend pages**: refactored `SettingsPage`, new `ScheduledPromptsPage`, refactored `AdminConsolePage`.
- **New frontend components**: `AppearancePanel`, `ThemeBuilder`, `IconUploader`, `WorkspaceSettingsPanel`, `SystemPromptViewer`, `SystemPromptEditor`, `PinnedContextManager`, `MorningCard`, `QuickCaptureOverlay`, `VoiceModeButton`.
- **New hooks**: `useVoiceMode`.
- **New Zustand stores**: `useSettingsStore`, `useBrandingStore`.

## Data Models

The detailed schema is described in the [Database Changes](#database-changes) section that follows. Summary:

- **New tables**: `bh_themes` (theme palettes, both presets and custom), `bh_platform_settings` (key/value table for platform default theme and branding asset version pointers).
- **Extended JSONB**: `bh_users.settings_json` gains documented keys (`theme_id`, `text_size`, `morning_card_workspace_id`, `morning_card_disabled`, `voice`).
- **Reused tables**: `bh_workspaces` (system_prompt column already exists), `bh_pinned_context` (R15 schema unchanged), `bh_hooks` and `bh_hook_log` (R17 schemas unchanged — scheduled prompts are stored as standard hook rows).
- **No alters**: every existing column is left as-is. Only additive migrations.

## Database Changes

Two new tables are added in the `public` schema, both prefixed with `bh_` to match the existing convention. The existing `bh_users.settings_json` JSONB column gains documented keys; no DDL change needed.

### New table: `public.bh_themes`

```sql
CREATE TABLE public.bh_themes (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,                   -- url-safe identifier
    is_preset       BOOLEAN NOT NULL DEFAULT false,  -- shipped in code, undeletable
    owner_id        INTEGER REFERENCES public.bh_users(id) ON DELETE CASCADE,
    -- owner_id semantics:
    --   NULL + is_preset=true   → built-in preset (visible to all, undeletable)
    --   NULL + is_preset=false  → admin-published custom theme (visible to all)
    --   <user_id>               → personal custom theme (visible only to that user + admin)
    tokens_json     JSONB NOT NULL,                  -- { background, surface, primary, accent, text, text_muted, border, danger, success }
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slug, owner_id)
);

CREATE INDEX idx_bh_themes_owner ON public.bh_themes(owner_id);
CREATE INDEX idx_bh_themes_preset ON public.bh_themes(is_preset);
```

Every value in `tokens_json` is a 6-digit (`#rrggbb`) or 8-digit (`#rrggbbaa`) hex string. Validation lives in `theme_validator.py`; the table itself stores whatever is committed so validation rules can evolve.

### New table: `public.bh_platform_settings`

A single-row key/value table (not a one-row-only table — using key/value lets us add platform-wide settings later without further migrations).

```sql
CREATE TABLE public.bh_platform_settings (
    key             TEXT PRIMARY KEY,
    value_json      JSONB NOT NULL,
    updated_by      INTEGER REFERENCES public.bh_users(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Initial keys seeded by migration 009:

| key | value_json shape | purpose |
|-----|------------------|---------|
| `default_theme_id` | `{"theme_id": 1}` | Platform default theme (R1.3, R3.7) |
| `app_icon_version` | `{"version": "1717000000"}` | Cache-busting query string (R2.4) |
| `app_icon_active_filename` | `{"filename": "icon-set-default"}` | Pointer into `/files/branding/active/` |
| `app_icon_previous_filename` | `{"filename": null}` | Single-slot rollback target (R2.7) |

### Additions to `bh_users.settings_json`

The column already exists. New documented keys (all optional; absence means default):

```json
{
  "theme_id": 7,
  "text_size": "medium",
  "morning_card_workspace_id": 3,
  "morning_card_disabled": false,
  "voice": {
    "output_enabled": true,
    "voice_name": "Google US English",
    "speech_rate": 1.0,
    "auto_submit_pause_ms": 2000,
    "manual_send": false
  }
}
```

All values are advisory: the resolver functions (`theme_resolver`, `text_size_resolver`, `voice_settings_resolver`) tolerate missing keys, unknown values, and stale references. This invariant is exercised by the property tests (see Correctness Properties §10).

### Migration files

Two new migration files starting at the next number (008 already exists):

```
009_themes_and_branding.sql     -- creates bh_themes, bh_platform_settings, seeds 4 presets
010_settings_json_keys.sql      -- comment-only migration documenting the new keys (no DDL)
```

See §14 for full migration list and ordering notes.

## Backend API Endpoints

All paths are absolute. Auth column: `admin` = role admin only, `user` = any authenticated user, `member` = workspace-scoped member, `either` = admin or workspace member.

### Theme management (admin)

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/themes | user | — | `{themes: [{id, name, slug, is_preset, owner_id, tokens_json, is_default}]}` filtered by visibility (R3.5) | 200 |
| POST | /api/themes | user | `{name, tokens_json}` (admin can pass `publish: true`) | created theme row | 201; 400 on validation; 422 on contrast block (R1.8) |
| PATCH | /api/themes/{id} | user (own) / admin (any) | partial `{name, tokens_json}` | updated row | 200; 403 if not owner; 422 on contrast block |
| DELETE | /api/themes/{id} | user (own) / admin (any) | — | `{deleted: true, affected_user_count: N}` | 200; 403 if not owner; 409 if preset |
| POST | /api/themes/{id}/set-platform-default | admin | — | `{ok: true}` | 200; 404; 409 if user-scoped theme |

### Branding management (admin)

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/branding/icon | user | — | `{version, urls: {icon_192, icon_512, icon_maskable_512}, has_rollback}` | 200 |
| POST | /api/branding/icon | admin | multipart/form-data: `file` (PNG) | `{version, urls}` | 200; 400 (size/dim/mime); 413 (>4MB) |
| POST | /api/branding/icon/revert-to-default | admin | — | `{version}` | 200 |
| POST | /api/branding/icon/rollback | admin | — | `{version}` | 200; 409 if no rollback slot |
| GET | /icons/icon-192.png | public | — | PNG bytes | 200 |
| GET | /icons/icon-512.png | public | — | PNG bytes | 200 |
| GET | /icons/icon-maskable-512.png | public | — | PNG bytes | 200 |
| GET | /manifest.json | public | — | JSON with versioned icon URLs | 200 |

### User settings (own settings only)

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/settings | user | — | full `settings_json` plus `effective_theme: {id, tokens_json}`, `effective_text_size: "medium"` | 200 |
| PATCH | /api/settings | user | partial settings keys: `theme_id`, `text_size`, `morning_card_workspace_id`, `morning_card_disabled`, `voice` | updated full settings | 200; 400 if `theme_id` not visible to user |
| POST | /api/settings/reset-theme | user | — | `{theme_id: null}` (clears override → falls back to platform default per R3.3) | 200 |

### Workspace system prompt (already exists; documented here for completeness)

The existing `PATCH /api/workspaces/{id}` already accepts a `system_prompt` field (custom-chat-app R2). This spec adds a length check and audit-log emission:

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| PATCH | /api/workspaces/{id} (extended) | admin (for system_prompt) / member (other fields) | `{system_prompt?: string, …}` | updated workspace | 200; 400 if `len(system_prompt) > 50000` (R6.6); 403 for non-admin updating system_prompt (R6.8) |
| GET | /api/workspaces/{id} | either | — | workspace row including `system_prompt` (R5.1, R5.2) | 200; 403 |

### Pinned context (already exists per R15; documented here for the UI contract)

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/workspaces/{id}/pinned-context | either | — | `{entries: [{id, type, title, content?, query?, refresh_minutes?, cached_result?, cached_at?, priority, token_estimate}], total_token_estimate, budget}` | 200 |
| POST | /api/workspaces/{id}/pinned-context | admin | `{type, title, content?, query?, refresh_minutes?, priority}` | created entry | 201; 403 |
| PATCH | /api/workspaces/{id}/pinned-context/{eid} | admin | partial fields | updated entry | 200; 403 |
| DELETE | /api/workspaces/{id}/pinned-context/{eid} | admin | — | `{deleted: true}` | 200; 403 |
| POST | /api/workspaces/{id}/pinned-context/{eid}/refresh | admin | — | `{cached_result, cached_at, token_estimate}` | 200; 400 if static; 403 |

### Morning card

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/briefing/latest?workspace_id=X | member | — | `{briefing_id, content, generated_at, age_hours, parsed_sections: [{key, label, content}]}` or `{briefing_id: null}` if no briefing in last 24h | 200 |
| POST | /api/briefing/generate-now?workspace_id=X | member | — | same shape as GET, freshly generated | 200; 503 if briefing service errors |

### Quick capture

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| POST | /api/quick-capture/extract | user | `{text?, image_path?, workspace_id}` | passes through to smart-capture-extract; returns `{intents, asset, raw_text, extract_token}` | 200; 400; 502 on n8n error |
| POST | /api/quick-capture/commit | user | `{domain, payload, asset_id?, extract_token, workspace_id}` | passes through to smart-capture-commit | 200; 400; 502 |
| POST | /api/quick-capture/raw-note | user | `{text, workspace_id}` | `{path: "/knowledge/captures/<slug>.md"}` | 200 (R9.9 fallback) |

### Scheduled prompts (CRUD on bh_hooks rows where event_type=schedule, action_type=call_ai)

| Method | Path | Auth | Body | Response | Status |
|--------|------|------|------|----------|--------|
| GET | /api/scheduled-prompts | user | optional `?workspace_id=X` | `{prompts: [{id, name, workspace_id, prompt_template, cron_expression, cron_human, delivery_method, is_enabled, last_run, last_status}]}` filtered to user's workspaces | 200 |
| POST | /api/scheduled-prompts | member | `{name, workspace_id, prompt_template, cron_expression, delivery_method}` (`delivery_method` ∈ {`pin`, `pushover`}) | created hook row | 201; 400 if invalid cron (R11.11) |
| PATCH | /api/scheduled-prompts/{id} | member | partial | updated row | 200; 403 if not in user's workspace |
| DELETE | /api/scheduled-prompts/{id} | member | — | `{deleted: true}` | 200 |
| POST | /api/scheduled-prompts/{id}/toggle | member | `{enabled: bool}` | `{is_enabled}` | 200 |
| POST | /api/scheduled-prompts/{id}/run-now | member | — | `{run_id, status}` (synchronous if fast, otherwise 202 with poll link) | 200/202 |
| GET | /api/scheduled-prompts/{id}/log?limit=10 | member | — | `{entries: [{executed_at, success, error_message?, response_snippet?}]}` (reads `bh_hook_log`) | 200 |


## Backend Services and Modules

New Python modules added under `backend/services/` and `backend/routers/`. All follow the existing module conventions (asyncpg pool from `backend.database.get_pool`, pydantic models in `backend/models/`, FastAPI routers registered in `backend/main.py`).

### `backend/services/theme_resolver.py`

Resolves the active theme for a user using the priority order from R3.7: user override (`bh_users.settings_json.theme_id`) → platform default (`bh_platform_settings.default_theme_id`) → built-in `Dark Navy` preset. The resolver returns the full `tokens_json`. It is the only path the frontend uses to discover which theme to render. Stale references (theme deleted) fall through to the next entry — so user-visible behavior matches R3.8 without raising errors. This module is the implementation surface for property test §13-1.

### `backend/services/theme_validator.py`

Validates a `tokens_json` payload before insert/update. Two responsibilities:
1. Hex token validation: every value matches `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`. (Property test §13-2)
2. Contrast ratio computation between `text` and `background` using the WCAG relative-luminance formula. Returns `ok` / `warn` / `block` per the thresholds in R1.7 / R1.8. (Property test §13-3)

Both pure functions, no I/O. Reused by both the admin theme endpoint and the personal theme builder endpoint.

### `backend/services/branding_store.py`

Manages the on-disk `/files/branding/` directory:
- `upload_icon(file)`: validates (mime/dim/size), invokes Pillow to generate the 192px and maskable-512px variants (12% inner padding for the safe zone, matching `scripts/generate_icons.py`), atomically swaps the active set, moves the previous active set into the rollback slot.
- `revert_to_default()`: replaces the active set with built-ins generated by the existing `scripts/generate_icons.py`. Preserves the rollback slot.
- `rollback()`: swaps `active` ↔ `previous`. No-op (409 to caller) if `previous` is empty.
- `get_manifest()`: returns the current versioned manifest URLs.

The icon validator is the implementation surface for property test §13-4.

### `backend/services/text_size_resolver.py`

A trivial pure module that maps `settings_json.text_size` ∈ {`small`, `medium`, `large`, `extra_large`} to a multiplier. Unknown values fall through to `medium` (R4.6). Implementation surface for property test §13-5.

### `backend/services/scheduled_prompts.py`

A thin facade over `bh_hooks` that:
- Exposes the CRUD shape the frontend wants (name, prompt_template, schedule, delivery_method) without leaking the full hook engine model.
- Validates cron expressions on save using `croniter.is_valid()` (R11.11).
- Translates `delivery_method` ∈ {`pin`, `pushover`} into the appropriate `action_config` JSON for the existing `call_ai` hook handler.
- Implements `run_now(id)` by calling `hook_engine._execute_hook(hook, context)` directly with a synthetic context.

This module never duplicates hook_engine logic — it only owns the API translation. Cron validation is the implementation surface for property test §13-9.

### `backend/services/hook_engine.py` (extension)

The existing `_execute_hook` action dispatcher already handles `call_ai`. We extend it so that for `action_type='call_ai'` with `action_config.delivery_method` set, the result is routed:
- `delivery_method='pin'`: insert a `system` message into `bh_messages` for the workspace's primary conversation with `metadata = {pinned: true, scheduled_prompt_id: hook.id}` (R11.5).
- `delivery_method='pushover'`: call the existing `notifications.send_pushover()` helper, truncating the message to 1000 chars and appending a deep-link to the workspace (R11.6, property test §13-10).

The cron path itself is unchanged — APScheduler is already wired up — so a hook with a valid cron will fire on each matching tick exactly once (property test §13-9).

### `backend/services/briefing_summary.py`

A small parser used by the morning card to split the briefing markdown produced by `BriefingService.generate()` into sections. The briefing prompt already produces well-formed sections labeled with `**Weather:**`, `**Yesterday's Spending:**`, etc. (see `briefing.py`). This module:
- Extracts each section and returns `[{key, label, content}]`.
- Inserts a `—` placeholder for any expected section that the briefing omitted (R8.7).

### `backend/routers/themes.py`

Routes for `/api/themes/*`. Wraps `theme_resolver`, `theme_validator`, and DB CRUD. RBAC enforced via `Depends(require_admin)` on publish/delete-of-NULL-owner endpoints; otherwise a per-row owner check (admin OR `owner_id == user.id`).

### `backend/routers/branding.py`

Routes for `/api/branding/icon/*`. Multipart upload, JSON for the rest. Writes the audit log entry for icon changes.

### `backend/routers/settings.py`

Routes for `/api/settings`. Read returns the user's `settings_json` plus a resolved `effective_theme` (so the frontend doesn't need to do the priority dance) and `effective_text_size`. Write merges partial keys into `settings_json` with JSON-patch semantics.

### `backend/routers/quick_capture.py`

Three thin endpoints that pass through to the existing `smart-capture-extract` and `smart-capture-commit` skills via `skill_executor.execute()`, plus the raw-note fallback (R9.9). Permission inheritance: the request runs in the user's current workspace context — skill availability is enforced by `skill_executor`'s existing checks.

### `backend/routers/scheduled_prompts.py`

Routes for `/api/scheduled-prompts/*`. Wraps `scheduled_prompts.py`. Reads from `bh_hooks` and `bh_hook_log`; writes only to `bh_hooks`. Filters list endpoints to workspaces the caller has access to.

### `backend/routers/briefing.py`

Routes for `/api/briefing/*`. `GET /latest` queries `bh_messages` for the most recent system message tagged `metadata.briefing=true` in the user's morning-card workspace (or `General`). `POST /generate-now` calls `BriefingService.generate()` and persists the result.

## Frontend Components

All new components live under `frontend/src/components/` and `frontend/src/pages/`. Style and conventions match the existing components (see `Sidebar.tsx`, `ChatArea.tsx`): TailwindCSS utility classes, Zustand for cross-cutting state, hand-rolled hooks for non-trivial side effects.

### Settings page refactor — `pages/SettingsPage.tsx`

Becomes a section-based layout matching R12.1. Sections mounted in order: Profile, Appearance, Voice, Notifications, Briefing, Context Capture, Scheduled Prompts. The existing `SettingsPage.tsx` is kept as the shell; each section is a child component so the file stays small.

### `components/AppearancePanel.tsx`

Owns the Appearance section. Reads `effective_theme` and `effective_text_size` from the new `useSettingsStore()` Zustand store, renders the theme grid + text-size buttons + "Build a custom theme" link. Calls `PATCH /api/settings` on every change. Props: none. State: optimistic `pendingThemeId` for instant feedback.

### `components/ThemeBuilder.tsx`

Modal/page (mobile: full screen, desktop: centered modal) with one color picker per token. Inputs are HTML `<input type="color">` plus a paired hex text field for direct entry. Live preview shows a fake chat message (user + assistant) with a sample sidebar fragment. Props: `themeId?: number`, `onSave: (theme) => void`, `onClose: () => void`. State: working tokens, contrast badge (live `ok | warn | block`).

### `components/IconUploader.tsx`

Renders the current 192/512 icons side-by-side with an upload control and rollback button. Validates file client-side (size, dim) before upload. Props: none. Reads from `useBrandingStore()`. After upload, bumps the manifest version and triggers a service-worker update notification.

### `components/WorkspaceSettingsPanel.tsx`

Right-side or modal panel that opens from the workspace settings cog. Tabs: System Prompt, Pinned Context. Mounts `<SystemPromptViewer>` / `<SystemPromptEditor>` and `<PinnedContextManager>`. Props: `workspaceId`, `mode: 'view' | 'edit'`.

### `components/SystemPromptViewer.tsx` and `SystemPromptEditor.tsx`

Viewer: read-only markdown render of `bh_workspaces.system_prompt`, plus character/token counter (R5.5). Editor: side-by-side textarea + preview, debounced 300ms (R6.3), Save/Cancel with confirm-on-discard. Reuses the same markdown renderer the chat already uses (`react-markdown` + rehype). Props: `workspaceId`, `initialPrompt`, `canEdit`.

### `components/PinnedContextManager.tsx`

List + add/edit form for the workspace's pinned-context entries. Renders entries with title, type badge, priority, token estimate, and (for dynamic) last refresh timestamp. Click expands to full content / SQL / cached result. Add/edit form fields per R7.3. Refresh-now button on dynamic entries calls `POST .../{eid}/refresh`. Running token total at the top with the 75%-of-budget warning (R7.8). Props: `workspaceId`, `canEdit`.

### `components/MorningCard.tsx`

Renders at the top of `ChatArea` when `activeWorkspace.id === settings.morning_card_workspace_id`. Fetches `GET /api/briefing/latest`. If `briefing_id == null`, shows a "Generate today's briefing" button that calls `POST /api/briefing/generate-now`. If present, renders the parsed sections with icons (☀ weather, 💸 spending, 📥 inbox, 📅 schedule, ✨ anything else) and a close button. Dismissal stored in `localStorage` keyed by `morning-card-dismissed:<YYYY-MM-DD>`. Props: `workspaceId`. State: `briefing`, `dismissed`.

### `components/QuickCaptureOverlay.tsx`

Modal triggered by `Ctrl+Shift+K` (or `Cmd+Shift+K`) from a global keyboard handler in `App.tsx`, or by navigating to `/quick-capture` (PWA share target). Single textarea, image attach button, Save/Cancel. After Save → calls `/api/quick-capture/extract`, shows extracted intents in a confirm sub-view, then `/api/quick-capture/commit` per accepted intent. Toast on success. On extract failure, shows Retry + "Save as raw note" (R9.9). Props: `initialText?`, `initialImage?` (for share-target pre-population).

### `components/VoiceModeButton.tsx` and `hooks/useVoiceMode.ts`

`VoiceModeButton` lives next to the send button in `InputArea.tsx`. The hook owns the lifecycle:
- `start()`: calls `navigator.mediaDevices.getUserMedia({audio:true})` (for permission), then instantiates `webkitSpeechRecognition` / `SpeechRecognition`. Streams `onresult` partials into the input field.
- Pause detection: 2-second silence (configurable) auto-finalizes and submits unless `manual_send` is on.
- TTS: subscribes to assistant message stream events, chunks the prose, calls `SpeechSynthesisUtterance` per chunk. Strips fenced code blocks, markdown tables, and inline images, replacing them with verbal placeholders ("code block omitted", "table omitted") — the implementation surface for property test §13-7.
- `stop()`: aborts `SpeechRecognition` and cancels any speaking utterance.
- Capability detection: `'SpeechRecognition' in window || 'webkitSpeechRecognition' in window`. If false, the button is hidden and a one-time toast fires (R10.8).

### `pages/ScheduledPromptsPage.tsx`

Standalone route at `/scheduled-prompts`. Lists all scheduled prompts the user has access to, with columns: name, workspace, schedule (human-readable cron via `cronstrue`), delivery method, enabled toggle, last run status, actions (Edit, Run Now, Disable, Delete). Click a row to expand its last-10 log entries. "New scheduled prompt" button opens a form panel with cron input, friendly preset picker ("every day at X", "weekly on Y at X", "monthly on day Z at X" → translated to cron client-side), and delivery-method radio.

### `pages/AdminConsolePage.tsx`

Replaces the existing `AdminPanel.tsx` as the entry. Sidebar navigation with sections: Users, Skills, Hooks, Cost, Workspaces (existing), plus Theme Management and Icon Management (new). Each section is a child route. Visible only to admins (R12.5); non-admin sees "Settings" without the Admin entry.

### `stores/settings.ts` (new Zustand store)

```typescript
interface SettingsStore {
  settings: UserSettings;          // raw settings_json
  effectiveTheme: Theme;           // resolved by backend
  effectiveTextSize: TextSize;     // resolved by backend
  loadSettings: () => Promise<void>;
  patch: (delta: Partial<UserSettings>) => Promise<void>;
}
```

### `stores/branding.ts` (new Zustand store)

Caches `{version, urls, has_rollback}` and exposes `refresh()`, called after every icon mutation.

## CSS Theming Approach

The current frontend uses TailwindCSS plus three CSS custom properties on `:root` (`--color-surface`, `--color-surface-light`, `--color-surface-dark`). The enhancement extends this approach without changing Tailwind's compile-time model.

### Step 1: token application at runtime

When `useSettingsStore.loadSettings()` returns the resolved `effective_theme`, a `useEffect` in `App.tsx` writes every token from `tokens_json` onto `:root` as a CSS custom property:

```javascript
// App.tsx (sketch)
useEffect(() => {
  const root = document.documentElement;
  const t = effectiveTheme.tokens_json;
  root.style.setProperty('--color-background', t.background);
  root.style.setProperty('--color-surface', t.surface);
  root.style.setProperty('--color-primary', t.primary);
  root.style.setProperty('--color-accent', t.accent);
  root.style.setProperty('--color-text', t.text);
  root.style.setProperty('--color-text-muted', t.text_muted);
  root.style.setProperty('--color-border', t.border);
  root.style.setProperty('--color-danger', t.danger);
  root.style.setProperty('--color-success', t.success);
}, [effectiveTheme]);
```

Theme switches happen instantly (no reload, R3.2) because every styled element references the custom property, not a hard-coded color.

### Step 2: Tailwind token mapping

`tailwind.config.ts` is updated so the `surface` and `brand` colors point at the new custom properties. This keeps all existing utility classes (`bg-surface`, `text-brand-500`, etc.) working unchanged:

```typescript
// tailwind.config.ts (extended)
extend: {
  colors: {
    background: 'var(--color-background)',
    surface: {
      DEFAULT: 'var(--color-surface)',
      light: 'var(--color-surface-light)',  // kept for backward compat; unset means same as surface
      dark: 'var(--color-surface-dark)',
    },
    primary: 'var(--color-primary)',
    accent: 'var(--color-accent)',
    text: {
      DEFAULT: 'var(--color-text)',
      muted: 'var(--color-text-muted)',
    },
    border: 'var(--color-border)',
    danger: 'var(--color-danger)',
    success: 'var(--color-success)',
    // existing brand-50..brand-900 retained for chat send button etc., to be migrated in a later pass
  }
}
```

A small follow-up pass replaces hard-coded colors in components (e.g., `bg-[#0f0f1a]` in `Sidebar.tsx`) with the new utility classes. This is mechanical and tracked as a task, not a design concern.

### Step 3: text size cascade

Text size only affects chat content (R4.4), so the cascade is rooted on a single wrapper. `MessageList.tsx` mounts inside a `<div className={textSizeClass}>` where `textSizeClass` is one of:

```css
.bh-text-small      { font-size: 0.875rem; }
.bh-text-medium     { font-size: 1rem; }       /* default; same as body */
.bh-text-large      { font-size: 1.125rem; }
.bh-text-xlarge     { font-size: 1.25rem; }
```

All chat content elements (user bubbles, assistant markdown, code blocks) use `font-size: inherit` or `1em`-relative sizes, so they scale with the wrapper. UI chrome (sidebar, headers, buttons) lives outside this wrapper and remains fixed-size. `useEffect` in `MessageList.tsx` chooses the class from `useSettingsStore().effectiveTextSize`.

## Branding Asset Storage

### Directory layout

```
/files/branding/
├── active/                              # served at /icons/* (FastAPI static mount)
│   ├── icon-192.png
│   ├── icon-512.png
│   └── icon-maskable-512.png
├── previous/                            # single rollback slot (R2.7)
│   ├── icon-192.png
│   ├── icon-512.png
│   └── icon-maskable-512.png
├── history/                             # optional; admin can clear
│   └── 2026-05-28T22-13-02_icon-set/    # timestamped sets, kept for forensic recovery
│       └── …
└── manifest.json                        # versioned manifest emitted on every change
```

The `previous/` directory holds exactly one set at a time. Uploading a new icon moves the current `active/` into `previous/` (after first archiving the existing `previous/` into `history/<timestamp>/`).

### Versioning

`bh_platform_settings` row `app_icon_version.version` holds a string timestamp (Unix epoch, e.g., `"1717000000"`). On every icon change (upload, revert, rollback), `branding_store` updates this value. The frontend uses it in two places:

1. The PWA manifest at `/manifest.json` is generated dynamically by FastAPI: each icon URL gets `?v=<version>` appended.
2. The HTML `<link rel="icon">` tag in `index.html` uses `<link rel="icon" href="/icons/icon-192.png?v={version}">` — which means the version string is interpolated server-side before sending the index.

This pattern keeps the icon URL paths under `/icons/` stable (R2.5) while forcing browsers and installed PWAs to refetch when the underlying bytes change (R2.4).

### Built-in fallback

`scripts/generate_icons.py` already exists and produces the dark-navy + indigo-ring + white "B" monogram set. `branding_store.revert_to_default()` invokes it (in-process, not as a subprocess) writing into a `default/` folder, then symlink-swaps `active/` to point at it. The `default/` folder is kept on disk so revert is fast and idempotent.

### Rollback semantics

- Upload N: `active/` → `history/<ts>/`, `previous/` becomes the rolled-out version, new bytes go to `active/`. (Edge case on first upload: `previous/` was empty → it stays empty after archive of nothing.)
- Rollback: `active/` ↔ `previous/` swap. After rollback, `previous/` contains what was just live; calling rollback again toggles back. (See property test §13-… handled implicitly by upload validator + version sequencing; we keep rollback as an example test rather than a full PBT to avoid over-engineering.)
- Revert to default: `active/` ← copy of `default/`. `previous/` is preserved unchanged so the admin can still rollback to the immediately-prior custom icon if they regret reverting.

## Quick Capture Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  Trigger (one of):                                                    │
│   1. Ctrl+Shift+K (or Cmd+Shift+K) anywhere in the app                │
│   2. /quick-capture route invoked by Web Share Target on Android      │
│      (manifest entry below pre-fills initialText / initialImage)      │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │   <QuickCaptureOverlay />             │
                │   inputs: textarea, image attach      │
                └──────────────────────────────────────┘
                                   │  Save
                                   ▼
                ┌──────────────────────────────────────┐
                │  POST /api/files/upload (if image)    │
                │  → returns asset_id, image_path       │
                └──────────────────────────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │  POST /api/quick-capture/extract      │
                │  body: {text?, image_path?, ws_id}    │
                │  → smart-capture-extract via          │
                │    skill_executor                     │
                │  ← {intents, asset, extract_token}    │
                └──────────────────────────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │  Confirm UI: list intents, user       │
                │  toggles which to keep                │
                └──────────────────────────────────────┘
                                   │  Confirm
                                   ▼
                ┌──────────────────────────────────────┐
                │  for each accepted intent:            │
                │    POST /api/quick-capture/commit     │
                │    body: {domain, payload, asset_id?, │
                │           extract_token, ws_id}       │
                └──────────────────────────────────────┘
                                   │
                                   ▼
                ┌──────────────────────────────────────┐
                │  Toast: "Saved 1 knowledge note,      │
                │          1 shopping list item"        │
                │  Overlay closes                        │
                └──────────────────────────────────────┘
```

### Web Share Target manifest entry

Added to the existing `manifest.json`:

```json
{
  "share_target": {
    "action": "/quick-capture",
    "method": "POST",
    "enctype": "multipart/form-data",
    "params": {
      "title": "title",
      "text": "text",
      "url": "url",
      "files": [
        { "name": "files", "accept": ["image/*"] }
      ]
    }
  }
}
```

A small route handler in the React Router catches `POST /quick-capture` (handled in the service worker for share-target navigations on Chrome Android, then re-dispatched to the SPA route), reads the multipart form data, and mounts `<QuickCaptureOverlay initialText={text} initialImage={files[0]} />`.

### Failure handling

`POST /api/quick-capture/extract` returning a non-200 (n8n down, smart-capture errored) makes the overlay show "Retry" and "Save as raw note". "Save as raw note" calls `POST /api/quick-capture/raw-note` which writes to `/knowledge/captures/<slug>.md` via filewriter — never invoking the AI path (R9.9).


## Voice Mode Flow

### Capability detection

On `App.tsx` mount, `useVoiceMode` checks for the API surfaces:

```typescript
const supported =
  ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) &&
  'speechSynthesis' in window;
```

If `supported === false`, `<VoiceModeButton>` returns `null` and a one-time toast fires (R10.8). The capability flag is exposed to settings UI as a read-only badge.

### Recognition lifecycle

```
[user clicks mic] → start()
   │
   ├─→ getUserMedia({audio:true})  // permission prompt only on first use
   │
   ├─→ recognition = new SpeechRecognition()
   │     recognition.continuous = true
   │     recognition.interimResults = true
   │     recognition.lang = navigator.language
   │
   ├─→ onresult: append finalized transcript to input field;
   │              show interim transcript in lighter color
   │
   ├─→ silence timer: reset on every result event
   │     - if elapsed > settings.voice.auto_submit_pause_ms
   │       AND not settings.voice.manual_send
   │       → finalize + submit
   │
   └─→ [user clicks mic again] → stop()
       recognition.stop()
       finalize current transcript without auto-submit (R10.6)
```

### TTS lifecycle (output)

When `settings.voice.output_enabled === true`, the hook subscribes to the streaming WebSocket `token` events. Tokens are accumulated into a buffer; the buffer is segmented into "speakable chunks" by walking the streamed markdown:

1. Detect fenced code block boundaries (` ``` `). Inside a code block, no speech — replace the entire region with `"code block omitted"`.
2. Detect markdown table rows (`^\\|.*\\|$` for two or more consecutive lines). Replace with `"table omitted"`.
3. Detect inline images (`!\[alt\](url)`) — replace with `"image: <alt>"` if alt is non-empty, else `"image omitted"`.
4. Everything else is passed to `SpeechSynthesisUtterance` with `voice = settings.voice.voice_name` and `rate = settings.voice.speech_rate`.

This transformation is the implementation surface for property test §13-7.

The stop-speaking button (R10.7) calls `window.speechSynthesis.cancel()`.

### Settings persistence

```typescript
interface VoiceSettings {
  output_enabled: boolean;        // default true
  voice_name: string;              // default ""  (uses platform default)
  speech_rate: number;             // default 1.0 (range 0.5–2.0)
  auto_submit_pause_ms: number;    // default 2000
  manual_send: boolean;            // default false
}
```

Stored under `bh_users.settings_json.voice`. Read/write is round-trip safe (property test §13-… implicit; not enumerated separately).

### Privacy invariant

Audio data never leaves the browser (R10.10). The browser-only APIs return text, not audio. Property test §13-8 enforces this by mocking `fetch` and `WebSocket.send` and asserting no call body has a MIME type starting with `audio/`.

## Scheduled Prompts Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  ScheduledPromptsPage: user fills in form                            │
│   {name, workspace_id, prompt_template, cron_expression,             │
│    delivery_method ∈ {pin, pushover}}                                 │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
       ┌─────────────────────────────────────────────────────────┐
       │  POST /api/scheduled-prompts                             │
       │   - validate cron via croniter.is_valid(expr)             │
       │   - INSERT bh_hooks (event_type='schedule',               │
       │       action_type='call_ai',                              │
       │       cron_expression=expr,                               │
       │       action_config={                                      │
       │         prompt: prompt_template,                           │
       │         model: 'claude-haiku-4-5-20251001',                │
       │         delivery_method: 'pin' | 'pushover',               │
       │         workspace_id: ws.id                                │
       │       },                                                    │
       │       is_enabled=true)                                     │
       │   - hook_engine.register_schedule(hook)                    │
       └─────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (some time later)
       ┌─────────────────────────────────────────────────────────┐
       │  APScheduler tick fires → hook_engine._execute_hook()     │
       │   - build RoutingContext from action_config.workspace_id  │
       │   - invoke router_engine in "system-prompt-only" mode:    │
       │       same path as a regular Layer-3 message but          │
       │       message = action_config.prompt;                     │
       │       conversation_id = workspace primary conversation;   │
       │       force_model = action_config.model                   │
       │   - capture full assistant response                        │
       └─────────────────────────────────────────────────────────┘
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
              ┌─────────────────┐  ┌─────────────────────┐
              │  delivery=pin   │  │  delivery=pushover  │
              │  INSERT system  │  │  notifications.     │
              │  message into   │  │   send_pushover(    │
              │  workspace      │  │     truncate(resp,  │
              │  primary conv,  │  │       1000),        │
              │  metadata = {   │  │     url=ws_link)    │
              │    pinned: true,│  └─────────────────────┘
              │    scheduled_   │
              │    prompt_id:   │
              │    hook.id      │
              │  }              │
              └─────────────────┘
                          │
                          ▼
              ┌─────────────────────────────────────────────────┐
              │  bh_hook_log: insert {hook_id, success, error?, │
              │                       result_snippet, timestamp}│
              └─────────────────────────────────────────────────┘
```

### "System-prompt-only invocation context"

The router_engine is reused, not duplicated. The cron path constructs the same `RoutingContext` as a normal user message, but skips Layers 1 and 2 — scheduled prompts always run on the workspace's default model with full system prompt + pinned context, since the user's intent is "act on this fresh, with all the context the workspace usually gets". The only differences from a user-driven message:

- `context.user_id` is set to the hook's `created_by` user
- `conversation_id` is the workspace's primary conversation (auto-created if missing)
- `context.skip_capture = true` (don't run `context_capture` on the assistant's reply — these messages aren't conversational facts)
- `context.is_scheduled = true` (used for cost-attribution and to suppress UI streaming notifications to other connected sessions)

### Run Now

`POST /api/scheduled-prompts/{id}/run-now` calls `hook_engine._execute_hook(hook, context)` directly with a synthetic context, bypassing the cron tick. Result is reported synchronously if it returns within 30s, otherwise a 202 with a poll link.

## Pinned Context UI Integration

The custom-chat-app spec already defines the pinned-context endpoints (R15) and they are already implemented. This spec adds only the UI. The contract the UI relies on:

```
GET /api/workspaces/{id}/pinned-context
→ 200 {
    entries: [
      {
        id: number,
        type: 'static' | 'dynamic',
        title: string,
        content: string | null,                // for static
        query: string | null,                  // for dynamic
        refresh_minutes: number | null,        // for dynamic
        cached_result: string | null,          // for dynamic, last-rendered text
        cached_at: string | null,              // ISO8601
        priority: number,                      // lower = included first
        token_estimate: number
      }
    ],
    total_token_estimate: number,
    budget: number                             // workspace pinned-context budget (default 2000)
  }

POST /api/workspaces/{id}/pinned-context
body: { type, title, content?, query?, refresh_minutes?, priority }
→ 201 (entry row)

PATCH /api/workspaces/{id}/pinned-context/{eid}
body: partial fields above
→ 200 (entry row)

DELETE /api/workspaces/{id}/pinned-context/{eid}
→ 200 { deleted: true }

POST /api/workspaces/{id}/pinned-context/{eid}/refresh    (NEW — added by this spec)
→ 200 { cached_result, cached_at, token_estimate }
→ 400 if entry is type='static'
```

The "Refresh now" interaction:

1. UI shows a spinner on the entry row.
2. UI calls `POST .../refresh`.
3. Server re-executes the SQL against the workspace's permitted schemas (using the existing schema-guard logic from custom-chat-app), updates `cached_result`, `cached_at`, and recomputes `token_estimate`.
4. Server returns the updated row; UI replaces the entry inline.
5. Total token estimate at the top updates; if it crosses 75% of budget, a yellow warning banner appears (property test §13-6).

Errors during refresh (SQL invalid, schema not permitted) return 400 with `{detail}` and the UI shows the error inline next to the entry without modifying the cached value.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Theme resolution priority is total and stable

For any combination of `(user_override_id, platform_default_id, deleted_id_set)`, where each id may be present, absent, or refer to a row in `deleted_id_set`, `theme_resolver.resolve(user)` returns the highest-priority theme not in `deleted_id_set`, falling through `user_override → platform_default → built-in 'Dark Navy'` in that order. The function never raises.

**Validates: Requirements 1.3, 1.9, 3.7, 3.8, 4.6**

### Property 2: Hex token validator accepts exactly the hex grammar

For any string `s`, `theme_validator.is_valid_hex(s)` returns true iff `s` matches `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`. Generators MUST include leading-`#`/no-`#` variants, mixed-case, and near-misses (5/7/9 chars, non-hex characters, leading whitespace).

**Validates: Requirement 1.6**

### Property 3: Contrast threshold decision is monotonic and symmetric

For any pair of valid hex colors `(text, background)`, `theme_validator.contrast_decision(text, background)` returns `'block'` iff the WCAG relative luminance ratio is below 2.0, `'warn'` iff in `[2.0, 4.5)`, and `'ok'` iff `≥ 4.5`. The function is symmetric: `decision(a, b) == decision(b, a)`.

**Validates: Requirements 1.7, 1.8**

### Property 4: Icon upload validator accepts exactly the published rules

For any tuple `(mime, width, height, size_bytes)`, `branding_store.validate_icon(mime, width, height, size_bytes)` returns ok iff `mime == 'image/png'` AND `min(width, height) ≥ 512` AND `abs(width - height) / max(width, height) ≤ 0.01` AND `size_bytes ≤ 4_194_304`. All other inputs return a typed error with a per-rule message.

**Validates: Requirements 2.2, 2.3**

### Property 5: Text size resolver is total and falls back to medium

For any string `s`, `text_size_resolver.resolve(s)` returns `('small', 0.875)` iff `s == 'small'`; `('large', 1.125)` iff `s == 'large'`; `('extra_large', 1.25)` iff `s == 'extra_large'`; and `('medium', 1.0)` for every other input including `null`, `undefined`, integers, and arbitrary strings.

**Validates: Requirements 4.1, 4.6**

### Property 6: Pinned context budget warning matches the threshold

For any list `L` of non-negative token estimates and any positive `budget`, the UI predicate `should_warn(L, budget) == (sum(L) > 0.75 * budget)`. The function never raises on empty lists or zero budget (returns false).

**Validates: Requirement 7.8**

### Property 7: Morning card visibility follows the truth table

For any `(briefing_age_hours, dismiss_set, current_date_iso)` where `dismiss_set` is a set of YYYY-MM-DD strings, `morning_card.is_visible(briefing_age_hours, dismiss_set, current_date_iso) == (briefing_age_hours < 24 AND current_date_iso ∉ dismiss_set)`.

**Validates: Requirements 8.1, 8.5, 8.6**

### Property 8: TTS markdown stripping preserves prose and elides code/tables/images

For any markdown document `m`, let `s = tts_strip(m)`. Then:
- For every fenced code block region in `m`, no character of that region's body appears in `s`.
- For every contiguous markdown table region in `m`, no row of that region appears in `s`.
- For every inline image `![alt](url)` in `m`, the URL does not appear in `s`.
- The substring `"code block omitted"` appears in `s` iff `m` contained at least one fenced code block.
- The substring `"table omitted"` appears in `s` iff `m` contained at least one markdown table.
- For prose regions outside of code/table/image, the original characters appear in `s` in their original order.

**Validates: Requirement 10.5**

### Property 9: Voice mode never emits audio over the network

For any sequence of voice-mode UI events (start, partial result, finalize, submit, stop, TTS speak), no `fetch`, `XMLHttpRequest`, or `WebSocket.send` call carries a body with MIME type `audio/*` or a binary blob produced by `MediaRecorder`. Implementation: a network-mock guard fails the test if any request body matches.

**Validates: Requirement 10.10**

### Property 10: Cron expression validator agrees with croniter

For any string `s`, `scheduled_prompts.validate_cron(s) == croniter.is_valid(s)`. The function never raises.

**Validates: Requirement 11.11**

### Property 11: Scheduled prompt fires once per matching tick

Under a virtual clock, for any valid cron expression `c` and any time range `[t0, t1]`, `count(hook_engine.fires(hook(c), t0, t1)) == count(croniter(c).get_next_in_range(t0, t1))`. No duplicate fires; no missed fires within the range.

**Validates: Requirement 11.4**

### Property 12: Pushover delivery truncates to 1000 chars and includes workspace link

For any string `response_text` and any workspace `ws`, `pushover_payload(response_text, ws)` returns `{message, url}` where `len(message) ≤ 1000` AND `url` deep-links into `ws` (via the existing `https://595bowershub.tailc4d58a.ts.net/workspace/<ws.id>` route).

**Validates: Requirement 11.6**

### Property 13: settings_json.theme_id is always resolvable or absent

For any sequence of operations on `bh_users.settings_json.theme_id` and `bh_themes` (theme creation, deletion, ownership changes) followed by `theme_resolver.resolve(user)`, the resolver returns a theme that is visible to the user (per property §1) or the built-in fallback. The resolver never returns a theme owned by a different user.

**Validates: Requirements 3.5, 3.7**


## Error Handling

The platform uses FastAPI's exception model with a small set of typed errors mapped to HTTP status codes:

- `ThemeValidationError` → 400 (with per-token field error messages, R1.6)
- `ContrastBlockError` → 422 (text/background contrast below 2.0, R1.8)
- `IconValidationError` → 400 or 413 (size/dim/mime, R2.3)
- `PermissionDeniedError` → 403 (theme owned by different user, non-admin updating system_prompt, etc.)
- `CronValidationError` → 400 with the croniter error message (R11.11)
- `BriefingDataError` → 200 with the briefing rendered using whatever data succeeded (R16.7 in custom-chat-app, mirrored here)
- `SmartCaptureFailureError` → bubbled through `/api/quick-capture/extract` as 502 with `{retryable: true}`

Frontend error handling:

- All `4xx` responses are surfaced as inline error toasts using the existing toast system; the offending field is highlighted where applicable.
- Network failures (5xx, timeouts) show a generic "Something went wrong, try again" toast and log details to the console for debugging.
- The morning card and quick-capture overlay tolerate partial failure: morning card renders missing sections with `—`, quick capture offers "Save as raw note" when extract fails.
- Voice mode permission denial (mic blocked) shows a clear message and stays in TTS-only mode if `output_enabled` is true.

## Testing Strategy

### Dual approach

This feature spans pure logic (theme resolution, validation, parsing) and side-effect-heavy UI/IO (icon upload, hook firing, voice APIs). The strategy reflects this:

**Unit tests (example-based)** — used for:
- UI rendering: AppearancePanel, ThemeBuilder, MorningCard, QuickCaptureOverlay, ScheduledPromptsPage component tests via React Testing Library + mocked stores.
- Endpoint smoke tests: each new endpoint invoked once with valid input and once with invalid input, asserting correct status code and body shape.
- RBAC: each endpoint invoked with admin / member / unauthenticated tokens, asserting expected status codes.
- Migration tests: `009_themes_and_branding.sql` applied to a clean DB produces the 4 preset rows with the expected slugs and default platform setting.
- Web Share Target manifest: read built `manifest.json`, assert `share_target` field shape.

**Property-based tests** — used for the 13 properties above. Each property test runs at minimum 100 iterations.

### Property test configuration

- Library: `hypothesis` for Python (backend pure functions); `fast-check` for TypeScript (frontend pure functions like `tts_strip`, `morning_card.is_visible`, `text_size_resolver.resolve`).
- Iterations: minimum 100 per property test.
- Each test is tagged with: `Feature: bowershub-ai-enhancements, Property {N}: {title}`.
- Generators follow the spec: hex strings (with deliberate near-misses), markdown documents (with fenced blocks/tables/images interleaved with prose), cron expressions (mix of valid and invalid), file size/dim tuples bracketing the published thresholds.

### Integration tests (1–3 examples each)

- Icon upload pipeline end-to-end: real PNG → Pillow generates 192/maskable variants → files appear under `/files/branding/active/` → `GET /icons/icon-192.png` returns 200.
- Scheduled prompt cron firing: insert a hook with `* * * * *`, fast-forward virtual clock by 3 minutes, assert 3 entries in `bh_hook_log`.
- Quick capture happy-path: extract → confirm → commit, asserting the smart-capture webhooks were called with the right shape (using a mocked n8n).

### Smoke tests

- Migration applies on container startup without error.
- All four preset themes render in the Appearance panel.
- The new manifest.json is reachable and contains the share_target field.

### What is NOT property-tested (and why)

- **TTS audio output**: SpeechSynthesis is a browser API; we only test the text it receives (covered by Property 8). The audio itself is unobservable without a real audio device.
- **STT recognition accuracy**: the platform doesn't own the recognition logic — Web Speech API is the spec.
- **Pillow image fidelity**: trusted dependency. We test that variants are produced with the right dimensions, not that pixel content matches a reference.
- **APScheduler internals**: trusted dependency. Property 11 tests our hook_engine integration, not the scheduler library.
- **n8n webhook responses**: external service. Quick capture flow is integration-tested with a mocked endpoint.

## Migration Strategy

Migrations are appended in numeric order. The existing migration runner (`backend/migrations/`, applied automatically on startup, tracked in `bh_migrations`) handles the ordering. Two new files for this feature:

### `009_themes_and_branding.sql`

Creates `bh_themes` and `bh_platform_settings` tables. Seeds:
- 4 preset rows in `bh_themes` (`is_preset=true`, `owner_id=NULL`):
  - **Dark Navy** — slug `dark-navy`, the current default tokens (background `#0f0f1a`, surface `#1a1a2e`, primary `#6366f1`, etc.)
  - **Light Stone** — slug `light-stone`, light mode (background `#f8f7f4`, surface `#ffffff`, primary `#4f46e5`, text `#1f2937`)
  - **Forest** — slug `forest`, green-on-dark (background `#0f1f17`, primary `#22c55e`)
  - **Mono** — slug `mono`, grayscale (background `#000000`, primary `#ffffff`, text `#e5e7eb`)
- 4 rows in `bh_platform_settings`: `default_theme_id` → `dark-navy`'s id, `app_icon_version` → current epoch timestamp, `app_icon_active_filename` → `"icon-set-default"`, `app_icon_previous_filename` → `null`.

No data backfill needed; existing users without `settings_json.theme_id` will resolve to the platform default automatically (Property 1).

### `010_settings_json_keys.sql`

Comment-only / no-op migration that documents the new `settings_json` keys for future maintainers. Does not alter any rows. Body:

```sql
-- Documentation-only migration: bh_users.settings_json keys added by the
-- bowershub-ai-enhancements spec. No DDL/DML.
--
-- Keys (all optional):
--   theme_id                       integer, references bh_themes.id
--   text_size                      'small' | 'medium' | 'large' | 'extra_large'
--   morning_card_workspace_id      integer, references bh_workspaces.id
--   morning_card_disabled          boolean
--   voice                          { output_enabled, voice_name, speech_rate,
--                                    auto_submit_pause_ms, manual_send }
--
-- Resolvers in backend.services tolerate missing/unknown values and never raise.
SELECT 1;
```

### Rollback notes

- `009` is reversible by `DROP TABLE bh_themes; DROP TABLE bh_platform_settings;` if needed during dev. Production rollback is not planned.
- Adding new keys to `settings_json` is non-destructive; old keys remain untouched.

### Sequence in the migrations directory after this spec

```
backend/migrations/
├── 001_initial_schema.sql
├── 002_seed_skills.sql
├── 003_seed_workspaces.sql
├── 004_seed_model_rates.sql
├── 005_fix_model_ids.sql
├── 006_builtin_files_command.sql
├── 007_universal_skills.sql
├── 008_rename_finance_query_to_ask_db.sql
├── 009_themes_and_branding.sql            ← new
└── 010_settings_json_keys.sql             ← new
```

## Non-Goals / Out of Scope

To prevent scope creep during implementation, this spec explicitly does NOT cover:

1. **Calendar integration** — the morning card's "schedule" section will render `—` until a calendar skill exists. See custom-chat-app TODO #26.
2. **Server-side speech-to-text** — voice mode is browser-only. No Whisper, no Deepgram, no audio uploads to the backend.
3. **n8n workflow changes** — the smart-capture, send-email, and other existing webhooks are consumed as-is. No edits to `n8n-workflows/build-*.py` files.
4. **AWS Bedrock provider work** — model selection in scheduled prompts uses whatever providers are already configured. Bedrock credentials remain a separate TODO (custom-chat-app TODO #33).
5. **Chart / Mermaid rendering for scheduled prompt outputs** — pin delivery posts the raw markdown response into the workspace conversation. Artifact rendering is governed by the existing `ArtifactDetector` (custom-chat-app design).
6. **Icon set with multiple sizes beyond 192/512** — no Apple touch icons, no favicon ICO, no Microsoft tile XML. Only the three PNGs the existing PWA already uses.
7. **Theme inheritance / nesting** — a theme is a flat map of tokens. No light-mode-vs-dark-mode pairs, no token aliases, no @media query support.
8. **WCAG full audit** — the contrast check covers text-on-background only, not all foreground/background combinations. No automated screen-reader testing.
9. **Internationalization** — UI strings are English. Voice mode uses `navigator.language` for STT but TTS voice list is whatever the browser exposes.
10. **Per-conversation theme overrides** — themes are per-user, not per-conversation or per-workspace.
11. **Voice transcription history** — voice input is transient; nothing about the audio or the partial transcripts is persisted beyond the resulting chat message.
12. **Scheduled prompt template variables** — the prompt is a static string. No `{{date}}`, no `{{user_name}}` interpolation. (Future work if it becomes necessary.)
13. **Multi-tenant icon scoping** — there is one platform-wide icon set, not per-workspace icons.
14. **PWA install banner customization** — relies on the browser's default install prompt.
15. **Auto-rotation of theme/voice keys** when they reference deleted entities — handled at read time by the resolvers, not by background cleanup jobs.

