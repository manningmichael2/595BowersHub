-- Register the run-categorizer skill and slash command.
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only)
VALUES (
    'run-categorizer',
    'Trigger the bulk transaction categorizer on-demand (uses local AI).',
    'native://run-categorizer',
    'POST',
    '{"type": "object", "properties": {}}',
    'single',
    true,
    '{1}',
    now(),
    false
);

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, is_active, flags)
VALUES (
    '/categorize',
    'Run bulk categorization on all uncategorized transactions',
    (SELECT id FROM bh_skills WHERE name = 'run-categorizer'),
    '{}',
    NULL,
    true,
    '[]'
);
