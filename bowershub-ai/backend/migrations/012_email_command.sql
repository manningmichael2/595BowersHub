-- Migration 012: Rename /inbox to /email slash command + add /local
-- The /email command shows a prioritized email digest by default,
-- with sub-commands: /email clean, /email preview, /email all

-- Replace the old /inbox command with /email
UPDATE public.bh_slash_commands
SET command = '/email',
    description = 'Email digest (clean, preview, all)'
WHERE command = '/inbox';

-- If /inbox didn't exist, insert /email fresh
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id)
VALUES ('/email', 'Email digest (clean, preview, all)', NULL, '{}', NULL)
ON CONFLICT DO NOTHING;

-- Add /local command
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id)
VALUES ('/local', 'Chat with local AI (free, no API cost)', NULL, '{}', NULL)
ON CONFLICT DO NOTHING;
