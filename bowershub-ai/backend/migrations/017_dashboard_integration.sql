-- Migration 017: Dashboard Integration
--
-- Creates the widget registry and layout persistence tables for the integrated
-- dashboard (/dashboard route). Replaces the standalone Flask dashboard.
--
-- Tables:
--   bh_dashboard_widgets  — DB-driven widget type registry
--   bh_dashboard_layouts  — Per-user layout persistence (widget arrangement per page)
--
-- Seeds all 12 widget types and default layouts for the admin user.

-- Widget type registry (what widgets are available)
CREATE TABLE IF NOT EXISTS public.bh_dashboard_widgets (
    id              SERIAL PRIMARY KEY,
    widget_key      TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    description     TEXT,
    category        TEXT NOT NULL DEFAULT 'general',
    data_endpoint   TEXT NOT NULL,
    default_config  JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_pages   JSONB NOT NULL DEFAULT '[]'::jsonb,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- User layout persistence (arrangement per page)
CREATE TABLE IF NOT EXISTS public.bh_dashboard_layouts (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    page_key        TEXT NOT NULL,
    widgets         JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, page_key)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_layouts_user
    ON public.bh_dashboard_layouts(user_id);

-- Seed all 12 widget types
INSERT INTO public.bh_dashboard_widgets
    (widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order)
VALUES
    ('weather', 'Weather', 'Current conditions and 3-day forecast', 'general',
     '/api/dashboard/weather',
     '{"polling_interval_ms": 300000, "location": "Clawson,MI"}'::jsonb,
     '["overview"]'::jsonb, 1),

    ('finance_summary', 'Finance Summary', 'MTD spending, top categories, and net change', 'finance',
     '/api/dashboard/finance/summary',
     '{"polling_interval_ms": 60000}'::jsonb,
     '["overview", "finance"]'::jsonb, 2),

    ('finance_balances', 'Balances', 'Account balances grouped by type with net worth', 'finance',
     '/api/dashboard/finance/balances',
     '{"polling_interval_ms": 60000}'::jsonb,
     '["finance"]'::jsonb, 3),

    ('recent_transactions', 'Recent Transactions', 'Last 10 transactions with details', 'finance',
     '/api/dashboard/finance/recent-transactions',
     '{"polling_interval_ms": 60000}'::jsonb,
     '["finance"]'::jsonb, 4),

    ('system_health', 'System Health', 'CPU, memory, disk usage, and uptime', 'system',
     '/api/dashboard/system-health',
     '{"polling_interval_ms": 30000}'::jsonb,
     '["system"]'::jsonb, 5),

    ('containers', 'Containers', 'Docker container status and quick links', 'system',
     '/api/dashboard/containers',
     '{"polling_interval_ms": 30000, "links": {"n8n": "http://100.106.180.101:5678", "bowershub-ai": "https://595bowershub.tailc4d58a.ts.net"}}'::jsonb,
     '["overview", "system"]'::jsonb, 6),

    ('inventory', 'Inventory', 'Item counts per inventory table', 'general',
     '/api/dashboard/inventory',
     '{"polling_interval_ms": 300000}'::jsonb,
     '["system"]'::jsonb, 7),

    ('knowledge_base', 'Knowledge Base', 'Knowledge base file and topic counts', 'general',
     '/api/dashboard/knowledge',
     '{"polling_interval_ms": 300000}'::jsonb,
     '["system"]'::jsonb, 8),

    ('recent_emails', 'Recent Emails', 'Unread count and last 5 subject lines', 'general',
     '/api/dashboard/emails',
     '{"polling_interval_ms": 120000}'::jsonb,
     '["overview"]'::jsonb, 9),

    ('tailscale_devices', 'Tailscale Devices', 'Device list with online/offline status', 'system',
     '/api/dashboard/tailscale',
     '{"polling_interval_ms": 60000}'::jsonb,
     '["system"]'::jsonb, 10),

    ('api_spend', 'API Spend', '7-day Anthropic API usage and cost breakdown', 'system',
     '/api/dashboard/api-spend',
     '{"polling_interval_ms": 300000}'::jsonb,
     '["finance"]'::jsonb, 11),

    ('sports_scores', 'Sports Scores', 'Recent scores for tracked teams', 'general',
     '/api/dashboard/sports-scores',
     '{"polling_interval_ms": 300000}'::jsonb,
     '["overview"]'::jsonb, 12)
ON CONFLICT (widget_key) DO NOTHING;

-- Seed default layouts for admin user (id=1)
-- Overview page: Weather, Finance Summary, Containers, Recent Emails, Sports Scores
INSERT INTO public.bh_dashboard_layouts (user_id, page_key, widgets, updated_at)
VALUES (1, 'overview', '[
    {"widget_key": "weather", "position": 0, "config_overrides": {}},
    {"widget_key": "finance_summary", "position": 1, "config_overrides": {}},
    {"widget_key": "containers", "position": 2, "config_overrides": {}},
    {"widget_key": "recent_emails", "position": 3, "config_overrides": {}},
    {"widget_key": "sports_scores", "position": 4, "config_overrides": {}}
]'::jsonb, now())
ON CONFLICT (user_id, page_key) DO NOTHING;

-- Finance page: Finance Summary, Balances, Recent Transactions, API Spend
INSERT INTO public.bh_dashboard_layouts (user_id, page_key, widgets, updated_at)
VALUES (1, 'finance', '[
    {"widget_key": "finance_summary", "position": 0, "config_overrides": {}},
    {"widget_key": "finance_balances", "position": 1, "config_overrides": {}},
    {"widget_key": "recent_transactions", "position": 2, "config_overrides": {}},
    {"widget_key": "api_spend", "position": 3, "config_overrides": {}}
]'::jsonb, now())
ON CONFLICT (user_id, page_key) DO NOTHING;

-- System page: System Health, Containers, Tailscale Devices, Inventory, Knowledge Base
INSERT INTO public.bh_dashboard_layouts (user_id, page_key, widgets, updated_at)
VALUES (1, 'system', '[
    {"widget_key": "system_health", "position": 0, "config_overrides": {}},
    {"widget_key": "containers", "position": 1, "config_overrides": {}},
    {"widget_key": "tailscale_devices", "position": 2, "config_overrides": {}},
    {"widget_key": "inventory", "position": 3, "config_overrides": {}},
    {"widget_key": "knowledge_base", "position": 4, "config_overrides": {}}
]'::jsonb, now())
ON CONFLICT (user_id, page_key) DO NOTHING;
