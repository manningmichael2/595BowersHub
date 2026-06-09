---
name: spec
description: Author a best-in-class, Kiro-compatible feature spec (requirements → design → tasks in .kiro/specs/<feature>/) using grounded research, a design tournament, adversarial critique, and automated traceability. Use ONLY when the user explicitly runs /spec to plan a feature. Do not auto-invoke.
argument-hint: [feature-name]
allowed-tools: Read Write Edit Bash(mkdir -p *) Bash(uuidgen) Bash(python3 *) Bash(git *) Agent Task
disable-model-invocation: true
---

# `/spec $ARGUMENTS` — best-in-class spec authoring

Produce a feature spec for **$ARGUMENTS** in `.kiro/specs/<slug>/` (Kiro-compatible
format, so either tool can read/continue it). This is **not** a three-file
template fill — it's an orchestrated workflow that makes the spec better than a
single pass could: requirements are **grounded** in the real codebase, the design
is the winner of a **tournament** of approaches, each phase is **adversarially
critiqued** before you see it, and traceability is **mechanically enforced**.

Templates (follow their structure exactly):
@./template-requirements.md
@./template-design.md
@./template-tasks.md

Read `CLAUDE.md` and `.kiro/steering/595bowershub-project.md` for project context, and `project-review.md` for known critical issues. **Non-negotiable project rule: NO HARDCODING** — commands/flags/themes/skills/model lists are DB-driven; new ones are DB rows, not code constants. Parameterized SQL only. Forward-only migrations.

The flow is **multi-turn and human-gated**: do a phase, present it, then **stop and wait** for approval before the next. Never write all three files at once.

## Phase 0 — Setup + calibrate rigor (no approval needed)

1. Slugify "$ARGUMENTS" → lowercase-kebab (e.g. "Dynamic Model Discovery" → `dynamic-model-discovery`). If empty, ask for a name and stop.
2. `mkdir -p .kiro/specs/<slug>`.
3. Create `.kiro/specs/<slug>/.config.kiro` (single line): `{"specId": "<uuid>", "workflowType": "requirements-first", "specType": "feature"}` — generate the UUID with `uuidgen` (fallback `python3 -c "import uuid;print(uuid.uuid4())"`).
4. **Calibrate depth** by judging the feature's scope, then tell the user the level you picked and why (they can override):
   - **light** — small/localized (one file, no schema change). Skip research & tournament; one critique pass.
   - **standard** (default) — typical feature. 1 grounding research pass, single design + 1 critique pass per phase.
   - **deep** — architectural / security / data-integrity / cross-cutting (e.g. the foundation work in `project-review.md`). Full machinery: parallel grounding research, a design tournament, and a critic pass at every phase.

Scale the orchestration below to the chosen level. **Spawn subagents in parallel** (multiple `Agent`/`Task` calls in one turn) — never serially.

## Phase 1 — Requirements (grounded)

1. **Ground it** (standard/deep): spawn the `spec-researcher` subagent — for **deep**, fan out 2–3 in parallel across distinct areas (existing code & reusable patterns; constraints & prior decisions from steering/context-log/project-review; external best practices). Wait for results. Requirements must be written **from this evidence**, not guessed.
2. Write `requirements.md` from the template: numbered `R<n>.<m>` items (grouped under `## Feature N` when there are distinct areas), acceptance criteria, non-functional requirements (fold in the project guardrails), constraints, dependencies, success metrics.
3. **Critique** (standard/deep): spawn the `spec-critic` subagent on `requirements.md`. Apply its BLOCKER/MAJOR findings; note any you consciously reject and why.
4. **Stop:** "Requirements drafted at `.kiro/specs/<slug>/requirements.md` (level: <level>; <N> requirements; critic findings addressed). Review/edit, then say **design**."

## Phase 2 — Design (tournament)

Only after approval.
- **light/standard:** investigate the relevant code read-only, write one grounded `design.md`, then run `spec-critic` on it and apply findings.
- **deep — design tournament:** spawn 2–3 subagents (`Agent`) **in parallel**, each tasked to propose a design for the same requirements from a **distinct angle**:
  - *minimal-change* — smallest diff that satisfies the requirements, maximally reusing existing code.
  - *ideal-architecture* — the clean long-term design ignoring migration cost.
  - *risk-first* — optimize for safety/reversibility/security (relevant to the C1/C2-class issues).
  Then **synthesize**: pick the strongest spine and graft the best ideas from the others into a single `design.md`, recording the key trade-off decisions and why the losers lost. Run `spec-critic` on the result and apply findings.
- Reference requirement IDs inline ("satisfies R1.2").
- **Stop:** "Design drafted (approach: <synthesis summary>). Review/edit, then say **tasks**."

## Phase 3 — Tasks (executable + traceable)

Only after approval.
1. Write `tasks.md` from the template: numbered `## Task N` blocks with `- [ ]` subtasks, effort, explicit dependencies, a `Requirements:` line naming the `R<n>.<m>` items each task satisfies, a per-task test/migration step, and a Definition of Done.
2. **Enforce traceability (mechanical gate):** run
   `python3 .claude/hooks/spec-validate.py .kiro/specs/<slug>/`
   and fix every UNCOVERED requirement, DANGLING ref, and UNTRACED task until it exits 0. Show the user the final clean output.
3. **Final critique** (deep): one more `spec-critic` pass across all three files for seam gaps.
4. **Stop:** "Spec complete and traceable in `.kiro/specs/<slug>/`. Commit with `git add .kiro/specs/<slug>` and add a one-line entry to `context-log.md`."

## Principles
- Evidence over assertion: cite `file:line` in the design where it reuses or changes existing code.
- Every requirement → ≥1 task; every task → ≥1 requirement (the validator enforces this).
- The critic exists to find gaps before code does — take its BLOCKERs seriously.
- This skill only *authors* the spec. Implementation is a separate step: work tasks one at a time, each verified against its Definition of Done.
