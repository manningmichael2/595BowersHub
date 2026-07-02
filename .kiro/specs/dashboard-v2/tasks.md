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

### Task 4: Agent Event Data Model
- **Effort:** S
- **Requirements:** R2.2
- [ ] Create a migration `0012_agent_events.sql` to add a `bh_agent_events` table (id, timestamp, source, message, level, action_payload (JSONB)).
- [ ] Implement a `backend/services/agent_logger.py` to write to this table and emit the new row directly into the `dashboard_stream.py` publisher.

### Task 5: Interactive Task Reel UI
- **Effort:** M
- **Requirements:** R2.2, R2.3
- [ ] Build `<TaskReelWidget />` in the frontend that subscribes to the `agent_events` array from the SSE stream.
- [ ] Implement parsing logic: if an event's `action_payload` contains an action definition (e.g., `{type: "mutation", endpoint: "/api/...", body: {...}}`), render an inline button next to the text.
- [ ] Wire the button to execute the defined `fetch/api` call and show a success/failure toast.

### Task 6: Action Center UI
- **Effort:** S
- **Requirements:** R2.1
- [ ] Build `<ActionCenter />` in the frontend, positioned above the main grid.
- [ ] Define trigger logic in `dashboard_stream.py` to evaluate the cache (e.g., `if disk_usage > 95`) and emit a specific `actions` array to the stream.
- [ ] Render the array as dismissible/actionable cards; hide the component entirely if the array is empty.

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