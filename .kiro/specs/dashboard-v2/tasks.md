# Dashboard V2: SSE Command Center — Tasks

> Each task traces to requirements in `requirements.md`. Work top-to-bottom; respect dependencies.

## Phase 1: Core Plumbing (SSE Stream)

> **Phase 1 status (2026-07-01):** DONE. The SSE plumbing (Tasks 1–3) existed
> unlogged on `main`, but `DashboardV2` was a status-only stub. This pass built
> the real V2 UI (per-user layout fed by the stream), hardened the publisher
> scoping, and verified end-to-end (streamed widgets render live, "● Live" pill).

### Task 1: Opt-In Configuration
- **Effort:** S
- **Requirements:** R1.5
- [x] Add `use_experimental_dashboard` to the frontend `SettingsSchema` and `useSettingsStore` (present + `settings.py` PATCH field + Settings toggle).
- [x] Update `DashboardPage.tsx` to read the setting: render `<DashboardV2 />` if true, fallback to the existing `<WidgetGrid />` if false.

### Task 2: Backend SSE Stream Engine
- **Effort:** M
- **Requirements:** R1.1, R1.2, R1.3
- [x] Create `backend/services/dashboard_stream.py` — singleton `DashboardStateCache` (asyncio `Condition`-backed).
- [x] `asyncio` background publisher loop polls the 13 dashboard data functions on staggered schedules → cache. **Scoping hardened this pass:** the shared cache is correct only because every dashboard endpoint returns household-global data (verified — none filter by caller); the `_SYSTEM_CTX` sentinel documents + guards that invariant (no per-user endpoint may join the global publisher).
- [x] `GET /api/dashboard/stream` — custom `StreamingResponse` generator: immediate hydration event, then `Condition`-driven update events (1 s disconnect poll).
- [x] Wired into `main.py` lifespan (`start_/stop_dashboard_stream_loop`).

### Task 3: Frontend SSE Subscriber & Resilience
- **Effort:** M
- **Requirements:** R1.4
- [x] `useDashboardStream.ts` — streams via `fetch`+`ReadableStream` (Authorization header; native `EventSource` can't send it), parses `data:` frames into `widgetData`.
- [x] `visibilitychange` closes the stream when hidden, reconnects + re-hydrates when visible.
- [x] Widget data now flows from the stream, not per-widget polling: `WidgetGrid` gained a `streamData` prop (V2 renders `StreamWidgetCard`, keyed via `endpointToStreamKey`); `useDashboardStore` keeps owning the per-user *layout* only. `DashboardV2` is now the real streamed grid + `DashboardNav` + a "● Live" indicator (was a status stub). Verified end-to-end on a seeded stack. tsc clean; 369 frontend tests + 14 new `streamKey` cases.

---

## Phase 2: Action Center & Task Reel

### Task 4: Agent Event Data Model — DONE (2026-07-01)
- **Effort:** S
- **Requirements:** R2.2
- [x] Migration **`0059_agent_events.sql`** (not `0012` — chain is at 0058) adds `bh_agent_events` (id, created_at, source, message, level CHECK'd, `action_payload` jsonb) + a `created_at DESC, id DESC` index. Forward-only + idempotent.
- [x] `backend/services/agent_logger.py`: `log_event()` persists + pushes onto the SSE cache via `DashboardStateCache.append_event` (newest-first, bounded to 50); `hydrate_recent()` seeds the cache from history on boot (wired into `main.py` lifespan after a startup heartbeat). Fire-and-forget (never raises into callers). `created_at` stringified so the whole cache stays `json.dumps`-able (SSE contract). Emitters wired into the categorizer + SimpleFin sync completions.
- [x] **Tests:** `test_agent_logger.py` (3, DB-backed) — persist + jsonb round-trip + newest-first bounded push + cache JSON-serializable; invalid level → `info`; hydrate refills a cold cache; `append_event` cap/order.

### Task 5: Interactive Task Reel UI — DONE (2026-07-01)
- **Effort:** M
- **Requirements:** R2.2, R2.3
- [x] `TaskReelWidget.tsx` subscribes to `widgetData.agent_events` from the stream (mounted in `DashboardV2` below the grid). Level-colored dots (info/success/warning/error), source, relative time, scrollable.
- [x] When an event carries `action_payload {label,type:'mutation',endpoint,method,body}`, renders an inline button.
- [x] The button dispatches via the api client (POST/PATCH/PUT/DELETE), toasts success/failure, shows a "✓ Done" terminal state. **Verified end-to-end** on a seeded stack (reel shows live categorizer/simplefin/embedding events + a working Recategorize button).
- [x] **Tests:** `TaskReelWidget.test.tsx` (4) — empty state, event row, no-button-without-action, and the inline mutation fires the right endpoint + toasts + disables. tsc clean; 383 frontend tests.

### Task 6: Action Center UI — DONE (2026-07-01)
- **Effort:** S
- **Requirements:** R2.1
- [x] `ActionCenter.tsx` mounted above the grid in `DashboardV2`; level-styled cards, per-session client-side dismiss.
- [x] Trigger logic in `dashboard_stream.evaluate_actions()` (pure, unit-tested): derives cards from `system_health` — disk ≥90% (warning) / ≥95% (error), memory ≥90% (warning). Recomputed on each `system_health` poll and pushed to the cache's `actions` key **only when the card set changes** (no redundant notify). Transient CPU spikes are intentionally left to the Hardware HUD (Task 7), not the Action Center.
- [x] Renders dismissible cards; the whole strip renders `null` when there are no live/undismissed actions.
- [x] **Tests:** `test_dashboard_actions.py` (6 — thresholds, levels, stable ids, non-numeric guard, empty) + `ActionCenter.test.tsx` (4 — empty→null, render, dismiss-hides, dismiss-keeps-others). 387 frontend tests; tsc clean.
- **Follow-up:** actionable finance triggers (e.g. "N uncategorized → [Categorize]") need an uncategorized-count in the cache + an on-demand categorizer endpoint — deferred (not in the stream today).

---

## Phase 3: Hardware HUD & Generative UI

### Task 7: Hardware HUD (Agent Strain)
- **Effort:** M
- **Requirements:** R2.4
- [ ] Update `backend/services/system_health.py` to read the active background task registry (from APScheduler or the Agent Logger) when CPU > 90%.
- [ ] Upgrade the frontend `SystemHealthWidget.tsx` to conditionally render the "Strain Culprit" banner based on the new payload data.

### Task 8: Generative UI Rendering Pipeline
- **Effort:** H
- **Requirements:** R2.5
- [ ] Build a `<DynamicWidgetRenderer />` component in the frontend capable of taking a strict JSON schema (e.g., defining a simple chart, a list, or a metric block) and rendering it.
- [ ] Add a new LLM tool (`render_dashboard_widget`) to the `router_engine.py` context.
- [ ] When the LLM calls the tool, save the generated widget JSON to `bh_dashboard_layouts` under a special "ephemeral" layout, triggering an SSE layout update to instantly display the generated UI to the user.