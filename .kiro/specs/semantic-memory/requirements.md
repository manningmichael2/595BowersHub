# Semantic Memory (pgvector) — Requirements

## Overview

Add a semantic search/memory layer so recall matches by **meaning**, not keywords — the single biggest capability gap for a lifetime knowledge base (`project-review.md` §8.3). The fix uses what already runs: **pgvector** in Postgres + a **local embedding model via Ollama** (free, private). Today recall is Postgres full-text (`tsvector`) over messages/artifacts plus literal grep/`tsvector` over the knowledge graph; this layers semantic similarity *alongside* that (additive, not a replacement).

**v1 scope (this spec) = scope "A": chat messages (`public.bh_messages`) + knowledge-graph entities (`public.bh_entities`)** — both already in Postgres, so v1 needs **no file ingestion and no notes/Obsidian sync**. That keeps v1 useful regardless of whether a markdown-PKM workflow is ever adopted. Notes, documents, and finance are explicitly **out of scope** here (see Future Phases).

Requirements state *what* and *how it's verified*; specific tables/columns/migration numbers/index types are deferred to `design.md`.

## Feature 1: Embedding infrastructure (Ollama + pgvector)

### R1.1 — Local embedding client
The system generates embeddings by calling the local Ollama server's current embeddings endpoint (`POST /api/embed`; `/api/embeddings` is deprecated), reusing the existing Ollama base-URL/`httpx` configuration. It never calls a paid/remote embedding API.

### R1.2 — Embedding model & dimension are DB-driven (no hardcoding)
The embedding model and its vector dimension are resolved at runtime from the existing DB-driven model-config mechanism (the role/alias + platform-settings system), not from code constants. A sane default is seeded by migration. Changing the dimension is a deliberate, config-gated action because it rebuilds the vector storage (see R3.4).

### R1.3 — Schema added via a forward-only migration, runnable as the app role
The vector storage, its index, and the full-text column are created by a forward-only migration that is **safe to run as the non-superuser app role** (`bowershub_app`): it assumes the `vector` extension already exists and never performs the privileged extension install. Parameterized/forward-only per project rules.

### R1.4 — Embedding models are excluded from the chat picker via a data-driven flag
An Ollama-pulled embedding model must not appear as a selectable *chat* model in discovery / `list_active`. The exclusion is driven by a DB capability/role attribute on the model row — **not** a hardcoded name substring (which would itself violate the no-hardcoding rule).

### R1.5 — Missing-extension and infra-ordering safety
If the pgvector extension/type is absent at startup (e.g. the Postgres image was not yet swapped), the migration **fails loudly with an actionable remediation message** rather than ambiguously — and the system never half-applies. The mandatory ordering (infra/extension first, then code deploy) is documented (see R4.1).

## Feature 2: Indexing pipeline (capture → embed → store)

### R2.1 — Chunk store with the keys needed for scoping and versioning
Embeddings live in a chunk store keyed by `(source_type, source_id)` (v1 source types: `message`, `entity`). Each row carries: the chunk text, the embedding, a full-text vector, the `embedding_model` + `embedding_version` it was produced with, a content-hash of the embedded text, and **the scoping key(s) required to authorize a result** (R3.3) — i.e. enough to filter a vector hit to the caller's allowed scope without a fragile multi-join at query time.

### R2.2 — Defined, denoised source→text mapping; one chunk per row in v1
What gets embedded is explicit: for messages, only meaning-bearing roles (`user`/`assistant`) — never `system`/`tool_call`/`tool_result`; for entities, the name + summary (+ defined attribute text). Because both v1 sources are short, **v1 stores one chunk per source row**; the recursive splitter (overlap, long-document chunking) is deferred to Phase B.

### R2.3 — Embedding is off the request path and durable across restart
Embedding work runs in a background worker draining a **DB-backed** pending/outbox state — never blocking a chat turn or HTTP request, and **surviving a process restart** (in-process-only tasks that lose state on restart do not satisfy this).

### R2.4 — Capture cannot be bypassed by any insert site
Every eligible new/updated source row is enqueued for (re)embedding by a mechanism that **no message/entity write path can bypass** (there are 5+ message-insert sites today). Re-embedding fires only when the embedded text's content-hash changed (not on metadata-only edits).

### R2.5 — Index stays consistent on delete/edit
Deleting a source row removes its chunks/vectors; editing text that changes the hash replaces that source's chunks. (Because the store uses a polymorphic `(source_type, source_id)` key, this is enforced by trigger/cleanup, not a single FK cascade.) No orphaned or stale vectors survive a source change.

### R2.6 — Resumable, idempotent backfill of existing data
A batch job embeds the existing `bh_messages`/`bh_entities` backlog. Re-running it produces **zero duplicate chunks** for already-embedded rows; a killed run **resumes from the last committed batch** (keyed on the R2.4 content-hash). It runs off-peak and reports progress.

### R2.7 — Embed-failure handling (Ollama down / model not pulled / wrong dimension)
Write-path embed failures **retry with backoff and dead-letter** without losing or corrupting the source row. A returned vector whose dimension/model does not match the configured one is **rejected, never stored**. (Query-time fallback is R3.3.)

## Feature 3: Hybrid retrieval

### R3.1 — Vector similarity search
The system retrieves nearest neighbors by cosine distance over the embedding index, top-k.

### R3.2 — Hybrid ranking (vector + full-text)
Results combine vector similarity with Postgres full-text ranking, merged via Reciprocal Rank Fusion (rank-based, so score scales need no normalization). The query embedding is a bound parameter, never interpolated.

### R3.3 — Results are correctly scoped, and degrade to FTS when embeddings are unavailable
Retrieval surfaces through the existing `/api/search` and chat `/recall` paths, additively (existing full-text behavior preserved). Scoping is an explicit security requirement:
- **Messages** are filtered to the caller's authorized workspace/conversations (via the R2.1 scoping key).
- **Entities** are returned per the **existing knowledge-graph visibility** (today `bh_entities` is global / `created_by`-scoped with no workspace) — v1 does **not** silently widen access, and this visibility decision is stated, not buried.
- If the query cannot be embedded (Ollama down/model missing), retrieval **falls back to existing full-text** rather than erroring — the additive promise survives an embedding outage.

### R3.4 — Model/version change is handled deterministically
`embedding_version` is defined concretely (see design) and stored per chunk (R2.1). A **same-dimension** model/version change triggers a controlled background re-embed; rows whose vectors are not yet current are **excluded from semantic ranking until repaired** (no silent mixing of vector spaces). A **dimension change** is out of scope of this online path — it is an explicit, destructive re-embed migration, not an in-place repair.

## Feature 4: Operability

### R4.1 — Infra cutover runbook + ordering
A `docs/` runbook (mirroring `docs/c7-db-roles-cutover.md`) documents the one-time privileged steps and their **mandatory ordering before any code deploy**: swap the Postgres image to a pgvector-capable build, the superuser `CREATE EXTENSION vector;`, any `GRANT`s the app role needs, and pulling the embedding model into Ollama.

### R4.2 — Index + queue health is observable
A status surface reports: index coverage (rows embedded vs. total), backfill progress, embedding-queue depth/lag, **dead-letter/failure count**, and the active embedding model/version.

## Acceptance Criteria

- [ ] Recalling a past chat by *meaning* (different words than were used) returns the right `user`/`assistant` message(s) — something keyword search misses; `system`/`tool` messages never appear.
- [ ] A newly sent message becomes semantically searchable at steady state without adding latency to the chat turn (eventually-consistent).
- [ ] Killing the backend mid-backfill and restarting resumes embedding with **no duplicate chunks**; re-running the completed backfill inserts nothing new.
- [ ] Editing an entity's summary updates its vector; deleting it removes its vector (no stale hit).
- [ ] With Ollama stopped, `/recall` and `/api/search` still return full-text results (graceful degradation), and pending embeds resume when Ollama returns.
- [ ] The embedding model + dimension are Postgres rows, changeable without a code edit; no embedding model appears in the chat picker (verified via the capability flag, not a name match).
- [ ] Message results never cross workspace boundaries; entity visibility matches the pre-existing knowledge-graph behavior (no widening).
- [ ] A fresh DB build succeeds as `bowershub_app` given the extension was pre-created by superuser; with the extension absent, the migration fails with a clear remediation message.

## Non-Functional Requirements

- **No hardcoding:** embedding model + dimension and the chat-picker exclusion are DB-driven (alias/settings + capability flag), read at runtime — never code constants. (Project rule #1.)
- **Data safety:** parameterized SQL; forward-only migration; the privileged extension install is out-of-band and documented, never silently attempted by the app.
- **Security:** the app role stays `NOSUPERUSER`; only the documented one-time step uses superuser. RBAC/workspace scoping enforced on all retrieval (R3.3).
- **Performance / cost:** embeddings are local (no API cost) and off the request path; interactive recall stays fast; backfill batched off-peak. Index storage + RAM footprint on the Minisforum (`halfvec` × backlog + ANN index) is estimated before backfill and tracked (R4.2).

## Constraints & Assumptions

- Runs on the Minisforum over Tailscale; Postgres + Ollama are the Portainer `ai-services` stack (repo `infrastructure/` is diverged and does not deploy them — infra changes happen via Portainer).
- The chosen dimension is effectively permanent: changing to a different-dimension model means a full destructive re-embed (R3.4). The default is chosen deliberately up front.
- Eventually-consistent by design: a small lag between a write and its searchability is acceptable; source rows are authoritative, so a briefly-stale index is harmless and self-corrects.

## Dependencies

- **Postgres image** swapped to a pgvector-capable build — Portainer infra change (R4.1).
- **One-time superuser `CREATE EXTENSION vector;`** + grants — the app role cannot install it (R1.3/R4.1).
- **Embedding model pulled into Ollama** into the `ollama_data` volume (R4.1).
- Reused systems: the DB-driven model-config mechanism (R1.2), `bh_messages`/`bh_entities` write paths (R2.4), `services/search.py` + `/recall` (R3.3), the migration runner `backend/database.py` (R1.3/R1.5).

## Future Phases (out of scope for v1, captured so the design doesn't paint them out)

- **Phase B — Notes/PKM:** markdown vault as source of truth (Octarine/Obsidian-compatible, frontmatter-aware), Postgres as a rebuildable derived index with a file-watcher + periodic reconcile. Brings in the recursive chunker (R2.2). Triggered only if a markdown-PKM workflow is adopted.
- **Phase C — Documents** (`files.assets` AI-extracted text) and **finance memos** (low signal-to-noise; last/optional).

## Success Metrics (validation; non-gating unless a target is set here)

- Semantic recall: on a hand-labeled set of "by meaning" queries (the labeled set is built during validation and lives under the spec dir), the correct item appears in top-5 — and hybrid retrieval scores at least as high as vector-only and FTS-only on that set. Target % is set when the labeled set exists; until then this is a **non-gating** validation check.
- Index freshness and chat-path latency targets (N-seconds, unchanged p95) are set in design once measured on real hardware.
