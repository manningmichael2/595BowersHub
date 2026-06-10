# BowersHub AI — Full System Review
*June 7, 2026*

---

## What We Built (Last 2 Days)

**Architecture shift from rigid → flexible:**

| Before | After |
|--------|-------|
| Hardcoded skills per use case | Universal tool router + API registry (DB-driven) |
| Sports failed on any unrecognized input | Ollama fallback interprets ambiguous queries |
| Box score impossible at L2 | ESPN `/summary` endpoint, Haiku-formatted |
| Raw JSON displayed to user | Local model (simple) or Haiku (complex) formats all responses |
| L1/L2/L3 rigid silos | Ollama layer between L2 and L3 for zero-cost refinement |
| Every new capability = code change | New API = one DB INSERT into `bh_api_registry` |
| `_display` bypassed all formatting | Complex responses now route through Haiku for clean output |

**New features shipped:**
- `/news` command with RSS sources (NPR, Ars Technica, ESPN)
- Pitcher matchup + box score via ESPN `/summary`
- Sports skill handles "baseball", "ufc", "football", "who is pitching" — all via Ollama fallback when lookup fails
- `local_intelligence.py` — centralized Ollama service (sports interpret, news interpret, L2 refinement, pre-L3 gate)
- `toolbox.py` — safe HTTP executor, `calculate()`, `convert_units()`, usage logging
- `tool_router.py` — Haiku sees API registry, decides what to call
- `bh_api_registry` table with 9 seeded APIs (ESPN, wttr, NPR, Open-Meteo, TMDB, ExchangeRate, Wikipedia, NumbersAPI)
- `bh_api_usage_log` table for pattern detection
- L3 now has `http_request`, `calculate`, `convert_units`, `search_api_registry` tools available to Sonnet

---

## 🔴 Critical Issues — Fix These First

### 1. ~~Duplicate Migration Numbers~~ ✅ Fixed June 7, 2026

Migration 015 was created as the canonical "next" migration, documenting that prior collisions (009, 010, 012, 013) all ran successfully. Future migrations continue from 016+. The collision was documented in the migration file itself.

### 2. ~~Four Slash Commands Missing From DB~~ ✅ Fixed June 7, 2026

Migration 015 inserted `/score`, `/sports`, `/inventory`, `/transactions`, `/health` into `bh_slash_commands` with proper descriptions and flags. They now appear in `/help`, the autocomplete frontend, and flag suggestions.

### 3. ~~`weather` Skill DB Row Points to HTTPS URL~~ ✅ Fixed June 7, 2026

Migration 015 updated `bh_skills` row for `weather` from `https://wttr.in/?format=j1` to `native://weather`. The native Python handler is now correctly invoked for all L2-routed weather queries. Also cleaned up orphaned `/inbox` slash command row.

---

## 🟡 Architecture Issues — Clean Up Soon

### 4. ~~Two `api_usage_log` Tables~~ ✅ Documented June 7, 2026

The two tables serve different purposes and are intentionally separate:
- `public.api_usage_log` → Anthropic API cost tracking (model, tokens, cost_usd)
- `public.bh_api_usage_log` → External HTTP API call log (url, status, duration)

Migration 016 added `COMMENT ON TABLE` documentation to make the distinction clear. No rename needed — they're different data.

### 5. ~~`known_builtins` Fallback Masks Missing DB Rows~~ ✅ Fixed June 7, 2026

The hardcoded `known_builtins` set was removed from `router_engine.py`. Now all commands must exist in `bh_slash_commands` or they get a friendly "Unknown command, type /help" response. Only `/help` and `/new` have a bootstrap safety fallback (they must always work even on an empty DB).

### 6. ~~`_LOW_RISK_SKILLS` Is Hardcoded~~ ✅ Fixed June 7, 2026

Migration 016 added `is_read_only BOOLEAN` column to `bh_skills`. The hardcoded Python `frozenset` was replaced with a `_is_read_only_skill()` method that reads from the skill data already fetched by the classifier. Adding a new read-only skill = `UPDATE bh_skills SET is_read_only = true WHERE name = 'x'`. No code changes.

### 7. ~~Hardcoded Model IDs~~ ✅ Fixed June 7, 2026

Added `HAIKU_MODEL`, `SONNET_MODEL`, `LOCAL_MODEL` constants to `config.py`. All references in `tool_router.py` now use `_get_haiku_model()` (reads from env). `router_engine.py` uses `self.config.HAIKU_MODEL`. Updating the model when Anthropic releases a new version = one env var change, zero code changes.

### 8. ESPN and wttr.in Have Dual Coverage — Documented, Acceptable

The native `sports-score` and `weather` skills call ESPN/wttr directly. The API registry also has these APIs. This is *intentional dual coverage*: native skills are optimized fast-paths for the most common queries (instant dispatch, no Haiku reasoning). The tool router handles edge cases the native skills can't (standings, team rosters, box scores via chained calls). Long term, as the tool router proves reliable, native skills can be progressively retired. No action needed now.

### 9. ~~`calculate()` Uses `eval()`~~ ✅ Fixed June 7, 2026

Replaced `eval()` with `simpleeval` library (proper sandboxed evaluator — no access to builtins, imports, or attribute traversal). Added `simpleeval==1.0.3` to requirements.txt. Also supports `abs`, `round`, `min`, `max`, `sqrt` as safe functions.

### 10. ~~Admin Cost Dashboard Queries Wrong Table~~ ✅ Fixed June 7, 2026

Rewrote `/api/admin/cost` to query `bh_messages` directly instead of the n8n-era `api_usage_log` table. Now shows:
- Cost by **routing layer** (L1/L2/L3 breakdown)
- Cost by **workspace** (Finance vs General vs Woodshop)
- Cost by **model** (Haiku vs Sonnet token usage)
- Daily totals with response counts

Much more useful than the previous source-grouped view.

---

## 🟢 Good Decisions

These were the right calls:

- **`bh_` table prefix** — clean namespace separation from finance tables
- **Native skill registry** (`@native_skill` decorator + auto-discovery) — adding a skill is just creating a file, no config changes
- **`_display` convention** — pre-formatted responses skip unnecessary Haiku calls
- **Ollama as free pre-processor** — zero cost for ambiguous query interpretation before spending Haiku tokens
- **Local model for simple formatting, Haiku for complex** — the 500-char threshold is a reasonable heuristic
- **API registry as DB table** — correct design, enables admin UI management
- **`bh_slash_commands.flags` JSONB** — clean extensible schema for autocomplete hints
- **3-layer routing with cost transparency** — L1/L2/L3 badges + per-message cost is genuinely rare in personal AI tools
- **Conversation branching in schema** — `parent_id`, `branch_point_msg` — you'll want this later
- **`bh_artifacts` table** — ready for rich output (HTML artifacts, charts, Mermaid diagrams)

---

## Admin Panel — What's Missing

The current admin has: Users, Workspaces, Skills, Cost, Audit, Themes, Icons.

**What should be added:**

### Slash Commands Manager ✅ Built June 7, 2026
Admin → Slash Commands shows all `bh_slash_commands` rows with flags, skill associations, and workspace scoping. Full CRUD: add new commands, edit descriptions/flags, toggle active, delete. Backend: `GET/POST/PATCH/DELETE /api/admin/slash-commands`.

### API Registry Manager ✅ Built June 7, 2026
Admin → API Registry shows all `bh_api_registry` entries with base URLs, endpoints, auth type, usage counts. Full CRUD: register new APIs, edit descriptions/endpoints, toggle active/inactive, delete. Adding a new tool to the AI = add it here. Backend: `GET/POST/PATCH/DELETE /api/admin/api-registry`.

### Routing Patterns ✅ Built June 7, 2026
Admin → Routing Patterns shows all `bh_patterns` rows. Full CRUD with a **live regex tester** built into the editor. 12 patterns pre-seeded covering weather, sports, finance, knowledge, and news. Patterns fire at L1 (zero cost, zero latency).

### Cost Dashboard v2 ✅ Fixed June 7, 2026
Now built on `bh_messages` — shows cost by routing layer, workspace, and model. See fix #10 above.

### Python Tool Builder
Since n8n is being phased out, a code editor in the admin UI that creates files in `backend/services/skills/` which the skill registry auto-discovers on restart (or hot-reload). For a single-user private system, skills as stored Python code in a `bh_skill_code` table that gets `exec()`'d is also reasonable — simpler deployment, no container restart needed.

---

## Remaining To-Do List

### Immediate Fixes (under 1 hour each)
1. ~~**Migration to insert missing slash commands**~~ ✅ Done (migration 015)
2. ~~**Fix weather skill webhook_url**~~ ✅ Done (migration 015)
3. ~~**Renumber duplicate migrations**~~ ✅ Done (documented in migration 015)
4. ~~**Add `/inbox` cleanup**~~ ✅ Done (migration 015)

### Admin Panel Additions (half day each)
5. ~~**Slash Commands section**~~ ✅ Done (backend CRUD + frontend UI in admin panel)
6. ~~**API Registry section**~~ ✅ Done (backend CRUD + frontend UI in admin panel)
7. ~~**Cost dashboard v2**~~ ✅ Done (queries bh_messages with layer/workspace/model breakdown)
8. ~~**Patterns section**~~ ✅ Done (backend CRUD + frontend UI with regex tester)

### Architecture Cleanup (1-2 hours)
9. ~~**`is_read_only` on `bh_skills`**~~ ✅ Done (migration 016, replaces hardcoded set)
10. ~~**Config constant for model IDs**~~ ✅ Done (config.HAIKU_MODEL, config.SONNET_MODEL)
11. ~~**Rename `api_usage_log`**~~ ✅ Documented (tables serve different purposes, comments added)
12. ~~**`simpleeval` for safe math**~~ ✅ Done (replaced eval() in toolbox)

### New Skills / Features (from prior to-do + new ideas)
13. ~~**Password recovery flow**~~ ✅ Done — `bh_password_reset_tokens` table, `POST /api/auth/request-password-reset` (rate-limited, never reveals if email exists), `POST /api/auth/reset-password` (token single-use, 30-min expiry, revokes all sessions). Frontend: "Forgot password?" link on login page, `/forgot-password` page, `/reset-password?token=xxx` page. Email sent via existing Gmail SMTP.
14. ~~**CalDAV calendar**~~ ✅ Done — `backend/services/calendar.py` with full CalDAV read/write via Google App Password. Native skills: `calendar`, `get-calendar`, `schedule`, `calendar-create`, `add-event`. Integrated into morning briefing.
15. **Manon onboarding** — Deferred. System is fundamentally single-user in practice (env vars, Pushover, knowledge base, sports teams all hardcoded to Michael). Realistic path: password recovery (TODO #13) + invite link + Cooking/House workspace access. She doesn't need her own SimpleFin/Gmail/Pushover. Real blockers are: no password reset flow, no per-user notification routing, shared `/knowledge/` directory mixes facts. Not worth building until she actively wants to use it.
16. ~~**Game-day alerts**~~ ✅ Done — `backend/services/gameday_alerts.py` checks ESPN every 30 minutes for upcoming games from tracked teams (Tigers, Lions, Pistons, Red Wings, Michigan, USMNT). Sends Pushover notification ~90 minutes before game time with opponent, start time (ET), and pitching matchup (for MLB). In-memory debounce prevents duplicate alerts.
17. ~~**Structured memory**~~ ✅ Done — `bh_entities` + `bh_relationships` tables (migration 019). Full knowledge graph service (`knowledge_graph.py`) with: `remember_entity()`, `remember_relationship()`, `recall_entities()`, `recall_related()`, `recall_graph()`. Dual-path: `/remember` writes to both markdown (legacy) and graph (structured). `/recall` searches both and prefers graph results. L3 Sonnet has `knowledge_graph_query` and `knowledge_graph_remember` tools. Full-text search + JSONB attribute search + relationship traversal.
18. ~~**Smart capture from photo**~~ ✅ Done — `smart-capture-extract` and `smart-capture-commit` skills registered, Quick Capture overlay with extract/commit/raw-note endpoints, photo attachments via chat input sent to L3 for vision processing, Woodshop workspace instructs AI to offer capture when photos shared.

---

## Ideas You Didn't Ask About (But Should Know)

### You're Building Something Genuinely Novel

Most personal AI tools are wrappers around ChatGPT. BowersHub AI has:
- Real financial data with NL→SQL
- Local model for zero-cost orchestration
- Dynamic API registry that grows over time
- Usage logging that can self-optimize
- Per-workspace skill permissions
- A 3-layer cost-aware router

That's not a product anyone sells. The closest commercial equivalent is a $200/month enterprise tool (Dust.tt, Glean, or similar). You have it running at ~$2-5/day.

### The Conversation Branch Table Is Untapped

`bh_conversations` has `parent_id` and `branch_point_msg` — branching is fully designed and migrated. But there's no UI for it. This is actually one of the most powerful features of local AI tools: "try this approach, if it doesn't work, branch back." Worth surfacing.

### `bh_artifacts` Table Has No UI

The schema supports code, HTML, Mermaid, chart, markdown, and table artifacts — the same thing Claude.ai's "artifacts" feature does. The table exists, the `artifact_manager.py` service exists. It just needs a frontend panel to render them. This would be a big UX upgrade — interactive charts, generated HTML pages, that kind of thing.

### Proactive Intelligence Is Underutilized

You have Pushover, apscheduler, and a morning briefing. But the `bh_pinned_context` table supports **dynamic context** (refreshed on a schedule). You could add:
- "Show me the Tigers schedule for this week" as pinned dynamic context in the General workspace — so every morning briefing already knows upcoming games
- Budget alert context — "you're 78% through your dining budget" appears in every Finance workspace conversation this week, without you having to ask
- This is passive intelligence — context that shows up automatically when it's relevant

### The API Registry Should Auto-Suggest

Right now when Haiku's tool router returns `no_tool`, the query escalates to L3. Before that escalation, you could have the local model do a quick search: "is there a free API that could answer '{query}'?" and if it finds something plausible, register it on the fly and retry. This is true self-extending capability — the toolbox grows from usage. It would need a rate limit to prevent thrash, but it's a real possibility with the current architecture.

### Manon Is a Mostly-Missed Feature

She has a user account and a cooking workspace. But she doesn't have a tailscale device connected, there's no password recovery for her, and the workspace system prompt is generic. If she were a real daily user, the cooking workspace could be genuinely useful: recipe recall, meal planning with her preferences, shopping list that syncs with a shared note. Worth building out before suggesting she use it.

### The `/local` Command Is Underexposed

Chatting with the local Llama 3.2 3B model is free (literally $0 per message). It's fast enough for simple questions, definitions, brainstorming, editing. But most users don't know it exists. Consider making it more prominent — a toggle in the input area like the TTS button, or a "free mode" indicator. For questions that clearly don't need live data or reasoning, routing to Ollama at L2 as `direct_answer` (which the tool router already does) is $0 vs $0.002. Over thousands of messages that adds up.

### Pattern-Based Routing (`bh_patterns`) Is Zero-Used

The initial schema includes a `bh_patterns` table for regex/keyword routing rules. Nothing has ever been inserted into it. This is actually a very powerful feature: you could add patterns like `(?i)\bhow much did i spend on\b` → `spending-summary` skill, or `(?i)\btigers?\b.*(score|game)` → `sports-score`. These fire before even Haiku touches the message (true L1). But there's no UI, no documentation, no examples. This is capability sitting completely dormant.

### Security: All DB Users Still Superuser

Every container still connects as `michael` (the Postgres superuser). If the AI ever constructs a malicious SQL query via `ask-db`, it could `DROP TABLE` anything. Creating a `bowershub_ai` Postgres role with `SELECT`, `INSERT`, `UPDATE` on `bh_*` tables (and `SELECT` only on finance tables) would contain the blast radius significantly. Not urgent for a single-user private system, but worth noting.

---

## Routing Architecture Diagram

```
User message
    │
    ▼ [L1] Deterministic
    ├── starts with "/" → DB lookup in bh_slash_commands
    │       ├── skill_id != NULL → skill executor → RoutingResult(layer="L1")
    │       └── skill_id IS NULL → _handle_builtin_command() → one of 14 handlers
    │   DB miss → known_builtins fallback set (hardcoded)
    │
    ├── pattern match → bh_patterns table (regex/keyword → skill)
    │
    ├── force_model set? → skip to L3
    │
    ▼ [L2] Lightweight AI classification (Haiku ~$0.001)
    ├── _classify() → CLASSIFICATION_PROMPT with skills list + conversation context
    │       confidence > threshold (0.65 read-only, 0.75 write):
    │           → _execute_classified_skill()
    │           → if complex display: Haiku formatting pass (+$0.001)
    │
    │   borderline confidence (0.4–threshold): [L2.5a local refinement]
    │       → refine_classification() via local Ollama (free)
    │       → if confident enough → _execute_classified_skill()
    │
    │   L2 returned null skill: [L2.5b pre-L3 gate]
    │       → local model picks a skill at ≥0.7 confidence
    │       → _execute_classified_skill()
    │
    ▼ [L2.5] Flexible Tool Router (Haiku + API registry ~$0.002-0.004)
    ├── route_with_tools() reads bh_api_registry
    ├── TOOL_USE_PROMPT → Haiku decides: api_call | calculate | convert | direct_answer | no_tool
    │   api_call → execute_api_call() → up to 3 chained calls → _format_api_response()
    │   calculate → toolbox.calculate() (safe eval, instant)
    │   convert → toolbox.convert_units() (instant)
    │   direct_answer → Haiku answers from its own knowledge
    │   no_tool → falls through to L3
    │
    ▼ [L3] Full reasoning (Sonnet ~$0.03-0.08)
    └── _layer3_reason() → streaming via WebSocket
        tools: web_search + {http_request, calculate, convert_units, search_api_registry}
              + all workspace skills as tool definitions
        → multi-turn tool-use loop → RoutingResult(layer="L3")
```

---

## DB Table Inventory

### Core `bh_*` Tables
- `bh_users` — auth, role, settings
- `bh_invite_links` — invite-based registration
- `bh_refresh_tokens` — JWT refresh rotation
- `bh_workspaces` — system_prompt, permitted_schemas, temperature
- `bh_workspace_users` — membership
- `bh_pinned_context` — static/dynamic context blocks
- `bh_conversations` — with branching support
- `bh_messages` — full log with routing_layer, cost_usd
- `bh_skills` — skill registry
- `bh_workspace_skills` — workspace↔skill join
- `bh_slash_commands` — command registry with flags JSONB
- `bh_patterns` — regex/keyword routing
- `bh_model_rates` — per-model pricing
- `bh_hooks` — event hooks
- `bh_hook_log` — hook execution history
- `bh_artifacts` — rich output
- `bh_audit_log` — admin actions
- `bh_notification_prefs` — per-user prefs
- `bh_push_subscriptions` — web push
- `bh_themes` — preset + custom themes
- `bh_platform_settings` — key/value config
- `bh_reminders` — timed reminders
- `bh_api_registry` — dynamic API toolbox
- `bh_api_usage_log` — external API call log

### Pre-existing Tables (finance/n8n era)
- `public.transactions` — SimpleFin-synced
- `public.accounts` — bank accounts
- `public.categories` — 2-tier category hierarchy
- `public.category_examples` — learning loop examples
- `public.budgets` — monthly budgets
- `public.alert_log` — budget alert dedup
- `public.api_usage_log` — Anthropic cost tracking (n8n + BowersHub)

---

## API Registry Contents

| Name | Base URL | Auth | Key Endpoints |
|------|----------|------|---------------|
| `espn` | site.api.espn.com | none | scoreboard, summary, standings, teams, news |
| `wttr` | wttr.in | none | forecast |
| `npr_rss` | feeds.npr.org | none | top_stories, world, business, science, technology |
| `ars_technica` | feeds.arstechnica.com | none | all |
| `open_meteo` | api.open-meteo.com | none | forecast, geocoding |
| `tmdb` | api.themoviedb.org | api_key | search_movie, search_tv, trending, movie_detail |
| `exchangerate` | open.er-api.com | none | latest |
| `wikipedia` | en.wikipedia.org/api/rest_v1 | none | summary, random |
| `numbersapi` | numbersapi.com | none | number_fact, date_fact, math_fact |

---

## Native Skills Registry

| Module | Registered Names |
|--------|-----------------|
| `weather.py` | weather, get-weather |
| `sports_score.py` | sports-score |
| `knowledge.py` | recall, remember |
| `finance.py` | balances, get-balances, transactions, filter-transactions, spending-summary, ask-db, finance-query, override-category, list-files |
| `inventory.py` | inventory, inventory-admin |
| `email.py` | send-email |
| `news.py` | news, headlines, get-news |

**Total: 20 handlers across 7 modules.**

---

## Cost Profile (observed)

| Query Type | Layer | Typical Cost |
|-----------|-------|-------------|
| Slash command (`/weather`, `/score tigers`) | L1 | $0.000 |
| Simple skill dispatch ("what's the weather?") | L2 | $0.001 |
| Skill + formatting pass ("tigers boxscore") | L2 | $0.003-0.004 |
| Tool router API call ("exchange rate EUR to USD") | L2.5 | $0.002-0.004 |
| Full reasoning / multi-tool | L3 | $0.03-0.08 |
| Previous "who is pitching" (before fix) | L3 | $0.05 |
| Same query after fix | L2 | $0.001-0.004 |

**Estimated daily cost at current usage: $0.15-0.50/day** (down from $7/day with AnythingLLM)
