# Dashboard V2: SSE Command Center — Requirements

## Overview
Transform the BowersHub dashboard from a passive polling interface (13 simultaneous HTTP requests per minute) into a real-time, event-driven Command Center. The system will leverage a Server-Sent Events (SSE) architecture to reduce backend load and introduce interactive, agent-aware features like the Action Center, Task Reel, and Generative UI widgets.

---

## 1. Architecture & Performance (The SSE Engine)

### R1.1 — Single Unified SSE Stream
The dashboard must retrieve all its data via a single `text/event-stream` endpoint (`GET /api/dashboard/stream`). The 13 individual polling endpoints will be deprecated for users opted-in to the V2 dashboard.

### R1.2 — Backend Publisher Loop
The backend must run an asynchronous task (e.g., in `main.py` lifespan) that aggregates data from all dashboard sources (System Health, Finance, Weather, etc.) on their own optimal schedules, yielding JSON events to connected clients. 

### R1.3 — First-Frame Hydration
Upon a new client connection, the SSE endpoint must immediately emit a "Hydration Event" containing the last-known cached state of all active widgets, ensuring the UI does not render empty frames while waiting for the next polling cycle.

### R1.4 — Mobile Lifecycle Resilience
The frontend implementation must use the browser's `visibilitychange` API. When the app is backgrounded, it should cleanly close the SSE connection. When foregrounded, it must instantly reconnect and request a fresh Hydration Event.

### R1.5 — Zero-Disruption Opt-In
The V2 dashboard must be explicitly opt-in via a `use_experimental_dashboard` boolean in `bh_users.settings_json`. The legacy `WidgetGrid` and its polling hook must remain functional for opted-out users until V2 is formally promoted to default.

---

## 2. Core Features (The "Alive" OS)

### R2.1 — The Action Center
The UI must include a dynamic top-row container. This container must remain entirely hidden if there are no active alerts. It must render dismissible or actionable cards for critical system states (e.g., "Minisforum Disk at 95%", "Uncategorized Transactions").

### R2.2 — Interactive Task Reel
The dashboard must feature a scrolling, terminal-style widget displaying recent background tasks and system logs (replacing the visibility previously provided by the n8n execution UI). 

### R2.3 — Inline Mutations
Events in the Task Reel and Action Center must support actionable payloads. A log entry (e.g., "Categorizer: Processed $14.99 as Unknown") must be capable of rendering an inline button (e.g., "[Recategorize]") that directly triggers a backend mutation without requiring the user to open a chat interface.

### R2.4 — Hardware HUD (Agent Strain)
The System Health widget must be upgraded to correlate host hardware strain directly to agent activity. If CPU or VRAM usage exceeds a defined threshold (e.g., 90%), the widget must display the active background task causing the load (e.g., "EmbeddingWorker backfill").

### R2.5 — Generative UI (Artifact Canvas)
The dashboard grid must support dynamic, ephemeral widgets. The LLM must be equipped with a tool to emit a UI JSON payload that the frontend parses to render custom React components (e.g., mini bar-charts, temporary task lists) inside a dashboard cell.
