# n8n Decommission — Design

> Satisfies `requirements.md`. Requirement IDs referenced inline. Synthesized from a 3-approach tournament (minimal-change / ideal-architecture / risk-first); the key trade-off decisions are recorded at the end.

## Architecture Overview

The remaining n8n dependency is the **smart-capture** pipeline (extract → per-intent commit) plus `process-asset`; everything else is already native. This design ports smart-capture in-process behind a **DB-driven engine switch**, using a strangler-fig rollout where n8n stays the reachable fallback until a clean soak, then is decommissioned.

**The linchpin fact:** skill dispatch is *name-first* — `skill_executor._try_native_skill` (`skill_executor.py:146-153,214-218`) matches by skill **name** and returns before `webhook_url` is read. So **registering a native handler under the existing skill name *is* the cutover**, and flipping `bh_skills.webhook_url` is inert. The engine choice therefore lives **inside the handler**, driven by a `smart_capture.engine` setting (`n8n | native | shadow`) — mirroring the project's existing DB-driven engine switch for the categorizer (`categorization/config.py` + `orchestrator.py` `shadow = engine=='shadow'`).

```
PWA / overlay ─┐                       ┌─ engine=n8n     → proxy to N8N_BASE/webhook/…  (rollback target)
Quick Capture  ├─ execute("smart-      │─ engine=native  → in-process extract/commit
db_browser     │   capture-extract/    ├─ engine=shadow  → run native + n8n, return n8n, log diff (extract only)
 inbox extract ─┘   commit")           └
                        │
        name-first dispatch → NEW services/smart_capture/*  → model_provider (extract)
                                                            → list_router / knowledge / parameterized INSERTs (commit)
                                                            → bh_platform_settings (engine + token secret)
                                                            → bh_smart_capture_commits (idempotency)
```

**New vs reused:** *New* = a small `services/smart_capture/` package + a `@native_skill` registration module + migration `0058`. *Reused verbatim* = `skill_registry`/dispatch, `model_provider` (`resolve_role("fast")`, Haiku-class), `list_router.route_and_add`, `knowledge.remember` + `knowledge_graph.remember_entity`, `_quote_ident`, `bh_platform_settings`, `get_http_client`.

## Components

### `services/smart_capture/` (new package — the one substantial addition)
A handful of focused, unit-testable modules (deliberately **not** a plugin framework — see decisions):
- **`config.py`** — `get_engine(conn) -> 'n8n'|'native'|'shadow'` (default `n8n`, unknown → `n8n` fail-safe) + `get_token_secret(conn) -> bytes`. Reads `bh_platform_settings`, mirroring `categorization/config.py`. (R2.6)
- **`intents.py`** — frozen `CaptureIntent{domain,summary,payload,needs_more_info}` with a **single** `canonical()` (`json.dumps(sort_keys, separators=(',',':'))` over `{domain,payload,asset_id}`) and `hash()` (`sha256(canonical)`). Including `asset_id` in the canonical form **binds the asset into the token** so it can't be swapped at commit (fixes the confused-deputy gap: commit's `asset_id` is validated against the signed hash, not trusted from the body). The one canonical form used by both token mint/verify + the parity gate. (R2.2/R6.1)
  **Membership assumes drop-only confirm:** the overlay commits `intent.payload` unchanged and only lets the user *drop* intents via `accepted[]` checkboxes (`QuickCaptureOverlay.tsx:140,316` — verified), so exact-hash membership holds. If an edit-before-commit UI is ever added, commit must re-mint (recorded as a constraint).
- **`tokens.py`** — `mint(intents, user_id, workspace_id, secret, now)` / `verify(token, committed_intent, committed_asset_id, user_id, workspace_id, secret, now)`. Real **HMAC-SHA256** (stdlib `hmac`, `compare_digest`) over a self-describing payload `{v, ts, uid, wid, ih:[per-intent hash…]}`. Verify recomputes the HMAC (rejects **tamper**), checks 30-min expiry (rejects **expired**), checks `uid/wid` == the auth-resolved acting user/workspace (rejects **wrong-workspace**), and checks `hash(committed_intent, committed_asset_id) ∈ ih` (**membership** incl. asset — rejects a swapped asset; not equality — R2.2/R2.2a). The secret is stored as 64 hex chars and **hex-decoded to 32 bytes** by `get_token_secret` (pin the decode so mint/verify agree — m5).
- **`prompt.py`** — the ported classify prompt + `DOMAINS` allow-list, verbatim from the `Build Classify Prompt` node, as the single source of truth (replaces the JSON `jsCode` string). (R2.1)
- **`extract.py`** — `extract_native(text, image_path, domain_hint, user_id, workspace_id, model_provider, conn)`: one `model_provider.complete(resolve_role("fast"), max_tokens≈2048)`; reproduces `Parse Classification` fence-strip + `other`-fallback; enforces a **max input size** (R2.8); returns `{ok, intents, asset?, raw_text?, extract_token}` (token minted here). On model error → `{ok:false, error}` (drives the overlay raw-note fallback + a clear inbox error — R2.7).
- **`commit.py`** — `commit_native(domain, payload, asset_id, extract_token, user_id, workspace_id, conn)`: verify token → **idempotency guard** → route to a **committer function** (below). For DB-backed domains the dedup row + the write are in one `conn.transaction()` (R2.7 atomicity). **Idempotency mechanics (m3):** `INSERT INTO bh_smart_capture_commits(dedup_key, result_json) … ON CONFLICT (dedup_key) DO NOTHING`; if 0 rows inserted, `SELECT result_json` and return it (a replay returns the original success, writes nothing). Per-intent result `{ok, domain, record_id|error}`; partial success is never reported as success.
- **committers** — explicit functions (not a registry), covering **every** DOMAIN in `prompt.py`. Several are genuinely bespoke (a single generic INSERT can't express them — M2):
  - `shopping_list → list_router.route_and_add(items, user_id)` (**fixes** the n8n markdown divergence).
  - `knowledge_fact → knowledge.remember + knowledge_graph.remember_entity` (drops the n8n→`/webhook/remember` hop).
  - **`project`, `other` → knowledge/markdown** (their n8n targets are markdown, not a table) — routed to `knowledge.remember` (searchable, deduped) rather than a raw file append. Closes the M1 gap (extract can emit these).
  - `tool/router_bit/saw_blade/wood/album/manual → insert_typed(conn, spec, payload, asset_id)` — parameterized `INSERT` (`$1,$2…`), identifiers via `_quote_ident`, per-domain `TableSpec`; **`_extra_fields` are folded into the row's `notes`** (preserving the n8n `Plan Commit` behavior — M2), and the `*_files` asset-link row is written from the (token-bound) `asset_id`.
  - **`house_room` → upsert** (`INSERT … ON CONFLICT (name) DO UPDATE`) so re-capturing a room doesn't duplicate (bespoke — M2).
  - **`recipe` → dedicated committer** (slug generation + ingredients/method flattened into the recipe row, per n8n) (bespoke — M2).
  - **`cook_log` → dedicated committer** (resolves `recipe_id` via a parameterized recipe lookup before insert — bespoke — M2).
  - No string-interpolated SQL survives; all identifiers via `_quote_ident`, all values bound (R2.3, NFR).
  - **Non-DB idempotency (m3):** `shopping_list`/`knowledge_fact`/`project`/`other` write through services outside a single SQL txn, so their dedup relies on those services' existing content-dedup (e.g. `knowledge.remember` de-dups by content; list add is set-like). The `bh_smart_capture_commits` guard still short-circuits an exact (token,intent) replay before the service call.
  - **Asset orphans (m3/R2.7):** if a DB row commits but its filewriter asset-link fails, the orphan is recorded in a structured log line with the `asset_id` + `dedup_key` (no janitor table for v1 — logged for manual/later reconcile), and the intent is reported failed.
- **`engine.py`** — `run_extract(params,…,config)` / `run_commit(params,…,config)`: the engine branch, reading `get_engine()` per call.
  - **extract** — `native`→in-process; `n8n`→`_proxy_n8n` (httpx to `N8N_BASE/webhook/…`, the rollback path); `shadow`→run native **and** proxy, **return n8n's body**, and mint the native token **over n8n's returned intents** (not native's) so body + token agree (fixes B1: otherwise a native≠n8n divergence would return n8n intents whose hashes ∉ a native-minted token → every divergent commit rejected). The native extract output is used **only** for the logged diff (R6.2). All circulating tokens are thus native-HMAC before cutover (R6.3 continuity).
  - **commit** — has **no shadow/proxy double-write path** (shadowing commit would write rows twice). Under `native` **and** `shadow`, commit runs **native** and verifies the (native) token; under `n8n`, commit proxies to n8n. This defines commit behavior during the S2 shadow soak (fixes B2). Note: because commit is native whenever `engine≠n8n`, the token secret/format is identical across the engines a session might span (R6.3).
  - **Image sub-path (M4/R2.4):** a global engine flip would cut text and image over together, but native vision (`process-asset`) may not be ported yet. So under `engine=native|shadow`, an **image**-based extract whose `process-asset` port hasn't landed **proxies that request to n8n** (a narrow, explicit per-request fallback gated on a `smart_capture.process_asset_native` setting), while text extract runs native. This lets text cut over first (R2.4) without breaking image capture in the overlay or `/inbox/ai-extract`. Once R3.1 lands, the flag flips and image goes native too.

### `services/skills/smart_capture.py` (new — ~30 lines)
Auto-discovered by `skill_registry.discover_skills()`. Thin `@native_skill("smart-capture-extract")` / `("smart-capture-commit")` (+ later `("process-asset")`) wrappers that read the injected context and delegate to `engine.run_*`. (R2.5/R2.6)

### `skill_executor._try_native_skill` (edit — the only dispatch-core change)
Currently injects only `{**params, "_user_id": user_id}` (`:222`). Thread the extras the handler needs: add `workspace_id` to `_try_native_skill` (pass at `:146`; `execute` already has it at `:113`) and inject `"_workspace_id"`, `"_config": self.config`, `"_model_provider": <cached provider>`. Extra keys are ignored by all other handlers — non-breaking.

### Consumer repoints (edits)
- `quick_capture.py` extract/commit already call `executor.execute("smart-capture-…")` (`:175,224`) → **zero functional change**; native on registration. Raw-note fallback (`:245-294`) untouched.
- `db_browser.py` `/inbox/ai-extract` (`:4228`) + `/inbox/url-extract` (`:4290`) currently httpx-POST to `_get_smart_capture_url` and **bypass dispatch** → repoint through `executor.execute("smart-capture-extract", …)`. **Preserve each response shape** (they read the raw extract dict, not the overlay `{intents}` serialization). `/inbox/url-extract` **does not scrape** — it wraps the URL in a text prompt (`:4300-4312`); replicate exactly. Delete `_get_smart_capture_url` once both are repointed. **Workspace (m4):** these routes are `require_admin` with no workspace context; they pass a defined workspace — the `smart_capture.inbox_workspace_id` setting if set, **else resolved at runtime** to the admin's default workspace by query (never a hardcoded id — NO-HARDCODING) — so the token is `wid`-bound like any other capture.

### Process Asset — native vision (R3.1/R2.4) — the second port
`process-asset` (no native handler today) is a **second real port**, not a footnote. Design: `services/smart_capture/process_asset.py` mirrors the n8n `process-asset.json` — a `model_provider` **vision** call (image → `ai_summary` + `ai_extracted` structured fields), a **parameterized** insert into the existing `assets` tables, and the dedup/move logic (hash-based). Registered as `@native_skill("process-asset")`. `extract_native`'s image branch calls it in-process (replacing the n8n `Run Process Asset` sub-workflow). Gated by `smart_capture.process_asset_native` (default off): while off, image extract proxies to n8n even under `engine=native` (the M4 fallback); flipping it on cuts image over. This is sequenced as its own increment after text.

### Supporting changes for Features 1, 3, 4 (non-smart-capture)
- **R1 inventory** → the `inventory.md` artifact (audit outputs); no code.
- **R3.2 `override-category`** → resolved by the evidence bar (grep app for `update-category`; n8n execution history; `api_usage_log` window). Native `category_override.py` already supersedes it (`skills/finance.py`), so the expected outcome is a follow-up migration **deactivating** the row; port only if a live caller is found.
- **R3.3 scheduled workflows + the `api_usage_log` cross-dependency (M6, important):** confirm `email-receipts-importer` / `api-usage-logger` against n8n's active list. **Critical:** if n8n's `api-usage-logger` is what writes `api_usage_log`, then removing n8n breaks the Postgres fallback the dashboard's `/api/anthropic-spend` relies on (`admin.py:313`). So before R4.3/decommission, verify who populates `api_usage_log` today; if it's n8n, a **native usage logger** (apscheduler job or inline in `model_provider`'s cost-tracking) must land first. Recorded in `inventory.md`; blocks decommission if unresolved.
- **R4.3 dashboard** → remove `proxy_n8n` + the n8n path of `/api/anthropic-spend` (Postgres-only, contingent on the logger above); drop the n8n link in `index.html`. Sequenced at S5.

## Data Flow (representative: multi-intent capture)

1. Overlay/inbox → `execute("smart-capture-extract", {text|image_path, …})` → `run_extract` reads engine → `extract_native` (or n8n/shadow) → model_provider → intents + `extract_token` (minted over **all** intents incl. each intent's `asset_id`; binds uid/wid).
2. User reviews, drops (not edits) one intent → overlay commits **once per kept intent**: `execute("smart-capture-commit", {domain, payload, asset_id, extract_token})`.
3. `commit_native`: `verify(token, this_intent, this_asset_id, uid, wid)` (HMAC + expiry + wid match + **membership incl. asset**) → `dedup_key = sha256(hmac || intent.hash())` → `INSERT … bh_smart_capture_commits ON CONFLICT DO NOTHING`; if 0 rows, `SELECT result_json` and return it (idempotent replay no-op) → else run the committer (same txn for DB domains) → return per-intent status.

## Data Model / Migrations

- **Migration:** `bowershub-ai/backend/migrations/0058_smart_capture_native.sql` (confirm next free number at impl; latest is `0057`). Forward-only, idempotent, applies on `fresh_db`, green under `test_migrate_as_app_role.py` (scoped migrator role).
- **Seeds (`bh_platform_settings`, `ON CONFLICT (key) DO NOTHING`):** `smart_capture.engine = '"n8n"'`; `smart_capture.token_secret = to_jsonb(encode(gen_random_bytes(32),'hex'))` (pgcrypto already present, `0001_baseline.sql:99`) — **DB-driven secret, no code constant** (NFR).
- **New table:** `bh_smart_capture_commits(dedup_key text PRIMARY KEY, result_json jsonb, created_at timestamptz DEFAULT now())` — idempotency (R2.2a).
- **Existing tables written by committers** (no schema change): `inventory.{tools,router_bits,saw_blades,wood,albums,manuals}` + `*_files` link rows, `cook.{recipes,cook_log}`, `house.rooms`, plus `bh_lists`/knowledge via their services.
- **Optional cosmetic:** `UPDATE bh_skills SET webhook_url='native://…'` for the smart-capture rows — **inert** under name-first dispatch (documentation only).

## API / Interfaces

- **Native skills:** `smart-capture-extract` (in: `{text?, image_path?, domain_hint?}`; out: `{ok, intents:[{domain,summary,payload,needs_more_info}], asset?, raw_text?, extract_token}`), `smart-capture-commit` (in: `{domain, payload, asset_id?, extract_token}`; out: `{ok, domain, record_id?|error?}`). Permission/workspace inheritance via `SkillExecutor.execute` (unchanged). Later: `process-asset`.
- **Config surface:** `smart_capture.engine` + `smart_capture.token_secret` in `bh_platform_settings` (admin-editable via the existing settings path). The engine flip is the cutover/rollback control.
- **No new HTTP endpoints** — the three routers keep their current signatures; only their internals change.

## Technology Choices

- **Stdlib `hmac`/`hashlib`, no new dependency** — the membership payload is custom anyway; `hmac.compare_digest` gives constant-time verify. (`itsdangerous`'s `URLSafeTimedSerializer` was considered — cleaner envelope, but a new dep for what stdlib does in ~20 lines; rejected for the household-scale footprint.)
- **Mirror `CategorizerConfig`** for `CaptureConfig` — the project already has a DB-driven engine + shadow pattern; alignment over invention.
- **`model_provider` governed path** (`resolve_role("fast")`, cost-tracked) — one call, no added hops (perf NFR).
- **Engine setting, not `webhook_url` flip, as the switch** — forced by name-first dispatch (see Overview); also keeps rollback a data change, not a deploy (R6.3).
- **Plumbing (m2):** `get_engine`/`get_token_secret`/`commit_native` acquire a connection from the global `get_pool()` (not injected); the handler is injected `_config`/`_model_provider`/`_workspace_id` via the params dict (the existing `_user_id` convention). Like `categorization/config.load_config`, the engine read is **un-cached** — one small `bh_platform_settings` SELECT per dispatch. At 2-user scale this is negligible and is what makes an `engine` flip take effect on the **next** request with no restart (the basis of the R6.3 rollback claim).

## Rollout & Reversibility (the risk-first spine — drives `tasks.md`)

| Step | `engine` | Runs | Gate to advance |
|---|---|---|---|
| **S0** land native, dark | `n8n` | handler registered, proxies 100% to n8n; behavior identical | deterministic unit tests green (token, membership, idempotency, parameterized SQL, both inbox shapes) |
| **S1** offline parity | `n8n` | golden corpus vs native in CI | **≥95% intent field-level agreement** vs golden, **0 schema violations**, oversized + both inbox shapes covered (R6.1) — **blocks S2** |
| **S2** shadow | `shadow` | native+n8n, n8n authoritative, native token minted, diff logged | **≥7-day soak (or ≥50 real captures)** with **0 native-vs-n8n structural-parity failures** (R6.2) — **blocks S3** |
| **S3** cutover | `native` | native authoritative; n8n untouched & reachable | error/commit-success/raw-note rates at baseline; any regression → flip to `n8n` (one row) |
| **S4** soak | `native` (rollback `n8n` live) | n8n container + health probe + webhook branch all still present | clean window, no rollbacks — **blocks S5** |
| **S5** decommission (owner) | — | owner stops n8n in Portainer; **then** guard + health/dashboard removal + `N8N_BASE` optional/dropped land | irreversible; only after S4 |

**Hard ordering rule (R3.4/R4.2):** the dead-webhook guard and `check_n8n`/`/health --n8n` removal land **only at S5, after** the Portainer stop — during S0–S4 the `engine=n8n` proxy *is* the rollback and needs the webhook branch + `N8N_BASE`. `N8N_BASE`-optional (`config.py`) may land earlier (doesn't break the proxy), but the secret isn't unset until S5.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Guard/health removed early → kills rollback path | Hard-sequence to S5 after Portainer stop; test that `engine=n8n` proxies at every pre-S5 step |
| `canonical()` drift mint↔verify → every commit rejected (self-DoS) | One shared `canonical()`, unit-tested with reordered-keys/whitespace/unicode fixtures |
| Membership coded as equality → legit per-intent commits rejected | Explicit membership test vs the signed hash set; corpus has a multi-intent note committed per-intent |
| In-flight session broken at cutover | Shadow mints the **native** token while returning n8n's body → all outstanding tokens verify natively before S3 (legacy-accept shim as fallback) |
| Replay/double-commit in 30-min window | `bh_smart_capture_commits` `ON CONFLICT DO NOTHING`, inside the commit transaction |
| `url-extract` silently changes (native scrapes) | Replicate the exact pass-URL-as-text behavior; corpus asserts its response shape |
| Inbox consumers keep hitting n8n | Repoint both in the same PR as the overlay; they bypass dispatch today |
| SQL-injection regression | Route to existing services; `insert_typed` + `_quote_ident`; a test rejecting interpolated SQL in the commit path |
| Wrong container removed | R5.1 confirms Portainer `ai-services` (not repo compose); owner-gated; export retained |
| Migration fails scoped-role CI | Forward-only, idempotent, guarded seeds; green under `test_migrate_as_app_role.py` |

## Test Strategy

- **Deterministic (exact assertions, `fresh_db`):** token mint/verify (tamper/expiry/wrong-ws/fabricated rejected), membership vs equality, idempotency (replay = one row), each committer's parameterized write, "no interpolated SQL" guard, both inbox response shapes, oversized-input rejection, model-error → raw-note/clear-error.
- **Parity (statistical, corpus):** grocery text / multi-intent / image receipt / ambiguous / empty / oversized / both inbox shapes — schema-valid + semantic field agreement ≥ target vs golden, NOT string/LLM equality (R6.1). Run native vs a recorded n8n fixture (no live network).
- **Shadow (soak):** `engine=shadow` structured diff metric == 0 before flip (R6.2).
- **Boot (R6.4):** app starts + `/health` green with `N8N_BASE` unset (post-S5).

## Synthesis decisions (tournament record)

- **Spine: minimal-change** (2 modules + migration + surgical edits). *Ideal-architecture* lost as the base because its committer-registry + `TableSpec` framework is abstraction for two users over ~8 fixed tables (its own critique conceded this); we kept its genuinely-load-bearing ideas — the **typed intent + shared `canonical()`**, the **single-source prompt**, the **shopping→`bh_lists`/knowledge delegation**, and mirroring **`CategorizerConfig`** — and dropped the framework.
- **Rollout & token/dedup model: risk-first** wins wholesale — the **S0→S5 gates**, the **hard guard/health-after-S5 ordering**, and **shadow-mints-native-token** continuity are the safety spine.
- **Commit has no shadow/engine-diff:** shadowing commit would double-write; commit is `n8n`-proxy or `native` only. (All three agents or their critiques agreed once raised.)
- **Explicit committer functions, not a registry:** right-sized per the ideal agent's own "over-engineered" verdict; a future refactor can extract a registry if capture domains proliferate.
- **Stdlib HMAC, not `itsdangerous`:** avoids a dependency for ~20 lines; the payload is custom regardless.
