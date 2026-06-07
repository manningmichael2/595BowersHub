# BowersHub AI

Self-hosted personal AI hub for the 595BowersHub stack. FastAPI backend + React/Vite/Tailwind PWA frontend, packaged as a single Docker container. Runs at `http://100.106.180.101:5003` (HTTP, internal) and `https://595bowershub.tailc4d58a.ts.net` (HTTPS via Caddy reverse proxy on Tailscale).

Key concepts:

- **Three-layer routing** — L1 deterministic patterns / slash commands → L2 Haiku classification → L3 Sonnet with tool use.
- **JWT auth** — 1-hour access + 30-day refresh with rotation. Designed to be the auth layer for the entire ecosystem.
- **Postgres-backed** — 19+ `bh_*` tables in the existing `finance` database.
- **n8n skill integration** — every "skill" is a webhook in the existing n8n stack.
- **Streaming** — chat is streamed over WebSocket.

Source layout:

- `backend/` — FastAPI app, services, websocket handlers, Postgres migrations
- `frontend/` — React 18 + Vite + Tailwind PWA
- `scripts/` — deploy + smoke test helpers
- `Dockerfile` — multi-stage build (frontend → backend → final image)

---

## Changelog

### BowersHub AI Enhancements (this spec) — May 2026

This release adds a large batch of admin controls, personalization features, and proactive surfaces. The feature is **purely additive** — no new env-var requirements, no breaking schema changes for existing data.

**New database tables**

- `bh_themes` — admin-managed theme catalog + per-user override storage
- `bh_platform_settings` — workspace-level system-prompt overrides + branding state
- (Plus extensions to `bh_users` for `theme_id` / `text_size`, and supporting columns on `bh_workspaces`, `bh_user_settings`, `bh_scheduled_prompts`, `bh_briefings`.)

**New backend routers** (mounted under `/api/`)

- `themes` (R1) — admin CRUD on the theme catalog; per-user theme override
- `branding` (R2) — admin icon upload (PNG/SVG validated), rollback to previous icon, dynamic web-manifest generation for PWA cache busting
- `settings` (R3, R4, R5, R6) — per-user theme/text-size persistence and workspace system-prompt editor (admin-only, 50K-character cap)
- `quick-capture` (R9) — Ctrl+Shift+K hotkey overlay backend + Web Share Target ingest endpoint
- `scheduled-prompts` (R11) — cron-triggered AI tasks with delivery as pinned conversation entry or Pushover push
- `briefing` (R8) — Morning Card data assembly (calendar, weather, top tasks, recent captures)
- `pinned-context` (R7) — refresh endpoint that re-runs the workspace's dynamic SQL to rebuild the system-prompt context block

**New frontend pages and components**

- Settings page reorganized into a section-based layout with seven sections, in order: **Profile, Appearance, Voice, Notifications, Briefing, Context Capture, Scheduled Prompts**. Admin-only sections are gated by user role.
- Theme builder — "Build a custom theme" flow under Appearance (R1.4)
- Workspace System Prompt editor — admin-only textarea with character counter and 50K cap
- Morning Card — proactive briefing surface that appears at the top of the conversation list each morning (R8)
- Quick Capture overlay — Ctrl+Shift+K hotkey + share-target landing UI (R9)
- Voice Mode controls — STT + TTS run entirely in-browser; **no audio leaves the device** (R10)
- Scheduled Prompts manager — schedule, enable/disable, view next-run time, view recent runs

**Service worker / PWA additions**

- `/quick-capture` Web Share Target action — share text/URLs/images from any Android app into BowersHub AI; the service worker forwards the payload to the Quick Capture ingest endpoint
- Dynamic `manifest.webmanifest` — generated per-request so admin icon swaps invalidate browser PWA caches without a hard reset

**Key technical decisions**

- **CroniterTrigger fix for day-of-week** — APScheduler's stock cron parser disagrees with `croniter` on `0 = Sunday` vs `0 = Monday`. Implemented a thin `CroniterTrigger` wrapper that delegates to `croniter` so user-entered cron expressions behave the same way they do everywhere else (R11).
- **Dynamic web manifest for cache busting** — when the admin uploads a new app icon (R2), the manifest URL changes via a content hash, forcing PWAs to re-fetch icons without manual intervention.
- **ServiceWorker share-target handler** — the `/quick-capture` action receives `POST` multipart from the OS share sheet; the SW unpacks text/url/files and forwards to the API while the user lands on the overlay UI.
- **In-browser voice processing** — Web Speech API for STT and `SpeechSynthesis` for TTS keeps Voice Mode latency low and avoids streaming any audio off-device.
- **Pinned context refresh as an explicit endpoint** — instead of re-running pinned SQL on every message, the system caches the pinned block and exposes a `POST /api/pinned-context/refresh` to rebuild on demand (R7).
- **System prompt 50K cap** — enforced server-side and surfaced in the editor as a live character counter (R5/R6).

**Migration notes**

- All schema changes ship as forward-only migrations in `backend/migrations/`. They apply cleanly to a fresh install and to the existing deployed database.
- No new required env vars. Optional: `PUSHOVER_USER_KEY` / `PUSHOVER_API_TOKEN` are reused if scheduled-prompt push delivery is enabled (already present in the stack for budget alerts).
- Existing users default to the platform's default theme and `text_size = 'medium'` until they pick something else.
