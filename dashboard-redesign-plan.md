# 595BowersHub — Dashboard Redesign Plan
**Author:** Gemini CLI (Senior Architecture Partner)
**Date:** June 12, 2026

## 1. Current State Assessment
After exploring the frontend (`dashboard.ts`, `WidgetRegistry.ts`, `DashboardPage.tsx`) and backend (`routers/dashboard.py`), here is the baseline:
*   **Architecture:** The dashboard uses a registry pattern. The backend defines 13 widgets and serves user-specific layouts. The frontend dynamically loads components (`React.lazy`) and maps them to data endpoints.
*   **Data Fetching:** Each widget instance calls its own endpoint (e.g., `/api/dashboard/weather`, `/api/dashboard/system-health`). 
*   **UX:** It is currently a classic "read-only status board" segmented by tabs. 

**The Limitation:** It is highly functional but passive. You have to *read* it to get value. It functions like a standard Grafana or Home Assistant dashboard rather than the command center of an intelligent agent.

---

## 2. Strategic Vision: The "Bento Box" Command Center
A "better than best" dashboard shouldn't just display data; it should be an **interactive surface for your AI**. 

I propose moving to a **"Bento Box" architecture** (popularized by Apple and modern SaaS like Linear/Vercel). This design uses a tight, masonry-style grid with varying card sizes, subtle glassmorphism (or ultra-flat matte), and high data density. 

More importantly, widgets should transition from *monitors* to *actuators*. 

### 2.1 The Look and Feel
*   **Typography:** Monospace fonts for all metrics (costs, temps, balances) to align nicely. Clean, sans-serif UI font (Inter/Geist) for labels.
*   **Aesthetic:** Remove heavy borders. Use subtle background shading (e.g., `bg-surface-50` to `bg-surface-100` on hover).
*   **Interactivity:** Hovering over a card should reveal contextual actions (e.g., hovering over the "Recent Transactions" card reveals a "Recategorize" button for each row).

---

## 3. Proposed Cards & Widgets

Instead of 13 disparate widgets, we should group them semantically and make them interactive.

### 🆕 The Agent Feed (Novel Feature)
*   **What it is:** A live ticker of what your background agents (n8n workflows, Proactive Assistant) are doing right now.
*   **Why it wins:** It makes the AI feel "alive." Instead of seeing static data, you see: *"8:01 AM: Categorized 3 new receipts. 7:00 AM: Delivered Morning Briefing."*

### 🆕 Quick Capture / Memory Drop (Novel Feature)
*   **What it is:** A simple, always-present text box in a 2x1 widget. 
*   **Why it wins:** Instead of opening the chat to say "Remember to buy milk," you just type it here and hit Enter. It directly feeds the `EmbeddingWorker` for your new `pgvector` memory.

### 🔄 The "Server Room" (Consolidation)
*   **What it is:** Combine System Health, Docker Containers, and Tailscale into one high-density 2x2 widget.
*   **Why it wins:** Saves screen real estate. Shows a green/amber/red status light for the whole stack, expanding only if something is wrong.

### 🔄 Actionable Finance
*   **What it is:** The Recent Transactions widget, but interactive.
*   **Why it wins:** If you see an "Amazon" charge categorized as "Unknown," you click a dropdown *directly on the widget* to fix it. This triggers the `override-category` skill without needing to type a chat command.

### 🧠 Contextual Layouts (The "Smart" Dash)
*   **What it is:** The layout changes based on the data.
*   **Why it wins:** If it's Sunday during NFL season, the Sports Score widget automatically moves to the top. If CPU usage hits 95%, the System Health widget expands and flashes amber.

---

## 4. Architectural Upgrades

To support this without melting the Minisforum host, the architecture needs an upgrade.

### 4.1 The "Thundering Herd" Problem
Right now, loading the dashboard fires 13 simultaneous HTTP GET requests. Even with the new HTTP Connection Pooling (R1), this hammers the backend and the SQLite/Postgres DBs all at once.

### 4.2 The Fix: Server-Sent Events (SSE) or Batched Sync
*   **Implementation:** Replace the 13 individual `data_endpoint` hits with a single WebSocket or SSE connection: `/api/dashboard/stream`.
*   **How it works:** The backend maintains a background loop that polls the data sources at their appropriate intervals (e.g., CPU every 2s, Weather every 1h, Finance every 5m) and pushes updates down the stream.
*   **The Win:** The frontend makes exactly *one* connection on load. Widgets re-render only when the SSE stream pushes new data for their specific key.

---

## 5. Level of Effort (LOE) & Phasing

If we want to build this, I recommend splitting it to avoid breaking the current stable state.

### Phase 1: Aesthetic & Interactive UI (Low LOE)
*   **Tasks:** Upgrade `WidgetShell.tsx` to the "Bento" aesthetic. Add the "Quick Capture" widget using the existing `ask-db` or `knowledge` endpoints. Add interactive buttons to the Finance widget.
*   **Time:** 2-3 focused sessions. 

### Phase 2: The SSE Data Stream (Medium LOE)
*   **Tasks:** Build `backend/services/dashboard_stream.py`. Convert frontend `useDashboardWidget.ts` to consume an EventSource rather than `fetch`.
*   **Time:** 3-4 sessions (requires careful state management in Zustand).

### Phase 3: The Agent Feed & Smart Layouts (High LOE)
*   **Tasks:** Wire n8n webhooks and Python background tasks to emit events to an `agent_events` table. Build the frontend ticker. Write logic to dynamically reorder layouts based on conditions.
*   **Time:** 1-2 weeks.

---
**Next Steps:** If you agree with this vision, I recommend starting with **Phase 2 (The SSE Data Stream)**. The current architecture will struggle with the "Thundering Herd" as we add more widgets. Fixing the plumbing first allows us to build the fancy UI on a solid foundation.