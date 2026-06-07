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

    CLASSIFICATION_PROMPT = """You are a message classifier for a personal AI assistant. Given a user message and a list of available skills, determine if the message can be FULLY answered by calling exactly ONE skill with specific parameters.

Available skills:
{skills_list}

Respond with ONLY valid JSON (no markdown, no explanation):
{{"skill": "<skill_name or null>", "confidence": <0.0-1.0>, "params": {{<extracted parameters>}}}}

IMPORTANT RULES:
- Return a skill ONLY if the message is a simple, direct request that one skill can fully handle (e.g., "what's my balance?" → balances skill)
- Return {{"skill": null, "confidence": 0.0, "params": {{}}}} for ANY of these:
  - General knowledge questions ("who is X?", "what is Y?", "explain Z")
  - Questions requiring analysis, comparison, or reasoning
  - Questions that need multiple data sources
  - Conversational messages, opinions, or open-ended questions
  - Anything you're not 100% sure maps to exactly one skill
- For "recall" skill: only use if the user explicitly asks to search their knowledge base or asks "what do I know about X"
- For "ask-db" skill: only use for specific data lookups that are clearly one query ("how much did I spend on X", "show transactions from Y", "list my router bits")
- When in doubt, return null — it's better to escalate to the full reasoning model than to give a bad answer

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
            classification = await self._classify(message, context)
            if classification and classification.get("skill") and classification.get("confidence", 0) > 0.75:
                skill_result = await self._execute_classified_skill(
                    classification, message, context
                )
                if skill_result:
                    return skill_result
        except Exception as e:
            logger.warning(f"Layer 2 classification failed, escalating to L3: {e}")

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
            return None

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
            return await self._handle_cost_command(context)

        elif command == "/files":
            return await self._handle_files_command(args)

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

    async def _handle_cost_command(self, context: RoutingContext) -> RoutingResult:
        """Handle /cost — show today's AI spend breakdown."""
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total,
                    COUNT(*) as message_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L1' THEN 1 ELSE 0 END), 0) as l1_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L2' THEN 1 ELSE 0 END), 0) as l2_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L3' THEN 1 ELSE 0 END), 0) as l3_count,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L2' THEN cost_usd ELSE 0 END), 0) as l2_cost,
                    COALESCE(SUM(CASE WHEN routing_layer = 'L3' THEN cost_usd ELSE 0 END), 0) as l3_cost
                FROM public.bh_messages
                WHERE created_at >= CURRENT_DATE
                AND role = 'assistant'
            """)

        total = float(row["total"])
        lines = [
            f"**Today's AI spend: ${total:.4f}**\n",
            f"- **L1** (free): {row['l1_count']} messages",
            f"- **L2** (Haiku): {row['l2_count']} messages — ${float(row['l2_cost']):.4f}",
            f"- **L3** (Sonnet): {row['l3_count']} messages — ${float(row['l3_cost']):.4f}",
            f"\nTotal messages today: {row['message_count']}",
        ]
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

        prompt = self.CLASSIFICATION_PROMPT.format(
            skills_list=skills_list,
            message=message,
        )

        try:
            result = await asyncio.wait_for(
                self.model_provider.complete(
                    model="claude-haiku-4-5-20251001",
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

            # Format raw data into natural language via a short Haiku call
            raw_formatted = self.skill_executor.format_response(result)

            # Wrap in conversational language
            formatting_result = await self.model_provider.complete(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": self.FORMATTING_PROMPT.format(
                    question=original_message,
                    raw_data=raw_formatted[:3000],  # Cap context size
                )}],
                max_tokens=500,
            )

            total_input = formatting_result.input_tokens
            total_output = formatting_result.output_tokens

            return RoutingResult(
                layer="L2",
                content=formatting_result.content,
                model_used="claude-haiku-4-5-20251001",
                input_tokens=total_input,
                output_tokens=total_output,
                cost_usd=self._calculate_cost("claude-haiku-4-5-20251001", total_input, total_output),
                skill_name=skill_name,
            )

        except SkillPermissionError:
            # User doesn't have permission — escalate to L3 which will explain
            return None
        except SkillExecutionError as e:
            return RoutingResult(
                layer="L2",
                content=f"I tried to look that up but the {e.skill_name} skill had an issue. {e.detail or 'Try again?'}",
                model_used="claude-haiku-4-5-20251001",
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
            for tc in current_tool_calls:
                tool_call_count += 1
                # Skip server-side tools — they're already resolved by
                # Anthropic. The all-server-side short-circuit above
                # handled the common case, but a mixed batch (web_search
                # alongside a regular skill call) reaches this loop, and
                # we still need to avoid running web_search through
                # skill_executor.
                if tc["name"] == "web_search":
                    continue
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
        """Calculate cost in USD based on model rates."""
        # Heuristic pricing based on model name
        lower = model.lower()
        if "haiku" in lower:
            input_rate, output_rate = 0.80, 4.00
        elif "opus" in lower:
            input_rate, output_rate = 15.00, 75.00
        elif "sonnet" in lower:
            input_rate, output_rate = 3.00, 15.00
        else:
            input_rate, output_rate = 3.00, 15.00  # Default to Sonnet pricing
        cost = (input_tokens * input_rate / 1_000_000) + (output_tokens * output_rate / 1_000_000)
        return round(cost, 6)
