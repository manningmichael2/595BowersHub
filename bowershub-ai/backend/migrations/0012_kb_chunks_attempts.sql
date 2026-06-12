-- 0012_kb_chunks_attempts.sql
-- Add a retry counter to kb_chunks so the EmbeddingWorker can back off and
-- dead-letter transient embed failures after N attempts (R2.7), instead of
-- retrying forever or silently dropping a row whose embedding failed.

ALTER TABLE public.kb_chunks
    ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
