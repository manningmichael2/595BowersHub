"""
DB-backed tests for the RouterEngine Layer 1 (deterministic) path.

project-review.md C5 flagged the router's core as untested. The companion
`test_router_engine.py` covers the L2/L3 *decision* logic with mocks; this
suite exercises L1 — slash-command dispatch and regex pattern matching —
against a real Postgres schema (built from the squashed baseline) with the
seeded `bh_slash_commands` / `bh_skills` / `bh_patterns` rows.

L1 must never touch the model provider, so a NoCallProvider asserts that
invariant. The SkillExecutor is replaced with a recording double so we test
the router's DB query + parameter templating + dispatch decision *without*
making real n8n webhook / native-skill calls.

Validates the L1 half of project-review.md C5.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations
from backend.services.router_engine import RouterEngine, RoutingContext
from backend.services.skill_executor import SkillResult

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )


class NoCallProvider:
    """A ModelProvider that fails loudly if L1 ever escalates to a model call."""

    async def complete(self, *args, **kwargs):  # noqa: D401
        raise AssertionError("Layer 1 must not invoke the model provider")


class RecordingSkillExecutor:
    """Records skill dispatches instead of hitting n8n / native skills."""

    def __init__(self):
        self.calls: list[dict] = []

    async def get_workspace_skills(self, workspace_id):
        return []

    async def execute(
        self, skill_name, params, user_id, workspace_id, bypass_workspace_check=False
    ):
        self.calls.append(
            {
                "skill": skill_name,
                "params": dict(params),
                "bypass": bypass_workspace_check,
            }
        )
        return SkillResult(skill_name, {"ok": True})

    def format_response(self, result):
        return f"[{result.skill_name} ran]"


def _context(**over):
    base = dict(
        user_id=1,
        user_role="member",
        workspace_id=1,  # 'General', seeded by the baseline
        workspace_name="General",
        system_prompt="",
        default_model="model-deep",
        max_context_tokens=8000,
        permitted_schemas=["public"],
        conversation_id=0,
    )
    base.update(over)
    return RoutingContext(**base)


@pytest_asyncio.fixture
async def l1(fresh_db, db_settings):
    """Schema-loaded engine: real DB pool + NoCallProvider + recording executor."""
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    skills = RecordingSkillExecutor()
    engine = RouterEngine(NoCallProvider(), skills, config)
    try:
        yield engine, skills
    finally:
        await close_pool()


# --- Builtin slash commands -------------------------------------------------


async def test_help_lists_seeded_commands(l1):
    """/help is a builtin that reads bh_slash_commands and lists them."""
    engine, _ = l1
    result = await engine.route("/help", _context(), object())

    assert result.layer == "L1"
    # The baseline seeds /help and /new globally — both must appear.
    assert "/help" in result.content
    assert "/new" in result.content


async def test_new_command_starts_conversation(l1):
    engine, _ = l1
    result = await engine.route("/new", _context(), object())

    assert result.layer == "L1"
    assert "new conversation" in result.content.lower()


async def test_unknown_command_is_reported(l1):
    """An unseeded /command returns a helpful L1 message, not an error/escalation."""
    engine, _ = l1
    result = await engine.route("/definitelynotacommand", _context(), object())

    assert result.layer == "L1"
    assert "Unknown command" in result.content


# --- Skill-backed slash command + $args templating --------------------------


async def test_remember_command_templates_args(l1):
    """/remember maps to a skill with a {topic: $args_first, fact: $args_rest}
    template (seeded row). Verify the router splits the args and dispatches."""
    engine, skills = l1
    result = await engine.route(
        "/remember finance/accounts opened a new savings account", _context(), object()
    )

    assert result.layer == "L1"
    assert result.skill_name == "remember"
    assert len(skills.calls) == 1
    call = skills.calls[0]
    assert call["skill"] == "remember"
    assert call["params"]["topic"] == "finance/accounts"
    assert call["params"]["fact"] == "opened a new savings account"
    # /remember is a global command (workspace_id IS NULL) -> bypass workspace check.
    assert call["bypass"] is True


# --- Regex pattern matching (Layer 1, non-slash) ----------------------------


async def test_pattern_match_extracts_capture_group(l1):
    """A bh_patterns row with a $1 template extracts the regex capture group
    and dispatches the bound skill — the non-slash L1 path."""
    engine, skills = l1

    # Seed a high-priority, unambiguous pattern bound to the 'weather' skill (id 15).
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_patterns
                (id, rule, rule_type, skill_id, param_template, priority, workspace_id, is_active)
            VALUES (99001, $1, 'regex', 15, $2::jsonb, 1, NULL, true)
            """,
            r"^weatherbot (.+)$",
            '{"location": "$1"}',
        )

    result = await engine.route("weatherbot Detroit", _context(), object())

    assert result.layer == "L1"
    assert result.skill_name == "weather"
    assert len(skills.calls) == 1
    assert skills.calls[0]["params"]["location"] == "Detroit"


async def test_non_matching_message_is_not_l1(l1):
    """A plain message that matches no slash/pattern falls through L1 (returns
    None internally) — here we assert L1 dispatch did NOT fire a skill."""
    engine, skills = l1

    # No pattern seeded that matches this; _try_pattern_match returns None.
    # Force a model call would happen at L2, but we stop before that by checking
    # the deterministic layers produced nothing.
    slash = await engine._try_slash_command("hello there", _context()) \
        if "hello there".startswith("/") else None
    pattern = await engine._try_pattern_match("hello there", _context())

    assert slash is None
    assert pattern is None
    assert skills.calls == []
