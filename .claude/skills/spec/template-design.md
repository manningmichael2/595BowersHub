# <Feature> — Design

> Satisfies requirements in `requirements.md`. Reference IDs inline (e.g. "satisfies R1.2").

## Architecture Overview

<Text/ASCII diagram of how this fits the existing system (PWA → FastAPI L1/L2/L3 router → skills → Postgres / filewriter / Ollama). What's new vs. what's reused.>

## Components

### <Component / module name>
- **Responsibility:** <one line>
- **Location:** `bowershub-ai/backend/...` or `frontend/src/...`
- **Inputs / Outputs:** <...>
- **Reuses:** <existing helpers — e.g. `_quote_ident`, skill_registry, model_provider>

## Data Flow

<Step-by-step or ASCII diagram of a representative request/job through the new components.>

## Data Model / Migrations

- **New/changed tables:** <name, columns, types, indexes, FKs, constraints>
- **Migration file:** `bowershub-ai/backend/migrations/<NNN>_<name>.sql` (forward-only, auto-applied; pick the next unused number — avoid the known duplicate-number issue)
- **DB-driven config rows:** <any `bh_slash_commands` / skills / model-rate rows this adds — remember, config is data, not code>

## API / Interfaces

- **Endpoints / skills / slash commands:** <method, path or skill name, request/response shape, auth/RBAC>

## Technology Choices

- **<choice>** because <rationale>. Note any new dependency to add to `requirements.txt` / `package.json`.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| <risk> | <mitigation> |

## Test Strategy

- <What gets unit/integration tested; whether it needs the real DB; what the eval/observability hook is, if any.>
