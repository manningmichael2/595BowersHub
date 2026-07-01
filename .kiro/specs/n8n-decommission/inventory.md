# n8n Decommission — Authoritative Inventory (Task 1)

> **Status:** complete — read-only, no production change.
> **Produced:** 2026-07-01 by direct code grep + live prod DB queries (postgres `finance`, this host) + running-container inspection.
> Satisfies R1.1–R1.4. This is the disposition table the porting phases (Tasks 2–16) act on.

## Running containers (prod, this host)
- `bowershub-ai` (app), `postgres` (pgvector/pgvector:pg16), **`n8n` (n8nio/n8n:latest — still live)**, plus ollama/caddy.
- Note: n8n is on the `:latest` tag (the design review's "pinned SHAs" claim does not cover n8n).

## Dispatch is name-first (verified)
`skill_executor.execute` calls `_try_native_skill(name)` **first** (`skill_executor.py:146`); a non-None result short-circuits (`:147-148`) **before** the `webhook_url` is ever resolved (`:150-153`). ⇒ **A skill with a registered `@native_skill(name)` handler runs in-process even if its `bh_skills.webhook_url` still points at `/webhook/...`.** The URL is inert for those rows. This is why the raw `bh_skills` webhook count overstates real n8n dependence.

## `bh_skills` rows carrying `/webhook/%` (11 rows, prod)
Cross-referenced against the 23 registered `@native_skill(...)` handlers.

| skill | webhook_url | native handler? | **disposition** |
|---|---|---|---|
| ask-db | /webhook/finance-query | ✅ | **already-native** (inert URL) |
| balances | /webhook/balances | ✅ | **already-native** |
| filter-transactions | /webhook/filter | ✅ | **already-native** |
| inventory-admin | /webhook/inventory-admin | ✅ | **already-native** |
| list-files | /webhook/list-files | ✅ | **already-native** |
| send-email | /webhook/send-email | ✅ | **already-native** |
| spending-summary | /webhook/transactions | ✅ | **already-native** |
| transactions | /webhook/transactions | ✅ | **already-native** |
| **smart-capture-extract** | /webhook/smart-capture/extract | ❌ | **port-required** (Tasks 3, 5, 7) |
| **smart-capture-commit** | /webhook/smart-capture/commit | ❌ | **port-required** (Tasks 4, 5, 7) |
| **process-asset** | /webhook/process-asset | ❌ | **port-required** (Task 8, vision) |

**Only 3 of 11 genuinely reach n8n.** The other 8 already run native; their `webhook_url` is cosmetic and can be flipped to `native://…` any time (optional cleanup, no behavior change).

## Live backend code touchpoints
| file / lines | what | phase |
|---|---|---|
| `config.py:35,129,174` | `N8N_BASE` **required at boot** (`os.environ["N8N_BASE"]`) | S4 — make optional |
| `routers/quick_capture.py:176,225` | Quick-Capture → `smart-capture-extract`/`commit`; raw-note fallback `:254-294` | rides smart-capture port |
| `routers/db_browser.py:3939-3943,4257,4311` | `_get_smart_capture_url` + `/inbox/ai-extract` + `/inbox/url-extract` | Task 7 |
| `services/skill_executor.py:52,150-153` | `n8n_base` + webhook fallback dispatch | dead-webhook guard (S2/S4) |
| `services/healthcheck.py:25,141,185` | `check_n8n` / `N8N_URL` / `/health --n8n` | S4 — remove |
| `dashboard/app.py:118-146` | `/api/anthropic-spend` reads `api_usage_log` | fallback already native (see below) |

## `api_usage_log` writer — the decommission gate (RESOLVED)
The spec flagged this as a hard dependency (dashboard spend must survive n8n's death). Prod data settles it:

- **5,376 rows total**, newest `2026-06-22`. Writers by name:
  - `Finance SQL Query` (n8n) — 5,346 rows, **last wrote 2026-06-07** (stopped when ask-db went native).
  - `bowershub-ai/finance_narration`, `bowershub-ai/finance_ask_db` (**native**, `services/cost_tracker.py:33`) — wrote 2026-06-22.
  - `Smart Capture` / `Process Asset` / `URL Lookup` (n8n) — last wrote May.
- **Conclusion: n8n is no longer the writer.** The native `cost_tracker.py` (wired via `finance_narration.py:111`) is the current/active writer, so decommissioning n8n does **not** break `api_usage_log` or the dashboard spend view. **The gate is already satisfied — no new logger is required before S5.**
- ⚠️ **Pre-existing coverage gap (not caused by decommission):** the native logger only records finance narration + ask-db LLM calls, **not** general L1/L2/L3 chat spend. The dashboard "anthropic spend" therefore under-reports and has since ~2026-06-22. Worth fixing for accuracy, but it is orthogonal to n8n removal — n8n wasn't logging chat spend either.

## Scheduled / non-skill n8n workflows
| workflow (`n8n-workflows/`) | disposition |
|---|---|
| `api-usage-logger.json` | **superseded** by native `cost_tracker.py` (see gate above) — retire |
| `email-receipts-importer.json` | **DORMANT → defer (port-or-drop at S5).** Evidence: 0 email/receipt-sourced `finance.transactions` in 60 days; no recent `api_usage_log`; n8n on SQLite. It hinges on n8n's **IMAP Trigger** + the Gmail 'Receipts' label and chains to `receipt-to-transaction` (**not ported**). A native port is buildable — the pieces exist (`services/email_reader.py` IMAP, now-native `process-asset`, `model_provider`) — but needs: (1) native `receipt-to-transaction`, (2) an apscheduler poll job, (3) live Gmail creds + real receipt emails to verify end-to-end. Not built here: it's unused, owner can live without it, and it can't be honestly verified without live email. Decide at decommission. |
| `smart-capture.json`, `process-asset.json` | the 3 port-required skills above |
| `build-*.py`, others | build artifacts for the above; die with them |

## Hardcoded Tailscale IP `100.106.180.101` (from the design review)
Live (non-archive) occurrences that matter: `dashboard/app.py`, `dashboard/index.html`, `n8n-workflows/*`, and `bowershub-ai/backend/config.py` / `services/knowledge.py` / `scripts/smoke_test.py` / `README.md`. The `n8n-workflows/` ones die with decommission; `dashboard` is already `BOWERSHUB_HOST`-driven (default unchanged). Remaining backend literals are defaults — separate small cleanup, tracked but not part of this spec.

## Net effect on the plan
The spec's core thesis holds and is now **confirmed against prod**: the only genuine n8n runtime dependencies are **smart-capture (extract + commit)** and **process-asset**, plus the boot-time `N8N_BASE` requirement. The `api_usage_log` blocker the design flagged is **already cleared** (native writer live). Ready to proceed to Task 2 (native `smart_capture` spine) once owner green-lights execution. Only Task 16 (Portainer stop) is irreversible.
