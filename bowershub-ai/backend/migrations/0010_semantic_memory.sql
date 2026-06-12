-- 0010_semantic_memory.sql — pgvector semantic-memory layer (spec: semantic-memory).
--
-- Adds the chunk store (public.kb_chunks) that holds one embedding per source row
-- (chat message / KG entity), plus the DB-driven embedding config and the chat-
-- picker exclusion flag. Forward-only, auto-applied by backend/database.py.
--
-- Runs entirely as the app role `bowershub_app` (NOSUPERUSER): the privileged
-- `CREATE EXTENSION vector` is done out-of-band by the superuser cutover
-- (docs/semantic-memory-cutover.md, R4.1). The guard below makes a forgotten
-- cutover fail LOUDLY and roll back cleanly rather than half-apply (R1.5).

-- Resolve unqualified custom types (vector/halfvec, installed in public). On a
-- from-zero build the baseline sets a session search_path of '' that persists to
-- this migration on the same connection; without this they'd be unresolvable.
-- LOCAL → scoped to this migration's transaction, never leaks.
SET LOCAL search_path = public, pg_catalog;

-- === R1.5 guard: the vector type MUST already exist ========================
-- First (post-search_path) statement, so a missing extension aborts the whole
-- migration's transaction (database.py wraps each migration in one) with an
-- actionable remediation pointer — no partial schema.
DO $$
BEGIN
    PERFORM 'vector'::regtype;
EXCEPTION WHEN undefined_object THEN
    RAISE EXCEPTION 'pgvector missing: the "vector" type does not exist. Run docs/semantic-memory-cutover.md (swap the Postgres image to pgvector/pgvector:pg16, then CREATE EXTENSION vector as superuser) BEFORE deploying this code.';
END $$;

-- No-op when the superuser cutover already installed it; this is NOT the
-- privileged install (IF NOT EXISTS short-circuits before the privilege check
-- when the extension is present, so it is safe as bowershub_app).
CREATE EXTENSION IF NOT EXISTS vector;

-- === Chunk store (R2.1) =====================================================
-- Polymorphic (source_type, source_id) key — no FK, because it spans two source
-- tables; delete-consistency is the worker's anti-join reap (R2.5). One chunk
-- per source row in v1 (chunk_index always 0; R2.2).
CREATE TABLE IF NOT EXISTS public.kb_chunks (
    id                bigserial   PRIMARY KEY,
    source_type       text        NOT NULL CHECK (source_type IN ('message', 'entity')),
    source_id         bigint      NOT NULL,                  -- bigint: source PKs are integer (widening-safe)
    chunk_index       integer     NOT NULL DEFAULT 0,
    content           text        NOT NULL,                  -- the embedded text (denoised, assembled in Python)
    content_hash      text        NOT NULL,                  -- sha256(content); the re-embed gate (R2.4/R2.6)
    embedding         halfvec(1024),                         -- NULL = pending (R2.3); fp16, ~½ storage/RAM
    embedding_model   text,                                  -- which model produced it (R3.4)
    embedding_version integer,                               -- from embedding_config.version (R3.4)
    fts               tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embed_state       text        NOT NULL DEFAULT 'pending'
                                  CHECK (embed_state IN ('pending', 'done', 'dead')),
    last_error        text,                                  -- dead-letter detail (R2.7/R4.2)
    attempts          integer     NOT NULL DEFAULT 0,        -- retry counter → 'dead' after N (R2.7)
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kb_chunks_source_uniq UNIQUE (source_type, source_id, chunk_index)  -- idempotency (R2.6)
);

-- maintain updated_at like the rest of the schema (function exists since baseline)
CREATE OR REPLACE TRIGGER kb_chunks_updated_at
    BEFORE UPDATE ON public.kb_chunks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- === Indexes ================================================================
-- Vector ANN (R3.1): partial HNSW over embedded rows only, so pending NULLs
-- never bloat the index. halfvec_cosine_ops matches the cosine metric.
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw
    ON public.kb_chunks USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding IS NOT NULL;

-- Full-text (R3.2)
CREATE INDEX IF NOT EXISTS kb_chunks_fts_gin
    ON public.kb_chunks USING gin (fts);

-- Reconcile joins + orphan anti-join (R2.4/R2.5)
CREATE INDEX IF NOT EXISTS kb_chunks_source_idx
    ON public.kb_chunks (source_type, source_id);

-- Worker drain: find pending work cheaply (R2.3)
CREATE INDEX IF NOT EXISTS kb_chunks_pending_idx
    ON public.kb_chunks (id) WHERE embed_state = 'pending';

-- === Chat-picker exclusion flag (R1.4) ======================================
-- A capability flag, NOT a name substring: embedding models are discovered into
-- bh_model_rates like any other, but excluded from the chat picker on this flag.
ALTER TABLE public.bh_model_rates
    ADD COLUMN IF NOT EXISTS is_embedding boolean NOT NULL DEFAULT false;

-- === DB-driven embedding config (R1.2) ======================================
-- Seed the default embedding model row so the `embed` alias FK resolves on a
-- from-zero build (mirrors the 0005 cold-start seed). Discovery later refreshes
-- it; ON CONFLICT keeps the is_embedding flag set if the row already exists.
INSERT INTO public.bh_model_rates
    (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok,
     supports_vision, supports_tools, max_output_tokens, is_active, is_embedding)
VALUES
    ('ollama', 'bge-m3', 'BGE-M3 (Embeddings, Local)', 0, 0, false, false, 0, true, true)
ON CONFLICT (model_id) DO UPDATE SET is_embedding = true, is_active = true;

-- `embed` role alias → the seeded model (R1.2). FK requires the row above.
INSERT INTO public.bh_model_aliases (role, model_id) VALUES
    ('embed', 'bge-m3')
ON CONFLICT (role) DO NOTHING;

-- Embedding config: model/dim/version/metric, read fresh by the worker each tick
-- (R3.4). dim is effectively permanent (changing it is a destructive re-embed).
INSERT INTO public.bh_platform_settings (key, value_json) VALUES
    ('embedding_config', '{"model": "bge-m3", "dim": 1024, "version": 1, "metric": "cosine"}')
ON CONFLICT (key) DO NOTHING;

-- Guard: the `embed` role must resolve to an ACTIVE embedding model row, so a
-- botched seed can never silently leave embedding dark on deploy (mirrors the
-- 0005/0009 alias guards).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM public.bh_model_aliases a
          JOIN public.bh_model_rates r ON r.model_id = a.model_id
         WHERE a.role = 'embed' AND r.is_active AND r.is_embedding
    ) THEN
        RAISE EXCEPTION 'embed alias seed failed: role ''embed'' does not resolve to an active embedding model row';
    END IF;
END $$;
