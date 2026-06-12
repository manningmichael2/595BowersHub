"""
Skill Executor: calls n8n webhooks, enforces permissions, formats responses.
"""

import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from backend.http_client import get_http_client

from backend.config import Config
from backend.database import get_pool

logger = logging.getLogger(__name__)

# C1 stopgap: these skills run LLM-generated SQL against the shared superuser
# connection pool (see services/finance.py:ask_db). Until the least-privilege
# sandbox lands (Phase 1: scoped role + sqlglot + read-only txn), restrict them
# to admins so a non-admin member can't exfiltrate the whole DB via chat.
# TODO(phase-1): replace with a DB-driven per-skill min-role column on bh_skills.
ADMIN_ONLY_SKILLS = {"ask-db", "finance-query"}


class SkillPermissionError(Exception):
    """Raised when a user/workspace doesn't have permission to use a skill."""
    pass


class SkillExecutionError(Exception):
    """Raised when a skill webhook call fails."""
    def __init__(self, skill_name: str, status_code: int = 0, detail: str = ""):
        self.skill_name = skill_name
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Skill '{skill_name}' failed: {status_code} {detail}")


class SkillResult:
    """Result from a skill execution."""
    def __init__(self, skill_name: str, raw_data: Any, response_hint: Optional[str] = None):
        self.skill_name = skill_name
        self.raw_data = raw_data
        self.response_hint = response_hint


class SkillExecutor:
    """
    Calls n8n webhooks and formats responses.
    Enforces workspace + user permission checks before execution.
    """

    def __init__(self, config: Config):
        self.config = config
        self.n8n_base = config.N8N_BASE.rstrip("/")

    async def get_skill(self, skill_name: str) -> Optional[dict]:
        """Load a skill from the database by name."""
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM public.bh_skills WHERE name = $1 AND is_active = true",
                skill_name,
            )
        return dict(row) if row else None

    async def get_workspace_skills(self, workspace_id: int) -> List[dict]:
        """Get all skills assigned to a workspace."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.* FROM public.bh_skills s
                JOIN public.bh_workspace_skills ws ON ws.skill_id = s.id
                WHERE ws.workspace_id = $1 AND s.is_active = true
            """, workspace_id)
        return [dict(r) for r in rows]

    def check_user_permitted(self, skill: dict, user_id: int) -> bool:
        """Check if a user is permitted to use a skill."""
        restricted = skill.get("restricted_users") or []
        if not restricted:
            return True  # Empty = all users allowed
        return user_id in restricted

    async def _user_is_admin(self, user_id: int) -> bool:
        """Return True if the given user has the admin role."""
        pool = get_pool()
        async with pool.acquire() as conn:
            role = await conn.fetchval(
                "SELECT role FROM public.bh_users WHERE id = $1", user_id
            )
        return role == "admin"

    async def check_workspace_permitted(self, skill_id: int, workspace_id: int) -> bool:
        """Check if a skill is assigned to a workspace."""
        pool = get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval("""
                SELECT 1 FROM public.bh_workspace_skills
                WHERE workspace_id = $1 AND skill_id = $2
            """, workspace_id, skill_id)
        return bool(exists)

    async def execute(
        self, skill_name: str, params: Dict[str, Any],
        user_id: int, workspace_id: int,
        bypass_workspace_check: bool = False,
    ) -> SkillResult:
        """
        Execute a skill: permission check → native handler OR webhook call → return result.

        bypass_workspace_check: when True, skip the workspace assignment check
        (for global slash commands). User-level restrictions still apply.
        """
        skill = await self.get_skill(skill_name)
        if not skill:
            raise SkillExecutionError(skill_name, detail="Skill not found")

        # User-level permission check (always enforced)
        if not self.check_user_permitted(skill, user_id):
            raise SkillPermissionError(f"User not permitted to use skill: {skill_name}")

        # Admin-only gate (C1 stopgap) for SQL-executing skills.
        if skill_name in ADMIN_ONLY_SKILLS and not await self._user_is_admin(user_id):
            raise SkillPermissionError(
                f"Skill '{skill_name}' is restricted to administrators"
            )

        # Workspace check (can be bypassed for global slash commands)
        if not bypass_workspace_check:
            if not await self.check_workspace_permitted(skill["id"], workspace_id):
                raise SkillPermissionError(f"Skill '{skill_name}' not available in this workspace")

        # Check for native (in-process Python) skill handler first
        native_result = await self._try_native_skill(skill_name, params, user_id)
        if native_result is not None:
            return native_result

        # Resolve URL
        url = skill["webhook_url"]
        if url.startswith("/"):
            url = f"{self.n8n_base}{url}"

        # Execute webhook
        method = skill["http_method"].upper()
        logger.info(f"Executing skill '{skill_name}': {method} {url}")

        try:
            client = get_http_client()
            if method == "GET":
                response = await client.get(url, timeout=httpx.Timeout(5.0, read=30.0))
            else:
                response = await client.post(url, json=params, timeout=httpx.Timeout(5.0, read=30.0))

            if response.status_code >= 400:
                raise SkillExecutionError(
                    skill_name, response.status_code,
                    f"HTTP {response.status_code}"
                )

            # Parse response. wttr.in (and some n8n webhooks) return content-type
            # text/plain even when the body is JSON, so don't trust the header alone.
            content_type = response.headers.get("content-type", "")
            body_text = response.text
            raw_data: Any
            if "application/json" in content_type:
                raw_data = response.json()
            else:
                stripped = body_text.lstrip()
                looks_like_json = stripped.startswith("{") or stripped.startswith("[")
                if looks_like_json:
                    try:
                        raw_data = response.json()
                    except Exception:
                        raw_data = body_text[:2000]
                else:
                    raw_data = body_text[:2000]

            return SkillResult(
                skill_name=skill_name,
                raw_data=raw_data,
                response_hint=skill.get("response_hint"),
            )

        except httpx.TimeoutException:
            raise SkillExecutionError(skill_name, detail="Request timed out (30s)")
        except httpx.ConnectError:
            raise SkillExecutionError(skill_name, detail="Connection refused")

    async def _try_native_skill(
        self, skill_name: str, params: Dict[str, Any], user_id: Optional[int] = None
    ) -> Optional[SkillResult]:
        """
        Check if a skill has a registered native (in-process Python) handler.
        Returns SkillResult if handled, None if it should fall through to webhook.
        
        Handlers are auto-discovered from backend/services/skills/ at app startup
        via skill_registry.discover_skills(). To add a new native skill:
          1. Create backend/services/skills/<name>.py
          2. Use @native_skill("skill-name") decorator on the handler
          3. Add a bh_skills row with webhook_url = 'native://<skill-name>'
        """
        from backend.services.skill_registry import get_handler

        handler = get_handler(skill_name)
        if handler is None:
            return None  # Not a native skill — fall through to webhook

        # Pass the acting user id under a reserved key so handlers that need it
        # (e.g. weather → per-user default location) can read it; others ignore it.
        result = await handler({**params, "_user_id": user_id})
        return SkillResult(skill_name=skill_name, raw_data=result)

    def format_response(self, result: SkillResult) -> str:
        """Convert raw skill output to human-readable markdown."""
        data = result.raw_data

        if data is None:
            return "No data returned."

        if isinstance(data, str):
            return data

        # Native skills with pre-formatted display — always prefer this
        if isinstance(data, dict) and "_display" in data:
            return data["_display"]

        # Error responses
        if isinstance(data, dict) and "error" in data:
            return f"⚠️ {data['error']}"

        # Special-case wttr.in weather JSON (legacy — old format before native skill)
        if isinstance(data, dict) and "current_condition" in data:
            return self._render_weather(data)

        if isinstance(data, list):
            if not data:
                return "No results found."
            if isinstance(data[0], dict):
                # Recall results: list of {topic, file, lines}
                if all(isinstance(d, dict) and "topic" in d and "lines" in d for d in data):
                    return self._render_recall(data)
                # Special case: single row with a single value (typical of COUNT/SUM queries)
                if len(data) == 1 and len(data[0]) == 1:
                    key, value = next(iter(data[0].items()))
                    display_key = key.replace("_", " ")
                    return f"**{display_key}: {value}**"
                if len(data[0].keys()) > 3:
                    return self._render_table(data)
                else:
                    return self._render_numbered_list(data)
            return "\n".join(f"- {item}" for item in data)

        if isinstance(data, dict):
            if "error" in data:
                return f"⚠️ {data.get('message', data.get('error', 'Something went wrong'))}"
            if "results" in data and isinstance(data["results"], list):
                return self.format_response(SkillResult(
                    skill_name=result.skill_name,
                    raw_data=data["results"],
                    response_hint=result.response_hint,
                ))
            return self._render_key_value(data)

        return str(data)

    def _render_weather(self, data: dict) -> str:
        """Format wttr.in JSON into a readable summary."""
        try:
            current = data["current_condition"][0]
            nearest = data.get("nearest_area", [{}])[0]
            location_parts = []
            for key in ("areaName", "region", "country"):
                vals = nearest.get(key, [])
                if vals and vals[0].get("value"):
                    location_parts.append(vals[0]["value"])
            location = ", ".join(location_parts) if location_parts else "your location"

            temp_f = current.get("temp_F", "?")
            temp_c = current.get("temp_C", "?")
            feels_f = current.get("FeelsLikeF", "?")
            condition = current.get("weatherDesc", [{}])[0].get("value", "")
            humidity = current.get("humidity", "?")
            wind_mph = current.get("windspeedMiles", "?")
            wind_dir = current.get("winddir16Point", "")

            lines = [
                f"**🌤 Weather in {location}**",
                f"- {condition}, **{temp_f}°F** ({temp_c}°C), feels like {feels_f}°F",
                f"- Humidity: {humidity}% • Wind: {wind_mph} mph {wind_dir}",
            ]

            # 3-day forecast
            if "weather" in data and len(data["weather"]) > 0:
                lines.append("\n**Forecast:**")
                for day in data["weather"][:3]:
                    date = day.get("date", "")
                    high = day.get("maxtempF", "?")
                    low = day.get("mintempF", "?")
                    desc = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if day.get("hourly") else ""
                    lines.append(f"- {date}: {desc} • {high}°F / {low}°F")

            return "\n".join(lines)
        except (KeyError, IndexError, TypeError):
            return f"Got weather data but couldn't parse it cleanly. Raw: `{str(data)[:200]}...`"

    def _render_table(self, rows: List[dict]) -> str:
        """Render a list of dicts as a markdown table."""
        if not rows:
            return "No data."

        headers = list(rows[0].keys())
        # Filter out internal fields
        headers = [h for h in headers if not h.startswith("_")]

        lines = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for row in rows[:50]:  # Cap at 50 rows
            values = []
            for h in headers:
                val = row.get(h, "")
                if val is None:
                    val = "—"
                elif isinstance(val, float):
                    if "amount" in h.lower() or "price" in h.lower() or "cost" in h.lower() or "value" in h.lower():
                        val = f"${val:,.2f}"
                    else:
                        val = f"{val:.2f}"
                else:
                    val = str(val)[:50]  # Truncate long values
                values.append(val)
            lines.append("| " + " | ".join(values) + " |")

        if len(rows) > 50:
            lines.append(f"\n*...and {len(rows) - 50} more rows*")

        return "\n".join(lines)

    def _render_recall(self, groups: List[dict]) -> str:
        """Render recall search results: list of {topic, file, lines}.

        Output is grouped by topic with each matching line shown as a bullet.
        Strips the dated-fact prefix `- [YYYY-MM-DD] ` and the markdown header
        line so what's left is the actual content the user wrote.
        """
        if not groups:
            return "No results found."

        out = []
        for g in groups:
            topic = g.get("topic", "")
            lines = g.get("lines", []) or []

            # Filter out the topic header line (e.g. "# cooking / manon-allergies")
            content_lines = []
            for ln in lines:
                text = (ln.get("line") or "").strip()
                if not text or text.startswith("#"):
                    continue
                # Strip the standard remember-skill prefix: "- [YYYY-MM-DD] "
                stripped = re.sub(r"^-\s*\[\d{4}-\d{2}-\d{2}\]\s*", "", text)
                # Or just the leading bullet if there's no date
                stripped = re.sub(r"^-\s+", "", stripped)
                content_lines.append(stripped)

            if not content_lines:
                continue

            out.append(f"**{topic}**")
            for cl in content_lines:
                out.append(f"- {cl}")
            out.append("")  # blank line between topics

        # Strip trailing blank line
        while out and out[-1] == "":
            out.pop()

        if not out:
            return "No results found."
        return "\n".join(out)

    def _render_numbered_list(self, rows: List[dict]) -> str:
        lines = []
        for i, row in enumerate(rows[:30], 1):
            parts = []
            for k, v in row.items():
                if v is None:
                    continue
                # If only one column, just show the value; otherwise label it
                if len(row) == 1:
                    parts.append(str(v))
                else:
                    label = k.replace("_", " ")
                    parts.append(f"{label}: {v}")
            lines.append(f"{i}. {' — '.join(parts)}")
        if len(rows) > 30:
            lines.append(f"*...and {len(rows) - 30} more*")
        return "\n".join(lines)

    def _render_key_value(self, data: dict) -> str:
        """Render a dict as key-value pairs."""
        lines = []
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if value is None:
                continue
            display_key = key.replace("_", " ").title()
            if isinstance(value, float) and ("amount" in key or "price" in key or "cost" in key or "balance" in key):
                lines.append(f"**{display_key}:** ${value:,.2f}")
            elif isinstance(value, dict):
                lines.append(f"**{display_key}:** {', '.join(f'{k}: {v}' for k, v in value.items())}")
            elif isinstance(value, list):
                lines.append(f"**{display_key}:** {len(value)} items")
            else:
                lines.append(f"**{display_key}:** {value}")
        return "\n".join(lines)

    def build_tool_schemas(self, skills: List[dict]) -> List[dict]:
        """Convert skill records to Anthropic tool-use format."""
        import json as json_mod
        tools = []
        for skill in skills:
            schema = skill.get("param_schema") or {}
            # Handle case where asyncpg returns string instead of dict
            if isinstance(schema, str):
                try:
                    schema = json_mod.loads(schema)
                except (json_mod.JSONDecodeError, TypeError):
                    schema = {}
            if not isinstance(schema, dict):
                schema = {}
            # Ensure schema has required structure for Anthropic
            if not schema.get("type"):
                schema = {"type": "object", "properties": {}}
            # Ensure properties key exists
            if "properties" not in schema:
                schema["properties"] = {}
            # Fix nested object properties that lack 'properties' key
            for prop_name, prop_def in schema.get("properties", {}).items():
                if isinstance(prop_def, dict) and prop_def.get("type") == "object":
                    if "properties" not in prop_def:
                        prop_def["properties"] = {}
            tools.append({
                "name": skill["name"],
                "description": skill["description"],
                "input_schema": schema,
            })
        return tools
