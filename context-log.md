# 595BowersHub Context Log

Running log of decisions, discoveries, TODOs, and completed work across all Kiro sessions.

---

## [2026-05-11] Session Notes

- [Decision]: Set up Kiro workspace for 595BowersHub project in `C:\Users\manni\OneDrive\Homebrew_dev\`
- [Decision]: Created steering file at `.kiro/steering/595bowershub-project.md` — always-on project context for all Kiro sessions
- [Decision]: Created 3 hooks: `capture-context` (agentStop), `update-steering-on-md-edit` (fileEdited), `spec-complete-notify` (postTaskExecution)
- [TODO]: Connect Kiro to Minisforum via Remote SSH extension
- [TODO]: Start spec for Postgres migration (highest priority financial feature)
- [TODO]: Switch Finance workspace model from Sonnet to Haiku 4.5
- [TODO]: Auto-embed daily JSON files into AnythingLLM after nightly sync
- [TODO]: Set up Woodshop, Cooking, Records workspaces in AnythingLLM
- [TODO]: Investigate MCP servers for filesystem, n8n, and Postgres access
- [TODO]: Add Audiobookshelf container to Minisforum
- [TODO]: Migrate Home Assistant from HA Green to Minisforum container
- [TODO]: Set up Google account integration (Gmail/Calendar) for home management
- [TODO]: Create second AnythingLLM user for Manon (cooking/recipe workspace)
- [TODO]: Security hardening — Caddy reverse proxy, auth on filewriter, firewall rules
- [TODO]: Backup strategy for finance data and Docker volumes

---

## [2026-06-09] Session Notes — Claude Code (architecture review + workspace setup)

First session run via **Claude Code CLI** (alongside Kiro; Kiro credits exhausted for the month). Claude Code and Kiro now share this repo — see new `CLAUDE.md` for the coexistence protocol. This log is the shared handoff journal.

- [Decision]: Produced a full architecture review → `project-review.md` (repo root, committed `b87a0bb`). Exec summary, current-state assessment, strengths, critical issues (C1–C7), foundation plan (§8), and API/subscription cost analysis (§9). Verdict: strong core, weak operational/security envelope — fix foundations before new features.
- [Discovery]: **Critical security issue (C1)** — `ask-db` (`services/finance.py`) runs LLM-generated SQL on the **superuser** pool behind only a regex blocklist. Any member can read `bh_users` hashes / host files. Stopgap: gate to admin; real fix: least-privilege `finance_reader` role + `sqlglot` + read-only txn.
- [Discovery]: **Schema not rebuildable (C2)** — two migration dirs; `bowershub-ai/backend/migrations` crashes on a fresh DB (`013`, `021` alter tables only created by the orphaned top-level `/migrations`). Seven duplicate migration numbers. No CI.
- [Discovery]: `db-admin/` (2943 lines) is a redundant, unauthenticated, SQL-injectable twin of `db_browser.py` — recommend deleting, folding its inbox/AI-extract endpoints into bowershub-ai behind auth.
- [Done]: SimpleFin credential leak (C3) — owner rotated + moved to env (confirmed).
- [Decision]: PWA wording in review corrected — it **is** a real installable PWA; only the offline/caching layer is missing (intentional, low priority).
- [TODO][next session, priority order]: **(1)** dynamic model discovery to remove hardcoded model IDs (no-hardcoding ethos) — Models API → `bh_model_rates`, reference by role not string; see `project-review.md` §9.6. **(2)** reproducible schema + off-site backups (C2). **(3)** `ask-db` sandbox + per-app scoped DB roles (C1/C7). **(4)** CI with from-empty-DB migration test (C5). Then **(5)** pgvector semantic memory (§8.3) as first feature.
- [Discovery][cost]: at heavy personal use, optimized API spend ≈ $8–20/mo (verify prompt caching `cache_read_input_tokens` is non-zero; move batch jobs to the 50%-off Batch API). Recommend keeping one frontier sub for features, letting the app absorb the routine/personal-data load. A flight lookup hit L3 because it's multi-source — fix via a composite `find-travel` skill or L2 skill-chaining, not a threshold tweak.
- [Done][env]: Backend venv repaired (system lacks `ensurepip`; pip bootstrapped via `/usr/bin/pip3 --python`) and all reqs synced — **438 tests collect**. Frontend deps current — **`tsc --noEmit` clean**. Added `CLAUDE.md`. (`.venv`=Py3.14 vs Docker 3.12; DB-backed tests need Postgres.)

---

## [2026-06-09] Idea parked — in-app "Claude Code" code agent (modify the repo from the mobile app)

- [Idea]: Add an admin-only access point in the mobile/PWA frontend to edit the BowersHub codebase via an agent ("change X" from the phone → agent edits → PR). The phone stays a **thin client** (chat/event stream UI); no agent runs on-device — API key + GitHub token never leave the server.
- [Decision][architecture]: Recommended path is **Managed Agents (CMA)**, not the subscription and not an unsandboxed agent on the prod host. Shape: `agents.create()` once (agent toolset + GitHub MCP, store `agent_id`) → per-request `sessions.create()` with a `github_repository` resource + vault for GitHub auth → stream `session.events` to the app → agent edits in Anthropic's container, pushes a branch, opens a **PR**. Alt path = Claude Agent SDK on our own infra (more direct, but points bash/edit at the prod box — rejected for now). Bills per-token via the API either way; the Pro/Max subscription is **not** a legitimate backend for this (interactive-use-only ToS).
- [Decision][sequencing]: **Blocked on the foundation work — do NOT build before C2 + C5.** The feature's own guardrails *are* the foundation tasks: reviewable PRs need CI (C5) to gate merges; an agent that writes/pushes needs reproducible schema + off-site backups (C2) for blast-radius recovery; least-privilege discipline = C1/C7. Build it first and you build the safety net twice, badly. Natural slot: **after** dynamic model discovery (§9.6) → C2 → C1/C7 → C5 → pgvector (§8.3), i.e. once CI gates PRs and backups exist.
- [Guardrails when built]: admin-role + 2FA on the endpoint (it's RCE-as-a-feature, gate via `auth.py`); default to branch+PR, never direct-to-`main`/auto-deploy; deploy stays a separate explicit human action; secrets server-side/vault only.
- [TODO][later]: when foundations land, `/spec mobile-code-agent` → `.kiro/specs/mobile-code-agent/` (requirements/design/tasks) capturing the CMA call sequence above.

---

## [2026-06-09] Session Notes — Claude Code (Phase 0 security stopgaps)

Started executing the review's game plan. Chose **Phase 0 = same-day risk reducers** (hours, low blast radius) before the heavier Phase 1 blockers. Work is on branch `foundation/phase-0-security`.

- [Handoff]: Found ~60 uncommitted files of in-progress feature work (CalDAV calendar, budget/inbox/reminder/gameday alert jobs, morning briefing scheduler, dashboard + db_browser router registration, `/files` static serving, slash-command flags, frontend sweep) — **not mine**. Snapshotted as commit `dd6e04f` ("WIP: in-progress feature batch …") to start Phase 0 from a clean tree. That batch shipped **18 failing frontend tests** across 4 files — now fixed (see below).
- [Done][test-fixes]: Fixed the 18 pre-existing frontend failures so the suite is green for merge. **All four were stale tests / env gaps, not product bugs — fixes are test-only + config, no production source changed.** (1) `useDashboardWidget` — test used `vi.runAllTimersAsync()` on the hook's perpetual poll `setInterval` → 10k-timer infinite-loop abort; switched to bounded `advanceTimersByTimeAsync(0)`. (2) `dashboardIntegration` — jsdom lacks `ResizeObserver` (react-grid-layout needs it) → added `src/test/setup.ts` polyfill via `setupFiles`; also rewrote 4 assertions that checked Tailwind `grid-cols-*`/`gap-` classes from a pre-react-grid-layout era to assert the real `.react-grid-layout` DOM. (3) `FieldHint` PBT — generator emitted `-0`, which `JSON.stringify`→`"0"` breaks round-trip; normalized `-0`→`0` in the arbitrary. (4) `SettingsPanels` — asserted an **inert** `.bh-text-*` class; actual live-preview sizing is inline `font-size` (index.css documents this) → assert strictly-increasing inline preview sizes. Full suite: **219 passed / 29 files**, `tsc` clean.
- [Done][C7/CORS]: Replaced `allow_origins=["*"]` (`main.py:186`) with an explicit allowlist via new `resolve_cors_origins()` (`config.py`) — combines `PUBLIC_URL` + comma-sep `CORS_ORIGINS` + localhost dev origins, drops any `*` (invalid with `allow_credentials`). Documented both env vars in `.env.example`.
- [Done][C7/rate-limit]: Wired the previously-dead `RateLimiter` onto `/api/auth/login` — new `login` limit (5/min) keyed **per-IP** via new `client_ip()` helper that honors `X-Forwarded-For` (we sit behind Caddy). `RateLimiter.check()` generalized from `user_id:int` to `Subject = Union[int,str]`. Verified: 5 allowed / rest 429, distinct IPs isolated.
- [Done][C1/ask-db stopgap]: Added admin-only gate in `skill_executor.execute()` for `ADMIN_ONLY_SKILLS = {ask-db, finance-query}` (new `_user_is_admin()` role lookup). Non-admins now can't run LLM-SQL on the superuser pool via chat. **Stopgap only** — real fix (least-priv role + `sqlglot` + read-only txn) is still Phase 1. `TODO(phase-1)` left in code to swap this for a DB-driven per-skill min-role column.
- [Done][C6/frontend]: Added top-level `ErrorBoundary` (no more white-screen on render throw) + a minimal zustand toast system (`stores/toast.ts`, `components/Toaster.tsx`) wired into `main.tsx`. Wired the two silent error paths to toasts: WS `error` event (the "typing indicator vanishes" gap) and the API 401 session-expiry. `tsc --noEmit` clean; touched/created files' tests pass.
- [Next]: Phase 1 true blockers — (1) reproducible-from-zero schema + verified off-site backups (C2), (2) real `ask-db` sandbox + per-app scoped DB roles (C1/C7), (3) CI with from-empty migration test + secrets scan (C5). Note: the dynamic-model-discovery task (§9.6) is still queued; the WIP batch re-added hardcoded `HAIKU_MODEL`/`SONNET_MODEL` to `config.py` (`SONNET_MODEL` stale), so §9.6 still applies.

---
