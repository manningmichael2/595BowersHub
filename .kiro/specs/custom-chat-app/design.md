# Technical Design Document

## Overview

This document defines the technical architecture for BowersHub AI — a self-hosted personal AI assistant platform. The system is composed of a FastAPI backend serving a React PWA frontend, deployed as a single Docker container on the 595BowersHub Minisforum server. It integrates with existing infrastructure (Postgres, n8n webhooks, filewriter, knowledge base) and provides intelligent message routing, multi-user workspaces, automated context capture, and a polished conversational UI.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Container                          │
│                      (bowershub-ai:5003)                         │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              FastAPI Application Server                    │   │
│  │                                                           │   │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌────────┐ │   │
│  │  │  Auth   │  │  Router   │  │   Skills   │  │ Hooks  │ │   │
│  │  │ Module  │  │  Engine   │  │  Executor  │  │ Engine │ │   │
│  │  └─────────┘  └──────────┘  └────────────┘  └────────┘ │   │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌────────┐ │   │
│  │  │ Model   │  │ Context  │  │  Artifact  │  │  File  │ │   │
│  │  │Provider │  │ Capture  │  │  Manager   │  │Manager │ │   │
│  │  └─────────┘  └──────────┘  └────────────┘  └────────┘ │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │          WebSocket Manager (streaming)               │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Static Files (React PWA build output)             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌──────────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────┐
│   Postgres   │ │    n8n    │ │ Anthropic │ │  Filewriter   │
│  (finance)   │ │ webhooks  │ │ / Bedrock │ │  / Files      │
└──────────────┘ └───────────┘ └───────────┘ └───────────────┘
```

## Components and Interfaces

### 1. Backend Module Structure

```
bowershub-ai/
├── backend/
│   ├── main.py                  # FastAPI app entry, lifespan, static mount
│   ├── config.py                # Environment variable loading + validation
│   ├── database.py              # asyncpg pool, migration runner
│   ├── models/                  # Pydantic models (request/response schemas)
│   │   ├── auth.py
│   │   ├── conversation.py
│   │   ├── workspace.py
│   │   ├── skill.py
│   │   ├── hook.py
│   │   └── message.py
│   ├── routers/                 # FastAPI route modules
│   │   ├── auth.py              # /api/auth/*
│   │   ├── conversations.py     # /api/conversations/*
│   │   ├── workspaces.py        # /api/workspaces/*
│   │   ├── skills.py            # /api/skills/*
│   │   ├── hooks.py             # /api/hooks/*
│   │   ├── files.py             # /api/files/*
│   │   ├── search.py            # /api/search/*
│   │   ├── admin.py             # /api/admin/*
│   │   └── health.py            # /api/health
│   ├── services/                # Business logic layer
│   │   ├── router_engine.py     # 3-layer routing logic
│   │   ├── model_provider.py    # Anthropic/Bedrock/Ollama abstraction
│   │   ├── skill_executor.py    # Webhook calling + response formatting
│   │   ├── context_capture.py   # Auto-capture background logic
│   │   ├── hook_engine.py       # Event dispatch + action execution
│   │   ├── artifact_manager.py  # Artifact detection, storage, versioning
│   │   ├── file_manager.py      # Upload, resize, store, asset creation
│   │   ├── briefing.py          # Daily briefing generation
│   │   ├── search.py            # Full-text search across all content
│   │   └── notifications.py     # Web Push + Pushover dispatch
│   ├── websocket/               # WebSocket handling
│   │   ├── manager.py           # Connection registry, broadcast
│   │   └── handlers.py          # Message streaming, typing indicators
│   ├── middleware/               # Request middleware
│   │   ├── auth.py              # JWT validation, user injection
│   │   ├── rate_limit.py        # Per-user rate limiting
│   │   └── audit.py             # Admin action logging
│   └── migrations/              # SQL migration files
│       ├── 001_initial_schema.sql
│       ├── 002_seed_skills.sql
│       └── 003_seed_workspaces.sql
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/          # React components
│   │   ├── pages/               # Route-level pages
│   │   ├── hooks/               # Custom React hooks
│   │   ├── services/            # API client, WebSocket client
│   │   ├── stores/              # Zustand state management
│   │   └── utils/               # Formatters, helpers
│   ├── public/
│   │   ├── manifest.json        # PWA manifest
│   │   ├── sw.js                # Service worker
│   │   └── icons/               # App icons (192, 512)
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── package.json
├── Dockerfile
├── docker-compose.yml           # For local dev (optional)
├── requirements.txt
└── patterns.json                # Default Layer 1 pattern catalog
```

### 2. Frontend Component Architecture

```
App
├── AuthGate                         # Login/register, token management
├── AppShell                         # Authenticated layout
│   ├── Sidebar                      # Desktop: left panel
│   │   ├── WorkspaceSwitcher        # Workspace list + create
│   │   ├── ConversationList         # Sorted by last activity
│   │   │   └── ConversationItem     # Title, timestamp, branch indicator
│   │   ├── DailyCostBadge           # Running daily total
│   │   └── UserMenu                 # Settings, admin, logout
│   ├── ChatArea                     # Main content
│   │   ├── ChatHeader               # Workspace name, model picker, search
│   │   ├── MessageList              # Virtualized message scroll
│   │   │   ├── UserMessage          # Text + attachments
│   │   │   ├── AssistantMessage     # Markdown + layer badge + cost
│   │   │   ├── ToolCallMessage      # Skill invocation indicator
│   │   │   └── SystemMessage        # Briefing, context capture note
│   │   ├── TypingIndicator          # Animated dots during streaming
│   │   └── InputArea                # Text input + file attach + slash autocomplete
│   │       ├── SlashAutocomplete    # Dropdown on "/" keystroke
│   │       ├── FileAttachButton     # Drag-drop + picker
│   │       ├── ModelPicker          # Auto / specific model selector
│   │       └── SendButton
│   ├── ArtifactPanel                # Right panel (desktop) / overlay (mobile)
│   │   ├── ArtifactTabs             # Multiple artifacts per conversation
│   │   ├── CodeArtifact             # Syntax highlighted, copy button
│   │   ├── HtmlArtifact             # Sandboxed iframe
│   │   ├── ChartArtifact            # Chart.js rendered
│   │   ├── MermaidArtifact          # Diagram rendered to SVG
│   │   └── ArtifactActions          # Save, download, share, version history
│   └── MobileNav                    # Bottom sheet (mobile only)
│       ├── WorkspaceTab
│       ├── ChatTab
│       └── SettingsTab
├── AdminPanel                       # Admin-only routes
│   ├── UserManagement
│   ├── SkillRegistry
│   ├── HookManager
│   ├── CostDashboard
│   └── WorkspaceAdmin
├── SearchOverlay                    # Ctrl+K global search
└── SettingsPage                     # User preferences
```

## Data Models

### New Tables (in `public` schema of the existing `finance` database)

```sql
-- ============================================================
-- AUTHENTICATION & USERS
-- ============================================================

CREATE TABLE public.bh_users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK (role IN ('admin', 'member', 'viewer')),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    settings_json   JSONB DEFAULT '{}'::jsonb  -- user preferences
);

CREATE TABLE public.bh_invite_links (
    id              SERIAL PRIMARY KEY,
    token           TEXT NOT NULL UNIQUE,
    created_by      INTEGER REFERENCES public.bh_users(id),
    role            TEXT NOT NULL DEFAULT 'member',
    expires_at      TIMESTAMPTZ NOT NULL,
    used_by         INTEGER REFERENCES public.bh_users(id),
    used_at         TIMESTAMPTZ
);

CREATE TABLE public.bh_refresh_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);
```

```sql
-- ============================================================
-- WORKSPACES
-- ============================================================

CREATE TABLE public.bh_workspaces (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    icon            TEXT,                       -- emoji or icon name
    color           TEXT,                       -- hex color for UI
    system_prompt   TEXT NOT NULL DEFAULT '',
    default_model   TEXT DEFAULT 'auto',        -- 'auto' or specific model ID
    temperature     NUMERIC(3,2) DEFAULT 0.7,
    max_context_tokens INTEGER DEFAULT 8000,
    auto_capture    BOOLEAN DEFAULT true,
    permitted_schemas TEXT[] DEFAULT '{}',      -- e.g., {'public', 'inventory'}
    settings_json   JSONB DEFAULT '{}'::jsonb,
    created_by      INTEGER REFERENCES public.bh_users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.bh_workspace_users (
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK (role IN ('owner', 'member', 'viewer')),
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE public.bh_pinned_context (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    context_type    TEXT NOT NULL CHECK (context_type IN ('static', 'dynamic')),
    title           TEXT NOT NULL,
    content         TEXT,                       -- for static: markdown content
    query           TEXT,                       -- for dynamic: SQL query
    refresh_minutes INTEGER DEFAULT 60,        -- for dynamic: refresh interval
    cached_result   TEXT,                      -- for dynamic: last query result
    cached_at       TIMESTAMPTZ,
    priority        INTEGER DEFAULT 100,       -- lower = included first
    token_estimate  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
-- ============================================================
-- CONVERSATIONS & MESSAGES
-- ============================================================

CREATE TABLE public.bh_conversations (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    title           TEXT,                       -- auto-generated or user-set
    parent_id       INTEGER REFERENCES public.bh_conversations(id),  -- for branching
    branch_point_msg INTEGER,                  -- message ID where branch diverges
    is_archived     BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bh_conversations_workspace_user
    ON public.bh_conversations(workspace_id, user_id, updated_at DESC);

CREATE TABLE public.bh_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES public.bh_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool_call', 'tool_result')),
    content         TEXT NOT NULL,
    attachments     JSONB DEFAULT '[]'::jsonb,  -- [{asset_id, filename, mime, thumbnail_url}]
    model_used      TEXT,
    routing_layer   TEXT CHECK (routing_layer IN ('L1', 'L2', 'L3')),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        NUMERIC(10,6),
    metadata        JSONB DEFAULT '{}'::jsonb,  -- skill_name, artifact_id, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bh_messages_conversation
    ON public.bh_messages(conversation_id, created_at);
CREATE INDEX idx_bh_messages_fts
    ON public.bh_messages USING gin(to_tsvector('english', content));
```

```sql
-- ============================================================
-- SKILLS & ROUTING
-- ============================================================

CREATE TABLE public.bh_skills (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,       -- e.g., 'finance-query'
    description     TEXT NOT NULL,              -- shown to router + admin UI
    webhook_url     TEXT NOT NULL,              -- full URL or relative to N8N_BASE
    http_method     TEXT NOT NULL DEFAULT 'POST',
    param_schema    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- JSON Schema for parameters
    response_hint   TEXT,                       -- 'table', 'single', 'text', 'json'
    is_active       BOOLEAN DEFAULT true,
    restricted_users INTEGER[] DEFAULT '{}',   -- empty = all users; populated = only these user IDs
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.bh_workspace_skills (
    workspace_id    INTEGER NOT NULL REFERENCES public.bh_workspaces(id) ON DELETE CASCADE,
    skill_id        INTEGER NOT NULL REFERENCES public.bh_skills(id) ON DELETE CASCADE,
    PRIMARY KEY (workspace_id, skill_id)
);

CREATE TABLE public.bh_slash_commands (
    id              SERIAL PRIMARY KEY,
    command         TEXT NOT NULL,              -- e.g., '/balance'
    description     TEXT NOT NULL,
    skill_id        INTEGER REFERENCES public.bh_skills(id),  -- null = built-in handler
    param_template  JSONB DEFAULT '{}'::jsonb,  -- maps command args to skill params
    workspace_id    INTEGER REFERENCES public.bh_workspaces(id),  -- null = global
    is_active       BOOLEAN DEFAULT true
);

CREATE TABLE public.bh_patterns (
    id              SERIAL PRIMARY KEY,
    rule            TEXT NOT NULL,              -- regex pattern
    rule_type       TEXT NOT NULL DEFAULT 'regex' CHECK (rule_type IN ('regex', 'keyword')),
    skill_id        INTEGER NOT NULL REFERENCES public.bh_skills(id),
    param_template  JSONB DEFAULT '{}'::jsonb,  -- named group → param mapping
    description     TEXT,
    priority        INTEGER DEFAULT 100,       -- lower = higher priority
    workspace_id    INTEGER REFERENCES public.bh_workspaces(id),  -- null = global
    is_active       BOOLEAN DEFAULT true
);

CREATE TABLE public.bh_model_rates (
    id              SERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,              -- 'anthropic', 'bedrock', 'ollama'
    model_id        TEXT NOT NULL UNIQUE,       -- e.g., 'claude-haiku-4-5-20251001'
    display_name    TEXT NOT NULL,
    input_cost_per_mtok  NUMERIC(10,4),        -- cost per million input tokens
    output_cost_per_mtok NUMERIC(10,4),        -- cost per million output tokens
    supports_vision BOOLEAN DEFAULT false,
    supports_tools  BOOLEAN DEFAULT false,
    max_output_tokens INTEGER DEFAULT 4096,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
-- ============================================================
-- HOOKS
-- ============================================================

CREATE TABLE public.bh_hooks (
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
    -- For call_webhook: {url, method, body_template}
    -- For call_ai: {prompt, model, display_result}
    -- For capture_context: {} (uses default logic)
    -- For notify: {title, message_template, priority}
    conditions      JSONB DEFAULT '{}'::jsonb,
    -- {keywords: [], users: [], skills: [], hours: {start, end}}
    cron_expression TEXT,                      -- for schedule events
    is_enabled      BOOLEAN DEFAULT true,
    created_by      INTEGER REFERENCES public.bh_users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.bh_hook_log (
    id              SERIAL PRIMARY KEY,
    hook_id         INTEGER NOT NULL REFERENCES public.bh_hooks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    trigger_data    JSONB,                     -- what triggered it
    action_result   JSONB,                     -- what happened
    success         BOOLEAN NOT NULL,
    error_message   TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
-- ============================================================
-- ARTIFACTS
-- ============================================================

CREATE TABLE public.bh_artifacts (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES public.bh_conversations(id) ON DELETE CASCADE,
    message_id      INTEGER NOT NULL REFERENCES public.bh_messages(id) ON DELETE CASCADE,
    artifact_type   TEXT NOT NULL CHECK (artifact_type IN (
        'code', 'html', 'mermaid', 'chart', 'markdown', 'table'
    )),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    language        TEXT,                       -- for code artifacts
    version         INTEGER NOT NULL DEFAULT 1,
    parent_id       INTEGER REFERENCES public.bh_artifacts(id),  -- for versioning
    file_path       TEXT,                      -- if saved to disk
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- AUDIT LOG
-- ============================================================

CREATE TABLE public.bh_audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES public.bh_users(id),
    action          TEXT NOT NULL,             -- 'login', 'create_user', 'modify_skill', etc.
    target_type     TEXT,                      -- 'user', 'workspace', 'skill', 'hook'
    target_id       INTEGER,
    details         JSONB DEFAULT '{}'::jsonb,
    ip_address      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bh_audit_log_user ON public.bh_audit_log(user_id, created_at DESC);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================

CREATE TABLE public.bh_notification_prefs (
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    web_push        BOOLEAN DEFAULT true,
    pushover        BOOLEAN DEFAULT false,
    quiet_start     TIME,                      -- e.g., '22:00'
    quiet_end       TIME,                      -- e.g., '07:00'
    PRIMARY KEY (user_id, event_type)
);

CREATE TABLE public.bh_push_subscriptions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    subscription    JSONB NOT NULL,            -- Web Push subscription object
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Core Service Designs

### Router Engine (services/router_engine.py)

The Router is the central intelligence of the platform. It processes every user message through a deterministic pipeline:

```python
class RouterEngine:
    """
    3-layer message routing:
    Layer 1: Slash commands + regex patterns (zero cost, <100ms)
    Layer 2: Haiku/Ollama classification (low cost, <2s)
    Layer 3: Sonnet/selected model reasoning (full cost, streaming)
    """

    async def route(self, message: str, context: RoutingContext) -> RoutingResult:
        # Layer 1: Deterministic
        if message.startswith('/'):
            result = await self._try_slash_command(message, context)
            if result:
                return RoutingResult(layer='L1', result=result)

        pattern_match = await self._try_pattern_match(message, context)
        if pattern_match:
            return RoutingResult(layer='L1', result=pattern_match)

        # Layer 2: Lightweight classification
        if not context.force_model:
            classification = await self._classify(message, context)
            if classification and classification.confidence > 0.75:
                skill_result = await self._execute_skill(
                    classification.skill_name,
                    classification.params,
                    context
                )
                # Wrap raw skill output in natural language
                formatted = await self._format_skill_response(
                    skill_result, message, context
                )
                return RoutingResult(layer='L2', result=formatted)

        # Layer 3: Full reasoning with tool use
        return await self._reason(message, context)

    async def _classify(self, message: str, context: RoutingContext):
        """Call Haiku/Ollama to classify intent. Returns skill + params + confidence."""
        skills = await self._get_workspace_skills(context)
        prompt = self._build_classification_prompt(message, skills)
        response = await self.model_provider.complete(
            model=context.workspace.classification_model or 'claude-haiku-4-5-20251001',
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256
        )
        return self._parse_classification(response)

    async def _reason(self, message: str, context: RoutingContext):
        """Full Sonnet reasoning with tool-use (streaming)."""
        tools = self._build_tool_schemas(context)
        history = await self._get_context_messages(context)
        system = self._build_system_prompt(context)

        # Stream response via WebSocket
        async for chunk in self.model_provider.stream(
            model=context.force_model or context.workspace.default_model or 'claude-sonnet-4-5',
            system=system,
            messages=history + [{"role": "user", "content": message}],
            tools=tools,
            max_tokens=4096
        ):
            yield chunk
```

#### RoutingContext (passed to every route call)

```python
@dataclass
class RoutingContext:
    user: User
    workspace: Workspace
    conversation_id: int
    force_model: Optional[str]       # if user selected a specific model
    attachments: List[Attachment]     # files attached to this message
    websocket: WebSocket             # for streaming responses
```

### Model Provider Abstraction (services/model_provider.py)

```python
class ModelProvider:
    """Unified interface to Anthropic, Bedrock, and Ollama."""

    def __init__(self, config: Config):
        self.providers: Dict[str, BaseProvider] = {}
        if config.ANTHROPIC_API_KEY:
            self.providers['anthropic'] = AnthropicProvider(config.ANTHROPIC_API_KEY)
        if config.AWS_ACCESS_KEY_ID:
            self.providers['bedrock'] = BedrockProvider(
                config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY, config.AWS_REGION
            )
        if config.OLLAMA_URL:
            self.providers['ollama'] = OllamaProvider(config.OLLAMA_URL)

    async def complete(self, model: str, messages, max_tokens, tools=None, system=None):
        """Non-streaming completion. Used by Layer 2 classification."""
        provider = self._resolve_provider(model)
        return await provider.complete(model, messages, max_tokens, tools, system)

    async def stream(self, model: str, messages, max_tokens, tools=None, system=None):
        """Streaming completion. Used by Layer 3 reasoning."""
        provider = self._resolve_provider(model)
        async for chunk in provider.stream(model, messages, max_tokens, tools, system):
            yield chunk

    async def list_models(self) -> List[ModelInfo]:
        """Discover available models from all providers."""
        models = []
        for name, provider in self.providers.items():
            models.extend(await provider.list_models())
        return models

    def _resolve_provider(self, model: str) -> BaseProvider:
        """Determine which provider handles a given model ID."""
        # Model ID prefixes or lookup table
        if model.startswith('claude') and 'anthropic' in self.providers:
            return self.providers['anthropic']
        elif model.startswith('us.') or model.startswith('amazon.'):
            return self.providers['bedrock']
        elif 'ollama' in self.providers:
            return self.providers['ollama']
        raise ModelNotAvailableError(model)


class BaseProvider(ABC):
    """Abstract base for all model providers."""

    @abstractmethod
    async def complete(self, model, messages, max_tokens, tools, system) -> CompletionResult:
        ...

    @abstractmethod
    async def stream(self, model, messages, max_tokens, tools, system) -> AsyncIterator[StreamChunk]:
        ...

    @abstractmethod
    async def list_models(self) -> List[ModelInfo]:
        ...
```

#### Provider Implementations

- **AnthropicProvider**: Uses `anthropic` Python SDK. Supports vision (image content blocks), tool use, streaming via `client.messages.stream()`.
- **BedrockProvider**: Uses `boto3` with `bedrock-runtime`. Translates Anthropic message format to Bedrock's `converse` API. Supports all Claude models on Bedrock plus any other models available.
- **OllamaProvider**: Uses HTTP calls to Ollama's `/api/chat` endpoint. Translates tool schemas to Ollama's function-calling format. Used primarily for Layer 2 classification when configured.

### Context Capture (services/context_capture.py)

```python
class ContextCapture:
    """
    Runs as a background task after each assistant response.
    Evaluates whether the exchange contains persistable information.
    """

    CAPTURE_PROMPT = """Analyze this conversation exchange. Extract any facts, preferences,
decisions, or corrections the user stated that would be useful to remember long-term.

Rules:
- Only extract EXPLICIT statements, never infer
- Format each fact as a single sentence
- Return JSON: {"facts": [{"topic": "...", "statement": "..."}]} or {"facts": []} if nothing to capture
- Topics should be lowercase slugs: "finance/accounts", "woodshop/tools", "cooking/preferences"

Exchange:
User: {user_message}
Assistant: {assistant_message}"""

    async def evaluate(self, user_msg: str, assistant_msg: str, workspace: Workspace) -> List[CapturedFact]:
        response = await self.model_provider.complete(
            model='claude-haiku-4-5-20251001',
            messages=[{"role": "user", "content": self.CAPTURE_PROMPT.format(
                user_message=user_msg, assistant_message=assistant_msg
            )}],
            max_tokens=128
        )
        facts = self._parse_facts(response)

        persisted = []
        for fact in facts:
            topic = f"{workspace.name.lower()}/{fact.topic}"
            if not await self._is_duplicate(topic, fact.statement):
                await self._persist(topic, fact.statement)
                persisted.append(fact)

        return persisted

    async def _is_duplicate(self, topic: str, statement: str) -> bool:
        """Check existing knowledge file for semantic duplicates."""
        existing = await self.file_manager.read_knowledge(topic)
        if not existing:
            return False
        # Simple substring check first (fast path)
        if statement.lower() in existing.lower():
            return True
        # Could add Haiku-based semantic dedup here if needed
        return False

    async def _persist(self, topic: str, statement: str):
        """Append fact to /knowledge/<topic>.md"""
        date = datetime.now().strftime('%Y-%m-%d')
        line = f"- [{date}] {statement}"
        await self.file_manager.append_knowledge(topic, line)
```

### Hook Engine (services/hook_engine.py)

```python
class HookEngine:
    """
    Event-driven automation system. Hooks are workspace-scoped
    and fire on defined events with optional conditions.
    """

    def __init__(self, db, model_provider, skill_executor, notifications):
        self.db = db
        self.model_provider = model_provider
        self.skill_executor = skill_executor
        self.notifications = notifications
        self._scheduler = AsyncIOScheduler()  # APScheduler for cron hooks

    async def startup(self):
        """Load all schedule-type hooks and register cron jobs."""
        hooks = await self.db.fetch(
            "SELECT * FROM bh_hooks WHERE event_type = 'schedule' AND is_enabled = true"
        )
        for hook in hooks:
            self._scheduler.add_job(
                self._execute_hook, 'cron',
                **self._parse_cron(hook['cron_expression']),
                args=[hook],
                id=f"hook_{hook['id']}"
            )
        self._scheduler.start()

    async def dispatch(self, event_type: str, context: HookEventContext):
        """Called by the application when an event occurs."""
        hooks = await self.db.fetch("""
            SELECT * FROM bh_hooks
            WHERE workspace_id = $1 AND event_type = $2 AND is_enabled = true
        """, context.workspace_id, event_type)

        for hook in hooks:
            if self._check_conditions(hook, context):
                asyncio.create_task(self._execute_hook(hook, context))

    async def _execute_hook(self, hook: dict, context: HookEventContext = None):
        """Execute a hook action and log the result."""
        try:
            match hook['action_type']:
                case 'call_webhook':
                    result = await self.skill_executor.call_url(
                        hook['action_config']['url'],
                        hook['action_config'].get('body_template', {}),
                        context
                    )
                case 'call_ai':
                    result = await self.model_provider.complete(
                        model=hook['action_config'].get('model', 'claude-haiku-4-5-20251001'),
                        messages=[{"role": "user", "content": hook['action_config']['prompt']}],
                        max_tokens=512
                    )
                case 'capture_context':
                    result = await self.context_capture.evaluate(
                        context.user_message, context.assistant_message, context.workspace
                    )
                case 'notify':
                    result = await self.notifications.send(
                        user_id=context.user_id,
                        title=hook['action_config']['title'],
                        message=hook['action_config']['message_template']
                    )

            await self._log_execution(hook['id'], event_type, context, result, success=True)
        except Exception as e:
            await self._log_execution(hook['id'], event_type, context, None, success=False, error=str(e))
```

### Skill Executor (services/skill_executor.py)

```python
class SkillExecutor:
    """
    Calls n8n webhooks and formats responses.
    Enforces workspace + user permission checks before execution.
    """

    async def execute(self, skill_name: str, params: dict, context: RoutingContext) -> SkillResult:
        skill = await self._get_skill(skill_name)

        # Permission check
        if not self._user_permitted(skill, context.user):
            raise PermissionDeniedError(f"User not permitted to use skill: {skill_name}")
        if not self._workspace_permitted(skill, context.workspace):
            raise PermissionDeniedError(f"Skill not available in this workspace")

        # Build request
        url = self._resolve_url(skill.webhook_url)
        body = self._build_body(skill.param_schema, params)

        # Execute with timeouts
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=30.0)) as client:
            response = await client.request(
                method=skill.http_method,
                url=url,
                json=body
            )

        if response.status_code >= 400:
            raise SkillExecutionError(skill_name, response.status_code)

        return SkillResult(
            skill_name=skill_name,
            raw_data=response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            response_hint=skill.response_hint
        )

    async def format_response(self, result: SkillResult) -> str:
        """Convert raw skill output to human-readable markdown."""
        data = result.raw_data

        if isinstance(data, list) and len(data) > 0:
            if len(data[0].keys()) > 3:
                return self._render_table(data)
            else:
                return self._render_numbered_list(data)
        elif isinstance(data, dict):
            if 'error' in data:
                return f"⚠️ {data.get('message', 'Something went wrong. Try again?')}"
            return self._render_key_value(data)
        else:
            return str(data)
```

### WebSocket Manager (websocket/manager.py)

```python
class WebSocketManager:
    """
    Manages active WebSocket connections for real-time streaming.
    Each authenticated user can have multiple connections (phone + desktop).
    """

    def __init__(self):
        self.connections: Dict[int, List[WebSocket]] = {}  # user_id → connections

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.connections.setdefault(user_id, []).append(websocket)

    async def disconnect(self, websocket: WebSocket, user_id: int):
        self.connections[user_id].remove(websocket)

    async def stream_to_user(self, user_id: int, event: StreamEvent):
        """Send a streaming event to all of a user's connections."""
        for ws in self.connections.get(user_id, []):
            try:
                await ws.send_json(event.dict())
            except WebSocketDisconnect:
                await self.disconnect(ws, user_id)

    async def send_typing(self, user_id: int, conversation_id: int):
        await self.stream_to_user(user_id, StreamEvent(
            type='typing', conversation_id=conversation_id
        ))

    async def send_token(self, user_id: int, conversation_id: int, token: str):
        await self.stream_to_user(user_id, StreamEvent(
            type='token', conversation_id=conversation_id, data=token
        ))

    async def send_skill_status(self, user_id: int, conversation_id: int, skill_name: str, status: str):
        await self.stream_to_user(user_id, StreamEvent(
            type='skill_status', conversation_id=conversation_id,
            data={'skill': skill_name, 'status': status}
        ))

    async def send_complete(self, user_id: int, conversation_id: int, message: dict):
        await self.stream_to_user(user_id, StreamEvent(
            type='complete', conversation_id=conversation_id, data=message
        ))
```

#### WebSocket Protocol (client ↔ server)

```json
// Client → Server: Send message
{"type": "message", "conversation_id": 123, "content": "what's my balance?", "model": "auto", "attachments": []}

// Server → Client: Typing indicator
{"type": "typing", "conversation_id": 123}

// Server → Client: Streaming token
{"type": "token", "conversation_id": 123, "data": "Your"}

// Server → Client: Skill being called
{"type": "skill_status", "conversation_id": 123, "data": {"skill": "balances", "status": "calling"}}

// Server → Client: Complete message (final, includes metadata)
{"type": "complete", "conversation_id": 123, "data": {"id": 456, "content": "...", "model_used": "claude-haiku-4-5-20251001", "routing_layer": "L1", "cost_usd": 0.0, "artifacts": []}}

// Server → Client: Context captured
{"type": "context_captured", "conversation_id": 123, "data": {"facts": ["Ally is the emergency fund"]}}

// Server → Client: Error
{"type": "error", "conversation_id": 123, "data": {"message": "Something went wrong. Try again?"}}
```

## API Design

### Authentication Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/auth/login | Email + password → JWT access + refresh tokens |
| POST | /api/auth/refresh | Refresh token → new access token |
| POST | /api/auth/logout | Revoke refresh token |
| POST | /api/auth/invite | (Admin) Generate invite link |
| POST | /api/auth/register | Use invite link to create account |

### Conversation Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/conversations?workspace_id=X | List conversations for workspace |
| POST | /api/conversations | Create new conversation |
| GET | /api/conversations/:id | Get conversation with recent messages |
| PATCH | /api/conversations/:id | Rename, archive |
| DELETE | /api/conversations/:id | (Admin) Permanent delete |
| POST | /api/conversations/:id/branch/:msg_id | Branch from message |
| POST | /api/conversations/:id/share/:user_id | Share with user |
| GET | /api/conversations/:id/messages?before=X&limit=50 | Paginated history |

### Message Endpoint (REST fallback — primary path is WebSocket)

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/messages | Send message (non-streaming fallback) |

### Workspace Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/workspaces | List user's workspaces |
| POST | /api/workspaces | Create workspace |
| GET | /api/workspaces/:id | Get workspace details |
| PATCH | /api/workspaces/:id | Update workspace settings |
| DELETE | /api/workspaces/:id | Delete workspace (admin) |
| GET | /api/workspaces/:id/schemas | List available DB schemas |
| POST | /api/workspaces/:id/users | Add user to workspace |
| DELETE | /api/workspaces/:id/users/:uid | Remove user from workspace |
| GET | /api/workspaces/:id/pinned-context | List pinned context |
| POST | /api/workspaces/:id/pinned-context | Add pinned context |
| PATCH | /api/workspaces/:id/pinned-context/:id | Update pinned context |
| DELETE | /api/workspaces/:id/pinned-context/:id | Remove pinned context |

### Skill Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/skills | List all skills (admin: all; user: permitted) |
| POST | /api/skills | Create skill (admin) |
| PATCH | /api/skills/:id | Update skill (admin) |
| DELETE | /api/skills/:id | Delete skill (admin) |
| POST | /api/skills/:id/test | Test skill with sample input (admin) |

### Hook Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/hooks?workspace_id=X | List hooks for workspace |
| POST | /api/hooks | Create hook |
| PATCH | /api/hooks/:id | Update hook |
| DELETE | /api/hooks/:id | Delete hook |
| POST | /api/hooks/:id/test | Manually trigger hook |
| GET | /api/hooks/:id/log | Get execution log |

### File Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/files/upload | Upload file(s) to chat |
| GET | /api/files/:asset_id | Serve file (with auth check) |
| GET | /api/files/:asset_id/thumbnail | Serve resized thumbnail |

### Search Endpoint

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/search?q=X&workspace=Y&type=Z | Global search |

### Admin Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/admin/users | List all users |
| PATCH | /api/admin/users/:id | Update user role/status |
| GET | /api/admin/cost | Cost dashboard data |
| GET | /api/admin/models | List models + rates |
| PATCH | /api/admin/models/:id | Update model rates |
| GET | /api/admin/audit | Audit log |

### Utility Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Health check |
| GET | /api/models | Available models for current user |
| GET | /api/slash-commands?workspace_id=X | Available commands |

## Message Flow (End-to-End)

```
User types "what did I spend on groceries this week?" in Finance workspace
    │
    ▼
[Frontend] Optimistic UI: show user message, display typing indicator
    │
    ▼
[WebSocket] {"type": "message", "conversation_id": 42, "content": "...", "model": "auto"}
    │
    ▼
[Auth Middleware] Validate JWT, inject user context
    │
    ▼
[Router Engine - Layer 1] Check slash commands → no match
                          Check patterns → no match
    │
    ▼
[Router Engine - Layer 2] Call Haiku classifier:
    Prompt: "Classify this message. Available skills: [finance-query: NL→SQL for financial data, ...]"
    Response: {"skill": "finance-query", "confidence": 0.92, "params": {"question": "what did I spend on groceries this week?"}}
    │
    ▼
[Permission Check] finance-query allowed in Finance workspace? ✓
                   User michael allowed to use finance-query? ✓
    │
    ▼
[Skill Executor] POST http://n8n:5678/webhook/finance-query
    Body: {"question": "what did I spend on groceries this week?"}
    Response: {"sql_generated": "...", "results": [...], "row_count": 12}
    │
    ▼
[Response Formatter] Haiku call to wrap raw data in natural language:
    "You spent $247.83 on groceries this week across 12 transactions. Here's the breakdown:
     | Date | Store | Amount |
     | ... | ... | ... |"
    │
    ▼
[Cost Logger] Log Layer 2 classification (128 in, 45 out, $0.0001)
              Log formatting call (890 in, 200 out, $0.0004)
    │
    ▼
[Context Capture] Background: "User asked about grocery spending. No new facts to capture."
    │
    ▼
[Hook Engine] Dispatch 'message_received' event → no matching hooks
    │
    ▼
[WebSocket] {"type": "complete", "data": {"content": "...", "routing_layer": "L2", "cost_usd": 0.0005, "model_used": "claude-haiku-4-5-20251001"}}
    │
    ▼
[Frontend] Render formatted response with L2 badge and $0.0005 cost indicator
```

## Layer 3 Tool-Use Flow (Sonnet with Skills)

When a message requires reasoning + skill calls:

```
User: "Compare my grocery spending this month vs last month and tell me if I'm on track for my budget"
    │
    ▼
[Layer 2] Confidence: 0.55 (needs reasoning, not just a lookup) → escalate to Layer 3
    │
    ▼
[Layer 3] Send to Sonnet with tools:
    System: {workspace system prompt + pinned context (budget amounts, account info)}
    Tools: [{name: "finance-query", description: "...", input_schema: {...}}, ...]
    │
    ▼
[Sonnet Response - tool_use]:
    "I'll look up your spending for both periods."
    tool_call: finance-query({"question": "total grocery spending current month"})
    │
    ▼
[WebSocket] {"type": "token", "data": "I'll look up..."} (streaming text)
[WebSocket] {"type": "skill_status", "data": {"skill": "finance-query", "status": "calling"}}
    │
    ▼
[Skill Executor] → n8n → result: {"results": [{"total": -312.45}]}
    │
    ▼
[Feed result back to Sonnet as tool_result]
    │
    ▼
[Sonnet Response - tool_use]:
    tool_call: finance-query({"question": "total grocery spending last month"})
    │
    ▼
[Skill Executor] → n8n → result: {"results": [{"total": -487.22}]}
    │
    ▼
[Feed result back to Sonnet]
    │
    ▼
[Sonnet Response - text]:
    "Here's your grocery spending comparison:
     - This month (so far): $312.45
     - Last month (full): $487.22
     - Daily average this month: $12.02/day
     - Daily average last month: $15.72/day

     You're actually spending less per day this month! At your current pace,
     you'd end the month around $360 — well under last month. If your grocery
     budget is $450/month, you're solidly on track. 🎯"
    │
    ▼
[WebSocket] Streaming tokens as they arrive
[WebSocket] {"type": "complete", "data": {..., "routing_layer": "L3", "cost_usd": 0.0089}}
```

## Frontend State Management

Using **Zustand** for lightweight, performant state management:

```typescript
// stores/auth.ts
interface AuthStore {
  user: User | null;
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshToken: () => Promise<void>;
}

// stores/workspace.ts
interface WorkspaceStore {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  setActive: (id: number) => void;
  fetchWorkspaces: () => Promise<void>;
}

// stores/conversation.ts
interface ConversationStore {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  messages: Message[];
  isStreaming: boolean;
  streamingContent: string;
  setActive: (id: number) => void;
  sendMessage: (content: string, attachments?: File[]) => void;
  loadMore: () => Promise<void>;
  branch: (messageId: number) => Promise<void>;
}

// stores/ui.ts
interface UIStore {
  theme: 'dark' | 'light';
  sidebarOpen: boolean;
  artifactPanelOpen: boolean;
  activeArtifact: Artifact | null;
  searchOpen: boolean;
  modelPickerSelection: string; // 'auto' or model ID
}
```

### Key Frontend Libraries

| Library | Purpose | Why |
|---------|---------|-----|
| React 18 | UI framework | Component model, hooks, concurrent features |
| Vite | Build tool | Fast HMR, optimized production builds |
| Zustand | State management | Minimal boilerplate, no providers needed |
| TailwindCSS | Styling | Utility-first, responsive, dark mode built-in |
| react-markdown + rehype | Markdown rendering | Full GFM support, syntax highlighting |
| react-syntax-highlighter | Code blocks | Language-aware highlighting in artifacts |
| mermaid | Diagrams | Render Mermaid syntax to SVG |
| chart.js + react-chartjs-2 | Charts | Render data visualizations in artifacts |
| react-virtuoso | Message list | Virtualized scrolling for long conversations |
| workbox | Service worker | PWA caching, offline support |
| lucide-react | Icons | Clean, consistent icon set |

## Artifact Detection Logic

The backend detects artifact-worthy content in AI responses using pattern matching:

```python
class ArtifactDetector:
    """Identifies content in AI responses that should render as artifacts."""

    RULES = [
        # Code blocks over 15 lines
        ArtifactRule(
            pattern=r'```(\w+)?\n(.*?)```',
            condition=lambda match: match.group(2).count('\n') > 15,
            artifact_type='code',
            extract_language=lambda match: match.group(1) or 'text'
        ),
        # HTML documents (contains <html> or <!DOCTYPE or full <div> structures)
        ArtifactRule(
            pattern=r'```html?\n(.*?)```',
            condition=lambda match: '<html' in match.group(1).lower() or len(match.group(1)) > 500,
            artifact_type='html'
        ),
        # Mermaid diagrams
        ArtifactRule(
            pattern=r'```mermaid\n(.*?)```',
            condition=lambda _: True,
            artifact_type='mermaid'
        ),
        # Data tables over 10 rows
        ArtifactRule(
            pattern=r'(\|.*\|.*\n){10,}',
            condition=lambda _: True,
            artifact_type='table'
        ),
    ]

    def detect(self, content: str) -> List[DetectedArtifact]:
        artifacts = []
        for rule in self.RULES:
            for match in re.finditer(rule.pattern, content, re.DOTALL):
                if rule.condition(match):
                    artifacts.append(DetectedArtifact(
                        type=rule.artifact_type,
                        content=match.group(1) or match.group(0),
                        language=rule.extract_language(match) if rule.extract_language else None,
                        span=(match.start(), match.end())
                    ))
        return artifacts
```

When artifacts are detected, the response is split: the artifact content is stored separately and the chat message contains a reference marker that the frontend renders as an "Open in panel" button.

## Security Design

### Authentication Flow

```
1. User submits email + password to POST /api/auth/login
2. Server verifies bcrypt hash
3. Server generates:
   - Access token (JWT, 1hr expiry, contains: user_id, role, email)
   - Refresh token (opaque, 30-day expiry, stored hashed in bh_refresh_tokens)
4. Client stores access token in memory, refresh token in httpOnly cookie
5. All API requests include Authorization: Bearer <access_token>
6. WebSocket auth: access token sent as first message after connection
7. When access token expires, client calls POST /api/auth/refresh with cookie
8. Server validates refresh token hash, issues new access + refresh pair
9. Old refresh token is revoked (rotation)
```

### Data Isolation Enforcement

```python
class SchemaGuard:
    """Ensures queries only access permitted schemas."""

    async def validate_query(self, sql: str, permitted_schemas: List[str]) -> bool:
        """
        Parse SQL and verify all referenced tables are in permitted schemas.
        Used when the finance-query skill returns generated SQL.
        """
        # Extract table references from SQL
        tables = self._extract_table_refs(sql)
        for table in tables:
            schema = table.split('.')[0] if '.' in table else 'public'
            if schema not in permitted_schemas:
                raise SchemaViolationError(
                    f"Query references schema '{schema}' which is not permitted in this workspace"
                )
        return True

    async def get_permitted_connection(self, workspace: Workspace):
        """
        Returns a DB connection with search_path restricted to permitted schemas.
        Prevents accidental cross-schema access.
        """
        conn = await self.pool.acquire()
        schemas = ','.join(workspace.permitted_schemas)
        await conn.execute(f"SET search_path TO {schemas}")
        return conn
```

### Rate Limiting

```python
class RateLimiter:
    """Token bucket rate limiter using Redis-like in-memory store."""

    def __init__(self):
        self.buckets: Dict[int, TokenBucket] = {}

    async def check(self, user_id: int, action: str) -> bool:
        limits = {
            'message': (30, 60),      # 30 messages per 60 seconds
            'api_call': (100, 3600),   # 100 API calls per hour
            'file_upload': (20, 3600), # 20 uploads per hour
        }
        max_tokens, window = limits[action]
        bucket = self.buckets.setdefault(user_id, TokenBucket(max_tokens, window))
        return bucket.consume()
```

## Deployment Architecture

### Dockerfile (multi-stage build)

```dockerfile
# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + compiled frontend
FROM python:3.12-slim
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy compiled frontend
COPY --from=frontend-build /app/frontend/dist ./static/

# Copy default configs
COPY patterns.json ./patterns.json

EXPOSE 5003
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5003", "--workers", "1"]
```

### Docker Run Command

```bash
docker run -d \
  --name bowershub-ai \
  --restart unless-stopped \
  --network ai-services_ai-network \
  -p 5003:5003 \
  -v /home/michael/files:/files \
  -v /home/michael/knowledge:/knowledge \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e AWS_ACCESS_KEY_ID=AKIA... \
  -e AWS_SECRET_ACCESS_KEY=... \
  -e AWS_REGION=us-east-1 \
  -e OLLAMA_URL=http://ollama:11434 \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=finance \
  -e DB_USER=michael \
  -e DB_PASSWORD=... \
  -e N8N_BASE=http://n8n:5678 \
  -e JWT_SECRET=... \
  -e FILES_ROOT=/files \
  -e KNOWLEDGE_ROOT=/knowledge \
  -e PUSHOVER_USER_KEY=... \
  -e PUSHOVER_API_TOKEN=... \
  -e VAPID_PRIVATE_KEY=... \
  -e VAPID_PUBLIC_KEY=... \
  bowershub-ai
```

### Deploy Script (same pattern as db-admin)

```bash
#!/bin/bash
set -e
ssh michael@100.106.180.101 "rm -rf ~/bowershub-ai"
scp -r /home/michael/KiroProject/bowershub-ai michael@100.106.180.101:~/bowershub-ai
ssh michael@100.106.180.101 "
  docker stop bowershub-ai 2>/dev/null || true
  docker rm bowershub-ai 2>/dev/null || true
  docker build --no-cache -t bowershub-ai ~/bowershub-ai
  docker run -d --name bowershub-ai --restart unless-stopped \
    --network ai-services_ai-network -p 5003:5003 \
    -v /home/michael/files:/files \
    -v /home/michael/knowledge:/knowledge \
    -e ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY \
    -e DB_HOST=postgres -e DB_PORT=5432 -e DB_NAME=finance \
    -e DB_USER=michael -e DB_PASSWORD=\$DB_PASSWORD \
    -e N8N_BASE=http://n8n:5678 \
    -e JWT_SECRET=\$JWT_SECRET \
    -e FILES_ROOT=/files -e KNOWLEDGE_ROOT=/knowledge \
    bowershub-ai
"
```

## Default Pattern Catalog (patterns.json)

```json
[
  {
    "id": "balance",
    "rule": "(?i)^(what('s| is) my |show |get )?(account )?balance(s)?",
    "rule_type": "regex",
    "skill_name": "balances",
    "param_template": {},
    "description": "Check account balances",
    "priority": 10
  },
  {
    "id": "weather",
    "rule": "(?i)^(what('s| is) the |how('s| is) the )?weather",
    "rule_type": "regex",
    "skill_name": "weather",
    "param_template": {},
    "description": "Get current weather",
    "priority": 10
  },
  {
    "id": "recall",
    "rule": "(?i)^(what do (you|I) know about |recall |remember .* about )(.+)",
    "rule_type": "regex",
    "skill_name": "recall",
    "param_template": {"query": "$3"},
    "description": "Search knowledge base",
    "priority": 20
  },
  {
    "id": "inbox_files",
    "rule": "(?i)^(what('s| is) in (my |the )?inbox|list (inbox )?files|show inbox)",
    "rule_type": "regex",
    "skill_name": "list-files",
    "param_template": {"path": "inbox"},
    "description": "List files in inbox",
    "priority": 10
  },
  {
    "id": "spending_summary",
    "rule": "(?i)^(how much (have I|did I) spen[dt]|spending (summary|breakdown|this month))",
    "rule_type": "regex",
    "skill_name": "spending-summary",
    "param_template": {},
    "description": "Monthly spending summary",
    "priority": 15
  }
]
```

## Default Seed Data

### Pre-registered Skills

| Skill Name | Webhook URL | Response Hint | Restricted Users |
|------------|-------------|---------------|------------------|
| finance-query | /webhook/finance-query | table | [michael] |
| balances | /webhook/balances | table | [michael] |
| transactions | /webhook/transactions | table | [michael] |
| filter-transactions | /webhook/filter | table | [michael] |
| spending-summary | /webhook/transactions | table | [michael] |
| override-category | /webhook/update-category | single | [michael] |
| smart-capture-extract | /webhook/smart-capture/extract | json | [] |
| smart-capture-commit | /webhook/smart-capture/commit | single | [] |
| inventory-admin | /webhook/inventory-admin | single | [michael] |
| remember | /webhook/remember | text | [] |
| recall | /webhook/recall | text | [] |
| send-email | /webhook/send-email | single | [michael] |
| process-asset | /webhook/process-asset | json | [] |
| list-files | (built-in via filewriter) | table | [] |
| weather | (built-in via wttr.in) | text | [] |

### Pre-configured Workspaces

| Workspace | Users | Permitted Schemas | Skills |
|-----------|-------|-------------------|--------|
| General | all | public | recall, remember, weather, send-email, list-files |
| Finance | michael | public, files | finance-query, balances, transactions, filter, spending-summary, override-category, recall, remember |
| Woodshop | michael | inventory, files | smart-capture-*, inventory-admin, recall, remember, list-files, process-asset |
| Cooking | michael, manon | cook, files | smart-capture-*, recall, remember, list-files |
| House | michael, manon | house, files | smart-capture-*, recall, remember, list-files |

### Default Slash Commands

| Command | Skill | Workspace | Description |
|---------|-------|-----------|-------------|
| /balance | balances | Finance | Show all account balances |
| /spend | spending-summary | Finance | MTD spending breakdown |
| /weather | weather | (global) | Current weather |
| /recall | recall | (global) | Search knowledge base |
| /files | list-files | (global) | List inbox files |
| /cost | (built-in) | (global) | Today's AI spend |
| /help | (built-in) | (global) | List available commands |
| /new | (built-in) | (global) | Start new conversation |

## PWA Configuration

### manifest.json

```json
{
  "name": "BowersHub AI",
  "short_name": "BowersHub",
  "description": "Personal AI Assistant",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1a1a2e",
  "theme_color": "#16213e",
  "orientation": "portrait-primary",
  "icons": [
    {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
    {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
  ]
}
```

### Service Worker Strategy

- **App shell**: Cache-first (HTML, CSS, JS, icons) — instant load even offline
- **API calls**: Network-first with stale-while-revalidate fallback for conversation list
- **WebSocket**: No caching — real-time only
- **File uploads**: Network-only
- **Offline mode**: Show cached conversations read-only, queue messages for send when reconnected

## Migration Strategy

### From AnythingLLM

1. Deploy BowersHub AI alongside AnythingLLM (both running simultaneously)
2. Create user accounts (Michael, Manon)
3. Configure workspaces with matching system prompts
4. Verify all skills work through the new platform
5. Run both for 1 week to validate cost savings and UX
6. Once satisfied, stop AnythingLLM container (don't delete — keep as fallback)
7. Update dashboard links to point to port 5003

### Database Migrations

All new tables use the `bh_` prefix to avoid conflicts with existing tables. The migration runner checks a `bh_migrations` tracking table:

```sql
CREATE TABLE IF NOT EXISTS public.bh_migrations (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Migrations are applied in filename order on startup. If a migration fails, the app exits with a clear error message.

## Cost Estimation

### Per-message cost breakdown (typical usage)

| Scenario | Layer | Model | Input Tokens | Output Tokens | Cost |
|----------|-------|-------|-------------|---------------|------|
| /balance (slash command) | L1 | none | 0 | 0 | $0.0000 |
| "what's my balance?" (pattern match) | L1 | none | 0 | 0 | $0.0000 |
| "how much did I spend on gas?" | L2 | Haiku (classify) + Haiku (format) | ~800 | ~300 | $0.0003 |
| "explain my spending trends" | L3 | Haiku (classify) + Sonnet (reason) | ~3000 | ~800 | $0.0180 |
| Context capture (per message) | bg | Haiku | ~400 | ~50 | $0.0001 |
| Conversation auto-title | bg | Haiku | ~200 | ~20 | $0.0001 |

### Projected daily cost (based on current usage patterns)

Assuming ~30 messages/day (Michael's typical):
- 10 messages hit L1 (slash/pattern): $0.00
- 12 messages hit L2 (skill lookups): $0.0036
- 8 messages hit L3 (reasoning): $0.144
- 30 context captures: $0.003
- 5 new conversations titled: $0.0005

**Total: ~$0.15/day** (vs current ~$7/day with AnythingLLM + Sonnet agent loop)

### Cost savings breakdown

| Component | AnythingLLM (current) | BowersHub AI (projected) |
|-----------|----------------------|--------------------------|
| Agent routing (every message) | $5-6/day (Sonnet) | $0.00 (deterministic + Haiku) |
| Actual reasoning | $1-2/day (Sonnet) | $0.14/day (Sonnet, only when needed) |
| Context capture | N/A | $0.003/day (Haiku) |
| n8n workflows | $0.29/day | $0.29/day (unchanged) |
| **Total** | **~$7/day** | **~$0.45/day** |

## Technology Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend framework | FastAPI | Async, WebSocket support, Pydantic validation, matches existing stack |
| Frontend framework | React 18 + Vite | Component model, ecosystem, PWA support, future React Native option |
| State management | Zustand | Minimal boilerplate, no context providers, good TypeScript support |
| Styling | TailwindCSS | Utility-first, responsive, dark mode, no CSS-in-JS runtime cost |
| Database | Existing Postgres | No new infrastructure, cross-schema queries, full-text search built-in |
| Real-time | WebSocket (native) | Streaming tokens, typing indicators, no polling overhead |
| Auth | JWT + refresh tokens | Stateless verification, mobile-friendly, standard pattern |
| Search | Postgres tsvector | Zero additional infrastructure, good enough for personal scale |
| PWA | Workbox | Google's service worker toolkit, reliable caching strategies |
| Deployment | Single Docker container | Matches existing pattern, simple, one build artifact |
| AI SDK | anthropic (Python) | Official SDK, streaming support, tool use |
| AWS SDK | boto3 | Standard, Bedrock converse API |
| HTTP client | httpx | Async, timeout support, connection pooling |
| Scheduler | APScheduler | Cron hooks, lightweight, in-process |
| Markdown | react-markdown + rehype | Full GFM, plugin ecosystem, syntax highlighting |

## Requirement Traceability

| Requirement | Design Components |
|-------------|-------------------|
| R1: Auth | bh_users, bh_invite_links, bh_refresh_tokens, Auth middleware, /api/auth/* |
| R2: Workspaces | bh_workspaces, bh_workspace_users, bh_workspace_skills, /api/workspaces/* |
| R3: Routing | RouterEngine (Layer 1/2/3), bh_patterns, classification prompt |
| R4: Model Providers | ModelProvider abstraction, bh_model_rates, AnthropicProvider/BedrockProvider/OllamaProvider |
| R5: Conversations | bh_conversations, bh_messages, /api/conversations/*, branching via parent_id |
| R6: Context Capture | ContextCapture service, hook integration, /knowledge/* file writes |
| R7: Skills | bh_skills, bh_workspace_skills, SkillExecutor, /api/skills/* |
| R8: Slash Commands | bh_slash_commands, SlashAutocomplete component, Layer 1 routing |
| R9: Artifacts | bh_artifacts, ArtifactDetector, ArtifactPanel component |
| R10: File Attachments | FileManager, /api/files/*, vision content blocks, Process Asset integration |
| R11: Hooks | bh_hooks, bh_hook_log, HookEngine, APScheduler, /api/hooks/* |
| R12: Cost Tracking | bh_messages.cost_usd, api_usage_log, CostBadge component, /cost command |
| R13: React PWA | Frontend architecture, manifest.json, service worker, Vite build |
| R14: FastAPI Backend | main.py, Dockerfile, migrations, health endpoint |
| R15: Pinned Context | bh_pinned_context, system prompt assembly, dynamic query refresh |
| R16: Daily Briefing | Scheduled hook, BriefingService, pinned message display |
| R17: Branching | bh_conversations.parent_id/branch_point_msg, branch UI |
| R18: Search | Postgres tsvector index, /api/search, SearchOverlay component |
| R19: Notifications | bh_notification_prefs, bh_push_subscriptions, Web Push + Pushover |
| R20: Security | SchemaGuard, RateLimiter, audit log, input validation, JWT |

## Error Handling

### Backend Error Strategy

| Error Type | Handling | User Impact |
|------------|----------|-------------|
| Model provider timeout (Layer 2) | Escalate to Layer 3 | Invisible — slightly slower response |
| Model provider timeout (Layer 3) | Return friendly error, log details | "I couldn't complete that request. Try again?" |
| Skill webhook failure (4xx/5xx) | Return error with skill name, offer retry | "The finance query skill had an issue. Try again?" |
| Skill webhook timeout (30s) | Cancel request, return timeout error | "That took too long. The skill might be overloaded." |
| Database connection lost | Retry 3x with backoff, then degrade | "Having trouble saving. Your message is preserved." |
| WebSocket disconnect | Client auto-reconnects with exponential backoff | Brief "Reconnecting..." indicator |
| Context capture failure | Log silently, don't affect user flow | No visible impact |
| Hook execution failure | Log to bh_hook_log, notify admin if configured | No visible impact (unless notify hook) |
| File upload too large | Reject with clear size limit message | "File too large. Maximum is 10MB." |
| Rate limit exceeded | Return 429 with retry-after header | "You're sending messages too quickly. Wait a moment." |
| Invalid JWT | Return 401, client triggers refresh flow | Invisible if refresh succeeds; login redirect if not |
| Schema violation | Block query, log attempt, return generic error | "I can't access that data in this workspace." |

### Frontend Error Boundaries

- **Global error boundary**: Catches React render errors, shows "Something went wrong" with reload button
- **WebSocket error handler**: Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
- **API error interceptor**: Catches 401 → refresh token flow; 403 → redirect to workspace list; 5xx → toast notification
- **Optimistic UI rollback**: If message send fails, mark the message as "failed" with a retry button (content preserved)

## Testing Strategy

### Backend Tests

| Layer | Tool | Coverage Target |
|-------|------|-----------------|
| Unit tests | pytest + pytest-asyncio | Router logic, permission checks, pattern matching, cost calculation |
| Integration tests | pytest + httpx (TestClient) | API endpoints, auth flow, WebSocket messages |
| Database tests | pytest + asyncpg (test DB) | Migrations, queries, data isolation |

### Frontend Tests

| Layer | Tool | Coverage Target |
|-------|------|-----------------|
| Component tests | Vitest + React Testing Library | Message rendering, slash autocomplete, artifact panel |
| Integration tests | Vitest + MSW (mock service worker) | Auth flow, conversation CRUD, WebSocket streaming |
| E2E tests (future) | Playwright | Critical paths: login → send message → receive response |

### Key Test Scenarios

1. **Routing correctness**: Verify slash commands hit L1, skill lookups hit L2, reasoning hits L3
2. **Permission isolation**: User B cannot access User A's finance workspace or skills
3. **Schema guard**: Queries in Cooking workspace cannot reference `public.transactions`
4. **Cost tracking accuracy**: Verify logged costs match actual API usage
5. **WebSocket streaming**: Tokens arrive in order, complete message matches final content
6. **Context capture**: Facts are extracted, deduplicated, and persisted correctly
7. **Hook execution**: Events trigger correct hooks with correct conditions
8. **Offline PWA**: App loads from cache, shows read-only conversations, queues messages

## Correctness Properties

### Property 1: Message Ordering
Messages within a conversation are always displayed in chronological order (by created_at). The frontend uses optimistic IDs until server confirmation.

**Validates: Requirements 5.1, 13.6**

### Property 2: Cost Consistency
The sum of all message costs in a conversation equals the conversation's total cost. The daily total in the UI matches the sum of all messages that day.

**Validates: Requirements 12.1, 12.2, 12.3**

### Property 3: Permission Invariant
A user can never see, query, or invoke resources outside their assigned workspaces and permitted skills. This is enforced at the query layer, not just the UI.

**Validates: Requirements 1.4, 2.2, 7.4, 20.1, 20.2**

### Property 4: Context Window Budget
The total tokens sent to any model never exceeds: pinned_context_budget + max_context_tokens + current_message. Overflow is handled by truncating oldest context messages.

**Validates: Requirements 5.5, 15.3, 15.6**

### Property 5: Artifact Versioning
Each artifact version references its parent. The chain is never broken — deleting a version removes it from display but preserves the chain for other versions.

**Validates: Requirements 9.4**

### Property 6: Hook Idempotency
Schedule hooks that fire while a previous execution is still running are skipped (no double-execution). Event hooks are fire-and-forget (no retry on failure).

**Validates: Requirements 11.1, 11.6**

### Property 7: Refresh Token Rotation
Each refresh token can only be used once. Using a revoked token invalidates all tokens for that user (security: detects token theft).

**Validates: Requirements 1.2, 1.6, 1.7**

### Property 8: Data Isolation Guarantee
The `SET search_path` approach ensures that even if a skill generates SQL referencing an unqualified table name, it resolves only within permitted schemas.

**Validates: Requirements 20.1, 2.2**
