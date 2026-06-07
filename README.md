# 595BowersHub — Personal AI Hub

A self-hosted, private AI assistant platform running on a mini PC. One PWA on your phone that handles personal finance, woodshop inventory management, cooking/recipe tracking, home management, and general knowledge — all private, all on-prem, accessible anywhere via Tailscale VPN.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    BowersHub AI (PWA)                     │
│         React 18 + Vite + TailwindCSS + WebSocket        │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  FastAPI Backend (Python)                 │
│                                                          │
│  ┌─────────┐  ┌─────────┐  ┌──────────────────────┐    │
│  │   L1    │  │   L2    │  │         L3           │    │
│  │ Pattern │→ │ Haiku   │→ │  Sonnet + Tool Use   │    │
│  │ Match   │  │Classify │  │  (streaming, multi)  │    │
│  └────┬────┘  └────┬────┘  └──────────┬───────────┘    │
│       │             │                   │                │
│  ┌────▼─────────────▼───────────────────▼────────────┐  │
│  │           Native Python Skills                     │  │
│  │  weather · sports · recall · remember · categorizer│  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │   Ollama     │  │  Anthropic  │  │  apscheduler │  │
│  │ (local LLM)  │  │   (cloud)   │  │  (cron jobs) │  │
│  └──────────────┘  └─────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────┘
         │                    │                │
    ┌────▼────┐        ┌─────▼─────┐    ┌────▼────┐
    │Postgres │        │ Filewriter │    │  n8n    │
    │  (data) │        │(files/IMAP)│    │(scheduled│
    │         │        │            │    │workflows)│
    └─────────┘        └────────────┘    └─────────┘
```

## Key Design Patterns

### 3-Layer Message Routing
Every message flows through a cost-optimized pipeline:
- **L1 — Deterministic** (free): Slash commands (`/weather`, `/score`) and regex patterns. Pure Python, no AI.
- **L2 — Lightweight AI** (~$0.0003): Haiku classifies intent → picks one skill → formats response.
- **L3 — Full Reasoning** (~$0.01-0.05): Sonnet with multi-turn tool use, streaming, web search.

### Native Skill Migration
Skills start as n8n webhook workflows, then migrate to in-process Python functions one at a time. The `_try_native_skill()` dispatcher checks for `native://` URLs before falling through to HTTP. Zero-downtime migration with instant rollback.

### Local + Cloud Model Hybrid
- **Background tasks** (categorization, dedup): Local Ollama model (Llama 3.2 3B, 24 tok/s, free)
- **Interactive chat**: Anthropic API (Haiku for classification, Sonnet for reasoning)
- **Result**: ~$0.15-0.30/day total AI cost for full personal assistant functionality

### Pre-formatted Skill Output
Native skills return a `_display` field with polished markdown. The response looks great whether it comes through L1, L2, or L3 — no reliance on a formatting LLM call.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| BowersHub AI | 5003 | Chat app (FastAPI + React PWA) |
| Postgres | 5432 | All data (finance, inventory, knowledge, chat) |
| Ollama | 11434 | Local LLM for background tasks |
| Filewriter | 5001 | File I/O + IMAP microservice |
| n8n | 5678 | Scheduled workflows (bank sync, email receipts) |
| DB Admin | 5002 | Database browser + inbox processing |
| Dashboard | 8080 | Home hub dashboard |
| Caddy | 443 | HTTPS reverse proxy (Tailscale cert) |

## Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, httpx, APScheduler
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS
- **Database**: PostgreSQL 16 (multi-schema: public, inventory, files, cook, house)
- **AI**: Anthropic Claude (Haiku + Sonnet), Ollama (Llama 3.2 3B)
- **Infra**: Docker, Tailscale VPN, Caddy, Let's Encrypt
- **Workflows**: n8n (scheduled jobs), migrating to in-process Python

## Project Structure

```
bowershub-ai/          — Main chat app (FastAPI + React)
  backend/
    services/          — Native Python skills + routing engine
    migrations/        — Postgres migrations (auto-applied on startup)
    websocket/         — Real-time chat via WebSocket
  frontend/
    src/components/    — React UI components
    src/stores/        — Zustand state (auth, settings, conversations)
db-admin/              — Database browser app
dashboard/             — Home hub dashboard
filewriter/            — File I/O + IMAP microservice
infrastructure/        — Docker compose for shared services
n8n-workflows/         — Workflow build scripts (n8n-as-code)
migrations/            — Shared database migrations
scripts/               — Backup, deploy, cert renewal
anythingllm-skills/    — Legacy skills (retired, kept for reference)
```

## Deployment

```bash
# Deploy any service
./scripts/deploy.sh bowershub-ai
./scripts/deploy.sh db-admin
./scripts/deploy.sh dashboard

# Or directly
cd bowershub-ai && docker compose up -d --build
```

All secrets live in `.env` files on the server (never committed). See `.env.example` files for required variables.

## Cost

~$30/month total:
- Kiro: $19
- Anthropic API: $2-5 (chat interactions)
- SimpleFin: $1.50 (bank sync)
- Electricity: ~$5
- Everything else (Ollama, n8n, Postgres, self-hosted): $0

## License

Personal project. Published as a reference architecture for anyone building their own AI assistant stack.
