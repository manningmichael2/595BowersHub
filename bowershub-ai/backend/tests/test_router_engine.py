"""
Unit tests for the RouterEngine L1/L2/L3 cascade — the product's heart.

project-review.md C5 flagged `router_engine.py` (the actual routing pipeline)
as having ZERO automated tests. This suite covers the *routing decisions* —
which layer handles a message and whether the expensive model is invoked —
with a mocked ModelProvider and SkillExecutor, so it needs no database.

What is covered here (decision logic):
  - force_model bypasses L2 classification and goes straight to L3.
  - High-confidence L2 classification executes the skill (no L3 call).
  - Low/zero-confidence and null-skill classifications escalate to L3.
  - Malformed classifier JSON is swallowed (resilience) and escalates, never raises.
  - The DB-driven read-only threshold (0.65) vs write-path threshold (0.75) split.
  - The borderline (>=0.4) local-refinement (L2.5) path can rescue a skill.
  - SkillPermissionError escalates to L3; SkillExecutionError returns an L2 apology.
  - `_classify` strips markdown fences, returns None on no skills / bad JSON.

Deliberately NOT covered here (need a seeded DB — left as a follow-up):
  L1 slash-command dispatch and regex pattern matching (read `bh_patterns` /
  `bh_slash_commands`), and the full `_layer3_reason` streaming/tool loop.
  Those want the `fresh_db` fixture and a WebSocket TestClient harness.

Validates the routing-decision half of project-review.md C5.
"""

from __future__ import annotations

import json

import pytest

from backend.config import Config
from backend.models.message import CompletionResult
from backend.services import router_engine as router_engine_mod
from backend.services.router_engine import (
    RouterEngine,
    RoutingContext,
    RoutingResult,
)
from backend.services.skill_executor import (
    SkillExecutionError,
    SkillPermissionError,
    SkillResult,
)


# --- Test doubles -----------------------------------------------------------


class FakeProvider:
    """A ModelProvider stand-in that returns pre-programmed completions.

    `responses` is consumed in order; a plain str becomes a CompletionResult.
    Every call is recorded so tests can assert the model was (not) invoked.
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls: list[dict] = []

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        self.calls.append({"model": model, "max_tokens": max_tokens})
        if not self._responses:
            raise AssertionError(
                "FakeProvider.complete called more times than programmed"
            )
        nxt = self._responses.pop(0)
        if isinstance(nxt, str):
            return CompletionResult(
                content=nxt, model=model, input_tokens=11, output_tokens=7
            )
        return nxt


class FakeSkillExecutor:
    """Minimal SkillExecutor: serves a fixed skill list and a canned execute()."""

    def __init__(self, skills=None, exec_result=None, exec_error=None):
        self._skills = skills or []
        self._exec_result = exec_result
        self._exec_error = exec_error
        self.executed: list[tuple[str, dict]] = []

    async def get_workspace_skills(self, workspace_id):
        return [dict(s) for s in self._skills]

    async def execute(self, skill_name, params, user_id, workspace_id):
        self.executed.append((skill_name, params))
        if self._exec_error is not None:
            raise self._exec_error
        if self._exec_result is not None:
            return self._exec_result
        return SkillResult(skill_name, {"value": 1})

    def format_response(self, result):
        if isinstance(result.raw_data, dict) and "_display" in result.raw_data:
            return str(result.raw_data["_display"])
        return str(result.raw_data)

    def build_tool_schemas(self, skills):
        return []


def _classification(skill, confidence, params=None):
    return json.dumps(
        {"skill": skill, "confidence": confidence, "params": params or {}}
    )


def _make_context(**over):
    base = dict(
        user_id=1,
        user_role="member",
        workspace_id=1,
        workspace_name="Home",
        system_prompt="",
        default_model="model-deep",
        max_context_tokens=8000,
        permitted_schemas=["public"],
        conversation_id=0,  # 0 => _classify/route skip all DB history fetches
    )
    base.update(over)
    return RoutingContext(**base)


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def neutralize(monkeypatch):
    """Stub the optional out-of-band collaborators so route() is deterministic
    and DB/network-free: resolve_role -> fixed string, the local-intelligence
    refiner and the Haiku tool-router both -> no-op (return None)."""

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(router_engine_mod, "resolve_role", lambda role: f"model-{role}")

    import backend.services.local_intelligence as li
    import backend.services.tool_router as tr

    monkeypatch.setattr(li, "refine_classification", _none)
    monkeypatch.setattr(tr, "route_with_tools", _none)
    return monkeypatch


class _L3Sentinel:
    """Records whether L3 was reached and returns a recognizable result."""

    def __init__(self):
        self.called = False

    async def __call__(self, message, context, ws_manager):
        self.called = True
        return RoutingResult(layer="L3", content="L3 REASONING", model_used="model-deep")


def _wire(engine, *, l3=None, patterns_match=None):
    """Attach an L3 sentinel and a no-op pattern matcher to an engine instance.

    Pattern matching and L3 reasoning both touch the DB / stream over the WS;
    here we want to assert the *decision* to reach them, not run them.
    """
    sentinel = l3 or _L3Sentinel()
    engine._layer3_reason = sentinel

    async def _patterns(message, context):
        return patterns_match

    engine._try_pattern_match = _patterns
    return sentinel


# --- Layer-selection tests --------------------------------------------------


@pytest.mark.asyncio
async def test_force_model_skips_classification_and_goes_l3(neutralize):
    """When the user pins a model, L2 classification is skipped entirely."""
    provider = FakeProvider([])  # complete() must never be called
    skills = FakeSkillExecutor(
        skills=[{"name": "weather", "description": "w", "is_read_only": True}]
    )
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)

    result = await engine.route(
        "tell me a story", _make_context(force_model="model-deep"), object()
    )

    assert result.layer == "L3"
    assert sentinel.called is True
    assert provider.calls == [], "classifier must not run when a model is forced"


@pytest.mark.asyncio
async def test_force_model_auto_does_not_skip_l2(neutralize):
    """force_model == 'auto' is the sentinel for 'no pin' — L2 still runs."""
    provider = FakeProvider([_classification(None, 0.0)])
    skills = FakeSkillExecutor(skills=[{"name": "weather", "description": "w"}])
    engine = RouterEngine(provider, skills, Config())
    _wire(engine)

    await engine.route("anything", _make_context(force_model="auto"), object())

    assert len(provider.calls) == 1, "'auto' should not bypass classification"


@pytest.mark.asyncio
async def test_high_confidence_read_only_executes_skill_at_l2(neutralize):
    """A confident classification of a read-only skill is handled at L2."""
    provider = FakeProvider(
        [_classification("weather", 0.9), "It is 70 and sunny."]
    )
    skills = FakeSkillExecutor(
        skills=[{"name": "weather", "description": "w", "is_read_only": True}],
        exec_result=SkillResult("weather", {"temp": 70}),
    )
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)
    # Cost lookup hits the catalog/DB; pin it for this unit test.
    engine._calculate_cost = lambda model, i, o: 0.0

    result = await engine.route("what's the weather?", _make_context(), object())

    assert result.layer == "L2"
    assert result.skill_name == "weather"
    assert result.content == "It is 70 and sunny."
    assert ("weather", {}) in skills.executed
    assert sentinel.called is False, "L3 must not run when L2 handled it"


@pytest.mark.asyncio
async def test_low_confidence_escalates_to_l3(neutralize):
    """Below the 0.4 refinement floor, a write-path skill drops through to L3."""
    provider = FakeProvider([_classification("create-thing", 0.3)])
    skills = FakeSkillExecutor(
        skills=[{"name": "create-thing", "description": "w", "is_read_only": False}]
    )
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)

    result = await engine.route("do the thing", _make_context(), object())

    assert result.layer == "L3"
    assert sentinel.called is True
    assert skills.executed == [], "low-confidence skill must not execute"


@pytest.mark.asyncio
async def test_null_skill_classification_escalates_to_l3(neutralize):
    """An explicit {skill: null} means 'no single skill fits' -> escalate."""
    provider = FakeProvider([_classification(None, 0.0)])
    skills = FakeSkillExecutor(skills=[{"name": "weather", "description": "w"}])
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)

    result = await engine.route("explain quantum entanglement", _make_context(), object())

    assert result.layer == "L3"
    assert sentinel.called is True


@pytest.mark.asyncio
async def test_malformed_classifier_json_escalates_without_raising(neutralize):
    """Garbage from the classifier is swallowed; the request still reaches L3."""
    provider = FakeProvider(["not json at all {{{"])
    skills = FakeSkillExecutor(skills=[{"name": "weather", "description": "w"}])
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)

    result = await engine.route("hello there", _make_context(), object())

    assert result.layer == "L3"
    assert sentinel.called is True


# --- The DB-driven read-only vs write-path threshold split ------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_read_only, expected_layer",
    [
        (True, "L2"),   # 0.70 clears the 0.65 read-only threshold -> execute
        (False, "L3"),  # 0.70 misses the 0.75 write-path threshold -> escalate
    ],
)
async def test_read_only_threshold_governs_dispatch(
    neutralize, is_read_only, expected_layer
):
    """is_read_only (a bh_skills column) lowers the dispatch threshold to 0.65.

    The same 0.70 confidence executes a read-only skill but escalates a
    write-path one — the exact DB-driven branch in route()."""
    responses = [_classification("thing", 0.70)]
    if expected_layer == "L2":
        responses.append("formatted output")  # the L2 formatting pass
    provider = FakeProvider(responses)
    skills = FakeSkillExecutor(
        skills=[{"name": "thing", "description": "t", "is_read_only": is_read_only}],
        exec_result=SkillResult("thing", {"k": "v"}),
    )
    engine = RouterEngine(provider, skills, Config())
    engine._calculate_cost = lambda model, i, o: 0.0
    sentinel = _wire(engine)

    result = await engine.route("do thing", _make_context(), object())

    assert result.layer == expected_layer
    assert sentinel.called is (expected_layer == "L3")


@pytest.mark.asyncio
async def test_borderline_confidence_refinement_rescues_skill(neutralize):
    """L2.5: a 0.5 classification is refined locally; if the refiner is
    confident, the skill executes instead of escalating to L3."""

    async def _refine(message, skill, confidence, skills):
        return {"skill": "weather", "confidence": 0.95, "params": {}}

    import backend.services.local_intelligence as li
    neutralize.setattr(li, "refine_classification", _refine)

    provider = FakeProvider([_classification("weather", 0.5), "Sunny, 72."])
    skills = FakeSkillExecutor(
        skills=[{"name": "weather", "description": "w", "is_read_only": True}],
        exec_result=SkillResult("weather", {"temp": 72}),
    )
    engine = RouterEngine(provider, skills, Config())
    engine._calculate_cost = lambda model, i, o: 0.0
    sentinel = _wire(engine)

    result = await engine.route("hows the weather looking", _make_context(), object())

    assert result.layer == "L2"
    assert result.skill_name == "weather"
    assert sentinel.called is False


# --- Skill error handling ---------------------------------------------------


@pytest.mark.asyncio
async def test_permission_error_escalates_to_l3(neutralize):
    """A SkillPermissionError at L2 escalates so L3 can explain the denial."""
    provider = FakeProvider([_classification("admin-skill", 0.95)])
    skills = FakeSkillExecutor(
        skills=[{"name": "admin-skill", "description": "a", "is_read_only": True}],
        exec_error=SkillPermissionError("nope"),
    )
    engine = RouterEngine(provider, skills, Config())
    sentinel = _wire(engine)

    result = await engine.route("run admin skill", _make_context(), object())

    assert result.layer == "L3"
    assert sentinel.called is True


@pytest.mark.asyncio
async def test_execution_error_returns_l2_apology(neutralize):
    """A SkillExecutionError yields a graceful L2 message, not an escalation."""
    provider = FakeProvider([_classification("weather", 0.95)])
    skills = FakeSkillExecutor(
        skills=[{"name": "weather", "description": "w", "is_read_only": True}],
        exec_error=SkillExecutionError("weather", status_code=500, detail="upstream down"),
    )
    engine = RouterEngine(provider, skills, Config())
    engine._calculate_cost = lambda model, i, o: 0.0
    sentinel = _wire(engine)

    result = await engine.route("weather?", _make_context(), object())

    assert result.layer == "L2"
    assert result.skill_name == "weather"
    assert "weather" in result.content
    assert sentinel.called is False


# --- _classify() unit behavior ----------------------------------------------


@pytest.mark.asyncio
async def test_classify_returns_none_with_no_skills(neutralize):
    """No workspace skills => no classifier call at all."""
    provider = FakeProvider([])
    engine = RouterEngine(provider, FakeSkillExecutor(skills=[]), Config())

    out = await engine._classify("anything", _make_context())

    assert out is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_classify_strips_markdown_code_fence(neutralize):
    """Models often wrap JSON in ```json fences — the parser must strip them."""
    fenced = "```json\n" + _classification("weather", 0.8) + "\n```"
    provider = FakeProvider([fenced])
    skills = FakeSkillExecutor(skills=[{"name": "weather", "description": "w"}])
    engine = RouterEngine(provider, skills, Config())

    out = await engine._classify("weather?", _make_context())

    assert out is not None
    assert out["skill"] == "weather"
    assert out["confidence"] == 0.8


@pytest.mark.asyncio
async def test_classify_returns_none_on_bad_json(neutralize):
    """A non-JSON completion yields None rather than raising."""
    provider = FakeProvider(["definitely not json"])
    skills = FakeSkillExecutor(skills=[{"name": "weather", "description": "w"}])
    engine = RouterEngine(provider, skills, Config())

    out = await engine._classify("weather?", _make_context())

    assert out is None
