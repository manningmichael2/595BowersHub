# Implementation Plan: Dashboard Integration

## Overview

Integrate the personal dashboard as a first-class `/dashboard` route inside BowersHub AI, replacing the standalone Flask dashboard. Implementation is layered: database migration → backend API → frontend foundation (store, hook, registry) → individual widget components → integration and polish. Each task is independently testable.

## Tasks

- [x] 1. Database migration and seed data
  - [x] 1.1 Create migration 017_dashboard_integration.sql
    - Create `bh_dashboard_widgets` table (widget_key, display_name, description, category, data_endpoint, default_config JSONB, default_pages JSONB, sort_order, is_active)
    - Create `bh_dashboard_layouts` table (user_id, page_key, widgets JSONB, updated_at) with UNIQUE(user_id, page_key) constraint
    - Create index on `bh_dashboard_layouts(user_id)`
    - Seed all 12 widget types with correct data_endpoint paths, default_config (polling intervals), and default_pages assignments
    - Seed default layouts for "overview", "finance", and "system" pages for the admin user (id=1)
    - _Requirements: 2.1, 3.5, 5 (default pages)_

- [x] 2. Backend dashboard router — registry and layouts
  - [x] 2.1 Create `backend/routers/dashboard.py` with widget registry and layout endpoints
    - `GET /api/dashboard/widgets` — query `bh_dashboard_widgets` where `is_active = true`, return list
    - `GET /api/dashboard/layouts` — return all layouts for the authenticated user; if none exist, generate defaults from widget registry `default_pages` column
    - `PUT /api/dashboard/layouts` — accept a `{ pages: [{ page_key, widgets: [...] }] }` body, upsert into `bh_dashboard_layouts`
    - Use `Depends(get_current_user_id)` from existing auth middleware
    - Register router in `backend/main.py` with `app.include_router(dashboard_router)`
    - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 2.2 Write unit tests for layout persistence round-trip
    - **Property 2: Layout persistence round-trip**
    - **Validates: Requirements 3.2, 3.4**

- [x] 3. Backend dashboard router — system health and containers
  - [x] 3.1 Implement `GET /api/dashboard/system-health` endpoint
    - Read CPU usage from `/proc/stat` (calculate percentage from deltas)
    - Read memory from `/proc/meminfo` (used/total/percent)
    - Read disk from `os.statvfs()` for each mount point (`/`, `/files`, `/knowledge`)
    - Read uptime from `/proc/uptime`
    - Return structured JSON; handle exceptions per sub-section with error flags
    - Enforce 2-second response target
    - _Requirements: 7.1, 7.3, 7.4_

  - [x] 3.2 Implement `GET /api/dashboard/containers` endpoint
    - Connect to Docker daemon via `httpx` to `/var/run/docker.sock` (unix socket)
    - List containers with name, status, image, ports, uptime
    - If Docker daemon is unreachable, return `{ containers: [], error: "Docker daemon unreachable" }` instead of failing
    - _Requirements: 7.2, 7.3, 10.1_

  - [x] 3.3 Write property test for partial response resilience
    - **Property 5: Partial response resilience**
    - **Validates: Requirements 7.3, 11.2**

- [x] 4. Backend dashboard router — finance endpoints
  - [x] 4.1 Implement finance data endpoints
    - `GET /api/dashboard/finance/summary` — MTD total spending, top 5 categories, net change vs previous month
    - `GET /api/dashboard/finance/balances` — all accounts grouped by type (checking, savings, credit, investment) with net worth total
    - `GET /api/dashboard/finance/recent-transactions` — last 10 transactions with amount, description, category, posted_date
    - Wrap all SQL in try/except; on schema error (missing column/table), return `{ error: true, message: "<sql error>", data: null }` with HTTP 200
    - Validate expected column names at startup, log warnings for missing columns
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 4.2 Write property test for graceful SQL error handling
    - **Property 6: Graceful SQL error handling**
    - **Validates: Requirements 8.4**

- [x] 5. Backend dashboard router — weather, inventory, knowledge, emails, tailscale, api-spend
  - [x] 5.1 Implement remaining data endpoints
    - `GET /api/dashboard/weather` — delegate to existing `backend/services/weather.py`, format response as current conditions + 3-day forecast; return error object if wttr.in unreachable
    - `GET /api/dashboard/inventory` — query item counts per inventory table (`tools`, `router_bits`, `saw_blades`)
    - `GET /api/dashboard/knowledge` — count files in `/knowledge` directory tree
    - `GET /api/dashboard/emails` — connect to Gmail IMAP via existing credentials, return count + last 5 subjects; return error flag if IMAP unreachable
    - `GET /api/dashboard/tailscale` — run `tailscale status --json` via subprocess, parse device list; return error if tailscale CLI not found
    - `GET /api/dashboard/api-spend` — query `public.api_usage_log` for 7-day total and per-day breakdown
    - Each endpoint handles its own errors independently, returns partial data with error flags
    - _Requirements: 9.1, 9.2, 9.3, 11.1, 11.2_

- [x] 6. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend foundation — Zustand store and useDashboardWidget hook
  - [x] 7.1 Create `frontend/src/stores/dashboard.ts` (Zustand store)
    - Define `DashboardState` interface with: availableWidgets, layouts (Record<string, PageLayout>), activePage, isLoading
    - Implement `loadDashboard()` — fetches widgets + layouts from API on mount
    - Implement `setActivePage(page)`, `addWidget(pageKey, widgetKey)`, `removeWidget(pageKey, widgetKey)`, `reorderWidgets(pageKey, widgets)`
    - `addWidget`/`removeWidget`/`reorderWidgets` optimistically update local state then persist via `PUT /api/dashboard/layouts`
    - _Requirements: 3.3, 3.4, 12.3_

  - [x] 7.2 Create `frontend/src/hooks/useDashboardWidget.ts`
    - Accept options: `{ endpoint, pollingInterval?, timeout? }`
    - Return: `{ data, error, isLoading, isStale, lastFetched, refresh }`
    - Fetch on mount, cache last successful response in state
    - Re-fetch on configurable polling interval (default 60s)
    - On fetch failure: retain cached data, set `isStale: true`, set `lastFetched` to last success timestamp
    - Enforce per-widget timeout (default 10s) via AbortController
    - Expose `refresh()` for manual pull-to-refresh
    - Clean up interval and abort on unmount
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 12.3_

  - [x] 7.3 Write property test for widget failure independence
    - **Property 3: Widget failure independence**
    - **Validates: Requirements 6.1**

  - [x] 7.4 Write property test for stale data caching
    - **Property 4: Stale data caching on failure**
    - **Validates: Requirements 6.2**

- [x] 8. Frontend foundation — Widget registry, shell, and grid
  - [x] 8.1 Create `frontend/src/components/dashboard/WidgetRegistry.ts`
    - Define `WidgetProps` and `WidgetDefinition` interfaces
    - Create `WIDGET_COMPONENTS` map: widget_key → `{ component: lazy(() => import(...)) }`
    - Export `getWidgetComponent(key)` that returns the definition or undefined for unknown keys
    - Register all 12 widget keys with lazy imports
    - _Requirements: 2.3, 2.4, 12.1, 12.2_

  - [x] 8.2 Create `frontend/src/components/dashboard/WidgetShell.tsx`
    - Common widget chrome: card container with header (display_name), loading skeleton, error state, stale indicator badge
    - Wrap children in a per-widget React Error Boundary — catch render throws, show "Widget unavailable — tap to retry" fallback
    - Use CSS custom properties from the theme system for all colors (`--color-surface`, `--color-border`, `--color-text-muted`, etc.)
    - Touch-friendly: minimum 44x44px interactive targets
    - _Requirements: 5.1, 5.2, 4.4, 6.2, 6.3_

  - [x] 8.3 Create `frontend/src/components/dashboard/WidgetGrid.tsx`
    - CSS Grid layout (not a library): single-column below 640px, 2-col at 640px+, 3-col at 1024px+
    - Accept `widgets: WidgetInstance[]` and render each via WidgetRegistry lookup + WidgetShell wrapper
    - Skip unknown widget_keys silently (no crash)
    - _Requirements: 4.1, 4.2, 2.3, 2.4_

  - [x] 8.4 Write property test for widget rendering matches registry
    - **Property 1: Widget rendering matches registry**
    - **Validates: Requirements 2.3, 2.4**

- [x] 9. Frontend — DashboardPage, navigation, and routing
  - [x] 9.1 Create `frontend/src/pages/DashboardPage.tsx` and `DashboardNav.tsx`
    - DashboardPage: mounts at `/dashboard`, calls `loadDashboard()` on mount, renders DashboardNav + WidgetGrid for active page
    - DashboardNav: tab bar with "Overview", "Finance", "System" — highlights active page, calls `setActivePage`
    - Mobile: tabs as horizontal scroll if needed
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

  - [x] 9.2 Register `/dashboard` route in App.tsx and add sidebar navigation
    - Add `<Route path="/dashboard" element={<DashboardPage />} />` to the router
    - Add dashboard icon to Sidebar (replace the existing `📊` external link/iframe with an internal `<Link to="/dashboard">`)
    - Navigate without full page reload (react-router client-side nav)
    - _Requirements: 1.1, 1.2_

- [x] 10. Checkpoint — Frontend foundation complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Widget components — Core widgets
  - [x] 11.1 Implement WeatherWidget component
    - Display current temperature (°F), feels-like, conditions, humidity, wind speed
    - Show 3-day forecast in a compact row
    - Use `useDashboardWidget` with endpoint from widget config
    - _Requirements: 9.1, 9.2_

  - [x] 11.2 Implement SystemHealthWidget component
    - Display CPU %, memory bar (used/total), disk bars per mount, uptime
    - Color-code thresholds (green < 70%, yellow 70-90%, red > 90%)
    - _Requirements: 7.1_

  - [x] 11.3 Implement ContainersWidget component
    - List each container with name, status badge (green=running, muted=stopped), clickable web_url link
    - Read URL mapping from widget config_overrides (not hardcoded)
    - Visually distinguish stopped containers (muted color, warning icon)
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 11.4 Implement FinanceSummaryWidget component
    - Show MTD total spending, top 5 categories as a mini bar chart or ranked list, net change badge
    - _Requirements: 8.1_

- [x] 12. Widget components — Finance and data widgets
  - [x] 12.1 Implement BalancesWidget component
    - Group accounts by type (checking, savings, credit, investment)
    - Show net worth total prominently at top
    - _Requirements: 8.2_

  - [x] 12.2 Implement RecentTransactionsWidget component
    - List last 10 transactions: amount (color-coded +/-), description, category pill, posted_date
    - _Requirements: 8.3_

  - [x] 12.3 Implement ApiSpendWidget component
    - Show 7-day total cost, per-day sparkline or bar chart
    - _Requirements: 11.1_

  - [x] 12.4 Implement SportsScoresWidget component
    - Show most recent scores for tracked teams
    - Compact card layout
    - _Requirements: 11.1_

- [x] 13. Widget components — System and utility widgets
  - [x] 13.1 Implement InventoryWidget component
    - Show item counts per table (tools, router_bits, saw_blades) as simple stat cards
    - _Requirements: 11.1_

  - [x] 13.2 Implement KnowledgeBaseWidget component
    - Show total file count, maybe top topics
    - _Requirements: 11.1_

  - [x] 13.3 Implement RecentEmailsWidget component
    - Show unread count + last 5 subject lines
    - Handle IMAP-unreachable error gracefully
    - _Requirements: 11.1, 11.2_

  - [x] 13.4 Implement TailscaleWidget component
    - Show device list with online/offline status indicators
    - _Requirements: 11.1_

- [x] 14. Checkpoint — All widgets implemented
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Integration and polish
  - [x] 15.1 Implement AddWidgetModal and layout management UI
    - Modal to browse available widgets by category, add to current page
    - On mobile: move-up/move-down buttons for reorder; on desktop: drag-and-drop reorder
    - Remove widget button (X) on each widget in edit mode
    - Persist changes immediately via the Zustand store actions
    - _Requirements: 3.3, 3.4, 4.3_

  - [x] 15.2 Wire up theme reactivity and verify across themes
    - Ensure all widget components use only CSS custom properties from the BowersHub theme system
    - Verify immediate re-render on theme change (no page reload)
    - Spot-check rendering on OLED Black, Nord, Michigan, and a light theme
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 15.3 Mobile responsiveness pass
    - Verify single-column stacked layout below 640px
    - Verify tap-to-expand on widgets that support detail view
    - Verify 44x44px touch targets on all interactive elements
    - Test on Pixel 9 Pro viewport (412px width)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 15.4 Write integration tests for dashboard load and theme reactivity
    - Test full `/dashboard` route mount → widget fetch → render cycle
    - Test theme change triggers CSS variable update on widget elements
    - Test viewport resize triggers layout change (single-col ↔ multi-col)
    - _Requirements: 1.1, 5.2, 4.1, 4.2_

- [x] 16. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python/FastAPI with asyncpg; frontend uses TypeScript/React with Zustand
- Docker socket access (`/var/run/docker.sock`) must be bind-mounted into the bowershub-ai container for the containers endpoint
- The `sports_scores` widget can reuse `backend/services/sports_score.py` which already exists
- Weather endpoint delegates to the existing `backend/services/weather.py`
- Finance queries use the existing asyncpg pool and existing table schema (transactions, accounts, categories)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "3.2"] },
    { "id": 2, "tasks": ["2.2", "3.3", "4.1", "5.1"] },
    { "id": 3, "tasks": ["4.2", "7.1", "7.2"] },
    { "id": 4, "tasks": ["7.3", "7.4", "8.1", "8.2", "8.3"] },
    { "id": 5, "tasks": ["8.4", "9.1", "9.2"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3", "11.4", "12.1", "12.2", "12.3", "12.4"] },
    { "id": 7, "tasks": ["13.1", "13.2", "13.3", "13.4"] },
    { "id": 8, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 9, "tasks": ["15.4"] }
  ]
}
```
