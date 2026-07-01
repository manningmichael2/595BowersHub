# n8n Decommission — Requirements

## Overview

Remove 595BowersHub's runtime dependency on **n8n** and retire the container. The skill/automation migration to in-process Python is ~90% done — native `@native_skill` handlers + ~12 `apscheduler` jobs already own categorization, simplefin sync, transfer-link, insights, embeddings, budgets, inbox, reminders, briefing, and model discovery. Because skill dispatch matches a **native handler by name before** falling through to the `webhook_url` (`skill_executor.py:146-153`), most `/webhook/…` skill rows are already dead URLs. The genuinely-remaining n8n runtime calls are a small set — chiefly the **smart-capture** extract/commit pipeline behind Quick Capture — plus the boot-time `N8N_BASE` requirement and a few cosmetic health/dashboard references.

Why now: the design review's "n8n is a zombie" item and the standing **n8n→code** direction (steering: "let n8n shrink toward retirement"). Retiring it removes a heavy always-on container and a second, weaker code path.

This spec is a **strangler-fig** migration: stand up native beside n8n, flip the `bh_skills` row, soak with rollback-by-row available, then remove. **n8n keeps running until the final owner-gated cutover.**

---

## Feature 1: Authoritative inventory (know exactly what still calls n8n)

### R1.1 — Enumerate every runtime n8n touchpoint from code
The system's n8n touchpoints are listed with evidence: `skill_executor.py:52,150-199` (webhook dispatch), `config.py:35,129,174` (`N8N_BASE` required at boot), `routers/quick_capture.py:146-242` (extract/commit), `routers/db_browser.py:3942-3943` + `:4228-4326` (smart-capture URL builder **and** the `/inbox/ai-extract` + `/inbox/url-extract` consumers — second/third callers, easy to miss), `services/healthcheck.py:25,141,185` + `router_engine.py:992` (health). `hook_engine._action_call_webhook` is a generic user-webhook action, **not** an n8n dependency — explicitly out of scope.

### R1.2 — Audit prod `bh_skills` for rows that are *neither* native *nor* name-intercepted
Because dispatch is name-first, a `/webhook/…` row is only a true n8n call if **no `@native_skill` of the same name is registered**. The audit identifies exactly those rows from the **live prod DB** (migrations are misleading — baseline rows still read `/webhook/` for already-native skills). Expected result, to confirm: `smart-capture-extract`, `smart-capture-commit`, `process-asset`, and `override-category` (`/webhook/update-category`, likely orphaned). Output: a recorded `{name, webhook_url, has_native_handler, disposition}` table. Requires a read-only prod query (owner-run or via `ask-db`).

### R1.3 — Confirm n8n's own scheduled/trigger workflows (with a defined method)
The active workflows inside n8n that fire on schedule/webhook and are NOT covered by an `apscheduler` job are identified **via the n8n UI/API: the active-workflow list + each workflow's execution history** (owner-run, since this is otherwise unfalsifiable). Candidates: `email-receipts-importer`, `api-usage-logger`. Each is marked `port-required` or `already-covered` (citing the covering job/handler) before decommission.

### R1.4 — No silent coverage gaps
Every touchpoint and skill row from R1.1–R1.3 has a recorded disposition — `already-native` (cite the replacement), `port-required` (becomes a task), or `cosmetic-remove`. The inventory is written to `.kiro/specs/n8n-decommission/inventory.md`. No item is dropped without a recorded decision. (Read-only phase; no production change.)

---

## Feature 2: Port smart-capture to native Python (the one real feature port)

### R2.1 — Native smart-capture extract (text-first)
The system extracts structured intents from Quick-Capture **text** in-process (replacing `/webhook/smart-capture/extract`), via the project `model_provider`, returning the exact shape the overlay consumes: `{ ok, intents:[{domain, summary, payload, needs_more_info}], asset?, raw_text?, extract_token }` (per `quick_capture.py:146-196` + the n8n `Build Classify Prompt` node). The ported prompt + domain allow-list (inventory{tool,router_bit,saw_blade,wood,album,manual}, house room, recipe, cook_log, shopping_list, knowledge_fact, project, other) match the workflow.

### R2.2 — `extract_token` is **fixed**, not faithfully ported (security)
The native pipeline mints and **actually verifies** a signed `extract_token` (real HMAC-SHA256, ≤32-byte secret from config/DB — **not** the hardcoded `"sc-extract-v1-595bowers"`; preserve the 30-min expiry). n8n's commit validator only checked presence/format/expiry and never recomputed the HMAC (`smart-capture.json` `Validate Commit`) — the root of the logged "agent fabricates commit payloads" incident. The token is signed over the **full set** of extracted intents (canonicalized) **plus the acting `user_id` + `workspace_id`** — so commit authorizes the workspace/user from the *token*, never from the client-supplied body (critical in the shared Michael/Manon household). Commit **rejects** expired, tampered, and wrong-workspace/user tokens.

### R2.2a — Per-intent commit: membership + idempotency (no equality, no replay)
The overlay calls commit **once per accepted intent** (`quick_capture.py:79-85,207`), so each call carries one intent against a token minted over all of them. Verification is therefore **membership** — the committed intent must be a member of the token's signed set — **not** equality (equality would reject every legitimate per-intent commit). Because the same valid token is reused across N calls and is replayable within its 30-min window, commit is **idempotent per (token, intent)**: a stable dedup key (e.g. hash of token + canonical intent) prevents a client retry or replay from writing duplicate rows. The replay window (= token lifetime) is stated explicitly.

### R2.3 — Native smart-capture commit routes to existing native actions
Commit (replacing `/webhook/smart-capture/commit`) verifies the token (R2.2), then writes each accepted intent through native paths — reusing existing services, **not** reimplementing writes where one exists:
- `shopping_list` → `lists.route_and_add` (the native `bh_lists` system) — **fixing** the workflow's divergent markdown write.
- `knowledge_fact` → `knowledge.remember` + `knowledge_graph.remember_entity` (eliminating the workflow's n8n→`/webhook/remember` hop).
- inventory / cook / house domains → **parameterized** INSERTs into `inventory.*`, `cook.*`, `house.*` (the workflow uses string-interpolated SQL and no native helper exists — the port must use parameterized SQL / `_quote_ident`, project rule).
- A user dropping an intent in the confirm step commits only the kept intents (a single commit per kept intent, R2.2a).

### R2.4 — Image extract may ship after text (coupling acknowledged)
Image-based extract internally invokes Process Asset (vision). Text-only extract (R2.1) may cut over first; image extract is gated on the Process-Asset port (R3.1) so the native path has full parity before the image path flips. The split is explicit, not silent.

### R2.5 — Engine switch + register handlers + repoint **all** consumers
Native handlers are registered for smart-capture extract + commit. Cutover/rollback is driven by a **DB-driven `smart_capture.engine` setting** (`n8n | native | shadow`, default `n8n`), which the handler consults (see R2.6) — *not* by flipping `webhook_url` (which is inert under name-first dispatch). All consumers call the native skills: `quick_capture.py` extract/commit **and** `db_browser.py` `/inbox/ai-extract` (`{image_path,text,domain_hint}`) **and** `/inbox/url-extract` (`{url,columns}`). Each consumer's existing **response shape** is preserved (the inbox consumers read a different shape than the overlay's `{intents:[…]}` — repointing must not silently change what each UI reads; confirm whether url-extract actually scrapes the URL or just passes text, and replicate that exactly). The raw-note fallback (`quick_capture.py:245-294`) is retained unchanged.

### R2.6 — Dispatch reality: the handler owns the engine choice
Because `_try_native_skill` matches by **name** and returns before `webhook_url` is read (`skill_executor.py:146-153,214-218`), registering the native handler makes it the live dispatch point immediately. The handler therefore **internally** chooses per the `smart_capture.engine` setting: `native` runs in-process; `n8n` proxies to the existing webhook (using `N8N_BASE` while it still exists); `shadow` runs native **and** proxies, returns n8n's result, and logs a structured diff (this is what makes R6.2 achievable). Flipping the setting is the cutover/rollback control — no redeploy, no `bh_skills` edit.

### R2.7 — Dependency failure contracts (filewriter / model_provider)
Behavior is specified when a dependency fails on either path: **extract** — if `model_provider` errors/times out, the overlay gets the raw-note fallback (existing) and the inbox consumers get a clear error (no silent empty result); **commit** — a per-intent write that fails (DB, or filewriter for an asset/markdown target) returns that intent's failure to the client without claiming success, and does not leave a half-written intent (each intent commit is atomic; an orphaned asset is logged for cleanup). No partial success is reported as success.

### R2.8 — Input bounds
Extract enforces a max input size; an oversized capture is rejected (or truncated with a recorded marker) rather than silently producing truncated/invalid JSON at `max_tokens`. Malformed/truncated model output degrades to a clear error + raw-note fallback, never a partial commit.

---

## Feature 3: Port or retire the remaining webhooks

### R3.1 — Process Asset (vision) ported or natively invoked
`process-asset` (`/webhook/process-asset`) is implemented as a native handler (or a native vision call smart-capture's image path uses), since image extract depends on it. The row flips to `native://` (or is removed if folded into smart-capture).

### R3.2 — `override-category` resolved (with a defined orphan check)
`override-category` (`/webhook/update-category`) is resolved by an explicit evidence bar, not assertion: (a) grep the app/frontend for `update-category` / the skill name; (b) check the n8n workflow's execution history for recent calls; (c) inspect `api_usage_log` over a window. If unreferenced → **retire** the row (deactivate); if a live caller exists → port native (it is superseded by native `categorize-*`/`commit-bulk-update` in `category_override.py`). The evidence + decision are recorded in `inventory.md`.

### R3.3 — Scheduled n8n workflows ported or confirmed covered
Each active n8n schedule from R1.3 is either added as an `apscheduler` job or documented as already covered. After this, **no n8n workflow is the sole owner of any behavior.**

### R3.4 — Skill dispatch no longer reaches n8n (guard lands at decommission, not before)
After R2.5 + R3.1–R3.2 and a clean soak, no `bh_skills` row routes to an n8n webhook. The dead-webhook guard (`skill_executor` raises a clear `SkillExecutionError` if a `/webhook/` skill is invoked) lands **only at/after decommission (Feature 5)** — never during the soak, since it would break the `smart_capture.engine=n8n` rollback path (R6.3). Until then, the webhook branch stays functional as the rollback target.

---

## Feature 4: Make the app n8n-free at boot and in surfaces

### R4.1 — `N8N_BASE` optional at boot
`config.py` no longer requires `N8N_BASE` (drop from `_REQUIRED`; keep the `""` default). The app boots and `/health` is green with `N8N_BASE` unset. Empty is treated as "n8n not configured" without crashing.

### R4.2 — Remove the n8n health surface (after the soak)
`healthcheck.check_n8n` + its registry entry and the `/health --n8n` flag (`router_engine.py:992`) are removed; `/health` reports no n8n component. **Sequenced after the soak** — while n8n is still the rollback target (R6.3), keep its health probe so the fallback path stays observable.

### R4.3 — Dashboard no longer depends on n8n
`dashboard/app.py` `proxy_n8n` and the n8n-webhook path of `/api/anthropic-spend` are removed (the latter already has a Postgres `api_usage_log` fallback, `admin.py:313`); `index.html` drops the n8n UI link.

---

## Feature 5: Decommission the container and delete the artifacts (owner-gated)

### R5.1 — Stop the live n8n in Portainer
The running n8n lives in the **Portainer `ai-services` stack**, NOT the repo `infrastructure/docker-compose.yml` (which is diverged and deploys nothing live). The container is stopped/removed **in Portainer by the owner**; removing the `n8n` service from the repo compose is documentation-only. This is the one irreversible, deploy-side step — done only after Features 2–4 ship and soak.

### R5.2 — Delete workflow artifacts
`n8n-workflows/` (build scripts, `.json` exports, `_config.py`) and dead references are removed; the n8n export is retained somewhere recoverable (escape hatch) per the decommission checklist. `archive/n8n-workflows-deactivated/` is already archived (out of scope).

### R5.3 — Drop `N8N_BASE` from config & deploy
`N8N_BASE` is removed from `config.py`, `*.env.example`, and the live deploy secrets after R4.1 lands.

---

## Feature 6: Verification, parity & rollback

### R6.1 — Parity gate before cutover
A golden corpus of representative captures asserts native extract produces schema-valid intents **semantically equivalent** to expected (compare canonical/normalized fields with tolerance — NOT exact string/LLM equality), and commit produces the expected rows. The corpus covers: grocery text, a multi-intent note, an image receipt, ambiguous + empty edges, an **oversized** capture, **and both `db_browser` inbox shapes** (`/inbox/ai-extract` image_path/text/domain_hint and `/inbox/url-extract` url/columns) asserting the *response shape each consumer reads*. The deterministic glue (token mint/verify, membership + idempotency, DB writes, image handling) gets exact-assertion unit tests. This gate blocks the cutover.

### R6.2 — Shadow run before flipping
With `smart_capture.engine = shadow` (R2.6), the handler runs native **and** proxies to n8n, returns n8n's result to the user, and logs a structured diff. The engine is held in `shadow` on real captures until the native-vs-n8n parity-failure rate is zero for the soak window, then flipped to `native`. (This is achievable precisely because the handler owns dispatch — there is no separate shadow plumbing to build.)

### R6.3 — Reversible until decommission; rollback is a setting flip
Cutover/rollback is flipping the `smart_capture.engine` DB setting (`native` ↔ `n8n`) — **no redeploy, no `bh_skills` edit**. This works because the native handler proxies to n8n while the setting says `n8n` (R2.6); flipping `webhook_url` would NOT roll back, since name-first dispatch ignores it. For an in-flight overlay (extract under one engine, commit under another), the `extract_token` format + secret are identical across native and the n8n path during the soak (or the verifier accepts both), so a mid-cutover session is not broken. n8n stays running and the engine can return to `n8n` right up until R5.1 — the only irreversible step.

### R6.4 — Boots without n8n
An asserted check that the app starts and `/health` is green with `N8N_BASE` unset and no n8n container reachable.

---

## Acceptance Criteria

- [ ] `inventory.md` lists every n8n touchpoint + skill row with a recorded disposition; the prod `bh_skills` audit (R1.2) and n8n active-workflow list (R1.3) are captured by their defined methods.
- [ ] With `smart_capture.engine=native`: Quick Capture (overlay extract→confirm→commit, PWA share target) **and** both `db_browser` inbox consumers run fully native, each preserving the response shape its UI reads; the raw-note fallback still works.
- [ ] Native commit writes through `lists.route_and_add` / `knowledge.remember` / parameterized domain INSERTs; no string-interpolated SQL.
- [ ] `extract_token` is HMAC-verified with a config-sourced secret and **binds user+workspace**; commit verifies the intent is a **member** of the signed set and is **idempotent per (token, intent)**; expired/tampered/wrong-workspace/replayed commits are rejected (regression-tested).
- [ ] Parity corpus (incl. both inbox shapes + an oversized case) passes; `engine=shadow` shows zero native-vs-n8n parity failures for the soak window before the flip to `native`.
- [ ] Flipping `smart_capture.engine` between `n8n` and `native` switches behavior with no redeploy (rollback verified).
- [ ] App boots + `/health` green with `N8N_BASE` unset; no n8n component in `/health`.
- [ ] The migration (next free number — `0058` at time of writing, confirm at impl) seeds the `smart_capture.engine` setting + token secret, applies on `fresh_db`, idempotent, green under CI `test_migrate_as_app_role.py` (scoped migrator role).
- [ ] After owner soak: n8n stopped in Portainer, `n8n` removed from repo compose, `n8n-workflows/` deleted (export retained), `N8N_BASE` dropped from config/secrets, dead-webhook guard + n8n health surface removed.

## Non-Functional Requirements

- **No hardcoding:** the `extract_token` secret and any new config are DB/env-driven, never code constants (Project rule #1). The skill native↔n8n switch stays a `bh_skills` row, not a code flag.
- **Data safety:** all commit-path SQL is parameterized (identifiers via `_quote_ident`); the row-flip is a forward-only, idempotent migration applied on `fresh_db`; rollback is a row update through Feature 4.
- **Security:** real HMAC verification on commit (closes the fabricated-payload bug); least-privilege migrator/runtime roles preserved; n8n export retained for recovery.
- **Performance / cost:** native extract is one `model_provider` call (Haiku-class, max_tokens ~2048, per the workflow) — no added hops; commit reuses existing services.

## Constraints & Assumptions

- Runs on the Minisforum over Tailscale; **live n8n is the Portainer `ai-services` stack**, so the decommission is an owner action in Portainer — the repo compose/`deploy.sh` are not the live control plane.
- Next free migration number is **0058** at time of writing — confirm against `backend/migrations/` at implementation and reserve a contiguous block if multiple are needed; migrations auto-apply on startup and must pass the scoped-role CI gate (`test_migrate_as_app_role.py`).
- DB-backed tests use `fresh_db` (+ throwaway `pgvector/pgvector:pg16` locally if no DB is reachable).
- Deploy/owner-gated steps: the prod `bh_skills` query (R1.2), the smart-capture flip soak, and the Portainer container removal (R5.1).

## Dependencies

- **Process Asset / vision port (R3.1)** must land before image-extract cutover (R2.4).
- `model_provider`, `lists.route_and_add`, `knowledge.remember`/`remember_entity`, and the `@native_skill`/`skill_registry` mechanism (all existing) are reused.
- No dependency on other open specs; PRs #55–#58 already merged.

## Success Metrics

- **n8n runtime calls from the app:** → 0 (verified: no `bh_skills` row routes to a webhook; `N8N_BASE` unset and app healthy).
- **Smart-capture parity:** ≥ target field-level agreement vs the golden corpus, 0 schema violations, 0 shadow-run parity failures in the soak window before flip.
- **Container footprint:** the n8n container removed from the live stack after soak.
- **Security:** 100% of commits require a valid HMAC `extract_token` (fabricated/expired payloads rejected in tests).
