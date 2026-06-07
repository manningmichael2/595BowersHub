-- Migration 004: Email label tracking for AI inbox triage
-- Tracks which labels the AI has used and how often, so the classifier
-- stays consistent over time.

CREATE TABLE IF NOT EXISTS public.email_labels (
  label       TEXT PRIMARY KEY,              -- e.g., 'AI-Tags/Receipts'
  times_used  INTEGER NOT NULL DEFAULT 1,
  first_used  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed with the initial labels we know we want
INSERT INTO public.email_labels (label, times_used) VALUES
  ('AI-Tags/Receipts', 0),
  ('AI-Tags/Bills', 0),
  ('AI-Tags/Subscriptions', 0),
  ('AI-Tags/Shipping', 0),
  ('AI-Tags/Finance', 0),
  ('AI-Tags/Pets', 0),
  ('AI-Tags/House', 0),
  ('AI-Tags/Travel', 0),
  ('AI-Tags/Social', 0),
  ('AI-Tags/Newsletters', 0),
  ('AI-Tags/Spam-ish', 0),
  ('AI-Tags/Action-Required', 0)
ON CONFLICT (label) DO NOTHING;

-- Track which emails have been processed so we don't re-classify
CREATE TABLE IF NOT EXISTS public.email_classified (
  message_id  TEXT PRIMARY KEY,              -- RFC message-id header
  classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  labels      TEXT[] NOT NULL DEFAULT '{}'   -- labels applied
);

CREATE INDEX IF NOT EXISTS idx_email_classified_at ON public.email_classified (classified_at DESC);
