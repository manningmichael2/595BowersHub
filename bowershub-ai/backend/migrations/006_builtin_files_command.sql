-- Make /files a built-in slash command (no backing skill).
-- The router handles it directly by listing FILES_ROOT subdirectories.

UPDATE public.bh_slash_commands
SET skill_id = NULL, param_template = '{}'::jsonb
WHERE command = '/files';
