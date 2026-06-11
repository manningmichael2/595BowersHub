"""Tests for the model-discovery seam (spec: dynamic-model-discovery, Task 3).

No network: AnthropicDiscoverySource is driven by a fake async SDK client, and a
FakeDiscoverySource stands in for the CatalogRefresh tests (Task 4). These exercise
R2.1 (discover), R1.3 (real caps), R1.5 (chat-target filter), R2.4 (cold-start seed),
and R2.6 (injectability)."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.services.model_catalog import (
    AnthropicDiscoverySource,
    DiscoveredModel,
    DiscoveryResult,
    DiscoverySource,
    OllamaDiscoverySource,
    StaticDiscoverySource,
    is_chat_target,
)


# --- fakes -----------------------------------------------------------------
def _cap(supported: bool):
    return SimpleNamespace(supported=supported)


def _model(model_id, display_name="X", ctx=200000, out=64000,
           vision=True, thinking=True, effort=True, structured=True):
    """A fake anthropic SDK ModelInfo-ish object."""
    return SimpleNamespace(
        id=model_id, display_name=display_name,
        max_input_tokens=ctx, max_tokens=out,
        capabilities=SimpleNamespace(
            image_input=_cap(vision), thinking=_cap(thinking),
            effort=_cap(effort), structured_outputs=_cap(structured),
        ),
    )


class _FakeModelsPage:
    """Async-iterable mimicking client.models.list()'s auto-paginating result."""
    def __init__(self, models, raise_after=None):
        self._models = models
        self._raise_after = raise_after

    def __aiter__(self):
        async def gen():
            for i, m in enumerate(self._models):
                if self._raise_after is not None and i == self._raise_after:
                    raise RuntimeError("simulated mid-page network drop")
                yield m
        return gen()


class _FakeAnthropic:
    def __init__(self, models, raise_after=None):
        self.models = SimpleNamespace(
            list=lambda **kw: _FakeModelsPage(models, raise_after)
        )


class FakeDiscoverySource:
    """Injectable test source (R2.6). Optionally gates `discover()` on an asyncio.Event
    so Task 4 can prove single-flight serialization by holding one refresh open."""
    def __init__(self, provider, models, complete=True, gate: asyncio.Event = None):
        self.provider = provider
        self._models = models
        self._complete = complete
        self.gate = gate
        self.calls = 0

    async def discover(self) -> DiscoveryResult:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return DiscoveryResult(models=list(self._models), complete=self._complete)


# --- is_chat_target (R1.5) -------------------------------------------------
def test_chat_target_keeps_claude_drops_non_claude():
    assert is_chat_target("claude-sonnet-4-6", None) is True
    assert is_chat_target("text-embedding-3", None) is False
    assert is_chat_target("llama3.2:3b", None) is False


def test_chat_target_drops_explicit_non_structured():
    caps = SimpleNamespace(structured_outputs=_cap(False))
    assert is_chat_target("claude-embed-x", caps) is False


def test_chat_target_keeps_when_caps_unknown():
    # defensive: missing structured_outputs leaf must not drop a claude model
    assert is_chat_target("claude-future", SimpleNamespace()) is True


# --- AnthropicDiscoverySource (R2.1, R1.3) ---------------------------------
@pytest.mark.asyncio
async def test_anthropic_discovery_maps_real_fields():
    src = AnthropicDiscoverySource(_FakeAnthropic([
        _model("claude-sonnet-4-6", "Claude Sonnet 4.6", ctx=1000000, out=64000),
        _model("claude-haiku-4-5-20251001", "Claude Haiku 4.5", ctx=200000),
    ]))
    res = await src.discover()
    assert res.complete is True
    assert isinstance(src, DiscoverySource)        # satisfies the Protocol
    by_id = {m.id: m for m in res.models}
    assert by_id["claude-sonnet-4-6"].max_input_tokens == 1000000
    assert by_id["claude-sonnet-4-6"].max_output_tokens == 64000
    assert by_id["claude-haiku-4-5-20251001"].supports_thinking is True
    assert by_id["claude-sonnet-4-6"].supports_structured_outputs is True
    # no price attribute exists on DiscoveredModel (pricing is operator-owned)
    assert not hasattr(by_id["claude-sonnet-4-6"], "input_cost_per_mtok")


@pytest.mark.asyncio
async def test_anthropic_discovery_filters_non_chat_targets():
    src = AnthropicDiscoverySource(_FakeAnthropic([
        _model("claude-sonnet-4-6"),
        _model("claude-embed-1", structured=False),   # explicit non-structured → dropped
        _model("text-embedding-x"),                    # non-claude → dropped
    ]))
    res = await src.discover()
    assert {m.id for m in res.models} == {"claude-sonnet-4-6"}


@pytest.mark.asyncio
async def test_anthropic_discovery_partial_page_is_incomplete():
    # a mid-iteration error must yield complete=False (so refresh deactivates nothing)
    src = AnthropicDiscoverySource(_FakeAnthropic(
        [_model("claude-sonnet-4-6"), _model("claude-haiku-4-5-20251001")],
        raise_after=1,
    ))
    res = await src.discover()
    assert res.complete is False
    assert {m.id for m in res.models} == {"claude-sonnet-4-6"}   # only the first survived


# --- OllamaDiscoverySource (R2.4 degradation) ------------------------------
@pytest.mark.asyncio
async def test_ollama_discovery_unreachable_is_incomplete():
    # nothing listening on this port → graceful complete=False, no raise
    src = OllamaDiscoverySource("http://127.0.0.1:1")
    res = await src.discover()
    assert res.complete is False and res.models == []


# --- StaticDiscoverySource (R2.4) + cold-start coherence -------------------
@pytest.mark.asyncio
async def test_static_seed_is_incomplete_and_matches_alias_ids():
    res = await StaticDiscoverySource().discover()
    assert res.complete is False                       # can seed, never deactivate
    seed_ids = {m.id for m in res.models}
    # MUST equal the 0005 alias-seed model_ids (canonical, T0 decision) so a
    # cold-start catalog built from this seed lets resolve_role succeed.
    assert seed_ids == {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-opus-4-5-20251101",
        "llama3.2:3b",
    }


# --- FakeDiscoverySource is a valid DiscoverySource (R2.6) ------------------
@pytest.mark.asyncio
async def test_fake_source_satisfies_protocol_and_gate():
    gate = asyncio.Event()
    fake = FakeDiscoverySource("anthropic", [DiscoveredModel("claude-x", "anthropic", "X")], gate=gate)
    assert isinstance(fake, DiscoverySource)
    task = asyncio.create_task(fake.discover())
    await asyncio.sleep(0)            # let it reach the gate
    assert not task.done()           # blocked until released (used by Task 4 single-flight test)
    gate.set()
    res = await task
    assert res.complete is True and res.models[0].id == "claude-x"
