# <Feature> — Requirements

## Overview

<1–3 sentences: what this feature is and the user value. Why now.>

## Feature 1: <area name>

### R1.1 — <short title>
<Plain statement of the requirement. Prefer "The system <does X> so that <benefit>." Be specific and testable.>

### R1.2 — <short title>
<...>

## Feature 2: <area name>

### R2.1 — <short title>
<...>

## Acceptance Criteria

- [ ] <Observable, checkable outcome 1>
- [ ] <Observable, checkable outcome 2>

## Non-Functional Requirements

- **No hardcoding:** any new commands/flags/themes/skills/model references are DB-driven (Postgres), read via API — never code constants. (Project rule #1.)
- **Data safety:** parameterized SQL; schema changes via forward-only migration files; consider backup/rollback for destructive changes.
- **Security:** least-privilege DB access where applicable; no secrets in code; auth/RBAC respected.
- **Performance / cost:** <e.g. keep interactive paths off L3 where possible; cache repeated context>.

## Constraints & Assumptions

- <Timeline, infra (runs on the Minisforum over Tailscale), existing-system constraints>

## Dependencies

- <Other specs, services (filewriter/n8n/Ollama), external APIs, migrations that must land first>

## Success Metrics

- <Metric>: <target>
