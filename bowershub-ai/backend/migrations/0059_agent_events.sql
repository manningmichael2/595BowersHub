-- 0059_agent_events.sql
-- Dashboard V2 Phase 2: agent/system event log powering the Task Reel + Action
-- Center. Rows are household-global background-task/system events (categorizer,
-- SimpleFin sync, embedding worker, alerts). Some carry an `action_payload` the
-- UI renders as a one-tap mutation button. Forward-only + idempotent.

CREATE TABLE IF NOT EXISTS public.bh_agent_events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    source         text        NOT NULL,
    message        text        NOT NULL,
    level          text        NOT NULL DEFAULT 'info'
                     CHECK (level IN ('info', 'success', 'warning', 'error')),
    -- Optional inline action: {"label","type":"mutation","endpoint","method","body"}
    action_payload jsonb
);

-- The reel and hydration read the most-recent-first; index the sort key.
CREATE INDEX IF NOT EXISTS idx_agent_events_created_at
    ON public.bh_agent_events (created_at DESC, id DESC);
