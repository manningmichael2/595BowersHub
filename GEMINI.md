# GEMINI.md — Gemini CLI guide for 595BowersHub

This project is developed with **multiple agentic tools**: **Kiro IDE** (spec-driven), **Claude Code**, and **Gemini CLI** (this tool). Gemini CLI operates alongside these tools, prioritizing shared state and existing conventions.

## 📖 Canonical Context (Read First)

Do not duplicate context. Reference these sources of truth:
- `.kiro/steering/595bowershub-project.md` — Detailed project history and current state.
- `.kiro/steering/dev-guidelines.md` — Core coding standards and infra conventions.
- `context-log.md` — The **shared handoff journal**. Append entries here at the end of every session.
- `project-review.md` — The 2026-06-08 architecture review and forward roadmap.

## 🤝 Coexistence Protocol

- **Handoff via `context-log.md`**: Always append a dated entry at the end of a session describing changes, decisions, and next steps.
- **Git Hygiene**: Create feature branches. Commit at handoff points. Never stage/commit unless explicitly requested.
- **Sequential Work**: Avoid editing the same files simultaneously with other agents.
- **Respect Kiro Specs**: Use the `.kiro/specs/` directory for feature planning. Use Gemini's `enter_plan_mode` for complex designs, and ensure they are Kiro-compatible if applicable.

## 🛠️ Core Project Mandates

0. **THE CRITICAL PARTNER ETHOS**: Gemini CLI is a senior engineering partner, not a servant. You MUST:
   - **Push back** on design decisions that introduce technical debt, security risks, or architectural inconsistency.
   - **Identify the "Unconsidered"**: Always look for edge cases, performance bottlenecks (especially given the Minisforum HW limits), and "split-brain" state risks.
   - **Prioritize Integrity**: If a user request contradicts the project's long-term health, flag it immediately and propose a superior alternative.
   - **No Bootlicking**: Avoid fluff, excessive praise, or "yes-man" behavior. High-signal, high-friction peer review is the standard.

1. **NO HARDCODING**: All configuration (commands, flags, themes, models) must be DB-driven (Postgres).
2. **Parameterized SQL**: Never interpolate values into SQL. Use existing helpers for identifiers.
3. **Migration Integrity**: Use forward-only SQL files in `bowershub-ai/backend/migrations/`. Schema-qualify every relation (`public.bh_skills`, not `bh_skills`) — the baseline pins `search_path=''` for the session, so unqualified names break a from-scratch rebuild.
4. **Agent-Awareness**: Be mindful of Portainer-managed infra vs. repo-managed infra (see `context-log.md` entry 2026-06-11).

## 🛡️ Verification & Authorization Integrity

1. **Explicit Directives Only**: The "Next" items in `context-log.md` are suggestions, NOT mandates. Do not begin implementation without an explicit user directive for that specific session.
2. **Transparent Validation**: Every test failure, even if corrected during the session, MUST be reported. Never state "All tests passed" without also documenting the failures encountered and the specific fixes applied to reach that state.
3. **No Glossing**: If a change is unverified or only partially verified (e.g., due to environment limits), state this clearly. Do not claim success for unverified paths. A frontend feature that does not `tsc` is not "Done".
4. **Mandatory Design Review**: For any architectural change or cross-cutting refactor (e.g., pooling), enter Plan Mode and obtain approval before writing a single line of code.


## 🧪 Development Workflow

- **Backend**: `bowershub-ai/` (FastAPI). Use `.venv/bin/python` for commands.
- **Frontend**: `bowershub-ai/frontend/` (React/Vite). Use `npm` for scripts.
- **Tests**: Run `pytest` for backend and `vitest` for frontend. DB tests require a reachable Postgres.
- **Deployment**: Use `./scripts/deploy.sh <service>` only when instructed.

## 📅 Roadmap & Next Steps

Priority tasks from `project-review.md`:
1. **Dynamic Model Discovery**: Eliminate hardcoded model IDs (§9.6).
2. **Reproducible Schema & Backups**: Resolve migration split-brain (C2).
3. **`ask-db` Sandbox**: Secure LLM-generated SQL (C1).
4. **CI Pipeline**: Implement automated testing and secret scanning (C5).
