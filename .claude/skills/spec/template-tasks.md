# <Feature> — Tasks

> Each task traces to one or more requirements. Work them top-to-bottom; respect dependencies.

## Task 1: <title>
- **Effort:** S / M / L
- **Dependencies:** none
- **Requirements:** R1.1, R1.2
- [ ] <concrete subtask>
- [ ] <concrete subtask>
- [ ] **Tests:** <what to add / how to verify>

## Task 2: <title>
- **Effort:** S / M / L
- **Dependencies:** Task 1
- **Requirements:** R2.1
- [ ] <subtask>
- [ ] **Migration:** `bowershub-ai/backend/migrations/<NNN>_<name>.sql` (if schema changes)
- [ ] **Tests:** <...>

## Task 3: <title>
- **Effort:** S / M / L
- **Dependencies:** Task 1, Task 2
- **Requirements:** R2.2
- [ ] <subtask>
- [ ] **Tests:** <...>

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied.
- [ ] No hardcoded config introduced (commands/flags/models are DB rows).
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`).
- [ ] `context-log.md` updated with a dated entry.
