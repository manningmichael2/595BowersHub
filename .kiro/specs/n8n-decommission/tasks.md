# n8n Decommission — Tasks

> Each task traces to requirements (`Requirements:` line). Work top-to-bottom; respect dependencies. Backend: `bowershub-ai/backend`. DB-backed tests use `fresh_db` (+ throwaway `pgvector/pgvector:pg16` locally). Ordered by the S0→S5 rollout in `design.md`.
> **Owner-gated:** Task 1 (prod query), Task 13 (cutover flip), Task 16 (Portainer removal). n8n stays running until Task 16.

## Task 1: Authoritative inventory → `inventory.md`
- **Effort:** S
- **Dependencies:** none
- **Requirements:** R1.1, R1.2, R1.3, R1.4
- [ ] Finalize the code-touchpoint list (skill_executor, quick_capture, db_browser inbox×2, config, healthcheck, dashboard) from grep.
- [ ] **Owner/`ask-db`:** `SELECT name, webhook_url FROM bh_skills WHERE webhook_url LIKE '/webhook/%' ORDER BY name;` → mark each `already-native` (has a registered handler by name) / `port-required` / `cosmetic`.
- [ ] **Owner/n8n UI:** active-workflow list + execution history → classify `email-receipts-importer`, `api-usage-logger`; **resolve who writes `api_usage_log`** (native vs n8n) — this gates decommission (design "supporting changes").
- [ ] Write `.kiro/specs/n8n-decommission/inventory.md` with every touchpoint + skill row + its disposition. **No production change.**
- [ ] **Tests:** none (documentation artifact); the disposition table is the deliverable.

## Task 2: `smart_capture` package spine — config, intents, tokens
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R2.2, R2.2a, R2.6, R6.3
- [ ] `services/smart_capture/config.py` — `get_engine(conn)` (`n8n|native|shadow`, default `n8n`, unknown→`n8n`) + `get_token_secret(conn)→bytes` (hex-decode 32 bytes), reading `bh_platform_settings` (mirror `categorization/config.py`, un-cached).
- [ ] `intents.py` — frozen `CaptureIntent`; single `canonical()` over `{domain,payload,asset_id}`; `hash()`.
- [ ] `tokens.py` — `mint`/`verify` real HMAC-SHA256 (`hmac.compare_digest`) over `{v,ts,uid,wid,ih:[…]}`; verify recomputes HMAC, 30-min expiry, uid/wid match, **membership incl. asset**.
- [ ] **Tests:** tamper/expired/wrong-workspace/fabricated rejected; membership passes for a signed intent + fails for a foreign one; asset-swap rejected; `canonical()` stable under reordered keys/whitespace/unicode.

## Task 3: Native extract (text) + prompt + input bounds
- **Effort:** M
- **Dependencies:** Task 2, Task 6
- **Requirements:** R2.1, R2.7, R2.8
- [ ] `prompt.py` — port `Build Classify Prompt` + `DOMAINS` allow-list verbatim (single source of truth).
- [ ] `extract.py::extract_native` — one `model_provider.complete(resolve_role("fast"), max_tokens≈2048)`; reproduce `Parse Classification` fence-strip + `other`-fallback; return `{ok,intents,asset?,raw_text?,extract_token}`; enforce **max input size** (reject/mark oversized); model error → `{ok:false,error}`.
- [ ] **Tests:** text capture → expected intent shape; oversized rejected; malformed/truncated model output → clear error (never partial); domain allow-list enforced.

## Task 4: Native commit + committers + idempotency
- **Effort:** L
- **Dependencies:** Task 2, Task 6
- **Requirements:** R2.3, R2.2a, R2.7
- [ ] `commit.py::commit_native` — verify token → `dedup_key=sha256(hmac||intent.hash())` → `INSERT bh_smart_capture_commits ON CONFLICT DO NOTHING`; if 0 rows, `SELECT result_json` and return (replay no-op); else run committer (same txn for DB domains).
- [ ] Committers (explicit fns, **all** DOMAINS): `shopping_list→list_router.route_and_add`; `knowledge_fact/project/other→knowledge.remember(+remember_entity)`; `tool/router_bit/saw_blade/wood/album/manual→insert_typed` (parameterized `$n`, `_quote_ident`, `_extra_fields`→notes, `*_files` asset link); `house_room→upsert`; `recipe→slug+flatten`; `cook_log→recipe-lookup then insert`.
- [ ] Per-intent atomic; a failed intent → `{ok:false,error}` for that intent only (no partial-success-as-success); orphaned asset logged (structured line w/ asset_id+dedup_key).
- [ ] **Tests:** each committer writes the right row (parameterized); replay = one row; partial-failure reported per-intent; a test asserting **no string-interpolated SQL** in the commit path; `_extra_fields`→notes preserved; house_room re-capture upserts (no dup).

## Task 5: Register native skills + engine wrappers + thread dispatch context
- **Effort:** M
- **Dependencies:** Task 3, Task 4
- **Requirements:** R2.5, R2.6
- [ ] `engine.py::run_extract/run_commit` — extract: native/n8n/`shadow` (shadow mints token over **n8n's** returned intents, returns n8n body, logs diff); commit: native when `engine≠n8n`, else `_proxy_n8n`.
- [ ] `services/skills/smart_capture.py` — `@native_skill("smart-capture-extract"/"commit")` thin wrappers.
- [ ] `skill_executor._try_native_skill` — add `workspace_id` param (pass at `:146`) + inject `_workspace_id`/`_config`/`_model_provider` (cached) into params (non-breaking; extra keys ignored).
- [ ] **Tests:** extract/commit dispatch native under `engine=native`; proxy under `engine=n8n`; shadow returns n8n body + native token + a diff log; other native skills unaffected by the injected keys.

## Task 6: Migration `0058` — engine setting, token secret, dedup table
- **Effort:** S
- **Dependencies:** Task 2
- **Requirements:** R2.6, R6.3
- [ ] **Migration:** `backend/migrations/0058_smart_capture_native.sql` (confirm next free number) — seed `smart_capture.engine='"n8n"'`, `smart_capture.token_secret=to_jsonb(encode(gen_random_bytes(32),'hex'))`, `smart_capture.process_asset_native=false`, and `smart_capture.inbox_workspace_id=null` (**not a hardcoded id** — resolved at runtime, Task 7); `CREATE TABLE bh_smart_capture_commits(dedup_key text PK, result_json jsonb, created_at timestamptz default now())`; `ON CONFLICT DO NOTHING` throughout; optional cosmetic `UPDATE bh_skills … native://…`.
- [ ] **Tests:** applies on `fresh_db` + idempotent re-run; green under `test_migrate_as_app_role.py` (scoped migrator role); settings + table present; secret hex-decodes to 32 bytes.

## Task 7: Repoint all consumers
- **Effort:** M
- **Dependencies:** Task 5
- **Requirements:** R2.5
- [ ] `quick_capture.py` — verify extract/commit go native on registration (no functional change); raw-note fallback (`:245-294`) untouched.
- [ ] `db_browser.py` `/inbox/ai-extract` + `/inbox/url-extract` — route through `executor.execute("smart-capture-extract", …)` with the inbox workspace = `smart_capture.inbox_workspace_id` if set, **else resolved at runtime** to the admin's default workspace (query, not a hardcoded id); **preserve each response shape**; replicate `url-extract` **text pass-through (no scrape)** exactly; delete `_get_smart_capture_url`.
- [ ] **Tests:** overlay + both inbox consumers run native end-to-end; each returns its original response shape; url-extract passes URL as text (asserted); **inbox consumers surface a clear error (not silent-empty) on a model_provider failure** (R2.7); raw-note still works.

## Task 8: Native Process Asset (vision) + image fallback
- **Effort:** L
- **Dependencies:** Task 3
- **Requirements:** R3.1, R2.4, R6.1
- [ ] `process_asset.py` — `model_provider` vision call (image→`ai_summary`+`ai_extracted`), parameterized insert into `assets` tables, hash dedup/move; `@native_skill("process-asset")`.
- [ ] `extract_native` image branch: under `engine=native|shadow`, call native process-asset **iff** `smart_capture.process_asset_native=true`, else proxy the image request to n8n (per-request fallback so text can cut over first).
- [ ] **Tests:** vision extract → asset row + structured fields (parameterized); dedup on re-upload; image fallback proxies while flag off, goes native when on; **image-receipt parity** (native vs recorded n8n fixture, ≥95% field agreement) — the image half of the R6.1 gate, blocking the image cutover.

## Task 9: Parity corpus + deterministic unit-test gate (S1)
- **Effort:** M
- **Dependencies:** Task 4, Task 7
- **Requirements:** R6.1
- [ ] Golden corpus (**text/inbox — image parity rides with Task 8**, since native image is gated behind `process_asset_native`): grocery text, multi-intent note, ambiguous, empty, **oversized**, **both inbox shapes** — assert native extract intents are schema-valid + **≥95% field-level agreement** vs golden (semantic/normalized, not string equality), 0 schema violations; commit produces expected rows.
- [ ] **Tests:** the corpus runs native vs a recorded n8n fixture (no live network); this gate blocks the text cutover.

## Task 10: Shadow mode + observability, run the soak (S2)
- **Effort:** M
- **Dependencies:** Task 5, Task 9
- **Requirements:** R6.2
- [ ] Structured per-call native-vs-n8n diff logging under `engine=shadow`; emit commit-success / token-rejection(by reason) / raw-note-fallback metrics.
- [ ] Set `engine=shadow` in prod; hold ≥7-day (or ≥50-capture) soak; advance only at **0 structural-parity failures**.
- [ ] **Tests:** shadow path emits a diff record and returns the n8n result; metric counters increment.

## Task 11: Resolve `override-category` + scheduled workflows + `api_usage_log`
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R3.2, R3.3
- [ ] `override-category`: run the evidence bar (grep `update-category`; n8n history; `api_usage_log` window) → deactivate the row via a small guarded migration if orphaned (native `category_override.py` supersedes it); port only if a live caller is found.
- [ ] Scheduled workflows: confirm `email-receipts-importer`/`api-usage-logger` covered or port to `apscheduler`. **If n8n owns `api_usage_log`, land a native usage logger first** (else the dashboard spend fallback breaks) — blocks Task 14/16.
- [ ] **Tests:** deactivation migration idempotent on `fresh_db`; any new apscheduler job unit-tested; `api_usage_log` still populated natively.

## Task 12: Dead-webhook guard (lands at decommission only)
- **Effort:** S
- **Dependencies:** Task 16
- **Requirements:** R3.4
- [ ] `skill_executor`: raise a clear `SkillExecutionError` if a `/webhook/` skill is invoked. **Sequenced at/after Task 16** — never during soak (would break the `engine=n8n` rollback path).
- [ ] **Tests:** a `/webhook/` skill raises the guard; native skills unaffected.

## Task 13: `N8N_BASE` optional + cutover + boots-without-n8n
- **Effort:** S
- **Dependencies:** Task 10
- **Requirements:** R4.1, R6.3, R6.4
- [ ] `config.py`: drop `N8N_BASE` from `_REQUIRED`; `os.environ.get("N8N_BASE","")`.
- [ ] **Owner cutover:** after S1+S2 gates pass, flip `smart_capture.engine=native` (S3); verify rollback by flipping back to `n8n` with no redeploy.
- [ ] **Tests:** app boots + `/health` green with `N8N_BASE` unset (R6.4); flipping the engine setting switches behavior with no restart (rollback verified).

## Task 14: Remove n8n health + dashboard surfaces (after soak)
- **Effort:** S
- **Dependencies:** Task 11, Task 13, Task 16
- **Requirements:** R4.2, R4.3
- [ ] Remove `healthcheck.check_n8n` + registry entry + `/health --n8n` (`router_engine.py:992`).
- [ ] `dashboard/app.py`: remove `proxy_n8n`; `/api/anthropic-spend` → Postgres-only (contingent on the Task 11 native logger); drop the n8n link in `index.html`.
- [ ] **Tests:** `/health` reports no n8n component; dashboard spend returns from Postgres.

## Task 15: Delete workflow artifacts + drop `N8N_BASE`
- **Effort:** S
- **Dependencies:** Task 14, Task 16
- **Requirements:** R5.2, R5.3
- [ ] Delete `n8n-workflows/` (retain an export as escape hatch); remove `N8N_BASE` from `config.py`, `*.env.example`, and deploy secrets.
- [ ] **Tests:** full backend suite green with n8n fully gone; no residual `N8N_BASE` reference breaks boot.

## Task 16: Decommission the container (owner-gated, irreversible)
- **Effort:** S (gated on soak)
- **Dependencies:** Task 11, Task 13 + a clean prod soak
- **Requirements:** R5.1
- [ ] Confirm the live n8n is the **Portainer `ai-services` stack** (not repo compose); **owner stops/removes** it there; remove the `n8n` service from `infrastructure/docker-compose.yml` (documentation-only).
- [ ] **Tests:** post-removal, full regression + Quick-Capture E2E (overlay + PWA share) + inbox extract all green; `/health` green.

## Definition of Done
- [ ] All tasks complete; every requirement in `requirements.md` is satisfied.
- [ ] No hardcoded config introduced — engine + token secret + inbox workspace + process-asset flag are `bh_platform_settings` rows; skill routing stays DB-driven; all commit SQL parameterized.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; migration green under `test_migrate_as_app_role.py`); frontend unaffected (`npx tsc --noEmit` + `npm test`).
- [ ] Parity gate (≥95%) + a clean shadow soak (0 structural-parity failures) before the `engine=native` flip; rollback-by-setting verified.
- [ ] `api_usage_log` confirmed native-populated before decommission; n8n stopped only after soak; n8n export retained.
- [ ] `context-log.md` updated with a dated entry.
