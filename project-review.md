# 595BowersHub — Project Review

**Reviewer:** Claude (Opus 4.8), commissioned as an honest, critical architecture review
**Date:** 2026-06-08
**Scope:** Entire repository — steering/specs/docs, `bowershub-ai` (FastAPI backend + React PWA), `filewriter`, `db-admin`, `dashboard`, `n8n-workflows`, migrations, infrastructure, tests.

> This review is deliberately critical. The brief asked me not to validate but to find what will rot, what won't scale, and what's missing. The praise is real where it appears, but the bulk of the value is in the problems. Read the Critical Issues and Recommendations sections as the actionable core.

---

## 1. Executive Summary

595BowersHub is an unusually ambitious and, in its core, well-engineered self-hosted personal AI assistant. The central app (`bowershub-ai`) shows real engineering maturity: a cost-tiered L1/L2/L3 routing pipeline, a clean plugin-style skill registry, careful JWT auth with refresh-token rotation and theft detection, a genuinely good password-reset flow, DB-enforced data integrity, and a thoughtfully-built WebSocket reconnection layer. For a one-person hobby project, the ceiling on display here is high.

But the project is **not yet "best-in-class" or "built to last a lifetime,"** and several issues are serious enough that I'd fix them before building anything new:

1. **A real, exploitable security hole in the `ask-db` skill** — an LLM generates SQL from free text and it is executed on the **database superuser connection** behind only a regex blocklist. Any authenticated member can read every table including `bh_users` password hashes, and likely read files on the DB host. (`services/finance.py:455-459`)
2. **The schema cannot be rebuilt from scratch.** Two competing migration directories exist; the authoritative one crashes on a fresh database (`013`, `021` alter tables that were never created). There is no single source of truth for the schema, which directly contradicts the "lasts a lifetime / reproducible" goal.
3. **A committed live bank credential** (SimpleFin) sits in git history. (`n8n-workflows/simplefin-backfill.py:17`)
4. **A redundant, unauthenticated twin** of the database browser (`db-admin/app.py`, 2943 lines) exposes full DDL with SQL-identifier injection and zero auth.
5. **The product's core — the routing engine, skill executor, and WebSocket chat — has essentially zero automated tests, and there is no CI at all.** The exhaustively-tested parts are the periphery (db-browser, themes); the heart is untested.

The encouraging news: the team (you + Kiro) already self-identified many architectural risks in the June 5 "Architecture Review & Pushback" section of the steering doc, and the instinct there — *skip the framework churn, fix backups/secrets/deploys first* — was correct. This review extends that honesty into the parts the steering doc hasn't caught yet.

**Overall grade:** Strong B-minus core wrapped in a C-minus operational and security envelope. The gap between the quality of `router_engine.py`/`auth.py` and the quality of `db-admin/app.py`/the migration story is the single biggest theme of this review. The project is one focused hardening pass away from being genuinely solid.

---

## 2. Understanding of the Project Goals

From the README, steering doc (`595bowershub-project.md`, 1872 lines of session history), and specs, the intent is clear and coherent:

- **One private PWA** on the phone that unifies personal finance, woodshop inventory, cooking, home management, and general knowledge.
- **Fully self-hosted** on a mini PC, accessible anywhere via Tailscale VPN, HTTPS through Caddy. No reliance on third-party SaaS for the core experience.
- **Cost-optimized AI** via a 3-layer router: free deterministic L1 (slash commands/regex), cheap L2 (Haiku/Ollama classification), full-reasoning L3 (Sonnet + tool use). Target ~$0.15–0.30/day.
- **Database-driven everything** — slash commands, flags, themes, skills, models all live in Postgres; adding a command is an `INSERT`, not a code change. (This is rule #1 in the steering doc and is mostly honored.)
- **Native-skill migration** — skills start as n8n webhooks and migrate to in-process Python one at a time with instant rollback.
- **Built to last a lifetime** — tool/tech agnostic, clean, scalable, maintainable, solid foundations. Owner is a hobby user, not attached to any current implementation.

These are good goals and the architecture mostly serves them. The "DB-driven, no hardcoding" discipline is the standout design principle and it shows real foresight. The main tension is that **the operational foundations (reproducibility, secrets, test coverage, service consolidation) lag well behind the feature ambition** — and "lasts a lifetime" is won or lost on exactly those foundations, not on features.

---

## 3. Current State Assessment

### Component health at a glance

| Component | LOC | State | Verdict |
|---|---|---|---|
| `bowershub-ai/backend` (core) | ~26k | Active, mature | Good core, untested, one critical vuln |
| `bowershub-ai/frontend` (PWA) | ~33k | Active, mature | Good auth/WS/theming; weak types, no error boundary, fake PWA |
| `db_browser.py` (one router) | 4283 | Active | Powerful but a monolith; non-transactional; one DDL injection sink |
| `db-admin/` | 2943 | **Redundant** | Delete — unauthenticated, injectable twin of db_browser |
| `filewriter/` | 772 | Active | Mostly fine; one unguarded `/write`; no auth |
| `dashboard/` | 286 | Active | Thin proxy on host network, no auth, bare excepts |
| `n8n-workflows/` | ~build scripts | Shrinking | Being migrated out; committed secret; drift between JSON + generators |
| Migrations | 31 + 9 | **Split-brain** | Two systems; fresh-DB boot is broken |
| Tests | 42 backend + ~30 FE | Lopsided | Periphery covered, core untested, no CI |
| `archive/` | — | Dead | Correctly archived legacy skills/scripts |

### Observations

- The project is in active, heavy iteration — the steering doc reads like a flight log of marathon sessions. Velocity is high; consolidation and hardening lag behind.
- There's real **architectural debt from rapid iteration**: duplicate migration numbers (seven collisions), duplicate service implementations, a 4283-line router, a 1643-line admin page, ~178 `any` casts in the frontend.
- Much of the steering doc's own June 5 "things to fix" list (backups, secrets, docker-compose, filewriter-in-repo) **has been done** — credit where due. The remaining gaps are the deeper structural ones this review focuses on.

---

## 4. Strengths

These are genuine and worth protecting through any refactor:

1. **The L1/L2/L3 routing concept is excellent** (`router_engine.py`). Cost-tiering messages through deterministic → cheap-classify → full-reason, with confidence thresholds and a local-model "L2.5" refinement gate, is a smart, original design that directly serves the cost goal. The DB-driven `is_read_only` threshold tuning (0.65 vs 0.75) is a nice touch.
2. **Auth is well-built** (`services/auth.py`). HS256 with a required secret (no insecure default), bcrypt, 90-day opaque refresh tokens that are SHA-256 hashed at rest, **refresh-token rotation with reuse/theft detection that revokes the whole token family**. The password-reset flow (enumeration-safe, rate-limited, single-use, 30-min expiry, revokes refresh tokens) is the most carefully-built thing in the codebase.
3. **Data integrity is enforced in the database, not just app code** (`migrations/001_initial_schema.sql`, `019_knowledge_graph.sql`): real foreign keys with deliberate cascades, CHECK constraints encoding domain enums, composite/partial/GIN indexes, money typed as `NUMERIC` not float. This is well above typical hobby-project quality.
4. **The skill registry refactor is the right pattern** (`skill_registry.py`). Decorator-based `@native_skill(...)` auto-discovery replaced a 135-line if/elif chain with a 15-line lookup. Adding a skill is now a drop-in file + a DB row. Exactly the plugin architecture a long-lived tool wants.
5. **The "DB-driven, no hardcoding" discipline** for commands/flags/themes/models is real and consistently applied. This is the single best decision in the project for long-term maintainability.
6. **WebSocket reconnection is production-grade** (`services/websocket.ts`): exponential backoff capped at 30s, cold-start token race handling, 4001-close → refresh-then-reconnect, queued-message replay on auth.
7. **The migration *runner* is competent** (`database.py:78-131`) — versioned via a `bh_migrations` table, per-file transactions, fail-fast. The problem is the migration *set*, not the runner.
8. **The theming system** (CSS custom properties + runtime luminance contrast + the `--bh-text-base` text-scaling approach) is a clever, correct solution to a genuinely hard problem (scaling text without breaking rem-based layout).
9. **Honest self-review already in the steering doc.** The June 5 pushback section killing the Strands/Bedrock/OpenClaw migrations was the right call and shows good judgment about not chasing frameworks.

---

## 5. Critical Issues

Ordered by severity. The first three I'd treat as "stop and fix."

### 🔴 C1 — `ask-db` executes LLM-generated SQL on the superuser pool (RCE-adjacent data breach)
`services/finance.py:386-465`. Free-text → Haiku → SQL → `conn.fetch(sql)` on the **main superuser connection pool**. The only guards are a keyword-regex blocklist (`_DANGEROUS_SQL`) and a `startswith SELECT/WITH` check. This is inadequate:
- A pure read-only `SELECT` is already catastrophic: `SELECT email, password_hash FROM public.bh_users` dumps every credential; `SELECT pg_read_file('/etc/passwd')` reads files on the DB host; `COPY ... FROM PROGRAM` / `lo_import` are reachable via crafted SQL.
- The schema prompt *hides* `bh_*` tables from Haiku but **nothing stops generated SQL from querying them.**
- It's reachable by **any authenticated member** through normal chat routing (`skill_executor` only enforces an optional per-skill `restricted_users` list — no admin gate), and is steerable via prompt injection.
- The code comment at line 455 literally says *"finance_reader role is preferred but not required"* — the safe path was designed and then skipped.

**This is the most important issue in the report.** Fix: dedicated least-privilege Postgres role (`GRANT SELECT` on only finance/inventory tables, revoke `pg_read_file`/`COPY`/`lo_*`/`bh_*`), separate connection pool, read-only transaction with `statement_timeout`, and a real SQL parser (e.g. `sqlglot`) to assert a single SELECT. Gate to admin until that's in place.

### 🔴 C2 — The schema cannot be rebuilt; two migration systems, fresh-DB boot crashes
- `bowershub-ai/backend/migrations/` (31 files, `NNN_name.sql`, auto-applied) is authoritative in code. The top-level `/migrations/` (9 files, `NNN-name.sql`) is **referenced by nothing** but is the *only* place the finance/inventory/files/cook/house schemas and tables are defined.
- `013_investment_flag.sql:5` and `021_finance_schema.sql:15` `ALTER`/`SET SCHEMA` tables (`public.transactions`, `public.accounts`) that the backend migrations **never create** → `relation does not exist` → `SystemExit` → **the app will not boot on a clean database.** The running system only works because those tables were created out-of-band long ago.
- **Seven duplicate migration numbers** (009, 010, 012, 013, 015, 017, 022 each appear 2–3× with different names). Apply order within a number is decided by ASCII sort of the filename suffix — arbitrary relative to intent. The project rationalizes this in a comment in `015` rather than fixing it.
- No checksums (edits to applied migrations are silently ignored), no down-migrations.

For a "lasts a lifetime" system, **inability to reproduce the schema is the deepest structural problem** — it breaks disaster recovery, fresh deploys, and test-from-scratch. Everything else is fixable around it; this one undermines the foundation.

### 🔴 C3 — Committed live secret + an unauthenticated injectable service
- `n8n-workflows/simplefin-backfill.py:17` hardcodes a base64 SimpleFin credential that decodes to a `username:password` pair with **full access to bank transaction history.** It is in git. Rotate now, move to env.
- `db-admin/app.py` (2943 lines) is a **redundant, unauthenticated** reimplementation of `db_browser.py`. It exposes `DROP COLUMN`, `RENAME TABLE`, `CREATE SCHEMA`, arbitrary row delete/insert, and `DELETE FROM files.assets` to **anyone who can reach port 5002**, and it interpolates schema/table/**column** names raw into f-strings (identifier injection the `bowershub-ai` version explicitly closes via `_quote_ident`). It also has duplicate route definitions (`/api/inbox-files`, `/api/inbox-process` defined twice). This service should be **deleted**, its unique inbox/AI-extract features folded into `bowershub-ai` behind `require_admin`.

### 🟠 C4 — The db_browser is a powerful, mostly-non-transactional monolith with a DDL injection sink
`routers/db_browser.py` (4283 lines, the largest file in the repo):
- **DDL `DEFAULT` values are injected raw** (`db_browser.py:2540`): `parts.append(f"DEFAULT {default_str}")` with zero sanitization, flowing into `CREATE TABLE`/`ALTER TABLE ADD COLUMN`. Admin-only, but a genuine injection sink and untested.
- **Mutations + undo-log writes are not atomic** (`update_row` at 1040/1077, `bulk_edit` at 1388). If the undo insert fails it's swallowed; the data change commits unrecoverably. Bulk ops have no surrounding transaction and can partially apply.
- **No table allowlist** — any admin token can read/edit/DDL `public.bh_users`, auth/token tables, the undo log itself. `_quote_ident` stops injection but does nothing to restrict *which* tables are reachable.
- Massive duplication (the ~120-line filter/sort builder is copy-pasted verbatim between `get_rows` and `export_csv`; the PK-lookup query is repeated 6+ times), N+1 query patterns (CSV import is row-by-row `execute`, no COPY/`executemany`), and a fragile undo model that breaks after any rename/drop-column.

### 🟠 C5 — The core of the product is untested, and there is no CI
- **Zero tests** for `router_engine.py` (1569 lines — the L1/L2/L3 cascade, the actual product), `skill_executor.py` (only ever monkeypatched away), the WebSocket chat handlers (the primary UX), and the AI skills (`weather`, `sports_score`, `finance`).
- Auth's `authenticate()` / password verification is explicitly never called in tests (`test_branding_router.py:90`).
- The db-browser property-based tests are **largely tautological** — they reimplement the SQL logic in Python inside the test and fuzz the reimplementation, not the real code. They test the author's mental model, not the system.
- Finance endpoint tests **mock the database entirely**, so SQL correctness (the thing most likely to silently corrupt financial data) is unverified.
- **No `.github/workflows/` exists at all.** Nothing runs the suite automatically. For a tool that must not lose financial/knowledge data, regressions ship silently.

### 🟠 C6 — Frontend: no error boundary, no PWA offline/caching layer, weak type safety at the boundary
- **No top-level error boundary** — any render throw white-screens the whole app. The only `ErrorBoundary` is on one dashboard widget.
- **It is a real, installable PWA** — valid `manifest.json` (`display: standalone`, full icon set incl. maskable), a working service worker, and even a Web Share Target into Quick Capture. It installs and runs correctly as a standalone app on Android. **What it lacks is an offline/caching layer:** the service worker (`public/sw.js`) does deliberate network-only pass-through and clears all caches on activate, so there is **no precaching (slower cold launches), no offline shell, and no update-on-deploy prompt**, and there's no `navigator.onLine` UI feedback. `vite-plugin-pwa` is installed but unused (`sw.js` is hand-written). Note this is an *intentional* choice — caching was disabled to avoid staleness bugs (per the file comment), and since the app is unusable offline anyway (every feature needs the backend), this is **polish, not a foundation blocker.** Revisit only when faster launches/offline-shell are wanted, done properly via `vite-plugin-pwa`/Workbox with an update handshake.
- **~178 `any` occurrences** in non-test source; the entire `ApiClient` returns `Promise<any>` and responses are blind-cast (`as Conversation[]`) with no runtime validation — a backend shape change fails silently at runtime, defeating the "strict" TS config at the boundary.
- **No global toast/notification system** — WebSocket and API error paths `console.error` and no-op, so the user sees the typing indicator vanish with no message when the assistant errors.
- `AdminConsolePage.tsx` is a 1643-line god-file with 38 `useState` calls, eagerly bundled despite being admin-only.

### 🟡 C7 — Operational gaps that bite a lifetime tool
- **Every container connects to Postgres as the superuser `michael`** — any one service can `DROP TABLE` anything. No per-app scoped DB roles. (Also the root cause that makes C1 catastrophic instead of contained.)
- **CORS `allow_origins=["*"]` with `allow_credentials=True`** (`main.py:188`) on a public-facing proxy.
- **Rate limiting is fully implemented but never called anywhere** (`middleware/rate_limit.py`) — `/api/auth/login` has unlimited password-guessing.
- **Hardcoded Tailscale IP `100.106.180.101`** across n8n scripts, dashboard, db-admin, and even backend source (`knowledge.py:18`, `db_browser.py:3777`) — a single re-IP breaks dozens of references, contradicting "lasts a lifetime."
- **`:latest` image tags** for n8n and Ollama (`infrastructure/docker-compose.yml`); filewriter `pip install`s unpinned deps on every container start instead of using its own Dockerfile.
- **Backups**: the steering doc says nightly `pg_dump` + tar is done locally but **off-site/remote is "ready to enable," not enabled.** One SSD failure still loses everything. (Verify this is actually running and actually off-site.)

---

## 6. Recommendations

### Quick wins (hours to a day each, high value)

1. **Rotate the SimpleFin credential** and move it to env (`simplefin-backfill.py:17`). 15 minutes. (C3)
2. **Gate `ask-db` to admin-only** as an immediate stopgap while C1's real fix is built. One line in the skill/router. (C1)
3. **Wire up the existing rate limiter** on `/api/auth/login` (per-IP) — the code already exists, it's just never invoked. (C7)
4. **Lock down CORS** to the known frontend origin(s) instead of `["*"]`. (C7)
5. **Add a top-level React error boundary** in `main.tsx` and a minimal toast system wired to the WS/API error paths. (C6)
6. **Renumber the seven duplicate migrations** so apply-order is unambiguous. Mechanical. (C2)
7. **Add a `.github/workflows/ci.yml`** that spins up Postgres and runs `pytest` + `vitest`. Even with today's coverage this catches regressions. (C5)
8. **Confirm off-site backups are actually running** and restore-tested — not "ready to enable." (C7)
9. **Pin `:latest` images** to digests/fixed tags; switch filewriter compose to `build: .`. (C7)
10. **Move the hardcoded `100.106.180.101`** to config/env and use Docker service DNS for container-to-container calls. (C7)

### Longer-term architectural improvements

1. **Make the schema reproducible (the highest-leverage structural fix).** Merge the top-level `/migrations` finance/domain DDL into the backend migration chain *before* `013`/`021`, delete the orphaned directory, add a CI job that builds the full schema from an empty Postgres. Add content checksums to `bh_migrations` to detect drift. Until this is done, disaster recovery is theoretical. (C2)
2. **Properly sandbox `ask-db`**: least-privilege `finance_reader` role + separate pool + read-only transaction + `statement_timeout` + `sqlglot` validation. Then introduce **per-app scoped DB roles** for every service (the same root cause). This converts C1 from catastrophic to contained. (C1, C7)
3. **Delete `db-admin`**, migrate its unique inbox/AI-extract endpoints into `bowershub-ai` behind auth. Eliminates 2943 lines of unauthenticated, injectable, duplicated DDL surface and removes a whole class of "two divergent implementations" bugs. (C3)
4. **Decompose the two monoliths.** Split `db_browser.py` into a package (`introspection/crud/ddl/csv/images/views/undo/inbox`) with shared `_quote_ident`/PK-lookup helpers extracted; wrap every multi-statement mutation in a transaction; add a table allowlist. Split `AdminConsolePage.tsx` into per-section lazy-loaded files. (C4, C6)
5. **Test the core, not the periphery.** Highest value: `router_engine.route()` with a mocked model provider (assert L1 dispatch, L2 confidence escalation, fallbacks); a WebSocket chat e2e via `TestClient.websocket_connect`; the auth login path; the knowledge-capture write path without monkeypatching the executor. Convert the tautological db-browser PBTs to hit real endpoints against `fresh_db`. Run finance queries against a real seeded DB. (C5)
6. **Decide the real PWA story.** Either adopt `vite-plugin-pwa`/Workbox properly (precache, offline shell, update prompt) or drop the PWA framing and the unused dependency. Add `navigator.onLine` feedback. (C6)
7. **Add runtime validation at the API boundary** (zod/valibot) and a typed `ApiError extends Error`, eliminating the ~178 `any`s where they actually matter. Consider react-query/SWR to replace the 44 hand-rolled `useEffect`+fetch+3-useState patterns. (C6)
8. **Consolidate the n8n-as-code story.** Pick one source of truth (export live JSON *or* fully generate it — not both committed), centralize model IDs/pricing/credential IDs in `_config.py`, add a dry-run lint. Better: continue the planned migration of scheduled jobs to apscheduler and shrink n8n to near-zero, which the steering doc already favors. (C7)

---

## 7. Technology Assessment

**Where the current stack is right — keep it:**
- **FastAPI + asyncpg + Postgres + React/Vite/Zustand + Tailscale + Caddy** is an excellent, durable, boring-in-a-good-way stack for this problem. No reason to change any of it.
- **Postgres as the single canonical store** with domain schemas is the correct backbone for a lifetime tool. Markdown-as-memory is simple and greppable.
- **apscheduler in-process** for scheduled jobs is the right call and should *absorb* the remaining n8n scheduled workflows, not the reverse.
- The June 5 decision to **skip Strands/Bedrock/OpenClaw** was correct. The hand-rolled router loop is understood, tuned, and working; replacing it with a young framework would trade control for churn. Don't reopen that.

**Where a different tool/approach would serve the goals better:**

| Area | Current | Recommendation |
|---|---|---|
| `ask-db` SQL safety | regex blocklist on superuser pool | `sqlglot` parse + least-privilege role + read-only txn. The *approach*, not just the tool, is wrong today. |
| Migrations | hand-rolled runner, two dirs, dup numbers, no rollback/checksums | Keep the runner concept but adopt the discipline of a real tool (Alembic, or sqitch/dbmate if you want raw SQL): linear versioning, checksums, down-migrations, one source of truth. |
| db-admin service | standalone unauth Flask | Delete; consolidate into the hardened `db_browser`. |
| Frontend data fetching | 44× hand-rolled `useEffect`+fetch | react-query/SWR (caching, dedup, retry, cancellation) — removes the single biggest source of boilerplate and stale-data bugs. |
| API type safety | `any` + blind casts | zod/valibot runtime validation at the boundary. |
| PWA/offline | installable PWA, but `sw.js` does no caching (intentional) | Fine as-is. If faster launches/offline-shell are wanted later, adopt Workbox via `vite-plugin-pwa` with an update handshake. Low priority. |
| DB roles | every service = superuser `michael` | Per-app scoped roles. This is a Postgres feature, not a new tool — just use it. |
| n8n | 7+ workflows, drift, hardcoded IDs | Continue migrating to native Python/apscheduler; let n8n shrink toward retirement (already the stated direction). |
| Secrets | env files + one committed credential + plaintext history | The env-file approach is fine; add a secrets scanner (gitleaks) in CI to prevent recurrence, and treat anything ever committed as compromised → rotate. |

**Missing capabilities a production-grade personal assistant should have** (none require a stack change):
- Reproducible-from-zero schema + restore-tested off-site backups (the two together = real disaster recovery).
- CI with a secrets scanner and a from-empty DB migration test.
- An error/observability story: a top-level error boundary, a notification system, and lightweight error reporting (even self-hosted) so silent failures stop being invisible.
- Least-privilege DB roles and a query-level kill switch (statement timeouts) so one bad skill or token can't read everything.

---

## Closing

The core of this project is better than its reputation as a "hobby tool" suggests — `router_engine.py`, `auth.py`, the skill registry, and the DB-driven design philosophy are things a professional team would be happy to have shipped. The problem is not the ceiling; it's the floor. The operational and security foundations (reproducible schema, scoped DB roles, the `ask-db` sandbox, tested core, real CI, consolidated services) are exactly the things that determine whether a system survives a decade, and they currently trail the feature work by a wide margin.

If I could only push three things: **(1) make the schema rebuildable and back it up off-site, (2) sandbox `ask-db` and stop using the superuser everywhere, (3) test the routing core and add CI.** Do those, delete `db-admin`, rotate the leaked credential, and this becomes a genuinely solid foundation worthy of the "lasts a lifetime" ambition.

> **Update (2026-06-08):** The leaked SimpleFin credential (C3) has been rotated and moved out of source by the owner.

---

## 8. Forward Plan — Foundation Sequencing & Future Features

This section answers the follow-up questions: *were the design decisions right, do I fix the foundation first, and what should I build once it's solid?*

### 8.1 Was the architecture right? Yes.

The **fundamental** architecture is sound and would hold up at 10× the scope: Postgres as the single canonical store, DB-driven configuration (no hardcoding), the L1/L2/L3 cost-tiered router, native-skill migration via the plugin registry, and self-hosted-on-Tailscale. None of the critical issues in §5 were "this design is wrong" — every one is an *execution/foundation* problem (non-reproducible schema, superuser `ask-db`, untested core, a redundant service) that can be fixed **without changing the architecture.** The skeleton is right; the joints need hardening.

### 8.2 Fix the foundation first — but split it, don't treat it as one gate.

Treating all foundation work as a single blocking gate will stall feature progress. Split it:

- **True blockers — do before building more (they compound; every feature inherits the risk otherwise):**
  1. Reproducible-from-zero schema + restore-tested off-site backups (C2, C7).
  2. `ask-db` sandbox (least-privilege role + `sqlglot` + read-only txn) and per-app scoped DB roles (C1, C7).
  3. A CI pipeline (Postgres service + `pytest`/`vitest` + secrets scan + from-empty migration test) (C5).
- **Parallelizable — do alongside features (quality-of-life, non-blocking):** frontend error boundary + toast system, runtime type validation at the API boundary, decomposing `db_browser.py` and `AdminConsolePage.tsx`, deleting `db-admin`.

Budget roughly 1–2 focused sessions on the true blockers, then build features and clean up the rest opportunistically.

### 8.3 The one missing primitive that unlocks the most: a semantic/vector layer

There is currently **no embeddings/semantic search.** Recall is grep-based. For a lifetime knowledge base this is the single biggest capability gap, and the fix uses what's already running: **add `pgvector` to Postgres + a local embedding model via Ollama (free).** That yields semantic search over every note, document, transaction memo, and chat message — matches by meaning, not keyword. It is the foundation that makes roughly half the features below good instead of brittle. **Highest-value single addition to the entire project; build it first after the blockers.**

### 8.4 Features worth building

**Memory that compounds (what makes this *yours*, not ChatGPT):**
- Proactive capture — the assistant notices durable facts mid-conversation and offers to remember them, instead of requiring a manual `/remember`.
- Actually use the knowledge graph already built (migration 019, `bh_entities`/`bh_relationships`, currently near-unused): entity-centric recall pulling everything about one entity across finance, calendar, photos, and notes.
- Temporal memory / time-travel — versioned facts, "what did I think about X a year ago?"
- Spaced resurfacing — a weekly "here's a note from months ago you may want," so the second brain resurfaces, not just stores.

**Financial foresight (past "what did I spend"):**
- Subscription/recurring detector → "paying $14/mo for something last used in March."
- Anomaly alerts → "this charge is 3× your normal at this merchant."
- Cash-flow forecast → "at this rate you're short by the 28th; insurance renews next week (~$X)."
- Net-worth-over-time from periodic balance snapshots (balances already sync; just persist history).
- Year-round tax/deduction tagging for woodshop/business expenses.

**Document & receipt intelligence (filewriter + pdfplumber + smart-capture already exist):**
- Warranty & manual vault — photograph a receipt → extract purchase date + warranty length → remind before it lapses.
- Semantic search across all documents (the pgvector payoff).
- Auto-filing — any inbound doc (email attachment, photo, share-sheet) classified, summarized, and routed to the right schema.

**Agentic / multi-step (the "skill chaining" TODO is the unlock):**
- Compose skills into tasks — "plan a dinner for 6 Saturday" → checks calendar, pulls recipes, cross-references pantry inventory, builds a shopping list.
- Watchers / standing queries — "tell me when lumber drops below $X" — persistent background agents, not one-shot answers.

### 8.5 Non-obvious, higher-leverage ideas ("things you wouldn't think to ask about")

- **An evaluation/observability harness for the AI itself.** API usage is logged, but there's no way to answer "did the router pick the right layer? did the skill answer correctly? is L2 misclassifying?" A small eval setup (log routing decisions, thumbs-up/down, replay past messages against a new prompt) is what lets the system *improve with confidence over years* instead of by guesswork. This is what separates a toy from a tool that gets better with age.
- **Home Assistant bridge** (was in the earliest TODOs, then dropped). Natural-language control of lights/locks/climate, and the assistant gains home state as context ("garage still open at 8pm — close it?"). Makes the hub the brain of the house, not just a chat app.
- **Life-logging with correlation.** A habit/health log (sleep, workouts, weight, mood) queryable across years — "how did my running correlate with my mood last winter?" Uniquely possible because you own all the data.
- **Voice/phone as a first-class interface.** STT/TTS exists in-app; the next step is a phone-call interface (e.g. Twilio) or an always-listening ambient home mode.
- **Data portability & legacy** ("lasts a lifetime" taken literally): one-command full export (markdown + SQL) so there's never lock-in, plus a documented recovery/handoff path for continuity (or family access).
- **Multi-user / family done right** (Manon onboarding is already listed): shared vs. private workspaces, shared shopping list + calendar, per-user memory.

### 8.6 Suggested sequence

1. **Foundation blockers** (§8.2): schema consolidation → scoped DB roles + `ask-db` sandbox → CI.
2. **Semantic memory** (§8.3): pgvector + local embeddings — the multiplier for everything after.
3. **First features on top:** proactive capture + entity-centric recall (§8.4 memory), then warranty vault + financial foresight.
4. **Then the compounding/non-obvious bets** (§8.5): eval harness, Home Assistant bridge, life-logging.

---

## 9. Cost & Model Economics — API vs. Frontier Subscriptions

This section answers the follow-up: *can the app's metered API usage replace a $20/mo frontier subscription (Claude/Gemini), or is that cost-prohibitive?*

### 9.1 Current Claude API pricing (per 1M tokens, verified 2026-06-08)

| Model | Input | Output | Role in this app |
|---|---|---|---|
| Haiku 4.5 (`claude-haiku-4-5`) | $1 | $5 | L2 classification |
| Sonnet 4.6 (`claude-sonnet-4-6`) | $3 | $15 | L3 reasoning (default) |
| Opus 4.8 (`claude-opus-4-8`) | $5 | $25 | hardest L3 tasks only |

Two discounts dominate the math: **prompt caching** drops repeated context (system prompt + conversation history) to ~10% of input price (90% off reads); the **Batch API** is 50% off for non-interactive jobs.

### 9.2 The verdict: usage-dependent, but the app almost certainly wins for personal use

The README reports current spend at **~$2–5/mo** — because L1/L2/L3 routing already keeps most traffic free (L1) or near-free (L2 Haiku). The real question is heavy, all-the-time use. A realistic model:

- A cached L3 Sonnet message (~4K context, mostly cache-read, +800 output) ≈ **$0.015**.
- $20/mo buys ~**1,300 Sonnet reasoning messages/month ≈ 43/day**, on top of unlimited free L1 and ~free L2.
- On Opus 4.8 (1.67× Sonnet), that's ~**27 reasoning messages/day** for $20.

So:
- **Light-to-moderate use (< ~40 heavy reasoning messages/day):** API wins decisively — **$5–15/mo** *and* it has your personal data, which no subscription can match.
- **True power use (constant long Opus conversations, all-day deep research):** a flat $20 sub can be cheaper for that specific firehose (it's all-you-can-eat), but loses the personal-data integration.

### 9.3 Optimization levers (biggest first)

1. **Verify prompt caching is actually working — the single biggest win.** Cache the system prompt + conversation history so repeated context bills at 10%; this cuts L3 input cost 70–80%. Check `cache_read_input_tokens` is non-zero on responses — if it's zero, a silent invalidator (timestamp, unsorted JSON in the prefix) is defeating it. The router hand-rolls the Anthropic call, so this is fully in your control.
2. **Keep tuning L1/L2 routing** — every message kept off L3 is free or ~$0.0003.
3. **Push more to local Ollama** (free marginal cost) — summarization, dedup, simple classification, bounded only by the mini-PC's CPU.
4. **Batch API (50% off) for non-interactive jobs** — the nightly categorizer, morning briefing, and backfills aren't latency-sensitive; run them through Batches.
5. **Model tiering** — default L3 to Sonnet 4.6, reserve Opus 4.8 for genuinely hard tasks. (Note: `config.py` has `SONNET_MODEL = "claude-sonnet-4-5-20250514"`, a stale/incorrect ID — that date is the Sonnet 4 era. Move to the current `claude-sonnet-4-6` / `claude-opus-4-8` aliases.)
6. **Trim context** — summarize/compact old turns instead of resending full history every turn.

### 9.4 Recommendation: absorb the routine load, keep one sub for the buffet features

Don't frame it as "sunset all subscriptions." Replicating a frontier app via raw API (deep research, image generation, voice, Projects, polished native apps) is costly and a lot of work. Instead:

1. **Let the app absorb everything it's good at** — personal-data tasks, routed skills, anything touching finances/inventory/knowledge. Cheaper than $20/mo here *and* strictly better because it has your data.
2. **Keep exactly one frontier subscription** for the features the app can't cheaply replicate.
3. **Measure for one month** using the existing `api_usage_log` (your ground truth), after applying caching + batch. Likely landing: **~$8–20/mo** all-in at heavy use — enough to drop one $20 sub and keep a frontier app for features, not chat.

### 9.5 Routing observation — the email+calendar flight lookup that hit L3

A real example worth recording: a command to *"look through my email and calendar to find a flight"* routed to **L3** (full Sonnet reasoning) when it should be cheaper. The owner's instinct is right that this is a routine lookup that shouldn't cost full reasoning — but the fix is **not a simple L2 threshold tweak**, and it's worth being precise about why:

- L2 by design classifies intent → picks **exactly one** skill → formats the result (`router_engine.py` `CLASSIFICATION_PROMPT`). The classifier is explicitly instructed to return `null` and escalate for "questions that clearly need multiple data sources combined."
- This request spans **two** data sources (email *and* calendar) plus synthesis, so under the current architecture it *correctly* escalated to L3. Forcing it to L2 as-is would make L2 pick one skill and miss half the task.

The right fixes (either, ideally both):
1. **Composite skill** — build a single `find-travel` / `flight-lookup` skill that internally queries both email and calendar and returns a combined result. Then L2 can route to that one skill cheaply (and deterministically). This is the fastest win for this specific recurring pattern.
2. **Skill chaining at L2** (already a noted TODO) — let L2 invoke a small fixed sequence of read-only skills and combine their outputs without paying for a full L3 reasoning turn. This generalizes beyond flights to any "combine 2–3 personal-data sources" lookup.

A cheaper interim option: keep it on L3 but route these bounded multi-source lookups to a **Haiku-tier L3** (or low `effort`) instead of full Sonnet — they need orchestration, not deep reasoning. The broader lesson for the eval harness (§8.5): instrument which messages escalate to L3 and why, so over-escalation patterns like this surface as data rather than anecdote.

### 9.6 Model IDs should be discovered, not hardcoded (planned fix)

Hardcoded model IDs violate the project's core "no hardcoding / DB-driven everything" ethos (Rule #1 in the steering doc) and are a standing source of silent breakage — when Anthropic deprecates an ID, every hardcoded reference breaks at once. The codebase currently hardcodes models in several places:

- `config.py` — `HAIKU_MODEL`, `SONNET_MODEL` (already stale: `claude-sonnet-4-5-20250514`), `LOCAL_MODEL`.
- `services/finance.py` `ask_db` — inline `"claude-haiku-4-5"`.
- Every n8n workflow — `claude-haiku-4-5-20251001` hardcoded (flagged in the June 5 steering review as item #6).

**Intended design (planned next session):** the tool should auto-update to the latest models rather than pin strings.
- Discover models at runtime via the **Models API** (`GET /v1/models` → `client.models.list()` / `client.models.retrieve(id)`), which returns current IDs, context windows, capabilities, and supports capability filtering. `model_provider.py` already does partial dynamic discovery — extend it to be the single source.
- Persist the discovered catalog to the existing model tables (`bh_model_rates`, migrations 004/005) on a schedule.
- Reference models **by role/alias resolved from the DB** ("current Haiku", "current Sonnet", "current Opus") everywhere — `config.py`, `ask_db`, router tiers, n8n — never by literal string. Adding/swapping a model becomes a DB update, consistent with how slash commands and skills already work.
- This also dissolves the n8n hardcoding (item #6) as those skills migrate to native Python that reads the DB-backed catalog.
