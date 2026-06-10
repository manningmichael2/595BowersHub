-- Fix /schedule slash command: ensure it's a builtin (skill_id = NULL)
-- so the router handles it directly via _handle_schedule_command.
-- This fixes the case where 012_calendar_skill.sql may have inserted it
-- with skill_id linked to the calendar skill, causing it to go through
-- the skill executor path instead of the builtin handler.

-- If /schedule exists with a skill_id, null it out
UPDATE public.bh_slash_commands
SET skill_id = NULL,
    description = 'Show your calendar — today, tomorrow, this week, or any date range',
    flags = '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]'::jsonb
WHERE command = '/schedule';

-- If /schedule doesn't exist at all, insert it
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/schedule',
       'Show your calendar — today, tomorrow, this week, or any date range',
       NULL,
       '{}'::jsonb,
       NULL,
       '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/schedule');

-- Ensure calendar skills exist and are assigned to workspaces
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
VALUES (
    'calendar',
    'Read and create Google Calendar events. Can show today''s schedule, upcoming events for any date range, or add new events.',
    'native://calendar',
    'POST',
    true,
    '{"type": "object", "properties": {"days": {"type": "integer"}, "query": {"type": "string"}}}'::jsonb
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    webhook_url = EXCLUDED.webhook_url,
    is_active = true;

INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
VALUES (
    'calendar-create',
    'Create a new Google Calendar event. Requires a title and start time.',
    'native://calendar-create',
    'POST',
    true,
    '{"type": "object", "properties": {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "location": {"type": "string"}, "all_day": {"type": "boolean"}}}'::jsonb
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    webhook_url = EXCLUDED.webhook_url,
    is_active = true;

-- Assign to all workspaces
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT ws.id, s.id
FROM public.bh_workspaces ws
CROSS JOIN public.bh_skills s
WHERE s.name IN ('calendar', 'calendar-create')
ON CONFLICT DO NOTHING;
