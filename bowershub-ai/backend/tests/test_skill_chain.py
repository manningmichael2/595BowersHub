"""L2 skill chaining: multi-source read-only gather + synthesis before L3
(design-review proactivity). Pure unit tests — stubbed model + executor, no DB."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services.router_engine import RouterEngine

pytestmark = pytest.mark.asyncio


class _StubModel:
    """Returns queued completion contents in order; records calls."""
    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = []

    async def complete(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=self._contents.pop(0), input_tokens=10, output_tokens=20)


class _StubExecutor:
    def __init__(self, skills, failing=None):
        self._skills = skills
        self._failing = failing or set()
        self.executed = []

    async def get_workspace_skills(self, workspace_id):
        return self._skills

    async def execute(self, name, params, user_id, workspace_id):
        self.executed.append(name)
        if name in self._failing:
            raise RuntimeError("boom")
        return SimpleNamespace(raw_data={"_display": f"{name}:{params}"})

    def format_response(self, res):
        return res.raw_data["_display"]


def _engine(model, executor):
    eng = RouterEngine(model, executor, SimpleNamespace())
    eng._calculate_cost = lambda *a, **k: 0.0  # avoid catalog dependency
    return eng


def _ctx():
    return SimpleNamespace(user_id=1, workspace_id=1)


def _skills(*names_readonly):
    return [{"name": n, "description": f"{n} desc", "is_read_only": ro}
            for n, ro in names_readonly]


async def test_returns_none_with_fewer_than_two_readonly_skills():
    eng = _engine(_StubModel([]), _StubExecutor([]))
    skills = _skills(("weather", True), ("send-email", False))
    assert await eng._try_skill_chain("hi", _ctx(), skills) is None


async def test_single_source_plan_escalates():
    # Plan picks only one skill → not a chain → None (→ L3 / other layers).
    model = _StubModel([json.dumps({"calls": [{"skill": "weather", "params": {}}]})])
    eng = _engine(model, _StubExecutor(_skills(("weather", True), ("read-email", True))))
    assert await eng._try_skill_chain("what's the weather", _ctx(),
                                      _skills(("weather", True), ("read-email", True))) is None


async def test_multi_source_gathers_and_synthesizes():
    plan = json.dumps({"calls": [
        {"skill": "read-email", "params": {}},
        {"skill": "calendar-read", "params": {}},   # invalid (not in read-only set) → filtered
        {"skill": "weather", "params": {"city": "Detroit"}},
    ]})
    model = _StubModel([plan, "Combined answer from email + weather."])
    ex = _StubExecutor(_skills(("read-email", True), ("weather", True), ("send-email", False)))
    eng = _engine(model, ex)

    res = await eng._try_skill_chain("any flight emails and is it raining?", _ctx(),
                                     _skills(("read-email", True), ("weather", True),
                                             ("send-email", False)))
    assert res is not None
    assert res.layer == "L2" and res.skill_name == "skill_chain"
    assert res.content == "Combined answer from email + weather."
    # Only the two valid read-only skills were executed (invalid filtered out).
    assert ex.executed == ["read-email", "weather"]
    # Both Haiku calls (plan + synth) counted toward tokens.
    assert res.input_tokens == 20 and res.output_tokens == 40


async def test_one_skill_failing_still_synthesizes():
    plan = json.dumps({"calls": [
        {"skill": "read-email", "params": {}},
        {"skill": "weather", "params": {}},
    ]})
    model = _StubModel([plan, "Partial answer."])
    ex = _StubExecutor(_skills(("read-email", True), ("weather", True)), failing={"weather"})
    eng = _engine(model, ex)
    res = await eng._try_skill_chain("emails and weather", _ctx(),
                                     _skills(("read-email", True), ("weather", True)))
    assert res is not None and res.content == "Partial answer."
    assert ex.executed == ["read-email", "weather"]  # both attempted; one failed gracefully


async def test_bad_plan_json_returns_none():
    eng = _engine(_StubModel(["not json at all"]),
                  _StubExecutor(_skills(("read-email", True), ("weather", True))))
    assert await eng._try_skill_chain("x", _ctx(),
                                      _skills(("read-email", True), ("weather", True))) is None
