"""
Scheduled Prompts Service.

A thin CRUD facade over ``bh_hooks`` rows where ``event_type='schedule'``
and ``action_type='call_ai'``. The frontend treats these rows as
"scheduled prompts" with a name, a cron expression, a prompt template,
and a delivery method (``pin`` or ``pushover``); this module owns the
translation between that user-facing model and the underlying hook row.

The cron firing path itself is owned by ``hook_engine`` (APScheduler);
this module never duplicates that logic. ``run_now`` invokes
``hook_engine._execute_hook`` directly so a manual run goes through
exactly the same delivery path as a scheduled run.

Public surface (used by ``backend/routers/scheduled_prompts.py``):

    validate_cron(expr)                 -> bool
    list_for_user(user, workspace_id?)  -> list[dict]
    create(user, payload)               -> dict
    update(user, hook_id, partial)      -> dict
    delete(user, hook_id)               -> None
    toggle(user, hook_id, enabled)      -> dict
    run_now(user, hook_id, hook_engine) -> dict
    get_log(user, hook_id, limit=10)    -> list[dict]

Errors:

    CronInvalid                         (HTTP 400)
    NotFound                            (HTTP 404)
    Forbidden                           (HTTP 403)

Cron-human translation
----------------------
The task description originally specified ``cronstrue``, which is the
JavaScript/npm package. The Python equivalent is ``cron-descriptor``;
when present it is used for ``cron_human``. If the package is not
installed (or fails to translate a particular expression), we fall back
to the raw cron expression rather than raising — the human-readable
form is purely cosmetic and must not break list-view responses.

Implementation surface for tests in ``backend/tests/test_scheduled_prompts.py``
and the Property 10 test ``backend/tests/properties/test_cron_validator.py``.
"""

from __future__ import annotations
from backend.services.model_catalog import resolve_role

import json
import logging
from datetime import datetime
from typing import Any, Optional

from croniter import croniter

from backend.database import get_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default model for scheduled prompts. Matches the existing ``call_ai`` hook
#: action default in ``hook_engine._action_call_ai`` (Haiku — cheap enough
#: for daily/weekly proactive tasks).

#: Allowed delivery methods. ``pin`` posts the result as a pinned system
#: message in the workspace's primary conversation (R11.5); ``pushover``
#: sends a push notification truncated to 1000 chars (R11.6).
ALLOWED_DELIVERY_METHODS = frozenset({"pin", "pushover"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ScheduledPromptError(Exception):
    """Base class for service-level errors. Routers translate these to
    HTTP responses; the service layer never raises ``HTTPException``
    directly so it can be unit-tested without a FastAPI request."""


class CronInvalid(ScheduledPromptError):
    """Cron expression failed ``validate_cron``. HTTP 400."""

    def __init__(self, expr: str) -> None:
        self.expr = expr
        super().__init__(f"invalid cron expression: {expr!r}")


class NotFound(ScheduledPromptError):
    """No row matched the given ``hook_id``. HTTP 404."""


class Forbidden(ScheduledPromptError):
    """Caller lacks access to the row's workspace. HTTP 403."""


class InvalidPayload(ScheduledPromptError):
    """Payload missing a required field or carrying a disallowed value.
    HTTP 400."""


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------


def validate_cron(expr: Any) -> bool:
    """Return True iff ``expr`` is a valid cron expression.

    Thin wrapper around ``croniter.croniter.is_valid``. ``is_valid`` raises
    on ``None``/non-string input; the contract documented in R11.11 is that
    this helper *never raises*, so any exception is treated as "not valid".
    """
    try:
        return bool(croniter.is_valid(expr))
    except Exception:
        return False


def _human_describe(expr: str) -> str:
    """Translate a cron expression to a human-readable string.

    Uses ``cron-descriptor`` when available; otherwise returns the raw
    expression. The fallback is intentional — ``cron_human`` is a purely
    cosmetic field on list responses, and a missing optional dependency
    must not break the API.
    """
    try:
        from cron_descriptor import ExpressionDescriptor  # type: ignore[import-not-found]
    except Exception:
        return expr

    try:
        return ExpressionDescriptor(expr, throw_exception_on_parse_error=False).get_description()
    except Exception:
        return expr


# ---------------------------------------------------------------------------
# Workspace-access helpers
# ---------------------------------------------------------------------------


async def _accessible_workspace_ids(conn, user: dict) -> Optional[list[int]]:
    """Return the workspace IDs the user can access, or ``None`` for an
    admin (meaning "no scoping needed — they can see everything").

    Mirrors the convention used in ``backend/services/search.py`` so
    callers can share the same query patterns.
    """
    if user.get("role") == "admin":
        return None
    rows = await conn.fetch(
        "SELECT workspace_id FROM public.bh_workspace_users WHERE user_id = $1",
        user["id"],
    )
    return [r["workspace_id"] for r in rows]


async def _check_workspace_access(conn, user: dict, workspace_id: int) -> None:
    """Raise ``Forbidden`` if the user can't access ``workspace_id``."""
    if user.get("role") == "admin":
        return
    row = await conn.fetchrow(
        """
        SELECT 1 FROM public.bh_workspace_users
        WHERE user_id = $1 AND workspace_id = $2
        """,
        user["id"],
        workspace_id,
    )
    if row is None:
        raise Forbidden(f"workspace {workspace_id} not accessible to user {user['id']}")


async def _load_hook_or_403(conn, user: dict, hook_id: int) -> dict:
    """Fetch the hook row, enforce scope, and return it as a plain dict.

    Raises:
        NotFound: hook_id does not exist OR is not a scheduled-prompt hook
        Forbidden: caller lacks workspace access
    """
    row = await conn.fetchrow(
        """
        SELECT * FROM public.bh_hooks
        WHERE id = $1
          AND event_type = 'schedule'
          AND action_type = 'call_ai'
        """,
        hook_id,
    )
    if row is None:
        raise NotFound(f"scheduled prompt {hook_id} not found")
    hook = dict(row)
    await _check_workspace_access(conn, user, hook["workspace_id"])
    return hook


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _coerce_action_config(value: Any) -> dict:
    """``action_config`` is stored as JSONB; the asyncpg JSON codec we
    register decodes it to a dict, but legacy rows or test fixtures may
    still serve a JSON string. Tolerate both."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _serialize(hook: dict, *, last_run: Optional[datetime], last_status: Optional[str]) -> dict:
    """Render a hook row as the public scheduled-prompt shape."""
    cfg = _coerce_action_config(hook.get("action_config"))
    cron_expr = hook.get("cron_expression") or ""
    return {
        "id": hook["id"],
        "name": hook["name"],
        "workspace_id": hook["workspace_id"],
        "prompt_template": cfg.get("prompt", ""),
        "cron_expression": cron_expr,
        "cron_human": _human_describe(cron_expr) if cron_expr else "",
        "delivery_method": cfg.get("delivery_method", "pin"),
        "is_enabled": bool(hook.get("is_enabled")),
        "last_run": last_run.isoformat() if last_run else None,
        "last_status": last_status,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def list_for_user(user: dict, workspace_id: Optional[int] = None) -> list[dict]:
    """List scheduled prompts visible to ``user``.

    Joins ``bh_hooks`` against the latest ``bh_hook_log`` row per hook to
    populate ``last_run`` and ``last_status``.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        accessible = await _accessible_workspace_ids(conn, user)

        clauses = ["h.event_type = 'schedule'", "h.action_type = 'call_ai'"]
        params: list[Any] = []
        idx = 1

        if workspace_id is not None:
            # Per-workspace filter still has to respect access.
            await _check_workspace_access(conn, user, workspace_id)
            clauses.append(f"h.workspace_id = ${idx}")
            params.append(workspace_id)
            idx += 1
        elif accessible is not None:
            clauses.append(f"h.workspace_id = ANY(${idx}::int[])")
            params.append(accessible)
            idx += 1

        sql = f"""
            SELECT
                h.*,
                latest.executed_at AS last_run,
                latest.success AS last_success
            FROM public.bh_hooks h
            LEFT JOIN LATERAL (
                SELECT executed_at, success
                FROM public.bh_hook_log
                WHERE hook_id = h.id
                ORDER BY executed_at DESC
                LIMIT 1
            ) latest ON true
            WHERE {' AND '.join(clauses)}
            ORDER BY h.name
        """
        rows = await conn.fetch(sql, *params)

    out: list[dict] = []
    for row in rows:
        d = dict(row)
        last_run = d.pop("last_run", None)
        last_success = d.pop("last_success", None)
        last_status: Optional[str]
        if last_success is None:
            last_status = None
        else:
            last_status = "success" if last_success else "error"
        out.append(_serialize(d, last_run=last_run, last_status=last_status))
    return out


def _validate_create_payload(payload: dict) -> tuple[str, int, str, str, str]:
    """Validate a create payload and return its required fields as a tuple.

    Raises ``InvalidPayload`` for missing/empty fields, ``CronInvalid`` for
    a bad cron expression.
    """
    name = (payload.get("name") or "").strip()
    workspace_id = payload.get("workspace_id")
    prompt_template = payload.get("prompt_template")
    cron_expression = payload.get("cron_expression")
    delivery_method = payload.get("delivery_method")

    if not name:
        raise InvalidPayload("name is required")
    if not isinstance(workspace_id, int):
        raise InvalidPayload("workspace_id must be an int")
    if not isinstance(prompt_template, str) or not prompt_template.strip():
        raise InvalidPayload("prompt_template is required")
    if not isinstance(cron_expression, str) or not cron_expression.strip():
        raise InvalidPayload("cron_expression is required")
    if delivery_method not in ALLOWED_DELIVERY_METHODS:
        raise InvalidPayload(
            f"delivery_method must be one of {sorted(ALLOWED_DELIVERY_METHODS)}"
        )

    if not validate_cron(cron_expression):
        raise CronInvalid(cron_expression)

    return name, workspace_id, prompt_template, cron_expression, delivery_method


async def create(user: dict, payload: dict) -> dict:
    """Create a scheduled-prompt hook row.

    The caller is required to be a member of (or admin over) the target
    workspace. The cron expression is validated up front; ``action_config``
    is built from the payload.

    Note: APScheduler is not woken up here — newly-created hooks are
    picked up on the next ``HookEngine.startup()``. For the MVP this is
    acceptable; a future iteration can call ``hook_engine`` to add the
    job dynamically.
    """
    name, workspace_id, prompt_template, cron_expression, delivery_method = _validate_create_payload(payload)

    action_config = {
        "prompt": prompt_template,
        "model": resolve_role("fast"),
        "delivery_method": delivery_method,
        "workspace_id": workspace_id,
    }

    pool = get_pool()
    async with pool.acquire() as conn:
        await _check_workspace_access(conn, user, workspace_id)

        row = await conn.fetchrow(
            """
            INSERT INTO public.bh_hooks
                (workspace_id, name, description, event_type, action_type,
                 action_config, conditions, cron_expression, is_enabled, created_by)
            VALUES ($1, $2, $3, 'schedule', 'call_ai',
                    $4::jsonb, '{}'::jsonb, $5, true, $6)
            RETURNING *
            """,
            workspace_id,
            name,
            payload.get("description"),
            json.dumps(action_config),
            cron_expression,
            user["id"],
        )

    return _serialize(dict(row), last_run=None, last_status=None)


async def update(user: dict, hook_id: int, partial: dict) -> dict:
    """Update a scheduled-prompt row.

    Only the user-facing fields are accepted here:
    ``name``, ``prompt_template``, ``cron_expression``, ``delivery_method``,
    ``is_enabled``. Cron is re-validated whenever it changes. Other fields
    (``workspace_id``, ``event_type``, ``action_type``) are immutable
    through this surface.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        hook = await _load_hook_or_403(conn, user, hook_id)
        cfg = _coerce_action_config(hook["action_config"])

        updates: list[str] = []
        params: list[Any] = []
        idx = 1

        if "name" in partial:
            name = (partial["name"] or "").strip()
            if not name:
                raise InvalidPayload("name cannot be empty")
            updates.append(f"name = ${idx}")
            params.append(name)
            idx += 1

        if "cron_expression" in partial:
            cron_expression = partial["cron_expression"]
            if not isinstance(cron_expression, str) or not cron_expression.strip():
                raise InvalidPayload("cron_expression cannot be empty")
            if not validate_cron(cron_expression):
                raise CronInvalid(cron_expression)
            updates.append(f"cron_expression = ${idx}")
            params.append(cron_expression)
            idx += 1

        if "is_enabled" in partial:
            updates.append(f"is_enabled = ${idx}")
            params.append(bool(partial["is_enabled"]))
            idx += 1

        # action_config edits — merge in changed fields, keep the rest.
        config_changed = False
        new_cfg = dict(cfg)
        if "prompt_template" in partial:
            prompt = partial["prompt_template"]
            if not isinstance(prompt, str) or not prompt.strip():
                raise InvalidPayload("prompt_template cannot be empty")
            new_cfg["prompt"] = prompt
            config_changed = True
        if "delivery_method" in partial:
            dm = partial["delivery_method"]
            if dm not in ALLOWED_DELIVERY_METHODS:
                raise InvalidPayload(
                    f"delivery_method must be one of {sorted(ALLOWED_DELIVERY_METHODS)}"
                )
            new_cfg["delivery_method"] = dm
            config_changed = True

        if config_changed:
            new_cfg.setdefault("model", resolve_role("fast"))
            new_cfg.setdefault("workspace_id", hook["workspace_id"])
            updates.append(f"action_config = ${idx}::jsonb")
            params.append(json.dumps(new_cfg))
            idx += 1

        if not updates:
            # Nothing to do — return the current state with last-run info.
            return await _serialize_with_last_run(conn, hook)

        params.append(hook_id)
        sql = f"UPDATE public.bh_hooks SET {', '.join(updates)} WHERE id = ${idx} RETURNING *"
        row = await conn.fetchrow(sql, *params)
        return await _serialize_with_last_run(conn, dict(row))


async def _serialize_with_last_run(conn, hook: dict) -> dict:
    """Helper: fetch the latest log row for ``hook`` and serialize."""
    last = await conn.fetchrow(
        """
        SELECT executed_at, success FROM public.bh_hook_log
        WHERE hook_id = $1
        ORDER BY executed_at DESC LIMIT 1
        """,
        hook["id"],
    )
    if last is None:
        return _serialize(hook, last_run=None, last_status=None)
    return _serialize(
        hook,
        last_run=last["executed_at"],
        last_status="success" if last["success"] else "error",
    )


async def delete(user: dict, hook_id: int) -> None:
    """Delete a scheduled-prompt hook.

    The cascading FK on ``bh_hook_log`` removes the log entries with it.
    APScheduler still has the job registered until the next service
    restart; the dispatch path is gated on ``is_enabled`` and a row
    existing, so a stale job tick is a no-op against a missing row.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Enforce access by loading first.
        await _load_hook_or_403(conn, user, hook_id)
        await conn.execute("DELETE FROM public.bh_hooks WHERE id = $1", hook_id)


async def toggle(user: dict, hook_id: int, enabled: bool) -> dict:
    """Set ``is_enabled`` to ``enabled`` for the given hook."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await _load_hook_or_403(conn, user, hook_id)
        row = await conn.fetchrow(
            "UPDATE public.bh_hooks SET is_enabled = $1 WHERE id = $2 RETURNING *",
            bool(enabled),
            hook_id,
        )
        return await _serialize_with_last_run(conn, dict(row))


# ---------------------------------------------------------------------------
# run_now / get_log
# ---------------------------------------------------------------------------


async def run_now(user: dict, hook_id: int, hook_engine: Any) -> dict:
    """Execute a scheduled prompt immediately, outside its cron schedule.

    The execution path is identical to a scheduled fire: we call
    ``hook_engine._execute_hook(hook, context)`` directly. The result is
    written to ``bh_hook_log`` by the engine; we read the latest log row
    afterwards to build the return shape.

    Returns:
        ``{run_id, status, response_snippet?}``

    The design notes a 30-second soft budget for synchronous return; for
    the MVP we ``await`` the call directly and trust the budget. A future
    revision can use ``asyncio.wait_for`` and return 202 on timeout —
    that decision is the caller's, per the task description.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        hook = await _load_hook_or_403(conn, user, hook_id)

    # The hook_engine builds its own HookEventContext (synthetic context)
    # for scheduled hooks via ``_execute_scheduled_hook``. We reuse that
    # path so manual runs go through exactly the same delivery + logging
    # branches as scheduled runs.
    from backend.services.hook_engine import HookEventContext

    context = HookEventContext(
        workspace_id=hook["workspace_id"],
        user_id=user["id"],
    )
    await hook_engine._execute_hook(hook, context)

    # Read back the freshest log entry.
    async with pool.acquire() as conn:
        last = await conn.fetchrow(
            """
            SELECT id, success, action_result, error_message
            FROM public.bh_hook_log
            WHERE hook_id = $1
            ORDER BY executed_at DESC
            LIMIT 1
            """,
            hook_id,
        )

    if last is None:
        # _execute_hook always logs; if we got here the engine swallowed
        # the log call. Return a synthetic status so the caller still
        # gets a structured response.
        return {"run_id": None, "status": "unknown"}

    snippet: Optional[str] = None
    result = last["action_result"]
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = None
    if isinstance(result, dict):
        content = result.get("content") or result.get("body") or ""
        if isinstance(content, str) and content:
            snippet = content[:500]
    if snippet is None and last["error_message"]:
        snippet = str(last["error_message"])[:500]

    out: dict[str, Any] = {
        "run_id": last["id"],
        "status": "success" if last["success"] else "error",
    }
    if snippet:
        out["response_snippet"] = snippet
    return out


async def get_log(user: dict, hook_id: int, limit: int = 10) -> list[dict]:
    """Return the last ``limit`` log entries for a scheduled prompt,
    newest first. ``limit`` is clamped to [1, 100]."""
    limit = max(1, min(100, int(limit)))

    pool = get_pool()
    async with pool.acquire() as conn:
        # Access check (also confirms hook exists and is a scheduled prompt).
        await _load_hook_or_403(conn, user, hook_id)

        rows = await conn.fetch(
            """
            SELECT id, executed_at, success, action_result, error_message
            FROM public.bh_hook_log
            WHERE hook_id = $1
            ORDER BY executed_at DESC
            LIMIT $2
            """,
            hook_id,
            limit,
        )

    out: list[dict] = []
    for r in rows:
        result = r["action_result"]
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = None

        snippet: Optional[str] = None
        if isinstance(result, dict):
            content = result.get("content") or result.get("body") or ""
            if isinstance(content, str) and content:
                snippet = content[:500]

        out.append(
            {
                "id": r["id"],
                "executed_at": r["executed_at"].isoformat() if r["executed_at"] else None,
                "success": bool(r["success"]),
                "response_snippet": snippet,
                "error_message": r["error_message"],
            }
        )
    return out
