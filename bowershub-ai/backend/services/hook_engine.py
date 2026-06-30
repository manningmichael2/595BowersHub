"""
Hook Engine: event-driven automation system.
Hooks are workspace-scoped and fire on defined events with optional conditions.
"""

import asyncio
from backend.services.model_catalog import resolve_role
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from backend.http_client import get_http_client
from apscheduler.triggers.base import BaseTrigger
from croniter import croniter

from backend.config import Config
from backend.database import get_pool
from backend.services.model_provider import ModelProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Pushover message body limit for scheduled-prompt delivery (R11.6).
#: This is enforced by `pushover_payload`; the Pushover API itself caps at
#: 1024 chars, so 1000 leaves room for "…" plus a small safety margin.
PUSHOVER_MESSAGE_LIMIT = 1000

#: Public deep-link host used in scheduled-prompt Pushover payloads.
#: A fixed string for now — the platform only has one public URL. If the
#: deployment ever moves we can lift this into ``Config``; for the MVP it
#: matches the URL from `595bowershub-project.md`.
WORKSPACE_DEEPLINK_BASE = "https://595bowershub.tailc4d58a.ts.net/workspace"

#: One microsecond — used by ``CroniterTrigger`` to step back from
#: ``now`` when there is no previous fire so a fire exactly at ``now``
#: still qualifies. Module-scope so the trigger doesn't reconstruct a
#: ``timedelta`` on every fire-time computation.
_ONE_MICROSECOND = timedelta(microseconds=1)


# ---------------------------------------------------------------------------
# Helpers (module-level — importable from tests, see Property 12 / §9.2)
# ---------------------------------------------------------------------------


def pushover_payload(response_text: Any, ws: Any) -> Dict[str, str]:
    """Build a Pushover payload for a scheduled-prompt delivery.

    The body is the AI response truncated to ``PUSHOVER_MESSAGE_LIMIT``
    characters (R11.6). When truncation actually drops bytes, the last
    character of the truncated slice is replaced with ``…`` so users can
    see at a glance that the message was cut.

    The ``url`` is the deep-link to the workspace (``/workspace/<id>``)
    so users can tap the notification and land on the workspace where
    the full response was generated. Tapping a Pushover notification on
    Android with a ``url`` field opens it in the browser (or the PWA if
    installed).

    Parameters
    ----------
    response_text :
        The AI assistant's full response body. Anything non-string is
        coerced via ``str(...)`` so the helper never raises on odd input.
    ws :
        Either a workspace dict (with an ``id`` key) or an object with
        an ``id`` attribute. The ``id`` is appended to the deep-link.

    Returns
    -------
    dict
        ``{"message": <truncated>, "url": <workspace_link>}``.
    """
    if response_text is None:
        text = ""
    elif isinstance(response_text, str):
        text = response_text
    else:
        text = str(response_text)

    if len(text) > PUSHOVER_MESSAGE_LIMIT:
        # Reserve one character for the ellipsis so total length stays
        # at PUSHOVER_MESSAGE_LIMIT.
        truncated = text[: PUSHOVER_MESSAGE_LIMIT - 1] + "…"
    else:
        truncated = text

    if isinstance(ws, dict):
        ws_id = ws.get("id")
    else:
        ws_id = getattr(ws, "id", None)

    url = f"{WORKSPACE_DEEPLINK_BASE}/{ws_id}"

    return {"message": truncated, "url": url}


# ---------------------------------------------------------------------------
# CroniterTrigger
# ---------------------------------------------------------------------------


class CroniterTrigger(BaseTrigger):
    """APScheduler trigger that delegates fire-time computation to croniter.

    APScheduler's built-in ``CronTrigger.from_crontab`` parses the
    day-of-week field using Python's ``datetime.weekday()`` convention
    (Mon=0..Sun=6), but the rest of the platform — notably
    ``services.scheduled_prompts.validate_cron`` — uses ``croniter``,
    which follows the standard Unix cron convention (Sun=0..Sat=6).
    The two disagree on every day-of-week constraint, so a hook
    validated against croniter could fire on the wrong days when
    dispatched by APScheduler.

    Examples of the disagreement:

        ``0 0 * * 0``        → croniter: every Sunday at midnight
                              APScheduler from_crontab: every Monday
        ``30 14 * * 1-5``    → croniter: weekdays Mon-Fri at 14:30
                              APScheduler from_crontab: Tue-Sat at 14:30

    This trigger fixes the disagreement by routing fire-time computation
    through croniter for the dispatch path too. The validator and the
    scheduler now share the same engine, so a hook fires exactly when
    the cron expression — interpreted by croniter — says it should.

    APScheduler's :meth:`BaseTrigger.get_next_fire_time` contract:

        - If ``previous_fire_time`` is provided, return the next fire
          datetime strictly greater than it.
        - Otherwise, return the next fire datetime at or after ``now``.
        - Return ``None`` if no such datetime exists.

    Croniter's ``get_next`` returns the next fire strictly greater than
    its anchor. We anchor at ``previous_fire_time`` when present;
    otherwise we step back one microsecond before ``now`` so a fire
    exactly at ``now`` (e.g. ``* * * * *`` when ``now`` is on the
    minute boundary) is emitted.
    """

    __slots__ = ("_expr", "_tz")

    def __init__(self, expr: str, tz: Optional[Any] = None) -> None:
        self._expr = expr
        self._tz = tz or timezone.utc

    def get_next_fire_time(
        self,
        previous_fire_time: Optional[datetime],
        now: datetime,
    ) -> Optional[datetime]:
        if previous_fire_time is not None:
            anchor = previous_fire_time
        else:
            # croniter.get_next returns "fire > anchor"; step back one
            # microsecond so a fire exactly at ``now`` qualifies (the
            # APScheduler contract for previous=None is "fire >= now").
            anchor = now - _ONE_MICROSECOND

        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=self._tz)

        it = croniter(self._expr, anchor)
        next_fire = it.get_next(datetime)
        if next_fire.tzinfo is None:
            next_fire = next_fire.replace(tzinfo=self._tz)
        return next_fire

    def __getstate__(self) -> dict:
        return {"expr": self._expr, "tz": self._tz}

    def __setstate__(self, state: dict) -> None:
        self._expr = state["expr"]
        self._tz = state.get("tz", timezone.utc)

    def __repr__(self) -> str:
        return f"CroniterTrigger(expr={self._expr!r}, tz={self._tz!r})"


class HookEventContext:
    """Context for a hook event."""
    def __init__(
        self,
        workspace_id: int,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        user_message: Optional[str] = None,
        assistant_message: Optional[str] = None,
        skill_name: Optional[str] = None,
        file_path: Optional[str] = None,
        skip_capture: bool = False,
        is_scheduled: bool = False,
        capture_visibility: str = "private",
    ):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.user_message = user_message
        self.assistant_message = assistant_message
        self.skill_name = skill_name
        self.file_path = file_path
        # Visibility the Context Harvester applies to facts captured from this
        # exchange: 'private' (default — scoped to the author) or 'shared', set
        # from the chat-bar Personal/Shared toggle (websocket capture_visibility).
        self.capture_visibility = capture_visibility
        # Set to True for scheduled-prompt invocations so context_capture
        # is suppressed (R11.4) and per-user streaming notifications are
        # not emitted to other connected sessions (design §"System-prompt
        # only invocation context").
        self.skip_capture = skip_capture
        self.is_scheduled = is_scheduled


class HookEngine:
    """
    Event-driven automation system.
    Hooks are workspace-scoped and fire on defined events with optional conditions.
    """

    def __init__(self, model_provider: ModelProvider, config: Config):
        self.model_provider = model_provider
        self.config = config
        self._running_schedules: Dict[int, bool] = {}  # hook_id → is_running

    async def startup(self):
        """Load schedule hooks and start their cron jobs."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self._scheduler = AsyncIOScheduler()

            pool = get_pool()
            async with pool.acquire() as conn:
                hooks = await conn.fetch("""
                    SELECT * FROM public.bh_hooks
                    WHERE event_type = 'schedule' AND is_enabled = true
                """)

            for hook in hooks:
                if hook["cron_expression"]:
                    try:
                        # Use CroniterTrigger so the dispatch path agrees
                        # with services.scheduled_prompts.validate_cron
                        # (croniter, Sun=0..Sat=6) on day-of-week. See the
                        # CroniterTrigger docstring for why APScheduler's
                        # built-in CronTrigger.from_crontab is wrong here.
                        trigger = CroniterTrigger(hook["cron_expression"], tz=timezone.utc)
                        self._scheduler.add_job(
                            self._execute_scheduled_hook,
                            trigger,
                            args=[dict(hook)],
                            id=f"hook_{hook['id']}",
                            replace_existing=True,
                        )
                        logger.info(f"  Scheduled hook '{hook['name']}' ({hook['cron_expression']})")
                    except Exception as e:
                        logger.warning(f"  Failed to schedule hook '{hook['name']}': {e}")

            self._scheduler.start()
            logger.info(f"Hook engine started ({len(hooks)} schedule hooks)")

        except ImportError:
            logger.warning("APScheduler not available — schedule hooks disabled")
        except Exception as e:
            logger.warning(f"Hook engine startup failed: {e}")

    async def shutdown(self):
        """Stop the scheduler."""
        if hasattr(self, "_scheduler"):
            self._scheduler.shutdown(wait=False)

    async def dispatch(self, event_type: str, context: HookEventContext):
        """
        Called by the application when an event occurs.
        Finds matching hooks and executes them as background tasks.
        """
        pool = get_pool()
        async with pool.acquire() as conn:
            hooks = await conn.fetch("""
                SELECT * FROM public.bh_hooks
                WHERE workspace_id = $1 AND event_type = $2 AND is_enabled = true
            """, context.workspace_id, event_type)

        for hook in hooks:
            hook_dict = dict(hook)
            if self._check_conditions(hook_dict, context):
                # Fire and forget — don't block the message flow
                asyncio.create_task(self._execute_hook(hook_dict, context))

    def _check_conditions(self, hook: dict, context: HookEventContext) -> bool:
        """Check if hook conditions are met."""
        conditions = hook.get("conditions") or {}
        if not conditions:
            return True

        # Keyword condition
        keywords = conditions.get("keywords", [])
        if keywords and context.user_message:
            msg_lower = context.user_message.lower()
            if not any(kw.lower() in msg_lower for kw in keywords):
                return False

        # User condition
        users = conditions.get("users", [])
        if users and context.user_id not in users:
            return False

        # Skill condition
        skills = conditions.get("skills", [])
        if skills and context.skill_name not in skills:
            return False

        # Time window condition
        hours = conditions.get("hours")
        if hours:
            now_hour = datetime.now().hour
            start = hours.get("start", 0)
            end = hours.get("end", 24)
            if not (start <= now_hour < end):
                return False

        return True

    async def _execute_hook(self, hook: dict, context: Optional[HookEventContext] = None):
        """Execute a hook action and log the result."""
        hook_id = hook["id"]

        try:
            action_type = hook["action_type"]
            raw_config = hook.get("action_config") or {}
            # asyncpg with the JSON codec returns dicts; legacy fixtures
            # or unconfigured pools may hand back a JSON string. Normalize.
            if isinstance(raw_config, str):
                try:
                    raw_config = json.loads(raw_config)
                except json.JSONDecodeError:
                    raw_config = {}
            # Defensive copy + inject hook_id so action handlers (notably
            # ``_deliver_pin``) can record back-references without
            # re-querying.
            action_config = dict(raw_config) if isinstance(raw_config, dict) else {}
            action_config.setdefault("hook_id", hook_id)

            if action_type == "call_webhook":
                result = await self._action_call_webhook(action_config, context)
            elif action_type == "call_ai":
                result = await self._action_call_ai(action_config, context)
            elif action_type == "capture_context":
                result = await self._action_capture_context(context)
            elif action_type == "notify":
                result = await self._action_notify(action_config, context)
            else:
                result = {"error": f"Unknown action type: {action_type}"}

            await self._log_execution(hook_id, hook["event_type"], context, result, success=True)

        except Exception as e:
            logger.error(f"Hook '{hook.get('name')}' execution failed: {e}")
            await self._log_execution(hook_id, hook["event_type"], context, None, success=False, error=str(e))

    async def _execute_scheduled_hook(self, hook: dict):
        """Execute a scheduled hook (called by APScheduler)."""
        hook_id = hook["id"]

        # Skip if already running (idempotency)
        if self._running_schedules.get(hook_id):
            logger.debug(f"Skipping hook {hook_id} — already running")
            return

        self._running_schedules[hook_id] = True
        try:
            # Synthetic context for scheduled-prompt firing. ``is_scheduled``
            # tags the run so context_capture and per-user streaming
            # notifications stay quiet (R11.4 + design §"System-prompt
            # only invocation context").
            context = HookEventContext(
                workspace_id=hook["workspace_id"],
                user_id=hook.get("created_by"),
                skip_capture=True,
                is_scheduled=True,
            )
            await self._execute_hook(hook, context)
        finally:
            self._running_schedules[hook_id] = False

    # --- Hook Actions ---

    async def _action_call_webhook(self, config: dict, context: Optional[HookEventContext]) -> dict:
        """Call an external webhook."""
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        body_template = config.get("body_template", {})

        # Resolve template variables
        body = json.loads(json.dumps(body_template))  # Deep copy

        client = get_http_client()
        if method == "GET":
            resp = await client.get(url, timeout=30.0)
        else:
            resp = await client.post(url, json=body, timeout=30.0)

        return {"status_code": resp.status_code, "body": resp.text[:500]}

    async def _action_call_ai(self, config: dict, context: Optional[HookEventContext]) -> dict:
        """Send a prompt to an AI model.

        For scheduled-prompt hooks (R11.4), ``config`` carries a
        ``delivery_method`` ∈ {``pin``, ``pushover``}. The AI response is
        then routed to the configured destination:

        - ``pin``: insert the response as a system message on the
          workspace's primary conversation (R11.5).
        - ``pushover``: send the response as a Pushover notification,
          truncated to 1000 chars with a deep-link to the workspace
          (R11.6).

        On AI invocation failure the exception bubbles up to
        ``_execute_hook``, which writes a ``bh_hook_log`` row with
        ``success=false`` and the error message; we deliberately do not
        retry (R11.12).
        """
        prompt = config.get("prompt", "")
        model = config.get("model") or resolve_role("fast")

        result = await self.model_provider.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )

        delivery_method = config.get("delivery_method")
        delivery_result: Optional[dict] = None
        if delivery_method == "pin":
            delivery_result = await self._deliver_pin(result.content, config, context)
        elif delivery_method == "pushover":
            delivery_result = await self._deliver_pushover(result.content, config, context)

        out: Dict[str, Any] = {
            "content": result.content,
            "tokens": result.input_tokens + result.output_tokens,
        }
        if delivery_method:
            out["delivery_method"] = delivery_method
        if delivery_result is not None:
            out["delivery"] = delivery_result
        return out

    # --- Scheduled-prompt delivery helpers (R11.5, R11.6) ---

    async def _deliver_pin(
        self,
        response_text: str,
        config: dict,
        context: Optional[HookEventContext],
    ) -> dict:
        """Pin the AI response as a system message in the workspace's
        primary conversation (R11.5).

        "Primary conversation" for a workspace is defined here as a
        conversation owned by the hook's creator with the title
        "Scheduled Prompts" — created on first delivery if it doesn't
        exist. This mirrors the briefing service's pattern of using a
        named conversation as a per-feature inbox.
        """
        workspace_id = config.get("workspace_id")
        if workspace_id is None and context is not None:
            workspace_id = context.workspace_id
        if workspace_id is None:
            raise ValueError("pin delivery requires workspace_id")

        # Owner of the pinned message: prefer the hook's invoker (set on
        # the synthetic context when scheduled or when run_now is called);
        # fall back to the workspace's first owner.
        user_id = context.user_id if context else None

        pool = get_pool()
        async with pool.acquire() as conn:
            if user_id is None:
                row = await conn.fetchrow(
                    """
                    SELECT user_id FROM public.bh_workspace_users
                    WHERE workspace_id = $1
                    ORDER BY (role = 'owner') DESC, added_at ASC
                    LIMIT 1
                    """,
                    workspace_id,
                )
                if row is None:
                    raise ValueError(
                        f"workspace {workspace_id} has no users — cannot pin"
                    )
                user_id = row["user_id"]

            conv = await conn.fetchrow(
                """
                SELECT id FROM public.bh_conversations
                WHERE workspace_id = $1 AND user_id = $2
                  AND title = 'Scheduled Prompts'
                  AND is_archived = false
                ORDER BY created_at DESC LIMIT 1
                """,
                workspace_id,
                user_id,
            )
            if conv is None:
                conv = await conn.fetchrow(
                    """
                    INSERT INTO public.bh_conversations (workspace_id, user_id, title)
                    VALUES ($1, $2, 'Scheduled Prompts') RETURNING id
                    """,
                    workspace_id,
                    user_id,
                )

            metadata = {
                "pinned": True,
                "scheduled_prompt_id": config.get("hook_id"),
            }
            msg = await conn.fetchrow(
                """
                INSERT INTO public.bh_messages
                    (conversation_id, role, content, metadata)
                VALUES ($1, 'system', $2, $3::jsonb)
                RETURNING id
                """,
                conv["id"],
                response_text,
                json.dumps(metadata),
            )
            await conn.execute(
                "UPDATE public.bh_conversations SET updated_at = now() WHERE id = $1",
                conv["id"],
            )

        return {
            "method": "pin",
            "conversation_id": conv["id"],
            "message_id": msg["id"],
        }

    async def _deliver_pushover(
        self,
        response_text: str,
        config: dict,
        context: Optional[HookEventContext],
    ) -> dict:
        """Send the AI response as a Pushover notification (R11.6).

        Truncation + URL building are done by the module-level
        ``pushover_payload`` helper so the property test in §9.2 can
        target it directly without standing up the full hook engine.
        """
        workspace_id = config.get("workspace_id")
        if workspace_id is None and context is not None:
            workspace_id = context.workspace_id
        if workspace_id is None:
            raise ValueError("pushover delivery requires workspace_id")

        ws_name: Optional[str] = None
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name FROM public.bh_workspaces WHERE id = $1",
                workspace_id,
            )
            if row is not None:
                ws_name = row["name"]
                ws_dict = {"id": row["id"]}
            else:
                ws_dict = {"id": workspace_id}

        payload = pushover_payload(response_text, ws_dict)
        title = f"Scheduled prompt: {ws_name}" if ws_name else "Scheduled prompt"

        sent = False
        if self.config.pushover_enabled:
            from backend.services.notifications import NotificationService

            notifier = NotificationService(self.config)
            sent = await notifier.send_pushover(
                title=title,
                message=payload["message"],
                url=payload["url"],
                url_title="Open workspace",
            )

        return {
            "method": "pushover",
            "sent": sent,
            "url": payload["url"],
            "message_length": len(payload["message"]),
        }

    async def _action_capture_context(self, context: Optional[HookEventContext]) -> dict:
        """Run context capture on the current exchange."""
        if not context or not context.user_message or not context.assistant_message:
            return {"skipped": True, "reason": "No message content"}

        from backend.services.context_capture import ContextCapture
        capture = ContextCapture(self.model_provider, self.config)

        # Get workspace name + the capturing user's display name (household
        # attribution — facts record from whom they were captured; NULL for
        # system/automated runs with no associated user).
        pool = get_pool()
        async with pool.acquire() as conn:
            ws = await conn.fetchrow(
                "SELECT name FROM public.bh_workspaces WHERE id = $1",
                context.workspace_id,
            )
            captured_by = None
            if context.user_id:
                u = await conn.fetchrow(
                    "SELECT display_name, settings_json FROM public.bh_users WHERE id = $1",
                    context.user_id,
                )
                if u:
                    captured_by = u["display_name"]
                    # Per-user privacy opt-out (Settings → Context Capture).
                    settings = u["settings_json"] or {}
                    if settings.get("context_capture_disabled"):
                        return {"skipped": True, "reason": "User opted out of context capture"}

        workspace_name = ws["name"] if ws else "general"
        facts = await capture.evaluate(
            context.user_message, context.assistant_message, workspace_name,
            captured_by=captured_by, user_id=context.user_id,
            visibility=context.capture_visibility,
        )
        return {"facts_captured": len(facts), "facts": [f.statement for f in facts]}

    async def _action_notify(self, config: dict, context: Optional[HookEventContext]) -> dict:
        """Send a notification (Pushover)."""
        title = config.get("title", "BowersHub AI")
        message = config.get("message_template", "Hook triggered")

        if self.config.pushover_enabled:
            client = get_http_client()
            await client.post("https://api.pushover.net/1/messages.json", data={
                "token": self.config.PUSHOVER_API_TOKEN,
                "user": self.config.PUSHOVER_USER_KEY,
                "title": title,
                "message": message,
            })
            return {"sent": True, "method": "pushover"}
        return {"sent": False, "reason": "Pushover not configured"}

    # --- Logging ---

    async def _log_execution(
        self, hook_id: int, event_type: str,
        context: Optional[HookEventContext],
        result: Any, success: bool, error: str = None
    ):
        """Log hook execution to bh_hook_log."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO public.bh_hook_log
                        (hook_id, event_type, trigger_data, action_result, success, error_message)
                    VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                """, hook_id, event_type,
                    json.dumps({"user_id": context.user_id if context else None}),
                    json.dumps(result) if result else None,
                    success, error)
        except Exception as e:
            logger.warning(f"Failed to log hook execution: {e}")
