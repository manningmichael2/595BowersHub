"""
Router Engine: 3-layer intelligent message routing.

Layer 1: Slash commands + regex patterns (zero cost, <100ms)
Layer 2: Haiku/Ollama classification (low cost, <2s)
Layer 3: Sonnet/selected model reasoning (full cost, streaming)
"""

import json
import logging
import re
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.config import Config
from backend.database import get_pool
from backend.models.message import CompletionResult, StreamChunk, ToolCall
from backend.services.model_catalog import resolve_role
from backend.services.model_provider import ModelProvider
from backend.services.skill_executor import (
    SkillExecutor, SkillResult, SkillExecutionError, SkillPermissionError,
)
from backend.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


@dataclass
class RoutingContext:
    """Context passed through the routing pipeline."""
    user_id: int
    user_role: str
    workspace_id: int
    workspace_name: str
    system_prompt: str
    default_model: str
    max_context_tokens: int
    permitted_schemas: List[str]
    conversation_id: int
    force_model: Optional[str] = None  # if user selected a specific model
    attachments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RoutingResult:
    """Result from the routing pipeline."""
    layer: str  # 'L1', 'L2', 'L3'
    content: str
    model_used: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    skill_name: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


class RouterEngine:
    """
    3-layer message routing engine.
    Processes every user message through a deterministic pipeline.
    """

    CLASSIFICATION_PROMPT = """You are a message classifier for a personal AI assistant. Given a user message (and optional recent conversation history for context), determine if the message can be FULLY answered by calling exactly ONE skill with specific parameters.

Available skills:
{skills_list}

{history_block}Respond with ONLY valid JSON (no markdown, no explanation):
{{"skill": "<skill_name or null>", "confidence": <0.0-1.0>, "params": {{<extracted parameters>}}}}

IMPORTANT RULES:
- Return a skill ONLY if the message is a simple, direct request that one skill can fully handle
- Use conversation history to resolve follow-up questions (e.g. if the previous turn was about weather, "what about tomorrow?" is also a weather request)
- Return {{"skill": null, "confidence": 0.0, "params": {{}}}} for ANY of these:
  - General knowledge questions ("who is X?", "what is Y?", "explain Z")
  - Questions requiring analysis, comparison, or multi-step reasoning
  - Questions that clearly need multiple data sources combined
  - Conversational messages, opinions, or open-ended questions
- For "recall" skill: only use if the user explicitly asks to search their knowledge base or asks "what do I know about X"
- For "ask-db" skill: only use for specific data lookups that are clearly one query ("how much did I spend on X", "list my router bits")
- When in doubt, return null — it's better to escalate to the full reasoning model

EXAMPLES of messages that SHOULD map to a skill:
- "what's the weather?" → weather, params: {{}}
- "weather in Detroit" → weather, params: {{"location": "Detroit"}}
- "what is the weather tomorrow" → weather, params: {{}}
- "what about later today?" (after a weather question) → weather, params: {{}}
- "what's the score?" → sports-score, params: {{}}
- "Tigers score" → sports-score, params: {{"team": "Tigers"}}
- "who is pitching for the Tigers?" → sports-score, params: {{"team": "Tigers"}}
- "who's starting tonight?" (after a sports exchange) → sports-score, params: {{"team": "<team from context>"}}
- "what's the pitching matchup?" → sports-score, params: {{"team": "<team from context>"}}
- "give me the box score" → sports-score, params: {{"team": "<team from context>", "query_type": "boxscore"}}
- "tigers box score" → sports-score, params: {{"team": "Tigers", "query_type": "boxscore"}}
- "batting stats for the game" → sports-score, params: {{"team": "<team from context>", "query_type": "boxscore"}}
- "what's my balance" → get-balances, params: {{}}
- "how much did I spend on groceries" → ask-db, params: {{"question": "how much did I spend on groceries"}}
- "recall what I know about router bits" → recall, params: {{"query": "router bits"}}
- "what's in the news?" → news, params: {{}}
- "sports news" → news, params: {{"category": "sports"}}
- "tech headlines" → news, params: {{"category": "tech"}}
- "what's on my calendar today?" → calendar, params: {{"query": "today"}}
- "what do I have today?" → calendar, params: {{"query": "today"}}
- "what's on my schedule this week?" → calendar, params: {{"query": "week"}}
- "do I have anything tomorrow?" → calendar, params: {{"query": "tomorrow"}}
- "show my upcoming events" → calendar, params: {{"days": 7}}

User message: {message}"""

    FORMATTING_PROMPT = """You are a helpful assistant presenting data to the user. The user asked: "{question}"

Here is the data retrieved from the system:
{raw_data}

Present this data in a clear, conversational way. Use markdown formatting (tables, bold, lists) where helpful. Be thorough — include all the relevant data, don't summarize away details the user would want to see. If the data is empty or shows no results, say so clearly and suggest what the user could try instead."""

    def __init__(self, model_provider: ModelProvider, skill_executor: SkillExecutor, config: Config):
        self.model_provider = model_provider
        self.skill_executor = skill_executor
        self.config = config

    async def route(
        self, message: str, context: RoutingContext, ws_manager: WebSocketManager
    ) -> RoutingResult:
        """
        Route a message through the 3-layer pipeline.
        Returns the final result with metadata.
        """
        # Store ws_manager for commands that need streaming
        self._ws_manager = ws_manager

        # Layer 1: Deterministic (slash commands + patterns)
        if message.startswith("/"):
            result = await self._try_slash_command(message, context)
            if result:
                return result

        pattern_result = await self._try_pattern_match(message, context)
        if pattern_result:
            return pattern_result

        # If user forced a specific model, skip L2 and go to L3
        if context.force_model and context.force_model != "auto":
            return await self._layer3_reason(message, context, ws_manager)

        # Layer 2: Lightweight AI classification
        try:
            # Fetch workspace skills once — used for classification and threshold logic
            workspace_skills = await self.skill_executor.get_workspace_skills(context.workspace_id)

            classification = await self._classify(message, context)
            if classification and classification.get("skill"):
                skill = classification["skill"]
                confidence = classification.get("confidence", 0)
                # Lower threshold for read-only/info skills — false positives are harmless.
                # Threshold is DB-driven via bh_skills.is_read_only column.
                threshold = 0.65 if self._is_read_only_skill(skill, workspace_skills) else 0.75

                if confidence > threshold:
                    skill_result = await self._execute_classified_skill(
                        classification, message, context
                    )
                    if skill_result:
                        return skill_result

                # L2.5: Borderline confidence — use local model to refine
                elif confidence >= 0.4:
                    try:
                        from backend.services.local_intelligence import refine_classification
                        refined = await refine_classification(
                            message, skill, confidence, workspace_skills or []
                        )
                        if refined and refined.get("skill"):
                            refined_conf = refined.get("confidence", 0)
                            refined_skill = refined["skill"]
                            refined_threshold = 0.65 if self._is_read_only_skill(refined_skill, workspace_skills) else 0.75
                            if refined_conf >= refined_threshold:
                                skill_result = await self._execute_classified_skill(
                                    refined, message, context
                                )
                                if skill_result:
                                    return skill_result
                    except Exception as e:
                        logger.debug(f"L2.5 local refinement failed (non-critical): {e}")

            # L2 returned no skill — try local model as pre-L3 gate
            elif classification and not classification.get("skill"):
                try:
                    from backend.services.local_intelligence import refine_classification
                    if workspace_skills:
                        local_pick = await refine_classification(
                            message, None, 0.0, workspace_skills
                        )
                        if local_pick and local_pick.get("skill") and local_pick.get("confidence", 0) >= 0.7:
                            skill_result = await self._execute_classified_skill(
                                local_pick, message, context
                            )
                            if skill_result:
                                return skill_result
                except Exception as e:
                    logger.debug(f"Pre-L3 local gate failed (non-critical): {e}")

        except Exception as e:
            logger.warning(f"Layer 2 classification failed, escalating to L3: {e}")

        # Layer 2.5: Flexible Tool Router — Haiku with API registry
        # If the rigid skill system couldn't handle it, let Haiku reason
        # about available APIs and built-in tools before escalating to L3.
        try:
            from backend.services.tool_router import route_with_tools
            # Build conversation context for follow-up handling
            conv_context = ""
            if context.conversation_id:
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        rows = await conn.fetch("""
                            SELECT role, content FROM public.bh_messages
                            WHERE conversation_id = $1
                            AND role IN ('user', 'assistant')
                            ORDER BY created_at DESC LIMIT 4
                        """, context.conversation_id)
                    if rows:
                        conv_context = "\n".join(
                            f"{'User' if r['role'] == 'user' else 'Assistant'}: {r['content'][:200]}"
                            for r in reversed(rows)
                        )
                except Exception:
                    pass

            tool_result = await route_with_tools(message, conv_context)
            if tool_result and tool_result.get("content"):
                return RoutingResult(
                    layer="L2",
                    content=tool_result["content"],
                    model_used=tool_result.get("model_used", resolve_role("fast")),
                    input_tokens=tool_result.get("input_tokens", 0),
                    output_tokens=tool_result.get("output_tokens", 0),
                    cost_usd=self._calculate_cost(
                        resolve_role("fast"),
                        tool_result.get("input_tokens", 0),
                        tool_result.get("output_tokens", 0),
                    ),
                    skill_name="toolbox",
                )
        except Exception as e:
            logger.debug(f"Tool router failed (non-critical): {e}")

        # Layer 3: Full reasoning with tool use
        return await self._layer3_reason(message, context, ws_manager)

    # --- Layer 1: Deterministic ---

    async def _try_slash_command(self, message: str, context: RoutingContext) -> Optional[RoutingResult]:
        """Try to match a slash command."""
        parts = message.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        pool = get_pool()
        async with pool.acquire() as conn:
            # Check workspace-specific commands first, then global
            row = await conn.fetchrow("""
                SELECT sc.*, s.name as skill_name, s.webhook_url, s.http_method
                FROM public.bh_slash_commands sc
                LEFT JOIN public.bh_skills s ON s.id = sc.skill_id
                WHERE sc.command = $1 AND sc.is_active = true
                AND (sc.workspace_id = $2 OR sc.workspace_id IS NULL)
                ORDER BY sc.workspace_id DESC NULLS LAST
                LIMIT 1
            """, command, context.workspace_id)

        if not row:
            # All commands should be in bh_slash_commands. If a /command isn't found,
            # tell the user — don't maintain a hardcoded fallback list.
            # The only exception is /help and /new which must always work even if
            # the DB is empty (bootstrap safety).
            if command in ("/help", "/new"):
                return await self._handle_builtin_command(command, args, context)
            return RoutingResult(
                layer="L1",
                content=f"Unknown command: `{command}`. Type `/help` for available commands.",
            )

        # Built-in commands (no skill_id)
        if row["skill_id"] is None:
            return await self._handle_builtin_command(command, args, context)

        # Skill-backed command
        params = row["param_template"] or {}
        if not isinstance(params, dict):
            params = {}
        # Replace $args placeholder
        for key, val in list(params.items()):
            if isinstance(val, str) and "$args" in val:
                if "$args_first" in val:
                    # First word of args
                    parts = args.split(None, 1)
                    params[key] = val.replace("$args_first", parts[0] if parts else "")
                elif "$args_rest" in val:
                    # Everything after the first word
                    parts = args.split(None, 1)
                    params[key] = val.replace("$args_rest", parts[1] if len(parts) > 1 else "")
                else:
                    params[key] = val.replace("$args", args)

        try:
            # Slash commands bypass workspace skill restrictions — if it's a global command,
            # the user explicitly asked for it and we should run it.
            is_global_command = row["workspace_id"] is None
            result = await self.skill_executor.execute(
                row["skill_name"], params, context.user_id, context.workspace_id,
                bypass_workspace_check=is_global_command,
            )
            formatted = self.skill_executor.format_response(result)
            return RoutingResult(
                layer="L1", content=formatted, skill_name=row["skill_name"]
            )
        except (SkillExecutionError, SkillPermissionError) as e:
            return RoutingResult(layer="L1", content=f"⚠️ {e}")

    async def _handle_builtin_command(self, command: str, args: str, context: RoutingContext) -> RoutingResult:
        """Handle built-in slash commands that don't map to skills."""
        if command == "/help":
            pool = get_pool()
            async with pool.acquire() as conn:
                commands = await conn.fetch("""
                    SELECT command, description FROM public.bh_slash_commands
                    WHERE is_active = true
                    AND (workspace_id = $1 OR workspace_id IS NULL)
                    ORDER BY command
                """, context.workspace_id)
            lines = ["**Available commands:**\n"]
            for cmd in commands:
                lines.append(f"- `{cmd['command']}` — {cmd['description']}")
            return RoutingResult(layer="L1", content="\n".join(lines))

        elif command == "/new":
            return RoutingResult(layer="L1", content="✓ Starting a new conversation.")

        elif command == "/cost":
            return await self._handle_cost_command(args, context)

        elif command == "/files":
            return await self._handle_files_command(args)

        elif command == "/inventory":
            return await self._handle_inventory_command(args)

        elif command == "/transactions":
            return await self._handle_transactions_command(args)

        elif command == "/remind":
            return await self._handle_remind_command(args, context)

        elif command == "/briefing":
            return await self._handle_briefing_command(args, context)

        elif command == "/email":
            return await self._handle_email_command(args)

        elif command == "/local":
            return await self._handle_local_command(args, context)

        elif command == "/health":
            return await self._handle_health_command(args)

        elif command == "/inbox":
            # Legacy alias — redirect to /email
            return await self._handle_email_command(args)

        elif command in ("/sports", "/score"):
            return await self._handle_sports_command(args)

        elif command == "/news":
            return await self._handle_news_command(args)

        elif command in ("/schedule", "/calendar"):
            return await self._handle_schedule_command(args)

        elif command == "/weather":
            return await self._handle_weather_command(args)

        elif command == "/recall":
            return await self._handle_recall_command(args)

        return RoutingResult(layer="L1", content=f"Unknown command: {command}")

    async def _handle_files_command(self, args: str) -> RoutingResult:
        """List files in a directory under FILES_ROOT."""
        from pathlib import Path
        directory = args.strip() or "inbox"
        # Sanitize to prevent traversal
        directory = directory.replace("..", "").strip("/")

        files_root = Path(self.config.FILES_ROOT)
        target = files_root / directory

        if not target.exists() or not target.is_dir():
            return RoutingResult(layer="L1", content=f"Directory not found: `{directory}`")

        try:
            entries = sorted(target.iterdir())
        except PermissionError:
            return RoutingResult(layer="L1", content=f"Cannot access: `{directory}`")

        if not entries:
            return RoutingResult(layer="L1", content=f"📁 `{directory}/` is empty")

        lines = [f"**📁 {directory}/** ({len(entries)} items)\n"]
        files = [e for e in entries if e.is_file()]
        dirs = [e for e in entries if e.is_dir()]

        if dirs:
            for d in dirs[:20]:
                lines.append(f"- 📁 `{d.name}/`")

        if files:
            for f in files[:30]:
                size = f.stat().st_size
                size_str = f"{size:,}B" if size < 1024 else f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
                icon = "🖼" if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif') else "📄"
                lines.append(f"- {icon} `{f.name}` ({size_str})")

        if len(entries) > 50:
            lines.append(f"\n*...and {len(entries) - 50} more*")

        return RoutingResult(layer="L1", content="\n".join(lines))

    async def _handle_inventory_command(self, args: str) -> RoutingResult:
        """Handle /inventory — list inventory items or show summary."""
        from backend.services.inventory import get_inventory
        # Strip -- prefix from flags (--tools → tools)
        table = args.strip().lstrip("-")
        # Map shorthand flags to table names
        table_aliases = {"bits": "router_bits", "blades": "saw_blades"}
        table = table_aliases.get(table, table)
        result = await get_inventory(table=table)
        display = result.get("_display", str(result))
        return RoutingResult(layer="L1", content=display)

    async def _handle_transactions_command(self, args: str) -> RoutingResult:
        """Handle /transactions — show recent transactions or filter."""
        from backend.services.transactions import get_transactions, get_large_transactions, get_recurring_transactions, get_uncategorized_transactions
        # Strip -- prefix from flags (--week → week, --today → today)
        cleaned = args.strip().lstrip("-")

        # --sync: pull latest from SimpleFin
        if cleaned in ("sync", "refresh"):
            from backend.services.simplefin_sync import sync_simplefin
            result = await sync_simplefin(window_days=14)
            display = result.get("_display", "Sync complete.")
            return RoutingResult(layer="L1", content=display)

        # Special flags
        if cleaned in ("large", "big"):
            result = await get_large_transactions()
            display = result.get("_display", str(result))
            return RoutingResult(layer="L1", content=display)
        if cleaned in ("recurring", "subscriptions"):
            result = await get_recurring_transactions()
            display = result.get("_display", str(result))
            return RoutingResult(layer="L1", content=display)
        if cleaned in ("uncategorized", "uncat"):
            result = await get_uncategorized_transactions()
            display = result.get("_display", str(result))
            return RoutingResult(layer="L1", content=display)
        if cleaned in ("help", "?"):
            return RoutingResult(layer="L1", content=(
                "**💳 /transactions flags:**\n\n"
                "- `/transactions` — Last 15 transactions\n"
                "- `/transactions --sync` — Pull latest from SimpleFin now\n"
                "- `/transactions --today` — Today only\n"
                "- `/transactions --week` — Last 7 days\n"
                "- `/transactions --month` — This month\n"
                "- `/transactions --large` — Over $100\n"
                "- `/transactions --recurring` — Likely recurring charges\n"
                "- `/transactions --uncategorized` — No category assigned\n"
                "- `/transactions house` — Search by category or description"
            ))

        # Map flags to date phrases
        flag_map = {"week": "last week", "month": "this month", "today": "today"}
        query = flag_map.get(cleaned, cleaned)
        result = await get_transactions(args=query)
        display = result.get("_display", str(result))
        return RoutingResult(layer="L1", content=display)

    async def _handle_remind_command(self, args: str, context: RoutingContext) -> RoutingResult:
        """Handle /remind — set a timed reminder."""
        cleaned = args.strip()
        cleaned_lower = cleaned.lower().lstrip("-")

        # /remind --list
        if cleaned_lower in ("list", "pending", "show"):
            pool = get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT message, deliver_at FROM public.bh_reminders
                    WHERE user_id = $1 AND delivered_at IS NULL
                    ORDER BY deliver_at ASC
                """, context.user_id)
            if not rows:
                return RoutingResult(layer="L1", content="📌 No pending reminders.")
            lines = ["**📌 Pending Reminders**\n"]
            for r in rows:
                time_str = r["deliver_at"].strftime("%I:%M %p, %b %d").lstrip("0")
                lines.append(f"- {time_str} — {r['message']}")
            return RoutingResult(layer="L1", content="\n".join(lines))

        # /remind --clear
        if cleaned_lower in ("clear", "cancel", "clearall"):
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute("""
                    DELETE FROM public.bh_reminders
                    WHERE user_id = $1 AND delivered_at IS NULL
                """, context.user_id)
            count = int(result.split()[-1]) if result else 0
            return RoutingResult(layer="L1", content=f"✅ Cleared {count} pending reminder{'s' if count != 1 else ''}.")

        if not cleaned:
            return RoutingResult(layer="L1", content=(
                "**Usage:** `/remind <when> <message>`\n\n"
                "Examples:\n"
                "- `/remind in 30 minutes check the oven`\n"
                "- `/remind in 2 hours call the dentist`\n"
                "- `/remind tomorrow at 9am review budget`\n\n"
                "Flags:\n"
                "- `/remind --list` — Show pending reminders\n"
                "- `/remind --clear` — Cancel all pending"
            ))
        
        from backend.services.reminder_parser import parse_reminder
        parsed = parse_reminder(cleaned)
        
        if not parsed:
            return RoutingResult(layer="L1", content=(
                "⚠️ Couldn't parse the time. Try:\n"
                "- `in 30 minutes`, `in 2 hours`, `in 1 day`\n"
                "- `tomorrow at 9am`, `at 5pm`"
            ))
        
        deliver_at, message = parsed
        
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO public.bh_reminders (user_id, message, deliver_at) VALUES ($1, $2, $3)",
                context.user_id, message, deliver_at,
            )
        
        time_str = deliver_at.strftime("%I:%M %p on %b %d").lstrip("0")
        return RoutingResult(layer="L1", content=f"✅ Reminder set for **{time_str}**:\n\n> {message}")

    async def _handle_briefing_command(self, args: str, context: RoutingContext) -> RoutingResult:
        """Handle /briefing — show or configure morning briefing."""
        cleaned = args.strip().lower().lstrip("-")
        
        if not cleaned or cleaned == "now":
            # Generate an on-demand briefing (full)
            from backend.services.briefing import BriefingService
            svc = BriefingService(self.model_provider, self.skill_executor, self.config)
            content = await svc.generate(context.user_id, context.workspace_id)
            return RoutingResult(layer="L1", content=content)

        if cleaned == "short":
            # Quick briefing — just weather + emails
            from backend.services.briefing import BriefingService
            svc = BriefingService(self.model_provider, self.skill_executor, self.config)
            content = await svc.generate_short(context.user_id)
            return RoutingResult(layer="L1", content=content)
        
        if cleaned == "off":
            return RoutingResult(layer="L1", content="✅ Morning briefing disabled. Use `/briefing` to re-enable.")
        
        if cleaned == "on":
            return RoutingResult(layer="L1", content="✅ Morning briefing enabled at 7:00 AM.")
        
        return RoutingResult(layer="L1", content=(
            "**Briefing flags:**\n"
            "- `/briefing` — full briefing now\n"
            "- `/briefing --short` — just weather + emails\n"
            "- `/briefing on` — enable daily 7am briefing\n"
            "- `/briefing off` — disable daily briefing"
        ))

    async def _handle_email_command(self, args: str) -> RoutingResult:
        """Handle /email — prioritized email digest, cleanup, or full list."""
        from backend.services.inbox_cleaner import clean_inbox, email_digest, email_all, email_unsubscribe

        args_lower = args.strip().lower().lstrip("-")  # Accept --flag or flag

        # /email help — show available flags
        if args_lower in ("help", "?"):
            help_text = """**📬 /email flags:**

- `/email` — Show prioritized digest of important emails
- `/email --clean` — Classify and archive junk (newsletters, marketing, spam)
- `/email --preview` — Dry-run of clean (shows what would happen)
- `/email --all` — Show all recent emails with categories
- `/email --unsubscribe` — Find senders to unsubscribe from
- `/email --help` — This message"""
            return RoutingResult(layer="L1", content=help_text)

        # /email --clean
        if args_lower in ("clean", "tidy"):
            result = await clean_inbox(limit=30, dry_run=False)
            display = result.get("_display", "Email cleanup complete.")
            return RoutingResult(layer="L1", content=display)

        # /email --preview
        if args_lower in ("preview", "dry", "check"):
            result = await clean_inbox(limit=30, dry_run=True)
            display = result.get("_display", "Email preview complete.")
            return RoutingResult(layer="L1", content=display)

        # /email --all
        if args_lower == "all":
            result = await email_all(limit=30)
            display = result.get("_display", "No emails.")
            return RoutingResult(layer="L1", content=display)

        # /email --important — show only priority emails
        if args_lower in ("important", "priority"):
            result = await email_digest(limit=20)
            # Filter to just the important section from the digest
            display = result.get("_display", "📭 No unread emails.")
            return RoutingResult(layer="L1", content=display)

        # /email --unsubscribe
        if args_lower in ("unsubscribe", "unsub"):
            result = await email_unsubscribe(limit=50)
            display = result.get("_display", "No candidates found.")
            return RoutingResult(layer="L1", content=display)

        # /email (no args or a number) — prioritized digest
        limit = 20
        if args_lower.isdigit():
            limit = min(int(args_lower), 50)

        result = await email_digest(limit=limit)
        display = result.get("_display", "📭 No unread emails.")
        return RoutingResult(layer="L1", content=display)

    async def _handle_local_command(self, args: str, context: RoutingContext) -> RoutingResult:
        """Handle /local — chat with the local Ollama model for free.
        
        Streams the response via WebSocket just like L3, but uses the local
        local Ollama model at zero cost.
        """
        if not args.strip():
            help_text = """**🖥️ /local — Free local AI chat**

Chat with the local Llama 3.2 3B model running on your server. Zero API cost.

Usage: `/local <your question or prompt>`

Examples:
- `/local summarize what a CalDAV server does`
- `/local write a haiku about woodworking`
- `/local explain the difference between a dado and a rabbet`

_Note: This model is smaller than Claude — great for simple questions, brainstorming, and casual chat. For complex reasoning or tool use, just send a normal message (routes to Claude)._"""
            return RoutingResult(layer="L1", content=help_text)

        # Stream response from Ollama
        ws_manager = getattr(self, '_ws_manager', None)

        model = resolve_role("local")
        messages = [{"role": "user", "content": args.strip()}]

        full_content = ""
        try:
            async for chunk in self.model_provider.stream(
                model=model, messages=messages, max_tokens=2048,
            ):
                if chunk.type == "text_delta" and chunk.data:
                    full_content += chunk.data
                    if ws_manager:
                        await ws_manager.send_token(
                            context.user_id, context.conversation_id, chunk.data
                        )
        except Exception as e:
            logger.error(f"/local streaming failed: {e}")
            return RoutingResult(layer="L1", content=f"⚠️ Local model error: {e}")

        return RoutingResult(layer="L1", content=full_content, model=model)

    async def _handle_sports_command(self, args: str) -> RoutingResult:
        """Handle /sports — scores and schedules.
        
        Usage:
            /sports                     → scores for my tracked teams
            /sports --scores            → same as above
            /sports --scores tigers     → Tigers latest score
            /sports --schedule          → schedule for my tracked teams (7 days)
            /sports --schedule usmnt    → USMNT schedule
            /sports tigers              → Tigers score (shorthand for --scores tigers)
            /sports mlb                 → All MLB scores today
        """
        from backend.services.sports_score import (
            get_sports_score, get_sports_schedule,
            get_my_teams_scores, get_my_teams_schedule,
        )

        args = args.strip()

        # Parse flags
        if args.startswith("--schedule"):
            remainder = args[len("--schedule"):].strip()
            if not remainder:
                result = await get_my_teams_schedule()
            else:
                result = await get_sports_schedule(team=remainder)
            display = result.get("_display", "No schedule data available.")
            return RoutingResult(layer="L1", content=display)

        if args.startswith("--scores"):
            remainder = args[len("--scores"):].strip()
            if not remainder:
                result = await get_my_teams_scores()
            else:
                result = await get_sports_score(team=remainder)
            display = result.get("_display", "No results available.")
            return RoutingResult(layer="L1", content=display)

        if args.startswith("--help"):
            help_text = """**🏟️ /sports — Scores & Schedules**

**Scores (latest/live):**
- `/sports` or `/sports --scores` — Your tracked teams
- `/sports --scores tigers` — Specific team
- `/sports tigers` — Shorthand (same as above)
- `/sports mlb` — All games for a league

**Schedule (upcoming):**
- `/sports --schedule` — Your tracked teams (next 7 days)
- `/sports --schedule usmnt` — Specific team schedule

**Tracked teams:** Tigers, Lions, Pistons, Red Wings, Michigan, USMNT"""
            return RoutingResult(layer="L1", content=help_text)

        # No flag — treat as a team/league name for scores (default behavior)
        if not args:
            result = await get_my_teams_scores()
        else:
            result = await get_sports_score(team=args)

        display = result.get("_display", "No results available.")
        return RoutingResult(layer="L1", content=display)

    async def _handle_news_command(self, args: str) -> RoutingResult:
        """Handle /news — fetch current headlines.

        Usage:
            /news              → Top headlines (NPR)
            /news sports       → Sports headlines (ESPN)
            /news tech         → Tech news (Ars Technica)
            /news world        → World news
            /news business     → Business news
        """
        from backend.services.news import get_news

        args = args.strip()
        category = args if args else "top"

        result = await get_news(category=category)
        display = result.get("_display", str(result))
        return RoutingResult(layer="L1", content=display)

    async def _handle_weather_command(self, args: str) -> RoutingResult:
        """Handle /weather — get weather forecast.

        Usage:
            /weather              → Current weather (default location)
            /weather detroit      → Weather for a specific location
            /weather --tomorrow   → Tomorrow's forecast
            /weather --week       → 5-day forecast
        """
        from backend.services.weather import get_weather

        cleaned = args.strip().lstrip("-")

        # Parse flags — the weather skill currently shows today + 2 days regardless,
        # but we pass the location through
        location = None
        if cleaned and cleaned not in ("tomorrow", "tmrw", "week", "5day", "forecast"):
            location = cleaned

        result = await get_weather(location=location)
        display = result.get("_display", str(result))
        return RoutingResult(layer="L1", content=display)

    async def _handle_recall_command(self, args: str) -> RoutingResult:
        """Handle /recall — search knowledge base.

        Usage:
            /recall <query>    → Search for a topic
            /recall --list     → Show all knowledge topics
            /recall --recent   → Show last 10 facts saved
        """
        cleaned = args.strip().lstrip("-")

        if cleaned in ("list", "topics", "all"):
            # Show all knowledge topics from the graph
            from backend.services.knowledge_graph import get_stats, recall_entities
            stats = await get_stats()
            entities = await recall_entities(limit=30)
            lines = [f"## 🧠 Knowledge Base ({stats['entities']} entities, {stats['relationships']} connections)", ""]
            if stats.get("types"):
                type_list = ", ".join(f"{t}: {c}" for t, c in stats["types"].items())
                lines.append(f"**Types:** {type_list}")
                lines.append("")
            for e in entities[:20]:
                lines.append(f"- **{e['name']}** ({e['entity_type']}){' — ' + e['summary'][:60] if e.get('summary') else ''}")
            return RoutingResult(layer="L1", content="\n".join(lines))

        if cleaned in ("recent", "latest", "last"):
            from backend.services.knowledge_graph import recall_entities
            entities = await recall_entities(limit=10)
            if not entities:
                return RoutingResult(layer="L1", content="No knowledge saved yet. Try `/remember <topic> <fact>`")
            lines = ["## 🧠 Recent Knowledge", ""]
            for e in entities:
                date_str = e["updated_at"].strftime("%b %-d") if e.get("updated_at") else ""
                lines.append(f"- **{e['name']}** ({e['entity_type']}) — {e.get('summary', '')[:80]} *({date_str})*")
            return RoutingResult(layer="L1", content="\n".join(lines))

        # Default: search
        if not cleaned:
            return RoutingResult(layer="L1", content="What would you like to recall? Usage: `/recall <search term>`")

        # Use the skill handler (searches both graph + markdown)
        result = await self.skill_executor.execute("recall", {"query": cleaned}, 1, 1)
        formatted = self.skill_executor.format_response(result)
        return RoutingResult(layer="L1", content=formatted)

    async def _handle_schedule_command(self, args: str) -> RoutingResult:
        """Handle /schedule (and /calendar) — show calendar events.

        Usage:
            /schedule            → Today + next 7 days
            /schedule today      → Today only
            /schedule tomorrow   → Tomorrow only
            /schedule week       → This week (7 days)
            /schedule 14         → Next 14 days
        """
        from backend.services.calendar import get_events

        cleaned = args.strip().lower()

        if not cleaned or cleaned in ("help", "?"):
            help_text = (
                "**📅 /schedule flags:**\n\n"
                "- `/schedule` — Today + next 7 days\n"
                "- `/schedule today` — Today only\n"
                "- `/schedule tomorrow` — Tomorrow only\n"
                "- `/schedule week` — Next 7 days\n"
                "- `/schedule 14` — Next N days"
            )
            return RoutingResult(layer="L1", content=help_text)

        days_map = {"today": 0, "tomorrow": 1, "week": 6, "this week": 6, "next week": 13}
        days = days_map.get(cleaned, None)
        if days is None:
            try:
                days = int(cleaned)
            except (ValueError, TypeError):
                days = 7

        result = await get_events(days_ahead=days)
        display = result.get("_display", str(result))
        return RoutingResult(layer="L1", content=display)

    async def _handle_health_command(self, args: str) -> RoutingResult:
        """Handle /health — check all service connections."""
        from backend.services.healthcheck import run_healthcheck
        cleaned = args.strip().lstrip("-")
        service = cleaned if cleaned and cleaned != "help" else None

        if cleaned == "help":
            return RoutingResult(layer="L1", content=(
                "**🏥 /health flags:**\n\n"
                "- `/health` — Check all services\n"
                "- `/health --postgres` — Check database\n"
                "- `/health --ollama` — Check local AI model\n"
                "- `/health --filewriter` — Check file service\n"
                "- `/health --imap` — Check Gmail connection\n"
                "- `/health --simplefin` — Check bank sync\n"
                "- `/health --anthropic` — Check Claude API\n"
                "- `/health --n8n` — Check workflow engine\n"
                "- `/health --pushover` — Check push notifications"
            ))

        result = await run_healthcheck(service=service)
        display = result.get("_display", "Health check complete.")
        return RoutingResult(layer="L1", content=display)

    async def _handle_cost_command(self, args: str, context: RoutingContext) -> RoutingResult:
        """Handle /cost — show AI spend breakdown."""
        pool = get_pool()
        cleaned = args.strip().lstrip("-") if args else ""

        # Determine date range
        if cleaned in ("week", "7", "7d"):
            days = 7
            period_label = "Last 7 days"
        elif cleaned in ("month", "30", "30d"):
            days = 30
            period_label = "Last 30 days"
        else:
            days = 1
            period_label = "Today"

        date_filter = f"created_at >= CURRENT_DATE - INTERVAL '{days} days'" if days > 1 else "created_at >= CURRENT_DATE"

        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total,
                    COUNT(*) as message_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L1' THEN 1 ELSE 0 END), 0) as l1_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L2' THEN 1 ELSE 0 END), 0) as l2_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L3' THEN 1 ELSE 0 END), 0) as l3_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L2' THEN cost_usd ELSE 0 END), 0) as l2_cost,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L3' THEN cost_usd ELSE 0 END), 0) as l3_cost
                FROM public.bh_messages
                WHERE {date_filter}
                AND role = 'assistant'
            """)

        total = float(row["total"])
        lines = [
            f"**💰 AI Spend — {period_label}: ${total:.4f}**\n",
            f"- **L1** (free): {row['l1_count']} messages",
            f"- **L2** (Haiku): {row['l2_count']} messages — ${float(row['l2_cost']):.4f}",
            f"- **L3** (Sonnet): {row['l3_count']} messages — ${float(row['l3_cost']):.4f}",
            f"\nTotal messages: {row['message_count']}",
        ]

        # --breakdown: add per-model detail
        if cleaned in ("breakdown", "models", "detail"):
            async with pool.acquire() as conn2:
                model_rows = await conn2.fetch(f"""
                    SELECT model_used, COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost
                    FROM public.bh_messages
                    WHERE {date_filter} AND model_used IS NOT NULL AND cost_usd > 0
                    GROUP BY model_used ORDER BY cost DESC
                """)
            if model_rows:
                lines.append("\n**By model:**")
                for mr in model_rows:
                    lines.append(f"- {mr['model_used']}: {mr['calls']} calls — ${float(mr['cost']):.4f}")

        return RoutingResult(layer="L1", content="\n".join(lines))

    async def _try_pattern_match(self, message: str, context: RoutingContext) -> Optional[RoutingResult]:
        """Try to match message against regex/keyword patterns."""
        pool = get_pool()
        async with pool.acquire() as conn:
            patterns = await conn.fetch("""
                SELECT p.*, s.name as skill_name
                FROM public.bh_patterns p
                JOIN public.bh_skills s ON s.id = p.skill_id
                WHERE p.is_active = true AND s.is_active = true
                AND (p.workspace_id = $1 OR p.workspace_id IS NULL)
                ORDER BY p.priority ASC
            """, context.workspace_id)

        for pattern in patterns:
            try:
                match = re.search(pattern["rule"], message)
                if match:
                    # Extract parameters from named groups or template
                    pt = pattern["param_template"]
                    if isinstance(pt, str):
                        try:
                            pt = json.loads(pt)
                        except (json.JSONDecodeError, TypeError):
                            pt = {}
                    params = dict(pt) if isinstance(pt, dict) else {}
                    # Replace $N placeholders with capture groups
                    for key, val in list(params.items()):
                        if isinstance(val, str) and val.startswith("$"):
                            group_idx = int(val[1:]) if val[1:].isdigit() else 0
                            try:
                                params[key] = match.group(group_idx) or ""
                            except (IndexError, re.error):
                                params[key] = ""

                    result = await self.skill_executor.execute(
                        pattern["skill_name"], params, context.user_id, context.workspace_id
                    )
                    formatted = self.skill_executor.format_response(result)
                    return RoutingResult(
                        layer="L1", content=formatted, skill_name=pattern["skill_name"]
                    )
            except (SkillExecutionError, SkillPermissionError) as e:
                return RoutingResult(layer="L1", content=f"⚠️ {e}")
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern['rule']}")
                continue

        return None

    # --- Layer 2: Lightweight AI Classification ---

    # Read-only / information-retrieval skills that are safe to dispatch at lower confidence.
    # Write-path or side-effect skills stay at the default 0.75 threshold.
    # This is now DB-driven via bh_skills.is_read_only — cached per-request from the
    # skills list that _classify() already fetches.
    _read_only_skills_cache: Optional[set] = None

    @staticmethod
    def _is_read_only_skill(skill_name: str, skills: Optional[list] = None) -> bool:
        """Check if a skill is read-only (lower confidence threshold) from DB data."""
        if skills:
            for s in skills:
                if s.get("name") == skill_name:
                    return s.get("is_read_only", False)
        # Fallback: treat unknown skills as write-path (higher threshold = safer)
        return False

    async def _classify(self, message: str, context: RoutingContext) -> Optional[Dict[str, Any]]:
        """Call Haiku to classify intent. Returns {skill, confidence, params} or None."""
        skills = await self.skill_executor.get_workspace_skills(context.workspace_id)
        if not skills:
            return None

        # Build skills list for the prompt
        skills_list = "\n".join(
            f"- {s['name']}: {s['description']}"
            for s in skills
        )

        # Fetch the last 3 turns of conversation history so the classifier can
        # resolve follow-up questions (e.g. "what about later today?" after a
        # weather exchange). We keep this very small — it's only for reference,
        # not reasoning.
        history_block = ""
        if context.conversation_id:
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT role, content FROM public.bh_messages
                        WHERE conversation_id = $1
                        AND role IN ('user', 'assistant')
                        ORDER BY created_at DESC
                        LIMIT 6
                    """, context.conversation_id)
                if rows:
                    lines = []
                    for row in reversed(rows):
                        role_label = "User" if row["role"] == "user" else "Assistant"
                        # Truncate long assistant responses — we only need the gist
                        snippet = row["content"][:300].replace("\n", " ")
                        lines.append(f"{role_label}: {snippet}")
                    history_block = (
                        "Recent conversation (for context only):\n"
                        + "\n".join(lines)
                        + "\n\n"
                    )
            except Exception as e:
                logger.warning(f"Failed to load history for L2 classifier: {e}")

        prompt = self.CLASSIFICATION_PROMPT.format(
            skills_list=skills_list,
            history_block=history_block,
            message=message,
        )

        try:
            result = await asyncio.wait_for(
                self.model_provider.complete(
                    model=resolve_role("fast"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                ),
                timeout=10.0,
            )

            # Parse JSON response
            content = result.content.strip()
            # Handle potential markdown wrapping
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            classification = json.loads(content)
            logger.info(
                f"L2 classification: skill={classification.get('skill')}, "
                f"confidence={classification.get('confidence')}"
            )
            return classification

        except asyncio.TimeoutError:
            logger.warning("Layer 2 classification timed out (10s)")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Layer 2 classification parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Layer 2 classification failed: {e}")
            return None

    async def _execute_classified_skill(
        self, classification: Dict[str, Any], original_message: str, context: RoutingContext
    ) -> Optional[RoutingResult]:
        """Execute a skill identified by Layer 2 and format the response."""
        skill_name = classification["skill"]
        params = classification.get("params", {})
        if not isinstance(params, dict):
            params = {}

        # Defensive parameter normalization: Haiku sometimes uses synonym keys
        # ("query" instead of "question", "text" instead of "content"). For
        # ask-db specifically, the user's message IS the question, so fall
        # back to it whenever we don't have a usable `question` value. Same
        # idea for recall (single free-form query field).
        if skill_name == "ask-db":
            if not params.get("question"):
                params["question"] = (
                    params.pop("query", None)
                    or params.pop("q", None)
                    or original_message
                )
        elif skill_name == "recall":
            if not params.get("query"):
                params["query"] = (
                    params.pop("question", None)
                    or params.pop("q", None)
                    or original_message
                )

        try:
            # Execute the skill
            result = await self.skill_executor.execute(
                skill_name, params, context.user_id, context.workspace_id
            )

            # Format raw data into human-readable markdown
            raw_formatted = self.skill_executor.format_response(result)

            # If the skill returned pre-formatted _display content, check if it's
            # simple enough to use directly or complex enough to need formatting.
            has_display = (
                isinstance(result.raw_data, dict) and "_display" in result.raw_data
            )

            if has_display:
                display_content = raw_formatted
                # Check if display content contains broken markdown tables (pipe chars)
                # or is complex enough to need formatting. Pipe tables never render well
                # in the chat UI — always send them through Haiku for clean formatting.
                has_pipe_tables = "| --- |" in display_content or display_content.count("|") > 8
                is_complex = len(display_content) > 800
                
                if not has_pipe_tables and not is_complex:
                    content = display_content
                    total_input = 0
                    total_output = 0
                else:
                    # Complex data — Haiku formatting pass for clean mobile rendering
                    formatting_result = await self.model_provider.complete(
                        model=resolve_role("fast"),
                        messages=[{"role": "user", "content": (
                            f"You are formatting data for a mobile chat app. The user asked: \"{original_message}\"\n\n"
                            f"Raw response:\n{display_content[:5000]}\n\n"
                            "FORMAT RULES:\n"
                            "- Clean markdown that renders well on mobile\n"
                            "- For stats/tables, use monospace code blocks with aligned columns\n"
                            "- Keep all the data — don't drop any players or stats\n"
                            "- Use emoji for structure\n"
                            "- Never show raw pipe-table markdown\n\n"
                            "Reformat this:"
                        )}],
                        max_tokens=1500,
                    )
                    content = formatting_result.content
                    total_input = formatting_result.input_tokens
                    total_output = formatting_result.output_tokens
            else:
                # Wrap in conversational language via a short Haiku call
                formatting_result = await self.model_provider.complete(
                    model=resolve_role("fast"),
                    messages=[{"role": "user", "content": self.FORMATTING_PROMPT.format(
                        question=original_message,
                        raw_data=raw_formatted[:3000],  # Cap context size
                    )}],
                    max_tokens=500,
                )
                content = formatting_result.content
                total_input = formatting_result.input_tokens
                total_output = formatting_result.output_tokens

            return RoutingResult(
                layer="L2",
                content=content,
                model_used=resolve_role("fast"),
                input_tokens=total_input,
                output_tokens=total_output,
                cost_usd=self._calculate_cost(resolve_role("fast"), total_input, total_output),
                skill_name=skill_name,
            )

        except SkillPermissionError:
            # User doesn't have permission — escalate to L3 which will explain
            return None
        except SkillExecutionError as e:
            return RoutingResult(
                layer="L2",
                content=f"I tried to look that up but the {e.skill_name} skill had an issue. {e.detail or 'Try again?'}",
                model_used=resolve_role("fast"),
                skill_name=skill_name,
            )

    # --- Layer 3: Full Reasoning ---

    async def _layer3_reason(
        self, message: str, context: RoutingContext, ws_manager: WebSocketManager
    ) -> RoutingResult:
        """Full Sonnet reasoning with tool-use and streaming."""
        # Build system prompt with pinned context
        system = await self._build_system_prompt(context)

        # Load conversation history
        history = await self._get_context_messages(context)

        # Build tool schemas from workspace skills
        skills = await self.skill_executor.get_workspace_skills(context.workspace_id)
        tools = self.skill_executor.build_tool_schemas(skills) if skills else None

        # Always include Anthropic's native web search tool. It's a
        # server-side tool — Claude executes the search and ingests the
        # results in-loop, with no n8n round-trip. Useful for live data
        # like sports scores, current news, today's weather forecast,
        # or anything that wouldn't be in the model's training cutoff.
        # https://docs.claude.com/en/docs/build-with-claude/tool-use/web-search-tool
        web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }
        if tools is None:
            tools = [web_search_tool]
        else:
            tools = list(tools) + [web_search_tool]

        # Universal toolbox — HTTP executor, calculator, unit converter, API registry search.
        # These give Sonnet the same capabilities as the L2 tool router.
        try:
            from backend.services.tool_router import get_l3_tools
            toolbox_tools = get_l3_tools()
            tools = tools + toolbox_tools
        except Exception as e:
            logger.debug(f"Failed to load toolbox tools for L3: {e}")

        # Build user message (with vision if attachments)
        user_content = self._build_user_content(message, context.attachments)

        # Select model — use dynamic default from provider if workspace doesn't specify
        if context.force_model and context.force_model != "auto":
            model = context.force_model
        elif context.default_model and context.default_model != "auto":
            model = context.default_model
        else:
            model = self.model_provider.get_default_chat_model()

        messages = history + [{"role": "user", "content": user_content}]

        # Stream response, handling tool calls
        full_content = ""
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        max_tool_calls = 5

        while True:
            current_tool_calls: List[Dict[str, Any]] = []
            current_tool_json = ""
            current_tool_id = ""
            current_tool_name = ""

            async for chunk in self.model_provider.stream(
                model=model, messages=messages, max_tokens=4096,
                tools=tools, system=system,
            ):
                if chunk.type == "text_delta":
                    # Anthropic occasionally emits text_delta chunks with
                    # `data=None` — usually when a server-side tool
                    # (web_search) is interleaving citation/result blocks
                    # that the SDK normalizes away. Skip silently instead
                    # of letting the concat crash the stream.
                    if not chunk.data:
                        continue
                    full_content += chunk.data
                    await ws_manager.send_token(context.user_id, context.conversation_id, chunk.data)

                elif chunk.type == "tool_use_start":
                    current_tool_id = chunk.data["id"]
                    current_tool_name = chunk.data["name"]
                    current_tool_json = ""
                    logger.info(
                        f"L3 tool_use: name={current_tool_name} (user={context.user_id}, ws={context.workspace_id})"
                    )
                    await ws_manager.send_skill_status(
                        context.user_id, context.conversation_id, current_tool_name, "calling"
                    )

                elif chunk.type == "server_tool_use_start":
                    # Anthropic-side server tool (web_search). The API
                    # resolves it inline and continues streaming the
                    # final answer text — we don't add it to the
                    # caller-side tool_calls list. Just surface a status
                    # so the UI shows what's happening.
                    server_name = chunk.data.get("name", "web_search")
                    logger.info(
                        f"L3 server_tool_use: name={server_name} (user={context.user_id}, ws={context.workspace_id})"
                    )
                    await ws_manager.send_skill_status(
                        context.user_id, context.conversation_id, server_name, "calling"
                    )

                elif chunk.type == "tool_use_delta":
                    current_tool_json += chunk.data

                elif chunk.type == "message_stop":
                    # If we accumulated a tool call, finalize it
                    if current_tool_id and current_tool_name:
                        try:
                            args = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            args = {}
                        current_tool_calls.append({
                            "id": current_tool_id,
                            "name": current_tool_name,
                            "arguments": args,
                        })

                elif chunk.type == "usage":
                    total_input_tokens += chunk.data.get("input_tokens", 0)
                    total_output_tokens += chunk.data.get("output_tokens", 0)

            # If no tool calls, we're done
            if not current_tool_calls:
                break

            # Anthropic-native server tools (web_search etc.) execute on
            # Anthropic's side WITHIN the same streaming response: the
            # model emits the tool_use block for transparency, the API
            # resolves it, then the model continues generating using the
            # results — all before message_stop. So `full_content`
            # already holds the complete answer when we see one.
            #
            # If every recorded tool_call is a server-side tool, we
            # should NOT loop back for another API turn — the response
            # is finished. Only when there's at least one real (skill-
            # executor) tool call do we continue the multi-turn dance.
            SERVER_SIDE_TOOLS = {"web_search"}
            if all(tc["name"] in SERVER_SIDE_TOOLS for tc in current_tool_calls):
                for tc in current_tool_calls:
                    await ws_manager.send_skill_status(
                        context.user_id, context.conversation_id, tc["name"], "complete"
                    )
                break

            # Execute tool calls (up to max)
            if tool_call_count >= max_tool_calls:
                full_content += "\n\n*[Reached maximum tool calls for this message]*"
                break

            # Add assistant message with tool use to history
            assistant_content = []
            if full_content:
                assistant_content.append({"type": "text", "text": full_content})
            for tc in current_tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call and add results
            tool_results = []
            # Tools from the universal toolbox (handled by tool_router)
            TOOLBOX_TOOLS = {"http_request", "calculate", "convert_units", "search_api_registry", "knowledge_graph_query", "knowledge_graph_remember", "manage_list"}
            for tc in current_tool_calls:
                tool_call_count += 1
                # Skip server-side tools — already resolved by Anthropic
                if tc["name"] == "web_search":
                    continue

                # Universal toolbox tools — handle via tool_router
                if tc["name"] in TOOLBOX_TOOLS:
                    try:
                        from backend.services.tool_router import execute_l3_tool
                        result_text = await execute_l3_tool(tc["name"], tc["arguments"])
                        await ws_manager.send_skill_status(
                            context.user_id, context.conversation_id, tc["name"], "complete"
                        )
                    except Exception as e:
                        result_text = f"Error: {e}"
                        await ws_manager.send_skill_status(
                            context.user_id, context.conversation_id, tc["name"], "failed"
                        )
                else:
                    # Legacy skill executor path
                    try:
                        skill_result = await self.skill_executor.execute(
                            tc["name"], tc["arguments"], context.user_id, context.workspace_id
                        )
                        result_text = self.skill_executor.format_response(skill_result)
                        await ws_manager.send_skill_status(
                            context.user_id, context.conversation_id, tc["name"], "complete"
                        )
                    except (SkillExecutionError, SkillPermissionError) as e:
                        result_text = f"Error: {e}"
                        await ws_manager.send_skill_status(
                            context.user_id, context.conversation_id, tc["name"], "failed"
                        )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_text[:5000],  # Cap tool result size
                })

            messages.append({"role": "user", "content": tool_results})

            # Reset content for next iteration (model will continue after tool results)
            full_content = ""

        cost = self._calculate_cost(model, total_input_tokens, total_output_tokens)

        return RoutingResult(
            layer="L3",
            content=full_content,
            model_used=model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_usd=cost,
        )

    # --- Helpers ---

    async def _build_system_prompt(self, context: RoutingContext) -> str:
        """Assemble system prompt from workspace prompt + pinned context + tool guidance."""
        # Anchor the model to today's date so it stops answering from a
        # stale "I think it's mid-2025" perspective. The Anthropic models
        # don't get a current-time signal otherwise.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%A, %B %-d, %Y (UTC)")

        # Base instruction for all workspaces
        base = f"""You are BowersHub AI, a personal AI assistant for Michael's self-hosted data platform.

The current date is {today}. Use this — do not assume any other date. Your training data has a knowledge cutoff well before today; anything that could have changed since (sports scores, news, schedules, weather, prices, releases) is unreliable from memory and MUST be looked up.

CRITICAL: When the user asks about their personal data (router bits, tools, transactions, accounts, balances, inventory, files, recipes, etc.), you MUST use the available tools to query the actual data. NEVER say "I don't have access" or "I don't have detailed information" — that's wrong, you DO have access via the tools below. Call the appropriate tool and present the results.

CRITICAL: You have a `web_search` tool available. You MUST call it — not answer from memory — for any of the following:
- Sports scores, game times, standings, schedules ("Tigers score", "is the Yankees game on tonight")
- Today's or this week's news
- Weather forecasts beyond what the local weather skill returns
- Stock or crypto prices
- Current product availability, pricing, release dates
- Anything the user phrased in present tense about a fact that changes ("what's the latest...", "is X out yet", "what time does Y start")
- Any specific factual claim where being wrong would mislead the user
If you're unsure whether the answer changes over time, default to web_search. Do NOT preface searches with "let me check" — just call the tool. Don't web-search the user's own data (use the personal-data tools), and don't web-search things that genuinely don't change (math, definitions, history before 2020, syntax of programming languages).

When you describe what you're doing, speak in plain user-facing terms ("looking up your data", "checking your inventory", "querying the database", "checking the web") rather than naming specific tools. Tool names are an implementation detail.

For example:
- "tell me about my router bits" → call ask-db with {{"question": "list all router bits with their details"}}
- "what's my balance?" → call balances
- "how much did I spend on groceries?" → call ask-db
- "what tools do I have?" → call ask-db with an appropriate question

The ask-db tool is universal — it queries every schema you have access to (transactions, inventory, files, recipes, house data), not just finance.

For general knowledge questions ("who is X?", "what is Y?", "explain Z"), answer directly from your training — you don't need a tool. Be conversational and thorough.

When the user asks you to remember something but doesn't specify a topic, infer a reasonable topic slug from the content. For example:
- "I have two cats named Whiskers and Mittens" → topic: "personal/pets", fact: "Has two cats: Whiskers and Mittens"
- "My favorite coffee is Stumptown Hair Bender" → topic: "personal/preferences", fact: "Favorite coffee is Stumptown Hair Bender"
- "Manon prefers her steak medium-rare" → topic: "cooking/preferences", fact: "Manon prefers steak medium-rare"
Then call the remember tool with both the inferred topic and the fact. Don't ask the user to specify the topic — just pick a sensible one and tell them what you remembered."""

        parts = [base, "", context.system_prompt or ""]

        # Load pinned context
        pool = get_pool()
        async with pool.acquire() as conn:
            pinned = await conn.fetch("""
                SELECT title, content, cached_result, context_type
                FROM public.bh_pinned_context
                WHERE workspace_id = $1
                ORDER BY priority ASC
            """, context.workspace_id)

        for pin in pinned:
            if pin["context_type"] == "static" and pin["content"]:
                parts.append(f"\n--- {pin['title']} ---\n{pin['content']}")
            elif pin["context_type"] == "dynamic" and pin["cached_result"]:
                parts.append(f"\n--- {pin['title']} (live data) ---\n{pin['cached_result']}")

        return "\n".join(parts)

    async def _get_context_messages(self, context: RoutingContext) -> List[Dict[str, Any]]:
        """Load recent conversation messages as context within token budget."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT role, content, attachments FROM public.bh_messages
                WHERE conversation_id = $1
                AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT 20
            """, context.conversation_id)

        # Reverse to chronological, then trim to token budget
        messages = []
        token_count = 0
        for row in reversed(rows):
            # Rough estimate: 4 chars per token
            msg_tokens = len(row["content"]) // 4
            if token_count + msg_tokens > context.max_context_tokens:
                break
            messages.append({"role": row["role"], "content": row["content"]})
            token_count += msg_tokens

        return messages

    def _build_user_content(self, message: str, attachments: List[Dict[str, Any]]) -> Any:
        """Build user message content, including vision blocks for images."""
        if not attachments:
            return message

        # Build multi-part content with text + images
        content = [{"type": "text", "text": message}]
        for att in attachments:
            if att.get("mime", "").startswith("image/") and att.get("base64"):
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att["mime"],
                        "data": att["base64"],
                    }
                })
        return content

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD. Delegates to the single catalog-reading cost function
        (DB price by exact key, non-zero heuristic floor on a miss) — the heuristic no
        longer lives here. All three call sites route through this one home (R3.3)."""
        from backend.services.model_catalog import cost_for
        return cost_for(model, input_tokens, output_tokens)
