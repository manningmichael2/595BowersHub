-- Migration 015: Fix critical issues #1-3 from system review
-- 1. Insert missing slash commands (/score, /sports, /inventory, /transactions, /health)
-- 2. Fix weather skill webhook_url to use native handler
-- 3. Clean up orphaned /inbox row
-- 4. Note: duplicate migration numbering is addressed by this file being 015
--    (all prior migrations already ran successfully — this documents the canonical order)

-- ============================================================
-- FIX #2: Insert missing slash commands into bh_slash_commands
-- These commands work via the known_builtins fallback in code,
-- but are invisible to /help, autocomplete, and flag display.
-- ============================================================

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/score', 'Get live sports scores', NULL, '{}', NULL, '[
  {"flag": "--tigers", "description": "Detroit Tigers"},
  {"flag": "--lions", "description": "Detroit Lions"},
  {"flag": "--pistons", "description": "Detroit Pistons"},
  {"flag": "--wings", "description": "Detroit Red Wings"},
  {"flag": "--michigan", "description": "Michigan Wolverines"},
  {"flag": "--all", "description": "All tracked teams"}
]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/score');

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/sports', 'Sports scores, schedules, and box scores', NULL, '{}', NULL, '[
  {"flag": "--schedule", "description": "Upcoming games for tracked teams"},
  {"flag": "--scores", "description": "Latest scores for tracked teams"}
]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/sports');

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/inventory', 'Browse inventory items', NULL, '{}', NULL, '[
  {"flag": "--tools", "description": "Browse tools"},
  {"flag": "--bits", "description": "Browse router bits"},
  {"flag": "--blades", "description": "Browse saw blades"}
]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/inventory');

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/transactions', 'View recent transactions', NULL, '{}', NULL, '[
  {"flag": "--today", "description": "Today only"},
  {"flag": "--week", "description": "Last 7 days"},
  {"flag": "--month", "description": "This month"},
  {"flag": "--large", "description": "Transactions over $100"},
  {"flag": "--uncategorized", "description": "No category assigned"}
]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/transactions');

INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags)
SELECT '/health', 'Check service connections', NULL, '{}', NULL, '[
  {"flag": "--postgres", "description": "Check database"},
  {"flag": "--ollama", "description": "Check local AI model"},
  {"flag": "--anthropic", "description": "Check Claude API"},
  {"flag": "--all", "description": "Check all services"}
]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_slash_commands WHERE command = '/health');

-- ============================================================
-- FIX #3: Update weather skill to use native handler
-- The seed migration (002) set webhook_url to the raw HTTPS URL.
-- Native Python handler should be invoked instead.
-- ============================================================

UPDATE public.bh_skills
SET webhook_url = 'native://weather'
WHERE name = 'weather' AND webhook_url != 'native://weather';

-- Also fix any alias rows
UPDATE public.bh_skills
SET webhook_url = 'native://get-weather'
WHERE name = 'get-weather' AND webhook_url NOT LIKE 'native://%';

-- ============================================================
-- CLEANUP: Remove orphaned /inbox row (renamed to /email in migration 012)
-- ============================================================

DELETE FROM public.bh_slash_commands WHERE command = '/inbox';

-- ============================================================
-- DOCUMENTATION: Migration numbering collisions
-- The following pairs share numbers but all ran successfully:
--   009: sports_score_skill + themes_and_branding
--   010: reminders + settings_json_keys  
--   012: email_command + news_skill_sports_update
--   013: api_toolbox + investment_flag
-- This is now the canonical "next" migration (015).
-- Future migrations continue from 016+.
-- ============================================================
