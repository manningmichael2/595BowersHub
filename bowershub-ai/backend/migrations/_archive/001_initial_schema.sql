-- ============================================================
-- BowersHub AI: Initial Schema
-- Creates all tables for auth, workspaces, conversations,
-- skills, hooks, artifacts, audit, and notifications.
-- ============================================================

-- AUTHENTICATION & USERS
CREATE TABLE IF NOT EXISTS public.bh_users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK (role IN ('admin', 'member', 'viewer')),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    settings_json   JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.bh_invite_links (
    id              SERIAL PRIMARY KEY,
    token           TEXT NOT NULL UNIQUE,
    created_by      INTEGER REFERENCES public.bh_users(id),
    role            TEXT NOT NULL DEFAULT 'member',
    expires_at      TIMESTAMPTZ NOT NULL,
    used_by         INTEGER REFERENCES public.bh_users(id),
    used_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.bh_refresh_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);

-- WORKSPACES
CREATE TABLE IF NOT EXISTS public.bh_workspaces (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    icon            TEXT,
    color           TEXT,
    system_prompt   TEXT NOT NULL DEFAULT '',
    default_model   TEXT DEFAULT 'auto',
    temperature     NUMERIC(3,2) DEFAULT 0.70,
    max_context_tokens INTEGER DEFAULT 8000,
    auto_capture    BOOLEAN DEFAULT true,
    permitted_schemas TEXT[] DEFAULT '{}',
    settings_json   JSONB DEFAULT '{}'::jsonb,
    created_by      INTEGER REFERENCES public.bh_users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.bh_workspace_users (
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK (role IN ('owner', 'member', 'viewer')),
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.bh_pinned_context (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    context_type    TEXT NOT NULL CHECK (context_type IN ('static', 'dynamic')),
    title           TEXT NOT NULL,
    content         TEXT,
    query           TEXT,
    refresh_minutes INTEGER DEFAULT 60,
    cached_result   TEXT,
    cached_at       TIMESTAMPTZ,
    priority        INTEGER DEFAULT 100,
    token_estimate  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CONVERSATIONS & MESSAGES
CREATE TABLE IF NOT EXISTS public.bh_conversations (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    title           TEXT,
    parent_id       INTEGER REFERENCES public.bh_conversations(id),
    branch_point_msg INTEGER,
    is_archived     BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bh_conversations_workspace_user
    ON public.bh_conversations(workspace_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.bh_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES public.bh_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool_call', 'tool_result')),
    content         TEXT NOT NULL,
    attachments     JSONB DEFAULT '[]'::jsonb,
    model_used      TEXT,
    routing_layer   TEXT CHECK (routing_layer IN ('L1', 'L2', 'L3')),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        NUMERIC(10,6),
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bh_messages_conversation
    ON public.bh_messages(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_bh_messages_fts
    ON public.bh_messages USING gin(to_tsvector('english', content));

-- SKILLS & ROUTING
CREATE TABLE IF NOT EXISTS public.bh_skills (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,
    http_method     TEXT NOT NULL DEFAULT 'POST',
    param_schema    JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_hint   TEXT,
    is_active       BOOLEAN DEFAULT true,
    restricted_users INTEGER[] DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.bh_workspace_skills (
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    skill_id        INTEGER NOT NULL REFERENCES public.bh_skills(id) ON DELETE CASCADE,
    PRIMARY KEY (workspace_id, skill_id)
);

CREATE TABLE IF NOT EXISTS public.bh_slash_commands (
    id              SERIAL PRIMARY KEY,
    command         TEXT NOT NULL,
    description     TEXT NOT NULL,
    skill_id        INTEGER REFERENCES public.bh_skills(id),
    param_template  JSONB DEFAULT '{}'::jsonb,
    workspace_id    INTEGER REFERENCES public.bh_workspaces(id),
    is_active       BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS public.bh_patterns (
    id              SERIAL PRIMARY KEY,
    rule            TEXT NOT NULL,
    rule_type       TEXT NOT NULL DEFAULT 'regex' CHECK (rule_type IN ('regex', 'keyword')),
    skill_id        INTEGER NOT NULL REFERENCES public.bh_skills(id),
    param_template  JSONB DEFAULT '{}'::jsonb,
    description     TEXT,
    priority        INTEGER DEFAULT 100,
    workspace_id    INTEGER REFERENCES public.bh_workspaces(id),
    is_active       BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS public.bh_model_rates (
    id              SERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,
    model_id        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    input_cost_per_mtok  NUMERIC(10,4),
    output_cost_per_mtok NUMERIC(10,4),
    supports_vision BOOLEAN DEFAULT false,
    supports_tools  BOOLEAN DEFAULT false,
    max_output_tokens INTEGER DEFAULT 4096,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HOOKS
CREATE TABLE IF NOT EXISTS public.bh_hooks (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    event_type      TEXT NOT NULL CHECK (event_type IN (
        'message_sent', 'message_received', 'file_uploaded',
        'conversation_started', 'conversation_ended',
        'schedule', 'manual'
    )),
    action_type     TEXT NOT NULL CHECK (action_type IN (
        'call_webhook', 'call_ai', 'capture_context', 'notify'
    )),
    action_config   JSONB NOT NULL DEFAULT '{}'::jsonb,
    conditions      JSONB DEFAULT '{}'::jsonb,
    cron_expression TEXT,
    is_enabled      BOOLEAN DEFAULT true,
    created_by      INTEGER REFERENCES public.bh_users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.bh_hook_log (
    id              SERIAL PRIMARY KEY,
    hook_id         INTEGER NOT NULL REFERENCES public.bh_hooks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    trigger_data    JSONB,
    action_result   JSONB,
    success         BOOLEAN NOT NULL,
    error_message   TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ARTIFACTS
CREATE TABLE IF NOT EXISTS public.bh_artifacts (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES public.bh_conversations(id) ON DELETE CASCADE,
    message_id      INTEGER NOT NULL REFERENCES public.bh_messages(id) ON DELETE CASCADE,
    artifact_type   TEXT NOT NULL CHECK (artifact_type IN (
        'code', 'html', 'mermaid', 'chart', 'markdown', 'table'
    )),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    language        TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    parent_id       INTEGER REFERENCES public.bh_artifacts(id),
    file_path       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- AUDIT LOG
CREATE TABLE IF NOT EXISTS public.bh_audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES public.bh_users(id),
    action          TEXT NOT NULL,
    target_type     TEXT,
    target_id       INTEGER,
    details         JSONB DEFAULT '{}'::jsonb,
    ip_address      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bh_audit_log_user
    ON public.bh_audit_log(user_id, created_at DESC);

-- NOTIFICATIONS
CREATE TABLE IF NOT EXISTS public.bh_notification_prefs (
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    web_push        BOOLEAN DEFAULT true,
    pushover        BOOLEAN DEFAULT false,
    quiet_start     TIME,
    quiet_end       TIME,
    PRIMARY KEY (user_id, event_type)
);

CREATE TABLE IF NOT EXISTS public.bh_push_subscriptions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    subscription    JSONB NOT NULL,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
