# Dashboard V2: SSE Command Center — Design Specification
**Status:** Scoped & Planned

## 1. Architectural Foundation (The SSE Engine)
To support a real-time, interactive command center without straining the Minisforum host, the dashboard will migrate from client-side polling to a **Server-Sent Events (SSE)** architecture.

*   **Opt-In Migration:** A `use_experimental_dashboard` toggle in `bh_users.settings_json` will allow side-by-side testing.
*   **The Hub:** `backend/services/dashboard_stream.py` runs an `asyncio` loop, polling sources internally and pushing a single unified state payload down a `text/event-stream` endpoint (`/api/dashboard/stream`).
*   **Resilience:** The frontend will use the `visibilitychange` API to aggressively reconnect and request a "Hydration Event" to survive mobile background termination and solve the "First Frame" rendering delay.

---

## 2. Core Feature Set (Selected by User)

### 2.1 The "Action Center" (Contextual Triage)
*   A dynamic row at the top of the grid that only appears when the system requires user attention.
*   Acts as a unified inbox for anomalies (e.g., "Minisforum Disk at 95%", "3 Uncategorized Transactions").

### 2.2 The Interactive Task Reel (The "Inner Monologue")
*   Replaces the deprecated n8n UI with a live, scrolling terminal-style feed of background Python tasks.
*   **Actionable Inline:** Feed items are not just text; they contain inline action buttons.
    *   *Example:* `[08:14:02] Categorizer: Processed Amazon receipt ($14.99) as Unknown.` → `[Recategorize]` button inline. Clicking it opens a fast-action dropdown to fix it instantly.
    *   *Example:* `[08:15:00] Briefing: Morning draft ready.` → `[Play Audio]` button inline.

### 2.3 Generative UI Canvas (The "Artifact" Approach)
*   Moves beyond the 13 hardcoded widgets. The AI chat can generate ephemeral, task-specific widgets via JSON payloads.
*   If the user asks to "Track my coffee spending this week," the AI generates a payload that the dashboard translates into a temporary mini-bar-chart widget. 

### 2.4 The Hardware HUD (Resource Transparency)
*   An upgrade to the "Server Room" / System Health widget.
*   Correlates host hardware strain (CPU/VRAM) directly to agent activity. If the Minisforum CPU is pegged at 99%, the HUD visually indicates the culprit (e.g., "EmbeddingWorker is currently backfilling 500 records").

---

## 3. Level of Effort & Implementation Phases

### Phase 1: The Plumbing (SSE Stream)
*   **LOE:** Medium (3-4 sessions)
*   **Tasks:** Build `dashboard_stream.py`, convert frontend to Zustand SSE subscriber, ensure HTTP/2 multiplexing via Caddy. Build the opt-in toggle.

### Phase 2: Action Center & Interactive Task Reel
*   **LOE:** High (1-2 weeks)
*   **Tasks:** Standardize an `AgentEvent` data model in Postgres to track background actions. Build the frontend scrolling feed. Wire up inline mutation callbacks (like `override-category`).

### Phase 3: Hardware HUD & Generative UI
*   **LOE:** Medium to High
*   **Tasks:** Hook Ollama/Process metrics into the stream for the HUD. Build a dynamic component renderer in the frontend that accepts LLM JSON to render arbitrary charts/text blocks.