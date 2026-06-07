-- Add sports-score as a native (in-process) skill.
-- webhook_url is set to 'native://' as a marker — skill_executor handles it in Python.

INSERT INTO public.bh_skills (name, description, webhook_url, http_method, is_active, param_schema)
VALUES (
    'sports-score',
    'Get live sports scores for MLB, NHL, NBA, NFL. Provide a team name (e.g., "Tigers", "Red Wings") or ask for all scores in a sport.',
    'native://sports-score',
    'POST',
    true,
    '{"type":"object","properties":{"team":{"type":"string","description":"Team name (e.g., Tigers, Red Wings, Lions, Chiefs)"},"sport":{"type":"string","description":"Sport filter: mlb, nhl, nba, nfl. Optional if team is provided."}}}'::jsonb
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    webhook_url = EXCLUDED.webhook_url,
    param_schema = EXCLUDED.param_schema,
    is_active = true;

-- Assign to General workspace (id=1) so it's available in the default chat
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT 1, id FROM public.bh_skills WHERE name = 'sports-score'
ON CONFLICT DO NOTHING;
