-- 0051 — merge /score into /sports (it was a redundant alias).
--
-- /sports and /score both already routed to the same _handle_sports_command, and
-- /score's per-team flags (--tigers, --lions, …) were display-only — never parsed
-- (the handler takes free-text teams, e.g. `/sports tigers`). Keep the richer
-- /sports (scores + schedules + any team) and drop /score. The code's
-- ("/sports", "/score") tuple is narrowed to /sports in the same change.
-- Reversible: re-add the row via Admin if ever wanted.

DELETE FROM public.bh_slash_commands
 WHERE command = '/score' AND workspace_id IS NULL;
