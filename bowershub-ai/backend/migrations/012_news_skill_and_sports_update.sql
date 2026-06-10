-- Migration 012: Add /news skill and update sports-score description
-- The sports-score skill now handles pitching matchups, game details, and lineups
-- so the L2 classifier will route "who is pitching" queries to it instead of L3.

-- Update sports-score description to cover game info (pitchers, matchups)
UPDATE public.bh_skills
SET description = 'Get live sports scores, pitching matchups, game details for MLB, NHL, NBA, NFL, soccer, and more. Handles: scores, who is pitching, starting pitchers, game status, current pitcher. Provide a team name (e.g., "Tigers", "Red Wings") or ask for all scores in a sport.'
WHERE name = 'sports-score';

-- Add news skill (only if it doesn't already exist)
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
SELECT
    'news',
    'Get current news headlines. Categories: top (general), sports, tech, world, business. Returns latest headlines from free RSS sources.',
    'native://news',
    'POST',
    true,
    '{"type": "object", "properties": {"category": {"type": "string", "description": "News category: top, sports, tech, world, business"}, "limit": {"type": "integer", "description": "Number of headlines (default 10, max 20)"}}}'
WHERE NOT EXISTS (SELECT 1 FROM public.bh_skills WHERE name = 'news');

-- Register /news slash command (only if it doesn't already exist)
INSERT INTO public.bh_slash_commands (command, description, flags)
SELECT
    '/news',
    'Get current news headlines',
    '[{"flag": "sports", "description": "Sports headlines (ESPN)"}, {"flag": "tech", "description": "Tech news (Ars Technica)"}, {"flag": "world", "description": "World news"}, {"flag": "business", "description": "Business news"}]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/news');

-- Assign news skill to General workspace (id=1)
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT 1, id FROM public.bh_skills WHERE name = 'news'
AND NOT EXISTS (
    SELECT 1 FROM public.bh_workspace_skills ws
    JOIN public.bh_skills s ON s.id = ws.skill_id
    WHERE ws.workspace_id = 1 AND s.name = 'news'
);
