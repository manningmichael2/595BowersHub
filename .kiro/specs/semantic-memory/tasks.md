# Semantic Memory (pgvector) — Tasks

> Each task traces to requirements in `requirements.md`. Work top-to-bottom; respect dependencies.
> Capture is **reconcile-only** (no triggers) per `design.md` v2.

## Task 1: Infra cutover — pgvector image + superuser extension (runbook)
- **Effort:** M
- **Dependencies:** none
- **Requirements:** R4.1
- [ ] Write `docs/semantic-memory-cutover.md` mirroring `docs/c7-db-roles-cutover.md`: the mandatory **infra-before-code** ordering.
- [ ] Swap the Postgres image to `pgvector/pgvector:pg16` in the Portainer `ai-services` stack (not the repo `infrastructure/`, which is diverged) + restart.
- [ ] One-time as superuser `michael`: `CREATE EXTENSION vector;` + any `GRANT USAGE`/type grants `bowershub_app` needs to create vector columns/indexes.
- [ ] `ollama pull bge-m3` into the `ollama_data` volume; confirm `POST /api/embed` returns a 1024-d vector.
- [ ] **Tests:** runbook dry-run checklist; manual verification `SELECT 'vector'::regtype;` as `bowershub_app`.

## Task 2: Migration `0010_semantic_memory.sql` — kb_chunks + indexes + guard
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.3, R1.5, R2.1, R2.5
- [ ] First statement: `DO`-block guard `PERFORM 'vector'::regtype` → `RAISE EXCEPTION` with the `docs/semantic-memory-cutover.md` remediation (R1.5).
- [ ] `CREATE EXTENSION IF NOT EXISTS vector;` (no-op; never the privileged install).
- [ ] `CREATE TABLE public.kb_chunks` per design (polymorphic `(source_type, source_id)`, `halfvec(1024)` nullable, generated `fts`, `content_hash`, `embedding_model/version`, `embed_state/last_error`); `UNIQUE(source_type, source_id, chunk_index)`.
- [ ] Indexes: partial HNSW `(embedding halfvec_cosine_ops) WHERE embedding IS NOT NULL` `WITH (m=16, ef_construction=64)`; `GIN(fts)`; `btree(source_type, source_id)`; partial `btree WHERE embed_state='pending'`.
- [ ] Confirm the whole migration runs as `bowershub_app` (no superuser ops).
- [ ] **Migration:** `bowershub-ai/backend/migrations/0010_semantic_memory.sql` (forward-only, auto-applied).
- [ ] **Tests:** applies cleanly on `pgvector/pgvector:pg16`; against **stock `postgres:16`** the guard `RAISE EXCEPTION` fires with the remediation message (R1.5).

## Task 3: DB-driven embedding config + chat-picker exclusion
- **Effort:** M
- **Dependencies:** Task 2
- **Requirements:** R1.2, R1.4
- [ ] Seed an `embed` row in `bh_model_aliases`; add `"embed"` to `_TIER_KEYWORDS` + `_FALLBACK_ROLE_MODEL` (`model_catalog.py:474,597`); `resolve_role("embed")` works.
- [ ] Add `bh_platform_settings` key `embedding_config` → `{model:"bge-m3", dim:1024, version:1, metric:"cosine"}`; a reader helper (mirror `model_discovery_*` reads).
- [ ] Add an `is_embedding` capability flag to `bh_model_rates`; set it on discovered embedding models in `OllamaDiscoverySource`; `is_chat_target`/`list_active_public` exclude on the **flag**, not a name match (R1.4).
- [ ] **Tests:** alias resolves; config round-trips; an embed model is absent from the chat picker DTO while present in the catalog.

## Task 4: EmbeddingsClient — Ollama /api/embed
- **Effort:** S
- **Dependencies:** Task 3
- **Requirements:** R1.1, R2.7
- [ ] `services/embeddings.py`: `embed(texts) -> list[vec]` via `POST {OLLAMA_URL}/api/embed`, model from `resolve_role("embed")`, batched; reuse the httpx/base-url pattern.
- [ ] **Reject** any returned vector whose length ≠ configured `dim` (raise; never store) (R2.7).
- [ ] Add `pgvector` to `requirements.txt`; **guarded** `register_vector` on the asyncpg pool (skip + log remediation if type missing, re-register post-migration) (R1.3/R1.5 support).
- [ ] **Tests:** mocked Ollama returns deterministic vectors; dim-mismatch raises; client surfaces errors (no silent drop).

## Task 5: EmbeddingWorker — reconcile loop (find/embed/version)
- **Effort:** L
- **Dependencies:** Task 4
- **Requirements:** R2.2, R2.3, R2.4, R3.4
- [ ] apscheduler job (like `main.py:107`): find dirty rows via `LEFT JOIN` source→`kb_chunks` (no chunk, or `content_hash` differs, or `embedding_version < current`); watermark-paged + periodic full sweep (R2.4).
- [ ] Text assembly in Python: messages WHERE `role ∈ {user,assistant}` only; entities = `name` + `summary` (+ defined attribute text); single chunk in v1 (R2.2).
- [ ] Embed off the request path; all state in `kb_chunks` so restart resumes; read `current` version fresh from `embedding_config` each tick → re-embed stale-version rows (R2.3/R3.4).
- [ ] Backoff retry → `embed_state='dead'` + `last_error` after N attempts (R2.7 support).
- [ ] **Tests:** new message/entity gets embedded; noise roles never produce a chunk; killing mid-run and restarting resumes; bumping `embedding_config.version` re-embeds.

## Task 6: Reconcile consistency — edit re-embed + orphan reap
- **Effort:** S
- **Dependencies:** Task 5
- **Requirements:** R2.5
- [ ] Edit path: changed `content_hash` replaces that source's chunk(s).
- [ ] Delete path: **anti-join** `kb_chunks` whose `source_id` is absent from the source table → delete (no FK, polymorphic key).
- [ ] **Tests:** editing an entity summary updates its vector; deleting a source row removes its chunk(s); no orphan survives.

## Task 7: Backfill (= first reconcile pass)
- **Effort:** S
- **Dependencies:** Task 5
- **Requirements:** R2.6
- [ ] Run the reconcile with no time/watermark bound over existing `bh_messages` + `bh_entities`; batched, off-peak; progress logged.
- [ ] Resumable + idempotent via the `content_hash` + `UNIQUE` gate.
- [ ] Measure + record real rows/sec and total time for `bge-m3` on the box (feeds R4.2 / the storage estimate).
- [ ] **Tests:** re-running the completed backfill inserts zero new chunks; a killed run resumes with no duplicates.

## Task 8: HybridRetriever core — vector ANN + RRF
- **Effort:** M
- **Dependencies:** Task 4, Task 2
- **Requirements:** R3.1, R3.2
- [ ] `services/hybrid_retrieval.py`: cosine ANN (over-fetch `k*OF`) + existing `tsvector` ranking as two CTEs, merged via **RRF (k=60)**; query embedding a **bound param**.
- [ ] Exclude `embedding_version < current` from ranking; bump `hnsw.ef_search` per query as the recall knob.
- [ ] **Tests:** RRF merge math (pure unit); hybrid beats vector-only and FTS-only on a fixture set.

## Task 9: Wire retrieval into messages + entities, scoped, with graceful degrade
- **Effort:** M
- **Dependencies:** Task 8
- **Requirements:** R3.3, R3.4
- [ ] Messages: extend `SearchService._search_messages`; scope by `bh_conversations.workspace_id = ANY(_get_accessible_workspaces(user))`, applied as a **post-ANN join** on the over-fetched candidates (`None`/global spans all accessible).
- [ ] Entities: extend `knowledge_graph.recall_graph` (the path `/recall` uses); visibility unchanged = `is_active` global (no widening/narrowing).
- [ ] Degrade: query-embed failure → FTS-only, never error (R3.3).
- [ ] **Tests:** results never cross workspace boundaries (multi-workspace + global cases); entity visibility matches today's behavior; with Ollama stopped, `/recall` + `/api/search` still return FTS results; pending embeds resume on Ollama return.

## Task 10: Admin status / observability
- **Effort:** S
- **Dependencies:** Task 5
- **Requirements:** R4.2
- [ ] `GET /api/admin/semantic-memory/status` (`require_admin`): coverage (done/total), pending + **dead** counts, queue lag, active model/version; include the storage/RAM footprint estimate.
- [ ] **Tests:** status reflects seeded pending/done/dead rows.

## Task 11: Eval set + end-to-end validation
- **Effort:** S
- **Dependencies:** Task 9
- **Requirements:** R3.1, R3.2, R3.3
- [ ] Build a labeled "by-meaning" query set under `.kiro/specs/semantic-memory/eval/`; assert hybrid ≥ vector-only and FTS-only in top-5 (non-gating until a target % is set).
- [ ] Acceptance walkthrough: recall a past chat by meaning (different words) returns the right `user`/`assistant` message; `system`/`tool` never appear.
- [ ] **Tests:** the eval harness runs against the `pgvector/pgvector:pg16` test DB with mocked embeddings.

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (`spec-validate.py` green).
- [ ] No hardcoded config introduced — embedding model/dim and picker exclusion are DB rows/flags.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q` against a `pgvector/pgvector:pg16` throwaway DB; frontend unaffected).
- [ ] Infra cutover (Task 1) done and ordered **before** the code deploy; `0010` applied.
- [ ] `context-log.md` updated with a dated entry.
