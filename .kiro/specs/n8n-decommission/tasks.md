# n8n Decommission — Tasks

> Each task traces to requirements. Phases are sequential PRs; n8n stays running until Task 9.
> Backend: `bowershub-ai/backend`; frontend: `bowershub-ai/frontend`. DB-backed tests use `fresh_db`; run a throwaway `pgvector/pgvector:pg16` locally if no DB is reachable (per the run-db-tests-locally memory).
> **Owner-gated:** Tasks 1 (prod query), 9 (container removal/deploy). Everything else is normal PR work.

## Phase 0 — Inventory (R1)

### Task 1: Authoritative inventory → `inventory.md`
- **Effort:** S · **Deps:** none · **Requirements:** R1.1, R1.2, R1.3, R1.4
- [ ] Finalize the code-touchpoint list (R1.1) from grep (skill_executor, quick_capture, db_browser, config, healthcheck, dashboard).
- [ ] **Owner/`ask-db`:** `SELECT name, webhook_url FROM bh_skills WHERE webhook_url LIKE '/webhook/%' ORDER BY name;` → record each as `already-native` / `port-required` / `cosmetic` (R1.2, R1.4).
- [ ] **Owner/n8n UI:** enumerate active scheduled/webhook workflows; mark each ported / already-covered (R1.3).
- [ ] Write `.kiro/specs/n8n-decommission/inventory.md` with the dispositions. **No production change.**

## Phase 1 — Native smart-capture (R2)  ← the bulk

### Task 2: `services/smart_capture.py` — native extract
- **Effort:** L · **Deps:** Task 1 · **Requirements:** R2.1
- [ ] Port the n8n extract prompt + intent schema; single `model_provider` call; parse to the existing `{intents[], asset?, raw_text?}` shape the overlay consumes.
- [ ] Mint `extract_token` = HMAC(intents + issued_at), 30-min expiry (mirror the n8n signature).
- [ ] Tests: text capture → expected intents; image capture path; malformed model output degrades gracefully.

### Task 3: native commit + token verification
- **Effort:** M · **Deps:** Task 2 · **Requirements:** R2.2
- [ ] `commit(extract_token, accepted_intents, …)`: verify token (reject expired/tampered); dispatch each intent to the existing native action for its domain (finance/list/knowledge) — **no new write logic**.
- [ ] Tests: each intent type commits to the right table; expired/tampered token rejected; partial-accept (user drops an intent) commits only the kept ones.

### Task 4: register native skills + repoint Quick Capture
- **Effort:** M · **Deps:** Task 3 · **Requirements:** R2.3
- [ ] `@native_skill("smart-capture/extract")` + `("smart-capture/commit")` wrapping the service.
- [ ] Migration `00NN_smart_capture_native.sql`: flip the two `bh_skills` rows to `native://…`, guarded on the exact current `/webhook/…` value; forward-only, idempotent, applies on `fresh_db`.
- [ ] `routers/quick_capture.py` + `db_browser.py` smart-capture URL builder call the native skills; **raw-note fallback retained**.
- [ ] Tests: migration flips rows + idempotent; quick-capture extract/commit run fully native; raw-note still works.

### Task 5: parity gate
- **Effort:** M · **Deps:** Task 4 · **Requirements:** R2.4, R6.1
- [ ] Fixture corpus (grocery text, multi-intent note, image receipt); assert native extract intents + commit effects match expected. Block cutover on this.
- [ ] Frontend: existing Quick-Capture tests green; tsc + build clean. (No overlay change expected.)

## Phase 2 — Remaining webhooks (R3)

### Task 6: port/retire each `port-required` skill
- **Effort:** M (scales with Task 1 findings) · **Deps:** Task 1 · **Requirements:** R3.1, R3.3
- [ ] For each non-native row: implement a `@native_skill` (e.g. `process-asset` reusing the filewriter upload/asset-metadata path) **or** remove it with a recorded reason; flip rows via a small guarded migration.
- [ ] `skill_executor`: dead-webhook guard raises a clear `SkillExecutionError` if any `/webhook/` skill is ever invoked post-cutover.
- [ ] Tests per ported skill; guard test.

### Task 7: port/confirm n8n scheduled workflows
- **Effort:** S–M · **Deps:** Task 1 · **Requirements:** R3.2
- [ ] For each active n8n schedule from R1.3: add an `apscheduler` job **or** document it as already covered (`check_inbox` / native usage logging). After this, no n8n workflow solely owns any behavior.

## Phase 3 — n8n-free boot & surfaces (R4)

### Task 8: make the app n8n-free
- **Effort:** S · **Deps:** Tasks 4, 6, 7 · **Requirements:** R4.1, R4.2, R4.3, R6.2
- [ ] `config.py`: `N8N_BASE` optional (default `""`); drop from required-vars.
- [ ] `healthcheck.py`: remove `check_n8n`; `router_engine` drops `/health --n8n` + the n8n component.
- [ ] `dashboard/app.py`: remove `proxy_n8n`; `/api/anthropic-spend` → Postgres-only; `index.html` drops the n8n UI link.
- [ ] Test (R6.2): app boots + `/health` green with `N8N_BASE` unset.

## Phase 4 — Decommission (R5) — OWNER-GATED, deploy-side

### Task 9: stop n8n + delete artifacts
- **Effort:** S (but gated on soak) · **Deps:** Tasks 5, 8 + a clean prod soak · **Requirements:** R5.1, R5.2, R5.3, R6.1
- [ ] Confirm the live n8n is the Portainer `ai-services` stack (infra memory) — **owner confirms before acting**.
- [ ] Stop + remove the n8n container; remove the `n8n` service from `infrastructure/docker-compose.yml`.
- [ ] Delete `n8n-workflows/`; remove `N8N_BASE` from deploy secrets.
- [ ] Final full backend + frontend regression (R6.1) + n8n-free boot check (R6.2); Quick-Capture E2E in prod.

---

## Sequencing & gates
- **1 → (2→3→4→5) → 6,7 → 8 → 9.** Tasks 6/7 can run parallel to Phase 1 once Task 1 is done.
- **Cutover gate:** Task 5 (parity) green **and** a prod soak with rollback-by-`bh_skills`-row available, before Task 9.
- **Reversibility:** through Task 8, every skill swap is a one-row revert (R6.3). Task 9 is the only irreversible step.
- **Effort estimate:** Phase 1 (Tasks 2–5) is ~1–2 focused sessions; Phases 0/2/3 ~1 session combined; Phase 4 is minutes of work behind a soak window.
