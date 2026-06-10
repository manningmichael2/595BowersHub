-- Calendar skill: native CalDAV integration via Google App Password
-- Uses the same App Password as Gmail IMAP/SMTP — no OAuth required.

-- Register the calendar skill
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
VALUES (
    'calendar',
    'Read and create Google Calendar events. Can show today''s schedule, upcoming events for any date range, or add new events.',
    'native://calendar',
    'POST',
    true,
    '{
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days ahead to look (0=today, 1=tomorrow, 7=week). Default 7."
            },
            "query": {
                "type": "string",
                "description": "Range shorthand: today, tomorrow, week, next week, or a number of days."
            }
        }
    }'::jsonb
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    webhook_url = EXCLUDED.webhook_url,
    param_schema = EXCLUDED.param_schema,
    is_active = true;

-- Register the calendar-create skill
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
VALUES (
    'calendar-create',
    'Create a new Google Calendar event. Requires a title and start time. End time defaults to 1 hour after start.',
    'native://calendar-create',
    'POST',
    true,
    '{
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Event title (required)"},
            "start": {"type": "string", "description": "Start datetime: YYYY-MM-DD HH:MM or YYYY-MM-DDTHH:MM (required)"},
            "end": {"type": "string", "description": "End datetime: YYYY-MM-DD HH:MM (optional, defaults to 1 hour after start)"},
            "description": {"type": "string", "description": "Event notes or details (optional)"},
            "location": {"type": "string", "description": "Event location (optional)"},
            "all_day": {"type": "boolean", "description": "Set to true to create an all-day event (optional)"}
        }
    }'::jsonb
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    webhook_url = EXCLUDED.webhook_url,
    param_schema = EXCLUDED.param_schema,
    is_active = true;

-- Assign calendar skill to all default workspaces (IDs 1-5)
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT ws.id, s.id
FROM public.bh_workspaces ws
CROSS JOIN public.bh_skills s
WHERE s.name IN ('calendar', 'calendar-create')
ON CONFLICT DO NOTHING;

-- Register /schedule slash command as a builtin (skill_id = NULL).
-- The router_engine handles it directly via _handle_schedule_command.
-- This ensures it works even before the skill registry is checked.
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
VALUES (
    '/schedule',
    'Show your calendar — today, tomorrow, this week, or any date range',
    NULL,
    '{}'::jsonb,
    NULL,
    '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]'::jsonb
);

-- If /schedule already existed (from a prior failed migration attempt), fix it
UPDATE public.bh_slash_commands
SET skill_id = NULL,
    description = 'Show your calendar — today, tomorrow, this week, or any date range',
    flags = '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]'::jsonb
WHERE command = '/schedule';

-- The L2 classifier learns skills dynamically from bh_skills, nothing else needed.
