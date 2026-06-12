-- Migration 0010_semantic_memory.sql
-- Satisfies R1.3, R1.5, R2.1, R2.5

-- R1.5 guard (first statement): a DO block that raises if the vector type is missing.
-- This ensures the migration fails loudly if the infra (pgvector image swap) wasn't done first.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension is missing. Please follow the instructions in docs/semantic-memory-cutover.md (swap Postgres image to pgvector/pgvector:pg16 and run CREATE EXTENSION vector; as superuser) before deploying this migration.';
    END IF;
END $$;

-- R1.3: Ensure extension exists (privileged install was out-of-band per R4.1).
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the kb_chunks table (R2.1)
-- One chunk per row in v1 (R2.2).
CREATE TABLE public.kb_chunks (
    id bigserial PRIMARY KEY,
    source_type text NOT NULL,
    source_id bigint NOT NULL,
    chunk_index integer NOT NULL DEFAULT 0,
    content text NOT NULL,
    content_hash text NOT NULL,
    embedding public.halfvec(1024), -- Using halfvec(1024) for efficiency (fp16)
    embedding_model text,
    embedding_version integer,
    fts tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embed_state text NOT NULL DEFAULT 'pending',
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT kb_chunks_source_type_check CHECK (source_type = ANY (ARRAY['message'::text, 'entity'::text])),
    CONSTRAINT kb_chunks_embed_state_check CHECK (embed_state = ANY (ARRAY['pending'::text, 'done'::text, 'dead'::text])),
    CONSTRAINT kb_chunks_source_unique UNIQUE (source_type, source_id, chunk_index)
);

-- Partial HNSW index for vector similarity search (R3.1)
CREATE INDEX kb_chunks_embedding_idx ON public.kb_chunks 
USING hnsw (embedding public.halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64)
WHERE (embedding IS NOT NULL);

-- GIN index for hybrid full-text search (R3.2)
CREATE INDEX kb_chunks_fts_idx ON public.kb_chunks USING gin (fts);

-- Btree for joins and reconcile/orphan reaping (R2.5)
CREATE INDEX kb_chunks_source_lookup_idx ON public.kb_chunks (source_type, source_id);

-- Partial index for background worker drain (R2.3)
CREATE INDEX kb_chunks_pending_idx ON public.kb_chunks (id) 
WHERE (embed_state = 'pending');

-- Trigger to maintain updated_at
CREATE TRIGGER update_kb_chunks_updated_at
    BEFORE UPDATE ON public.kb_chunks
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at();
