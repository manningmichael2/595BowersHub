-- Reminders table for proactive alerts
CREATE TABLE IF NOT EXISTS public.bh_reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    deliver_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bh_reminders_due
    ON public.bh_reminders (deliver_at)
    WHERE delivered_at IS NULL;

-- Add /remind, /briefing, and /inbox slash commands
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id)
VALUES
    ('/remind', 'Set a timed reminder', NULL, '{}', NULL),
    ('/briefing', 'Show or configure morning briefing', NULL, '{}', NULL),
    ('/inbox', 'Classify and clean inbox emails (via local AI)', NULL, '{}', NULL)
ON CONFLICT DO NOTHING;
