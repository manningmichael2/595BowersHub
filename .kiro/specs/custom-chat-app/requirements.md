# Requirements Document

## Introduction

BowersHub AI is a self-hosted personal AI assistant platform that serves as the primary interface to Michael's private data management ecosystem. It replaces AnythingLLM with a purpose-built, multi-user application featuring intelligent routing, workspace-scoped permissions, automated context capture, and a polished conversational UI comparable to Claude or Gemini — while maintaining cost discipline through tiered model selection and deterministic workflow routing. The platform is built as a React PWA served by a FastAPI backend, deployable as a single Docker container on the 595BowersHub Minisforum server.

## Glossary

- **BowersHub_AI**: The complete platform — FastAPI backend + React PWA frontend, running on port 5003
- **Workspace**: A scoped environment with its own system prompt, available skills, permitted DB schemas, and user access list. Examples: Finance, Woodshop, Cooking, General
- **Skill**: A registered capability backed by an n8n webhook, a direct DB query, or a deterministic function. Skills are assigned to workspaces and optionally restricted by user role
- **Router**: The intelligent message-handling system that decides whether to use a deterministic skill, a lightweight classifier (Haiku), or a full reasoning model (Sonnet) for each message
- **Context_Capture**: An automated background process that scans conversations post-message and silently persists important facts, decisions, and preferences to the knowledge base
- **Artifact**: A rich output panel (code, charts, documents, plans) rendered alongside the chat — editable, saveable, and shareable
- **Conversation**: A threaded exchange between a user and the AI within a workspace, persisted with full history and branchable at any point
- **Model_Provider**: An abstraction over AI model backends (Anthropic direct, AWS Bedrock, Ollama) allowing per-workspace or per-message model selection
- **Hook**: An automated action triggered by an event (message sent, file uploaded, conversation started, schedule) scoped to a workspace
- **Slash_Command**: A deterministic shortcut (e.g., `/balance`, `/weather`) that bypasses AI routing entirely for instant, zero-cost responses
- **Briefing**: A scheduled AI-generated summary delivered as the first message when a user opens the app (pulls from transactions, weather, calendar, inbox, etc.)
- **PWA**: Progressive Web App — installable on Android and iOS home screens with app-like behavior, offline shell, and push notification support

## Requirements

### Requirement 1: Multi-User Authentication and Authorization

**User Story:** As Michael, I want to invite users (like Manon) with their own accounts and control what each person can access, so that my financial data stays private while shared workspaces work naturally.

#### Acceptance Criteria

1. THE platform SHALL support user registration via admin-generated invite links that expire after 72 hours, with no self-registration allowed
2. THE platform SHALL authenticate users via email/password with bcrypt-hashed passwords stored in Postgres, issuing JWT access tokens (1-hour expiry) and refresh tokens (30-day expiry)
3. THE platform SHALL enforce role-based access with three roles: admin (full access, user management, all workspaces), member (access to assigned workspaces only), and viewer (read-only access to assigned workspaces, cannot send messages)
4. WHEN a user attempts to access a workspace they are not assigned to, THE platform SHALL return a 403 response and not reveal the workspace exists
5. THE platform SHALL provide an admin panel for user management: invite new users, assign roles, assign workspace access, deactivate accounts
6. THE platform SHALL support session persistence so that mobile PWA users remain logged in across app restarts until the refresh token expires
7. IF a refresh token is expired or revoked, THEN THE platform SHALL redirect the user to the login screen without losing any draft message content in localStorage

### Requirement 2: Workspaces with Scoped Permissions

**User Story:** As Michael, I want workspaces that define what the AI knows, what tools it can use, and who can access it, so that each context feels purpose-built without leaking data between domains.

#### Acceptance Criteria

1. THE platform SHALL support creating workspaces with the following configurable properties: name, description, system prompt, icon/color, default model, assigned users, permitted skills, permitted DB schemas, and pinned context documents
2. WHEN a user sends a message in a workspace, THE Router SHALL only consider skills assigned to that workspace and only query DB schemas permitted for that workspace
3. THE platform SHALL allow workspaces to be shared between multiple users, with each user inheriting the workspace's skill and schema permissions
4. THE platform SHALL allow admins to create workspaces and assign any combination of users and skills; members SHALL be able to create personal workspaces with only the skills their role permits
5. THE platform SHALL support workspace-level settings: default model override, temperature, max context messages, auto-capture enabled/disabled, and custom slash commands
6. WHEN a new database table or schema is added to Postgres, THE platform SHALL make it available for assignment to workspaces without code changes — the schema list is discovered dynamically from information_schema
7. THE platform SHALL ship with pre-configured workspaces matching the current setup: Finance (Michael only), Woodshop (Michael only), Cooking (Michael + Manon), House (Michael + Manon), and General (all users)

### Requirement 3: Intelligent Message Routing

**User Story:** As Michael, I want the AI to handle my messages intelligently — using free deterministic lookups when possible, cheap classification when needed, and expensive reasoning only when it matters — without me ever having to choose a "mode."

#### Acceptance Criteria

1. THE Router SHALL process each message through three layers in order: Layer 1 (deterministic slash commands and pattern matching), Layer 2 (lightweight AI classification via Haiku or local model), Layer 3 (full reasoning via Sonnet or user-selected model)
2. WHEN a message matches a slash command or deterministic pattern, THE Router SHALL execute the corresponding skill directly and return the result without any AI model invocation
3. WHEN a message does not match Layer 1, THE Router SHALL send it to Layer 2 for intent classification using the cheapest available model (Haiku or Ollama), with a maximum of 256 output tokens and a 10-second timeout
4. WHEN Layer 2 classifies a message with high confidence (above 0.75) as a skill invocation, THE Router SHALL execute the identified skill and format the response using the workspace's default model for natural-language wrapping (one short Haiku call to make the raw data conversational)
5. WHEN Layer 2 classifies with low confidence or identifies the message as requiring reasoning/analysis/explanation, THE Router SHALL escalate to Layer 3 (Sonnet or the user's selected model) with full conversation context
6. THE Router SHALL be invisible to the user — no "agent mode" toggle, no mode switching. Every message just works. The only visible indicator is a small layer badge (L1/L2/L3) on each response showing what handled it
7. WHEN the user explicitly selects a model via the model picker, THE Router SHALL bypass Layer 1 and Layer 2 and send the message directly to the selected model with tool-use capabilities enabled
8. IF Layer 2 fails (timeout, error), THE Router SHALL gracefully escalate to Layer 3 rather than returning an error

### Requirement 4: Model Provider Abstraction

**User Story:** As Michael, I want to use Anthropic models directly, AWS Bedrock models, and eventually local models — with the ability to pick per-message or let the system choose automatically.

#### Acceptance Criteria

1. THE platform SHALL support multiple model providers behind a unified abstraction: Anthropic API (direct), AWS Bedrock, and Ollama (local)
2. THE platform SHALL expose a model picker in the chat UI that shows all available models grouped by provider, with the current workspace default highlighted
3. WHEN set to "Auto" (the default), THE platform SHALL use the Router's layer-based selection (Haiku for classification, Sonnet for reasoning, deterministic for patterns)
4. WHEN a user selects a specific model, THE platform SHALL use that model for the current message only, then revert to Auto for subsequent messages (unless the user locks the selection)
5. THE platform SHALL support configuring provider credentials via environment variables: ANTHROPIC_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, OLLAMA_URL
6. THE platform SHALL discover available models from each configured provider at startup and refresh the list every 24 hours
7. IF a selected model's provider is unavailable, THEN THE platform SHALL display an error and suggest falling back to an available alternative
8. THE platform SHALL track per-model cost rates in a configuration table and use them for real-time cost display

### Requirement 5: Conversation Management

**User Story:** As Michael, I want persistent conversations I can name, search, branch, and share — like Claude's interface but with workspace scoping.

#### Acceptance Criteria

1. THE platform SHALL persist all messages (user, assistant, system, tool-call, tool-result) with timestamps, model used, token counts, cost, and routing layer to a Postgres table
2. THE platform SHALL support multiple named conversations per workspace per user, displayed in a sidebar sorted by last activity
3. THE platform SHALL support conversation branching: the user can select any message in history and "fork" the conversation from that point, creating a new conversation that shares history up to the branch point
4. THE platform SHALL support sharing a conversation with another user who has access to the same workspace, granting them read-only access to the full thread
5. WHEN a new message is sent, THE platform SHALL include the most recent messages from the active conversation as context, up to a configurable token budget (default: 8000 tokens, adjustable per workspace)
6. THE platform SHALL support searching across all conversations within a workspace by message content, with results showing the matching message in context
7. THE platform SHALL auto-title new conversations after the first assistant response using a single Haiku call (cost: ~$0.0002), with the user able to rename at any time
8. THE platform SHALL support archiving conversations (hidden from sidebar but searchable) and permanent deletion (admin only)

### Requirement 6: Automated Context Capture

**User Story:** As Michael, I want the AI to automatically notice and remember important things I mention in conversation — facts, preferences, decisions — without me having to say "remember this."

#### Acceptance Criteria

1. AFTER each assistant response, THE platform SHALL run a lightweight background analysis (Haiku, max 128 output tokens) that evaluates whether the exchange contains a persistable fact, preference, decision, or correction
2. IF the Context_Capture identifies extractable information, THE platform SHALL write it to the knowledge base at /knowledge/<workspace-topic>.md using the existing append format (- [YYYY-MM-DD] <statement>), and display a subtle "📌 noted" indicator on the message
3. THE Context_Capture SHALL deduplicate against existing knowledge entries for the same topic before writing, using the same Haiku-based dedup logic as the existing remember webhook
4. THE Context_Capture SHALL respect workspace scoping — facts captured in the Finance workspace go to finance topics, Woodshop facts go to woodshop topics
5. THE platform SHALL allow users to disable auto-capture per workspace or globally in their settings
6. THE platform SHALL provide a "What do you know about me?" command that retrieves all captured context for the current workspace, formatted as a readable summary
7. IF the Context_Capture background call fails, THE platform SHALL log the failure silently without affecting the user's chat experience
8. THE platform SHALL expose captured context in a reviewable list where users can delete individual entries they don't want persisted

### Requirement 7: Skill and Webhook Integration

**User Story:** As Michael, I want all my existing n8n webhooks to work as skills in the new platform, with new skills easy to add and scoped to the right workspaces and users.

#### Acceptance Criteria

1. THE platform SHALL maintain a skill registry in Postgres that stores for each skill: name, description, webhook URL, HTTP method, parameter schema (JSON Schema), response format hint, permitted workspaces, and permitted user roles
2. THE platform SHALL integrate with all existing n8n webhooks (finance-query, smart-capture, inventory-admin, remember, recall, balances, transactions, filter, send-email, process-asset) as pre-registered skills
3. WHEN the Router identifies a skill to invoke, THE platform SHALL call the webhook with the extracted parameters as a JSON body, respecting a 5-second connection timeout and 30-second response timeout
4. THE platform SHALL support skill-level user restrictions: certain skills (e.g., finance-query, override-category) can be marked as restricted to specific users regardless of workspace assignment
5. THE platform SHALL provide an admin UI for managing skills: add new skills, edit parameters, assign to workspaces, restrict to users, test with sample input
6. WHEN a skill call fails, THE platform SHALL display a user-friendly error message and offer to retry, without exposing internal URLs or error details
7. THE platform SHALL support "compound skills" where Layer 3 can chain multiple skill calls in a single response (up to 5 per message), displaying progress indicators for each call
8. THE platform SHALL allow skills to be added or modified without application restart — the registry is read from the database on each request

### Requirement 8: Slash Commands

**User Story:** As Michael, I want instant shortcuts for common actions that skip AI entirely — fast, free, and predictable.

#### Acceptance Criteria

1. THE platform SHALL support slash commands that execute deterministic actions with zero AI cost and sub-500ms response time (excluding webhook latency)
2. THE platform SHALL ship with default slash commands: /balance (account balances), /weather (current weather), /recall <query> (search knowledge base), /files (list inbox), /spend (MTD spending summary), /cost (today's AI spend breakdown), /help (list available commands)
3. THE platform SHALL support workspace-specific slash commands defined in the workspace configuration
4. WHEN the user types "/" in the input field, THE platform SHALL display an autocomplete dropdown showing available commands with descriptions, filtered as the user types
5. THE platform SHALL support slash commands with arguments: /recall woodshop tools, /spend groceries, /balance checking
6. THE platform SHALL allow admins to create custom slash commands that map to webhook URLs with parameter templates, without code changes
7. IF a slash command's backing webhook fails, THEN THE platform SHALL display the error inline and suggest the user try the natural-language equivalent

### Requirement 9: Artifacts and Rich Output

**User Story:** As Michael, I want the AI to produce rich outputs — code, charts, documents, plans — in a side panel I can interact with, save, and share, like Claude's artifacts.

#### Acceptance Criteria

1. WHEN the AI generates content that qualifies as an artifact (code blocks over 15 lines, HTML documents, SVG/Mermaid diagrams, structured plans, data tables over 10 rows), THE platform SHALL render it in a resizable side panel adjacent to the chat
2. THE artifact panel SHALL support multiple artifact types: code (with syntax highlighting and copy button), HTML (rendered in an iframe sandbox), Mermaid diagrams (rendered to SVG), charts (Chart.js rendered), markdown documents (rendered with full formatting), and data tables (sortable, filterable)
3. THE platform SHALL allow users to save artifacts to the file system at /files/artifacts/<workspace>/<slug>.html, accessible via a direct URL
4. THE platform SHALL support artifact versioning — when the AI updates an artifact in a follow-up message, the panel shows the new version with the ability to view/restore previous versions
5. THE platform SHALL allow users to copy artifact content, download as a file, or share via a direct link (accessible to users with workspace access)
6. ON mobile viewports (width < 768px), THE artifact panel SHALL render as a full-screen overlay with a close button to return to chat
7. THE platform SHALL support the AI proactively creating artifacts when appropriate (e.g., generating a spending chart when discussing finances) without the user explicitly requesting it

### Requirement 10: File Attachments and Vision

**User Story:** As Michael, I want to attach photos and documents to my messages so the AI can see them — especially for cataloging tools, processing receipts, and capturing recipes.

#### Acceptance Criteria

1. THE platform SHALL support file attachments in chat messages via drag-and-drop, paste, or a file picker button, accepting images (JPEG, PNG, WebP, GIF), PDFs, and plain text files up to 10MB each
2. WHEN an image is attached, THE platform SHALL send it to the AI model with vision capabilities enabled, allowing the model to describe, analyze, or extract information from the image
3. WHEN an image is attached in a workspace with the smart-capture skill enabled, THE platform SHALL offer a "Process to inventory" action that triggers the existing Process Asset pipeline (vision extraction → staging → commit)
4. THE platform SHALL display attached images as inline thumbnails in the chat message, expandable to full size on click
5. THE platform SHALL store uploaded files in /files/chat-uploads/<conversation_id>/ and create a files.assets record for each, enabling future retrieval and cross-referencing
6. WHEN a PDF is attached, THE platform SHALL extract the text content and include it in the message context (up to 50,000 characters), with the original PDF stored for reference
7. THE platform SHALL resize images over 4MB before sending to the AI model (matching the existing Pillow resize logic in filewriter) to stay within API limits
8. THE platform SHALL support attaching multiple files to a single message (up to 5 files)

### Requirement 11: Workspace Hooks (Automated Actions)

**User Story:** As Michael, I want automated actions that fire on events within workspaces — like auto-capturing context, triggering workflows when files are uploaded, or running scheduled briefings.

#### Acceptance Criteria

1. THE platform SHALL support hooks that trigger on events: message_sent, message_received, file_uploaded, conversation_started, conversation_ended, schedule (cron expression), and manual (user-triggered button)
2. THE platform SHALL scope hooks to specific workspaces — a hook defined in the Finance workspace only fires for events in that workspace
3. THE platform SHALL support hook actions: call_webhook (POST to an n8n endpoint), call_ai (send a prompt to a model and optionally display the result), capture_context (run the context capture logic), and notify (send a push notification via Pushover)
4. THE platform SHALL provide a hook management UI where admins can create, edit, enable/disable, and test hooks per workspace
5. THE platform SHALL support hook conditions: only fire if the message contains certain keywords, only fire for certain users, only fire if a skill was invoked, only fire during certain hours
6. THE platform SHALL log all hook executions with timestamp, trigger event, action taken, and result (success/failure) for debugging
7. THE Context_Capture (Requirement 6) SHALL be implemented as a built-in hook of type "message_received" → "capture_context", enabled by default on all workspaces but disableable
8. THE platform SHALL support a "daily briefing" hook: a scheduled hook (default 7:00 AM) that generates a morning summary and pins it as the first message when the user opens the app

### Requirement 12: Cost Tracking and Transparency

**User Story:** As Michael, I want to see exactly what each message costs, which model handled it, and how my daily/weekly spend is trending — right in the chat interface.

#### Acceptance Criteria

1. THE platform SHALL display a cost indicator on each assistant message showing: the routing layer (L1/L2/L3), the model used, and the cost in USD (to 4 decimal places for cheap calls, 2 decimal places for expensive ones)
2. THE platform SHALL maintain a running daily cost total visible in the chat header or sidebar, updating in real-time as messages are sent
3. THE platform SHALL log all AI API calls to the existing public.api_usage_log table with: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, model, provider, workspace_id, user_id, routing_layer, and message_id
4. THE platform SHALL provide a /cost slash command and a settings page showing: today's spend, 7-day trend, breakdown by model/layer/workspace, and comparison to the previous period
5. THE platform SHALL support configurable daily cost alerts: when spend exceeds a threshold (default $2.00), display a warning banner and optionally restrict to Haiku-only mode
6. THE platform SHALL calculate costs using per-model rate tables stored in the database, updatable via admin UI without code changes
7. IF cost logging fails, THE platform SHALL still deliver the response to the user and log the failure to application logs

### Requirement 13: React PWA Frontend

**User Story:** As Michael, I want a polished, installable chat app that works great on my Pixel 9 Pro and my Windows desktop — fast, responsive, and app-like.

#### Acceptance Criteria

1. THE frontend SHALL be built as a React application (Vite build toolchain) compiled to static files and served by the FastAPI backend
2. THE frontend SHALL be installable as a PWA on Android (Chrome "Add to Home Screen") and iOS (Safari "Add to Home Screen") with a custom app icon, splash screen, and standalone display mode
3. THE frontend SHALL implement a responsive layout: sidebar (conversations + workspaces) on desktop, bottom-sheet navigation on mobile, with the chat area always maximized
4. THE frontend SHALL render assistant messages with full markdown support (bold, italic, headers, code blocks with syntax highlighting, tables, lists, blockquotes, links) using a library like react-markdown + rehype
5. THE frontend SHALL support dark mode (default) and light mode, with the preference stored per-user and respecting system preference on first visit
6. THE frontend SHALL implement optimistic UI: user messages appear instantly, typing indicators show during AI processing, and streaming responses render token-by-token as they arrive via WebSocket
7. THE frontend SHALL cache the conversation list and last-viewed conversation in localStorage/IndexedDB for instant app-open experience, syncing with the server in the background
8. THE frontend SHALL support keyboard shortcuts: Enter to send, Shift+Enter for newline, Ctrl+K for command palette, Escape to close panels
9. THE frontend SHALL implement a service worker that caches the app shell for offline access (showing cached conversations read-only when the server is unreachable)

### Requirement 14: FastAPI Backend Architecture

**User Story:** As Michael, I want the backend to be a clean Python FastAPI app in Docker, fitting my existing deployment pattern and easy to maintain and extend.

#### Acceptance Criteria

1. THE backend SHALL run as a FastAPI application on port 5003 inside a Docker container connected to the ai-services_ai-network, with restart policy "unless-stopped"
2. THE backend SHALL use an async Postgres connection pool (asyncpg, min 2 / max 20 connections) for all database operations
3. THE backend SHALL serve the compiled React frontend from a /static directory at the root URL path, with API routes under /api/* and WebSocket connections at /ws/*
4. THE backend SHALL implement WebSocket connections for real-time message streaming, typing indicators, and hook notifications
5. THE backend SHALL expose a health endpoint at GET /api/health returning: status, database connectivity, model provider availability, uptime, and active WebSocket count
6. THE backend SHALL accept configuration via environment variables: ANTHROPIC_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, OLLAMA_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, N8N_BASE, JWT_SECRET, FILES_ROOT, KNOWLEDGE_ROOT
7. IF any required environment variable (ANTHROPIC_API_KEY, DB_*, JWT_SECRET) is missing at startup, THEN THE backend SHALL exit with a non-zero status code and log which variable is missing
8. THE backend SHALL be deployable using the standard pattern: scp source to server, docker build --no-cache, docker stop/rm old container, docker run with env vars and volume mounts
9. THE backend SHALL implement database migrations via a migrations directory, auto-applied on startup if pending

### Requirement 15: Pinned Context and Workspace Memory

**User Story:** As Michael, I want each workspace to always know relevant background information — my accounts in Finance, my tool inventory in Woodshop — without me re-explaining every conversation.

#### Acceptance Criteria

1. THE platform SHALL support pinned context documents per workspace: markdown files or database query results that are automatically included in every AI request within that workspace
2. THE platform SHALL support two types of pinned context: static (a markdown document that rarely changes) and dynamic (a SQL query whose results are refreshed every N minutes and included as context)
3. WHEN a message is sent, THE platform SHALL prepend all pinned context for the active workspace to the system prompt, within a configurable token budget (default: 2000 tokens for pinned context)
4. THE platform SHALL provide a UI for managing pinned context per workspace: add/edit/remove documents, configure dynamic query refresh intervals, preview the rendered context
5. THE platform SHALL support referencing existing knowledge base files as pinned context (e.g., pin /knowledge/finance/accounts.md to the Finance workspace)
6. IF pinned context exceeds the token budget, THE platform SHALL truncate the oldest/lowest-priority entries and log a warning, never failing the message send

### Requirement 16: Daily Briefing

**User Story:** As Michael, I want a morning summary waiting for me when I open the app — what happened overnight, today's schedule, spending alerts, anything I should know.

#### Acceptance Criteria

1. THE platform SHALL generate a daily briefing at a configurable time (default 7:00 AM server time) by calling relevant skills and composing a summary
2. THE briefing SHALL include: weather forecast, yesterday's spending total and notable transactions, any budget alerts, unread email count, inbox file count, and any scheduled events (when calendar integration exists)
3. THE briefing SHALL be generated using Haiku (cost: ~$0.002) by providing skill outputs as context and asking for a concise, friendly summary
4. WHEN the user opens the app after the briefing has been generated, THE platform SHALL display it as a pinned message at the top of the General workspace (or a user-configured workspace)
5. THE platform SHALL allow users to customize briefing content (which data sources to include) and timing in their settings
6. THE platform SHALL allow users to disable the daily briefing entirely
7. IF any data source for the briefing fails, THE platform SHALL generate the briefing with available data and note which sources were unavailable

### Requirement 17: Conversation Branching

**User Story:** As Michael, I want to fork a conversation at any point to explore a different direction without losing the original thread.

#### Acceptance Criteria

1. THE platform SHALL allow users to select any message in a conversation and create a branch from that point
2. WHEN a branch is created, THE platform SHALL create a new conversation that shares all messages up to and including the selected message, with subsequent messages diverging
3. THE platform SHALL display branched conversations in the sidebar with a visual indicator showing the parent conversation and branch point
4. THE platform SHALL support multiple branches from the same message
5. THE platform SHALL allow users to navigate between branches and the original conversation without losing context
6. WHEN viewing a branched conversation, THE platform SHALL show a "branched from" indicator linking back to the original conversation and branch point

### Requirement 18: Search

**User Story:** As Michael, I want to search across all my conversations and knowledge base from one place, finding anything I've ever discussed or saved.

#### Acceptance Criteria

1. THE platform SHALL provide a global search function accessible via Ctrl+K (desktop) or a search icon (mobile) that searches across: conversation messages, knowledge base entries, and artifact content
2. THE platform SHALL support full-text search with relevance ranking, returning results grouped by source type (conversations, knowledge, artifacts)
3. THE platform SHALL display search results with surrounding context (the matching message plus 1 message before and after) and a link to jump to that point in the conversation
4. THE platform SHALL scope search results to content the current user has access to (respecting workspace permissions)
5. THE platform SHALL support search filters: by workspace, by date range, by content type (messages/knowledge/artifacts)
6. THE platform SHALL implement search using Postgres full-text search (tsvector/tsquery) for zero additional infrastructure

### Requirement 19: Push Notifications

**User Story:** As Michael, I want to get notified on my phone when important things happen — budget alerts, briefing ready, or when Manon shares something with me.

#### Acceptance Criteria

1. THE platform SHALL support push notifications via the Web Push API (for PWA) and Pushover (for reliable delivery when the app is closed)
2. THE platform SHALL send notifications for: daily briefing ready, budget threshold exceeded, shared conversation received, hook execution failures (admin only), and custom hook-triggered notifications
3. THE platform SHALL allow users to configure notification preferences: which events trigger notifications, quiet hours, and delivery method (web push, Pushover, or both)
4. THE platform SHALL NOT send notifications for routine events (message received in active conversation, context captured, etc.) to avoid notification fatigue
5. IF web push delivery fails, THE platform SHALL fall back to Pushover for critical notifications (budget alerts, hook failures)

### Requirement 20: Security and Data Isolation

**User Story:** As Michael, I want strong data isolation between users and workspaces, with my financial data completely inaccessible to other users even if they're on the same server.

#### Acceptance Criteria

1. THE platform SHALL enforce workspace-level data isolation: queries executed by the Router or skills SHALL only access DB schemas permitted for the active workspace, enforced at the query layer (not just UI)
2. THE platform SHALL enforce user-level skill restrictions: if a skill is marked as restricted to specific users, the Router SHALL not invoke it for other users even if the workspace permits it
3. THE platform SHALL NOT expose internal service URLs, API keys, database credentials, or stack traces in any client-facing response including error messages
4. THE platform SHALL validate and sanitize all user input: maximum 10,000 characters per message, HTML entity encoding for display, parameterized queries for any DB operations
5. THE platform SHALL implement rate limiting: maximum 30 messages per minute per user, maximum 100 API calls per hour per user, with configurable thresholds
6. THE platform SHALL log all authentication events (login, logout, failed attempts, token refresh) and all admin actions (user creation, permission changes, skill modifications) to an audit table
7. ALL file uploads SHALL be scanned for valid MIME types matching their extension, with executable files rejected regardless of extension
8. THE platform SHALL run within the Tailscale network with no public internet exposure; the Docker container SHALL bind to 0.0.0.0:5003 (accessible only via Tailscale IP and Docker internal network)
