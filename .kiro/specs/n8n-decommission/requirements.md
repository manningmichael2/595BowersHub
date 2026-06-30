# n8n Decommission — Requirements

## Overview

Remove the project's runtime dependency on **n8n** and retire the container. The skill/automation migration to in-process Python is already ~90% done (native `@native_skill` handlers + an 11-job `apscheduler` in `main.py` cover categorization, simplefin sync, transfer-link, insights, embeddings, budgets, inbox, reminders, briefing, model-discovery; most `bh_skills` rows already use `native://`). What remains is a small, identifiable set of genuine n8n touchpoints — chiefly the **smart-capture** pipeline behind Quick Capture — plus the boot-time `N8N_BASE` requirement and cosmetic health/dashboard references.

Owner intent (this session): *"chart a path to removing dependency on n8n"* → make it real as a gated, multi-phase spec. The driving reason is the design review's "n8n is a zombie" item + the project's standing **n8n→code** direction (prefer coded solutions over n8n unless n8n is specifically needed).

**Hard constraints (from steering):** NO-HARDCODING (config stays DB-driven); parameterized SQL; migrations forward-only and applied on `fresh_db`; commit at each handoff; deploy only when asked. **n8n stays running until the final cutover** — every phase before that is independently shippable and reversible.

**Non-goals:** rebuilding n8n's visual editor in Python; preserving the `.json` workflow exports (they retire with n8n); any change to the *behavior* users see from Quick Capture / categorization (this is a like-for-like backend swap, parity-gated).

---

## Feature 1: Authoritative inventory (know exactly what still calls n8n)

### R1.1 — Enumerate every runtime n8n touchpoint
Produce a definitive list of code paths that reach n8n, from the live system, not the `.json` files. Known surface to confirm/complete: `services/skill_executor.py` (`self.n8n_base`, webhook dispatch for any `bh_skills.webhook_url` starting `/webhook/`), `routers/quick_capture.py` + `routers/db_browser.py` (smart-capture extract/commit), `config.py` (`N8N_BASE` required at boot), `services/healthcheck.py` (`check_n8n`), and `dashboard/app.py` (`proxy_n8n`, `/api/anthropic-spend` webhook).

### R1.2 — Audit `bh_skills` in prod for non-native rows
Identify every `bh_skills` row whose `webhook_url` is an n8n path (`LIKE '/webhook/%'`) rather than `native://…`. This is the authoritative remaining skill-port list and **cannot be derived from migrations alone** (prod may have been updated since). Output: a table of `{name, webhook_url, has_native_equivalent}`. Requires a read-only prod DB query (owner-run or via `ask-db`).

### R1.3 — Confirm n8n's own scheduled/trigger workflows
List the workflows still *active inside n8n* (via the n8n API/UI) that fire on schedule or webhook and are NOT yet covered by an `apscheduler` job or native handler (candidates: `email-receipts-importer`, `api-usage-logger`). Each becomes either a port task or a "confirmed already-covered" note.

### R1.4 — No silent coverage gaps
The inventory explicitly records, for each touchpoint, its disposition: `already-native` (cite the replacement), `port-required` (becomes a task), or `cosmetic-remove`. Nothing is dropped without a recorded decision.

---

## Feature 2: Port smart-capture to native Python (the one real feature port)

### R2.1 — Native smart-capture extract
Re-implement the n8n smart-capture **extract** step in-process (`/webhook/smart-capture/extract` → a native handler/service). It takes Quick-Capture text (+ optional uploaded image asset) and returns the same structured response the overlay consumes today (`{ok, intents[], asset?, raw_text?, extract_token}`), using the project's `model_provider`. The extraction prompt + intent schema mirror the n8n workflow's.

### R2.2 — Native smart-capture commit
Re-implement the **commit** step (`/webhook/smart-capture/commit`) natively: each accepted intent is written through the corresponding already-native action (finance/lists/knowledge), validated by `extract_token` (preserve the 30-min signature-expiry semantics the n8n workflow enforced).

### R2.3 — Repoint Quick Capture off n8n
`routers/quick_capture.py` (extract/commit pass-throughs) and the `db_browser.py` smart-capture URL builder call the native path instead of `skill_executor`→n8n. The `bh_skills` rows for `smart-capture/extract` + `commit` flip to `native://`. The existing **raw-note fallback (R9.9)** is retained.

### R2.4 — Parity gate (no behavior regression)
A test set asserts the native extract/commit produces equivalent intents + commit effects to the n8n pipeline for a representative capture corpus (text and image). This gate must pass before the cutover. Quick-Capture UX (overlay extract → confirm intents → commit, PWA share-target) is unchanged.

---

## Feature 3: Port or retire the remaining webhooks

### R3.1 — Resolve every `port-required` skill from R1.2
For each non-native `bh_skills` row (e.g. `process-asset`, and any finance/`update-category` stragglers the audit surfaces), either implement a `@native_skill` handler and flip the row to `native://`, or record it as superseded/removed. `process-asset` is expected to be thin (Quick Capture already uploads via filewriter).

### R3.2 — Port or confirm n8n scheduled workflows from R1.3
Any still-firing n8n schedule (`email-receipts-importer`, `api-usage-logger`) is either ported to an `apscheduler` job or documented as already covered by `check_inbox` / native usage logging. After this, **no n8n workflow is the sole owner of any behavior.**

### R3.3 — Skill dispatch no longer needs n8n
After R3.1, `skill_executor` has no live skill routing to an n8n webhook. The `_quote`/dispatch path that prefixes `self.n8n_base` is either removed or left dormant behind a guard that errors clearly if a (now-nonexistent) `/webhook/` skill is ever invoked.

---

## Feature 4: Make the app n8n-free at boot and in surfaces

### R4.1 — `N8N_BASE` becomes optional
`config.py` no longer requires `N8N_BASE` (`os.environ["N8N_BASE"]` → optional with empty default). The app boots cleanly with `N8N_BASE` unset. Any remaining reference treats empty as "n8n not configured" without crashing.

### R4.2 — Remove the n8n healthcheck surface
`services/healthcheck.py`'s `check_n8n` and the `/health --n8n` flag (`router_engine`) are removed once nothing depends on n8n. `/health` no longer reports an n8n component.

### R4.3 — Dashboard no longer depends on n8n
`dashboard/app.py`'s `proxy_n8n` route and the n8n-webhook path of `/api/anthropic-spend` are removed; the latter already has a direct-Postgres fallback (`api_usage_log`) which becomes the sole path. Dashboard links to the n8n UI are removed from `index.html`.

---

## Feature 5: Decommission the container and delete the artifacts

### R5.1 — Stop and remove the n8n service
Stop the running n8n container (the live one is in the Portainer `ai-services` stack, per the infra memory — confirm before acting) and remove the `n8n` service from `infrastructure/docker-compose.yml`. **This is the one owner-gated, deploy-side action** and happens only after Features 2–4 are merged and verified.

### R5.2 — Delete the workflow artifacts
Remove `n8n-workflows/` (build scripts + `.json` exports + `_config.py`) and any now-dead references. The `archive/n8n-workflows-deactivated/` tree is already archived and out of scope.

### R5.3 — Remove `N8N_BASE` from deploy config
Drop `N8N_BASE` from the deploy environment/secrets and from `config.py`'s required-vars list once R4.1 lands.

---

## Feature 6: Verification & rollback

### R6.1 — Full regression before and after cutover
The full backend suite + frontend suite pass at every phase. Quick Capture (overlay + PWA share target), finance categorization, and inbox flows are exercised end-to-end after the smart-capture port.

### R6.2 — Boots without n8n
A test/asserted check that the app starts and `/health` is green with `N8N_BASE` unset and no n8n container reachable.

### R6.3 — Reversible until R5
Through Feature 4, n8n remains running and the swap is config-flippable (the `bh_skills` rows can point back at `/webhook/…`), so any parity problem found in soak is recoverable without redeploying. Only Feature 5 is irreversible — gated on a clean soak of the native smart-capture path.
