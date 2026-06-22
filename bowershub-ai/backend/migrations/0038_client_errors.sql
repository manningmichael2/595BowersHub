-- Client-side error telemetry (proactive error visibility).
--
-- Stores uncaught frontend errors / unhandled rejections / render crashes
-- reported by the browser, so a silent client break is captured for review
-- (via the DB browser) and can trigger a rate-limited admin Pushover ping.
-- Accessed by the app's main role only — no finance_reader grant needed.

CREATE TABLE IF NOT EXISTS public.bh_client_errors (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES public.bh_users(id) ON DELETE SET NULL,
    message     TEXT NOT NULL,
    stack       TEXT,
    url         TEXT,
    user_agent  TEXT,
    signature   TEXT,          -- message + top stack frame; used for dedupe/rate-limit
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bh_client_errors_created
    ON public.bh_client_errors (created_at DESC);

-- Supports "have we alerted on this signature recently?" lookups cheaply.
CREATE INDEX IF NOT EXISTS idx_bh_client_errors_sig_created
    ON public.bh_client_errors (signature, created_at DESC);
