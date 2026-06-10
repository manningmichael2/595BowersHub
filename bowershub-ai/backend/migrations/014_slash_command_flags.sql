-- Migration 014: Add flags column to slash commands
-- Stores available --flag options for each command as a JSONB array.
-- Frontend reads this instead of hardcoding.

ALTER TABLE public.bh_slash_commands
    ADD COLUMN IF NOT EXISTS flags JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.bh_slash_commands.flags IS
    'Array of {flag, description} objects for --flag autocomplete. Empty array = no flags.';

-- Populate flags for existing commands
UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--clean", "description": "Classify and archive junk/newsletters"},
  {"flag": "--preview", "description": "Dry-run — show what clean would do"},
  {"flag": "--all", "description": "Show all emails with categories"},
  {"flag": "--important", "description": "Show only important/priority emails"},
  {"flag": "--unsubscribe", "description": "Find senders to unsubscribe from"},
  {"flag": "--help", "description": "Show all /email flags"}
]'::jsonb WHERE command = '/email';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--sync", "description": "Pull latest transactions from SimpleFin now"},
  {"flag": "--today", "description": "Today only"},
  {"flag": "--week", "description": "Last 7 days"},
  {"flag": "--month", "description": "This month"},
  {"flag": "--large", "description": "Transactions over $100"},
  {"flag": "--recurring", "description": "Likely recurring charges"},
  {"flag": "--uncategorized", "description": "No category assigned"},
  {"flag": "--help", "description": "Show all /transactions flags"}
]'::jsonb WHERE command = '/transactions';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--tools", "description": "Browse tools"},
  {"flag": "--bits", "description": "Browse router bits"},
  {"flag": "--blades", "description": "Browse saw blades"},
  {"flag": "--help", "description": "Show all /inventory flags"}
]'::jsonb WHERE command = '/inventory';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--tigers", "description": "Detroit Tigers"},
  {"flag": "--lions", "description": "Detroit Lions"},
  {"flag": "--pistons", "description": "Detroit Pistons"},
  {"flag": "--wings", "description": "Detroit Red Wings"},
  {"flag": "--michigan", "description": "Michigan Wolverines"},
  {"flag": "--all", "description": "All tracked teams"}
]'::jsonb WHERE command = '/score';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--postgres", "description": "Check database connection"},
  {"flag": "--ollama", "description": "Check local AI model"},
  {"flag": "--simplefin", "description": "Check bank sync"},
  {"flag": "--anthropic", "description": "Check Claude API key"},
  {"flag": "--imap", "description": "Check Gmail/email connection"},
  {"flag": "--n8n", "description": "Check workflow engine"},
  {"flag": "--pushover", "description": "Check push notifications"},
  {"flag": "--filewriter", "description": "Check file service"}
]'::jsonb WHERE command = '/health';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--week", "description": "AI spend for the last 7 days"},
  {"flag": "--breakdown", "description": "Cost by model"}
]'::jsonb WHERE command = '/cost';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--list", "description": "Show all knowledge topics/files"},
  {"flag": "--recent", "description": "Show last 10 facts saved"}
]'::jsonb WHERE command = '/recall';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--tomorrow", "description": "Just tomorrows forecast"},
  {"flag": "--week", "description": "5-day forecast"}
]'::jsonb WHERE command = '/weather';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--list", "description": "Show pending reminders"},
  {"flag": "--clear", "description": "Cancel all pending reminders"}
]'::jsonb WHERE command = '/remind';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--short", "description": "Just weather + important emails"}
]'::jsonb WHERE command = '/briefing';

UPDATE public.bh_slash_commands SET flags = '[
  {"flag": "--help", "description": "Show usage info"}
]'::jsonb WHERE command = '/local';
