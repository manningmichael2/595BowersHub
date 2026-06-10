-- Migration 018: Password reset tokens
-- Enables email-based password recovery without admin intervention.

CREATE TABLE IF NOT EXISTS public.bh_password_reset_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
    ON public.bh_password_reset_tokens(user_id);

-- Clean up expired tokens periodically (older than 24h)
-- This index helps the cleanup query
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires
    ON public.bh_password_reset_tokens(expires_at);
