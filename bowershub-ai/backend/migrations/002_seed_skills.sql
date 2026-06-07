-- ============================================================
-- BowersHub AI: Seed Skills
-- Pre-registers all existing n8n webhook skills.
-- webhook_url is relative to N8N_BASE (resolved at runtime).
-- ============================================================

INSERT INTO public.bh_skills (name, description, webhook_url, http_method, param_schema, response_hint, restricted_users)
VALUES
    ('ask-db', 'Ask any question about your stored data in natural language. Translates to SQL and queries the database. Covers transactions, accounts, balances, inventory (tools, router bits, saw blades, wood), files, recipes, house data — every schema you have access to. Use this for any "how many", "show me", "what did I", "list my X" question.', '/webhook/finance-query', 'POST',
     '{"type":"object","properties":{"question":{"type":"string","description":"Natural language question about your data"}},"required":["question"]}',
     'table', '{1}'),

    ('balances', 'Get current balances for all bank accounts and net worth.', '/webhook/balances', 'POST',
     '{"type":"object","properties":{}}',
     'table', '{1}'),

    ('transactions', 'Get transactions by date range with category breakdown.', '/webhook/transactions', 'POST',
     '{"type":"object","properties":{"start_date":{"type":"string","description":"Start date YYYY-MM-DD"},"end_date":{"type":"string","description":"End date YYYY-MM-DD"}},"required":["start_date","end_date"]}',
     'table', '{1}'),

    ('filter-transactions', 'Search transactions by account, category, amount, or description.', '/webhook/filter', 'POST',
     '{"type":"object","properties":{"account":{"type":"string"},"category":{"type":"string"},"min_amount":{"type":"number"},"max_amount":{"type":"number"},"description":{"type":"string"}}}',
     'table', '{1}'),

    ('spending-summary', 'Monthly spending breakdown by category with top purchases.', '/webhook/transactions', 'POST',
     '{"type":"object","properties":{"month":{"type":"string","description":"Month in YYYY-MM format (optional, defaults to current)"}}}',
     'table', '{1}'),

    ('override-category', 'Re-categorize a transaction. Triggers learning loop for future auto-categorization.', '/webhook/update-category', 'POST',
     '{"type":"object","properties":{"transaction_id":{"type":"integer"},"category":{"type":"string"},"confirm_retroactive":{"type":"boolean"}},"required":["transaction_id","category"]}',
     'single', '{1}'),

    ('smart-capture-extract', 'Extract structured data from text and/or images. Returns draft intents for confirmation.', '/webhook/smart-capture/extract', 'POST',
     '{"type":"object","properties":{"text":{"type":"string"},"image_path":{"type":"string"},"domain_hint":{"type":"string"}}}',
     'json', '{}'),

    ('smart-capture-commit', 'Commit an accepted capture intent to the database or knowledge base.', '/webhook/smart-capture/commit', 'POST',
     '{"type":"object","properties":{"domain":{"type":"string"},"payload":{"type":"object"},"asset_id":{"type":"string"},"extract_token":{"type":"string"}},"required":["domain","payload","extract_token"]}',
     'single', '{}'),

    ('inventory-admin', 'Manage inventory records: update fields, archive, unarchive, delete, or merge duplicates.', '/webhook/inventory-admin', 'POST',
     '{"type":"object","properties":{"action":{"type":"string","enum":["update","archive","unarchive","delete","merge"]},"table":{"type":"string"},"id":{"type":"integer"},"fields":{"type":"object"}},"required":["action","table","id"]}',
     'single', '{1}'),

    ('remember', 'Save a fact to the knowledge base for long-term memory.', '/webhook/remember', 'POST',
     '{"type":"object","properties":{"topic":{"type":"string","description":"Topic slug e.g. finance/accounts"},"fact":{"type":"string","description":"The fact to remember"}},"required":["topic","fact"]}',
     'text', '{}'),

    ('recall', 'Search the knowledge base for previously saved facts.', '/webhook/recall', 'POST',
     '{"type":"object","properties":{"query":{"type":"string","description":"Search term"}},"required":["query"]}',
     'text', '{}'),

    ('send-email', 'Send an email via Gmail SMTP.', '/webhook/send-email', 'POST',
     '{"type":"object","properties":{"to":{"type":"string"},"subject":{"type":"string"},"body":{"type":"string"},"html":{"type":"string"}},"required":["to","subject","body"]}',
     'single', '{1}'),

    ('process-asset', 'Process a file through the vision pipeline: dedup, classify, extract metadata, move to permanent storage.', '/webhook/process-asset', 'POST',
     '{"type":"object","properties":{"path":{"type":"string","description":"File path relative to /files"},"domain_hint":{"type":"string"},"uploaded_by":{"type":"string"}},"required":["path"]}',
     'json', '{}'),

    ('list-files', 'List files in a directory (inbox, inventory, etc).', '/webhook/list-files', 'POST',
     '{"type":"object","properties":{"path":{"type":"string","description":"Directory to list, e.g. inbox"}},"required":["path"]}',
     'table', '{}'),

    ('weather', 'Get current weather conditions.', 'https://wttr.in/?format=j1', 'GET',
     '{"type":"object","properties":{}}',
     'text', '{}')

ON CONFLICT (name) DO NOTHING;
