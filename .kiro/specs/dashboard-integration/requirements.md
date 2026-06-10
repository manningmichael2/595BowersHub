# Requirements Document

## Introduction

This feature integrates the personal dashboard into BowersHub AI as a first-class route (`/dashboard`) within the existing React/Tailwind PWA, replacing the standalone Flask dashboard at port 8080. The dashboard shares auth, theming, and data access with the rest of BowersHub AI — delivering a single-app experience on mobile and desktop. The widget system is configurable, mobile-first, theme-reactive, and resilient to data source failures.

## Glossary

- **Dashboard_App**: The BowersHub AI React frontend, specifically the `/dashboard` route and its child pages/components.
- **Widget**: A self-contained UI card that displays data from a single source (e.g., weather, finance summary, container status). Formerly called "tile" in the standalone dashboard.
- **Widget_Registry**: A database-driven registry (`bh_dashboard_widgets` table) that defines available widget types and their configuration schemas.
- **Dashboard_Layout**: A user-persisted arrangement of widgets on a dashboard page, stored in `bh_dashboard_layouts`.
- **Dashboard_API**: A set of FastAPI endpoints under `/api/dashboard/` that supply widget data and layout persistence.
- **System_Health_Endpoint**: A new FastAPI endpoint that provides CPU, memory, disk, and Docker container metrics without requiring Netdata.
- **Widget_Hook**: A React custom hook (`useDashboardWidget`) that handles data fetching, caching, polling, error states, and staleness tracking for a single widget instance.
- **Dashboard_Page**: A named grouping of widgets (e.g., "Overview", "Finance", "System") that the user can navigate between via tabs or sidebar entries.

## Requirements

### Requirement 1: Dashboard Route and Navigation

**User Story:** As Michael, I want the dashboard accessible as a route inside BowersHub AI, so that I don't need a separate app or browser tab on my phone.

#### Acceptance Criteria

1. THE Dashboard_App SHALL render the dashboard at the `/dashboard` route within the existing React router.
2. WHEN the user taps the dashboard icon in the Sidebar, THE Dashboard_App SHALL navigate to `/dashboard` without a full page reload.
3. THE Dashboard_App SHALL display a navigation mechanism (tabs or sub-nav) to switch between Dashboard_Pages.
4. WHEN the user is on `/dashboard`, THE Dashboard_App SHALL indicate the active page in the navigation.
5. THE Dashboard_App SHALL include at least three default Dashboard_Pages: "Overview", "Finance", and "System".

### Requirement 2: Widget Registry and Configuration

**User Story:** As Michael, I want dashboard widgets defined in the database, so that adding a new widget type requires only a DB insert and a React component — no other code changes.

#### Acceptance Criteria

1. THE Widget_Registry SHALL store widget type definitions in a `bh_dashboard_widgets` table with columns for widget_key, display_name, description, default_config (JSONB), and data_endpoint.
2. WHEN the Dashboard_App loads, THE Dashboard_App SHALL fetch the list of available widget types from `GET /api/dashboard/widgets`.
3. THE Dashboard_App SHALL render only widgets whose widget_key has a corresponding React component registered in a client-side component map.
4. IF a widget_key has no matching React component, THEN THE Dashboard_App SHALL skip that widget silently without crashing the page.

### Requirement 3: Layout Persistence

**User Story:** As Michael, I want to add, remove, and reorder widgets on each page, and have the layout saved so it persists across sessions and devices.

#### Acceptance Criteria

1. THE Dashboard_API SHALL expose `GET /api/dashboard/layouts` to retrieve the user's saved layouts for all pages.
2. THE Dashboard_API SHALL expose `PUT /api/dashboard/layouts` to persist layout changes (widget list, order, and per-widget config overrides).
3. WHEN the user adds or removes a widget, THE Dashboard_App SHALL immediately persist the updated layout to the backend.
4. WHEN the user reorders widgets (drag-and-drop on desktop, move-up/move-down on mobile), THE Dashboard_App SHALL persist the new order.
5. IF no saved layout exists for a page, THEN THE Dashboard_App SHALL use a default layout defined in the Widget_Registry seed data.

### Requirement 4: Mobile-First Responsive Design

**User Story:** As Michael, I want the dashboard to be usable on my Pixel 9 Pro, so that I can glance at key info without needing my desktop.

#### Acceptance Criteria

1. WHILE the viewport width is less than 640px, THE Dashboard_App SHALL render widgets in a single-column stacked layout.
2. WHILE the viewport width is 640px or greater, THE Dashboard_App SHALL render widgets in a multi-column grid (2 or 3 columns depending on available width).
3. WHEN the user taps a widget on mobile, THE Dashboard_App SHALL expand it to show additional detail (if the widget supports it).
4. THE Dashboard_App SHALL use touch-friendly hit targets (minimum 44x44px) for all interactive elements within widgets.

### Requirement 5: Theme Reactivity

**User Story:** As Michael, I want the dashboard to follow my BowersHub AI theme choice (including custom themes), so that dark themes render correctly and the whole app feels unified.

#### Acceptance Criteria

1. THE Dashboard_App SHALL use only CSS custom properties from the existing BowersHub theme system (`--color-background`, `--color-surface`, `--color-primary`, `--color-text`, `--color-text-muted`, `--color-border`, `--color-accent`) for all widget chrome.
2. WHEN the user changes their theme in Settings, THE Dashboard_App SHALL immediately re-render with the updated colors without a page reload.
3. THE Dashboard_App SHALL render legibly across all 10+ existing preset themes (including OLED Black and light-background themes).

### Requirement 6: Resilient Data Fetching

**User Story:** As Michael, I want widgets to degrade gracefully when a data source is unavailable or slow, so that one broken tile doesn't take down the whole dashboard.

#### Acceptance Criteria

1. THE Widget_Hook SHALL fetch data for each widget independently so that a failure in one widget does not block or crash other widgets.
2. IF a widget's data fetch fails, THEN THE Widget_Hook SHALL display the most recent cached data with a "stale" indicator showing the last-successful-fetch timestamp.
3. IF a widget has never successfully fetched data, THEN THE Widget_Hook SHALL display a descriptive error message within the widget boundaries without affecting other widgets.
4. THE Widget_Hook SHALL enforce a per-widget fetch timeout of 10 seconds, after which the request is treated as failed.
5. THE Widget_Hook SHALL support configurable polling intervals per widget type (default: 60 seconds) to keep data fresh without overwhelming the backend.

### Requirement 7: System Health Endpoint (Netdata Replacement)

**User Story:** As Michael, I want built-in system health monitoring without Netdata, so that I can see CPU/memory/disk/container status without a third-party sign-in wall.

#### Acceptance Criteria

1. THE System_Health_Endpoint SHALL expose `GET /api/dashboard/system-health` returning current CPU usage percentage, memory usage (used/total in bytes), disk usage (used/total in bytes for each mount point), and system uptime.
2. THE System_Health_Endpoint SHALL expose `GET /api/dashboard/containers` returning a list of Docker containers with name, status (running/stopped/restarting), image, ports, and uptime.
3. WHEN the Docker daemon is unreachable, THE System_Health_Endpoint SHALL return system metrics (CPU/memory/disk) with an error flag for the container section rather than failing the entire response.
4. THE System_Health_Endpoint SHALL respond within 2 seconds under normal conditions.

### Requirement 8: Finance Widgets

**User Story:** As Michael, I want finance widgets that actually work and stay working even when database schemas change, so that I can see MTD spending and account balances at a glance.

#### Acceptance Criteria

1. THE Dashboard_API SHALL expose `GET /api/dashboard/finance/summary` returning month-to-date total spending, top 5 categories by spend, and net change from previous month.
2. THE Dashboard_API SHALL expose `GET /api/dashboard/finance/balances` returning all account balances grouped by type (checking, savings, credit, investment) with a net worth total.
3. THE Dashboard_API SHALL expose `GET /api/dashboard/finance/recent-transactions` returning the 10 most recent transactions with amount, description, category, and posted_date.
4. IF a finance query fails due to a missing column or table, THEN THE Dashboard_API SHALL return an error response with the specific SQL error rather than crashing the endpoint.
5. THE Dashboard_API SHALL use column names validated against the current schema at startup, logging a warning if expected columns are missing.

### Requirement 9: Weather Widget

**User Story:** As Michael, I want a weather widget showing current conditions and a short forecast, so that I can check weather without leaving the app.

#### Acceptance Criteria

1. THE Dashboard_API SHALL expose `GET /api/dashboard/weather` returning current temperature (°F), feels-like temperature, conditions description, humidity, wind speed, and a 3-day forecast.
2. THE Dashboard_API SHALL fetch weather data from wttr.in for Clawson, MI (configurable location in widget config).
3. IF wttr.in is unreachable, THEN THE Dashboard_API SHALL return an error response without crashing.

### Requirement 10: Container Status Widget

**User Story:** As Michael, I want to see which Docker containers are running and quickly link to their UIs, so that I can monitor services from one place.

#### Acceptance Criteria

1. THE Dashboard_App SHALL render a Containers widget that displays each container's name, status (running/stopped), and a clickable link to the container's web UI (if applicable).
2. THE Widget_Registry SHALL store the URL mapping for container links as JSONB configuration (not hardcoded in the React component).
3. WHEN a container is stopped, THE Dashboard_App SHALL visually distinguish it from running containers (e.g., muted color, warning icon).

### Requirement 11: Additional Widget Types

**User Story:** As Michael, I want widgets for inventory counts, knowledge base stats, email summaries, sports scores, Tailscale devices, and API spend, so that the rebuilt dashboard covers everything the old one did.

#### Acceptance Criteria

1. THE Dashboard_API SHALL expose data endpoints for: inventory item counts per table, knowledge base file count, recent emails (count + last 5 subjects), Tailscale device status, and Anthropic API spend (7-day total and per-day breakdown).
2. WHEN a data source for a widget is unavailable (e.g., Gmail IMAP unreachable), THE Dashboard_API SHALL return a partial response with an error flag for the failed sub-section.
3. THE Dashboard_App SHALL provide a React component for each of the following widget types: Inventory, Knowledge_Base, Recent_Emails, Tailscale_Devices, API_Spend, and Sports_Scores.

### Requirement 12: Widget Extensibility

**User Story:** As Michael, I want adding a new widget to be simple — just a React component, a data hook, and a DB row — so that the dashboard grows without architectural changes.

#### Acceptance Criteria

1. THE Dashboard_App SHALL use a component registry pattern where each widget_key maps to a lazy-loaded React component.
2. WHEN a developer creates a new widget, THE Dashboard_App SHALL require only: (a) a React component file, (b) a widget_key registration in the component map, and (c) an INSERT into `bh_dashboard_widgets`.
3. THE Widget_Hook SHALL accept a generic `data_endpoint` string from the Widget_Registry so new widgets can point to any backend URL without modifying shared code.

