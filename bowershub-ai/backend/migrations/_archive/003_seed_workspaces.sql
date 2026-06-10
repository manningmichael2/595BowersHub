-- ============================================================
-- BowersHub AI: Seed Workspaces and Slash Commands
-- Creates default workspaces. User assignments happen at first
-- login (admin user gets all, others get assigned via admin UI).
-- ============================================================

-- Default workspaces
INSERT INTO public.bh_workspaces (name, description, icon, color, system_prompt, permitted_schemas, auto_capture)
VALUES
    ('General', 'General-purpose assistant. Ask anything, save facts, send emails.', '🏠', '#6366f1',
     'You are BowersHub AI, a helpful personal assistant for Michael. You can search the knowledge base, remember facts, check the weather, send emails, and answer general questions. Be conversational, helpful, and concise.',
     '{public}', true),

    ('Finance', 'Financial advisor with access to all bank accounts, transactions, and spending data.', '💰', '#10b981',
     'You are BowersHub AI acting as a personal financial advisor. You have access to all bank accounts, transactions, and spending data. For complex questions, use the ask-db skill (natural-language SQL across all your data). For common lookups, use balances, transactions, or spending-summary. Format monetary amounts with $ and two decimal places. Negative amounts are spending, positive are income. Exclude transfers from spending analysis unless specifically asked.',
     '{public,files}', true),

    ('Woodshop', 'Woodworking assistant with tool inventory, router bits, and project tracking.', '🪚', '#f59e0b',
     'You are BowersHub AI acting as a woodshop assistant. You have access to the tool inventory (inventory.tools, inventory.router_bits, inventory.saw_blades) and can help catalog new tools, look up specifications, and track projects. When photos are shared, offer to process them into the inventory via smart-capture.',
     '{inventory,files}', true),

    ('Cooking', 'Recipe assistant for Michael and Manon. Track recipes, cook logs, and shopping lists.', '🍳', '#ef4444',
     'You are BowersHub AI acting as a cooking assistant for Michael and Manon. You can help find recipes, track what was cooked and when, manage shopping lists, and remember cooking preferences. Be friendly and suggest ideas when asked.',
     '{cook,files}', true),

    ('House', 'Home management — rooms, maintenance, improvements, and shared tasks.', '🏡', '#8b5cf6',
     'You are BowersHub AI acting as a home management assistant. You can help track rooms, maintenance tasks, home improvements, and shared household information. Both Michael and Manon have access to this workspace.',
     '{house,files}', true)

ON CONFLICT DO NOTHING;

-- Global slash commands (workspace_id = NULL means available everywhere)
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id)
VALUES
    ('/weather', 'Get current weather', (SELECT id FROM public.bh_skills WHERE name = 'weather'), '{}', NULL),
    ('/recall', 'Search knowledge base', (SELECT id FROM public.bh_skills WHERE name = 'recall'), '{"query": "$args"}', NULL),
    ('/files', 'List inbox files', (SELECT id FROM public.bh_skills WHERE name = 'list-files'), '{"path": "inbox"}', NULL),
    ('/help', 'List available commands', NULL, '{}', NULL),
    ('/new', 'Start a new conversation', NULL, '{}', NULL),
    ('/cost', 'Show today''s AI spend breakdown', NULL, '{}', NULL)
ON CONFLICT DO NOTHING;

-- Finance-specific slash commands
INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id)
VALUES
    ('/balance', 'Show all account balances', (SELECT id FROM public.bh_skills WHERE name = 'balances'), '{}',
     (SELECT id FROM public.bh_workspaces WHERE name = 'Finance')),
    ('/spend', 'Monthly spending breakdown', (SELECT id FROM public.bh_skills WHERE name = 'spending-summary'), '{}',
     (SELECT id FROM public.bh_workspaces WHERE name = 'Finance'))
ON CONFLICT DO NOTHING;

-- Assign skills to workspaces
-- General: recall, remember, weather, send-email, list-files
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE w.name = 'General' AND s.name IN ('recall', 'remember', 'weather', 'send-email', 'list-files')
ON CONFLICT DO NOTHING;

-- Finance: ask-db, balances, transactions, filter-transactions, spending-summary, override-category, recall, remember
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE w.name = 'Finance' AND s.name IN ('ask-db', 'balances', 'transactions', 'filter-transactions', 'spending-summary', 'override-category', 'recall', 'remember')
ON CONFLICT DO NOTHING;

-- Woodshop: smart-capture-extract, smart-capture-commit, inventory-admin, recall, remember, list-files, process-asset
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE w.name = 'Woodshop' AND s.name IN ('smart-capture-extract', 'smart-capture-commit', 'inventory-admin', 'recall', 'remember', 'list-files', 'process-asset')
ON CONFLICT DO NOTHING;

-- Cooking: smart-capture-extract, smart-capture-commit, recall, remember, list-files
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE w.name = 'Cooking' AND s.name IN ('smart-capture-extract', 'smart-capture-commit', 'recall', 'remember', 'list-files')
ON CONFLICT DO NOTHING;

-- House: smart-capture-extract, smart-capture-commit, recall, remember, list-files
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE w.name = 'House' AND s.name IN ('smart-capture-extract', 'smart-capture-commit', 'recall', 'remember', 'list-files')
ON CONFLICT DO NOTHING;
