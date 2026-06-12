# Semantic Memory (pgvector) — Design

> Satisfies requirements in `requirements.md`. Reference IDs inline.
> **v2** — revised after the design critic: capture is **reconcile-only** (triggers cut), scoping fixed to the real multi-workspace model, entity wiring made concrete, codec/index/orphan issues resolved.

## Architecture Overview

```
                         ┌──────────────── Postgres (pgvector) ────────────────┐
 source rows (chat, KG)  │  bh_messages / bh_entities        kb_chunks          │
                         │        ▲  (no triggers)               ▲ embedding    │
                         └────────┼──────────────────────────────┼─────────────┘
                                  │  LEFT JOIN: source w/o current chunk  → embed
   EmbeddingWorker ───────────────┤  ANTI JOIN: chunk w/o source row      → reap
   (periodic reconcile,           │  version < current                    → re-embed
    watermark-paged)              └──── Ollama /api/embed (local, free) ──────────
                                                                                 
   query ─► /api/search (messages)  &  /recall→knowledge_graph (entities)
                 └─► HybridRetriever: (vector ANN over-fetch ⊕ tsvector) → RRF → scope-filter top-k
```

**New:** `kb_chunks` table; `EmbeddingsClient` (Ollama `/api/embed`); `EmbeddingWorker` (reconcile loop); `HybridRetriever` woven into the *two* existing retrieval paths; an `embed` model role + `embedding_config` setting; migration `0010`; an infra runbook.
**Reused:** `model_catalog` resolver + `bh_model_aliases`/`bh_platform_settings` (R1.2); `OllamaProvider` httpx/base-url (R1.1); `database.py` migration runner + asyncpg pool (R1.3); `services/search.py` `_search_messages` + `_get_accessible_workspaces` (R3.3, messages); `services/knowledge_graph.py` `recall_graph` (R3.3, entities); apscheduler precedent in `main.py`.

## Capture mechanism — reconcile-only (R2.3/R2.4/R2.5/R2.6) — and why not triggers

The pending set is definitionally *`kb_chunks` rows that need work*. A single background **reconcile loop** maintains it by comparing source tables to `kb_chunks`; no triggers, no `LISTEN/NOTIFY`, no plpgsql.

- **Find work (R2.4):** `LEFT JOIN` eligible source rows (messages WHERE role ∈ {user,assistant}; all active entities) against `kb_chunks` on `(source_type, source_id)`; a row is dirty when it has **no chunk**, or its **content-hash differs** (edit, R2.5), or its **`embedding_version < current`** (model change, R3.4). Paged by a **watermark** (max `source_id`/`updated_at` seen) so steady-state ticks are cheap, with a periodic full sweep.
- **Reap orphans (R2.5):** an **anti-join** — `kb_chunks` whose `source_id` no longer exists in the source table → delete. (This is the delete path; there is no FK because the key is polymorphic.)
- **Backfill (R2.6) = the first reconcile pass.** One code path. Idempotent by the content-hash + `UNIQUE(source_type, source_id, chunk_index)` gate, so re-runs and a backfill/live overlap never duplicate or fight.

**Why reconcile-only over the trigger+NOTIFY design (critic verdict):** we already accept eventual consistency (`requirements.md` Constraints), so triggers buy only sub-second latency no requirement needs — while adding: plpgsql for INSERT/UPDATE/DELETE×2 tables, a `workspace_id` denormalization that goes **stale** if a conversation moves (a silent cross-workspace leak), a trigger-privilege dependency (`AFTER` triggers run as the *writer* role; a failed `kb_chunks` write would abort the user's chat turn — the exact request-path coupling R2.3 forbids), and LISTEN/NOTIFY drop-on-no-listener edges. Reconcile scanning the **source tables themselves** is *strictly stronger* on "no write path can bypass" (R2.4) than a trigger, which `COPY`/bulk/`session_replication_role` can skip. `pg_notify` is recorded as a **deferred latency optimization** (Future Phases), not v1.

## Components

### EmbeddingsClient — `services/embeddings.py`
- Calls Ollama `POST /api/embed` `{model, input:[…]}`; model via `resolve_role("embed")`, dim/version via the `embedding_config` setting (R1.1/R1.2); batches inputs.
- Reuses `OllamaProvider` base URL (`OLLAMA_URL`) + httpx (`model_provider.py:306`).
- **Failure contract (R2.7):** raises on error/timeout; **rejects any vector whose length ≠ configured dim** (never stores wrong-dim).

### EmbeddingWorker — `services/embedding_worker.py`
- apscheduler-driven reconcile (like `main.py:107`): each tick claims a batch of dirty rows (watermark-paged), assembles source text (Python — role filter + name/summary for entities, R2.2), content-hashes, **skips if unchanged**, embeds, upserts `kb_chunks` (`embedding/model/version/fts/hash`, `embed_state='done'`); retry w/ backoff → after N tries `embed_state='dead'` + `last_error` (R2.7/R4.2). All state is in `kb_chunks`, so restart just resumes (R2.3).
- **`current` version is read fresh from `embedding_config` each tick** (not cached), so a version bump propagates deterministically (R3.4).

### Migration `0010_semantic_memory.sql` (R1.3/R1.5)
- `CREATE EXTENSION IF NOT EXISTS vector;` (no-op; privileged install is out-of-band, R4.1), `kb_chunks`, indexes — all runnable as `bowershub_app`.
- **R1.5 guard (first statement):** a `DO $$ BEGIN PERFORM 'vector'::regtype; EXCEPTION WHEN undefined_object THEN RAISE EXCEPTION 'pgvector missing — run docs/semantic-memory-cutover.md (image swap + CREATE EXTENSION) before deploy'; END $$;` so a forgotten image-swap fails **loudly** and the migration's own transaction (`database.py:165`) rolls back cleanly — no half-apply.

### HybridRetriever — `services/hybrid_retrieval.py`, woven into both existing paths
- **Messages →** extend `SearchService._search_messages` (`search.py`): embed query, run vector ANN (over-fetch `k*OF`) + existing `tsvector` CTE, **RRF (k=60)** merge, then apply scope and trim to `k`.
- **Entities →** extend `knowledge_graph.recall_graph` (the path `/recall` actually uses): same RRF over entity vectors + entity `tsvector`. (Correction from v1: `/api/search`'s knowledge branch greps markdown and does **not** touch `bh_entities` — entity wiring goes through `recall_graph`, not `SearchService`.)
- **Scope (R3.3), corrected:** messages filtered by `bh_conversations.workspace_id = ANY(:accessible)` where `:accessible = _get_accessible_workspaces(user)` (the real model: a *list*; `None`/global search spans all accessible) — applied as a **post-ANN join on the over-fetched candidates** (cheap, K small) so it neither pre-filters the index nor relies on a denormalized column that can go stale. Over-fetch covers candidates dropped by scope. Entities: visibility unchanged from today = **`is_active` only, global** (no `created_by`/workspace filter — v1 neither widens nor narrows).
- **Degrade (R3.3):** query-embed failure → skip the vector CTE, return FTS-only; never error.
- **Version safety (R3.4):** ranking excludes `embedding_version < current`. v1 accepts a brief recall dip during a re-embed wave (small corpus, fast) and bumps `hnsw.ef_search` then; the scale-up path (rebuild the partial index as `… WHERE embedding_version = current` on cutover) is noted for later.

### Config & discovery
- **`embed` role:** seed `bh_model_aliases` row + add `"embed"` to `_TIER_KEYWORDS`/`_FALLBACK_ROLE_MODEL` (`model_catalog.py:474,597`) (R1.2).
- **`embedding_config` setting:** `bh_platform_settings` key `embedding_config` → `{model,dim,version,metric}` (read like `model_discovery_*`, `model_catalog.py:403,675`) (R1.2/R3.4).
- **Picker exclusion (R1.4):** a capability flag on `bh_model_rates` (e.g. `is_embedding`) set on discovered embed models; `is_chat_target`/`list_active_public` filter on the **flag**, not a name substring.

## Data Model / Migrations

`public.kb_chunks` (one chunk/row in v1, R2.2):

| column | type | notes |
|---|---|---|
| `id` | bigserial PK | |
| `source_type` | text CHECK in (`message`,`entity`) | |
| `source_id` | bigint | source row id (`bigint` = future-proof; source PKs are `integer`, widening-safe) |
| `chunk_index` | int | 0 in v1 |
| `content` | text | embedded text |
| `content_hash` | text | sha256(content); the re-embed gate (R2.4/R2.6) |
| `embedding` | `halfvec(1024)` NULL | NULL = pending (R2.3) |
| `embedding_model` | text NULL | (R3.4) |
| `embedding_version` | int NULL | from `embedding_config.version` (R3.4) |
| `fts` | tsvector | `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` |
| `embed_state` | text | `pending`\|`done`\|`dead` (R4.2) |
| `last_error` | text NULL | dead-letter detail (R2.7/R4.2) |
| `created_at`/`updated_at` | timestamptz | |

(No denormalized `workspace_id` — scoping is the post-ANN join above, avoiding the stale-leak risk.)
Indexes: `UNIQUE(source_type, source_id, chunk_index)` (idempotency, R2.6); **HNSW** `(embedding halfvec_cosine_ops)` partial `WHERE embedding IS NOT NULL` `WITH (m=16, ef_construction=64)` (R3.1); `GIN(fts)` (R3.2); `btree(source_type, source_id)` (joins/anti-join); partial `btree WHERE embed_state='pending'` (worker drain).
DB-driven rows added: `embed` alias + `embedding_config` (default `bge-m3`/`1024`/`1`/cosine).

**asyncpg codec (corrected):** `register_vector()` needs the type to exist and runs per-connection at pool init — *before* `0010`. So registration is **guarded**: attempt it, and on `undefined_object` log the same remediation pointer and continue (the `0010` guard is the authoritative loud-fail); re-register after migrations confirm the type. This avoids a cryptic pool-init crash that would pre-empt R1.5.

## API / Interfaces
- No new public endpoints — retrieval rides `/api/search` (messages) and `/recall` (entities), now hybrid.
- `GET /api/admin/semantic-memory/status` (`require_admin`): coverage (done/total), pending + **dead** counts, queue lag, active model/version (R4.2).

## Technology Choices
- **`bge-m3` (1024-dim)** default-seeded, DB-overridable — 8K context (future docs), multilingual, top RAG recall; `nomic-embed-text` (768) is the CPU-throughput escape hatch. Dim is effectively permanent (R3.4).
- **`halfvec(1024)`** (fp16, ~½ storage/RAM at ~equal quality); **HNSW + cosine** (`halfvec_cosine_ops`); **RRF (k=60)** hybrid.
- **New dep:** `pgvector` (Python) in `requirements.txt`; Postgres image → `pgvector/pgvector:pg16` (R4.1, infra).

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Image not swapped before deploy → `0010`/pool fails | R1.5 `DO`-block loud guard + **guarded codec registration** + R4.1 infra-before-code ordering |
| Re-embed wave starves results below k (version filter) | over-fetch + `ef_search` bump for v1; partial-index-rebuild-on-cutover for scale (R3.4) |
| Scope leak via stale denormalization | **no denormalized workspace**; post-ANN join to `bh_conversations` w/ `_get_accessible_workspaces` (R3.3) |
| Orphaned vectors after delete (no FK) | reconcile **anti-join** reap step (R2.5) |
| bge-m3 CPU backfill throughput on the Minisforum | **measure rows/sec on real HW before backfill** (record in R4.2); batched off-peak; `nomic` fallback. Backfill = first reconcile pass (no separate racing path) |
| Embedding model leaks into chat picker | capability flag, not name match (R1.4) |

## Test Strategy
- **Real-DB integration** on a throwaway `pgvector/pgvector:pg16` container (the `run-db-tests-locally` pattern, upgraded image; Ollama mocked to a deterministic vector): `0010` applies as the app role; reconcile embeds new message/entity, skips noise roles, reaps orphan on delete (R2.5), re-embeds on edit (content-hash) and on version bump (R3.4); backfill idempotency + **kill-and-resume → no duplicates** (R2.6); **scope never crosses workspaces** incl. multi-workspace + global (R3.3); **FTS-only fallback when the embed client raises** (R3.3/R2.7); picker excludes the embed model via the flag (R1.4).
- **R1.5 guard test:** run `0010` against a **stock `postgres:16`** (no `vector` type) and assert the `RAISE EXCEPTION` remediation message fires — the one security/ops guard CI must cover.
- **Pure unit:** RRF merge; message/entity text assembly + role filter (R2.2); content-hash gate; dim-mismatch rejection (R2.7).
- **Eval (non-gating):** labeled "by-meaning" query set under `.kiro/specs/semantic-memory/eval/`; assert hybrid ≥ vector-only and FTS-only in top-5.
